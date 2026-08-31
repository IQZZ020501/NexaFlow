"""Run untrusted Python code with process and resource limits."""

from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any
from urllib.parse import urlsplit

from .egress import LocalEgressProxy

RUNNER_UID = int(os.environ.get("SANDBOX_RUNNER_UID", "65532"))
RUNNER_GID = int(os.environ.get("SANDBOX_RUNNER_GID", "65532"))
MAX_CODE_BYTES = 256 * 1024
MAX_STDIN_BYTES = 256 * 1024
MAX_ARTIFACT_BYTES = 5 * 1024 * 1024
MAX_SKILLS = 8
MAX_SKILL_FILES = 128
MAX_SKILL_BYTES = 2 * 1024 * 1024
MAX_REQUIREMENTS = 32
MAX_REQUIREMENTS_BYTES = 8 * 1024
MAX_REQUIREMENT_LENGTH = 256
MAX_PACKAGES_FILES = 10_000
MAX_PACKAGES_BYTES = 64 * 1024 * 1024
SKILL_INSTALL_TIMEOUT_SECONDS = 25
SKILL_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
PACKAGE_REQUIREMENT = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,127})"
    r"(?:\[[A-Za-z0-9_,.-]+\])?"
    r"(?:\s*(?:===|==|~=|!=|<=|>=|<|>)\s*[A-Za-z0-9*+!._-]+"
    r"(?:\s*,\s*(?:===|==|~=|!=|<=|>=|<|>)\s*[A-Za-z0-9*+!._-]+)*)?\Z"
)
ARTIFACT_FORMAT = re.compile(r"[a-z0-9][a-z0-9+_-]{0,31}\Z")
PR_SET_CHILD_SUBREAPER = 36
_LINUX_RUNS_LOCK = threading.Lock()
_LINUX_ACTIVE_RUNS = 0


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


@dataclass(frozen=True)
class SkillRuntime:
    entrypoint: Path
    artifact_format: str


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


def _skill_requirements(
    skills_path: Path,
    names: tuple[str, ...],
) -> tuple[tuple[str, ...], str | None]:
    requirements: list[str] = []
    seen: set[str] = set()
    for name in names:
        path = skills_path / name / "requirements.txt"
        if not path.exists():
            continue
        if path.is_symlink() or not path.is_file():
            return (), "skill_invalid"
        try:
            raw = path.read_bytes()
        except OSError:
            return (), "skill_invalid"
        if len(raw) > MAX_REQUIREMENTS_BYTES:
            return (), "skill_requirements_too_large"
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return (), "skill_requirements_invalid"
        for line in text.splitlines():
            requirement = line.strip()
            if not requirement or requirement.startswith("#"):
                continue
            if (
                len(requirement) > MAX_REQUIREMENT_LENGTH
                or requirement.startswith("-")
                or any(token in requirement for token in ("://", "@", "/", "\\", ";"))
                or not PACKAGE_REQUIREMENT.fullmatch(requirement)
            ):
                return (), "skill_requirements_invalid"
            if requirement not in seen:
                seen.add(requirement)
                requirements.append(requirement)
                if len(requirements) > MAX_REQUIREMENTS:
                    return (), "skill_requirements_too_many"
    return tuple(requirements), None


def _stage_skills(workdir: Path, names: tuple[str, ...]) -> tuple[Path, str | None]:
    target_root = workdir / "skills"
    target_root.mkdir()
    if not names:
        return target_root, None

    configured_root = os.environ.get("SANDBOX_SKILLS_DIR", "").strip()
    configured_path = (
        Path(configured_root)
        if configured_root
        else Path(__file__).with_name("skills")
    )
    try:
        source_root = configured_path.resolve(strict=True)
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
        manifest = resolved / "SKILL.md"
        if manifest.is_symlink() or not manifest.is_file():
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


