"""Start the complete NexaFlow local development stack."""

from __future__ import annotations

import os
import re
import secrets
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import tomllib

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
OPEN_SANDBOX_STATE_DIR = Path.home() / ".local" / "share" / "nexaflow-opensandbox"
OPEN_SANDBOX_CONFIG = OPEN_SANDBOX_STATE_DIR / "server.toml"
OPEN_SANDBOX_DEFAULT_URL = "http://127.0.0.1:8088"
OPEN_SANDBOX_DEFAULT_IMAGE = "nexaflow/execution:local"
OPEN_SANDBOX_HEADER = "OPEN-SANDBOX-API-KEY"
SENSITIVE_BACKEND_ENV_KEYS = {
    "DATABASE_URL",
    "JWT_SECRET_KEY",
    "MODEL_SECRET_KEY",
    "OPENSANDBOX_API_KEY",
    "POSTGRES_PASSWORD",
}

_PRINT_LOCK = threading.Lock()


class DevError(RuntimeError):
    """A local-development setup error with an actionable message."""


def log(message: str) -> None:
    with _PRINT_LOCK:
        print(message, flush=True)


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _write_private(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", text=True
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def set_env_value(path: Path, key: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    replacement = f"{key}={value}"
    found = False
    updated: list[str] = []
    for line in lines:
        if pattern.match(line):
            updated.append(replacement)
            found = True
        else:
            updated.append(line)
    if not found:
        if updated and updated[-1]:
            updated.append("")
        updated.append(replacement)
    _write_private(path, "\n".join(updated) + "\n")


def ensure_env_file() -> dict[str, str]:
    if not ENV_FILE.exists():
        if not ENV_EXAMPLE.exists():
            raise DevError(f"Missing environment template: {ENV_EXAMPLE}")
        _write_private(ENV_FILE, ENV_EXAMPLE.read_text(encoding="utf-8"))
        log("[setup] Created .env from .env.example")

    values = read_env(ENV_FILE)
    generated = False
    for key, placeholder in (
        ("JWT_SECRET_KEY", "replace-with-a-random-32-byte-jwt-secret"),
        ("MODEL_SECRET_KEY", "replace-with-a-random-32-byte-model-secret"),
    ):
        if not values.get(key) or values[key] == placeholder:
            set_env_value(ENV_FILE, key, secrets.token_urlsafe(48))
            generated = True
    if generated:
        log("[setup] Generated private local application secrets in .env")
    return read_env(ENV_FILE)


def _configured_server_key(path: Path) -> str:
    try:
        with path.open("rb") as stream:
            data = tomllib.load(stream)
        key = data["server"]["api_key"]
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        raise DevError(f"Invalid OpenSandbox configuration: {path}") from exc
    if not isinstance(key, str) or not key.strip():
        raise DevError(f"OpenSandbox configuration has no API key: {path}")
    return key


def is_managed_opensandbox_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        and port == 8088
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
        and not parsed.username
        and not parsed.password
    )


def run(command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    log(f"[setup] {shlex.join(command)}")
    try:
        subprocess.run(command, cwd=cwd, env=env, check=True)
    except subprocess.CalledProcessError as exc:
        raise DevError(f"Command failed with exit code {exc.returncode}: {shlex.join(command)}") from exc


def require_commands() -> None:
    missing = [name for name in ("docker", "uv", "bun") if shutil.which(name) is None]
    if missing:
        raise DevError(f"Install the missing local development commands: {', '.join(missing)}")
    try:
        subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        subprocess.run(
            ["docker", "compose", "version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise DevError("Docker Desktop/Engine is not running or Docker Compose v2 is unavailable.") from exc


def ensure_local_opensandbox(values: dict[str, str]) -> tuple[dict[str, str], bool]:
    url = values.get("OPENSANDBOX_URL", "").strip() or OPEN_SANDBOX_DEFAULT_URL
    managed = is_managed_opensandbox_url(url)
    if not managed:
        if not values.get("OPENSANDBOX_API_KEY", "").strip():
            raise DevError("OPENSANDBOX_API_KEY is required for the configured external OpenSandbox.")
        return values, False

    configured_key = _configured_server_key(OPEN_SANDBOX_CONFIG) if OPEN_SANDBOX_CONFIG.exists() else ""
    environment_key = values.get("OPENSANDBOX_API_KEY", "").strip()
    if configured_key and environment_key and configured_key != environment_key:
        raise DevError(
            "The local OpenSandbox key does not match .env. Keep the existing private "
            f"configuration at {OPEN_SANDBOX_CONFIG} and align OPENSANDBOX_API_KEY."
        )
    api_key = configured_key or environment_key or secrets.token_urlsafe(48)
    if environment_key != api_key:
        set_env_value(ENV_FILE, "OPENSANDBOX_API_KEY", api_key)
        log("[setup] Stored the local OpenSandbox key in .env")
    if values.get("OPENSANDBOX_URL", "").strip() != url:
        set_env_value(ENV_FILE, "OPENSANDBOX_URL", url)
    image = values.get("OPENSANDBOX_IMAGE", "").strip() or OPEN_SANDBOX_DEFAULT_IMAGE
    if values.get("OPENSANDBOX_IMAGE", "").strip() != image:
        set_env_value(ENV_FILE, "OPENSANDBOX_IMAGE", image)

    if not OPEN_SANDBOX_CONFIG.exists():
        configure_env = os.environ.copy()
        configure_env["OPENSANDBOX_API_KEY"] = api_key
        run(
            [
                sys.executable,
                str(ROOT / "deploy" / "opensandbox" / "configure.py"),
                "--development",
                "--state-dir",
                str(OPEN_SANDBOX_STATE_DIR),
            ],
            env=configure_env,
        )
    return read_env(ENV_FILE), True


def prepare(values: dict[str, str], *, local_opensandbox: bool) -> None:
    run(["uv", "sync", "--dev", "--frozen"], cwd=BACKEND)
    run(["bun", "install", "--frozen-lockfile"], cwd=FRONTEND)
    run(
        [
            "docker",
            "compose",
            "--env-file",
            str(ENV_FILE),
            "-f",
            str(ROOT / "deploy" / "docker-compose.yml"),
            "-f",
            str(ROOT / "deploy" / "docker-compose.dev.yml"),
            "up",
            "-d",
            "--build",
            "--wait",
            "db",
            "redis",
            "qdrant",
        ]
    )
    if local_opensandbox:
        image = values.get("OPENSANDBOX_IMAGE", "").strip() or OPEN_SANDBOX_DEFAULT_IMAGE
        if "@sha256:" in image:
            raise DevError("Local development OPENSANDBOX_IMAGE must be a buildable image tag.")
        run(
            [
                "docker",
                "build",
                "-f",
                str(ROOT / "deploy" / "dockerfiles" / "app.Dockerfile"),
                "--target",
                "sandbox-runtime",
                "-t",
                image,
                str(ROOT),
            ]
        )
    run(["uv", "run", "python", "-m", "alembic", "upgrade", "head"], cwd=BACKEND)


def _request_status(url: str, *, headers: dict[str, str] | None = None) -> int | None:
    try:
        request = Request(url, headers=headers or {})
        with urlopen(request, timeout=1) as response:
            return response.status
    except HTTPError as exc:
        return exc.code
    except (OSError, URLError):
        return None


def _port_available(port: int) -> bool:
    try:
        with socket.create_server(("127.0.0.1", port)):
            return True
    except OSError:
        return False


def development_port(name: str, default: int) -> int:
    configured = os.getenv(name, str(default))
    try:
        port = int(configured)
    except ValueError as exc:
        raise DevError(f"{name} must be an integer.") from exc
    if not 1 <= port <= 65535:
        raise DevError(f"{name} must be between 1 and 65535.")
    return port


def require_development_ports(api_port: int, frontend_port: int) -> None:
    if api_port == frontend_port:
        raise DevError("API and Frontend development ports must be different.")
    for label, port, variable in (
        ("API", api_port, "NEXAFLOW_DEV_API_PORT"),
        ("Frontend", frontend_port, "NEXAFLOW_DEV_FRONTEND_PORT"),
    ):
        if not _port_available(port):
            raise DevError(
                f"{label} port 127.0.0.1:{port} is already in use. Stop the old "
                f"process or choose another port with {variable}."
            )


@dataclass
class ManagedProcess:
    label: str
    process: subprocess.Popen[str]
    output_thread: threading.Thread

    @classmethod
    def start(
        cls,
        label: str,
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> ManagedProcess:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )

        def forward_output() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                log(f"[{label}] {line.rstrip()}")

        thread = threading.Thread(target=forward_output, daemon=True)
        thread.start()
        return cls(label, process, thread)

    def stop(self) -> None:
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait()
        self.output_thread.join(timeout=1)


def wait_for_http(
    label: str,
    url: str,
    *,
    process: ManagedProcess | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 120,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = _request_status(url, headers=headers)
        if status is not None and 200 <= status < 300:
            return
        if status in {401, 403}:
            raise DevError(f"{label} rejected the configured credentials.")
        if process is not None and process.process.poll() is not None:
            raise DevError(f"{label} exited with code {process.process.returncode} during startup.")
        time.sleep(0.25)
    raise DevError(f"Timed out waiting for {label}: {url}")


def start_stack(
    values: dict[str, str],
    *,
    local_opensandbox: bool,
    api_port: int,
    frontend_port: int,
) -> int:
    backend_env = os.environ.copy()
    for key in (
        "OPENSANDBOX_URL",
        "OPENSANDBOX_API_KEY",
        "OPENSANDBOX_IMAGE",
        "OPENSANDBOX_EGRESS_DOMAINS",
    ):
        if key in values:
            backend_env[key] = values[key]
    backend_env["PYTHONUNBUFFERED"] = "1"
    public_process_env = os.environ.copy()
    for key in SENSITIVE_BACKEND_ENV_KEYS:
        public_process_env.pop(key, None)
    public_process_env["PYTHONUNBUFFERED"] = "1"
    api_url = f"http://127.0.0.1:{api_port}"
    frontend_url = f"http://127.0.0.1:{frontend_port}"
    public_process_env["NEXAFLOW_API_PROXY"] = api_url
    public_process_env["PORT"] = str(frontend_port)

    opensandbox_url = values.get("OPENSANDBOX_URL", OPEN_SANDBOX_DEFAULT_URL).rstrip("/")
    opensandbox_key = values.get("OPENSANDBOX_API_KEY", "")
    sandbox_list_url = f"{opensandbox_url}/v1/sandboxes"
    sandbox_headers = {OPEN_SANDBOX_HEADER: opensandbox_key}
    managed: list[ManagedProcess] = []
    try:
        sandbox_status = _request_status(sandbox_list_url, headers=sandbox_headers)
        if sandbox_status in {401, 403}:
            raise DevError("The running OpenSandbox rejected OPENSANDBOX_API_KEY.")
        if sandbox_status is None:
            if not local_opensandbox:
                raise DevError(f"Configured OpenSandbox is unavailable: {opensandbox_url}")
            sandbox = ManagedProcess.start(
                "sandbox",
                [
                    "uv",
                    "tool",
                    "run",
                    "--from",
                    "opensandbox-server==0.2.3",
                    "opensandbox-server",
                    "--config",
                    str(OPEN_SANDBOX_CONFIG),
                ],
                cwd=ROOT,
                env=public_process_env,
            )
            managed.append(sandbox)
            wait_for_http(
                "OpenSandbox",
                sandbox_list_url,
                process=sandbox,
                headers=sandbox_headers,
            )
        elif not 200 <= sandbox_status < 300:
            raise DevError(f"OpenSandbox readiness check returned HTTP {sandbox_status}.")
        else:
            log("[setup] Reusing the running OpenSandbox control plane")

        if not _port_available(api_port):
            raise DevError(f"API port 127.0.0.1:{api_port} is already in use.")
        if not _port_available(frontend_port):
            raise DevError(f"Frontend port 127.0.0.1:{frontend_port} is already in use.")

        api = ManagedProcess.start(
            "api",
            [
                "uv",
                "run",
                "python",
                "scripts/dev.py",
                "--host",
                "127.0.0.1",
                "--port",
                str(api_port),
            ],
            cwd=BACKEND,
            env=backend_env,
        )
        managed.append(api)
        wait_for_http("API", f"{api_url}/health", process=api)

        worker = ManagedProcess.start(
            "worker",
            ["uv", "run", "python", "scripts/worker.py"],
            cwd=BACKEND,
            env=backend_env,
        )
        managed.append(worker)

        frontend = ManagedProcess.start(
            "web",
            ["bun", "run", "dev"],
            cwd=FRONTEND,
            env=public_process_env,
        )
        managed.append(frontend)
        wait_for_http("Frontend", frontend_url, process=frontend)

        log("")
        log("NexaFlow is ready:")
        log(f"  Web:      {frontend_url}")
        log(f"  API:      {api_url}")
        log(f"  OpenAPI:  {api_url}/docs")
        log("Press Ctrl+C to stop OpenSandbox, API, Worker and Frontend.")

        while True:
            for item in managed:
                code = item.process.poll()
                if code is not None:
                    raise DevError(f"{item.label} exited unexpectedly with code {code}.")
            time.sleep(0.5)
    except KeyboardInterrupt:
        log("\nStopping NexaFlow development processes...")
        return 0
    finally:
        for item in reversed(managed):
            item.stop()


def main() -> int:
    if sys.platform == "win32":
        log("Native Windows is unsupported; run make dev inside WSL2.")
        return 2
    def terminate(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    try:
        require_commands()
        api_port = development_port("NEXAFLOW_DEV_API_PORT", 8000)
        frontend_port = development_port("NEXAFLOW_DEV_FRONTEND_PORT", 3000)
        require_development_ports(api_port, frontend_port)
        values = ensure_env_file()
        values, local_opensandbox = ensure_local_opensandbox(values)
        prepare(values, local_opensandbox=local_opensandbox)
        return start_stack(
            values,
            local_opensandbox=local_opensandbox,
            api_port=api_port,
            frontend_port=frontend_port,
        )
    except KeyboardInterrupt:
        log("\nDevelopment startup interrupted.")
        return 130
    except (DevError, OSError) as exc:
        log(f"\nDevelopment startup failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
