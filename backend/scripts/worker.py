"""Celery entrypoint without local execution; jobs run on the OpenSandbox host.

``--role`` selects what one worker serves:

- ``all`` (default): every queue plus the embedded Beat, for local development.
- ``background``: knowledge, tool, email and storage jobs plus the embedded
  Beat. Run exactly one, because Beat must stay a singleton.
- ``agents``: Agent and Workflow runs on a thread pool. Runs mostly wait on
  model providers, so one process serves many of them; scale it horizontally.
"""

import argparse
import asyncio
import hashlib
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.infra.config.settings import Settings
from app.infra.db.session import configure_database, get_session_factory
from app.infra.queue.celery import worker_pool_for_platform
from app.infra.security.keyring import KEY_SPECS, initialize_secret_keys

BACKGROUND_QUEUES = ("celery",)
AGENT_QUEUES = ("agents-legacy", "agents-v2")
WORKER_ROLES = ("all", "background", "agents")
# Worker sessions use NullPool, so this also bounds the PostgreSQL connections
# one Agent worker opens against the server default max_connections of 100.
AGENT_WORKER_CONCURRENCY = 32


@dataclass(frozen=True)
class WorkerRole:
    queues: tuple[str, ...]
    beat: bool
    pool: str
    concurrency: int | None = None


def worker_role(name: str, platform: str = sys.platform) -> WorkerRole:
    if name == "all":
        return WorkerRole(
            BACKGROUND_QUEUES + AGENT_QUEUES,
            beat=True,
            pool=worker_pool_for_platform(platform),
        )
    if name == "background":
        return WorkerRole(
            BACKGROUND_QUEUES,
            beat=True,
            pool=worker_pool_for_platform(platform),
        )
    if name == "agents":
        return WorkerRole(
            AGENT_QUEUES,
            beat=False,
            pool="threads",
            concurrency=AGENT_WORKER_CONCURRENCY,
        )
    raise ValueError(f"Unsupported worker role: {name}")


def parse_worker_arguments(arguments: list[str]) -> tuple[str, int | None, list[str]]:
    """Split the role and concurrency from arguments forwarded to Celery."""
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--role", choices=WORKER_ROLES, default="all")
    parser.add_argument("-c", "--concurrency", type=int)
    options, celery_arguments = parser.parse_known_args(arguments)
    return options.role, options.concurrency, celery_arguments


def worker_pidfile(broker_url: str, role: str = "all") -> Path:
    """Return a stable local lock path without embedding broker credentials."""
    parsed = urlsplit(broker_url)
    endpoint = f"{parsed.scheme}://{parsed.netloc.rsplit('@', 1)[-1]}{parsed.path}"
    identity = f"{Path(__file__).resolve().parents[1]}\0{endpoint}\0{role}"
    fingerprint = hashlib.sha256(identity.encode()).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / f"nexaflow-celery-{fingerprint}.pid"


def worker_command(
    arguments: list[str],
    *,
    pidfile: Path,
    role: WorkerRole,
    concurrency: int | None = None,
) -> list[str]:
    concurrency = concurrency or role.concurrency
    return [
        sys.executable,
        "-m",
        "celery",
        "-A",
        "app.infra.queue.celery:celery_app",
        "worker",
        *(["--beat"] if role.beat else []),
        f"--queues={','.join(role.queues)}",
        "--loglevel=info",
        "--pool",
        role.pool,
        *([f"--concurrency={concurrency}"] if concurrency else []),
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
    role_name, concurrency, celery_arguments = parse_worker_arguments(sys.argv[1:])
    role = worker_role(role_name)
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
            celery_arguments,
            pidfile=worker_pidfile(settings.celery_broker_url, role_name),
            role=role,
            concurrency=concurrency,
        ),
    )


if __name__ == "__main__":
    main()
