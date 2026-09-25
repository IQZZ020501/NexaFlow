"""Celery entrypoint without local execution; jobs run on the OpenSandbox host."""

import asyncio
import hashlib
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.infra.config.settings import Settings
from app.infra.db.session import configure_database, get_session_factory
from app.infra.queue.celery import worker_pool_for_platform
from app.infra.security.keyring import KEY_SPECS, initialize_secret_keys


def worker_pidfile(broker_url: str) -> Path:
    """Return a stable local lock path without embedding broker credentials."""
    parsed = urlsplit(broker_url)
    endpoint = f"{parsed.scheme}://{parsed.netloc.rsplit('@', 1)[-1]}{parsed.path}"
    identity = f"{Path(__file__).resolve().parents[1]}\0{endpoint}"
    fingerprint = hashlib.sha256(identity.encode()).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / f"nexaflow-celery-{fingerprint}.pid"


def worker_command(arguments: list[str], *, pidfile: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "celery",
        "-A",
        "app.infra.queue.celery:celery_app",
        "worker",
        "--beat",
        "--queues=celery,agents-legacy,agents-v2",
        "--loglevel=info",
        "--pool",
        worker_pool_for_platform(sys.platform),
        "--pidfile",
        str(pidfile),
        *arguments,
    ]


async def resolve_deployment_keys(settings: Settings) -> dict[str, str]:
    """Create or adopt the deployment keys before Celery replaces this process."""
    configure_database(settings, worker_process=True)
    return await initialize_secret_keys(
        settings,
        session_factory=get_session_factory(),
    )


def main() -> None:
    settings = Settings.from_env(require_bootstrap=False)
    if not settings.opensandbox_api_key:
        raise SystemExit(
            "OPENSANDBOX_API_KEY is required; no host execution fallback is available."
        )
    resolved = asyncio.run(resolve_deployment_keys(settings))
    # The Celery process inherits these, so a stored key never depends on this
    # process staying alive or on the .env values still being present.
    for spec in KEY_SPECS:
        os.environ[spec.environment_variable] = resolved[spec.name]
    os.execv(
        sys.executable,
        worker_command(
            sys.argv[1:],
            pidfile=worker_pidfile(settings.celery_broker_url),
        ),
    )


if __name__ == "__main__":
    main()
