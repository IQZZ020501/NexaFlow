"""Bounded liveness probe for the sandbox JSON-lines service."""

from __future__ import annotations

import json
import socket
from pathlib import Path

SOCKET_PATH = Path("/run/sandbox/sandbox.sock")
MAX_RESPONSE_BYTES = 4 * 1024


def probe(socket_path: str | Path = SOCKET_PATH) -> bool:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(1)
            client.connect(str(socket_path))
            client.sendall(b'{"version":1,"type":"healthcheck"}\n')
            with client.makefile("rb") as response:
                response_line = response.readline(MAX_RESPONSE_BYTES + 1)
        if not response_line or len(response_line) > MAX_RESPONSE_BYTES:
            return False
        response = json.loads(response_line)
    except (OSError, json.JSONDecodeError):
        return False
    return response == {
        "version": 1,
        "ok": True,
        "status": "ready",
    }


if __name__ == "__main__":
    raise SystemExit(0 if probe() else 1)
