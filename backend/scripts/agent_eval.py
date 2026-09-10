"""Run a release-gate evaluation suite against a live NexaFlow Agent."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.domain.agents.evaluation import (
    AgentEvaluationCase,
    AgentEvaluationObservation,
    AgentEvaluationResult,
    AgentEvaluationSuite,
    agent_evaluation_gate,
    evaluate_agent_observation,
)

TERMINAL_RUN_STATUSES = frozenset(
    {"succeeded", "failed", "cancelled", "awaiting_approval", "awaiting_input"}
)


class AgentEvaluationError(RuntimeError):
    """A bounded, user-safe live evaluation error."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class AgentEvaluationClient:
    def __init__(self, base_url: str, token: str, *, request_timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise AgentEvaluationError("The evaluation base URL is invalid.")
        if parsed.username is not None or parsed.password is not None:
            raise AgentEvaluationError("The evaluation base URL must not contain credentials.")
        if parsed.scheme == "http" and parsed.hostname not in {
            "127.0.0.1",
            "::1",
            "localhost",
        }:
            raise AgentEvaluationError(
                "Evaluation Bearer tokens require HTTPS except on loopback."
            )
        self.token = token
        self.request_timeout = request_timeout
        self.opener = build_opener(_NoRedirect())

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token}",
        }
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with self.opener.open(request, timeout=self.request_timeout) as response:
                value = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = f"HTTP {exc.code}"
            try:
                body = json.loads(exc.read(4096).decode("utf-8"))
                if isinstance(body, dict) and isinstance(body.get("detail"), str):
                    detail = f"{detail}: {body['detail'][:300]}"
            except (UnicodeDecodeError, ValueError):
                pass
            raise AgentEvaluationError(detail) from exc
        except (TimeoutError, URLError) as exc:
            raise AgentEvaluationError(type(exc).__name__) from exc
        except (UnicodeDecodeError, ValueError) as exc:
            raise AgentEvaluationError("The API returned invalid JSON.") from exc
        if not isinstance(value, dict):
            raise AgentEvaluationError("The API returned an invalid response object.")
        return value


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _duration_ms(run: dict[str, Any], fallback_seconds: float) -> int:
    started = _parse_timestamp(run.get("started_at"))
    finished = _parse_timestamp(run.get("finished_at"))
    if started is not None and finished is not None:
        return max(0, round((finished - started).total_seconds() * 1000))
    return max(0, round(fallback_seconds * 1000))


def observation_from_run(
    run: dict[str, Any],
    *,
    fallback_seconds: float,
) -> AgentEvaluationObservation:
    events = run.get("events")
    safe_events = events if isinstance(events, list) else []
    observed = tuple(
        str(event.get("tool_name"))
        for event in safe_events
        if isinstance(event, dict)
        and event.get("type") == "tool"
        and isinstance(event.get("tool_name"), str)
        and event.get("tool_name")
    )
    successful = tuple(
        str(event.get("tool_name"))
        for event in safe_events
        if isinstance(event, dict)
        and event.get("type") == "tool"
        and event.get("status") == "succeeded"
        and isinstance(event.get("tool_name"), str)
        and event.get("tool_name")
    )
    sources = run.get("sources")
    usage = run.get("model_usage")
    return AgentEvaluationObservation(
        status=str(run.get("status") or "unknown"),
        answer=str(run.get("result") or ""),
        grounding_status=str(run.get("grounding_status") or "not_started"),
        successful_tool_names=successful,
        observed_tool_names=observed,
        source_count=len(sources) if isinstance(sources, list) else 0,
        model_usage=usage if isinstance(usage, dict) else {},
        duration_ms=_duration_ms(run, fallback_seconds),
    )