def _skill_runtime(
    skills_path: Path,
    name: str,
) -> tuple[SkillRuntime | None, str | None]:
    skill_path = skills_path / name
    manifest_path = skill_path / "SKILL.md"
    try:
        text = manifest_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None, "skill_invalid"
    if not text.startswith("---\n"):
        return None, "skill_runtime_invalid"
    parts = text.split("---\n", 2)
    if len(parts) != 3:
        return None, "skill_runtime_invalid"

    fields: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key in {"entrypoint", "artifact-format"}:
            if key in fields:
                return None, "skill_runtime_invalid"
            fields[key] = value.strip()

    entrypoint_value = fields.get("entrypoint", "")
    artifact_format = fields.get("artifact-format", "")
    entrypoint = PurePosixPath(entrypoint_value)
    if (
        not entrypoint_value
        or entrypoint.is_absolute()
        or ".." in entrypoint.parts
        or entrypoint.suffix != ".py"
        or not ARTIFACT_FORMAT.fullmatch(artifact_format)
    ):
        return None, "skill_runtime_invalid"
    path = skill_path.joinpath(*entrypoint.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved_skill = skill_path.resolve(strict=True)
    except (FileNotFoundError, OSError):
        return None, "skill_runtime_invalid"
    if (
        path.is_symlink()
        or not resolved.is_file()
        or not resolved.is_relative_to(resolved_skill)
    ):
        return None, "skill_runtime_invalid"
    return SkillRuntime(resolved, artifact_format), None


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


def _installed_tree_size(path: Path) -> tuple[int, int, bool]:
    file_count = 0
    total_bytes = 0
    for current, directories, files in os.walk(path, followlinks=False):
        current_path = Path(current)
        if any((current_path / item).is_symlink() for item in (*directories, *files)):
            return file_count, total_bytes, False
        for filename in files:
            try:
                total_bytes += (current_path / filename).stat().st_size
            except OSError:
                return file_count, total_bytes, False
            file_count += 1
            if file_count > MAX_PACKAGES_FILES or total_bytes > MAX_PACKAGES_BYTES:
                return file_count, total_bytes, False
    return file_count, total_bytes, True


def _install_skill_dependencies(
    workdir: Path,
    skills_path: Path,
    names: tuple[str, ...],
    proxy_url: str | None,
    proxy_environment: dict[str, str],
) -> tuple[Path | None, str | None]:
    requirements, requirement_error = _skill_requirements(skills_path, names)
    if requirement_error is not None:
        return None, requirement_error
    if not requirements:
        return None, None
    if proxy_url is None:
        return None, "skill_network_unavailable"

    packages_path = workdir / "packages"
    packages_path.mkdir()
    if os.geteuid() == 0:  # pragma: no cover - requires root (CI Docker only)
        os.chown(packages_path, 0, RUNNER_GID)
        packages_path.chmod(0o770)
    environment = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(workdir),
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "PIP_CONFIG_FILE": "/dev/null",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "NEXAFLOW_ALLOW_SITE_PACKAGES": "1",
        **proxy_environment,
    }
    command = [
        sys.executable,
        "-I",
        "-B",
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--no-cache-dir",
        "--only-binary=:all:",
        "--target",
        str(packages_path),
        "--proxy",
        proxy_url,
        *requirements,
    ]
    try:
        process = subprocess.Popen(
            _sandboxed_child_command(command, workdir, proxy_url),
            cwd=workdir,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
            start_new_session=True,
            **(
                {
                    "user": RUNNER_UID,
                    "group": RUNNER_GID,
                    "extra_groups": [],
                    "umask": 0o077,
                }
                if os.geteuid() == 0
                else {}
            ),
        )
        try:
            stdout, stderr, error = _collect_output(
                process,
                64 * 1024,
                time.monotonic() + SKILL_INSTALL_TIMEOUT_SECONDS,
            )
            if error is None:
                process.wait()
        finally:
            _terminate(process)
            _terminate_linux_descendants()
    except (OSError, ValueError) as exc:
        return None, f"skill_dependency_install_failed:{exc}"

    if error is not None:
        return None, f"skill_dependency_install_failed:{error}"
    if process.returncode != 0:
        detail = (stderr or stdout).decode("utf-8", errors="replace").strip()
        detail = detail.splitlines()[-1][:500] if detail else "pip exited unsuccessfully"
        return None, f"skill_dependency_install_failed:{detail}"
    _file_count, _total_bytes, valid = _installed_tree_size(packages_path)
    if not valid:
        return None, "skill_dependencies_too_large"
    _restrict_read_only_tree(packages_path)
    return packages_path, None


def _read_artifact(path: Path, artifact_format: str, filename: str) -> dict[str, Any]:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ValueError(
            "artifact_missing: write the final file to output_path; "
            "do not use /tmp or another hard-coded path"
        ) from exc
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


def _sandboxed_child_command(
    command: list[str], workdir: Path, network_proxy: str | None = None
) -> list[str]:
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
    if network_proxy is not None:
        parsed_proxy = urlsplit(network_proxy)
        if parsed_proxy.hostname != "127.0.0.1" or parsed_proxy.port is None:
            raise ValueError("sandbox network proxy must use loopback")
        profile.append(
            f'(allow network-outbound (remote ip "localhost:{parsed_proxy.port}"))'
        )
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


