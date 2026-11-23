"""Input validation and safe external webhook mapping for automations."""

import json
import re
from copy import deepcopy
from typing import Any

MAX_GOAL_LENGTH = 4000
MAX_WEBHOOK_PATH_LENGTH = 200
_TEMPLATE_TOKEN_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")
_RESERVED_WORKFLOW_KEYS = frozenset({"files", "document"})


def _resolve_dotted_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for segment in path.split("."):
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        else:
            return None
    return current


def _render_template(template: str, payload: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        val = _resolve_dotted_path(payload, match.group(1))
        if val is None:
            raise ValueError(
                f"Webhook payload missing required path '{match.group(1)}'."
            )
        if isinstance(val, (dict, list)):
            return json.dumps(val, ensure_ascii=False)
        return str(val)

    return _TEMPLATE_TOKEN_RE.sub(replace, template)


def validate_input_config(raw_config: dict[str, Any]) -> dict[str, Any]:
    """Validate text / structured JSON input config and optional webhook mapping."""
    config = dict(raw_config or {})
    mode = config.get("mode", "text")
    if mode not in {"text", "json"}:
        raise ValueError("input_config.mode must be 'text' or 'json'.")

    raw_text = config.get("text", "")
    if raw_text is None:
        raw_text = ""
    if not isinstance(raw_text, str):
        raise ValueError("input_config.text must be a string.")
    text = raw_text.strip()
    if len(text) > MAX_GOAL_LENGTH:
        raise ValueError(
            f"input_config.text must be at most {MAX_GOAL_LENGTH} characters."
        )

    raw_json = config.get("json_payload")
    if raw_json is None:
        json_payload: dict[str, Any] = {}
    elif isinstance(raw_json, dict):
        json_payload = deepcopy(raw_json)
    else:
        raise ValueError("input_config.json_payload must be a JSON object.")

    encoded_json = json.dumps(json_payload, ensure_ascii=False, allow_nan=False)
    if len(encoded_json.encode("utf-8")) > 256 * 1024:
        raise ValueError("Automation JSON input exceeds maximum allowed size.")

    raw_path = config.get("webhook_input_path")
    webhook_input_path: str | None = None
    if isinstance(raw_path, str) and raw_path.strip():
        webhook_input_path = raw_path.strip()
        if len(webhook_input_path) > MAX_WEBHOOK_PATH_LENGTH or not re.fullmatch(
            r"[A-Za-z0-9_.-]+", webhook_input_path
        ):
            raise ValueError("webhook_input_path must be a valid dotted key path.")

    raw_template = config.get("webhook_prompt_template")
    webhook_prompt_template: str | None = None
    if isinstance(raw_template, str) and raw_template.strip():
        webhook_prompt_template = raw_template.strip()
        if len(webhook_prompt_template) > MAX_GOAL_LENGTH:
            raise ValueError("webhook_prompt_template exceeds maximum length.")

    if (
        mode == "text"
        and not text
        and not webhook_input_path
        and not webhook_prompt_template
    ):
        raise ValueError("Text input mode requires 'text' or a webhook mapping rule.")

    return {
        "mode": mode,
        "text": text,
        "json_payload": json_payload,
        "webhook_input_path": webhook_input_path,
        "webhook_prompt_template": webhook_prompt_template,
    }


def build_execution_input_snapshot(
    input_config: dict[str, Any],
    *,
    webhook_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build immutable frozen input snapshot; webhook data only populates inputs."""
    normalized = validate_input_config(input_config)
    mode = normalized["mode"]
    base_json = dict(normalized["json_payload"])
    mapped_payload: Any = None
    if webhook_payload is not None:
        if not isinstance(webhook_payload, dict):
            raise ValueError("Webhook payload must be a JSON object.")
        if normalized["webhook_input_path"]:
            extracted = _resolve_dotted_path(
                webhook_payload, normalized["webhook_input_path"]
            )
            if extracted is None:
                raise ValueError(
                    f"Webhook payload missing required path '{normalized['webhook_input_path']}'."
                )
            mapped_payload = extracted
        else:
            mapped_payload = deepcopy(webhook_payload)

    merged_json: dict[str, Any] = dict(base_json)
    if isinstance(mapped_payload, dict):
        merged_json.update(mapped_payload)
    elif mapped_payload is not None:
        merged_json["value"] = mapped_payload

    question_text = ""
    if normalized["webhook_prompt_template"] and isinstance(webhook_payload, dict):
        question_text = _render_template(
            normalized["webhook_prompt_template"], webhook_payload
        ).strip()
    elif isinstance(mapped_payload, str) and mapped_payload.strip():
        question_text = mapped_payload.strip()
    elif normalized["text"]:
        question_text = normalized["text"]

    if webhook_payload is not None and mode == "text" and not question_text:
        question_text = json.dumps(
            mapped_payload if mapped_payload is not None else webhook_payload,
            ensure_ascii=False,
        )

    if not question_text:
        for candidate_key in (
            "question",
            "prompt",
            "message",
            "task",
            "query",
            "input",
        ):
            candidate = merged_json.get(candidate_key)
            if isinstance(candidate, str) and candidate.strip():
                question_text = candidate.strip()
                break
    if not question_text:
        if merged_json:
            question_text = json.dumps(merged_json, ensure_ascii=False)
        else:
            question_text = "Execute scheduled task"

    if (
        webhook_payload is not None
        and mode == "text"
        and normalized["text"]
        and not normalized["webhook_prompt_template"]
        and not isinstance(mapped_payload, str)
    ):
        suffix = json.dumps(mapped_payload, ensure_ascii=False)
        question_text = f"{normalized['text']}\n\n```json\n{suffix}\n```"
    elif (
        mode == "json"
        and merged_json
        and question_text == normalized["text"]
        and normalized["text"]
    ):
        suffix = json.dumps(merged_json, ensure_ascii=False)
        question_text = f"{normalized['text']}\n\n```json\n{suffix}\n```"

    if len(question_text) > MAX_GOAL_LENGTH:
        raise ValueError("Automation task input exceeds 4000 characters.")
    question_text = question_text.strip() or "Execute automation task"

    extra_inputs: dict[str, Any] = {}
    if merged_json:
        extra_inputs["payload"] = merged_json
        for key, value in merged_json.items():
            if (
                isinstance(key, str)
                and key not in _RESERVED_WORKFLOW_KEYS
                and key != "question"
            ):
                extra_inputs[key] = value

    return {
        "mode": mode,
        "goal": question_text,
        "json_payload": merged_json,
        "extra_inputs": extra_inputs,
        "webhook_received": webhook_payload is not None,
    }


def extract_run_goal_and_extra_inputs(
    frozen_input: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    goal = (
        str(frozen_input.get("goal") or "").strip()[:MAX_GOAL_LENGTH]
        or "Execute automation task"
    )
    extra = frozen_input.get("extra_inputs")
    return (goal, dict(extra) if isinstance(extra, dict) else {})
