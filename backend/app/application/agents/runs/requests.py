"""Client request identity, serialized by the existing application row lock."""

import hashlib
import json

from fastapi import HTTPException

from app.domain.agents.access.permissions import require_agent_view
from app.infra.db.repositories.agents import repository


async def replay_run_request(
    db, workspace_id, agent_id, actor, access_source, consumer_id, request_id, payload
):
    if request_id is None:
        return None, None
    if (
        not request_id
        or len(request_id) > 64
        or any(not (c.isascii() and (c.isalnum() or c in "_-")) for c in request_id)
    ):
        raise HTTPException(422, "Agent request id is invalid.")
    agent = await repository.lock_agent(db, agent_id)
    if agent is None or agent.workspace_id != workspace_id:
        raise HTTPException(404, "Agent not found.")
    if access_source == "console":
        await require_agent_view(db, agent, actor)
    fingerprint = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    previous = await repository.get_agent_run_by_request(
        db, workspace_id, agent_id, access_source, consumer_id, request_id
    )
    if previous is not None and previous.request_hash != fingerprint:
        raise HTTPException(409, "Agent request id was reused with different data.")
    return previous, fingerprint
