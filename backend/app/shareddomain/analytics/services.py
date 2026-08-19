import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.analytics import WorkspaceAnalyticsRun, WorkspaceAnalyticsTeamMember
from app.entities.user import User
from app.entities.workspace import Workspace
from app.infrastructure.model_utils import utc_now
from app.infrastructure.repositories import analytics as analytics_repository
from app.schemas.analytics import (
    AnalyticsCountComparison,
    AnalyticsRatioComparison,
    WorkspaceAnalyticsAnonymousUsage,
    WorkspaceAnalyticsApplicationRankingItem,
    WorkspaceAnalyticsDistributions,
    WorkspaceAnalyticsDistributionItem,
    WorkspaceAnalyticsFrequentQuestion,
    WorkspaceAnalyticsHourlyPoint,
    WorkspaceAnalyticsMemberSummary,
    WorkspaceAnalyticsMetadata,
    WorkspaceAnalyticsRankings,
    WorkspaceAnalyticsResponse,
    WorkspaceAnalyticsSummary,
    WorkspaceAnalyticsTeamRankingItem,
    WorkspaceAnalyticsTokenSummary,
    WorkspaceAnalyticsTrendPoint,
    WorkspaceAnalyticsUserRankingItem,
)
from app.shareddomain.agents.models import agent_run_display_status
from app.shareddomain.audit.services import record_audit_log

ANALYTICS_TIMEZONE = "UTC"
DEFAULT_ANALYTICS_DAYS = 30
MAX_ANALYTICS_DAYS = 366
FREQUENT_QUESTION_MIN_COUNT = 3
FREQUENT_QUESTION_LIMIT = 20
FREQUENT_QUESTION_MAX_LENGTH = 200
TERMINAL_RUN_STATUSES = {"succeeded", "failed", "cancelled"}


@dataclass(frozen=True)
class AnalyticsPeriod:
    from_date: date
    to_date: date
    previous_from_date: date
    previous_to_date: date

    @property
    def start_at(self) -> datetime:
        return datetime.combine(self.from_date, time.min, tzinfo=UTC)

    @property
    def end_at(self) -> datetime:
        return datetime.combine(self.to_date, time.min, tzinfo=UTC)

    @property
    def previous_start_at(self) -> datetime:
        return datetime.combine(self.previous_from_date, time.min, tzinfo=UTC)


@dataclass(frozen=True)
class _PeriodSummary:
    active_users: int
    runs: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    unreported_runs: int
    success_rate: float | None
    average_duration_ms: float | None


def resolve_analytics_period(
    from_date: date | None,
    to_date: date | None,
    *,
    today: date | None = None,
) -> AnalyticsPeriod:
    if (from_date is None) != (to_date is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Analytics from and to dates must be provided together.",
        )
    if from_date is None or to_date is None:
        current_to = (today or utc_now().date()) + timedelta(days=1)
        current_from = current_to - timedelta(days=DEFAULT_ANALYTICS_DAYS)
    else:
        current_from = from_date
        current_to = to_date

    days = (current_to - current_from).days
    if days <= 0:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Analytics to date must be later than from date.",
        )
    if days > MAX_ANALYTICS_DAYS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Analytics date range cannot exceed {MAX_ANALYTICS_DAYS} days.",
        )
    return AnalyticsPeriod(
        from_date=current_from,
        to_date=current_to,
        previous_from_date=current_from - timedelta(days=days),
        previous_to_date=current_from,
    )


def normalize_frequent_question(value: str) -> tuple[str, str]:
    representative = re.sub(r"\s+", " ", value).strip()
    return representative.casefold(), representative


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _number(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float) and value.is_integer():
        return max(0, int(value))
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return 0


def _run_usage(run: WorkspaceAnalyticsRun) -> tuple[int, int, int, bool]:
    input_tokens = _number(run.model_usage.get("input_tokens"))
    output_tokens = _number(run.model_usage.get("output_tokens"))
    total_tokens = (
        max(0, run.workflow_token_usage)
        if run.workflow_token_usage is not None
        else _number(run.model_usage.get("total_tokens"))
    )
    model_calls = _number(run.model_usage.get("model_calls"))
    reported_model_calls = _number(run.model_usage.get("reported_model_calls"))
    return (
        input_tokens,
        output_tokens,
        total_tokens,
        model_calls > reported_model_calls,
    )


