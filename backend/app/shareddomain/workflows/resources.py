"""Canonical Workflow resource references and immutable snapshots."""

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from app.entities.tools import ToolRef, ToolSnapshot
from app.schemas.workflow import (
    CodeNodeConfig,
    KnowledgeNodeConfig,
    LlmNodeConfig,
    McpNodeConfig,
    ToolNodeConfig,
    WorkflowGraph,
)
from app.shareddomain.tools.runtime import (
    tool_snapshot_from_payload,
    tool_snapshot_payload,
)


WORKFLOW_RESOURCE_SCHEMA_VERSION = 1


def _ref_payload(reference: ToolRef) -> dict[str, str]:
    return {
        "tool_id": reference.tool_id,
        "version_id": reference.version_id,
    }


def _unique_tool_refs(references: list[ToolRef]) -> list[ToolRef]:
    unique: dict[str, ToolRef] = {}
    for reference in references:
        current = unique.setdefault(reference.tool_id, reference)
        if current.version_id != reference.version_id:
            raise ValueError("Workflow references multiple versions of one Tool.")
    return list(unique.values())


def legacy_mcp_references(graph: WorkflowGraph) -> list[tuple[str, str]]:
    references: list[tuple[str, str]] = []
    for node in graph.nodes:
        if node.data.type == "mcp":
            config = McpNodeConfig.model_validate(node.data.config)
            references.append((config.server_id, config.tool_name))
        elif node.data.type == "llm":
            config = LlmNodeConfig.model_validate(node.data.config)
            if config.mcp_enable:
                references.extend(
                    (item.server_id, item.tool_name) for item in config.mcp_servers
                )
    return list(dict.fromkeys(references))


def canonicalize_workflow_graph(
    graph: WorkflowGraph,
    legacy_tools: Mapping[tuple[str, str], ToolRef],
    inline_python: ToolRef | None,
) -> WorkflowGraph:
    payload = graph.model_dump(by_alias=True, mode="json")
    for node in payload["nodes"]:
        node_type = node["data"]["type"]
        config = node["data"]["config"]
        if node_type == "mcp":
            parsed = McpNodeConfig.model_validate(config)
            reference = legacy_tools.get((parsed.server_id, parsed.tool_name))
            if reference is None:
                raise ValueError("Legacy Workflow MCP Tool could not be resolved.")
            node["data"]["type"] = "tool"
            node["data"]["config"] = {
                "tool": _ref_payload(reference),
                "arguments": parsed.arguments,
            }
        elif node_type == "code":
            parsed = CodeNodeConfig.model_validate(config)
            if inline_python is None:
                raise ValueError("Inline Python Tool could not be resolved.")
            node["data"]["type"] = "tool"
            node["data"]["config"] = {
                "tool": _ref_payload(inline_python),
                "arguments": {"code": parsed.code, "inputs": parsed.inputs},
            }
        elif node_type == "llm":
            parsed = LlmNodeConfig.model_validate(config)
            references = [
                ToolRef(item.tool_id, item.version_id) for item in parsed.tools
            ]
            if parsed.mcp_enable:
                for item in parsed.mcp_servers:
                    reference = legacy_tools.get((item.server_id, item.tool_name))
                    if reference is None:
                        raise ValueError(
                            "Legacy Workflow MCP Tool could not be resolved."
                        )
                    references.append(reference)
            canonical_config = parsed.model_dump(
                mode="json",
                exclude={"mcp_enable", "mcp_servers", "tools"},
            )
            canonical_config["tools"] = [
                _ref_payload(item) for item in _unique_tool_refs(references)
            ]
            node["data"]["config"] = canonical_config
    return WorkflowGraph.model_validate(payload)


