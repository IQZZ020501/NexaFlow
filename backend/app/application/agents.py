"""Agent use-case facade.

Public entry point for the agent API: CRUD use cases from the agents domain
plus run orchestration and tool construction split into
``app.application.agent_runs`` and ``app.application.agent_tools``.
"""

from app.application.agent_runs import (
    create_agent_run,
    enqueue_prepared_agent_run,
    execution_messages,
    get_agent_run_entity,
    get_agent_run_response,
    list_agent_runs,
    list_agent_run_tool_calls,
    prepare_agent_run,
    resolve_agent_tool_approval,
    stream_agent_run,
)
from app.application.agent_tools import (
    KnowledgeSearchInput,
    build_knowledge_search_tool,
    build_mcp_agent_tool,
    mcp_function_name,
    run_to_response,
    safe_agent_error,
)
from app.shareddomain.agents.services import (
    ACTIVE_STATUS,
    accessible_agent_knowledge_bases,
    can_edit_agent,
    create_agent,
    delete_agent,
    get_agent,
    get_agent_model,
    get_agent_response,
    list_agents,
    update_agent,
)

__all__ = [
    "ACTIVE_STATUS",
    "KnowledgeSearchInput",
    "accessible_agent_knowledge_bases",
    "build_knowledge_search_tool",
    "build_mcp_agent_tool",
    "can_edit_agent",
    "create_agent",
    "create_agent_run",
    "delete_agent",
    "execution_messages",
    "enqueue_prepared_agent_run",
    "get_agent",
    "get_agent_model",
    "get_agent_response",
    "get_agent_run_response",
    "get_agent_run_entity",
    "list_agent_runs",
    "list_agent_run_tool_calls",
    "list_agents",
    "mcp_function_name",
    "prepare_agent_run",
    "resolve_agent_tool_approval",
    "run_to_response",
    "safe_agent_error",
    "stream_agent_run",
    "update_agent",
]