def _summarize_period(runs: list[WorkspaceAnalyticsRun]) -> _PeriodSummary:
    active_user_ids: set[str] = set()
    input_tokens = output_tokens = total_tokens = unreported_runs = 0
    succeeded = terminal = 0
    durations: list[float] = []
    for run in runs:
        if run.access_source == "console" and run.requested_by_user_id:
            active_user_ids.add(run.requested_by_user_id)
        run_input, run_output, run_total, unreported = _run_usage(run)
        input_tokens += run_input
        output_tokens += run_output
        total_tokens += run_total
        unreported_runs += int(unreported)
        display_status = agent_run_display_status(run.status)
        if display_status in TERMINAL_RUN_STATUSES:
            terminal += 1
            succeeded += int(display_status == "succeeded")
            if run.started_at is not None and run.finished_at is not None:
                duration = (_utc(run.finished_at) - _utc(run.started_at)).total_seconds()
                if duration >= 0:
                    durations.append(duration * 1000)
    return _PeriodSummary(
        active_users=len(active_user_ids),
        runs=len(runs),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        unreported_runs=unreported_runs,
        success_rate=succeeded / terminal if terminal else None,
        average_duration_ms=(sum(durations) / len(durations)) if durations else None,
    )


def _change_percent(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    if previous == 0:
        return 0.0 if current == 0 else None
    return round((current - previous) / previous * 100, 1)


def _count_comparison(current: int, previous: int) -> AnalyticsCountComparison:
    return AnalyticsCountComparison(
        value=current,
        previous_value=previous,
        change_percent=_change_percent(current, previous),
    )


def _ratio_comparison(
    current: float | None,
    previous: float | None,
) -> AnalyticsRatioComparison:
    return AnalyticsRatioComparison(
        value=round(current, 4) if current is not None else None,
        previous_value=round(previous, 4) if previous is not None else None,
        change_percent=_change_percent(current, previous),
    )


def _distribution(counter: Counter[str]) -> list[WorkspaceAnalyticsDistributionItem]:
    return [
        WorkspaceAnalyticsDistributionItem(key=key, count=count)
        for key, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]


def _build_trends(
    runs: list[WorkspaceAnalyticsRun],
    period: AnalyticsPeriod,
) -> list[WorkspaceAnalyticsTrendPoint]:
    days = (period.to_date - period.from_date).days
    values = {
        period.from_date + timedelta(days=index): {
            "runs": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }
        for index in range(days)
    }
    for run in runs:
        if run.created_at is None:
            continue
        day = _utc(run.created_at).date()
        if day not in values:
            continue
        run_input, run_output, run_total, _ = _run_usage(run)
        values[day]["runs"] += 1
        values[day]["input_tokens"] += run_input
        values[day]["output_tokens"] += run_output
        values[day]["total_tokens"] += run_total
    return [
        WorkspaceAnalyticsTrendPoint(date=day, **day_values)
        for day, day_values in values.items()
    ]


def _build_hourly_runs(
    runs: list[WorkspaceAnalyticsRun],
) -> list[WorkspaceAnalyticsHourlyPoint]:
    values = [0] * 24
    for run in runs:
        if run.created_at is not None:
            values[_utc(run.created_at).hour] += 1
    return [
        WorkspaceAnalyticsHourlyPoint(hour=hour, runs=count)
        for hour, count in enumerate(values)
    ]


def _build_rankings(
    runs: list[WorkspaceAnalyticsRun],
    team_members: list[WorkspaceAnalyticsTeamMember],
) -> WorkspaceAnalyticsRankings:
    users: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"name": "", "run_count": 0, "total_tokens": 0}
    )
    applications: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "name": "",
            "app_type": "agent",
            "run_count": 0,
            "total_tokens": 0,
            "terminal_count": 0,
            "succeeded_count": 0,
        }
    )
    teams_by_user: dict[str, list[WorkspaceAnalyticsTeamMember]] = defaultdict(list)
    for membership in team_members:
        teams_by_user[membership.user_id].append(membership)
    team_usage: dict[str, dict[str, Any]] = {}
    anonymous_runs = anonymous_tokens = 0
    for run in runs:
        _, _, total_tokens, _ = _run_usage(run)
        if run.access_source == "console" and run.requested_by_user_id:
            user = users[run.requested_by_user_id]
            user["name"] = (
                run.requester_name
                or run.requester_username
                or run.requested_by_user_id
            )
            user["run_count"] += 1
            user["total_tokens"] += total_tokens
        elif run.access_source in {"public", "api"}:
            anonymous_runs += 1
            anonymous_tokens += total_tokens

        if (
            run.access_source == "console"
            and run.requested_by_user_id
            and run.created_at is not None
        ):
            day = _utc(run.created_at).date()
            for membership in teams_by_user.get(run.requested_by_user_id, []):
                team = team_usage.setdefault(
                    membership.team_id,
                    {
                        "name": membership.team_name,
                        "run_count": 0,
                        "daily_runs": Counter(),
                    },
                )
                team["run_count"] += 1
                team["daily_runs"][day] += 1

        application = applications[run.agent_id]
        application["name"] = run.application_name
        application["app_type"] = run.app_type
        application["run_count"] += 1
        application["total_tokens"] += total_tokens
        display_status = agent_run_display_status(run.status)
        if display_status in TERMINAL_RUN_STATUSES:
            application["terminal_count"] += 1
            application["succeeded_count"] += int(display_status == "succeeded")

    user_items = sorted(
        (
            WorkspaceAnalyticsUserRankingItem(
                user_id=user_id,
                name=values["name"],
                run_count=values["run_count"],
                total_tokens=values["total_tokens"],
            )
            for user_id, values in users.items()
        ),
        key=lambda item: (-item.total_tokens, -item.run_count, item.name.casefold()),
    )[:10]
    application_items = sorted(
        (
            WorkspaceAnalyticsApplicationRankingItem(
                application_id=application_id,
                name=values["name"],
                app_type=values["app_type"],
                run_count=values["run_count"],
                total_tokens=values["total_tokens"],
                success_rate=(
                    values["succeeded_count"] / values["terminal_count"]
                    if values["terminal_count"]
                    else None
                ),
            )
            for application_id, values in applications.items()
        ),
        key=lambda item: (-item.total_tokens, -item.run_count, item.name.casefold()),
    )[:10]
    team_items = sorted(
        (
            WorkspaceAnalyticsTeamRankingItem(
                team_id=team_id,
                name=values["name"],
                peak_daily_runs=max(values["daily_runs"].values()),
                run_count=values["run_count"],
            )
            for team_id, values in team_usage.items()
        ),
        key=lambda item: (-item.peak_daily_runs, -item.run_count, item.name.casefold()),
    )[:10]
    return WorkspaceAnalyticsRankings(
        users=user_items,
        applications=application_items,
        anonymous=WorkspaceAnalyticsAnonymousUsage(
            run_count=anonymous_runs,
            total_tokens=anonymous_tokens,
        ),
        teams=team_items,
    )


