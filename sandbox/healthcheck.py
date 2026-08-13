"""Bounded liveness probe for the sandbox JSON-lines service."""

from __future__ import annotations

import json
import socket
import time
from pathlib import Path

SOCKET_PATH = Path("/run/sandbox/sandbox.sock")
MAX_RESPONSE_BYTES = 4 * 1024
PROBE_DEADLINE_SECONDS = 1.0


def _receive_line(client: socket.socket, deadline: float) -> bytes:
    """Accumulate one response line within a shared monotonic deadline."""
    chunks: list[bytes] = []
    received = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        client.settimeout(remaining)
        chunk = client.recv(MAX_RESPONSE_BYTES + 1 - received)
        if not chunk:
            break
        newline = chunk.find(b"\n")
        if newline >= 0:
            chunks.append(chunk[:newline])
            return b"".join(chunks)
        chunks.append(chunk)
        received += len(chunk)
        if received >= MAX_RESPONSE_BYTES:
            break
    return b"".join(chunks)


def probe(socket_path: str | Path = SOCKET_PATH) -> bool:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            deadline = time.monotonic() + PROBE_DEADLINE_SECONDS
            client.settimeout(PROBE_DEADLINE_SECONDS)
            client.connect(str(socket_path))
            client.sendall(b'{"version":1,"type":"healthcheck"}\n')
            response_line = _receive_line(client, deadline)
        if not response_line or len(response_line) > MAX_RESPONSE_BYTES:
            return False
        response = json.loads(response_line)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return response == {
        "version": 1,
        "ok": True,
        "status": "ready",
    }


if __name__ == "__main__":
    raise SystemExit(0 if probe() else 1)