def execute_case(
    client: AgentEvaluationClient,
    case: AgentEvaluationCase,
    *,
    workspace_id: str,
    agent_id: str,
    sample: int,
    poll_seconds: float,
    timeout_seconds: float,
) -> AgentEvaluationResult:
    root = (
        "/api/v1/workspaces/"
        f"{quote(workspace_id, safe='')}/agents/{quote(agent_id, safe='')}"
    )
    started = time.monotonic()
    run = client.request(
        "POST",
        f"{root}/runs",
        {"goal": case.goal, "conversation_id": str(uuid.uuid4())},
    )
    run_id = run.get("id")
    if not isinstance(run_id, str) or not run_id:
        raise AgentEvaluationError("The create-run response omitted the run id.")
    deadline = started + timeout_seconds
    while str(run.get("status") or "") not in TERMINAL_RUN_STATUSES:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            cancelled = client.request(
                "POST",
                f"{root}/runs/{quote(run_id, safe='')}/cancel",
            )
            run = {**cancelled, "status": "timed_out"}
            break
        time.sleep(min(poll_seconds, remaining))
        run = client.request("GET", f"{root}/runs/{quote(run_id, safe='')}")
    observation = observation_from_run(
        run,
        fallback_seconds=time.monotonic() - started,
    )
    return replace(
        evaluate_agent_observation(case, observation, sample=sample),
        run_id=run_id,
    )


def _report(
    suite: AgentEvaluationSuite,
    results: list[AgentEvaluationResult],
) -> tuple[bool, dict[str, Any]]:
    passed, summary = agent_evaluation_gate(suite, results)
    return passed, {
        "schema_version": 1,
        "gate": "passed" if passed else "failed",
        "summary": summary,
        "results": [
            {
                "case_id": result.case_id,
                "category": result.category,
                "sample": result.sample,
                "required": result.required,
                "passed": result.passed,
                "failures": list(result.failures),
                "run_id": result.run_id,
            }
            for result in results
        ],
    }


def _load_suite(path: Path) -> AgentEvaluationSuite:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise AgentEvaluationError(f"Unable to read dataset: {exc}") from exc
    except ValueError as exc:
        raise AgentEvaluationError("The evaluation dataset is invalid JSON.") from exc
    try:
        return AgentEvaluationSuite.from_dict(payload)
    except ValueError as exc:
        raise AgentEvaluationError(str(exc)) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a release-gate evaluation against one live Agent."
    )
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("NEXAFLOW_EVAL_BASE_URL", "http://127.0.0.1:8000"),
    )
    parser.add_argument(
        "--workspace-id", default=os.environ.get("NEXAFLOW_EVAL_WORKSPACE_ID")
    )
    parser.add_argument("--agent-id", default=os.environ.get("NEXAFLOW_EVAL_AGENT_ID"))
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--request-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.workspace_id or not args.agent_id:
        parser.error("--workspace-id and --agent-id are required")
    if args.poll_seconds <= 0 or args.timeout_seconds <= 0:
        parser.error("poll and run timeout values must be positive")
    if args.request_timeout_seconds <= 0:
        parser.error("request timeout must be positive")
    return args


def main() -> int:
    args = parse_args()
    token = os.environ.get("NEXAFLOW_EVAL_TOKEN", "").strip()
    if not token:
        print("NEXAFLOW_EVAL_TOKEN is required.", file=sys.stderr)
        return 2
    try:
        suite = _load_suite(args.dataset)
        client = AgentEvaluationClient(
            args.base_url,
            token,
            request_timeout=args.request_timeout_seconds,
        )
        results = [
            execute_case(
                client,
                case,
                workspace_id=args.workspace_id,
                agent_id=args.agent_id,
                sample=sample,
                poll_seconds=args.poll_seconds,
                timeout_seconds=args.timeout_seconds,
            )
            for case in suite.cases
            for sample in range(1, case.samples + 1)
        ]
        passed, report = _report(suite, results)
        rendered = json.dumps(report, ensure_ascii=False, indent=2)
        print(rendered)
        if args.output is not None:
            try:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(rendered + "\n", encoding="utf-8")
            except OSError as exc:
                raise AgentEvaluationError(
                    f"Unable to write evaluation report: {exc}"
                ) from exc
        return 0 if passed else 1
    except AgentEvaluationError as exc:
        print(f"Agent evaluation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
