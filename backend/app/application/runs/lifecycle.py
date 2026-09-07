"""Agent run orchestration.

Sibling module of ``app.application.agents`` (which re-exports the public
surface): preparing, executing, streaming, and listing agent runs.
"""

import asyncio
from copy import deepcopy
import json
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.agents.tools.builder import (
    run_to_response,
)
from app.application.tools.runtime.service import preflight_tool_snapshot
from app.entities.agents import Agent, AgentPublicationVersion
from app.entities.runs import AgentRun
from app.entities.identity.user import User
from app.infra.agents.live_stream import (
    LIVE_EVENT_TYPES,
    AgentLiveStreamReader,
)
from app.infra.config.settings import Settings
from app.application.governance.service import enforce_workspace_run_quota
from app.entities.defaults import new_id, utc_now
from app.infra.db.repositories.agents import repository as agent_repository
from app.infra.db.repositories.tools import repository as tool_repository
from app.infra.db.session import get_session_factory
from app.schemas.agents.contracts import AgentRunResponse, AgentToolCallResponse
from app.domain.audit.services import record_audit_log
from app.domain.agents.service import (
    ACTIVE_STATUS,
    AgentPublication,
    agent_publication_from_version,
    get_agent,
    get_agent_model,
)
from app.domain.agents.access.permissions import require_agent_view
from app.domain.agents.models import (
    AGENT_RUN_SUCCEEDED_STATUS,
    agent_run_generation,
    queued_agent_run_status,
)
from app.domain.agents.access.publications import (
    AGENT_PUBLICATION_SCHEMA_VERSION,
    agent_publication_hash,
    build_agent_configuration_snapshot,
    build_agent_resource_snapshot,
)
from app.domain.tools.access.bindings import resolve_application_tool_snapshots
from app.domain.tools.runtime import (
    TOOL_APPROVAL_EACH_CALL,
    tool_snapshot_from_payload,
    tool_snapshot_payload,
)

AGENT_EVENT_PAGE_SIZE = 200




async def cancel_run_tree(db: AsyncSession, run_id: str) -> bool:
    now = utc_now()
    run_ids = await agent_repository.cancel_agent_run_tree(db, run_id, now)
    if not run_ids:
        return False
    await tool_repository.settle_cancelled_agent_tool_invocations(db, run_ids, now)
    return True
