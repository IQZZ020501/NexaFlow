"""Quota concurrency, settlement, streaming and uncertain-request recovery."""

import asyncio
import os
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import tests.support  # noqa: F401
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domain.governance.models import ModelUsageReservation, WorkspaceTokenMonth
from app.domain.platform.models import Workspace, WorkspaceGovernance
from app.infra.db.base import Base
from app.infra.db.repositories.governance import tokens
from app.infra.models import metering
from app.ports.llm import ModelProviderError


class Provider:
    calls = 0
    failure = False
    missing_usage = False
    partial_usage = False
    parameters = None

    async def ainvoke(self, messages, **kwargs):
        self.calls += 1
        self.parameters = kwargs
        if self.failure:
            raise TimeoutError("unknown response")
        if self.partial_usage:
            return AIMessage(
                content="ok", response_metadata={"usage": {"prompt_tokens": 5}}
            )
        usage = (
            None
            if self.missing_usage
            else {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}
        )
        return AIMessage(content="ok", usage_metadata=usage)

    async def astream(self, messages, **kwargs):
        self.calls += 1
        yield AIMessageChunk(content="o")
        yield AIMessageChunk(
            content="k",
            usage_metadata={"input_tokens": 5, "output_tokens": 2, "total_tokens": 7},
        )

    def bind_tools(self, tools, **kwargs):
        return self


async def check(url):
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    workspace = "quota-" + uuid4().hex[:20]
    if url.startswith("sqlite"):
        async with engine.begin() as db:
            await db.run_sync(Base.metadata.create_all)
    try:
        async with factory() as db:
            db.add(
                Workspace(id=workspace, name=workspace, slug=workspace, description="")
            )
            await db.flush()
            db.add(
                WorkspaceGovernance(
                    workspace_id=workspace,
                    monthly_token_limit=100,
                    timezone="Asia/Shanghai",
                )
            )
            await db.commit()

        async def reserve(number):
            identity = str(uuid4())
            try:
                async with factory() as db:
                    await tokens.reserve(db, workspace, "model", identity, 30)
                    await db.commit()
                return identity
            except ModelProviderError:
                return None

        if url.startswith("postgresql"):
            results = await asyncio.gather(*(reserve(n) for n in range(12)))
        else:
            results = [await reserve(n) for n in range(12)]
        granted = [item for item in results if item]
        assert len(granted) == 3, granted
        for identity in granted:
            async with factory() as db:
                await tokens.settle(db, identity, 7)
                await tokens.settle(db, identity, 7)
                await db.commit()
        async with factory() as db:
            month = await db.scalar(
                select(WorkspaceTokenMonth).where(
                    WorkspaceTokenMonth.workspace_id == workspace
                )
            )
            assert (month.used_tokens, month.reserved_tokens) == (21, 0)
            governance = await db.get(WorkspaceGovernance, workspace)
            governance.monthly_token_limit = 20000
            await db.commit()

        registered = SimpleNamespace(
            id="model",
            workspace_id=workspace,
            provider_type="openai_compatible",
            meta={},
        )
        provider = Provider()
        model = metering.MeteredChatModel(provider, registered)
        with patch.object(metering, "get_session_factory", return_value=factory):
            await model.ainvoke([HumanMessage(content="hello")])
            assert provider.parameters["max_tokens"] == 4096
            chunks = [
                chunk
                async for chunk in model.bind(max_tokens=10).astream(
                    [HumanMessage(content="hi")]
                )
            ]
            assert "".join(chunk.content for chunk in chunks) == "ok"
            # A compaction call and a child call use the same provider boundary;
            # no Run aggregate is added a second time.
            await model.bind_tools([]).ainvoke([HumanMessage(content="summary")])
            provider.failure = True
            try:
                await model.ainvoke([HumanMessage(content="timeout")])
            except TimeoutError:
                pass
            else:
                raise AssertionError("Timeout disappeared")
            provider.failure = False
            provider.missing_usage = True
            await model.ainvoke([HumanMessage(content="missing usage")])
            async with factory() as db:
                month = await db.scalar(
                    select(WorkspaceTokenMonth).where(
                        WorkspaceTokenMonth.workspace_id == workspace
                    )
                )
                assert month.used_tokens == 42 and month.reserved_tokens > 16000
                records = list(
                    await db.scalars(
                        select(ModelUsageReservation).where(
                            ModelUsageReservation.workspace_id == workspace
                        )
                    )
                )
                uncertain = [row for row in records if row.state == "uncertain"]
                assert len(uncertain) == 2
                governance = await db.get(WorkspaceGovernance, workspace)
                governance.monthly_token_limit = (
                    month.used_tokens + month.reserved_tokens
                )
                await db.commit()
            calls = provider.calls
            try:
                await model.ainvoke([HumanMessage(content="blocked")])
            except ModelProviderError as exc:
                assert "quota exceeded" in str(exc)
            else:
                raise AssertionError("Quota did not block a real model call")
            assert calls == provider.calls
            # Only explicit usage reconciliation can release unknown occupancy.
            for row in uncertain:
                async with factory() as db:
                    await tokens.settle(db, row.id, 9)
                    await db.commit()
            async with factory() as db:
                governance = await db.get(WorkspaceGovernance, workspace)
                governance.monthly_token_limit = None
                await db.commit()
            provider.missing_usage = False
            await model.ainvoke([HumanMessage(content="unlimited")])
            assert "max_tokens" not in provider.parameters
            provider.partial_usage = True
            await model.ainvoke([HumanMessage(content="incomplete usage")])
            async with factory() as db:
                pending = list(
                    await db.scalars(
                        select(ModelUsageReservation).where(
                            ModelUsageReservation.workspace_id == workspace,
                            ModelUsageReservation.state == "uncertain",
                        )
                    )
                )
                assert len(pending) == 1, (
                    "A partial usage report released unknown occupancy"
                )
            started = asyncio.Event()

            class PendingProvider(Provider):
                async def ainvoke(self, messages, **kwargs):
                    started.set()
                    await asyncio.Future()

            request = asyncio.create_task(
                metering.MeteredChatModel(PendingProvider(), registered).ainvoke(
                    [HumanMessage(content="cancel after dispatch")]
                )
            )
            await started.wait()
            request.cancel()
            try:
                await request
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("Model cancellation disappeared")
            async with factory() as db:
                pending = list(
                    await db.scalars(
                        select(ModelUsageReservation).where(
                            ModelUsageReservation.workspace_id == workspace,
                            ModelUsageReservation.state == "uncertain",
                        )
                    )
                )
                assert len(pending) == 2 and all(
                    row.reserved_tokens > 0 for row in pending
                )
        with patch.object(
            tokens, "utc_now", return_value=datetime(2026, 12, 1, tzinfo=UTC)
        ):
            assert await reserve(99)
        print(
            "WORKSPACE_TOKEN_QUOTA_OK concurrency=12"
            if url.startswith("postgresql")
            else "WORKSPACE_TOKEN_QUOTA_OK sqlite"
        )
    finally:
        from sqlalchemy import delete

        async with factory() as db:
            for table in (
                ModelUsageReservation,
                WorkspaceTokenMonth,
                WorkspaceGovernance,
                Workspace,
            ):
                await db.execute(
                    delete(table).where(table.workspace_id == workspace)
                    if hasattr(table, "workspace_id")
                    else delete(table).where(table.id == workspace)
                )
            await db.commit()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(
        check(
            os.environ.get("NEXAFLOW_TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        )
    )
