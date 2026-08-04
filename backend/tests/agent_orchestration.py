import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from app.capabilities.llm.runtime import ModelCompletion, ModelToolCall
from app.shareddomain.agents.runner import (
    COMPLETE_STEP_TOOL,
    REPLAN_TOOL,
    SUBMIT_PLAN_TOOL,
    AgentOrchestrator,
    AgentRuntimeContext,
    AgentTool,
    AgentToolResult,
    initial_agent_state,
)


class SequenceProvider:
    def __init__(self, responses: list[ModelCompletion | Exception]) -> None:
        self.responses = responses

    def complete(self, *_args: Any, **_kwargs: Any) -> ModelCompletion:
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    async def stream_complete(self, *_args: Any, **kwargs: Any) -> ModelCompletion:
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        callback = kwargs.get("on_content_delta")
        if callback and response.content:
            await callback(response.content)
        return response


class FinalRequestProvider(SequenceProvider):
    final_messages: list[dict[str, Any]]

    async def stream_complete(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> ModelCompletion:
        self.final_messages = messages
        return await super().stream_complete(messages, **kwargs)


def tool_call(name: str, payload: dict[str, Any], call_id: str) -> ModelCompletion:
    return ModelCompletion(
        content="",
        tool_calls=(ModelToolCall(call_id, name, json.dumps(payload)),),
        finish_reason="tool_calls",
    )


def initial_state(run_id: str) -> dict[str, Any]:
    return initial_agent_state(
        run_id,
        "Complete the task",
        "Use available tools when needed.",
        {
            "max_turns": 8,
            "max_tool_calls": 6,
            "max_retrieval_calls": 3,
            "deadline_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        },
    )


async def collect(stream: Any) -> list[dict[str, Any]]:
    return [item async for item in stream]


def final_state(events: list[dict[str, Any]]) -> dict[str, Any]:
    states = [item["data"] for item in events if item["type"] == "values"]
    assert states
    return states[-1]


async def assert_replanning() -> None:
    provider = SequenceProvider(
        [
            tool_call(
                SUBMIT_PLAN_TOOL,
                {"steps": [{"title": "Inspect", "description": "Inspect the input"}]},
                "plan-1",
            ),
            tool_call(
                REPLAN_TOOL,
                {
                    "reason": "Two outcomes are required",
                    "steps": [
                        {"title": "Inspect", "description": "Inspect the input"},
                        {"title": "Report", "description": "Report the result"},
                    ],
                },
                "replan-1",
            ),
            tool_call(COMPLETE_STEP_TOOL, {"summary": "Inspected"}, "step-1"),
            tool_call(COMPLETE_STEP_TOOL, {"summary": "Reported"}, "step-2"),
            ModelCompletion("Done.", (), "stop"),
        ]
    )
    orchestrator = AgentOrchestrator(InMemorySaver())
    events = await collect(
        orchestrator.stream(
            "run-replan",
            AgentRuntimeContext(provider, []),
            state=initial_state("run-replan"),
        )
    )
    result = final_state(events)
    assert result["status"] == "succeeded"
    assert result["plan_revision"] == 2
    assert [step["status"] for step in result["plan"]] == ["completed", "completed"]
    assert any(
        item["type"] == "custom" and item["data"].get("type") == "answer_delta"
        for item in events
    )


async def assert_approval() -> None:
    executions = 0

    async def execute(_arguments: str) -> AgentToolResult:
        nonlocal executions
        executions += 1
        return AgentToolResult("Tool result", "tool.completed", {"ok": True})

    tool = AgentTool(
        "external_action",
        "Perform an external action.",
        {"type": "object"},
        execute,
        requires_approval=True,
    )
    provider = SequenceProvider(
        [
            tool_call(
                SUBMIT_PLAN_TOOL,
                {"steps": [{"title": "Act", "description": "Perform the action"}]},
                "plan-2",
            ),
            tool_call("external_action", {}, "action-1"),
            tool_call(COMPLETE_STEP_TOOL, {"summary": "Action completed"}, "step-3"),
            ModelCompletion("Approved and completed.", (), "stop"),
        ]
    )
    orchestrator = AgentOrchestrator(InMemorySaver())
    context = AgentRuntimeContext(provider, [tool])
    paused = await collect(
        orchestrator.stream(
            "run-approval",
            context,
            state=initial_state("run-approval"),
        )
    )
    assert executions == 0
    assert any(item.get("interrupts") for item in paused)

    resumed = await collect(
        orchestrator.stream("run-approval", context, approval_decision="approved")
    )
    assert executions == 1
    assert final_state(resumed)["status"] == "succeeded"


async def assert_expired_approval() -> None:
    executions = 0

    async def execute(_arguments: str) -> AgentToolResult:
        nonlocal executions
        executions += 1
        return AgentToolResult("Tool result", "tool.completed")

    tool = AgentTool(
        "external_action",
        "Perform an external action.",
        {"type": "object"},
        execute,
        requires_approval=True,
    )
    provider = SequenceProvider(
        [
            tool_call(
                SUBMIT_PLAN_TOOL,
                {"steps": [{"title": "Act", "description": "Perform the action"}]},
                "plan-expired",
            ),
            tool_call("external_action", {}, "action-expired"),
            ModelCompletion("The approval expired.", (), "stop"),
        ]
    )
    orchestrator = AgentOrchestrator(InMemorySaver())
    context = AgentRuntimeContext(provider, [tool])
    await collect(
        orchestrator.stream(
            "run-expired-approval",
            context,
            state=initial_state("run-expired-approval"),
        )
    )
    config = {"configurable": {"thread_id": "run-expired-approval"}}
    snapshot = await orchestrator.graph.aget_state(config)
    await orchestrator.graph.aupdate_state(
        config,
        {
            "budget": {
                **snapshot.values["budget"],
                "deadline_at": (
                    datetime.now(timezone.utc) - timedelta(seconds=1)
                ).isoformat(),
            }
        },
    )

    resumed = await collect(
        orchestrator.stream(
            "run-expired-approval",
            context,
            approval_decision="approved",
        )
    )
    result = final_state(resumed)
    assert executions == 0
    assert result["stop_reason"] == "deadline_reached"
    assert any(
        event["summary"] == "agent.approval_expired" for event in result["events"]
    )


async def assert_tool_limit_closes_call() -> None:
    executions = 0

    async def execute(_arguments: str) -> AgentToolResult:
        nonlocal executions
        executions += 1
        return AgentToolResult("Tool result", "tool.completed")

    tool = AgentTool(
        "limited_tool",
        "A tool that must not run after the limit.",
        {"type": "object"},
        execute,
    )
    provider = FinalRequestProvider(
        [
            tool_call(
                SUBMIT_PLAN_TOOL,
                {"steps": [{"title": "Act", "description": "Perform the action"}]},
                "plan-limit",
            ),
            tool_call("limited_tool", {}, "action-limit"),
            ModelCompletion("The tool limit was reached.", (), "stop"),
        ]
    )
    state = initial_state("run-tool-limit")
    state["budget"]["max_tool_calls"] = 0
    events = await collect(
        AgentOrchestrator(InMemorySaver()).stream(
            "run-tool-limit",
            AgentRuntimeContext(provider, [tool]),
            state=state,
        )
    )
    assert executions == 0
    assert final_state(events)["stop_reason"] == "tool_call_limit_reached"
    assert any(
        message.get("role") == "tool"
        and message.get("tool_call_id") == "action-limit"
        for message in provider.final_messages
    )


async def assert_recovery() -> None:
    orchestrator = AgentOrchestrator(InMemorySaver())
    failing = SequenceProvider(
        [
            tool_call(
                SUBMIT_PLAN_TOOL,
                {"steps": [{"title": "Recover", "description": "Recover execution"}]},
                "plan-3",
            ),
            RuntimeError("temporary failure"),
        ]
    )
    try:
        await collect(
            orchestrator.stream(
                "run-recovery",
                AgentRuntimeContext(failing, []),
                state=initial_state("run-recovery"),
            )
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("Graph failure was not surfaced.")
    assert await orchestrator.has_checkpoint("run-recovery")

    recovered = SequenceProvider(
        [
            tool_call(COMPLETE_STEP_TOOL, {"summary": "Recovered"}, "step-4"),
            ModelCompletion("Recovered successfully.", (), "stop"),
        ]
    )
    events = await collect(
        orchestrator.stream(
            "run-recovery",
            AgentRuntimeContext(recovered, []),
            recover=True,
        )
    )
    assert final_state(events)["result"] == "Recovered successfully."


async def main() -> None:
    await assert_replanning()
    await assert_approval()
    await assert_expired_approval()
    await assert_tool_limit_closes_call()
    await assert_recovery()


if __name__ == "__main__":
    asyncio.run(main())
