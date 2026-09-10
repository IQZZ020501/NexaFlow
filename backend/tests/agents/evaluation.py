"""Deterministic Agent runtime and release-gate evaluation suite."""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage

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

    def bind_tools(self, *_args: Any, **_kwargs: Any) -> ScriptedModel:
        return self

    async def ainvoke(self, _messages: list[BaseMessage]) -> AIMessage:
        return self.responses.pop(0)


class GatedStreamingModel:
    def __init__(self, manifest: str | None = None) -> None:
        self.first_chunk_emitted = asyncio.Event()
        self.finish = asyncio.Event()
        self.manifest = manifest or (
            '<nexaflow-grounding>{"status":"skipped",'
            '"evidence_ids":[],"reason_codes":[]}</nexaflow-grounding>\n'
        )

    def bind_tools(self, *_args: Any, **_kwargs: Any) -> GatedStreamingModel:
        return self

    async def astream(self, _messages: list[BaseMessage]):
        yield AIMessageChunk(content=f"{self.manifest}Live")
        self.first_chunk_emitted.set()
        await self.finish.wait()
        yield AIMessageChunk(
            content=" answer.",
            response_metadata={"finish_reason": "stop"},
        )


class InlineGroundingStreamingModel:
    def __init__(self) -> None:
        self.first_answer_chunk_emitted = asyncio.Event()
        self.finish = asyncio.Event()
        self.calls = 0

    def bind_tools(self, *_args: Any, **_kwargs: Any) -> InlineGroundingStreamingModel:
        return self

    async def astream(self, _messages: list[BaseMessage]):
        self.calls += 1
        yield AIMessageChunk(content="<nexaflow-")
        yield AIMessageChunk(
            content=(
                'grounding>{"status":"grounded","evidence_ids":["chunk-1"],'
                '"reason_codes":[]}</nexaflow-grounding>\n# 标题\n\n'
            )
        )
        self.first_answer_chunk_emitted.set()
        await self.finish.wait()
        yield AIMessageChunk(
            content="- 条目\n",
            response_metadata={"finish_reason": "stop"},
        )


def test_inline_grounding_precedes_streamed_markdown_without_a_second_call() -> None:
    async def execute() -> None:
        model = InlineGroundingStreamingModel()
        answer_seen = asyncio.Event()
        events: list[dict[str, Any]] = []

        async def emit(event: dict[str, Any]) -> None:
            events.append(event)
            if event.get("type") == "answer_delta":
                answer_seen.set()

        task = asyncio.create_task(
            run_agent(
                model,
                [{"role": "user", "content": "Answer from evidence."}],
                [],
                on_event=emit,
                grounding_mode="agentic",
                initial_evidence=[{"chunk_id": "chunk-1", "content": "fact"}],
            )
        )
        await model.first_answer_chunk_emitted.wait()
        await asyncio.wait_for(answer_seen.wait(), timeout=0.1)
        model.finish.set()
        result = await task
        assert model.calls == 1
        assert result.content == "# 标题\n\n- 条目\n"
        assert result.grounding_status == "grounded"
        assert result.grounding_meta["decision"] == "grounded"
        assert result.grounding_meta["evidence_ids"] == ["chunk-1"]
        assert result.grounding_meta["reason_codes"] == []
        assert result.grounding_meta["evidence_packet_count"] == 1
        assert result.grounding_meta["evidence_truncated"] is False
        assert len(result.grounding_meta["evidence_digest"]) == 64
        assert result.grounding_meta["mode"] == "inline"
        deltas = [
            event.get("delta")
            for event in events
            if event.get("type") == "answer_delta"
        ]
        assert "".join(deltas) == result.content
        assert "nexaflow-grounding" not in "".join(deltas)
        grounded_index = next(
            index
            for index, event in enumerate(events)
            if event.get("type") == "process"
            and event.get("event", {}).get("summary")
            == "agent.grounding_inline"
        )
        answer_index = next(
            index
            for index, event in enumerate(events)
            if event.get("type") == "answer_delta"
        )
        assert grounded_index < answer_index

    asyncio.run(execute())


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
        grounding_status=result.grounding_status,
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
        return AgentToolResult(content=arguments, summary="Echo succeeded.", output={"ok": True})

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
        ScriptedModel([tool_message("echo", "call-echo"), answer_message("Tool answer: ready.")]),
        [{"role": "user", "content": "Use echo."}],
        [tool],
        max_model_tokens=100,
    )

    grounded = await run_agent(
        ScriptedModel(
            [
                answer_message(
                    '<nexaflow-grounding>{"status":"grounded",'
                    '"evidence_ids":["chunk-1"],"reason_codes":[]}'
                    "</nexaflow-grounding>\nGrounded answer: fact."
                )
            ]
        ),
        [{"role": "user", "content": "Answer from evidence."}],
        [],
        grounding_mode="required",
        initial_evidence=[{"chunk_id": "chunk-1", "content": "fact"}],
        max_model_tokens=100,
    )
    return observation(direct), observation(with_tool), observation(
        grounded, source_count=1
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
                        "grounding_statuses": ["skipped"],
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
                    "id": "grounded",
                    "goal": "Answer from evidence.",
                    "category": "grounding",
                    "expect": {
                        "answer_contains": ["fact"],
                        "grounding_statuses": ["grounded"],
                        "min_sources": 1,
                        "max_total_tokens": 30,
                        "max_model_calls": 1,
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
            grounding_status="skipped",
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


def test_inline_grounding_stays_within_the_primary_model_token_budget() -> None:
    async def execute() -> None:
        await run_agent(
            ScriptedModel(
                [
                    answer_message(
                        '<nexaflow-grounding>{"status":"grounded",'
                        '"evidence_ids":["chunk-1"],"reason_codes":[]}'
                        "</nexaflow-grounding>\ndraft",
                        tokens=12,
                    )
                ]
            ),
            [{"role": "user", "content": "ground"}],
            [],
            grounding_mode="required",
            initial_evidence=[{"chunk_id": "chunk-1", "content": "fact"}],
            max_model_tokens=10,
        )

    try:
        asyncio.run(execute())
    except AgentRunnerError as exc:
        assert "token limit" in str(exc)
    else:
        raise AssertionError("Inline grounding exceeded the model token budget.")


def test_agentic_inline_grounding_streams_a_skipped_answer() -> None:
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
                [{"role": "user", "content": "Answer without retrieval."}],
                [],
                on_event=emit,
                grounding_mode="agentic",
            )
        )
        await model.first_chunk_emitted.wait()
        await asyncio.wait_for(answer_seen.wait(), timeout=0.1)
        assert [
            event.get("delta")
            for event in events
            if event.get("type") == "answer_delta"
        ] == ["Live"]
        model.finish.set()
        result = await task
        assert result.content == "Live answer."
        assert result.grounding_status == "skipped"
        assert [
            event.get("delta")
            for event in events
            if event.get("type") == "answer_delta"
        ] == ["Live", " answer."]
        assert not any(event.get("type") == "answer_reset" for event in events)
        assert any(
            event.get("type") == "process"
            and event.get("event", {}).get("summary")
            == "agent.grounding_skipped"
            for event in events
        )

    asyncio.run(execute())


