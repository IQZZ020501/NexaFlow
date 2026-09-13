"""Single-pass grounding manifest parsing for streamed Agent answers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

INLINE_GROUNDING_OPEN = "<nexaflow-grounding>"
INLINE_GROUNDING_CLOSE = "</nexaflow-grounding>"
MAX_INLINE_GROUNDING_CHARS = 4_096
GROUNDING_FALLBACK_ANSWER = (
    "Unable to verify this answer against the configured workspace knowledge sources."
)
GROUNDING_INSUFFICIENT_FALLBACK_ANSWER = (
    "The available workspace evidence is not sufficient to verify every detail. "
    "Please treat any unverified portion as provisional and provide a more specific "
    "question or the relevant source if you need a definitive answer."
)

InlineGroundingMode = Literal["agentic", "required"]


@dataclass(frozen=True)
class InlineGroundingOutcome:
    status: str
    meta: dict[str, Any]


def _available_evidence_ids(
    evidence_packets: list[dict[str, Any]],
) -> set[str]:
    return {
        value
        for packet in evidence_packets
        for value in (
            [packet.get("chunk_id")]
            + list(packet.get("contributing_chunk_ids") or [])
        )
        if isinstance(value, str) and value
    }


def _audit_meta(evidence_packets: list[dict[str, Any]]) -> dict[str, Any]:
    evidence_payload = json.dumps(
        evidence_packets,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return {
        "evidence_digest": hashlib.sha256(evidence_payload.encode()).hexdigest(),
        "evidence_packet_count": len(evidence_packets),
        "evidence_truncated": len(evidence_packets) >= 32
        or any(packet.get("content_truncated") is True for packet in evidence_packets),
        "mode": "inline",
    }


def _strings(value: Any, *, limit: int) -> list[str] | None:
    if not isinstance(value, list) or len(value) > limit:
        return None
    if any(not isinstance(item, str) or not item for item in value):
        return None
    return list(dict.fromkeys(value))


def validate_inline_grounding_manifest(
    raw_manifest: str,
    evidence_packets: list[dict[str, Any]],
    mode: InlineGroundingMode,
) -> InlineGroundingOutcome:
    audit = _audit_meta(evidence_packets)
    try:
        payload = json.loads(raw_manifest)
    except (TypeError, ValueError):
        payload = None
    if not isinstance(payload, dict):
        return InlineGroundingOutcome(
            "unavailable",
            {"decision": "unavailable", "error": "invalid_manifest", **audit},
        )

    status = payload.get("status")
    evidence_ids = _strings(payload.get("evidence_ids"), limit=32)
    reason_codes = _strings(payload.get("reason_codes"), limit=8)
    if (
        status not in {"grounded", "insufficient", "skipped"}
        or evidence_ids is None
        or reason_codes is None
    ):
        return InlineGroundingOutcome(
            "unavailable",
            {"decision": "unavailable", "error": "invalid_manifest", **audit},
        )

    available_ids = _available_evidence_ids(evidence_packets)
    if status == "grounded" and (
        not evidence_ids or any(item not in available_ids for item in evidence_ids)
    ):
        return InlineGroundingOutcome(
            "unavailable",
            {
                "decision": "unavailable",
                "error": "invalid_evidence_ids",
                **audit,
            },
        )
    if status == "skipped" and (mode == "required" or evidence_ids or available_ids):
        return InlineGroundingOutcome(
            "unavailable",
            {"decision": "unavailable", "error": "invalid_skip", **audit},
        )

    return InlineGroundingOutcome(
        str(status),
        {
            "decision": status,
            "evidence_ids": evidence_ids,
            "reason_codes": reason_codes,
            **audit,
        },
    )


class InlineGroundingStreamFilter:
    """Hide and validate a grounding manifest before releasing answer Markdown."""

    def __init__(
        self,
        evidence_packets: list[dict[str, Any]],
        mode: InlineGroundingMode,
    ) -> None:
        self._evidence_packets = evidence_packets
        self._mode = mode
        self._buffer = ""
        self._visible_parts: list[str] = []
        self.outcome: InlineGroundingOutcome | None = None

    @property
    def visible_content(self) -> str:
        return "".join(self._visible_parts)

    def _record_visible(self, value: str) -> str:
        if value:
            self._visible_parts.append(value)
        return value

    def push(self, delta: str) -> str:
        if not delta:
            return ""
        if self.outcome is not None:
            if self.outcome.status in {"grounded", "insufficient", "skipped"}:
                return self._record_visible(delta)
            return ""

        self._buffer += delta
        if (
            len(self._buffer) > MAX_INLINE_GROUNDING_CHARS
            and INLINE_GROUNDING_CLOSE not in self._buffer
        ):
            self.outcome = InlineGroundingOutcome(
                "unavailable",
                {
                    "decision": "unavailable",
                    "error": "manifest_too_large",
                    **_audit_meta(self._evidence_packets),
                },
            )
            self._buffer = ""
            return ""
        candidate = self._buffer.lstrip()
        if not candidate.startswith(INLINE_GROUNDING_OPEN):
            return ""
        close_index = candidate.find(INLINE_GROUNDING_CLOSE)
        if close_index < 0:
            return ""
        manifest_start = len(INLINE_GROUNDING_OPEN)
        self.outcome = validate_inline_grounding_manifest(
            candidate[manifest_start:close_index],
            self._evidence_packets,
            self._mode,
        )
        remainder = candidate[close_index + len(INLINE_GROUNDING_CLOSE) :]
        if remainder.startswith("\r\n"):
            remainder = remainder[2:]
        elif remainder.startswith(("\r", "\n")):
            remainder = remainder[1:]
        self._buffer = ""
        if self.outcome.status not in {"grounded", "insufficient", "skipped"}:
            return ""
        return self._record_visible(remainder)

    def finish(self) -> str:
        if self.outcome is None:
            audit = _audit_meta(self._evidence_packets)
            may_skip = (
                self._mode == "agentic"
                and not _available_evidence_ids(self._evidence_packets)
                and INLINE_GROUNDING_OPEN not in self._buffer
            )
            status = "skipped" if may_skip else "unavailable"
            self.outcome = InlineGroundingOutcome(
                status,
                {
                    "decision": status,
                    "reason" if may_skip else "error": "missing_manifest",
                    **audit,
                },
            )
            if may_skip:
                visible = self._buffer
            else:
                visible = GROUNDING_FALLBACK_ANSWER
            self._buffer = ""
            return self._record_visible(visible)
        if self.outcome.status == "unavailable":
            return self._record_visible(GROUNDING_FALLBACK_ANSWER)
        if self.outcome.status == "insufficient" and not self.visible_content.strip():
            return self._record_visible(GROUNDING_INSUFFICIENT_FALLBACK_ANSWER)
        return ""


__all__ = [
    "GROUNDING_FALLBACK_ANSWER",
    "GROUNDING_INSUFFICIENT_FALLBACK_ANSWER",
    "INLINE_GROUNDING_CLOSE",
    "INLINE_GROUNDING_OPEN",
    "MAX_INLINE_GROUNDING_CHARS",
    "InlineGroundingMode",
    "InlineGroundingOutcome",
    "InlineGroundingStreamFilter",
    "validate_inline_grounding_manifest",
]
