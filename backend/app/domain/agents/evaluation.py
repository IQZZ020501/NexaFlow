"""Pure Agent evaluation contracts and deterministic release-gate scoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _strings(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{field_name} must be an array of non-empty strings.")
    return tuple(item.strip() for item in value)


def _positive_int(value: Any, field_name: str, default: int | None = None) -> int | None:
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")
    return value


def _observed_non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, float) and value >= 0 and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


@dataclass(frozen=True)
class AgentEvaluationExpectation:
    status: str = "succeeded"
    grounding_statuses: tuple[str, ...] = ()
    answer_contains: tuple[str, ...] = ()
    answer_not_contains: tuple[str, ...] = ()
    required_tool_names: tuple[str, ...] = ()
    forbidden_tool_names: tuple[str, ...] = ()
    min_sources: int = 0
    max_total_tokens: int | None = None
    max_model_calls: int | None = None
    max_duration_ms: int | None = None

    @classmethod
    def from_dict(cls, value: Any) -> AgentEvaluationExpectation:
        if not isinstance(value, dict):
            raise ValueError("expect must be an object.")
        status = value.get("status", "succeeded")
        if not isinstance(status, str) or not status.strip():
            raise ValueError("expect.status must be a non-empty string.")
        min_sources = value.get("min_sources", 0)
        if (
            not isinstance(min_sources, int)
            or isinstance(min_sources, bool)
            or min_sources < 0
        ):
            raise ValueError("expect.min_sources must be a non-negative integer.")
        return cls(
            status=status.strip(),
            grounding_statuses=_strings(
                value.get("grounding_statuses"),
                "expect.grounding_statuses",
            ),
            answer_contains=_strings(
                value.get("answer_contains"),
                "expect.answer_contains",
            ),
            answer_not_contains=_strings(
                value.get("answer_not_contains"),
                "expect.answer_not_contains",
            ),
            required_tool_names=_strings(
                value.get("required_tool_names"),
                "expect.required_tool_names",
            ),
            forbidden_tool_names=_strings(
                value.get("forbidden_tool_names"),
                "expect.forbidden_tool_names",
            ),
            min_sources=min_sources,
            max_total_tokens=_positive_int(
                value.get("max_total_tokens"),
                "expect.max_total_tokens",
            ),
            max_model_calls=_positive_int(
                value.get("max_model_calls"),
                "expect.max_model_calls",
            ),
            max_duration_ms=_positive_int(
                value.get("max_duration_ms"),
                "expect.max_duration_ms",
            ),
        )


@dataclass(frozen=True)
class AgentEvaluationCase:
    id: str
    goal: str
    category: str
    expectation: AgentEvaluationExpectation
    samples: int = 1
    required: bool = True

    @classmethod
    def from_dict(cls, value: Any) -> AgentEvaluationCase:
        if not isinstance(value, dict):
            raise ValueError("Each evaluation case must be an object.")
        case_id = value.get("id")
        goal = value.get("goal")
        category = value.get("category", "general")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError("Evaluation case id must be a non-empty string.")
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError(f"Evaluation case {case_id!r} needs a non-empty goal.")
        if not isinstance(category, str) or not category.strip():
            raise ValueError(f"Evaluation case {case_id!r} has an invalid category.")
        required = value.get("required", True)
        if not isinstance(required, bool):
            raise ValueError(f"Evaluation case {case_id!r} required must be boolean.")
        return cls(
            id=case_id.strip(),
            goal=goal.strip(),
            category=category.strip(),
            expectation=AgentEvaluationExpectation.from_dict(value.get("expect", {})),
            samples=_positive_int(value.get("samples"), "samples", 1) or 1,
            required=required,
        )


@dataclass(frozen=True)
class AgentEvaluationSuite:
    cases: tuple[AgentEvaluationCase, ...]
    minimum_pass_rate: float = 1.0

    @classmethod
    def from_dict(cls, value: Any) -> AgentEvaluationSuite:
        if not isinstance(value, dict):
            raise ValueError("Evaluation suite must be an object.")
        raw_cases = value.get("cases")
        if not isinstance(raw_cases, list) or not raw_cases:
            raise ValueError("Evaluation suite cases must be a non-empty array.")
        cases = tuple(AgentEvaluationCase.from_dict(item) for item in raw_cases)
        ids = [item.id for item in cases]
        if len(ids) != len(set(ids)):
            raise ValueError("Evaluation case ids must be unique.")
        gate = value.get("gate", {})
        if not isinstance(gate, dict):
            raise ValueError("Evaluation suite gate must be an object.")
        minimum = gate.get("minimum_pass_rate", 1.0)
        if (
            not isinstance(minimum, (int, float))
            or isinstance(minimum, bool)
            or not 0 < float(minimum) <= 1
        ):
            raise ValueError("gate.minimum_pass_rate must be greater than 0 and at most 1.")
        return cls(cases=cases, minimum_pass_rate=float(minimum))


@dataclass(frozen=True)
class AgentEvaluationObservation:
    status: str
    answer: str
    grounding_status: str
    successful_tool_names: tuple[str, ...] = ()
    observed_tool_names: tuple[str, ...] = ()
    source_count: int = 0
    model_usage: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0


@dataclass(frozen=True)
class AgentEvaluationResult:
    case_id: str
    category: str
    sample: int
    required: bool
    passed: bool
    failures: tuple[str, ...]
    run_id: str = ""


def evaluate_agent_observation(
    case: AgentEvaluationCase,
    observation: AgentEvaluationObservation,
    *,
    sample: int,
) -> AgentEvaluationResult:
    expected = case.expectation
    failures: list[str] = []
    if observation.status != expected.status:
        failures.append(f"status:{observation.status}")
    if (
        expected.grounding_statuses
        and observation.grounding_status not in expected.grounding_statuses
    ):
        failures.append(f"grounding_status:{observation.grounding_status}")
    for index, text in enumerate(expected.answer_contains, start=1):
        if text not in observation.answer:
            failures.append(f"answer_missing:{index}")
    for index, text in enumerate(expected.answer_not_contains, start=1):
        if text in observation.answer:
            failures.append(f"answer_forbidden:{index}")
    successful = set(observation.successful_tool_names)
    observed = set(observation.observed_tool_names)
    for name in expected.required_tool_names:
        if name not in successful:
            failures.append(f"tool_missing:{name}")
    for name in expected.forbidden_tool_names:
        if name in observed:
            failures.append(f"tool_forbidden:{name}")
    if observation.source_count < expected.min_sources:
        failures.append(f"sources:{observation.source_count}")

    usage = observation.model_usage
    model_calls = _observed_non_negative_int(usage.get("model_calls"))
    reported_calls = _observed_non_negative_int(
        usage.get("reported_model_calls")
    )
    total_tokens = _observed_non_negative_int(usage.get("total_tokens"))
    if expected.max_total_tokens is not None:
        if model_calls is None or reported_calls is None or total_tokens is None:
            failures.append("usage:invalid")
        elif model_calls != reported_calls:
            failures.append("usage:unreported")
        elif total_tokens > expected.max_total_tokens:
            failures.append(f"total_tokens:{total_tokens}")
    if expected.max_model_calls is not None:
        if model_calls is None:
            if "usage:invalid" not in failures:
                failures.append("usage:invalid")
        elif model_calls > expected.max_model_calls:
            failures.append(f"model_calls:{model_calls}")
    if (
        expected.max_duration_ms is not None
        and observation.duration_ms > expected.max_duration_ms
    ):
        failures.append(f"duration_ms:{observation.duration_ms}")
    return AgentEvaluationResult(
        case_id=case.id,
        category=case.category,
        sample=sample,
        required=case.required,
        passed=not failures,
        failures=tuple(failures),
    )


def agent_evaluation_gate(
    suite: AgentEvaluationSuite,
    results: list[AgentEvaluationResult],
) -> tuple[bool, dict[str, Any]]:
    expected_samples = sum(case.samples for case in suite.cases)
    if len(results) != expected_samples:
        raise ValueError("Evaluation result count does not match the suite samples.")
    passed = sum(result.passed for result in results)
    pass_rate = passed / expected_samples
    required_failures = [
        f"{result.case_id}#{result.sample}"
        for result in results
        if result.required and not result.passed
    ]
    gate_passed = pass_rate >= suite.minimum_pass_rate and not required_failures
    return gate_passed, {
        "passed": passed,
        "total": expected_samples,
        "pass_rate": round(pass_rate, 6),
        "minimum_pass_rate": suite.minimum_pass_rate,
        "required_failures": required_failures,
    }


__all__ = [
    "AgentEvaluationCase",
    "AgentEvaluationExpectation",
    "AgentEvaluationObservation",
    "AgentEvaluationResult",
    "AgentEvaluationSuite",
    "agent_evaluation_gate",
    "evaluate_agent_observation",
]
