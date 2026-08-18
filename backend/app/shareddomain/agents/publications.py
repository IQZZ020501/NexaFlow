"""Canonical immutable Agent publication snapshots."""

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any

from app.entities.agents import Agent
from app.entities.tools import ToolSnapshot
from app.schemas.agent import AgentInteractionConfig
from app.shareddomain.tools.runtime import (
    tool_snapshot_from_payload,
    tool_snapshot_payload,
)


AGENT_PUBLICATION_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class AgentPublication:
    name: str
    description: str
    instructions: str
    model_id: str
    knowledge_query_mode: str
    knowledge_base_ids: list[str]
    tools: list[ToolSnapshot]
    interaction_config: dict[str, Any]
    legacy_mcp_tools: list[dict[str, str]] = field(default_factory=list)

    @property
    def mcp_tools(self) -> list[dict[str, str]]:
        """Temporary projection for legacy Run readers during the migration window."""
        return self.legacy_mcp_tools or [
            {
                "server_id": str(tool.execution_spec["server_id"]),
                "tool_name": str(tool.execution_spec["tool_name"]),
            }
            for tool in self.tools
            if tool.kind == "mcp"
            and "server_id" in tool.execution_spec
            and "tool_name" in tool.execution_spec
        ]


def normalized_interaction_config(value: dict[str, Any]) -> dict[str, Any]:
    return AgentInteractionConfig.model_validate(value).model_dump(mode="json")


def build_agent_configuration_snapshot(agent: Agent) -> dict[str, Any]:
    return {
        "name": agent.name,
        "description": agent.description,
        "instructions": agent.instructions,
        "model_id": agent.model_id,
        "knowledge_query_mode": agent.knowledge_query_mode,
        "interaction_config": normalized_interaction_config(agent.interaction_config),
    }


def build_agent_resource_snapshot(
    knowledge_base_ids: list[str],
    tools: list[ToolSnapshot],
) -> dict[str, Any]:
    if len(set(knowledge_base_ids)) != len(knowledge_base_ids):
        raise ValueError("Agent knowledge base references must be unique.")
    if len({tool.tool_id for tool in tools}) != len(tools):
        raise ValueError("Agent Tool references must be unique.")
    return {
        "knowledge_base_ids": sorted(knowledge_base_ids),
        "tools": [
            tool_snapshot_payload(tool)
            for tool in sorted(tools, key=lambda item: (item.tool_id, item.version_id))
        ],
    }


def agent_publication_hash(
    configuration_snapshot: dict[str, Any],
    resource_snapshot: dict[str, Any],
) -> str:
    encoded = json.dumps(
        {
            "schema_version": AGENT_PUBLICATION_SCHEMA_VERSION,
            "configuration": configuration_snapshot,
            "resources": resource_snapshot,
        },
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def publication_from_snapshots(
    configuration_snapshot: dict[str, Any],
    resource_snapshot: dict[str, Any],
) -> AgentPublication:
    try:
        tools = [
            tool_snapshot_from_payload(item)
            for item in resource_snapshot.get("tools", [])
        ]
        return AgentPublication(
            name=str(configuration_snapshot["name"]),
            description=str(configuration_snapshot.get("description", "")),
            instructions=str(configuration_snapshot["instructions"]),
            model_id=str(configuration_snapshot["model_id"]),
            knowledge_query_mode=str(configuration_snapshot["knowledge_query_mode"]),
            knowledge_base_ids=[
                str(item) for item in resource_snapshot.get("knowledge_base_ids", [])
            ],
            tools=tools,
            interaction_config=normalized_interaction_config(
                configuration_snapshot.get("interaction_config", {})
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Agent publication snapshot is invalid.") from exc


__all__ = [
    "AGENT_PUBLICATION_SCHEMA_VERSION",
    "AgentPublication",
    "agent_publication_hash",
    "build_agent_configuration_snapshot",
    "build_agent_resource_snapshot",
    "normalized_interaction_config",
    "publication_from_snapshots",
]
