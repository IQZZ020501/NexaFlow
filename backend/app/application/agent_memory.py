from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.agents import AgentRun
from app.infrastructure.repositories import agent as agent_repository

MAX_MEMORY_RUNS = 50
MAX_MEMORY_TURN_CHARS = 6000
MAX_MEMORY_TOTAL_CHARS = 60000


def format_conversation_memory(runs: list[AgentRun]) -> str:
    turns: list[str] = []
    total_chars = 0
    for run in runs:
        if len(turns) >= MAX_MEMORY_RUNS:
            break
        if run.status != "succeeded":
            continue
        goal = (run.goal or "").strip()[:MAX_MEMORY_TURN_CHARS]
        answer = (run.result or "").strip()[:MAX_MEMORY_TURN_CHARS]
        if not goal or not answer:
            continue
        turn = f"User: {goal}\nAgent: {answer}"
        if total_chars + len(turn) > MAX_MEMORY_TOTAL_CHARS:
            break
        turns.append(turn)
        total_chars += len(turn)
    return "\n\n".join(reversed(turns))


async def load_conversation_memory(
    db: AsyncSession,
    agent_id: str,
    user_id: str,
) -> str:
    runs = await agent_repository.list_agent_runs(
        db,
        agent_id,
        user_id,
        MAX_MEMORY_RUNS,
        status="succeeded",
    )
    return format_conversation_memory(runs)
