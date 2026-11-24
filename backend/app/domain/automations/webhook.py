"""HMAC-SHA256 verification and replay protection for automation webhooks."""

import hashlib
import hmac
import json
import secrets
from datetime import datetime
from typing import Any

MAX_WEBHOOK_PAYLOAD_BYTES = 256 * 1024
MAX_WEBHOOK_TIMESTAMP_SKEW_SECONDS = 300
DEFAULT_WEBHOOK_MAX_PENDING = 20
MAX_WEBHOOK_MAX_PENDING = 100


def generate_webhook_secret() -> str:
    return f"whsec_{secrets.token_urlsafe(32)}"


def canonical_payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sign_webhook_payload(
    secret: str, timestamp: str, raw_body: bytes, event_id: str
) -> str:
    signed = f"{timestamp}.{normalize_event_id(event_id)}.".encode("utf-8") + raw_body
    digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def normalize_event_id(value: str | None) -> str:
    trimmed = (value or "").strip()
    if (
        not trimmed
        or len(trimmed) > 128
        or not trimmed.isascii()
        or any(not 33 <= ord(ch) <= 126 for ch in trimmed)
    ):
        raise ValueError("Invalid or missing X-NexaFlow-Event-Id header.")
    return trimmed


def verify_webhook_signature(
    *,
    secret: str,
    timestamp_header: str | None,
    signature_header: str | None,
    event_id_header: str | None,
    raw_body: bytes,
    now_utc: datetime,
) -> tuple[str, int]:
    """Validate event ID, timestamp freshness, and constant-time HMAC-SHA256 digest."""
    event_id = normalize_event_id(event_id_header)
    raw_ts = (timestamp_header or "").strip()
    if not raw_ts or len(raw_ts) > 20 or not raw_ts.isascii() or not raw_ts.isdigit():
        raise ValueError("Invalid or missing X-NexaFlow-Timestamp header.")
    timestamp_int = int(raw_ts)
    skew = abs(int(now_utc.timestamp()) - timestamp_int)
    if skew > MAX_WEBHOOK_TIMESTAMP_SKEW_SECONDS:
        raise ValueError("Webhook timestamp is outside the allowed tolerance window.")

    raw_sig = (signature_header or "").strip()
    if not raw_sig.lower().startswith("sha256="):
        raise ValueError("Invalid or missing X-NexaFlow-Signature header.")
    provided_hex = raw_sig[7:].strip().lower()
    if len(provided_hex) != 64 or any(
        ch not in "0123456789abcdef" for ch in provided_hex
    ):
        raise ValueError("Malformed X-NexaFlow-Signature digest.")

    expected_sig = sign_webhook_payload(secret, raw_ts, raw_body, event_id)[7:]
    if not hmac.compare_digest(expected_sig, provided_hex):
        raise ValueError("Webhook signature verification failed.")
    return event_id, timestamp_int
