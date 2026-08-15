"""Run untrusted Python code with process and resource limits."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import ctypes
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any

RUNNER_UID = int(os.environ.get("SANDBOX_RUNNER_UID", "65532"))
RUNNER_GID = int(os.environ.get("SANDBOX_RUNNER_GID", "65532"))
MAX_CODE_BYTES = 256 * 1024
MAX_STDIN_BYTES = 256 * 1024
PR_SET_CHILD_SUBREAPER = 36


@dataclass(frozen=True)
class Limits:
    """Hard upper bounds for one child process."""

    timeout_ms: int = 5_000
    cpu_seconds: int = 5
    memory_bytes: int = 256 * 1024 * 1024
    max_output_bytes: int = 64 * 1024
    max_file_bytes: int = 1 * 1024 * 1024
    max_processes: int = 16
    max_open_files: int = 64

    @classmethod
    def from_request(cls, raw: Any) -> "Limits":
        if raw is None:
            return cls()
        if not isinstance(raw, dict):
            raise ValueError("limits must be an object")

        hard = cls()
        allowed = set(asdict(hard))
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"unknown limits: {', '.join(sorted(unknown))}")

        def bounded(name: str, default: int) -> int:
            value = raw.get(name, default)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"limits.{name} must be a positive integer")
            return min(value, getattr(hard, name))

        return cls(
            timeout_ms=bounded("timeout_ms", hard.timeout_ms),
            cpu_seconds=bounded("cpu_seconds", hard.cpu_seconds),
            memory_bytes=bounded("memory_bytes", hard.memory_bytes),
            max_output_bytes=bounded("max_output_bytes", hard.max_output_bytes),
            max_file_bytes=bounded("max_file_bytes", hard.max_file_bytes),
            max_processes=bounded("max_processes", hard.max_processes),
            max_open_files=bounded("max_open_files", hard.max_open_files),
        )


@dataclass(frozen=True)
class ExecutionResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int | None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "error": self.error,
        }


def _terminate(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if process.poll() is None:
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass


def _enable_linux_subreaper() -> None:  # pragma: no cover - Linux CI Docker only
    if sys.platform != "linux":
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))


def _linux_descendant_pids(parent_pid: int) -> set[int]:  # pragma: no cover
    if sys.platform != "linux":
        return set()

    children_by_parent: dict[int, set[int]] = {}
    for status_path in Path("/proc").glob("[0-9]*/status"):
        try:
            pid = int(status_path.parent.name)
            parent = next(
                int(line.split(":", 1)[1].strip())
                for line in status_path.read_text(encoding="utf-8").splitlines()
                if line.startswith("PPid:")
            )
        except (FileNotFoundError, ProcessLookupError, StopIteration, ValueError):
            continue
        children_by_parent.setdefault(parent, set()).add(pid)

    descendants: set[int] = set()
    pending = list(children_by_parent.get(parent_pid, ()))
    while pending:
        pid = pending.pop()
        if pid in descendants:
            continue
        descendants.add(pid)
        pending.extend(children_by_parent.get(pid, ()))
    return descendants


def _reap_children() -> None:  # pragma: no cover - Linux CI Docker only
    while True:
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            return


def _terminate_linux_descendants() -> None:  # pragma: no cover
    if sys.platform != "linux":
        return

    for _ in range(50):
        descendants = _linux_descendant_pids(os.getpid())
        if not descendants:
            _reap_children()
            if not _linux_descendant_pids(os.getpid()):
                return
        for pid in descendants:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        _reap_children()
        time.sleep(0.01)

    if _linux_descendant_pids(os.getpid()):
        raise RuntimeError("sandbox descendants survived cleanup")


def _collect_output(
    process: subprocess.Popen[bytes],
    limit: int,
    deadline: float,
) -> tuple[bytes, bytes, str | None]:
    selector = selectors.DefaultSelector()
    streams: dict[int, bytearray] = {}
    for stream in (process.stdout, process.stderr):
        assert stream is not None
        stream_fd = stream.fileno()
        os.set_blocking(stream_fd, False)
        streams[stream_fd] = bytearray()
        selector.register(stream_fd, selectors.EVENT_READ)

    exceeded: str | None = None
    while selector.get_map() or process.poll() is None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            exceeded = "wall_time_limit_exceeded"
            _terminate(process)
            break
        if not selector.get_map():
            time.sleep(min(remaining, 0.05))
            continue
        for key, _ in selector.select(min(remaining, 0.1)):
            try:
                data = os.read(
                    key.fd,
                    min(64 * 1024, limit + 1 - len(streams[key.fd])),
                )
            except BlockingIOError:
                continue
            if not data:
                selector.unregister(key.fd)
                continue
            streams[key.fd].extend(data)
            if len(streams[key.fd]) > limit:
                exceeded = "output_limit_exceeded"
                _terminate(process)
                break
        if exceeded is not None:
            break

    selector.close()
    stdout_fd = process.stdout.fileno() if process.stdout is not None else -1
    stderr_fd = process.stderr.fileno() if process.stderr is not None else -1
    return (
        bytes(streams.get(stdout_fd, b""))[:limit],
        bytes(streams.get(stderr_fd, b""))[:limit],
        exceeded,
    )


def run_code(code: str, stdin: str = "", limits: Limits | None = None) -> ExecutionResult:
    """Execute a UTF-8 Python program and return bounded output."""

    if os.name != "posix":
        raise RuntimeError("the sandbox requires a POSIX host")
    if not isinstance(code, str):
        raise ValueError("code must be a string")
    if not isinstance(stdin, str):
        raise ValueError("stdin must be a string")
    try:
        code_size = len(code.encode("utf-8"))
        stdin_size = len(stdin.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError("code and stdin must be valid UTF-8") from exc
    if code_size > MAX_CODE_BYTES:
        raise ValueError("code exceeds the 256 KiB limit")
    if stdin_size > MAX_STDIN_BYTES:
        raise ValueError("stdin exceeds the 256 KiB limit")
    limits = limits or Limits()
    _enable_linux_subreaper()

    with tempfile.TemporaryDirectory(prefix="nexaflow-sandbox-") as directory:
        workdir = Path(directory)
        code_path = workdir / "program.py"
        stdin_path = workdir / "stdin"
        code_path.write_text(code, encoding="utf-8")
        stdin_path.write_text(stdin, encoding="utf-8")
        if os.geteuid() == 0:  # pragma: no cover - requires root (CI Docker only)
            os.chown(workdir, 0, RUNNER_GID)
            os.chown(code_path, 0, RUNNER_GID)
            os.chown(stdin_path, 0, RUNNER_GID)
            workdir.chmod(0o770)
            code_path.chmod(0o440)
            stdin_path.chmod(0o440)
        else:
            code_path.chmod(0o400)
            stdin_path.chmod(0o400)

        environment = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "PYTHONHASHSEED": "0",
            "PYTHONNOUSERSITE": "1",
            "TMPDIR": str(workdir),
        }
        child_path = Path(__file__).with_name("child.py")
        identity: dict[str, Any] = {}
        if os.geteuid() == 0:  # pragma: no cover - requires root (CI Docker only)
            identity = {
                "user": RUNNER_UID,
                "group": RUNNER_GID,
                "extra_groups": [],
                "umask": 0o077,
            }
        with stdin_path.open("rb") as input_stream:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    "-S",
                    str(child_path),
                    json.dumps(asdict(limits), separators=(",", ":")),
                    str(code_path),
                ],
                cwd=workdir,
                env=environment,
                stdin=input_stream,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                start_new_session=True,
                **identity,
            )
            try:
                stdout, stderr, error = _collect_output(
                    process,
                    limits.max_output_bytes,
                    time.monotonic() + limits.timeout_ms / 1000,
                )
                if error is None:
                    process.wait()
            finally:
                _terminate(process)
                _terminate_linux_descendants()

    exit_code = process.returncode
    return ExecutionResult(
        ok=error is None and exit_code == 0,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
        exit_code=exit_code,
        error=error,
    )


def execute_request(request: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise ValueError("request must be an object")
    code = request.get("code")
    stdin = request.get("stdin", "")
    if not isinstance(code, str):
        raise ValueError("code must be a string")
    if not isinstance(stdin, str):
        raise ValueError("stdin must be a string")
    result = run_code(code, stdin, Limits.from_request(request.get("limits")))
    return {"version": 1, **result.as_dict()}


def encode_response(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