def canonicalize_workflow_snapshot_graph(
    graph: WorkflowGraph,
    snapshots: list[ToolSnapshot],
) -> WorkflowGraph:
    legacy_tools: dict[tuple[str, str], ToolRef] = {}
    inline_python: ToolRef | None = None
    for snapshot in snapshots:
        if snapshot.kind == "mcp":
            server_id = snapshot.execution_spec.get("server_id")
            tool_name = snapshot.execution_spec.get("tool_name")
            if isinstance(server_id, str) and isinstance(tool_name, str):
                legacy_tools[(server_id, tool_name)] = ToolRef(
                    snapshot.tool_id,
                    snapshot.version_id,
                )
        elif snapshot.execution_spec.get("builtin") == "inline_python":
            inline_python = ToolRef(snapshot.tool_id, snapshot.version_id)
    return canonicalize_workflow_graph(graph, legacy_tools, inline_python)


def workflow_resource_references(
    graph: WorkflowGraph,
) -> tuple[list[str], list[ToolRef]]:
    knowledge_base_ids: list[str] = []
    tool_references: list[ToolRef] = []
    for node in graph.nodes:
        if node.data.type == "knowledge":
            knowledge_base_ids.extend(
                KnowledgeNodeConfig.model_validate(
                    node.data.config
                ).resolved_knowledge_base_ids
            )
        elif node.data.type == "tool":
            item = ToolNodeConfig.model_validate(node.data.config).tool
            tool_references.append(ToolRef(item.tool_id, item.version_id))
        elif node.data.type == "llm":
            tool_references.extend(
                ToolRef(item.tool_id, item.version_id)
                for item in LlmNodeConfig.model_validate(node.data.config).tools
            )
    return (
        list(dict.fromkeys(knowledge_base_ids)),
        _unique_tool_refs(tool_references),
    )


def select_tool_snapshots(
    references: list[ToolRef],
    snapshots: list[ToolSnapshot],
) -> list[ToolSnapshot]:
    available = {
        (snapshot.tool_id, snapshot.version_id): snapshot for snapshot in snapshots
    }
    try:
        return [
            available[(reference.tool_id, reference.version_id)]
            for reference in references
        ]
    except KeyError as exc:
        raise ValueError("Workflow Tool binding is missing or stale.") from exc


def build_workflow_resource_snapshot(
    knowledge_base_ids: list[str],
    tools: list[ToolSnapshot],
    agents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": WORKFLOW_RESOURCE_SCHEMA_VERSION,
        "knowledge_base_ids": sorted(set(knowledge_base_ids)),
        "tools": [
            tool_snapshot_payload(item)
            for item in sorted(tools, key=lambda item: (item.tool_id, item.version_id))
        ],
        "agents": sorted(
            agents or [],
            key=lambda item: (str(item.get("agent_id")), str(item.get("version_id"))),
        ),
    }


def workflow_resource_hash(snapshot: dict[str, Any]) -> str:
    encoded = json.dumps(
        snapshot,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_workflow_resource_snapshot(
    graph: WorkflowGraph,
    snapshot: dict[str, Any],
    expected_hash: str,
) -> tuple[list[str], list[ToolSnapshot]]:
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("schema_version") != WORKFLOW_RESOURCE_SCHEMA_VERSION
        or snapshot.get("legacy") is True
        or workflow_resource_hash(snapshot) != expected_hash
    ):
        raise ValueError("Workflow resource snapshot is invalid.")
    knowledge_base_ids, references = workflow_resource_references(graph)
    if snapshot.get("knowledge_base_ids") != sorted(set(knowledge_base_ids)):
        raise ValueError("Workflow resource snapshot does not match its graph.")
    raw_tools = snapshot.get("tools")
    if not isinstance(raw_tools, list):
        raise ValueError("Workflow resource snapshot is invalid.")
    tools = [tool_snapshot_from_payload(item) for item in raw_tools]
    selected = select_tool_snapshots(references, tools)
    if len(selected) != len(tools):
        raise ValueError("Workflow resource snapshot does not match its graph.")
    return knowledge_base_ids, selected


__all__ = [
    "WORKFLOW_RESOURCE_SCHEMA_VERSION",
    "build_workflow_resource_snapshot",
    "canonicalize_workflow_graph",
    "canonicalize_workflow_snapshot_graph",
    "legacy_mcp_references",
    "load_workflow_resource_snapshot",
    "select_tool_snapshots",
    "workflow_resource_hash",
    "workflow_resource_references",
]
