"""Trusted command supervisor. The model's shell always runs as UID 65532."""

import base64
import hashlib
import os
import resource
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath
from uuid import uuid4

try:
    from .artifact_check import inspect_artifact
except ImportError:
    import importlib.util
    _check_spec = importlib.util.spec_from_file_location("nexaflow_artifact_check", Path(__file__).with_name("artifact_check.py"))
    _check_module = importlib.util.module_from_spec(_check_spec)
    _check_spec.loader.exec_module(_check_module)
    inspect_artifact = _check_module.inspect_artifact

UID = 65532
WORKSPACE = Path("/workspace")
PROJECT_SOURCE_BASE = Path("/")
EXPORTS = Path("/tmp/nexaflow-exports")
SESSION = Path("/tmp/nexaflow-session")
MAX_LOG = 30 * 1024
MAX_FILE = 5 * 1024 * 1024
# The guest writable layer is shared with the execution host. Cap the
# workspace instead of warning: an unbounded workspace fills the host disk and
# breaks every other tenant, not just this Run.
MAX_WORKSPACE_BYTES = 512 * 1024 * 1024
MAX_WORKSPACE_FILES = 20000
PROJECT_IGNORED = frozenset({".git", ".venv", "venv", "node_modules", "__pycache__", ".cache", ".nexaflow"})
MAX_PROJECT_FILES = 64
MAX_PROJECT_BYTES = 64 * 1024 * 1024
WORKSPACE_CHECK_SECONDS = 0.2
# Export directories are read once by the backend right after the command
# returns. Keep a small window so an in-flight read is never truncated, then
# reclaim the rest.
KEPT_EXPORT_DIRECTORIES = 3


