"""Headless, single-process dual-port runner. python -m webapp.server --config ..."""
import argparse
import asyncio
from contextlib import contextmanager, ExitStack
import io
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
from urllib.request import urlopen

import uvicorn

from . import printer_service, task_service
from .settings import load_settings

log = logging.getLogger("label-server")


class SDKOutput(io.TextIOBase):
    """The vendor wheel prints request bodies and base64 previews to stdout."""
    def write(self, text):
        if text.strip():
            logging.getLogger("dtpweb").debug("%s", text.strip()[:500])
        return len(text)

    def flush(self):
        pass


class Server(uvicorn.Server):
    @contextmanager
    def capture_signals(self):
        # The runner owns the signal handlers for both servers.
        yield


class Helper:
    def __init__(self, settings):
        self.settings = settings
        self.process = None
        self.output = logging.getLogger("label-helper")
        self.output.propagate = False
        self.output.setLevel(logging.INFO)
        handler = RotatingFileHandler(Path(settings.log_dir) / "helper.log",
                                      maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8")
        self.output.addHandler(handler)
        self.reader = None
        self.last_attempt = 0
        self.last_check = 0

    def available(self):
        ports = [self.settings.sdk_port] if self.settings.sdk_port else [15216, 35216]
        for port in ports:
            try:
                with urlopen(f"http://{self.settings.sdk_host}:{port}/local/ServerInfo", timeout=2) as response:
                    info = json.load(response)
                if info.get("statusCode") == 0:
                    return True
            except Exception:
                pass
        return False

    def ensure(self):
        if not self.settings.helper_executable:
            return
        if time.monotonic() - self.last_check < 3:
            return
        self.last_check = time.monotonic()
        if self.available():
            return
        if self.process and self.process.poll() is None:
            return
        if time.monotonic() - self.last_attempt < 5:
            return
        self.last_attempt = time.monotonic()
        if self.settings.sdk_host not in ("127.0.0.1", "localhost"):
            raise ValueError("Managed helper requires a local sdk_host")
        env = os.environ.copy()
        if self.settings.helper_lib_dir:
            env["LD_LIBRARY_PATH"] = self.settings.helper_lib_dir + os.pathsep + env.get("LD_LIBRARY_PATH", "")
        self.process = subprocess.Popen(
            [self.settings.helper_executable], env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        process = self.process

        def drain():
            with process.stdout:
                while chunk := process.stdout.readline(8192):
                    self.output.info("%s", chunk.decode("utf-8", errors="replace").rstrip())

        self.reader = threading.Thread(target=drain, name="dtpweb-log", daemon=True)
        self.reader.start()
        log.info("Started managed dtpweb pid=%s", self.process.pid)

    def stop(self):
        # Only stop a helper started by this runner; never kill a preexisting helper.
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.reader:
            self.reader.join(timeout=2)
        for handler in self.output.handlers[:]:
            handler.close()
            self.output.removeHandler(handler)


async def serve(settings, stop):
    from .main import app
    from .custom_print_app import create_custom_app

    pairs = [(app, settings.port)]
    if settings.custom_port:
        pairs.append((create_custom_app(settings.custom_token), settings.custom_port))
    helper = Helper(settings)
    servers = []
    running = []
    with ExitStack() as stack:
        try:
            # Reserve all ports before starting anything; a conflict cannot leave half a service.
            sockets = [stack.enter_context(socket.create_server((settings.host, port)))
                       for _, port in pairs]
            for sock in sockets:
                sock.setblocking(False)
            await asyncio.to_thread(helper.ensure)
            for (application, _), sock in zip(pairs, sockets):
                server = Server(uvicorn.Config(application, log_level=settings.log_level,
                                               log_config=None, access_log=False))
                servers.append(server)
                running.append(asyncio.create_task(server.serve(sockets=[sock])))
            while not stop.is_set() and not any(task.done() for task in running):
                await asyncio.to_thread(helper.ensure)
                await asyncio.sleep(0.5)
            if not stop.is_set():
                raise RuntimeError("An HTTP server stopped unexpectedly")
        finally:
            for server in servers:
                server.should_exit = True
            # Mark queued/running jobs cancelled before waiting for HTTP shutdown.
            await asyncio.to_thread(task_service.shutdown)
            if running:
                await asyncio.gather(*running, return_exceptions=True)
            helper.stop()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="JSON settings file; relative paths resolve beside it")
    args = parser.parse_args()
    settings = load_settings(args.config)
    Path(settings.log_dir).mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(Path(settings.log_dir) / "service.log",
                                 maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    logging.basicConfig(level=settings.log_level.upper(),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s",
                        handlers=[handler, logging.StreamHandler()])
    sys.stdout = SDKOutput()
    printer_service.configure(settings)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    try:
        asyncio.run(serve(settings, stop))
    except Exception:
        log.exception("Headless service failed")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
