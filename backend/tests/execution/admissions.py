"""An unknown ephemeral creation survives Redis loss in the SQL ledger."""

import asyncio
import os
from dataclasses import replace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import tests.support  # noqa: F401
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tests.support import settings

from app.adapters.execution import opensandbox
from app.adapters.execution.capacity import CapacityScope
from app.entities.defaults import utc_now
from app.infra.db.base import Base
from app.infra.db.repositories.execution import placements
from app.infra.execution import sessions
from app.ports.execution import (
    ExecutionBusy,
    ExecutionNotStarted,
    ExecutionScope,
    execution_scope,
)


async def check(redis_url):
    label = uuid4().hex
    config = replace(
        settings(),
        celery_broker_url=redis_url,
        opensandbox_api_key="test-key",
        opensandbox_image="test-image",
        opensandbox_url=f"http://ephemeral-{label}.example",
        opensandbox_max_sandboxes=1,
    )
    platform = opensandbox.OpenSandboxExecution(config)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    scope = execution_scope.set(ExecutionScope("ephemeral-" + label, "command"))
    try:
        with (
            patch.object(sessions, "get_session_factory", return_value=factory),
            patch.object(
                opensandbox.Sandbox,
                "create",
                AsyncMock(side_effect=RuntimeError("SDK wrapped an unknown creation")),
            ) as create,
        ):
            try:
                await platform.execute({}, timeout_seconds=5, max_output_bytes=1000)
            except ExecutionNotStarted:
                pass
            else:
                raise AssertionError("An unknown create was reported as successful.")
            create.assert_awaited_once()
            assert not execution_scope.get().attempt.unconfirmed
            async with factory() as db:
                recorded = await placements.active(db, utc_now())
            assert len(recorded) == 1 and recorded[0].run_id is None
            async with platform.capacity._redis() as redis:
                keys = [
                    key async for key in redis.scan_iter(platform.capacity.key + "*")
                ]
                if keys:
                    await redis.delete(*keys)
            try:
                await platform.execute({}, timeout_seconds=5, max_output_bytes=1000)
            except ExecutionBusy as exc:
                assert exc.reason == "host_capacity"
            else:
                raise AssertionError(
                    "Redis loss discarded a possibly live ephemeral guest."
                )
            create.assert_awaited_once()
            # The SDK is a test double and created nothing; retire only this
            # test's explicit intent after checking the recovery boundary.
            await platform.store.release_admission(recorded[0].id)
            await platform.capacity.release_reservation(
                recorded[0].id, CapacityScope(workspace_key=recorded[0].workspace_id)
            )
        print("EPHEMERAL_ADMISSION_RECOVERY_OK")
    finally:
        execution_scope.reset(scope)
        async with platform.capacity._redis() as redis:
            keys = [key async for key in redis.scan_iter(platform.capacity.key + "*")]
            if keys:
                await redis.delete(*keys)
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(check(os.environ["NEXAFLOW_TEST_REDIS_URL"]))