def _build_frequent_questions(
    runs: list[WorkspaceAnalyticsRun],
) -> list[WorkspaceAnalyticsFrequentQuestion]:
    grouped: dict[str, dict[str, Any]] = {}
    for run in runs:
        normalized, representative = normalize_frequent_question(run.goal)
        if not normalized or run.created_at is None:
            continue
        created_at = _utc(run.created_at)
        values = grouped.setdefault(
            normalized,
            {"question": representative, "count": 0, "latest_at": created_at},
        )
        values["count"] += 1
        if created_at >= values["latest_at"]:
            values["question"] = representative
            values["latest_at"] = created_at
    items = [
        WorkspaceAnalyticsFrequentQuestion(
            question=(
                values["question"]
                if len(values["question"]) <= FREQUENT_QUESTION_MAX_LENGTH
                else f"{values['question'][: FREQUENT_QUESTION_MAX_LENGTH - 1]}…"
            ),
            count=values["count"],
            latest_at=values["latest_at"],
        )
        for values in grouped.values()
        if values["count"] >= FREQUENT_QUESTION_MIN_COUNT
    ]
    return sorted(
        items,
        key=lambda item: (-item.count, -item.latest_at.timestamp(), item.question.casefold()),
    )[:FREQUENT_QUESTION_LIMIT]


