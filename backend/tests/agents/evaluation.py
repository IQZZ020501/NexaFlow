"""Deterministic Agent runtime and release-gate evaluation suite."""

from __future__ import annotations

import asyncio
from typing import Any

import tests.support  # noqa: F401  # sets required env before app imports
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    message_to_dict,
)

from app.domain.agents.evaluation import (
    AgentEvaluationObservation,
    AgentEvaluationResult,
    AgentEvaluationSuite,
    agent_evaluation_gate,
    evaluate_agent_observation,
)
from app.domain.agents.runtime import (
    AgentRunnerError,
    AgentToolResult,
    create_agent_tool,
    run_agent,
)
from scripts.agent_eval import (
    AgentEvaluationClient,
    AgentEvaluationError,
    observation_from_run,
)


class ScriptedModel:
    def __init__(self, responses: list[AIMessage]) -> None:
        self.responses = list(responses)
        self.requests: list[list[BaseMessage]] = []
        self.bindings: list[list[str]] = []

    def bind_tools(self, *_args: Any, **_kwargs: Any) -> ScriptedModel:
        self.bindings.append([tool.name for tool in _args[0]])
        return self

    async def ainvoke(self, _messages: list[BaseMessage]) -> AIMessage:
        self.requests.append(list(_messages))
        return self.responses.pop(0)


class GatedStreamingModel:
    def __init__(self) -> None:
        self.first_chunk_emitted = asyncio.Event()
        self.finish = asyncio.Event()

    def bind_tools(self, *_args: Any, **_kwargs: Any) -> GatedStreamingModel:
        return self

    async def astream(self, _messages: list[BaseMessage]):
        yield AIMessageChunk(
            content="Live",
            additional_kwargs={"reasoning_content": "Choose the useful capability."},
        )
        self.first_chunk_emitted.set()
        await self.finish.wait()
        yield AIMessageChunk(
            content=" answer.",
            response_metadata={"finish_reason": "stop"},
        )


def answer_message(text: str, *, tokens: int = 12) -> AIMessage:
    return AIMessage(
        content=text,
        response_metadata={"finish_reason": "stop"},
        usage_metadata={
            "input_tokens": max(1, tokens - 3),
            "output_tokens": 3,
            "total_tokens": tokens,
        },
    )


def tool_message(name: str, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": {"value": "ok"}, "id": call_id, "type": "tool_call"}
        ],
        response_metadata={"finish_reason": "tool_calls"},
        usage_metadata={"input_tokens": 8, "output_tokens": 4, "total_tokens": 12},
    )


def observation(result: Any, *, source_count: int = 0) -> AgentEvaluationObservation:
    observed = tuple(
        str(event.get("tool_name"))
        for event in result.events
        if event.get("type") == "tool" and event.get("tool_name")
    )
    successful = tuple(
        str(event.get("tool_name"))
        for event in result.events
        if event.get("type") == "tool"
        and event.get("status") == "succeeded"
        and event.get("tool_name")
    )
    return AgentEvaluationObservation(
        status="succeeded",
        answer=result.content,
        successful_tool_names=successful,
        observed_tool_names=observed,
        source_count=source_count,
        model_usage=result.model_usage,
        duration_ms=1,
    )


