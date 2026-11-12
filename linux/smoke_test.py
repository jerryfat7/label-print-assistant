"""Real HTTP/SDK checks; never submit a print job when a printer is present."""
import argparse
import base64
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def request(base, path, data=None, expected=200):
    body = json.dumps(data).encode() if data is not None else None
    req = Request(base + path, data=body, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=30) as response:
            status, output = response.status, response.read()
    except HTTPError as error:
        status, output = error.code, error.read()
    if status != expected:
        raise AssertionError(f"{path}: HTTP {status}, {output[:300]!r}")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main-url", default="http://127.0.0.1:4050")
    parser.add_argument("--custom-url", default="http://127.0.0.1:4051")
    parser.add_argument("--output-dir", default="./smoke-output")
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    main_url, custom_url = args.main_url, args.custom_url
    checks = []

    def checked(name):
        checks.append(name)
        print("PASS", name)

    request(main_url, "/api/health")
    request(main_url, "/static/index.html")
    request(custom_url, "/health")
    checked("both ports and static page")
    readiness = json.loads(request(main_url, "/api/readiness"))
    assert readiness["ready"], readiness
    devices = json.loads(request(main_url, "/api/printers"))
    assert "error" not in devices, devices
    request(custom_url, "/printers")
    checked("real dtpweb connection and printer enumeration")
    parsed = json.loads(request(main_url, "/api/address/parse", {
        "text": "张三 13800000000 上海市黄浦区测试路1号"}))
    assert parsed["items"][0]["address"] == "上海市黄浦区", parsed
    checked("Chinese address parsing")
    for path in ["/api/address/template/default", "/api/inventory-label/template/box/default",
                 "/api/inventory-label/template/product/default"]:
        template = json.loads(request(main_url, path))["template"]
        assert (template["labelWidth"], template["labelHeight"]) == (40, 30)
    checked("40 x 30 mm templates")

    previews = [
        (main_url, "/api/address/preview", "address", {
            "name": "中文测试", "phone": "13800000000", "address": "上海市黄浦区"}),
        (main_url, "/api/inventory-label/preview", "box", {
            "name": "收纳箱 A", "address": "中文库存标签", "labelType": "box"}),
        (main_url, "/api/inventory-label/preview", "product", {
            "name": "商品测试", "phone": "SKU-001", "address": "规格：40×30", "labelType": "product"}),
        (custom_url, "/preview", "custom", {"job": {"width": 40, "height": 30}, "pages": [[
            {"type": "text", "text": "德佟 P1 中文测试", "x": 1, "y": 1, "width": 38, "height": 6, "fontHeight": 4},
            {"type": "qrcode", "text": "P1-LINUX-TEST", "x": 2, "y": 10, "width": 16, "height": 16},
            {"type": "barcode", "text": "12345678", "x": 20, "y": 12, "width": 18, "height": 10}
        ]]})
    ]
    for base, path, name, payload in previews:
        result = json.loads(request(base, path, payload))
        image = result.get("image", "")
        if not image:
            raise AssertionError(f"{name}: preview returned empty image")
        image_bytes = base64.b64decode(image.split(",", 1)[-1])
        assert image_bytes.startswith(b"\x89PNG\r\n\x1a\n"), name
        (output / f"{name}.png").write_bytes(image_bytes)
        checked(name + " preview PNG")

    request(main_url, "/api/address/print/not-a-task/status", expected=404)
    request(custom_url, "/print/not-a-task/cancel", {}, expected=404)
    request(main_url, "/api/address/print", {
        "items": [{"name": "invalid"}], "printerName": "invalid", "copies": 0}, expected=422)
    checked("invalid task and copies handling")

    if not devices["printers"]:
        submissions = [
            (main_url, "/api/address/print", "/api/address/print", {
                "items": [{"name": "软件测试"}], "printerName": "__missing_printer__"}),
            (main_url, "/api/inventory-label/print", "/api/inventory-label/print", {
                "items": [{"name": "软件测试"}], "printerName": "__missing_printer__"}),
            (custom_url, "/print", "/print", {
                "printerName": "__missing_printer__", "pages": [[{"type": "text", "text": "software test"}]]}),
        ]
        for base, path, prefix, payload in submissions:
            task = json.loads(request(base, path, payload))
            raw = request(base, prefix + "/" + task["taskId"] + "/status").decode()
            events = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: ")]
            assert any(e["status"] == "error" for e in events), events
            assert events[-1]["status"] == "finished", events
            assert events[-1]["current"] == 0, events
            assert request(base, prefix + "/" + task["taskId"] + "/status").decode() == raw
        checked("all three print routes: absent-printer failure, terminal SSE and replay")
    else:
        print("SKIP print submission checks: a physical printer is present")

    report = {"checks": checks, "readiness": readiness, "printers": devices["printers"],
              "physicalPrintTested": False}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Software checks complete; physical output has NOT been tested.")


if __name__ == "__main__":
    main()
