"""Per-run approval preferences for Agent tool execution."""

from typing import Literal, TypeAlias

from app.domain.tools.runtime import TOOL_APPROVAL_EACH_CALL
from app.entities.runs import AgentRun
from app.entities.tools import ToolSnapshot

AgentApprovalMode: TypeAlias = Literal[
    "always_ask",
    "ask_risky",
    "full_access",
]

DEFAULT_AGENT_APPROVAL_MODE: AgentApprovalMode = "ask_risky"
AGENT_APPROVAL_MODES = frozenset({"always_ask", "ask_risky", "full_access"})


def normalize_agent_approval_mode(value: object) -> AgentApprovalMode:
    if isinstance(value, str) and value in AGENT_APPROVAL_MODES:
        return value  # type: ignore[return-value]
    return DEFAULT_AGENT_APPROVAL_MODE


def run_agent_approval_mode(run: AgentRun) -> AgentApprovalMode:
    return normalize_agent_approval_mode(run.application_snapshot.get("approval_mode"))


def agent_tool_requires_approval(
    mode: AgentApprovalMode,
    snapshot: ToolSnapshot,
) -> bool:
    """Apply interactive consent without weakening the frozen Tool policy."""
    if mode == "full_access":
        return False
    if mode == "always_ask":
        return snapshot.effect != "pure"
    return snapshot.approval == TOOL_APPROVAL_EACH_CALL


def agent_mcp_requires_approval(
    mode: AgentApprovalMode,
    policy_mode: str,
) -> bool:
    """Return whether an enabled legacy MCP call needs interactive consent."""
    if mode == "full_access":
        return False
    if mode == "always_ask":
        return policy_mode != "disabled"
    return policy_mode != "read_only"


__all__ = [
    "AGENT_APPROVAL_MODES",
    "DEFAULT_AGENT_APPROVAL_MODE",
    "AgentApprovalMode",
    "agent_mcp_requires_approval",
    "agent_tool_requires_approval",
    "normalize_agent_approval_mode",
    "run_agent_approval_mode",
]
