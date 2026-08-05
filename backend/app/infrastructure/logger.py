"""Global logging setup for NexaFlow.

Every runtime process (API, Celery worker, Celery beat) initializes logging
through `setup_logging()`, so all log lines share one format and carry the
project name. Errors go through `app.infrastructure.errors.log_error`, which
tags each line with whether the failure comes from this project (`internal`)
or from an upstream service (`external`).
"""

import logging
import sys
from typing import Any

PROJECT_NAME = "NexaFlow"

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(project)s | %(name)s | %(message)s"


class _ProjectNameFilter(logging.Filter):
    """Injects the project name into every record so the format can render it."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.project = PROJECT_NAME
        return True


def setup_logging(level: int | str = logging.INFO) -> None:
    """Install the NexaFlow handler on the root logger.

    Idempotent: replaces any existing root handlers (including uvicorn's
    default one) so the project-tagged format applies to every app logger.
    Uvicorn/Celery's own loggers keep their dedicated handlers.

    ``level`` accepts a logging level constant or its name (e.g. ``"INFO"``).
    """
    if isinstance(level, str):
        level = logging.getLevelNamesMapping()[level.upper()]
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler.addFilter(_ProjectNameFilter())
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str = "") -> logging.Logger:
    """Return a project-scoped logger, e.g. ``NexaFlow.app.main``.

    The project prefix keeps every logger grouped under the project name in
    log aggregators and makes the origin explicit on each line.
    """
    return logging.getLogger(f"{PROJECT_NAME}.{name}".rstrip("."))


def render_context(context: dict[str, Any]) -> str:
    """Render key=value pairs for structured log lines."""
    parts = [f"{key}={value}" for key, value in context.items()]
    return f" [{' '.join(parts)}]" if parts else ""


def log_event(
    logger: logging.Logger,
    level: int,
    message: str,
    **context: Any,
) -> None:
    """Log a structured event with key=value context pairs.

    Companion to ``app.infrastructure.errors.log_error`` for non-error
    events: every line carries the project tag and greppable context, e.g.
    ``Knowledge task started. [task_id=abc task_type=parse]``.
    """
    logger.log(level, f"{message}{render_context(context)}")
