"""Unix-domain JSON-lines server for the NexaFlow code sandbox."""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import signal
import socketserver
import stat
import threading
from typing import Any

from .runner import encode_response, execute_request


MAX_REQUEST_BYTES = 768 * 1024
# ponytail: serialize same-UID jobs; move to one sandbox instance per job before
# increasing throughput so untrusted processes cannot signal sibling jobs.
MAX_CONCURRENT_RUNS = 1
logger = logging.getLogger(__name__)


class SandboxRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        self.connection.settimeout(5)
        try:
            line = self.rfile.readline(MAX_REQUEST_BYTES + 1)
        except TimeoutError:
            self.wfile.write(
                encode_response(
                    {"version": 1, "ok": False, "error": "request_timeout"}
                )
            )
            return
        if len(line) > MAX_REQUEST_BYTES:
            self.wfile.write(
                encode_response(
                    {"version": 1, "ok": False, "error": "request_too_large"}
                )
            )
            return
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("request must be an object")
            if not self.server.run_slot.acquire(blocking=False):  # type: ignore[attr-defined]
                response: dict[str, Any] = {
                    "version": 1,
                    "ok": False,
                    "error": "sandbox_busy",
                }
            else:
                try:
                    response = execute_request(request)
                finally:
                    self.server.run_slot.release()  # type: ignore[attr-defined]
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            response = {"version": 1, "ok": False, "error": str(exc)}
        except Exception:
            logger.exception("Sandbox request failed.")
            response = {"version": 1, "ok": False, "error": "sandbox_internal_error"}
        self.wfile.write(encode_response(response))


class SandboxServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 16

    def __init__(self, socket_path: str | Path):
        self.socket_path = Path(socket_path)
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        self.socket_path.parent.chmod(0o750)
        if self.socket_path.exists():
            if not stat.S_ISSOCK(self.socket_path.stat().st_mode):
                raise RuntimeError(f"refusing to replace non-socket path: {self.socket_path}")
            self.socket_path.unlink()
        super().__init__(str(self.socket_path), SandboxRequestHandler)
        self.run_slot = threading.BoundedSemaphore(MAX_CONCURRENT_RUNS)
        self.socket_path.chmod(0o660)

    def server_close(self) -> None:
        super().server_close()
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default="/run/sandbox/sandbox.sock")
    args = parser.parse_args()
    if os.name != "posix":
        raise SystemExit("the sandbox requires a POSIX host")
    server = SandboxServer(args.socket)

    def stop(_signum: int, _frame: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
