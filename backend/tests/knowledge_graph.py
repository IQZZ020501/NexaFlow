"""Persistent Evidence Graph RAG regression suite.

Run from backend/: uv run python -m tests.knowledge_graph
"""

import asyncio

import tests.support  # noqa: F401
from sqlalchemy import select, text

from app.infrastructure.base import Base
from app.infrastructure.session import get_engine, get_session_factory
from app.shareddomain.knowledge_graph.models import (
    KnowledgeGraphClaim,
    KnowledgeGraphEntity,
)


async def test_graph_database_constraints() -> None:
    async with get_engine().begin() as connection:
        await connection.execute(text("PRAGMA foreign_keys=ON"))
        await connection.run_sync(Base.metadata.create_all)
    async with get_session_factory()() as db:
        entity = await db.scalar(select(KnowledgeGraphEntity).limit(1))
        claim = await db.scalar(select(KnowledgeGraphClaim).limit(1))
        assert entity is None
        assert claim is None


async def main() -> None:
    await test_graph_database_constraints()
    print("OK: knowledge_graph")


if __name__ == "__main__":
    asyncio.run(main())
