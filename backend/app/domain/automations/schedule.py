"""Asia/Shanghai schedule calculation and bounded downtime catch-up rules."""

from datetime import UTC, datetime, time, timedelta
from typing import Any

from app.entities.defaults import APP_TIMEZONE, APP_TIMEZONE_NAME

DEFAULT_TIMEZONE_NAME = APP_TIMEZONE_NAME


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _parse_once_run_at(raw_value: object) -> datetime:
    if isinstance(raw_value, datetime):
        parsed = raw_value
    elif isinstance(raw_value, str) and raw_value.strip():
        text = raw_value.strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)
    else:
        raise ValueError("One-time schedule requires a valid ISO datetime 'run_at'.")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=APP_TIMEZONE)
    return parsed.astimezone(UTC).replace(microsecond=0)


def _validate_int_field(
    value: object, *, minimum: int, maximum: int, field: str
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Schedule field '{field}' must be an integer.")
    if value < minimum or value > maximum:
        raise ValueError(
            f"Schedule field '{field}' must be between {minimum} and {maximum}."
        )
    return value


def validate_trigger_config(
    trigger_type: str, raw_config: dict[str, Any]
) -> dict[str, Any]:
    """Validate and normalize schedule or webhook trigger settings."""
    config = dict(raw_config or {})
    if trigger_type == "once":
        run_at = _parse_once_run_at(config.get("run_at"))
        return {
            "run_at": run_at.astimezone(APP_TIMEZONE).isoformat(),
            "timezone": DEFAULT_TIMEZONE_NAME,
        }
    if trigger_type == "daily":
        hour = _validate_int_field(
            config.get("hour"), minimum=0, maximum=23, field="hour"
        )
        minute = _validate_int_field(
            config.get("minute"), minimum=0, maximum=59, field="minute"
        )
        return {
            "hour": hour,
            "minute": minute,
            "timezone": DEFAULT_TIMEZONE_NAME,
        }
    if trigger_type == "weekly":
        hour = _validate_int_field(
            config.get("hour"), minimum=0, maximum=23, field="hour"
        )
        minute = _validate_int_field(
            config.get("minute"), minimum=0, maximum=59, field="minute"
        )
        raw_weekdays = config.get("weekdays")
        if not isinstance(raw_weekdays, list) or not raw_weekdays:
            raise ValueError(
                "Weekly schedule requires a non-empty list of weekdays (1-7)."
            )
        weekdays = sorted(
            {
                _validate_int_field(day, minimum=1, maximum=7, field="weekdays")
                for day in raw_weekdays
            }
        )
        return {
            "weekdays": weekdays,
            "hour": hour,
            "minute": minute,
            "timezone": DEFAULT_TIMEZONE_NAME,
        }
    if trigger_type == "webhook":
        raw_max_pending = config.get("max_pending", 20)
        max_pending = _validate_int_field(
            raw_max_pending,
            minimum=1,
            maximum=100,
            field="max_pending",
        )
        return {"max_pending": max_pending}
    raise ValueError(f"Unsupported trigger_type: {trigger_type}")


def compute_next_schedule_at(
    trigger_type: str,
    trigger_config: dict[str, Any],
    *,
    after_utc: datetime,
    inclusive: bool = False,
) -> datetime | None:
    """Compute the next UTC instant matching the Beijing-time schedule after ``after_utc``."""
    anchor_utc = _as_utc(after_utc)
    if trigger_type == "webhook":
        return None
    if trigger_type == "once":
        target_utc = _parse_once_run_at(trigger_config.get("run_at"))
        if inclusive and target_utc >= anchor_utc:
            return target_utc
        if not inclusive and target_utc > anchor_utc:
            return target_utc
        return None

    anchor_bj = anchor_utc.astimezone(APP_TIMEZONE)
    hour = int(trigger_config["hour"])
    minute = int(trigger_config["minute"])
    target_clock = time(hour=hour, minute=minute)

    if trigger_type == "daily":
        candidate_bj = datetime.combine(
            anchor_bj.date(), target_clock, tzinfo=APP_TIMEZONE
        )
        if candidate_bj < anchor_bj or (not inclusive and candidate_bj == anchor_bj):
            candidate_bj += timedelta(days=1)
        return candidate_bj.astimezone(UTC)

    if trigger_type == "weekly":
        weekdays = {int(day) for day in trigger_config.get("weekdays", [])}
        if not weekdays:
            raise ValueError("Weekly schedule has no weekdays configured.")
        for offset in range(0, 8):
            candidate_date = anchor_bj.date() + timedelta(days=offset)
            if candidate_date.isoweekday() not in weekdays:
                continue
            candidate_bj = datetime.combine(
                candidate_date, target_clock, tzinfo=APP_TIMEZONE
            )
            if candidate_bj > anchor_bj or (inclusive and candidate_bj == anchor_bj):
                return candidate_bj.astimezone(UTC)
        return None

    raise ValueError(f"Unsupported trigger_type: {trigger_type}")


def resolve_due_schedule_slot(
    trigger_type: str,
    trigger_config: dict[str, Any],
    scheduled_at_utc: datetime,
    now_utc: datetime,
) -> tuple[datetime, int, datetime | None]:
    """Resolve due catch-up slot in O(1) without accumulating downtime backlogs.

    Returns ``(latest_due_slot_utc, missed_count_before, next_run_at_utc)``:
    when multiple occurrences slipped while workers were down, only the most
    recent occurrence (<= ``now_utc``) runs; earlier skipped occurrences are
    counted in ``missed_count_before``.
    """
    start_utc = _as_utc(scheduled_at_utc)
    now_norm = _as_utc(now_utc)
    if now_norm < start_utc:
        raise ValueError("Schedule slot is not yet due.")

    if trigger_type == "once":
        return (start_utc, 0, None)

    start_bj = start_utc.astimezone(APP_TIMEZONE)
    now_bj = now_norm.astimezone(APP_TIMEZONE)
    hour = int(trigger_config["hour"])
    minute = int(trigger_config["minute"])
    target_clock = time(hour=hour, minute=minute)

    if trigger_type == "daily":
        today_slot_bj = datetime.combine(
            now_bj.date(), target_clock, tzinfo=APP_TIMEZONE
        )
        if today_slot_bj > now_bj:
            latest_bj = today_slot_bj - timedelta(days=1)
        else:
            latest_bj = today_slot_bj
        if latest_bj < start_bj:
            latest_bj = start_bj
        missed_before = max(0, (latest_bj.date() - start_bj.date()).days)
        next_bj = latest_bj + timedelta(days=1)
        return (latest_bj.astimezone(UTC), missed_before, next_bj.astimezone(UTC))

    if trigger_type == "weekly":
        weekdays = sorted({int(day) for day in trigger_config.get("weekdays", [])})
        if not weekdays:
            raise ValueError("Weekly schedule has no weekdays configured.")
        today_slot_bj = datetime.combine(
            now_bj.date(), target_clock, tzinfo=APP_TIMEZONE
        )
        latest_date = (
            now_bj.date()
            if today_slot_bj <= now_bj
            else (now_bj.date() - timedelta(days=1))
        )
        latest_bj = None
        for back in range(0, 7):
            candidate_date = latest_date - timedelta(days=back)
            if candidate_date.isoweekday() in weekdays:
                latest_bj = datetime.combine(
                    candidate_date, target_clock, tzinfo=APP_TIMEZONE
                )
                break
        if latest_bj is None or latest_bj < start_bj:
            latest_bj = start_bj
        total_days = (latest_bj.date() - start_bj.date()).days
        full_weeks, extra_days = divmod(total_days, 7)
        occurrences_before = full_weeks * len(weekdays)
        for day_offset in range(0, extra_days):
            check_date = start_bj.date() + timedelta(days=full_weeks * 7 + day_offset)
            if check_date.isoweekday() in weekdays:
                occurrences_before += 1
        next_utc = compute_next_schedule_at(
            trigger_type,
            trigger_config,
            after_utc=latest_bj.astimezone(UTC),
            inclusive=False,
        )
        return (latest_bj.astimezone(UTC), max(0, occurrences_before), next_utc)

    raise ValueError(f"Unsupported trigger_type: {trigger_type}")
