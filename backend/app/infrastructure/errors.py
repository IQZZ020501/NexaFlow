"""Global error logging with internal/external source classification.

`log_error` is the single entry point for error logs. Every call tags the
line with ``source=internal`` when the failure is a bug in NexaFlow code, or
``source=external`` when an upstream service failed (LLM provider, MCP
server, Qdrant, Postgres, Redis, ...).

Classification rules, in order:

1. Instances of `ExternalServiceError` (our boundary wrappers) are external.
2. Exceptions whose class is defined in a third-party package are external.
3. Exceptions defined in the project or the standard library are internal,
   unless their cause chain leads back to an external failure (e.g. a
   pipeline wrapper re-raising an LLM API error with ``from exc``).

Service boundary code should raise `ExternalServiceError` subclasses so
upstream failures are tagged `external` even when wrapped deep inside
project code.
"""

import logging
import sys
from typing import Any, Literal

from app.infrastructure.logger import render_context

ErrorSource = Literal["internal", "external"]

_INTERNAL_MODULE_PREFIX = "app."


class ExternalServiceError(Exception):
    """Base class for errors caused by an upstream service.

    Subclass this at service boundaries (LLM providers, MCP servers, vector
    stores, ...) so `classify_error` tags those failures as `external`.
    """


def classify_error(exc: BaseException | None) -> ErrorSource:
    """Classify an exception as internal (NexaFlow code) or external (upstream)."""
    if exc is None:
        return "internal"

    if isinstance(exc, ExternalServiceError):
        return "external"

    module = type(exc).__module__ or ""
    if module.startswith(_INTERNAL_MODULE_PREFIX):
        # Our own wrapper may hide an external failure; follow the chain.
        for cause in (exc.__cause__, exc.__context__):
            if cause is not None and classify_error(cause) == "external":
                return "external"
        return "internal"

    if module == "builtins" or module.split(".", 1)[0] in sys.stdlib_module_names:
        return "internal"
    return "external"


def log_error(
    logger: logging.Logger,
    message: str,
    exc: BaseException | None = None,
    *,
    source: ErrorSource | None = None,
    **context: Any,
) -> None:
    """Log an error tagged with its source and structured context.

    ``source`` defaults to `classify_error(exc)`; pass it explicitly to
    override the automatic classification. ``context`` is rendered as
    ``key=value`` pairs after the message.
    """
    source = source or classify_error(exc)
    logger.error(
        f"{message} [source={source}]{render_context(context)}",
        exc_info=exc,
    )
