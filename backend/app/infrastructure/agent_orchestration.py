from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from sqlalchemy.engine import make_url

from app.infrastructure.config import Settings
from app.shareddomain.agents.runner import AgentOrchestrator


@asynccontextmanager
async def open_agent_orchestrator(
    settings: Settings,
) -> AsyncIterator[AgentOrchestrator]:
    serializer = JsonPlusSerializer(allowed_msgpack_modules=None)
    url = make_url(settings.database_url)
    if url.get_backend_name() != "postgresql":
        yield AgentOrchestrator(InMemorySaver(serde=serializer))
        return

    connection_string = url.set(drivername="postgresql").render_as_string(
        hide_password=False
    )
    async with AsyncPostgresSaver.from_conn_string(
        connection_string,
        serde=serializer,
    ) as checkpointer:
        await checkpointer.setup()
        yield AgentOrchestrator(checkpointer)
