from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time


def build_sandbox_command(
    *,
    sandbox_python: Path,
    sandbox_root: Path,
    socket_path: Path,
    hard_isolation: bool,
    skills_dir: Path | None,
) -> list[str]:
    server = [
        str(sandbox_python),
        "-B",
        "-m",
        "sandbox.server",
        "--socket",
        str(socket_path),
    ]
    if not hard_isolation:
        return server
    command = [
        str(sandbox_python),
        "-B",
        "-m",
        "sandbox.launcher",
        "--sandbox-root",
        str(sandbox_root),
        "--sandbox-python",
        str(sandbox_python),
    ]
    if skills_dir is not None:
        command.extend(["--skills-dir", str(skills_dir)])
    return [*command, "--socket", str(socket_path)]


def _sandbox_runtime() -> tuple[Path, Path]:
    configured = os.environ.get("SANDBOX_ROOT", "").strip()
    candidates = [
        Path(configured) if configured else None,
        Path("/opt/sandbox"),
        Path(__file__).resolve().parents[2],
    ]
    sandbox_root = next(
        (
            candidate.resolve()
            for candidate in candidates
            if candidate is not None and (candidate / "sandbox" / "server.py").is_file()
        ),
        None,
    )
    if sandbox_root is None:
        raise RuntimeError("Sandbox source directory was not found.")
    configured_python = os.environ.get("SANDBOX_PYTHON", "").strip()
    if configured_python:
        sandbox_python = Path(configured_python).resolve()
    else:
        sandbox_python = next(
            (
                candidate
                for candidate in (
                    sandbox_root / ".venv" / "bin" / "python",
                    sandbox_root / "sandbox" / ".venv" / "bin" / "python",
                )
                if candidate.is_file()
            ),
            sandbox_root / ".venv" / "bin" / "python",
        )
    if not sandbox_python.is_file():
        raise RuntimeError(
            "Sandbox runtime is missing; run `uv sync --project ../sandbox "
            "--no-install-project --frozen`."
        )
    return sandbox_root, sandbox_python


def _skills_directory() -> Path | None:
    configured = os.environ.get("SANDBOX_SKILLS_DIR", "").strip()
    if not configured:
        return None
    path = Path(configured)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise RuntimeError("SANDBOX_SKILLS_DIR must be an absolute real directory.")
    return path.resolve()


def _probe(socket_path: Path) -> bool:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(1)
            client.connect(str(socket_path))
            client.sendall(b'{"version":1,"type":"healthcheck"}\n')
            response = json.loads(client.makefile("rb").readline(4097))
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return response == {"version": 1, "ok": True, "status": "ready"}


def _wait_ready(process: subprocess.Popen[bytes], socket_path: Path) -> bool:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        if _probe(socket_path):
            return True
        time.sleep(0.1)
    return False


def _sandbox_self_check(socket_path: Path, *, hard_isolation: bool) -> bool:
    isolation_checks = ""
    if hard_isolation:
        isolation_checks = (
            "assert not os.path.exists('/app')\n"
            "assert not os.path.exists('/data')\n"
            "assert 'DATABASE_URL' not in os.environ\n"
            "probe = socket.socket()\n"
            "probe.settimeout(0.2)\n"
            "try:\n"
            "    probe.connect(('1.1.1.1', 53))\n"
            "except OSError:\n"
            "    pass\n"
            "else:\n"
            "    raise AssertionError('sandbox network is reachable')\n"
            "finally:\n"
            "    probe.close()\n"
        )
    request = {
        "code": (
            "import os, socket\n"
            f"{isolation_checks}"
            "from docx import Document\n"
            "document = Document()\n"
            "document.add_paragraph('NexaFlow sandbox ready')\n"
            "document.save(os.environ['NEXAFLOW_OUTPUT_PATH'])\n"
        ),
        "artifact": {"format": "docx", "filename": "self-check.docx"},
    }
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(10)
            client.connect(str(socket_path))
            client.sendall((json.dumps(request) + "\n").encode())
            response = json.loads(client.makefile("rb").readline(8 * 1024 * 1024))
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return response.get("ok") is True and response.get("artifact", {}).get(
        "format"
    ) == "docx"


def _stop(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _drop_linux_capabilities() -> None:
    if sys.platform != "linux" or os.geteuid() != 0:
        return
    libc = ctypes.CDLL(None, use_errno=True)
    cap_last = int(Path("/proc/sys/kernel/cap_last_cap").read_text().strip())
    for capability in range(cap_last + 1):
        if libc.prctl(24, capability, 0, 0, 0) != 0:  # PR_CAPBSET_DROP
            error_number = ctypes.get_errno()
            raise OSError(error_number, os.strerror(error_number))

    library = ctypes.util.find_library("cap")
    if library is None:
        raise RuntimeError("libcap is required to drop Worker capabilities.")
    libcap = ctypes.CDLL(library, use_errno=True)
    libcap.cap_init.restype = ctypes.c_void_p
    capabilities = libcap.cap_init()
    if not capabilities:
        raise RuntimeError("Failed to initialize an empty capability set.")
    try:
        if libcap.cap_set_proc(ctypes.c_void_p(capabilities)) != 0:
            error_number = ctypes.get_errno()
            raise OSError(error_number, os.strerror(error_number))
    finally:
        libcap.cap_free(ctypes.c_void_p(capabilities))
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))


