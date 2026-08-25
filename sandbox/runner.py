"""Run untrusted Python code with process and resource limits."""

from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any

RUNNER_UID = int(os.environ.get("SANDBOX_RUNNER_UID", "65532"))
RUNNER_GID = int(os.environ.get("SANDBOX_RUNNER_GID", "65532"))
MAX_CODE_BYTES = 256 * 1024
MAX_STDIN_BYTES = 256 * 1024
MAX_ARTIFACT_BYTES = 5 * 1024 * 1024
MAX_SKILLS = 8
MAX_SKILL_FILES = 128
MAX_SKILL_BYTES = 2 * 1024 * 1024
SKILL_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
ARTIFACT_FORMAT = re.compile(r"[a-z0-9][a-z0-9+_-]{0,31}\Z")
PR_SET_CHILD_SUBREAPER = 36


@dataclass(frozen=True)
class Limits:
    """Hard upper bounds for one child process."""

    timeout_ms: int = 5_000
    cpu_seconds: int = 5
    memory_bytes: int = 256 * 1024 * 1024
    max_output_bytes: int = 64 * 1024
    max_file_bytes: int = MAX_ARTIFACT_BYTES
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
    artifact: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "ok": self.ok,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "error": self.error,
        }
        if self.artifact is not None:
            payload["artifact"] = self.artifact
        return payload


def _artifact_spec(raw: Any) -> tuple[str, str] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) != {"format", "filename"}:
        raise ValueError("artifact must contain format and filename")
    artifact_format = raw.get("format")
    filename = raw.get("filename")
    if not isinstance(artifact_format, str) or not ARTIFACT_FORMAT.fullmatch(
        artifact_format
    ):
        raise ValueError("artifact.format is invalid")
    if (
        not isinstance(filename, str)
        or not filename
        or filename != filename.strip()
        or len(filename) > 120
        or Path(filename).name != filename
        or "/" in filename
        or "\\" in filename
        or "\x00" in filename
        or any(
            ord(character) < 32 or ord(character) == 127
            for character in filename
        )
    ):
        raise ValueError("artifact.filename is invalid")
    suffix = Path(filename).suffix.removeprefix(".").lower()
    expected_format = suffix or "file"
    if (
        not ARTIFACT_FORMAT.fullmatch(expected_format)
        or artifact_format != expected_format
    ):
        raise ValueError("artifact.filename is invalid")
    return artifact_format, filename


