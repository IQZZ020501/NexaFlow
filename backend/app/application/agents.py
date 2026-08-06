"""Agent use-case facade.

Public entry point for the agent API: CRUD use cases from the agents domain
plus run orchestration and tool construction split into
``app.application.agent_runs`` and ``app.application.agent_tools``.
"""

from app.application.agent_runs import (
    create_agent_run,
    execute_agent_run,
    execution_messages,
    list_agent_runs,
    prepare_agent_run,
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
    "execute_agent_run",
    "execution_messages",
    "get_agent",
    "get_agent_model",
    "get_agent_response",
    "list_agent_runs",
    "list_agents",
    "mcp_function_name",
    "prepare_agent_run",
    "run_to_response",
    "safe_agent_error",
    "stream_agent_run",
    "update_agent",
]