def _celery_command(autoscale: str | None, loglevel: str) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "celery",
        "-A",
        "app.infrastructure.celery:celery_app",
        "worker",
        "--beat",
        "--queues=celery,agents-legacy,agents-v2",
        f"--loglevel={loglevel}",
    ]
    if autoscale:
        command.append(f"--autoscale={autoscale}")
    return command


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--autoscale")
    parser.add_argument("--loglevel", default="INFO")
    parser.add_argument("--sandbox-self-check", action="store_true")
    args = parser.parse_args()

    environment = os.environ.get("ENVIRONMENT", "development").lower()
    production = environment == "production"
    if os.name != "posix":
        print(
            "Native Windows is unsupported; run the backend and Worker in WSL2.",
            file=sys.stderr,
        )
        return 2
    if sys.platform not in {"darwin", "linux"}:
        print("The embedded code sandbox requires macOS or Linux.", file=sys.stderr)
        return 2
    if sys.platform == "linux" and os.geteuid() != 0:
        print(
            "Linux Worker requires root startup for namespace sandbox isolation.",
            file=sys.stderr,
        )
        return 2

    try:
        sandbox_root, sandbox_python = _sandbox_runtime()
        skills_dir = _skills_directory()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    temporary_socket_dir: Path | None = None
    if production:
        socket_path = Path(
            os.environ.get("WORKFLOW_SANDBOX_SOCKET", "/run/sandbox/sandbox.sock")
        )
        if not socket_path.is_absolute():
            print("WORKFLOW_SANDBOX_SOCKET must be absolute.", file=sys.stderr)
            return 2
        socket_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        temporary_socket_dir = Path(tempfile.mkdtemp(prefix="nexaflow-worker-sandbox-"))
        socket_path = temporary_socket_dir / "sandbox.sock"

    if production and (sys.platform != "linux" or os.geteuid() != 0):
        print(
            "Production Worker requires Linux root startup for the embedded sandbox.",
            file=sys.stderr,
        )
        return 2

    sandbox: subprocess.Popen[bytes] | None = None
    worker: subprocess.Popen[bytes] | None = None
    hard_isolation = sys.platform == "linux" and os.geteuid() == 0
    try:
        sandbox_environment = {
            "PATH": f"{sandbox_python.parent}:/usr/bin:/bin",
            "PYTHONUNBUFFERED": "1",
        }
        if skills_dir is not None:
            sandbox_environment["SANDBOX_SKILLS_DIR"] = str(skills_dir)

        def start(use_hard_isolation: bool) -> subprocess.Popen[bytes]:
            return subprocess.Popen(
                build_sandbox_command(
                    sandbox_python=sandbox_python,
                    sandbox_root=sandbox_root,
                    socket_path=socket_path,
                    hard_isolation=use_hard_isolation,
                    skills_dir=skills_dir,
                ),
                cwd=sandbox_root,
                env=sandbox_environment,
                close_fds=True,
                start_new_session=True,
            )

        sandbox = start(hard_isolation)
        if not _wait_ready(sandbox, socket_path):
            _stop(sandbox)
            print("Embedded sandbox failed to start.", file=sys.stderr)
            return 3
        if sys.platform == "darwin":
            print(
                "Development Worker is using macOS Seatbelt child isolation.",
                file=sys.stderr,
            )

        if args.sandbox_self_check:
            if not _sandbox_self_check(
                socket_path,
                hard_isolation=(hard_isolation or sys.platform == "darwin"),
            ):
                print("Embedded sandbox self-check failed.", file=sys.stderr)
                return 4
            print("embedded sandbox self-check passed")
            return 0

        if hard_isolation:
            _drop_linux_capabilities()
        worker_environment = os.environ.copy()
        worker_environment["WORKFLOW_SANDBOX_SOCKET"] = str(socket_path)
        worker = subprocess.Popen(
            _celery_command(args.autoscale, args.loglevel),
            env=worker_environment,
            close_fds=True,
        )

        def stop(_signum: int, _frame: object) -> None:
            _stop(worker)
            _stop(sandbox)

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        while True:
            worker_status = worker.poll()
            sandbox_status = sandbox.poll()
            if worker_status is not None:
                return worker_status
            if sandbox_status is not None:
                _stop(worker)
                print("Embedded sandbox exited while Worker was running.", file=sys.stderr)
                return sandbox_status or 1
            time.sleep(0.2)
    except KeyboardInterrupt:
        return 130
    finally:
        _stop(worker)
        _stop(sandbox)
        if temporary_socket_dir is not None:
            shutil.rmtree(temporary_socket_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