class BoundedLog:
    def __init__(self, limit):
        self.limit = limit
        self.head = bytearray()
        self.tail = bytearray()
        self.total = 0

    def append(self, data):
        self.total += len(data)
        missing = self.limit // 2 - len(self.head)
        self.head.extend(data[:missing])
        self.tail.extend(data[missing:])
        del self.tail[:max(0, len(self.tail) - self.limit // 2)]

    def text(self):
        marker = b"\n[output truncated]\n" if self.total > self.limit else b""
        content = bytes(self.head) + marker + bytes(self.tail)
        if len(content) > self.limit:
            content = bytes(self.head) + marker + bytes(self.tail[-(self.limit - len(self.head) - len(marker)):])
        return content.decode("utf-8", errors="replace").encode("utf-8")[:self.limit].decode("utf-8", errors="ignore")


def kill_user_processes():
    """Separate sessions cannot escape this UID sweep; supervisor stays root."""
    for _ in range(5):
        found = False
        for directory in Path("/proc").iterdir():
            if not directory.name.isdecimal():
                continue
            try:
                fields = dict(line.split(":", 1) for line in (directory / "status").read_text().splitlines() if ":" in line)
                if int(fields["Uid"].split()[0]) == UID and not fields["State"].strip().startswith("Z"):
                    os.kill(int(directory.name), signal.SIGKILL)
                    found = True
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                pass
        if not found:
            return
        time.sleep(0.02)
    raise RuntimeError("Command user processes could not be stopped.")


def _child_limits(seconds):
    resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_NOFILE, (64,) * 2)
    resource.setrlimit(resource.RLIMIT_NPROC, (64,) * 2)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.setgroups([])
    os.setgid(UID)
    os.setuid(UID)


def _snapshot(outputs, *, excluded=frozenset()):
    files = {}
    if outputs.is_symlink() or not outputs.is_dir():
        return files
    for parent, directories, names in os.walk(outputs, followlinks=False):
        directories[:] = [name for name in directories if name not in excluded and not (Path(parent) / name).is_symlink()]
        for name in names:
            if name in excluded:
                continue
            path = Path(parent) / name
            info = path.lstat()
            if stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                files[path.relative_to(outputs).as_posix()] = (info.st_size, info.st_mtime_ns, info.st_ino)
    return files


def _workspace_usage():
    """Complete byte and file counts, without following symlinks.

    Quota enforcement compares samples, so truncated totals cannot distinguish
    a growing workspace from cleanup that is still above the limit.
    """
    total = 0
    files = 0
    for parent, directories, names in os.walk(WORKSPACE, followlinks=False):
        directories[:] = [
            name for name in directories if not (Path(parent) / name).is_symlink()
        ]
        for name in names:
            try:
                info = (Path(parent) / name).lstat()
            except OSError:
                continue
            if not stat.S_ISREG(info.st_mode):
                continue
            total += info.st_size
            files += 1
    return total, files


def _prune_exports() -> None:
    """Drop export directories older than the retained window."""
    EXPORTS.mkdir(mode=0o700, exist_ok=True)
    directories = []
    for child in EXPORTS.iterdir():
        if child.is_symlink() or not child.is_dir():
            continue
        try:
            directories.append((child.stat().st_mtime, child))
        except OSError:
            continue
    directories.sort()
    for _, child in directories[:-KEPT_EXPORT_DIRECTORIES]:
        shutil.rmtree(child, ignore_errors=True)


def restore_files(files, *, project_role=None):
    """Copy authorized saved versions into a guest without following user links."""
    if os.geteuid() != 0:
        raise RuntimeError("File restoration requires the trusted supervisor.")
    if project_role not in {None, "source", "work"}:
        raise ValueError("Invalid project file role.")
    read_only = project_role == "source"
    if not isinstance(files, dict) or len(files) > 64:
        raise ValueError("Invalid conversation files.")
    decoded = {}
    for path, encoded in files.items():
        if (
            not isinstance(path, str) or not path or len(path) > 512
            or "\\" in path or PurePosixPath(path).is_absolute()
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or any(ord(character) < 32 or ord(character) == 127 for character in path)
            or not isinstance(encoded, str) or len(encoded) > (MAX_FILE + 2) // 3 * 4
        ):
            raise ValueError("Invalid conversation file path or content.")
        content = base64.b64decode(encoded, validate=True)
        if not 0 < len(content) <= MAX_FILE:
            raise ValueError("Conversation file exceeds 5 MiB.")
        decoded[path] = content
    if sum(map(len, decoded.values())) > MAX_FILE:
        raise ValueError("Conversation file transfer exceeds 5 MiB.")
    WORKSPACE.mkdir(mode=0o700, exist_ok=True)
    if WORKSPACE.is_symlink():
        raise ValueError("Invalid workspace directory.")
    os.chown(WORKSPACE, UID, UID)
    if _workspace_usage()[0] + sum(map(len, decoded.values())) > MAX_WORKSPACE_BYTES:
        raise ValueError("Conversation files exceed the workspace size limit.")
    for path, content in decoded.items():
        root = PROJECT_SOURCE_BASE if read_only else WORKSPACE
        prefix = ["project", "sources"] if read_only else ["project" if project_role == "work" else "outputs"]
        descriptors = [os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)]
        try:
            for name in [*prefix, *path.split("/")[:-1]]:
                try:
                    os.mkdir(name, mode=0o755 if read_only else 0o700, dir_fd=descriptors[-1])
                except FileExistsError:
                    pass
                descriptor = os.open(
                    name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptors[-1],
                )
                descriptors.append(descriptor)
                os.fchown(descriptor, 0 if read_only else UID, 0 if read_only else UID)
                if read_only:
                    os.fchmod(descriptor, 0o755)
            try:
                descriptor = os.open(
                    path.rsplit("/", 1)[-1],
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o444 if read_only else 0o600, dir_fd=descriptors[-1],
                )
            except FileExistsError:
                # A retried import must preserve an edit already made in this guest.
                info = os.stat(
                    path.rsplit("/", 1)[-1], dir_fd=descriptors[-1],
                    follow_symlinks=False,
                )
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError("Invalid existing conversation file.")
                if read_only:
                    descriptor = os.open(path.rsplit("/", 1)[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptors[-1])
                    with os.fdopen(descriptor, "rb") as stream:
                        if stream.read(MAX_FILE + 1) != content:
                            raise ValueError("Source project file differs from its frozen version.")
                continue
            with os.fdopen(descriptor, "wb") as stream:
                os.fchown(stream.fileno(), 0 if read_only else UID, 0 if read_only else UID)
                stream.write(content)
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)
    return {"ok": True, "exit_code": 0}


