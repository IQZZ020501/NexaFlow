"""Authorized capability catalog and checkpointed active tool loadout."""

import json
from typing import Any

from langchain_core.tools import StructuredTool

from app.domain.agents.runtime.extensions import ExtensionRuntime
from app.domain.agents.runtime.tools import AgentToolResult, create_agent_tool
from app.entities.agent_skills import AgentSkillSnapshot

HARNESS_TOOL_NAMES = frozenset({"search_tools", "activate_tools", "load_skill"})


class CapabilityRegistry:
    def __init__(
        self, extensions: ExtensionRuntime, skills: list[AgentSkillSnapshot]
    ) -> None:
        self.extensions = extensions
        self.catalog = {tool.name: tool for tool in extensions.tools}
        if HARNESS_TOOL_NAMES.intersection(self.catalog):
            raise ValueError("Capability names conflict with reserved harness tools.")
        self.skills = {skill.version_id: skill for skill in skills}
        self.active_names = list(self.catalog)
        self.loaded_skills: list[str] = []
        self.management_tools = self._management_tools()

    def restore(self, state: dict[str, Any]) -> None:
        names = state.get("active_tools", list(self.catalog))
        if not isinstance(names, list) or any(
            name not in self.catalog for name in names
        ):
            raise ValueError("Checkpoint contains unavailable capabilities.")
        loaded = state.get("loaded_skills", [])
        if not isinstance(loaded, list) or any(
            name not in self.skills for name in loaded
        ):
            raise ValueError("Checkpoint contains unavailable Skill versions.")
        self.active_names = list(dict.fromkeys(names))
        self.loaded_skills = list(dict.fromkeys(loaded))

    def snapshot(self) -> dict[str, Any]:
        return {
            "active_tools": self.active_names[:],
            "loaded_skills": self.loaded_skills[:],
        }

    @property
    def tools(self) -> list[StructuredTool]:
        return [
            *self.management_tools,
            *(self.catalog[name] for name in self.active_names),
        ]

    def _management_tools(self) -> list[StructuredTool]:
        async def search(raw: str) -> AgentToolResult:
            query = json.loads(raw)["query"].casefold().split()
            matches = []
            for name, tool in self.catalog.items():
                text = f"{name} {tool.description}".casefold()
                if not query or any(term in text for term in query):
                    matches.append(
                        {
                            "name": name,
                            "description": tool.description[:500],
                            "active": name in self.active_names,
                        }
                    )
            return AgentToolResult(
                content=json.dumps(matches, ensure_ascii=False),
                summary="Capability catalog searched.",
                output=matches,
            )

        async def activate(raw: str) -> AgentToolResult:
            arguments = json.loads(raw)
            names = arguments["names"]
            unavailable = [name for name in names if name not in self.catalog]
            if unavailable:
                return AgentToolResult(
                    content="Unavailable capabilities: " + ", ".join(unavailable),
                    summary="Capability activation rejected.",
                    is_error=True,
                )
            self.active_names = list(dict.fromkeys(names))
            return AgentToolResult(
                content=json.dumps({"active_tools": self.active_names}),
                summary="Active capabilities updated.",
                output=self.snapshot(),
            )

        async def load(raw: str) -> AgentToolResult:
            version_id = json.loads(raw)["version_id"]
            skill = self.skills.get(version_id)
            if skill is None:
                return AgentToolResult(
                    content="Skill version is not in the authorized catalog.",
                    summary="Skill loading rejected.",
                    is_error=True,
                )
            if version_id not in self.loaded_skills:
                self.loaded_skills.append(version_id)
            definition = skill.definition
            content = {
                "name": skill.name,
                "version_id": skill.version_id,
                "instructions": definition.get("instructions", ""),
                "input_schema": definition.get("input_schema", {}),
                "output_schema": definition.get("output_schema", {}),
                "guardrails": definition.get("guardrails", {}),
            }
            return AgentToolResult(
                content=json.dumps(content, ensure_ascii=False),
                summary="Pinned Skill instructions loaded.",
                output={"name": skill.name, "version_id": version_id},
            )

        def management(
            name: str, description: str, parameters: dict[str, Any], execute: Any
        ) -> StructuredTool:
            return create_agent_tool(
                name=name,
                description=description,
                parameters=parameters,
                execute=execute,
                kind="builtin",
                policy_mode="harness_internal",
            )

        return [
            management(
                "search_tools",
                "Search the authorized tool catalog by capability or task. Discovery does not grant new permissions.",
                {
                    "type": "object",
                    "properties": {"query": {"type": "string", "maxLength": 200}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
                search,
            ),
            management(
                "activate_tools",
                "Set the active tool names for subsequent model turns. Only already-authorized catalog tools can be enabled. Harness management tools remain available.",
                {
                    "type": "object",
                    "properties": {
                        "names": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": len(self.catalog),
                            "uniqueItems": True,
                        }
                    },
                    "required": ["names"],
                    "additionalProperties": False,
                },
                activate,
            ),
            management(
                "load_skill",
                "Load the full instructions of an authorized pinned Skill version before using it. Use version_id from the Skill catalog.",
                {
                    "type": "object",
                    "properties": {
                        "version_id": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 36,
                        }
                    },
                    "required": ["version_id"],
                    "additionalProperties": False,
                },
                load,
            ),
        ]
