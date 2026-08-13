"""Small stdlib-only smoke test for the runner and socket protocol."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import socket
import sys
import tempfile
import threading
import time

from sandbox.runner import MAX_STDIN_BYTES, Limits, run_code
from sandbox.server import SandboxServer


def request(socket_path: Path, payload: dict) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(socket_path))
        client.sendall((json.dumps(payload) + "\n").encode())
        return json.loads(client.makefile("rb").readline())


def main() -> None:
    result = run_code("print(2 + 2)")
    assert result.ok and result.stdout.strip() == "4", result

    if os.geteuid() == 0:
        identity = run_code("import os; print(os.geteuid())")
        assert identity.stdout.strip() == "65532", identity

    timeout = run_code(
        "while True: pass",
        limits=Limits(timeout_ms=200, cpu_seconds=1),
    )
    assert timeout.error == "wall_time_limit_exceeded", timeout

    closed_output = run_code(
        "import os\nos.close(1)\nos.close(2)\nwhile True: pass",
        limits=Limits(timeout_ms=200, cpu_seconds=1),
    )
    assert closed_output.error == "wall_time_limit_exceeded", closed_output

    cpu = run_code(
        "while True: pass",
        limits=Limits(timeout_ms=3_000, cpu_seconds=1),
    )
    assert not cpu.ok and cpu.error is None, cpu
    assert cpu.exit_code in (-signal.SIGXCPU, -signal.SIGKILL), cpu

    output = run_code(
        "print('x' * 100_000)",
        limits=Limits(max_output_bytes=1024),
    )
    assert output.error == "output_limit_exceeded", output
    assert len(output.stdout.encode()) == 1024, output

    file_size = run_code(
        "open('large', 'wb').write(b'x' * 100_000)",
        limits=Limits(max_file_bytes=1024),
    )
    assert not file_size.ok and file_size.exit_code != 0, file_size

    open_files = run_code(
        "files = []\n"
        "try:\n"
        "    while True: files.append(open('/dev/null'))\n"
        "except OSError:\n"
        "    print('open-file-limit')\n",
        limits=Limits(max_open_files=16),
    )
    assert open_files.ok and open_files.stdout.strip() == "open-file-limit", open_files

    if sys.platform == "linux":
        descendant = run_code(
            "import os\n"
            "if os.fork() == 0:\n"
            "    while True: pass\n"
            "os._exit(0)\n",
            limits=Limits(timeout_ms=200, cpu_seconds=1),
        )
        assert descendant.error == "wall_time_limit_exceeded", descendant

        memory = run_code(
            "try:\n"
            "    bytearray(512 * 1024 * 1024)\n"
            "except MemoryError:\n"
            "    print('memory-limit')\n",
            limits=Limits(memory_bytes=128 * 1024 * 1024),
        )
        assert memory.ok and memory.stdout.strip() == "memory-limit", memory

        processes = run_code(
            "import subprocess\n"
            "try:\n"
            "    subprocess.run(['/bin/true'], check=True)\n"
            "except OSError:\n"
            "    print('process-limit')\n",
            limits=Limits(max_processes=1),
        )
        assert processes.ok and processes.stdout.strip() == "process-limit", processes

    try:
        run_code("print('ignored')", "x" * (MAX_STDIN_BYTES + 1))
    except ValueError as exc:
        assert "stdin exceeds" in str(exc)
    else:
        raise AssertionError("oversized stdin was accepted")

    assert Limits.from_request({"timeout_ms": 99_999}).timeout_ms == 5_000
    try:
        Limits.from_request({"memory_mb": 128})
    except ValueError as exc:
        assert "unknown limits" in str(exc)
    else:
        raise AssertionError("unknown limit was accepted")

    with tempfile.TemporaryDirectory() as directory:
        socket_path = Path(directory) / "sandbox.sock"
        server = SandboxServer(socket_path)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        for _ in range(100):
            if socket_path.exists():
                break
            time.sleep(0.01)
        if not socket_path.exists():
            server.shutdown()
            thread.join(timeout=1)
            server.server_close()
            raise AssertionError("sandbox socket was not created")
        response = request(socket_path, {"code": "print(input())", "stdin": "socket-ok"})
        server.shutdown()
        thread.join(timeout=1)
        server.server_close()
        assert response["ok"] and response["stdout"].strip() == "socket-ok", response

    print("sandbox self-check passed")


if __name__ == "__main__":
    main()
