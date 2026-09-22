"""Celery entrypoint without local execution; jobs run on the OpenSandbox host."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.infra.config.settings import Settings
from app.infra.queue.celery import worker_pool_for_platform


def worker_command(arguments: list[str]) -> list[str]:
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
        *arguments,
    ]


def main() -> None:
    settings = Settings.from_env(require_bootstrap=False)
    if not settings.opensandbox_api_key:
        raise SystemExit(
            "OPENSANDBOX_API_KEY is required; no host execution fallback is available."
        )
    os.execv(sys.executable, worker_command(sys.argv[1:]))


if __name__ == "__main__":
    main()
