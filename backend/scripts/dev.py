from __future__ import annotations

import argparse
import socket
import subprocess
import sys


def _stop(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _port_is_available(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        with socket.create_server((host, port), family=family):
            return True
    except OSError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not _port_is_available(args.host, args.port):
        print(
            f"API port {args.host}:{args.port} is already in use. "
            f"Stop the existing process or run make dev PORT={args.port + 1}.",
            file=sys.stderr,
        )
        return 3

    api: subprocess.Popen[bytes] | None = None
    try:
        api = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--reload",
                "--host",
                args.host,
                "--port",
                str(args.port),
            ]
        )
        return api.wait()
    except KeyboardInterrupt:
        return 130
    finally:
        _stop(api)


if __name__ == "__main__":
    raise SystemExit(main())
