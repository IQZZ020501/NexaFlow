"""Pure unit tests for automation schedules, input mapping, and HMAC verification."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import tests.support  # noqa: F401

from app.domain.automations import (
    build_execution_input_snapshot,
    canonical_payload_hash,
    compute_next_schedule_at,
    resolve_due_schedule_slot,
    sign_webhook_payload,
    validate_input_config,
    validate_trigger_config,
    verify_webhook_signature,
)

BJ = ZoneInfo("Asia/Shanghai")


def test_beijing_schedules_and_catchup() -> None:
    # Daily 09:30 Beijing time
    cfg = validate_trigger_config("daily", {"hour": 9, "minute": 30})
    after = datetime(2026, 11, 24, 9, 0, tzinfo=BJ).astimezone(UTC)
    next_dt = compute_next_schedule_at("daily", cfg, after_utc=after)
    assert next_dt is not None
    assert next_dt.astimezone(BJ) == datetime(2026, 11, 24, 9, 30, tzinfo=BJ)

    # Downtime from Nov 20 09:30 to Nov 24 10:00 Beijing time -> Nov 20,21,22,23,24 = 5 slots:
    # catch up latest (Nov 24 09:30), 4 earlier missed!
    first_due = datetime(2026, 11, 20, 9, 30, tzinfo=BJ).astimezone(UTC)
    now = datetime(2026, 11, 24, 10, 0, tzinfo=BJ).astimezone(UTC)
    latest, missed_before, nxt = resolve_due_schedule_slot("daily", cfg, first_due, now)
    assert latest.astimezone(BJ) == datetime(2026, 11, 24, 9, 30, tzinfo=BJ)
    assert missed_before == 4
    assert nxt is not None
    assert nxt.astimezone(BJ) == datetime(2026, 11, 25, 9, 30, tzinfo=BJ)

    # Weekly Monday & Wednesday 08:00 BJ (2026-11-16 is Monday, 2026-11-23 is next Monday)
    wcfg = validate_trigger_config(
        "weekly", {"weekdays": [3, 1, 1], "hour": 8, "minute": 0}
    )
    assert wcfg["weekdays"] == [1, 3]
    mon16 = datetime(2026, 11, 16, 8, 0, tzinfo=BJ).astimezone(UTC)
    tue24 = datetime(2026, 11, 24, 12, 0, tzinfo=BJ).astimezone(UTC)
    wlatest, wmissed, wnxt = resolve_due_schedule_slot("weekly", wcfg, mon16, tue24)
    # Missed: Mon16, Wed18 -> latest caught up Mon23; 2 missed earlier (Mon16, Wed18)
    assert wlatest.astimezone(BJ) == datetime(2026, 11, 23, 8, 0, tzinfo=BJ)
    assert wmissed == 2
    assert wnxt is not None
    assert wnxt.astimezone(BJ) == datetime(2026, 11, 25, 8, 0, tzinfo=BJ)

    # Once becomes None next
    ocfg = validate_trigger_config("once", {"run_at": "2026-11-25T14:00:00"})
    odue = datetime(2026, 11, 25, 14, 0, tzinfo=BJ).astimezone(UTC)
    olatest, omissed, onxt = resolve_due_schedule_slot(
        "once", ocfg, odue, datetime(2026, 11, 25, 15, 0, tzinfo=BJ).astimezone(UTC)
    )
    assert olatest == odue
    assert omissed == 0
    assert onxt is None


def test_webhook_hmac_and_input_mapping() -> None:
    secret = "whsec_unit_test_secret_123456"
    body = b'{"event":"alert","data":{"message":"Disk 95%","model_id":"evil"}}'
    now = datetime(2026, 11, 24, 12, 0, 0, tzinfo=UTC)
    ts = str(int(now.timestamp()))
    sig = sign_webhook_payload(secret, ts, body, "evt-100")

    ev, parsed_ts = verify_webhook_signature(
        secret=secret,
        timestamp_header=ts,
        signature_header=sig,
        event_id_header="evt-100",
        raw_body=body,
        now_utc=now,
    )
    assert ev == "evt-100"
    assert parsed_ts == int(ts)

    # Tampered signature fails
    try:
        verify_webhook_signature(
            secret=secret,
            timestamp_header=ts,
            signature_header="sha256=" + ("0" * 64),
            event_id_header="evt-100",
            raw_body=body,
            now_utc=now,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Expected tampered signature failure")

    # Expired timestamp fails
    try:
        verify_webhook_signature(
            secret=secret,
            timestamp_header=str(int(now.timestamp()) - 1000),
            signature_header=sign_webhook_payload(
                secret, str(int(now.timestamp()) - 1000), body, "evt-100"
            ),
            event_id_header="evt-100",
            raw_body=body,
            now_utc=now,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Expected stale timestamp failure")

    # Canonical payload hash detects differences even if whitespace differs
    h1 = canonical_payload_hash({"b": 2, "a": 1})
    h2 = canonical_payload_hash({"a": 1, "b": 2})
    h3 = canonical_payload_hash({"a": 1, "b": 3})
    assert h1 == h2 and h1 != h3

    # Input mapping isolates webhook data into inputs only
    icfg = validate_input_config(
        {
            "mode": "text",
            "text": "Handle incident",
            "webhook_input_path": "data.message",
            "webhook_prompt_template": "Alert: {{data.message}}",
        }
    )
    snap = build_execution_input_snapshot(
        icfg,
        webhook_payload={"event": "alert", "data": {"message": "Disk 95%"}},
    )
    assert snap["goal"] == "Alert: Disk 95%"


def test_webhook_identity_and_input_boundaries() -> None:
    secret, event_id = "test-secret", "delivery-1"
    now = datetime(2026, 11, 24, 0, 0, tzinfo=UTC)
    timestamp, body = str(int(now.timestamp())), b'{"value": false}'
    signature = sign_webhook_payload(secret, timestamp, body, event_id)
    for invalid_id in ("another-delivery", "\u4e2d\u6587", "bad\x00id"):
        try:
            verify_webhook_signature(
                secret=secret,
                timestamp_header=timestamp,
                signature_header=signature,
                event_id_header=invalid_id,
                raw_body=body,
                now_utc=now,
            )
        except ValueError:
            pass
        else:
            raise AssertionError(
                "Captured requests must not be replayable under another event ID"
            )
    snapshot = build_execution_input_snapshot(
        {"mode": "text", "webhook_input_path": "value"},
        webhook_payload={"value": False},
    )
    assert snapshot["goal"] == "false"
    for config, payload in [
        ({"mode": "text", "webhook_prompt_template": "{{missing}}"}, {}),
        ({"mode": "text", "webhook_input_path": "value"}, {"value": "x" * 4001}),
        ({"mode": "json", "json_payload": {"value": float("nan")}}, None),
    ]:
        try:
            build_execution_input_snapshot(config, webhook_payload=payload)
        except ValueError:
            pass
        else:
            raise AssertionError(
                "Invalid or oversized mapped input must fail explicitly"
            )


def test_sunday_uses_iso_weekday_seven() -> None:
    cfg = validate_trigger_config("weekly", {"weekdays": [7], "hour": 9, "minute": 0})
    monday = datetime(2026, 11, 23, 0, 0, tzinfo=BJ)
    assert compute_next_schedule_at("weekly", cfg, after_utc=monday).astimezone(
        BJ
    ) == datetime(2026, 11, 29, 9, tzinfo=BJ)


def main() -> None:
    test_beijing_schedules_and_catchup()
    test_webhook_hmac_and_input_mapping()
    test_webhook_identity_and_input_boundaries()
    test_sunday_uses_iso_weekday_seven()
    print("AUTOMATIONS_UNIT_OK")


if __name__ == "__main__":
    main()
