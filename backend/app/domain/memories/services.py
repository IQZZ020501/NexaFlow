"""Pure selection and validation of source-backed personalization data."""

import json
import re
from datetime import datetime, timezone

CATEGORIES = {"preference", "background", "goal", "project"}
MAX_MEMORIES = 100
MEMORY_REQUEST = re.compile(
    r"记住|記住|记得|記得|忘记|忘記|不要再记|不要再記|\bremember\b|\bforget\b|\bkeep in mind\b",
    re.I,
)
SENSITIVE = re.compile(
    r"password|api[_ -]?key|access[_ -]?token|private[_ -]?key|密码|密碼|私钥|私鑰|身份证|身分證|银行卡|銀行卡|sk-[A-Za-z0-9]{12,}|-----BEGIN",
    re.I,
)


def timestamp(value: datetime) -> float:
    return value.replace(tzinfo=value.tzinfo or timezone.utc).timestamp()


def terms(text: str) -> set[str]:
    lowered = text.casefold()
    words = set(re.findall(r"[a-z0-9_]{2,}", lowered))
    for phrase in re.findall(r"[\u3400-\u9fff]+", lowered):
        words.update(phrase[index : index + 2] for index in range(len(phrase) - 1))
    return words


def select_memories(items, query: str, project_id: str, now: datetime):
    query_terms = terms(query)
    ranked = []
    for item in items:
        if item.project_id and item.project_id != project_id:
            continue
        if item.expires_at is not None and timestamp(item.expires_at) <= timestamp(now):
            continue
        overlap = len(query_terms & terms(item.key + " " + item.content))
        if item.category != "preference" and overlap == 0:
            continue
        ranked.append((item, overlap))
    ranked.sort(
        key=lambda pair: (
            pair[0].category == "preference",
            pair[1],
            timestamp(pair[0].updated_at),
        ),
        reverse=True,
    )
    selected, chars = [], 0
    for item, _ in ranked[:8]:
        if chars + len(item.content) > 2400:
            continue
        selected.append(
            {
                "category": item.category,
                "key": item.key,
                "content": item.content,
                "project_id": item.project_id,
            }
        )
        chars += len(item.content)
    return selected


def parse_candidates(
    text: str, sources: list[str], *, automatic: bool, project_id: str
):
    """An exact quote and an eligible user source are mandatory for every edit."""
    try:
        values = json.loads(text)
    except (TypeError, ValueError):
        return []
    if not isinstance(values, list):
        return []
    result = []
    for value in values[:8]:
        if not isinstance(value, dict):
            continue
        source_index = value.get("source_index")
        if type(source_index) is not int or not 0 <= source_index < len(sources):
            continue
        source = sources[source_index]
        quote = value.get("quote")
        key, content = value.get("key"), value.get("content")
        category, action = value.get("category"), value.get("action")
        scope = value.get("scope")
        if not isinstance(scope, str) or scope not in {"user", "project"}:
            continue
        explicit = bool(MEMORY_REQUEST.search(source))
        if not automatic and not explicit:
            continue
        if (
            not isinstance(quote, str)
            or not 3 <= len(quote) <= 600
            or quote not in source
        ):
            continue
        if (
            not isinstance(category, str)
            or category not in CATEGORIES
            or not isinstance(action, str)
            or action not in {"upsert", "delete"}
        ):
            continue
        if not isinstance(key, str) or not 1 <= len(key.strip()) <= 80:
            continue
        if not isinstance(content, str) or not 1 <= len(content.strip()) <= 600:
            continue
        if SENSITIVE.search(key + " " + content + " " + quote):
            continue
        if action == "delete" and not explicit:
            continue
        scoped = scope == "project"
        if (scoped or category == "project") and not project_id:
            continue
        result.append(
            {
                "action": action,
                "key": key.strip().casefold(),
                "content": content.strip(),
                "category": category,
                "source_quote": quote,
                "project_id": project_id if scoped or category == "project" else "",
                "origin": "explicit" if explicit else "automatic",
            }
        )
    return result