def test_required_inline_grounding_rejects_unknown_evidence_before_output() -> None:
    async def execute() -> None:
        model = GatedStreamingModel(
            '<nexaflow-grounding>{"status":"grounded",'
            '"evidence_ids":["unknown"],"reason_codes":[]}'
            "</nexaflow-grounding>\n"
        )
        answer_seen = asyncio.Event()
        events: list[dict[str, Any]] = []

        async def emit(event: dict[str, Any]) -> None:
            events.append(event)
            if event.get("type") == "answer_delta":
                answer_seen.set()

        task = asyncio.create_task(
            run_agent(
                model,
                [{"role": "user", "content": "Answer from evidence."}],
                [],
                on_event=emit,
                grounding_mode="required",
                initial_evidence=[{"chunk_id": "chunk-1", "content": "fact"}],
            )
        )
        await model.first_chunk_emitted.wait()
        try:
            await asyncio.wait_for(answer_seen.wait(), timeout=0.05)
        except TimeoutError:
            pass
        else:
            raise AssertionError("Required grounding released an invalid answer.")
        model.finish.set()
        result = await task
        assert result.grounding_status == "unavailable"
        assert result.grounding_meta["error"] == "invalid_evidence_ids"
        assert result.content.startswith("Unable to verify this answer")
        assert not any(event.get("type") == "answer_reset" for event in events)

    asyncio.run(execute())


def test_required_inline_grounding_streams_only_after_a_valid_manifest() -> None:
    async def execute() -> None:
        model = GatedStreamingModel(
            '<nexaflow-grounding>{"status":"grounded",'
            '"evidence_ids":["chunk-1"],"reason_codes":[]}'
            "</nexaflow-grounding>\n"
        )
        answer_seen = asyncio.Event()
        events: list[dict[str, Any]] = []

        async def emit(event: dict[str, Any]) -> None:
            events.append(event)
            if event.get("type") == "answer_delta":
                answer_seen.set()

        task = asyncio.create_task(
            run_agent(
                model,
                [{"role": "user", "content": "Answer from evidence."}],
                [],
                on_event=emit,
                grounding_mode="required",
                initial_evidence=[{"chunk_id": "chunk-1", "content": "fact"}],
            )
        )
        await model.first_chunk_emitted.wait()
        await asyncio.wait_for(answer_seen.wait(), timeout=0.1)
        assert [
            event.get("delta")
            for event in events
            if event.get("type") == "answer_delta"
        ] == ["Live"]
        model.finish.set()
        result = await task
        assert result.content == "Live answer."
        assert result.grounding_status == "grounded"
        assert [
            event.get("delta")
            for event in events
            if event.get("type") == "answer_delta"
        ] == ["Live", " answer."]

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
            "grounding_status": "grounded",
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
    test_inline_grounding_precedes_streamed_markdown_without_a_second_call()
    test_release_gate()
    test_gate_rejects_blocked_tools_and_unreported_usage()
    test_inline_grounding_stays_within_the_primary_model_token_budget()
    test_agentic_inline_grounding_streams_a_skipped_answer()
    test_required_inline_grounding_rejects_unknown_evidence_before_output()
    test_required_inline_grounding_streams_only_after_a_valid_manifest()
    test_live_runner_contract_is_safe_and_observable()
    print("AGENT_EVALUATION_OK")


if __name__ == "__main__":
    main()
