"""Broker dispatch for durable Tool invocations."""

import asyncio
import logging

from app.infrastructure.celery import celery_app
from app.infrastructure.config import Settings
from app.infrastructure.errors import log_error
from app.infrastructure.logger import get_logger, log_event

logger = get_logger(__name__)


async def enqueue_tool_invocation(invocation_id: str, settings: Settings) -> None:
    celery_app.conf.update(broker_url=settings.celery_broker_url)
    try:
        await asyncio.to_thread(
            celery_app.send_task,
            "app.tools.run",
            args=(invocation_id,),
        )
    except Exception as exc:
        log_error(
            logger,
            "Tool invocation dispatch deferred to recovery beat.",
            exc,
            tool_invocation_id=invocation_id,
        )
    else:
        log_event(
            logger,
            logging.INFO,
            "Tool invocation queued.",
            tool_invocation_id=invocation_id,
        )


__all__ = ["enqueue_tool_invocation"]