def _skill_names(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if (
        not isinstance(raw, list)
        or len(raw) > MAX_SKILLS
        or any(not isinstance(name, str) or not SKILL_NAME.fullmatch(name) for name in raw)
        or len(set(raw)) != len(raw)
    ):
        raise ValueError("skills must contain up to 8 unique safe names")
    return tuple(raw)


def _stage_skills(workdir: Path, names: tuple[str, ...]) -> tuple[Path, str | None]:
    target_root = workdir / "skills"
    target_root.mkdir()
    if not names:
        return target_root, None

    configured_root = os.environ.get("SANDBOX_SKILLS_DIR", "")
    try:
        source_root = Path(configured_root).resolve(strict=True)
    except (FileNotFoundError, OSError):
        return target_root, "skill_not_found"
    if not source_root.is_dir():
        return target_root, "skill_not_found"

    file_count = 0
    total_bytes = 0
    for name in names:
        source = source_root / name
        try:
            resolved = source.resolve(strict=True)
        except (FileNotFoundError, OSError):
            return target_root, "skill_not_found"
        if source.is_symlink() or resolved.parent != source_root or not resolved.is_dir():
            return target_root, "skill_invalid"
        for current, directories, files in os.walk(resolved, followlinks=False):
            current_path = Path(current)
            paths = [current_path / item for item in (*directories, *files)]
            if any(path.is_symlink() for path in paths):
                return target_root, "skill_invalid"
            for filename in files:
                path = current_path / filename
                try:
                    size = path.stat().st_size
                except OSError:
                    return target_root, "skill_invalid"
                file_count += 1
                total_bytes += size
                if file_count > MAX_SKILL_FILES or total_bytes > MAX_SKILL_BYTES:
                    return target_root, "skill_too_large"
        shutil.copytree(resolved, target_root / name)
    return target_root, None


def _restrict_read_only_tree(path: Path) -> None:
    root = os.geteuid() == 0
    for current, directories, files in os.walk(path):
        current_path = Path(current)
        if root:  # pragma: no cover - requires root (CI Docker only)
            os.chown(current_path, 0, RUNNER_GID)
            for name in (*directories, *files):
                os.chown(current_path / name, 0, RUNNER_GID)
        current_path.chmod(0o550 if root else 0o500)
        for name in files:
            (current_path / name).chmod(0o440 if root else 0o400)


def _read_artifact(path: Path, artifact_format: str, filename: str) -> dict[str, Any]:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ValueError("artifact_missing") from exc
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise ValueError("artifact_invalid")
    if os.geteuid() == 0:  # pragma: no cover - requires root (CI Docker only)
        os.chown(path, 0, RUNNER_GID, follow_symlinks=False)
        path.chmod(0o440)
    if metadata.st_size <= 0:
        raise ValueError("artifact_empty")
    if metadata.st_size > MAX_ARTIFACT_BYTES:
        raise ValueError("artifact_too_large")
    content = path.read_bytes()
    return {
        "format": artifact_format,
        "filename": filename,
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "content_base64": base64.b64encode(content).decode("ascii"),
    }


def _sandboxed_child_command(command: list[str], workdir: Path) -> list[str]:
    if sys.platform != "darwin":
        return command
    sandbox_exec = shutil.which("sandbox-exec")
    if sandbox_exec is None:
        raise RuntimeError("macOS sandbox-exec is required for code execution")

    def quoted(path: Path) -> str:
        return json.dumps(str(path.resolve()))

    home = Path.home().resolve()
    base_prefix = Path(sys.base_prefix).resolve()
    readable = {
        Path(__file__).parent.resolve(),
        Path(sys.prefix).resolve(),
        base_prefix,
        workdir.resolve(),
    }
    denied_home_entries: list[Path] = []
    current = home
    base_parts = (
        base_prefix.relative_to(home).parts if base_prefix.is_relative_to(home) else ()
    )
    for part in base_parts:
        allowed = current / part
        denied_home_entries.extend(path for path in current.iterdir() if path != allowed)
        current = allowed
    if not base_parts:
        denied_home_entries.extend(home.iterdir())
    profile = [
        "(version 1)",
        "(allow default)",
        "(deny network*)",
        "(deny file-write*)",
        f"(allow file-write* (subpath {quoted(workdir)}))",
        '(allow file-write* (literal "/dev/null"))',
        *(
            f"(deny file-read* (subpath {quoted(path)}))"
            for path in denied_home_entries
        ),
        *(f"(allow file-read* (subpath {quoted(path)}))" for path in readable),
    ]
    return [sandbox_exec, "-p", "\n".join(profile), *command]


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


def run_code(
    code: str,
    stdin: str = "",
    limits: Limits | None = None,
    *,
    artifact: tuple[str, str] | None = None,
    skills: tuple[str, ...] = (),
) -> ExecutionResult:
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
        skills_path, skill_error = _stage_skills(workdir, skills)
        if skill_error is not None:
            return ExecutionResult(False, "", "", None, skill_error)
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
        _restrict_read_only_tree(skills_path)

        environment = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "PYTHONHASHSEED": "0",
            "PYTHONNOUSERSITE": "1",
            "TMPDIR": str(workdir),
        }
        if artifact is not None:
            environment.update(
                {
                    "NEXAFLOW_ALLOW_SITE_PACKAGES": "1",
                    "NEXAFLOW_OUTPUT_PATH": str(workdir / artifact[1]),
                    "NEXAFLOW_SKILLS_DIR": str(skills_path),
                }
            )
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
            command = _sandboxed_child_command(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    "-S",
                    str(child_path),
                    json.dumps(asdict(limits), separators=(",", ":")),
                    str(code_path),
                ],
                workdir,
            )
            process = subprocess.Popen(
                command,
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

        artifact_payload = None
        if error is None and process.returncode == 0 and artifact is not None:
            try:
                artifact_payload = _read_artifact(
                    workdir / artifact[1], artifact[0], artifact[1]
                )
            except ValueError as exc:
                error = str(exc)

    exit_code = process.returncode
    return ExecutionResult(
        ok=error is None and exit_code == 0,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
        exit_code=exit_code,
        error=error,
        artifact=artifact_payload,
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
    artifact = _artifact_spec(request.get("artifact"))
    skills = _skill_names(request.get("skills"))
    if skills and artifact is None:
        raise ValueError("skills require an artifact request")
    result = run_code(
        code,
        stdin,
        Limits.from_request(request.get("limits")),
        artifact=artifact,
        skills=skills,
    )
    return {"version": 1, **result.as_dict()}


def encode_response(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
