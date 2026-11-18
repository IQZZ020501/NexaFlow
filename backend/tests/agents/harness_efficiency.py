"""Model-facing loadout and execution feedback through the public Agent loop."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import tests.support  # noqa: F401
from tests.agents.evaluation import ScriptedModel, answer_message
from tests.agents.harness import call

from app.domain.agents.runtime import AgentToolResult, create_agent_tool, run_agent
from app.domain.agents.runtime.capabilities import CapabilityRegistry
from app.domain.agents.runtime.extensions import AgentExtension, ExtensionRuntime
from app.domain.agents.runtime.session import AgentSession


def registry():
    execute = AsyncMock(return_value=AgentToolResult(content="ok", summary="Done"))
    tools = [
        create_agent_tool(
            name=name,
            description="Load Word authoring instructions"
            if name == "documents_skill"
            else name,
            parameters={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            execute=execute,
            kind="builtin" if name in {"bash", "documents_skill"} else "mcp",
        )
        for name in ["bash", "documents_skill", *(f"optional_{n}" for n in range(12))]
    ]
    return CapabilityRegistry(
        ExtensionRuntime([AgentExtension("test", "1", tuple(tools))]), []
    )


def assert_guide_loadout_boundaries():
    reference_tool = registry().extensions.tools[-1]
    tools = tuple(
        reference_tool.model_copy(
            update={"name": f"reference_{n}", "description": "说明" * 160}
        )
        for n in range(60)
    )
    large = CapabilityRegistry(
        ExtensionRuntime([AgentExtension("test", "1", tools)]), []
    )
    assert len(large.catalog_message().content.encode()) <= 4096
    for kind, parameters, description in (
        ("mcp", {"type": "object", "properties": {}}, "Untrusted same-name tool"),
        (
            "builtin",
            {
                "type": "object",
                "properties": {"code": {"type": "string"}},
                "required": ["code"],
            },
            "Legacy executable tool",
        ),
        ("builtin", {"type": "object", "properties": {}}, "Large instructions " * 2000),
    ):
        capabilities = registry()
        guide = create_agent_tool(
            name="documents_skill",
            description=description,
            parameters=parameters,
            execute=AsyncMock(),
            kind=kind,
        )
        tools = tuple(
            guide if tool.name == guide.name else tool
            for tool in capabilities.extensions.tools
        )
        restricted = CapabilityRegistry(
            ExtensionRuntime([AgentExtension("test", "1", tools)]), []
        )
        assert "bash" in restricted.active_names
        assert "documents_skill" not in restricted.active_names
        assert "search_tools" in [tool.name for tool in restricted.tools]


async def assert_efficiency_feedback():
    assert_guide_loadout_boundaries()
    capabilities = registry()
    model = ScriptedModel(
        [call("documents_skill", {}, "guide"), answer_message("Ready")]
    )
    checkpoints = []
    deadline = datetime.now(UTC) + timedelta(seconds=240)

    async def save(state, phase):
        checkpoints.append(state)

    await run_agent(
        model,
        [{"role": "user", "content": "Create a Word document"}],
        [],
        session=AgentSession(capabilities),
        on_checkpoint=save,
        max_turns=6,
        max_tool_calls=12,
        execution_deadline_at=deadline,
    )
    assert "documents_skill" in model.bindings[0]
    assert "optional_0" not in model.bindings[0]
    first = "\n".join(str(m.content) for m in model.requests[0])
    assert "optional_0" in first and "activate_tools" in first
    for request in model.requests:
        statuses = [
            m for m in request if m.additional_kwargs.get("nexaflow_runtime_status")
        ]
        assert len(statuses) == 1
        assert "seconds" in statuses[0].content
        assert (
            sum(
                bool(m.additional_kwargs.get("nexaflow_capability_catalog"))
                for m in request
            )
            == 1
        )
    assert "1/6" in model.requests[0][-1].content
    assert "2/6" in model.requests[1][-1].content
    assert "1/12" in model.requests[1][-1].content

    # A resumed loop retains counters and gets the current deadline, not a new duration.
    checkpoint = next(
        s for s in checkpoints if s["turn"] == 1 and not s["pending_tool_calls"]
    )
    restored = ScriptedModel([answer_message("Resumed")])
    with patch("app.domain.agents.runtime.budget.datetime") as clock:
        clock.now.return_value = deadline - timedelta(seconds=40)
        await run_agent(
            restored,
            [],
            [],
            checkpoint=checkpoint,
            max_turns=6,
            max_tool_calls=12,
            session=AgentSession(registry()),
            execution_deadline_at=deadline,
        )
    status = restored.requests[0][-1].content
    assert "2/6" in status and "1/12" in status and "Prioritize" in status
    assert "40 seconds" in status
    assert "documents_skill" in restored.bindings[0]

    for max_turns, max_calls, responses, expected, absent in (
        (
            1,
            5,
            [answer_message("Incomplete")],
            "final model turn",
            "tool-call budget is exhausted",
        ),
        (
            6,
            1,
            [call("documents_skill", {}, "guide"), answer_message("Done")],
            "tool-call budget is exhausted",
            "final model turn",
        ),
    ):
        model = ScriptedModel(responses)
        await run_agent(
            model,
            [{"role": "user", "content": "Create Word"}],
            [],
            max_turns=max_turns,
            max_tool_calls=max_calls,
            session=AgentSession(registry()),
        )
        assert expected in model.requests[-1][-1].content
        assert absent not in model.requests[-1][-1].content

    model = ScriptedModel([answer_message("20")])
    await run_agent(
        model,
        [{"role": "user", "content": "12+8"}],
        [],
        session=AgentSession(registry()),
    )
    assert len(model.requests) == 1


def main():
    asyncio.run(assert_efficiency_feedback())
    print("AGENT_EFFICIENCY_OK")


if __name__ == "__main__":
    main()
