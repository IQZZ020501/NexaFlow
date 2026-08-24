"""Extended stdlib-only coverage suite for the sandbox package.

Complements `sandbox.self_check` with branches it does not reach: request
error paths on the JSON-lines server, healthcheck edge cases, `Limits`
validation, `run_code` argument validation, and process-termination paths.

Run via `sandbox/run_coverage.sh` (measures with coverage) or directly with
`python -m sandbox.tests` (also runs inside the CI Docker image, where the
root/Linux-gated branches execute).
"""

from __future__ import annotations

import base64
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

from sandbox import runner as runner_module
from sandbox import server as server_module
from sandbox.healthcheck import (
    MAX_RESPONSE_BYTES,
    PROBE_DEADLINE_SECONDS,
    _receive_line,
    probe,
)
from sandbox.runner import (
    MAX_CODE_BYTES,
    Limits,
    _terminate,
    execute_request,
    run_code,
)
from sandbox.server import MAX_REQUEST_BYTES, SandboxServer

HERE = Path(__file__).parent


def _coverage_prefix() -> list[str]:
    """Return [coverage-binary, run, flags] when available, else plain python."""
    binary = os.environ.get("SANDBOX_COVERAGE_BIN")
    if binary:
        nested = HERE / ".coverage.sandbox-nested"
        return [binary, "run", "--parallel-mode", f"--data-file={nested}"]
    return [sys.executable]


def check_limits_validation() -> None:
    for raw, fragment in [
        ("not-a-dict", "limits must be an object"),
        ({"timeout_ms": 0}, "positive integer"),
        ({"cpu_seconds": True}, "positive integer"),
        ({"memory_bytes": -1}, "positive integer"),
    ]:
        try:
            Limits.from_request(raw)
        except ValueError as exc:
            assert fragment in str(exc), (raw, exc)
        else:
            raise AssertionError(f"Limits.from_request({raw!r}) accepted")

    assert Limits.from_request(None) == Limits()
    clamped = Limits.from_request({"timeout_ms": 99_999, "max_processes": 2})
    assert clamped.timeout_ms == Limits().timeout_ms
    assert clamped.max_processes == 2

    try:
        Limits.from_request({"memory_mb": 128})
    except ValueError as exc:
        assert "unknown limits" in str(exc)
    else:
        raise AssertionError("unknown limit accepted")

    from sandbox.runner import MAX_STDIN_BYTES

    try:
        run_code("print('ignored')", "x" * (MAX_STDIN_BYTES + 1))
    except ValueError as exc:
        assert "stdin exceeds" in str(exc)
    else:
        raise AssertionError("oversized stdin accepted")


