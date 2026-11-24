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

DEFAULT_AGENT_APPROVAL_MODE: AgentApprovalMode = "always_ask"
AGENT_APPROVAL_MODES = frozenset({"always_ask", "ask_risky", "full_access"})


def normalize_agent_approval_mode(value: object) -> AgentApprovalMode:
    if isinstance(value, str) and value in AGENT_APPROVAL_MODES:
        return value  # type: ignore[return-value]
    return DEFAULT_AGENT_APPROVAL_MODE


def run_agent_approval_mode(run: AgentRun) -> AgentApprovalMode:
    if run.access_source == "api":
        # Machine callers cannot resolve interactive consent. The frozen Tool
        # policy and API preflight still reject non-auto or unsafe tools.
        return "ask_risky"
    return normalize_agent_approval_mode(run.application_snapshot.get("approval_mode"))


def model_decides_mcp_approval(run: AgentRun) -> bool:
    """Only new interactive Runs delegate individual MCP decisions to the model."""
    return (
        run.access_source in {"console", "public", "automation"}
        and run.application_snapshot.get("mcp_approval_version") == 2
        and run_agent_approval_mode(run) == "ask_risky"
    )


def agent_tool_requires_approval(
    mode: AgentApprovalMode,
    snapshot: ToolSnapshot,
    *,
    model_decides_mcp: bool = False,
    model_requires_approval: bool | None = None,
) -> bool:
    """Apply interactive consent without weakening the frozen Tool policy."""
    if mode == "full_access":
        return False
    if mode == "always_ask":
        return snapshot.kind in {"mcp", "integration"} or snapshot.effect != "pure"
    if snapshot.kind in {"mcp", "integration"} and model_decides_mcp:
        return model_requires_approval is not False
    return snapshot.approval == TOOL_APPROVAL_EACH_CALL


def agent_mcp_requires_approval(
    mode: AgentApprovalMode,
    policy_mode: str,
    *,
    model_decides_mcp: bool = False,
    model_requires_approval: bool | None = None,
) -> bool:
    """Return whether an enabled legacy MCP call needs interactive consent."""
    if mode == "full_access":
        return False
    if mode == "always_ask":
        return policy_mode != "disabled"
    if model_decides_mcp:
        return model_requires_approval is not False
    return policy_mode != "read_only"


__all__ = [
    "AGENT_APPROVAL_MODES",
    "DEFAULT_AGENT_APPROVAL_MODE",
    "AgentApprovalMode",
    "agent_mcp_requires_approval",
    "agent_tool_requires_approval",
    "model_decides_mcp_approval",
    "normalize_agent_approval_mode",
    "run_agent_approval_mode",
]