async def runtime_observations() -> tuple[AgentEvaluationObservation, ...]:
    direct = await run_agent(
        ScriptedModel([answer_message("Direct answer: ready.")]),
        [{"role": "user", "content": "Respond directly."}],
        [],
        max_model_tokens=100,
    )

    async def echo(arguments: str) -> AgentToolResult:
        return AgentToolResult(
            content=arguments, summary="Echo succeeded.", output={"ok": True}
        )

    tool = create_agent_tool(
        name="echo",
        description="Echo a value.",
        parameters={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        execute=echo,
        kind="builtin",
    )
    with_tool = await run_agent(
        ScriptedModel(
            [tool_message("echo", "call-echo"), answer_message("Tool answer: ready.")]
        ),
        [{"role": "user", "content": "Use echo."}],
        [tool],
        max_model_tokens=100,
    )

    knowledge = create_agent_tool(
        name="search_knowledge",
        description="Search optional workspace documents.",
        parameters={"type": "object", "properties": {"value": {"type": "string"}}},
        execute=echo,
        kind="knowledge",
    )
    searched = await run_agent(
        ScriptedModel(
            [
                tool_message("search_knowledge", "call-search"),
                answer_message("Document answer: fact."),
            ]
        ),
        [{"role": "user", "content": "Find the document."}],
        [knowledge],
    )
    return (
        observation(direct),
        observation(with_tool),
        observation(searched, source_count=1),
    )


def test_release_gate() -> None:
    suite = AgentEvaluationSuite.from_dict(
        {
            "gate": {"minimum_pass_rate": 1.0},
            "cases": [
                {
                    "id": "direct",
                    "goal": "Respond directly.",
                    "category": "answer",
                    "expect": {
                        "answer_contains": ["Direct answer"],
                        "max_total_tokens": 30,
                        "max_model_calls": 1,
                    },
                },
                {
                    "id": "tool",
                    "goal": "Use echo.",
                    "category": "tool",
                    "expect": {
                        "answer_contains": ["Tool answer"],
                        "required_tool_names": ["echo"],
                        "max_total_tokens": 40,
                        "max_model_calls": 2,
                    },
                },
                {
                    "id": "knowledge",
                    "goal": "Answer from evidence.",
                    "category": "capability",
                    "expect": {
                        "answer_contains": ["fact"],
                        "min_sources": 1,
                        "max_total_tokens": 30,
                        "max_model_calls": 2,
                    },
                },
            ],
        }
    )
    observations = asyncio.run(runtime_observations())
    results = [
        evaluate_agent_observation(case, item, sample=1)
        for case, item in zip(suite.cases, observations, strict=True)
    ]
    passed, summary = agent_evaluation_gate(suite, results)
    assert passed is True
    assert summary["passed"] == 3


def test_gate_rejects_blocked_tools_and_unreported_usage() -> None:
    suite = AgentEvaluationSuite.from_dict(
        {
            "gate": {"minimum_pass_rate": 0.5},
            "cases": [
                {
                    "id": "security",
                    "goal": "Do not call blocked tools.",
                    "required": True,
                    "expect": {
                        "answer_not_contains": ["unsafe"],
                        "forbidden_tool_names": ["missing_tool"],
                        "max_total_tokens": 20,
                    },
                },
                {
                    "id": "optional",
                    "goal": "Optional sample.",
                    "required": False,
                },
            ],
        }
    )
    failed = evaluate_agent_observation(
        suite.cases[0],
        AgentEvaluationObservation(
            status="succeeded",
            answer="unsafe",
            observed_tool_names=("missing_tool",),
            model_usage={
                "model_calls": 1,
                "reported_model_calls": 0,
                "total_tokens": 10,
            },
        ),
        sample=1,
    )
    optional = AgentEvaluationResult(
        case_id="optional",
        category="general",
        sample=1,
        required=False,
        passed=True,
        failures=(),
    )
    passed, summary = agent_evaluation_gate(suite, [failed, optional])
    assert passed is False
    assert "answer_forbidden:1" in failed.failures
    assert all("unsafe" not in failure for failure in failed.failures)
    assert "tool_forbidden:missing_tool" in failed.failures
    assert "usage:unreported" in failed.failures
    assert summary["pass_rate"] == 0.5
    assert summary["required_failures"] == ["security#1"]


def test_plain_answer_ignores_retired_grounding_and_token_limits() -> None:
    async def execute() -> None:
        result = await run_agent(
            ScriptedModel([answer_message("A useful ordinary answer.", tokens=12)]),
            [{"role": "user", "content": "Answer normally."}],
            [],
            grounding_mode="required",
            initial_evidence=[{"chunk_id": "chunk-1", "content": "unrelated"}],
            max_model_tokens=1,
        )
        assert result.content == "A useful ordinary answer."
        assert not hasattr(result, "grounding_status")
        assert not hasattr(result, "grounding_meta")
        assert result.model_usage["total_tokens"] == 12
        assert not any(
            str(event.get("summary") or "").startswith("agent.grounding_")
            for event in result.events
        )

    asyncio.run(execute())


def test_plain_answer_streams_immediately_without_a_manifest() -> None:
    async def execute() -> None:
        model = GatedStreamingModel()
        answer_seen = asyncio.Event()
        events: list[dict[str, Any]] = []

        async def emit(event: dict[str, Any]) -> None:
            events.append(event)
            if event.get("type") == "answer_delta":
                answer_seen.set()

        task = asyncio.create_task(
            run_agent(
                model,
                [{"role": "user", "content": "Answer normally."}],
                [],
                on_event=emit,
                grounding_mode="required",
                initial_evidence=[{"chunk_id": "chunk-1", "content": "unrelated"}],
            )
        )
        await model.first_chunk_emitted.wait()
        try:
            await asyncio.wait_for(answer_seen.wait(), timeout=0.1)
            assert [
                event["delta"]
                for event in events
                if event.get("type") == "answer_delta"
            ] == ["Live"]
        finally:
            model.finish.set()
        result = await task
        assert result.content == "Live answer."
        assert (
            "".join(
                event["delta"]
                for event in events
                if event.get("type") == "answer_delta"
            )
            == result.content
        )
        assert (
            "".join(
                event["delta"]
                for event in events
                if event.get("type") == "reasoning_delta"
            )
            == "Choose the useful capability."
        )
        assert not any(
            str(event.get("event", {}).get("summary") or "").startswith(
                "agent.grounding_"
            )
            for event in events
        )

    asyncio.run(execute())


def test_capabilities_share_the_same_loop_and_budget() -> None:
    async def execute() -> None:
        invoked: list[str] = []
        tools = []
        for kind in ("knowledge", "mcp", "builtin"):

            async def call(_arguments: str, selected: str = kind) -> AgentToolResult:
                invoked.append(selected)
                return AgentToolResult(content="No new information.", summary="Done.")

            tools.append(
                create_agent_tool(
                    name=f"tool_{kind}",
                    description=f"Optional {kind} capability.",
                    parameters={
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                    },
                    execute=call,
                    kind=kind,
                )
            )
        result = await run_agent(
            ScriptedModel(
                [
                    tool_message("tool_knowledge", "search-1"),
                    tool_message("tool_mcp", "external-1"),
                    tool_message("tool_builtin", "skill-1"),
                    tool_message("tool_knowledge", "search-2"),
                    tool_message("tool_knowledge", "search-3"),
                    answer_message("Completed."),
                ]
            ),
            [{"role": "user", "content": "Use the capabilities as needed."}],
            tools,
            max_turns=6,
            adaptive_retrieval=True,
            max_no_progress_rounds=1,
            knowledge_min_evidence_items=1,
        )
        assert result.content == "Completed."
        assert invoked == ["knowledge", "mcp", "builtin", "knowledge", "knowledge"]
        assert len(result.events) == 5
        for tool in tools:
            model = ScriptedModel(
                [
                    tool_message(tool.name, "call-budget"),
                    answer_message("Finished with available results."),
                ]
            )
            finalized = await run_agent(
                model,
                [{"role": "user", "content": "Use a capability."}],
                [tool],
                max_tool_calls=1,
            )
            assert finalized.content == "Finished with available results."
            assert model.bindings == [[tool.name]]
            assert "tool-call budget is exhausted" in str(
                model.requests[-1][-1].content
            )
            try:
                await run_agent(
                    ScriptedModel([tool_message(tool.name, "call-1")]),
                    [{"role": "user", "content": "Use a tool."}],
                    [tool],
                    max_tool_calls=0,
                )
            except AgentRunnerError as exc:
                assert "tool call limit" in str(exc)
            else:
                raise AssertionError(f"{tool.name} bypassed the common tool budget.")

    asyncio.run(execute())


def test_legacy_checkpoint_uses_the_generic_protocol_without_replaying_tools() -> None:
    async def execute() -> None:
        model = ScriptedModel([answer_message("Continued normally.")])
        saved: list[dict[str, Any]] = []

        async def checkpoint(state: dict[str, Any], _phase: str) -> None:
            saved.append(state)

        result = await run_agent(
            model,
            [
                {"role": "system", "content": "Tools are optional capabilities."},
                {"role": "user", "content": "Current goal."},
            ],
            [],
            checkpoint={
                "messages": [
                    message_to_dict(
                        SystemMessage(content="<nexaflow-grounding> required")
                    ),
                    message_to_dict(HumanMessage(content="Current goal.")),
                ],
                "events": [
                    {"type": "thought", "summary": "agent.grounding_check"},
                    {"type": "tool", "tool_kind": "knowledge", "status": "succeeded"},
                ],
                "turn": 1,
                "tool_call_count": 1,
                "grounding_status": "pending",
                "evidence_packets": [{"chunk_id": "chunk-1"}],
                "knowledge_call_count": 1,
            },
            on_checkpoint=checkpoint,
        )
        assert result.content == "Continued normally."
        assert model.requests[0][0].content == "Tools are optional capabilities."
        assert not any(
            "<nexaflow-grounding>" in str(message.content)
            for message in model.requests[0]
        )
        assert result.events == [
            {"type": "tool", "tool_kind": "knowledge", "status": "succeeded"},
        ]
        assert saved
        assert not (
            {"grounding_status", "evidence_packets", "knowledge_call_count"}
            & saved[-1].keys()
        )

    asyncio.run(execute())


def test_live_runner_contract_is_safe_and_observable() -> None:
    try:
        AgentEvaluationClient(
            "http://models.example.com",
            "secret",
            request_timeout=1,
        )
    except AgentEvaluationError as exc:
        assert "HTTPS" in str(exc)
    else:
        raise AssertionError("The live evaluator accepted a plaintext remote URL.")
    client = AgentEvaluationClient(
        "http://127.0.0.1:8000",
        "secret",
        request_timeout=1,
    )
    assert client.base_url == "http://127.0.0.1:8000"
    observed = observation_from_run(
        {
            "status": "succeeded",
            "result": "answer",
            "events": [
                {"type": "tool", "tool_name": "echo", "status": "running"},
                {"type": "tool", "tool_name": "echo", "status": "succeeded"},
            ],
            "sources": [{"source_ref": "chunk-1"}],
            "model_usage": {"model_calls": 1, "reported_model_calls": 1},
        },
        fallback_seconds=0.25,
    )
    assert observed.observed_tool_names == ("echo", "echo")
    assert observed.successful_tool_names == ("echo",)
    assert observed.source_count == 1
    assert observed.duration_ms == 250


def main() -> None:
    test_plain_answer_ignores_retired_grounding_and_token_limits()
    test_plain_answer_streams_immediately_without_a_manifest()
    test_capabilities_share_the_same_loop_and_budget()
    test_legacy_checkpoint_uses_the_generic_protocol_without_replaying_tools()
    test_release_gate()
    test_gate_rejects_blocked_tools_and_unreported_usage()
    test_live_runner_contract_is_safe_and_observable()
    print("AGENT_EVALUATION_OK")


if __name__ == "__main__":
    main()
