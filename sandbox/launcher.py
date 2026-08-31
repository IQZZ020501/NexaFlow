"""Linux namespace and chroot launcher for the sandbox broker."""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import fcntl
import os
from pathlib import Path
import shutil
import signal
import socket
import struct
import sys


CLONE_NEWNS = 0x00020000
CLONE_NEWUTS = 0x04000000
CLONE_NEWIPC = 0x08000000
CLONE_NEWPID = 0x20000000
CLONE_NEWNET = 0x40000000
MS_RDONLY = 1
MS_NOSUID = 2
MS_NODEV = 4
MS_NOEXEC = 8
MS_REMOUNT = 32
MS_BIND = 4096
MS_REC = 16384
MS_PRIVATE = 1 << 18
MNT_DETACH = 2
PR_SET_PDEATHSIG = 1
PR_CAPBSET_DROP = 24
PR_SET_NO_NEW_PRIVS = 38
SIOCGIFFLAGS = 0x8913
SIOCSIFFLAGS = 0x8914
IFF_UP = 0x1
BROKER_CAPABILITIES = {0, 5, 6, 7}  # CHOWN, KILL, SETGID, SETUID

libc = ctypes.CDLL(None, use_errno=True)
libc.mount.argtypes = [
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_ulong,
    ctypes.c_char_p,
]


def _bytes(value: str | Path | None) -> bytes | None:
    return os.fsencode(value) if value is not None else None


def _raise_errno(operation: str) -> None:
    error_number = ctypes.get_errno()
    raise OSError(error_number, f"{operation}: {os.strerror(error_number)}")


def _mount(
    source: str | Path | None,
    target: str | Path,
    filesystem: str | None = None,
    flags: int = 0,
    data: str | None = None,
) -> None:
    if libc.mount(
        _bytes(source),
        _bytes(target),
        _bytes(filesystem),
        flags,
        _bytes(data),
    ) != 0:
        _raise_errno(f"mount {target}")


def _destination(root: Path, path: Path) -> Path:
    if not path.is_absolute():
        raise ValueError("Sandbox mount paths must be absolute.")
    return root / path.relative_to("/")


def _bind(
    root: Path,
    source: Path,
    destination: Path | None = None,
    *,
    read_only: bool,
) -> None:
    resolved = source.resolve(strict=True)
    target = _destination(root, destination or source)
    if resolved.is_dir():
        target.mkdir(parents=True, exist_ok=True)
        bind_flags = MS_BIND | MS_REC
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
        bind_flags = MS_BIND
    _mount(resolved, target, flags=bind_flags)
    if read_only:
        _mount(
            None,
            target,
            flags=MS_BIND | MS_REMOUNT | MS_RDONLY | MS_NOSUID | MS_NODEV,
        )


def _tmpfs(root: Path, path: Path, data: str, *, noexec: bool = True) -> None:
    target = _destination(root, path)
    target.mkdir(parents=True, exist_ok=True)
    flags = MS_NOSUID | MS_NODEV | (MS_NOEXEC if noexec else 0)
    _mount("tmpfs", target, "tmpfs", flags, data)


def _libcap() -> ctypes.CDLL:
    library = ctypes.util.find_library("cap")
    if library is None:
        raise RuntimeError("libcap is required for sandbox capability isolation.")
    result = ctypes.CDLL(library, use_errno=True)
    result.cap_from_text.argtypes = [ctypes.c_char_p]
    result.cap_from_text.restype = ctypes.c_void_p
    return result


def _limit_broker_capabilities(libcap: ctypes.CDLL) -> None:
    cap_last = int(Path("/proc/sys/kernel/cap_last_cap").read_text().strip())
    for capability in range(cap_last + 1):
        if capability in BROKER_CAPABILITIES:
            continue
        if libc.prctl(PR_CAPBSET_DROP, capability, 0, 0, 0) != 0:
            _raise_errno("drop sandbox capability")
    capabilities = libcap.cap_from_text(
        b"cap_chown,cap_kill,cap_setgid,cap_setuid=ep"
    )
    if not capabilities:
        _raise_errno("parse sandbox capabilities")
    try:
        if libcap.cap_set_proc(ctypes.c_void_p(capabilities)) != 0:
            _raise_errno("set sandbox capabilities")
    finally:
        libcap.cap_free(ctypes.c_void_p(capabilities))
    if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        _raise_errno("set sandbox no-new-privileges")


def _bring_loopback_up() -> None:
    """Enable only the namespace-local loopback used by the egress relay."""
    if sys.platform != "linux":  # pragma: no cover - Linux-only launcher
        return
    request = struct.pack("16sH22s", b"lo", 0, b"")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as control:
        try:
            response = fcntl.ioctl(control.fileno(), SIOCGIFFLAGS, request)
            flags = struct.unpack("16sH22s", response)[1]
            if flags & IFF_UP:
                return
            fcntl.ioctl(
                control.fileno(),
                SIOCSIFFLAGS,
                struct.pack("16sH22s", b"lo", flags | IFF_UP, b""),
            )
        except OSError as exc:  # pragma: no cover - Linux capability failure
            raise RuntimeError(f"failed to enable sandbox loopback: {exc}") from exc