def check_run_code_validation() -> None:
    cases = [
        (lambda: run_code(123), ValueError, "code must be a string"),
        (lambda: run_code("print(1)", 123), ValueError, "stdin must be a string"),
        (lambda: run_code("\ud800"), ValueError, "valid UTF-8"),
        (lambda: run_code("x" * (MAX_CODE_BYTES // 1 + 1)), ValueError, "256 KiB"),
        (lambda: execute_request("x"), ValueError, "request must be an object"),
        (lambda: execute_request({"code": 123}), ValueError, "code must be a string"),
        (lambda: execute_request({"code": "x", "stdin": 1}), ValueError, "stdin must be a string"),
        (
            lambda: execute_request({"code": "pass", "artifact": []}),
            ValueError,
            "artifact must contain",
        ),
        (
            lambda: execute_request(
                {
                    "code": "pass",
                    "artifact": {"format": "pdf", "filename": "x.pdf"},
                }
            ),
            ValueError,
            "artifact.format",
        ),
        (
            lambda: execute_request({"code": "pass", "skills": ["../documents"]}),
            ValueError,
            "skills must contain",
        ),
        (
            lambda: execute_request({"code": "pass", "skills": ["documents"]}),
            ValueError,
            "skills require",
        ),
    ]
    for call, exc_type, fragment in cases:
        try:
            call()
        except exc_type as exc:
            assert fragment in str(exc), exc
        else:
            raise AssertionError(f"{call} did not raise {exc_type.__name__}")

    payload = execute_request({"code": "print(40 + 2)"})
    assert payload["ok"] is True and payload["stdout"].strip() == "42"
    assert execute_request({"code": "x"})["version"] == 1

    with tempfile.TemporaryDirectory() as directory:
        workdir = Path(directory)
        command = [sys.executable, "-c", "pass"]
        with mock.patch.object(runner_module.sys, "platform", "linux"):
            assert runner_module._sandboxed_child_command(command, workdir) == command
        with mock.patch.object(runner_module.sys, "platform", "darwin"), mock.patch.object(
            runner_module.shutil, "which", return_value=None
        ):
            try:
                runner_module._sandboxed_child_command(command, workdir)
            except RuntimeError as exc:
                assert "sandbox-exec" in str(exc)
            else:
                raise AssertionError("missing macOS sandbox-exec was accepted")


def check_artifact_outputs_and_skills() -> None:
    html = execute_request(
        {
            "code": (
                "import os\n"
                "open(os.environ['NEXAFLOW_OUTPUT_PATH'], 'w', encoding='utf-8').write("
                "'<html><style>body{color:#123}</style><body>ready</body></html>')\n"
            ),
            "artifact": {"format": "html", "filename": "page.html"},
        }
    )
    assert html["ok"] is True, html
    assert html["artifact"]["filename"] == "page.html"
    assert html["artifact"]["format"] == "html"
    assert base64.b64decode(html["artifact"]["content_base64"]).endswith(
        b"</html>"
    )

    docx = execute_request(
        {
            "code": (
                "import os, zipfile\n"
                "with zipfile.ZipFile(os.environ['NEXAFLOW_OUTPUT_PATH'], 'w') as archive:\n"
                "    archive.writestr('[Content_Types].xml', '<Types/>')\n"
                "    archive.writestr('word/document.xml', '<document/>')\n"
            ),
            "artifact": {"format": "docx", "filename": "report.docx"},
        }
    )
    assert docx["ok"] is True, docx
    assert docx["artifact"]["filename"] == "report.docx"

    with tempfile.TemporaryDirectory() as directory:
        skill = Path(directory) / "documents"
        skill.mkdir()
        (skill / "SKILL.md").write_text("skill-ready", encoding="utf-8")
        with mock.patch.dict(os.environ, {"SANDBOX_SKILLS_DIR": directory}):
            skilled = execute_request(
                {
                    "code": (
                        "import os\n"
                        "from pathlib import Path\n"
                        "text = (Path(os.environ['NEXAFLOW_SKILLS_DIR']) / "
                        "'documents' / 'SKILL.md').read_text()\n"
                        "open(os.environ['NEXAFLOW_OUTPUT_PATH'], 'w').write(text)\n"
                    ),
                    "skills": ["documents"],
                    "artifact": {"format": "html", "filename": "skill.html"},
                }
            )
            assert skilled["ok"] is True, skilled
            assert (
                base64.b64decode(skilled["artifact"]["content_base64"])
                == b"skill-ready"
            )

            missing = execute_request(
                {
                    "code": "pass",
                    "skills": ["missing"],
                    "artifact": {"format": "html", "filename": "missing.html"},
                }
            )
            assert missing["ok"] is False
            assert missing["error"] == "skill_not_found"

    try:
        execute_request(
            {
                "code": "pass",
                "artifact": {"format": "html", "filename": "../page.html"},
            }
        )
    except ValueError as exc:
        assert "filename" in str(exc)
    else:
        raise AssertionError("artifact path traversal was accepted")


def check_artifact_error_paths() -> None:
    for code, artifact_format, filename, expected_error in [
        ("pass", "html", "missing.html", "artifact_missing"),
        (
            "import os\nopen(os.environ['NEXAFLOW_OUTPUT_PATH'], 'wb').close()",
            "html",
            "empty.html",
            "artifact_empty",
        ),
        (
            "import os\nopen(os.environ['NEXAFLOW_OUTPUT_PATH'], 'wb').write(b'\\xff')",
            "html",
            "invalid.html",
            "artifact_invalid",
        ),
        (
            "import os\n"
            "open(os.environ['NEXAFLOW_OUTPUT_PATH'], 'wb').write(b'not-a-zip')",
            "docx",
            "invalid.docx",
            "artifact_invalid",
        ),
        (
            "import os, zipfile\n"
            "with zipfile.ZipFile(os.environ['NEXAFLOW_OUTPUT_PATH'], 'w') as archive:\n"
            "    archive.writestr('other.xml', '<x/>')\n",
            "docx",
            "incomplete.docx",
            "artifact_invalid",
        ),
    ]:
        result = execute_request(
            {
                "code": code,
                "artifact": {"format": artifact_format, "filename": filename},
            }
        )
        assert result["ok"] is False, result
        assert result["error"] == expected_error, result

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        def expect_artifact_error(path: Path, expected: str) -> None:
            try:
                runner_module._read_artifact(path, "html", "page.html")
            except ValueError as exc:
                assert str(exc) == expected, exc
            else:
                raise AssertionError(f"{path} was accepted as an artifact")

        expect_artifact_error(root, "artifact_invalid")
        oversized = root / "oversized.html"
        oversized.write_bytes(b"x" * (runner_module.MAX_ARTIFACT_BYTES + 1))
        expect_artifact_error(oversized, "artifact_too_large")

        root_file = root / "skills-file"
        root_file.write_text("not a directory", encoding="utf-8")
        with mock.patch.dict(
            os.environ,
            {"SANDBOX_SKILLS_DIR": str(root / "missing-skills")},
        ):
            missing_root = execute_request(
                {
                    "code": "pass",
                    "skills": ["documents"],
                    "artifact": {"format": "html", "filename": "missing-root.html"},
                }
            )
        assert missing_root["error"] == "skill_not_found", missing_root

        with mock.patch.dict(os.environ, {"SANDBOX_SKILLS_DIR": str(root_file)}):
            file_root = execute_request(
                {
                    "code": "pass",
                    "skills": ["documents"],
                    "artifact": {"format": "html", "filename": "file-root.html"},
                }
            )
        assert file_root["error"] == "skill_not_found", file_root

        skills_root = root / "skills"
        skills_root.mkdir()
        outside = root / "outside"
        outside.mkdir()
        (skills_root / "linked").symlink_to(outside, target_is_directory=True)
        with mock.patch.dict(os.environ, {"SANDBOX_SKILLS_DIR": str(skills_root)}):
            linked = execute_request(
                {
                    "code": "pass",
                    "skills": ["linked"],
                    "artifact": {"format": "html", "filename": "linked.html"},
                }
            )
        assert linked["error"] == "skill_invalid", linked

        nested = skills_root / "nested"
        nested.mkdir()
        (nested / "linked-file").symlink_to(root_file)
        with mock.patch.dict(os.environ, {"SANDBOX_SKILLS_DIR": str(skills_root)}):
            nested_link = execute_request(
                {
                    "code": "pass",
                    "skills": ["nested"],
                    "artifact": {"format": "html", "filename": "nested.html"},
                }
            )
        assert nested_link["error"] == "skill_invalid", nested_link

        large = skills_root / "large"
        large.mkdir()
        (large / "large.bin").write_bytes(b"x" * (runner_module.MAX_SKILL_BYTES + 1))
        with mock.patch.dict(os.environ, {"SANDBOX_SKILLS_DIR": str(skills_root)}):
            too_large = execute_request(
                {
                    "code": "pass",
                    "skills": ["large"],
                    "artifact": {"format": "html", "filename": "large.html"},
                }
            )
        assert too_large["error"] == "skill_too_large", too_large


def check_run_limits() -> None:
    timeout = run_code(
        "while True: pass",
        limits=Limits(timeout_ms=150, cpu_seconds=1),
    )
    assert timeout.error == "wall_time_limit_exceeded", timeout

    closed = run_code(
        "import os, time\nos.close(1)\nos.close(2)\ntime.sleep(1)",
        limits=Limits(timeout_ms=3_000, cpu_seconds=5),
    )
    assert closed.ok, closed  # pipes EOF; process exit observed via poll branch

    output = run_code(
        "print('x' * 100_000)",
        limits=Limits(max_output_bytes=1024),
    )
    assert output.error == "output_limit_exceeded", output
    assert len(output.stdout.encode()) == 1024, output


def check_terminate() -> None:
    # killpg on an already-exited process group -> ProcessLookupError -> pass.
    finished = subprocess.Popen([sys.executable, "-c", "pass"])
    finished.wait()
    _terminate(finished)  # poll() is not None; killpg lookup may fail harmlessly

    # TimeoutExpired chain: poll stays None, both waits time out.
    class Stubborn:
        pid = 2**31 - 1  # nonexistent group -> ProcessLookupError

        def poll(self) -> None:
            return None

        def wait(self, timeout: float = 0) -> None:
            raise subprocess.TimeoutExpired("process", timeout)

        def kill(self) -> None:
            pass

    _terminate(Stubborn())  # must not raise

    # Success path: real child in its own session, killed via its group.
    sleeper = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    _terminate(sleeper)
    sleeper.wait(timeout=2)
    assert sleeper.returncode == -signal.SIGKILL


def check_blocking_io_retry() -> None:
    real_read = os.read
    state = {"calls": 0}

    def flaky_read(fd: int, n: int) -> bytes:
        # Popen's errpipe read uses n=50000; _collect_output reads use
        # min(64 KiB, limit+1-len) -> 65537 for the default limit. Raise only
        # for the first _collect_output-style read.
        if state["calls"] == 0 and n != 50000:
            state["calls"] += 1
            raise BlockingIOError
        return real_read(fd, n)

    with mock.patch.object(runner_module.os, "read", flaky_read):
        result = run_code("print('retry-ok')")
    assert result.ok and result.stdout.strip() == "retry-ok", result
    assert state["calls"] == 1


def check_non_posix() -> None:
    with mock.patch.object(runner_module.os, "name", "nt"):
        try:
            run_code("print(1)")
        except RuntimeError as exc:
            assert "POSIX" in str(exc)
        else:
            raise AssertionError("non-POSIX run_code accepted")


def check_macos_seatbelt() -> None:
    if sys.platform != "darwin":
        return
    secret = HERE.parent / ".sandbox-seatbelt-secret"
    target = HERE.parent / ".sandbox-seatbelt-write"
    secret.write_text("must-not-read", encoding="utf-8")
    target.unlink(missing_ok=True)
    try:
        result = run_code(
            "from pathlib import Path\n"
            f"secret = Path({str(secret)!r})\n"
            f"target = Path({str(target)!r})\n"
            "try:\n"
            "    secret.read_text()\n"
            "except OSError:\n"
            "    print('read-blocked')\n"
            "else:\n"
            "    print('read-open')\n"
            "try:\n"
            "    target.write_text('polluted')\n"
            "except OSError:\n"
            "    print('write-blocked')\n"
            "else:\n"
            "    print('write-open')\n"
        )
        assert result.ok, result
        assert result.stdout.splitlines() == ["read-blocked", "write-blocked"]
        assert not target.exists()
    finally:
        secret.unlink(missing_ok=True)
        target.unlink(missing_ok=True)


def _raw_request(socket_path: Path, payload: bytes, read_response: bool = True) -> bytes | None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(8)
        client.connect(str(socket_path))
        client.sendall(payload)
        if not read_response:
            return None
        return client.makefile("rb").readline()


def check_server_error_paths() -> None:
    with tempfile.TemporaryDirectory() as directory:
        socket_path = Path(directory) / "errors.sock"
        server = SandboxServer(socket_path)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for _ in range(100):
                if socket_path.exists():
                    break
                time.sleep(0.01)
            assert socket_path.exists()

            response = json.loads(_raw_request(socket_path, b"[1,2]\n") or b"{}")
            assert response["error"] == "request must be an object", response

            response = json.loads(_raw_request(socket_path, b"{not-json\n") or b"{}")
            assert response["ok"] is False and "error" in response, response

            response = json.loads(_raw_request(socket_path, b"\xff\xfe\n") or b"{}")
            assert response["ok"] is False, response

            oversized = b'{"code":"print(1)","pad":"' + b"x" * (MAX_REQUEST_BYTES + 8) + b'"}\n'
            response = json.loads(_raw_request(socket_path, oversized) or b"{}")
            assert response["error"] == "request_too_large", response

            # Concurrent slot exhaustion -> sandbox_busy.
            assert server.run_slot.acquire(timeout=1)
            try:
                response = json.loads(_raw_request(socket_path, b'{"code":"print(1)"}\n') or b"{}")
                assert response["error"] == "sandbox_busy", response
            finally:
                server.run_slot.release()

            # Unexpected internal error -> sandbox_internal_error.
            original = server_module.execute_request
            server_module.execute_request = lambda request: (_ for _ in ()).throw(
                RuntimeError("boom")
            )
            previous_level = server_module.logger.level
            server_module.logger.setLevel(100)  # silence the expected traceback
            try:
                response = json.loads(_raw_request(socket_path, b'{"code":"print(1)"}\n') or b"{}")
                assert response["error"] == "sandbox_internal_error", response
            finally:
                server_module.logger.setLevel(previous_level)
                server_module.execute_request = original

            # Healthcheck request.
            response = json.loads(_raw_request(socket_path, b'{"version":1,"type":"healthcheck"}\n') or b"{}")
            assert response == {"version": 1, "ok": True, "status": "ready"}, response

            # Request timeout: partial line, no newline; handler times out at 5s.
            started = time.monotonic()
            response = json.loads(_raw_request(socket_path, b'{"code": "print(1)"') or b"{}")
            assert response["error"] == "request_timeout", response
            assert time.monotonic() - started >= 4.5
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()


def check_server_lifecycle() -> None:
    with tempfile.TemporaryDirectory() as directory:
        # Refuse to replace a regular file.
        file_path = Path(directory) / "occupied"
        file_path.write_text("not a socket", encoding="utf-8")
        try:
            SandboxServer(file_path)
        except RuntimeError as exc:
            assert "refusing to replace non-socket path" in str(exc)
        else:
            raise AssertionError("SandboxServer replaced a regular file")

        # Reuse of a freed socket path exercises the stale-socket unlink.
        socket_path = Path(directory) / "reuse.sock"
        first = SandboxServer(socket_path)
        first.server_close()
        assert not socket_path.exists()
        second = SandboxServer(socket_path)
        second.server_close()
        # Second close -> FileNotFoundError swallowed.
        second.server_close()

        # Overwriting a live socket exercises the exists/unlink path in __init__.
        live = SandboxServer(Path(directory) / "live.sock")
        replacement = SandboxServer(Path(directory) / "live.sock")
        replacement.server_close()
        live.server_close()


def check_main_cli() -> None:
    class FakeServer:
        def __init__(self, socket_path: str | Path):
            self.socket_path = Path(socket_path)
            self.closed = False
            self.shutdown_called = False

        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def shutdown(self) -> None:
            self.shutdown_called = True

        def server_close(self) -> None:
            self.closed = True

    handlers: dict[int, object] = {}

    def fake_signal(signum: int, handler: object) -> None:
        handlers[signum] = handler

    with tempfile.TemporaryDirectory() as directory:
        socket_path = Path(directory) / "cli.sock"
        with mock.patch.object(server_module, "SandboxServer", FakeServer), mock.patch.object(
            server_module.signal, "signal", fake_signal
        ), mock.patch.object(sys, "argv", ["sandbox-server", "--socket", str(socket_path)]):
            try:
                server_module.main()
            except KeyboardInterrupt:
                pass  # FakeServer.serve_forever raises it; finally ran server_close.
        assert FakeServer.__new__  # constructed through patched class
        # KeyboardInterrupt escaped main(); server_close ran in finally.
        # Trigger the registered SIGTERM handler to exercise `stop`.
        handler = handlers.get(signal.SIGTERM)
        assert handler is not None
        # Reconstruct: main() raises KeyboardInterrupt, so re-run with a server
        # whose serve_forever blocks until shutdown is requested.
        created: list[FakeServer] = []
        with tempfile.TemporaryDirectory() as directory2:
            socket_path2 = Path(directory2) / "cli2.sock"

            class BlockingServer(FakeServer):
                def serve_forever(self) -> None:
                    while not self.shutdown_called:
                        time.sleep(0.01)

            def make_server(path: str | Path) -> BlockingServer:
                instance = BlockingServer(path)
                created.append(instance)
                return instance

            with mock.patch.object(server_module, "SandboxServer", make_server), mock.patch.object(
                server_module.signal, "signal", fake_signal
            ), mock.patch.object(sys, "argv", ["sandbox-server", "--socket", str(socket_path2)]):
                thread = threading.Thread(target=server_module.main, daemon=True)
                thread.start()
                for _ in range(200):
                    if created:
                        break
                    time.sleep(0.01)
                assert created
                handler = handlers.get(signal.SIGTERM)
                assert handler is not None
                handler(None, None)  # type: ignore[misc]
                thread.join(timeout=5)
                assert created[0].closed is True

        # Non-POSIX host exits with SystemExit.
        with mock.patch.object(server_module.os, "name", "nt"), mock.patch.object(
            sys, "argv", ["sandbox-server"]
        ):
            try:
                server_module.main()
            except SystemExit as exc:
                assert "POSIX" in str(exc)
            else:
                raise AssertionError("non-POSIX main() did not exit")


def check_healthcheck_branches() -> None:
    # Deadline already passed -> empty line.
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        assert _receive_line(client, time.monotonic() - 0.5) == b""

    def start_server(directory: Path, payload: bytes, delay: float = 0) -> Path:
        socket_path = directory / "serve.sock"

        def runner() -> None:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                server.bind(str(socket_path))
                server.listen(1)
                connection, _ = server.accept()
                with connection:
                    connection.recv(1024)
                    if delay:
                        time.sleep(delay)
                    for value in payload:
                        try:
                            connection.sendall(bytes((value,)))
                        except BrokenPipeError:
                            break

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        for _ in range(100):
            if socket_path.exists():
                break
            time.sleep(0.01)
        time.sleep(0.05)  # allow listen() to run before clients connect
        return socket_path

    # EOF before newline -> partial line returned.
    with tempfile.TemporaryDirectory() as directory:
        socket_path = start_server(Path(directory), b'{"partial"')
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            deadline = time.monotonic() + PROBE_DEADLINE_SECONDS * 3
            client.settimeout(PROBE_DEADLINE_SECONDS * 3)
            client.connect(str(socket_path))
            client.sendall(b'{"version":1,"type":"healthcheck"}\n')
            assert _receive_line(client, deadline) == b'{"partial"'

    # Oversized chunked response without newline -> probe False (len > max).
    with tempfile.TemporaryDirectory() as directory:
        socket_path = start_server(Path(directory), b"x" * (MAX_RESPONSE_BYTES + 1))
        assert not probe(socket_path)

    # Exact limit without newline -> no crash, probe False.
    with tempfile.TemporaryDirectory() as directory:
        socket_path = start_server(Path(directory), b"y" * MAX_RESPONSE_BYTES)
        assert not probe(socket_path)

    # Empty response -> explicit false branch before JSON parsing.
    with tempfile.TemporaryDirectory() as directory:
        socket_path = start_server(Path(directory), b"")
        assert not probe(socket_path)

    # Healthcheck CLI exits 1 when the default socket is absent.
    env = dict(os.environ)
    prefix = _coverage_prefix()
    run = subprocess.run(
        [*prefix, "-m", "sandbox.healthcheck"],
        cwd=HERE.parent,  # package root for `-m sandbox.*`
        env=env,
        capture_output=True,
        timeout=30,
    )
    assert run.returncode == 1, run

    # CLI exits 0 against a live server on the default path (root or /run available).
    if os.geteuid() == 0 and Path("/run/sandbox").exists():
        socket_path = Path("/run/sandbox/sandbox.sock")
        server = SandboxServer(socket_path)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            run = subprocess.run(
                [*prefix, "-m", "sandbox.healthcheck"],
                cwd=HERE.parent,  # package root for `-m sandbox.*`
                env=env,
                capture_output=True,
                timeout=30,
            )
            assert run.returncode == 0, run
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()


def check_server_cli_subprocess() -> None:
    """Run `python -m sandbox.server --socket ...` as a real process."""
    prefix = _coverage_prefix()
    with tempfile.TemporaryDirectory() as directory:
        socket_path = Path(directory) / "cli-server.sock"
        process = subprocess.Popen(
            [*prefix, "-m", "sandbox.server", "--socket", str(socket_path)],
            cwd=HERE.parent,  # package root for `-m sandbox.*`
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            for _ in range(200):
                if socket_path.exists():
                    break
                time.sleep(0.02)
            assert socket_path.exists(), "cli server socket not created"
            assert probe(socket_path)
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=10)
            assert process.returncode == 0, process.returncode
            assert not socket_path.exists(), "socket not cleaned up on exit"
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


def main() -> None:
    check_limits_validation()
    check_run_code_validation()
    check_artifact_outputs_and_skills()
    check_artifact_error_paths()
    check_run_limits()
    check_terminate()
    check_blocking_io_retry()
    check_non_posix()
    check_macos_seatbelt()
    check_server_error_paths()
    check_server_lifecycle()
    check_main_cli()
    check_healthcheck_branches()
    check_server_cli_subprocess()
    print("sandbox extended tests passed")


if __name__ == "__main__":
    main()