@contextmanager
def _linux_run_scope():  # pragma: no cover - Linux CI Docker only
    global _LINUX_ACTIVE_RUNS
    if sys.platform != "linux":
        yield
        return

    with _LINUX_RUNS_LOCK:
        _LINUX_ACTIVE_RUNS += 1
    try:
        yield
    finally:
        with _LINUX_RUNS_LOCK:
            _LINUX_ACTIVE_RUNS -= 1
            if _LINUX_ACTIVE_RUNS == 0:
                _terminate_linux_descendants()


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
    code: str | None,
    stdin: str = "",
    limits: Limits | None = None,
    *,
    artifact: tuple[str, str] | None = None,
    skills: tuple[str, ...] = (),
    skill: str | None = None,
) -> ExecutionResult:
    """Execute a UTF-8 Python program and return bounded output."""

    if os.name != "posix":
        raise RuntimeError("the sandbox requires a POSIX host")
    if skill is None:
        if not isinstance(code, str):
            raise ValueError("code must be a string")
    elif (
        not isinstance(skill, str)
        or not SKILL_NAME.fullmatch(skill)
        or code is not None
        or skills
    ):
        raise ValueError("skill request is invalid")
    if not isinstance(stdin, str):
        raise ValueError("stdin must be a string")
    try:
        code_size = len(code.encode("utf-8")) if code is not None else 0
        stdin_size = len(stdin.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError("code and stdin must be valid UTF-8") from exc
    if code_size > MAX_CODE_BYTES:
        raise ValueError("code exceeds the 256 KiB limit")
    if stdin_size > MAX_STDIN_BYTES:
        raise ValueError("stdin exceeds the 256 KiB limit")
    limits = limits or Limits()
    _enable_linux_subreaper()
    staged_skill_names = (skill,) if skill is not None else skills

    with tempfile.TemporaryDirectory(prefix="nexaflow-sandbox-") as directory:
        workdir = Path(directory)
        code_path = workdir / "program.py"
        stdin_path = workdir / "stdin"
        if code is not None:
            code_path.write_text(code, encoding="utf-8")
        stdin_path.write_text(stdin, encoding="utf-8")
        skills_path, skill_error = _stage_skills(workdir, staged_skill_names)
        if skill_error is not None:
            return ExecutionResult(False, "", "", None, skill_error)
        if skill is not None:
            runtime, runtime_error = _skill_runtime(skills_path, skill)
            if runtime_error is not None or runtime is None:
                return ExecutionResult(False, "", "", None, runtime_error)
            if artifact is None:
                return ExecutionResult(False, "", "", None, "skill_artifact_required")
            if runtime.artifact_format != artifact[0]:
                return ExecutionResult(
                    False,
                    "",
                    "",
                    None,
                    "skill_artifact_format_invalid",
                )
            code_path = runtime.entrypoint
        if os.geteuid() == 0:  # pragma: no cover - requires root (CI Docker only)
            os.chown(workdir, 0, RUNNER_GID)
            os.chown(stdin_path, 0, RUNNER_GID)
            workdir.chmod(0o770)
            stdin_path.chmod(0o440)
            if skill is None:
                os.chown(code_path, 0, RUNNER_GID)
                code_path.chmod(0o440)
        else:
            stdin_path.chmod(0o400)
            if skill is None:
                code_path.chmod(0o400)
        _restrict_read_only_tree(skills_path)

        environment = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": str(workdir),
            "PYTHONHASHSEED": "0",
            "PYTHONNOUSERSITE": "1",
            "TMPDIR": str(workdir),
        }
        if artifact is not None or staged_skill_names:
            environment.update(
                {
                    "NEXAFLOW_ALLOW_SITE_PACKAGES": "1",
                }
            )
        if artifact is not None:
            environment["NEXAFLOW_OUTPUT_PATH"] = str(workdir / artifact[1])
        if staged_skill_names:
            environment["NEXAFLOW_SKILLS_DIR"] = str(skills_path)
        if skill is not None:
            environment["NEXAFLOW_SKILL_NAME"] = skill
        egress_socket = os.environ.get("SANDBOX_EGRESS_SOCKET", "").strip()
        egress_proxy: LocalEgressProxy | None = None
        proxy_url: str | None = None
        try:
            if egress_socket:
                egress_proxy = LocalEgressProxy(egress_socket)
                proxy_url = egress_proxy.start()
                environment.update(egress_proxy.environment())
            packages_path, package_error = _install_skill_dependencies(
                workdir,
                skills_path,
                staged_skill_names,
                proxy_url,
                egress_proxy.environment() if egress_proxy is not None else {},
            )
            if package_error is not None:
                return ExecutionResult(False, "", "", None, package_error)
            if packages_path is not None:
                environment["NEXAFLOW_PACKAGES_DIR"] = str(packages_path)
            child_path = Path(__file__).with_name("child.py")
            identity: dict[str, Any] = {}
            if os.geteuid() == 0:  # pragma: no cover - requires root (CI Docker only)
                identity = {
                    "user": RUNNER_UID,
                    "group": RUNNER_GID,
                    "extra_groups": [],
                    "umask": 0o077,
                }
            with stdin_path.open("rb") as input_stream, _linux_run_scope():
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
                    proxy_url,
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
        finally:
            if egress_proxy is not None:
                egress_proxy.close()

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
    skill = request.get("skill")
    stdin = request.get("stdin", "")
    if skill is None:
        if not isinstance(code, str):
            raise ValueError("code must be a string")
    elif (
        not isinstance(skill, str)
        or not SKILL_NAME.fullmatch(skill)
        or code is not None
        or request.get("skills") is not None
    ):
        raise ValueError("skill request is invalid")
    if not isinstance(stdin, str):
        raise ValueError("stdin must be a string")
    artifact = _artifact_spec(request.get("artifact"))
    skills = _skill_names(request.get("skills")) if skill is None else ()
    result = run_code(
        code,
        stdin,
        Limits.from_request(request.get("limits")),
        artifact=artifact,
        skills=skills,
        skill=skill,
    )
    return {"version": 1, **result.as_dict()}


def encode_response(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