def execute(command, *, python_binary):
    text = command.get("command")
    seconds = command.get("timeout_seconds", 60)
    if not isinstance(text, str) or not text.strip() or len(text) > 32768 or "\x00" in text:
        raise ValueError("Invalid shell command.")
    if type(seconds) is not int or not 1 <= seconds <= 300:
        raise ValueError("Command timeout must be between 1 and 300 seconds.")
    if os.geteuid() != 0:
        raise RuntimeError("Command supervisor requires root inside the execution guest.")
    WORKSPACE.mkdir(mode=0o700, exist_ok=True)
    if WORKSPACE.is_symlink():
        raise ValueError("Invalid workspace directory.")
    os.chown(WORKSPACE, UID, UID)
    outputs = WORKSPACE / "outputs"
    if not outputs.exists():
        outputs.mkdir(mode=0o700)
        os.chown(outputs, UID, UID)
    EXPORTS.mkdir(mode=0o700, exist_ok=True)
    info = EXPORTS.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError("Invalid export directory.")
    before = _snapshot(outputs)
    project_mode = command.get("project") is True
    project_root = WORKSPACE / "project"
    if project_mode:
        if not project_root.exists():
            project_root.mkdir(mode=0o700)
        if project_root.is_symlink() or not project_root.is_dir():
            raise ValueError("Invalid project directory.")
        os.chown(project_root, UID, UID)
    env = {"PATH": f"{Path(python_binary).parent}:/usr/local/bin:/usr/bin:/bin", "HOME": str(WORKSPACE), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "NEXAFLOW_OUTPUT_DIR": str(outputs)}
    env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
    environments = sorted(path for path in SESSION.glob("[a-f0-9]" * 32) if path.is_dir())
    env["PYTHONPATH"] = os.pathsep.join(str(path / "python") for path in environments)
    env["NODE_PATH"] = os.pathsep.join(str(path / "node/node_modules") for path in environments)
    stdout, stderr = BoundedLog(MAX_LOG // 2), BoundedLog(MAX_LOG // 2)
    usage = _workspace_usage()
    process = subprocess.Popen(["/bin/bash", "--noprofile", "--norc", "-c", text], cwd=WORKSPACE, env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        preexec_fn=lambda: _child_limits(seconds))
    timed_out = False
    quota_exceeded = False
    try:
        with selectors.DefaultSelector() as selector:
            for stream, log in ((process.stdout, stdout), (process.stderr, stderr)):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, log)
            deadline = time.monotonic() + seconds
            quota_check = time.monotonic() + WORKSPACE_CHECK_SECONDS
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
                if time.monotonic() >= quota_check:
                    quota_check = time.monotonic() + WORKSPACE_CHECK_SECONDS
                    previous = usage
                    usage = _workspace_usage()
                    # Kill only a command that keeps growing the workspace.
                    # A shrinking workspace means cleanup, which must stay
                    # possible even while the quota is exceeded.
                    if (
                        usage[0] > MAX_WORKSPACE_BYTES and usage[0] > previous[0]
                    ) or (
                        usage[1] > MAX_WORKSPACE_FILES and usage[1] > previous[1]
                    ):
                        quota_exceeded = True
                        break
                for key, _ in selector.select(timeout=0.02):
                    data = os.read(key.fd, 65536)
                    if data:
                        key.data.append(data)
                    else:
                        selector.unregister(key.fileobj)
            # Descendants may hold pipes after the foreground shell has exited.
            for key in list(selector.get_map().values()):
                for _ in range(16):
                    try:
                        data = os.read(key.fd, 65536)
                    except BlockingIOError:
                        break
                    if not data:
                        break
                    key.data.append(data)
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        kill_user_processes()
        process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()
    after = _snapshot(outputs)
    exported = []
    warnings = []
    pending = []
    inspection_deadline = time.monotonic() + 8
    for relative, metadata in sorted(after.items()):
        if before.get(relative) == metadata:
            continue
        if len(pending) >= 8 or not 0 < metadata[0] <= MAX_FILE:
            warnings.append(f"Output omitted: {relative[:255]} (limit: 8 files, 5 MiB each).")
            continue
        path = outputs / relative
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                continue
            content = stream.read(MAX_FILE + 1)
        if not 0 < len(content) <= MAX_FILE:
            continue
        if time.monotonic() >= inspection_deadline:
            warnings.append(f"Output omitted: {relative[:255]}: File inspection budget exceeded; export it again.")
            continue
        inspection = inspect_artifact(Path(relative).name, content, python_binary=python_binary, timeout_seconds=inspection_deadline - time.monotonic())
        if inspection["status"] != "passed":
            warnings.append(f"Output omitted: {relative[:255]}: {inspection['error']}")
            continue
        pending.append((relative, content, inspection))
    if pending:
        destination = EXPORTS / uuid4().hex
        destination.mkdir(mode=0o700)
        for relative, content, inspection in pending:
            target = destination / str(len(exported))
            target.write_bytes(content)
            target.chmod(0o400)
            exported.append({"path": str(target), "relative_path": relative, "filename": Path(relative).name, "size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(), "inspection": inspection})
    project_changes = []
    project_error = ""
    if project_mode:
        try:
            after_project = _snapshot(project_root, excluded=PROJECT_IGNORED)
            if project_root.is_symlink() or not project_root.is_dir():
                raise ValueError("Project directory was removed or replaced.")
            if len(after_project) > MAX_PROJECT_FILES or sum(item[0] for item in after_project.values()) > MAX_PROJECT_BYTES:
                raise ValueError("Project exceeds 64 files or 64 MiB; remove temporary files.")
            # Reject unsupported paths as a whole snapshot; never mistake a
            # replaced file or link for a durable deletion.
            for parent, directories, names in os.walk(project_root, followlinks=False):
                directories[:] = [name for name in directories if name not in PROJECT_IGNORED]
                for name in [*directories, *names]:
                    if name in PROJECT_IGNORED:
                        continue
                    info = (Path(parent) / name).lstat()
                    if not stat.S_ISDIR(info.st_mode) and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
                        raise ValueError("Project files cannot contain links or special files.")
            changes = []
            # Export a complete bounded work tree. Comparing only this command's
            # before/after loses edits after a rejected or interrupted DB save.
            # The host compares hashes with the Run's durable version cursor.
            for relative in sorted(after_project):
                descriptor = os.open(project_root / relative, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(descriptor, "rb") as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= MAX_FILE:
                        raise ValueError("Each project file must be a regular file between 1 byte and 5 MiB.")
                    content = stream.read(MAX_FILE + 1)
                if not 0 < len(content) <= MAX_FILE:
                    raise ValueError("Project file exceeds 5 MiB.")
                changes.append((relative, content))
            if changes:
                if not pending:
                    destination = EXPORTS / uuid4().hex
                    destination.mkdir(mode=0o700)
                for relative, content in changes:
                    target = destination / str(len(exported) + sum(not item.get("deleted") for item in project_changes))
                    target.write_bytes(content)
                    target.chmod(0o400)
                    project_changes.append({"path": str(target), "relative_path": relative, "deleted": False, "size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
        except (OSError, ValueError) as exc:
            project_changes = []
            project_error = str(exc)[:300]
    _prune_exports()
    total, files = _workspace_usage()
    if quota_exceeded:
        warnings.append(
            "Workspace exceeded its size limit while writing; the command was "
            "stopped. Remove temporary files before continuing."
        )
    elif total > MAX_WORKSPACE_BYTES or files > MAX_WORKSPACE_FILES:
        warnings.append(
            "Workspace exceeds its size limit; remove temporary files before continuing."
        )
    return {"ok": True, "exit_code": 125 if quota_exceeded else 124 if timed_out else process.returncode,
        "timed_out": timed_out, "quota_exceeded": quota_exceeded,
        "stdout": stdout.text(), "stderr": stderr.text(), "truncated": stdout.total > MAX_LOG // 2 or stderr.total > MAX_LOG // 2,
        "artifacts": exported, "warnings": warnings[:16],
        **({"project_changes": project_changes, "project_snapshot": not project_error, "project_error": project_error} if project_mode else {})}


def stop_stale():
    if os.geteuid() != 0:
        raise RuntimeError("Command cleanup requires root inside the guest.")
    for directory in Path("/proc").iterdir():
        if not directory.name.isdecimal() or int(directory.name) == os.getpid():
            continue
        try:
            arguments = (directory / "cmdline").read_bytes().split(b"\x00")
            if b"/opt/nexaflow/job.py" in arguments or b"/opt/nexaflow/mcp_bridge.py" in arguments:
                os.kill(int(directory.name), signal.SIGKILL)
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass
    kill_user_processes()


if __name__ == "__main__":
    if sys.argv[1:] != ["--stop-stale"]:
        raise ValueError("Unsupported supervisor operation.")
    stop_stale()