def _prepare_root(
    root: Path,
    sandbox_root: Path,
    sandbox_python: Path,
    socket_path: Path,
    skills_dir: Path | None,
) -> str:
    root.mkdir(mode=0o700)
    _mount("tmpfs", root, "tmpfs", MS_NOSUID | MS_NODEV, "size=128m,mode=0755")
    for source in (Path("/usr"), Path("/lib"), Path("/lib64")):
        if source.exists():
            _bind(root, source, read_only=True)
    for source in (
        Path("/etc/ld.so.cache"),
        Path("/etc/passwd"),
        Path("/etc/group"),
        Path("/etc/ssl"),
        Path("/etc/fonts"),
        Path("/var/cache/fontconfig"),
    ):
        if source.exists():
            _bind(root, source, read_only=True)

    package_dir = sandbox_root / "sandbox"
    runtime_dir = sandbox_python.parent.parent
    _bind(root, package_dir, read_only=True)
    if runtime_dir != package_dir and package_dir not in runtime_dir.parents:
        _bind(root, runtime_dir, read_only=True)
    _bind(
        root,
        socket_path.parent,
        Path("/run/sandbox"),
        read_only=False,
    )
    if skills_dir is not None:
        _bind(
            root,
            skills_dir,
            Path("/opt/nexaflow-skills"),
            read_only=True,
        )

    _tmpfs(root, Path("/tmp"), "size=64m,mode=0711")
    _tmpfs(root, Path("/dev"), "size=1m,mode=0755")
    for device in ("null", "zero", "random", "urandom"):
        _bind(
            root,
            Path("/dev") / device,
            Path("/dev") / device,
            read_only=False,
        )
    (_destination(root, Path("/dev/shm"))).mkdir(mode=0o700)
    proc = _destination(root, Path("/proc"))
    proc.mkdir()
    _mount("proc", proc, "proc", MS_NOSUID | MS_NODEV | MS_NOEXEC)
    return f"/run/sandbox/{socket_path.name}"


def _child(
    root: Path,
    sandbox_root: Path,
    sandbox_python: Path,
    socket_path: Path,
    egress_socket: Path | None,
    skills_dir: Path | None,
    libcap: ctypes.CDLL,
) -> None:
    parent_pid = os.getppid()
    if libc.prctl(PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0) != 0:
        _raise_errno("set sandbox parent-death signal")
    if os.getppid() != parent_pid:
        raise RuntimeError("Sandbox launcher parent exited.")
    if egress_socket is not None:
        _bring_loopback_up()
    inside_socket = _prepare_root(
        root,
        sandbox_root,
        sandbox_python,
        socket_path,
        skills_dir,
    )
    os.chroot(root)
    os.chdir(sandbox_root)
    _limit_broker_capabilities(libcap)
    environment = {
        "PATH": f"{sandbox_python.parent}:/usr/bin:/bin",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUNBUFFERED": "1",
    }
    if skills_dir is not None:
        environment["SANDBOX_SKILLS_DIR"] = "/opt/nexaflow-skills"
    inside_egress_socket = None
    if egress_socket is not None:
        inside_egress_socket = f"/run/sandbox/{egress_socket.name}"
        environment["SANDBOX_EGRESS_SOCKET"] = inside_egress_socket
    command = [
        str(sandbox_python),
        "-B",
        "-m",
        "sandbox.server",
        "--socket",
        inside_socket,
    ]
    if inside_egress_socket is not None:
        command.extend(["--egress-socket", inside_egress_socket])
    os.execve(
        sandbox_python,
        command,
        environment,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sandbox-root", required=True, type=Path)
    parser.add_argument("--sandbox-python", required=True, type=Path)
    parser.add_argument("--skills-dir", type=Path)
    parser.add_argument("--socket", required=True, type=Path)
    parser.add_argument("--egress-socket", type=Path)
    args = parser.parse_args()
    if sys.platform != "linux" or os.geteuid() != 0:
        parser.error("the hard sandbox launcher requires Linux root startup")
    for path in (
        args.sandbox_root,
        args.sandbox_python,
        args.socket.parent,
        args.egress_socket,
    ):
        if path is None:
            continue
        if not path.is_absolute():
            parser.error("sandbox paths must be absolute")
    if args.skills_dir is not None and not args.skills_dir.is_absolute():
        parser.error("skills path must be absolute")
    if args.egress_socket is not None:
        if args.egress_socket.parent != args.socket.parent:
            parser.error("egress socket must share the sandbox socket directory")
        if args.egress_socket.name == args.socket.name:
            parser.error("egress socket must differ from the sandbox socket")

    libcap = _libcap()
    root = Path("/run") / f"nexaflow-sandbox-root-{os.getpid()}"
    if root.exists():
        raise RuntimeError(f"Sandbox root already exists: {root}")
    flags = CLONE_NEWNS | CLONE_NEWUTS | CLONE_NEWIPC | CLONE_NEWPID | CLONE_NEWNET
    if libc.unshare(flags) != 0:
        _raise_errno("unshare sandbox namespaces")
    _mount(None, Path("/"), flags=MS_REC | MS_PRIVATE)
    child_pid = os.fork()
    if child_pid == 0:
        try:
            _child(
                root,
                args.sandbox_root,
                args.sandbox_python,
                args.socket,
                args.egress_socket,
                args.skills_dir,
                libcap,
            )
        except BaseException as exc:
            print(f"Sandbox isolation failed: {exc}", file=sys.stderr, flush=True)
            os._exit(127)

    def forward(signum: int, _frame: object) -> None:
        try:
            os.kill(child_pid, signum)
        except ProcessLookupError:
            pass

    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)
    try:
        while True:
            try:
                _pid, status = os.waitpid(child_pid, 0)
                return os.waitstatus_to_exitcode(status)
            except InterruptedError:
                continue
    finally:
        if libc.umount2(_bytes(root), MNT_DETACH) != 0 and ctypes.get_errno() != 22:
            _raise_errno("unmount sandbox root")
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