async def get_workspace_analytics(
    db: AsyncSession,
    workspace: Workspace,
    actor: User,
    from_date: date | None,
    to_date: date | None,
) -> WorkspaceAnalyticsResponse:
    period = resolve_analytics_period(from_date, to_date)
    counts = await analytics_repository.get_workspace_analytics_counts(db, workspace.id)
    team_members = await analytics_repository.list_workspace_analytics_team_members(
        db,
        workspace.id,
    )
    all_runs = await analytics_repository.list_workspace_analytics_runs(
        db,
        workspace.id,
        period.previous_start_at,
        period.end_at,
    )
    current_runs = [
        run
        for run in all_runs
        if run.created_at is not None and _utc(run.created_at) >= period.start_at
    ]
    previous_runs = [
        run
        for run in all_runs
        if run.created_at is not None and _utc(run.created_at) < period.start_at
    ]
    current = _summarize_period(current_runs)
    previous = _summarize_period(previous_runs)

    response = WorkspaceAnalyticsResponse(
        summary=WorkspaceAnalyticsSummary(
            members=WorkspaceAnalyticsMemberSummary(
                total=counts.members_total,
                active=counts.members_active,
            ),
            active_teams=counts.active_teams,
            active_users=_count_comparison(
                current.active_users,
                previous.active_users,
            ),
            runs=_count_comparison(current.runs, previous.runs),
            tokens=WorkspaceAnalyticsTokenSummary(
                input=current.input_tokens,
                output=current.output_tokens,
                total=current.total_tokens,
                unreported_runs=current.unreported_runs,
                previous_total=previous.total_tokens,
                change_percent=_change_percent(
                    current.total_tokens,
                    previous.total_tokens,
                ),
            ),
            success_rate=_ratio_comparison(
                current.success_rate,
                previous.success_rate,
            ),
            average_duration_ms=_ratio_comparison(
                current.average_duration_ms,
                previous.average_duration_ms,
            ),
        ),
        trends=_build_trends(current_runs, period),
        hourly_runs=_build_hourly_runs(current_runs),
        distributions=WorkspaceAnalyticsDistributions(
            run_types=_distribution(Counter(run.app_type for run in current_runs)),
            access_sources=_distribution(
                Counter(run.access_source for run in current_runs)
            ),
            statuses=_distribution(
                Counter(agent_run_display_status(run.status) for run in current_runs)
            ),
        ),
        rankings=_build_rankings(current_runs, team_members),
        frequent_questions=_build_frequent_questions(current_runs),
        metadata=WorkspaceAnalyticsMetadata(
            workspace_id=workspace.id,
            timezone=ANALYTICS_TIMEZONE,
            from_date=period.from_date,
            to_date=period.to_date,
            previous_from_date=period.previous_from_date,
            previous_to_date=period.previous_to_date,
            end_exclusive=True,
            generated_at=utc_now(),
        ),
    )
    record_audit_log(
        db,
        actor,
        "workspace.analytics.view",
        "workspace_analytics",
        workspace.id,
        workspace.name,
        {
            "from_date": period.from_date.isoformat(),
            "to_date": period.to_date.isoformat(),
            "timezone": ANALYTICS_TIMEZONE,
            "interval_days": (period.to_date - period.from_date).days,
        },
        workspace_id=workspace.id,
    )
    await db.commit()
    return response


__all__ = [
    "get_workspace_analytics",
    "normalize_frequent_question",
    "resolve_analytics_period",
]
