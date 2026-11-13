"""No physical printer or running helper is used by these regression tests."""
import asyncio
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from webapp import address_routes, custom_print_routes, inventory_routes
from webapp import label_service, printer_service, task_service
from webapp.main import app
from webapp.custom_print_app import create_custom_app
from webapp.settings import Settings, load_settings


async def request(application, path, method="GET", data=None, headers=None):
    sent = []
    body = json.dumps(data).encode() if data is not None else b""
    received = False

    async def receive():
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.sleep(60)

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
             "query_string": b"", "root_path": "", "headers": [(b"content-type", b"application/json")] + (headers or []),
             "server": ("test", 4050), "client": ("127.0.0.1", 1)}
    await application(scope, receive, send)
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    output = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, output


def collect(task_id):
    async def read():
        response = task_service.stream(task_id)
        return [json.loads(chunk.removeprefix("data: ").strip())
                async for chunk in response.body_iterator if chunk.startswith("data: ")]
    return asyncio.run(asyncio.wait_for(read(), timeout=5))


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.api = MagicMock()
        self.api.check_port.return_value = True
        self.api.check_plugin.return_value = True
        self.api.open_printer.return_value = True
        self.api.start_job.return_value = True
        self.api.commit_job.return_value = True
        self.api.get_printers.return_value = []
        self.api.is_printer_opened.return_value = False
        self.api.get_printer_name.return_value = ""
        self.api.print.return_value = {"previewData": ["data:image/png;base64,AA=="]}
        self.api.get_port.return_value = 15216
        self.saved = (printer_service._api, printer_service._initialized)
        printer_service._api = self.api
        printer_service._initialized = False

    def tearDown(self):
        printer_service._api, printer_service._initialized = self.saved

    def test_routes_and_validation(self):
        for application, path in [(app, "/api/health"), (app, "/static/index.html"),
                                  (create_custom_app(), "/health")]:
            self.assertEqual(asyncio.run(request(application, path))[0], 200)
        status, _ = asyncio.run(request(app, "/api/address/print", "POST",
                                       {"items": [{}], "printerName": "P1", "copies": 0}))
        self.assertEqual(status, 422)
        secured = create_custom_app("test-token")
        self.assertEqual(asyncio.run(request(secured, "/health"))[0], 401)
        self.assertEqual(asyncio.run(request(secured, "/health", headers=[
            (b"x-api-token", b"test-token")]))[0], 200)

    def test_helper_failure_does_not_poison_initialization(self):
        self.api.check_plugin.return_value = False
        with self.assertRaises(RuntimeError):
            printer_service.get_printers()
        self.assertFalse(printer_service._initialized)
        self.api.check_plugin.return_value = True
        self.assertEqual(printer_service.get_printers(), [])
        self.assertTrue(printer_service._initialized)

    def test_sdk_transport_timeout_is_seconds(self):
        with patch.object(printer_service, "_vendor_http_request") as transport:
            printer_service._bounded_request(url="/local/ServerInfo", timeout=5000)
            self.assertEqual(transport.call_args.kwargs["timeout"], 10.0)

    def test_no_printer_is_distinct_from_helper_readiness(self):
        status, body = asyncio.run(request(app, "/api/readiness"))
        state = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(state["ready"])
        self.assertFalse(state["printReady"])

    def test_missing_printer_reports_error_and_terminates_stream(self):
        self.api.open_printer.return_value = False
        response = asyncio.run(address_routes.start_print(address_routes.PrintRequest(
            items=[{"name": "test"}], printerName="missing")))
        events = collect(response["taskId"])
        self.assertEqual([e["status"] for e in events], ["error", "finished"])
        self.api.commit_job.assert_not_called()
        self.assertEqual(collect(response["taskId"]), events)  # SSE reconnect/replay

    def test_both_ports_share_fifo_and_queued_cancel_is_preserved(self):
        started, release = threading.Event(), threading.Event()
        order = []

        def blocked(*_, on_progress):
            started.set()
            release.wait(3)
            on_progress(1, 1, "finished")

        first = task_service.submit(blocked, 1)
        self.assertTrue(started.wait(1))
        try:
            address = asyncio.run(address_routes.start_print(address_routes.PrintRequest(
                items=[{"name": "address"}], printerName="P1")))
            custom = asyncio.run(custom_print_routes.start_print(custom_print_routes.PrintRequest(
                printerName="P1", pages=[[{"type": "text", "text": "custom"}]])))
            task_service.cancel(address["taskId"])
            self.api.draw_text.side_effect = lambda text, **kw: order.append(text)
        finally:
            release.set()
        collect(first)
        self.assertEqual(collect(address["taskId"])[-1]["status"], "cancelled")
        self.assertEqual(collect(custom["taskId"])[-1]["status"], "finished")
        self.assertEqual(order, ["custom"])

    def test_failed_drawing_closes_printer(self):
        self.api.draw_text.side_effect = RuntimeError("draw failure")
        response = asyncio.run(inventory_routes.start_print(inventory_routes.PrintRequest(
            items=[inventory_routes.PrintItem(name="box")], labelType="box", printerName="P1")))
        events = collect(response["taskId"])
        self.assertIn("error", [item["status"] for item in events])
        self.api.close_printer.assert_called_once()
        self.api.commit_job.assert_not_called()

    def test_preview_cannot_interleave_an_active_print(self):
        entered, release, preview_done = threading.Event(), threading.Event(), threading.Event()

        def draw(*_, **__):
            entered.set()
            release.wait(3)
        self.api.draw_text.side_effect = draw
        response = asyncio.run(address_routes.start_print(address_routes.PrintRequest(
            items=[{"name": "job"}], printerName="P1")))
        self.assertTrue(entered.wait(1))
        thread = threading.Thread(target=lambda: (
            label_service.generate_preview("预览", "", ""), preview_done.set()))
        thread.start()
        try:
            self.assertFalse(preview_done.wait(0.1))
        finally:
            release.set()
        collect(response["taskId"])
        thread.join(3)
        self.assertTrue(preview_done.is_set())

    def test_unknown_task_is_not_created_by_read_or_cancel(self):
        for operation in (task_service.stream, task_service.cancel):
            with self.assertRaises(HTTPException) as caught:
                operation("does-not-exist")
            self.assertEqual(caught.exception.status_code, 404)

    def test_unplugged_preview_omits_empty_printer_name_and_sets_resolution(self):
        self.api.get_font_name.return_value = "Droid Sans Fallback"
        label_service.generate_preview("中文测试", "", "")
        options = self.api.print.call_args.kwargs
        self.assertNotIn("printerName", options["printerInfo"])
        self.assertEqual(options["printerInfo"]["printerDPI"], 203)
        self.assertEqual(options["jobPages"][0][0]["fontName"], "Droid Sans Fallback")
        self.api.print.return_value = None
        with self.assertRaisesRegex(RuntimeError, "未生成预览"):
            label_service.generate_preview("中文测试", "", "")

    def test_config_paths_and_port_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            config.write_text('{"log_dir":"logs","port":14050,"custom_port":14051}', encoding="utf-8")
            settings = load_settings(str(config))
            self.assertEqual(settings.log_dir, str((Path(directory) / "logs").resolve()))
        with self.assertRaises(ValueError):
            Settings(port=4050, custom_port=4050)

    def test_product_preview_and_print_share_elements_without_phone_icon_or_empty_title(self):
        template = label_service.build_template(None, "product")
        elements = label_service._label_elements("商品", "SKU-001", "规格", template)
        self.assertEqual([item["text"] for item in elements], ["商品", "SKU-001", "规格"])
        label_service._draw_label(self.api, "商品", "SKU-001", "规格", template)
        self.assertEqual([c.kwargs["text"] for c in self.api.draw_text.call_args_list],
                         [item["text"] for item in elements])

    def test_running_job_cancels_between_copies(self):
        entered, release = threading.Event(), threading.Event()
        def commit(**kwargs):
            entered.set()
            release.wait(3)
            return True
        self.api.commit_job.side_effect = commit
        response = asyncio.run(address_routes.start_print(address_routes.PrintRequest(
            items=[{"name": "one"}], printerName="P1", copies=3)))
        self.assertTrue(entered.wait(1))
        try:
            task_service.cancel(response["taskId"])
        finally:
            release.set()
        self.assertEqual(collect(response["taskId"])[-1]["status"], "cancelled")
        self.api.commit_job.assert_called_once()
        self.api.close_printer.assert_called_once()

    def test_fifo_jobs_do_not_overlap(self):
        order = []
        def work(task_id, label, on_progress):
            order.append(label + "-start")
            time.sleep(0.02)
            order.append(label + "-end")
            on_progress(1, 1, "finished")
        first = task_service.submit(work, 1, "one")
        second = task_service.submit(work, 1, "two")
        collect(first)
        collect(second)
        self.assertEqual(order, ["one-start", "one-end", "two-start", "two-end"])

    def test_second_port_conflict_does_not_leave_main_port_running(self):
        with tempfile.TemporaryDirectory() as directory, socket.socket() as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen()
            with socket.socket() as reserve:
                reserve.bind(("127.0.0.1", 0))
                main_port = reserve.getsockname()[1]
            config = Path(directory) / "settings.json"
            config.write_text(json.dumps({"port": main_port, "custom_port": busy.getsockname()[1],
                                          "log_dir": str(Path(directory) / "logs")}), encoding="utf-8")
            result = subprocess.run([sys.executable, "-m", "webapp.server", "--config", str(config)],
                                    cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 1, result.stderr.decode(errors="replace"))
            with socket.socket() as probe:
                self.assertNotEqual(probe.connect_ex(("127.0.0.1", main_port)), 0)

    def test_connected_linux_dpi_response_is_numeric_in_info_and_preview(self):
        self.api.is_printer_opened.return_value = True
        self.api.get_printer_name.return_value = "test-printer"
        self.api.get_printer_dpi.return_value = {
            "statusCode": 0, "resultInfo": {"dpiX": 203, "dpiY": 203}}
        self.api.get_print_darkness.return_value = 5
        self.api.get_print_speed.return_value = 2
        self.api.get_gap_type.return_value = 2
        self.assertEqual(printer_service.get_printer_info()["dpi"], 203)
        label_service.generate_preview("连接测试", "", "")
        self.assertEqual(self.api.print.call_args.kwargs["printerInfo"]["printerDPI"], 203)

    def test_dpi_normalization_accepts_windows_number_and_rejects_errors(self):
        cases = [(300, 300), ({"dpiX": 203, "dpiY": 203}, 203),
                 ({"statusCode": 21, "resultInfo": "not opened"}, 0),
                 (None, 0), (False, 0), (float("nan"), 0), (-1, 0)]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(printer_service._dpi_value(value), expected)

    def test_unnamed_device_does_not_claim_print_readiness(self):
        self.api.get_printers.return_value = [{"name": "", "type": 9}]
        status, body = asyncio.run(request(app, "/api/readiness"))
        state = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(state["ready"])
        self.assertFalse(state["printReady"])
        self.assertIn("deviceAccessWarning", state)


if __name__ == "__main__":
    unittest.main()
