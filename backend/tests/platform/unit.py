"""Pure unit tests for the platform feature (moved from the former tests/unit.py).

No database, no HTTP client, no network: repositories and capability ports
are mocked or monkeypatched so each unit is tested in isolation. Run from
``backend/`` with:

    uv run python -m tests.platform.unit
"""
import tests.support  # noqa: F401  (sets required env before app imports)

"""Pure unit tests for business services.

No database, no HTTP client, no network: repositories and capability ports
are mocked or monkeypatched so each unit is tested in isolation. Run from
``backend/`` with:

    uv run python -m tests.unit
"""

import asyncio
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.application.resource_folders.service import (
    descendant_folder_ids,
    move_resource,
)
from app.domain.analytics.services import (
    MEMBER_TREND_LIMIT,
    AnalyticsPeriod,
    _build_member_trends,
)
from app.entities.analytics import WorkspaceAnalyticsRun
from app.entities.resource_folders.models import ResourceFolder
from app.schemas.resource_folders.contracts import ResourceFolderMoveRequest


def expect_http_error(callback, status_code: int) -> None:
    try:
        callback()
    except HTTPException as exc:
        assert exc.status_code == status_code, exc.status_code
        return
    raise AssertionError("expected HTTPException")

def payload_with(**fields):
    return SimpleNamespace(model_dump=lambda: fields)

def test_resource_folder_descendants_cover_nested_children() -> None:
    folders = [
        ResourceFolder(id="parent", parent_id=None),
        ResourceFolder(id="child", parent_id="parent"),
        ResourceFolder(id="grandchild", parent_id="child"),
        ResourceFolder(id="sibling", parent_id=None),
    ]
    assert descendant_folder_ids(folders, "parent") == {
        "parent",
        "child",
        "grandchild",
    }


def test_resource_folder_rejects_moving_builtin_tools() -> None:
    db = SimpleNamespace(commit=AsyncMock())
    set_resources_folder = AsyncMock()

    async def move_builtin_tool() -> HTTPException:
        with (
            patch(
                "app.application.resource_folders.service.require_managed_tool",
                new=AsyncMock(return_value=SimpleNamespace(kind="builtin")),
            ),
            patch(
                "app.application.resource_folders.service.repository.set_resources_folder",
                new=set_resources_folder,
            ),
        ):
            try:
                await move_resource(
                    db,
                    "workspace-1",
                    ResourceFolderMoveRequest(
                        resource_type="tool",
                        resource_id="builtin-tool-1",
                        folder_id=None,
                    ),
                    SimpleNamespace(id="admin-1", is_global_admin=False),
                    "admin",
                )
            except HTTPException as exc:
                return exc
        raise AssertionError("expected HTTPException")

    error = asyncio.run(move_builtin_tool())

    assert error.status_code == 422
    assert error.detail == "Built-in tools cannot be moved."
    set_resources_folder.assert_not_awaited()
    db.commit.assert_not_awaited()


def test_team_to_response() -> None:
    from app.domain.teams.services import team_to_response
    from app.entities.teams.models import Team

    team = Team(
        id="team-1",
        workspace_id="ws-1",
        name="Research",
        description="desc",
        status="active",
        is_default=True,
    )
    response = team_to_response(team)
    assert response.name == "Research"
    assert response.status == "active"
    assert response.is_default is True

def test_workspace_daily_quota_uses_shanghai_day_boundary() -> None:
    from datetime import UTC, datetime

    from app.application.governance.service import enforce_workspace_run_quota

    db = object()
    count_runs = AsyncMock(return_value=0)
    with (
        patch(
            "app.application.governance.service.utc_now",
            return_value=datetime(2026, 9, 5, 16, 30, tzinfo=UTC),
        ),
        patch(
            "app.application.governance.service.workspace_governance_repository.get",
            new=AsyncMock(return_value=SimpleNamespace(daily_run_limit=10)),
        ),
        patch(
            "app.application.governance.service.governance_repository.daily_run_count",
            new=count_runs,
        ),
    ):
        asyncio.run(enforce_workspace_run_quota(db, "workspace-1"))

    count_runs.assert_awaited_once_with(
        db,
        "workspace-1",
        datetime(2026, 9, 5, 16, tzinfo=UTC),
    )


def test_message_stream_releases_reader_at_lifetime_limit() -> None:
    from app.application.announcements.live import stream_message_updates

    reader = SimpleNamespace(available=True, read=AsyncMock(), close=AsyncMock())

    async def wait_for_event(**_kwargs):
        await asyncio.sleep(0.05)
        return []

    reader.read.side_effect = wait_for_event

    async def consume() -> list:
        with patch(
            "app.application.announcements.live.build_announcement_live_stream_reader",
            return_value=reader,
        ):
            return [
                update
                async for update in stream_message_updates(
                    object(),
                    workspace_id=None,
                    global_after=None,
                    workspace_after=None,
                    max_lifetime_seconds=0.01,
                )
            ]

    assert asyncio.run(consume()) == []
    reader.close.assert_awaited_once()


def test_workspace_analytics_member_trends() -> None:
    period = AnalyticsPeriod(
        from_date=date(2026, 8, 1),
        to_date=date(2026, 8, 4),
        previous_from_date=date(2026, 7, 29),
        previous_to_date=date(2026, 8, 1),
    )

    def make_run(
        run_id: str,
        user_id: str | None,
        name: str | None,
        created_at: datetime,
        *,
        access_source: str = "console",
        total_tokens: int = 10,
        workflow_token_usage: int | None = None,
    ) -> WorkspaceAnalyticsRun:
        return WorkspaceAnalyticsRun(
            id=run_id,
            agent_id="agent-1",
            application_name="Agent 1",
            app_type="workflow" if workflow_token_usage is not None else "agent",
            requested_by_user_id=user_id,
            requester_username=user_id,
            requester_name=name,
            access_source=access_source,
            status="succeeded",
            goal="test",
            model_usage={"total_tokens": total_tokens},
            workflow_token_usage=workflow_token_usage,
            started_at=created_at,
            finished_at=created_at,
            created_at=created_at,
        )

    # 2026-07-31T16:30:00Z is 2026-08-01 00:30+08:00 in Asia/Shanghai.
    runs = [
        make_run(
            "r-shanghai",
            "u-1",
            "Alice",
            datetime(2026, 7, 31, 16, 30, tzinfo=UTC),
            total_tokens=100,
        ),
        make_run(
            "r-workflow",
            "u-1",
            "Alice",
            datetime(2026, 8, 2, 10, 0, tzinfo=UTC),
            total_tokens=999,
            workflow_token_usage=250,
        ),
        # Excluded: public/api and missing requested_by_user_id
        make_run(
            "r-public",
            "u-public",
            "PublicUser",
            datetime(2026, 8, 2, 10, 0, tzinfo=UTC),
            access_source="public",
            total_tokens=500,
        ),
        make_run(
            "r-api",
            "u-api",
            "ApiUser",
            datetime(2026, 8, 2, 10, 0, tzinfo=UTC),
            access_source="api",
            total_tokens=500,
        ),
        make_run(
            "r-anon",
            None,
            None,
            datetime(2026, 8, 2, 10, 0, tzinfo=UTC),
            access_source="console",
            total_tokens=500,
        ),
    ]
    # Add 21 more users with 1 run each to verify MEMBER_TREND_LIMIT truncation and tie-breaking.
    for index in range(21):
        runs.append(
            make_run(
                f"r-extra-{index}",
                f"u-extra-{index:02d}",
                f"User {index:02d}",
                datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
                access_source="automation" if index % 2 == 0 else "console",
                total_tokens=100 - index,
            )
        )

    series = _build_member_trends(runs, period)
    assert len(series) == MEMBER_TREND_LIMIT
    assert series[0].user_id == "u-1"
    assert series[0].name == "Alice"
    assert series[0].total_runs == 2
    assert series[0].total_tokens == 350
    assert [(p.date, p.runs, p.total_tokens) for p in series[0].daily] == [
        (date(2026, 8, 1), 1, 100),
        (date(2026, 8, 2), 1, 250),
        (date(2026, 8, 3), 0, 0),
    ]
    assert series[1].user_id == "u-extra-00"
    assert series[-1].user_id == "u-extra-18"
    assert all(item.user_id not in {"u-public", "u-api"} for item in series)


def test_audit_retention_policy_and_cleanup() -> None:
    from app.domain.audit.services import (
        cleanup_expired_audit_logs,
        get_audit_retention_policy,
        update_audit_retention_policy,
    )
    from app.entities.audit import AuditRetentionSettings

    fixed_now = datetime(2026, 11, 26, 8, 0, tzinfo=UTC)
    actor = SimpleNamespace(id="admin-1", username="admin", name="Admin")

    async def exercise() -> None:
        db = SimpleNamespace(commit=AsyncMock())

        with patch(
            "app.domain.audit.services.audit_repository.get_retention_settings",
            new=AsyncMock(return_value=None),
        ):
            default_policy = await get_audit_retention_policy(db)
            assert default_policy.retention_days is None
            assert default_policy.updated_at is None

        saved_row = AuditRetentionSettings(
            retention_days=90,
            updated_by_user_id="admin-1",
            created_at=fixed_now,
            updated_at=fixed_now,
        )
        add_mock = AsyncMock()
        with (
            patch(
                "app.domain.audit.services.audit_repository.get_retention_settings",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.domain.audit.services.audit_repository.save_retention_settings",
                new=AsyncMock(return_value=saved_row),
            ) as save_mock,
            patch(
                "app.domain.audit.services.audit_repository.add",
                new=lambda session, entity: add_mock.call_args_list.append((session, entity)),
            ),
        ):
            updated = await update_audit_retention_policy(db, actor, 90)
            assert updated.retention_days == 90
            save_mock.assert_awaited_once_with(
                db,
                retention_days=90,
                updated_by_user_id="admin-1",
            )
            db.commit.assert_awaited_once()
            assert len(add_mock.call_args_list) == 1
            logged = add_mock.call_args_list[0][1]
            assert logged.action == "audit.retention.update"
            assert logged.details == {
                "previous_retention_days": None,
                "retention_days": 90,
            }

        # Keep-all policy must not issue deletes.
        db_keep_all = SimpleNamespace(commit=AsyncMock())
        with (
            patch(
                "app.domain.audit.services.audit_repository.get_retention_settings",
                new=AsyncMock(return_value=AuditRetentionSettings(retention_days=None)),
            ),
            patch(
                "app.domain.audit.services.audit_repository.delete_audit_logs_before",
                new=AsyncMock(return_value=999),
            ) as delete_mock,
        ):
            assert await cleanup_expired_audit_logs(db_keep_all) == 0
            delete_mock.assert_not_awaited()
            db_keep_all.commit.assert_not_awaited()

        # Finite retention deletes across batches until below batch_size.
        db_cleanup = SimpleNamespace(commit=AsyncMock())
        with (
            patch(
                "app.domain.audit.services.utc_now",
                return_value=fixed_now,
            ),
            patch(
                "app.domain.audit.services.audit_repository.get_retention_settings",
                new=AsyncMock(return_value=AuditRetentionSettings(retention_days=30)),
            ),
            patch(
                "app.domain.audit.services.audit_repository.delete_audit_logs_before",
                new=AsyncMock(side_effect=[2, 1]),
            ) as delete_mock,
        ):
            deleted = await cleanup_expired_audit_logs(
                db_cleanup,
                batch_size=2,
                max_batches=5,
            )
            assert deleted == 3
            assert delete_mock.await_count == 2
            expected_cutoff = fixed_now - timedelta(days=30)
            for call in delete_mock.await_args_list:
                assert call.args == (db_cleanup, expected_cutoff)
                assert call.kwargs == {"batch_size": 2}
            assert db_cleanup.commit.await_count == 2

    asyncio.run(exercise())


def main() -> None:
    test_resource_folder_descendants_cover_nested_children()
    test_resource_folder_rejects_moving_builtin_tools()
    test_team_to_response()
    test_workspace_daily_quota_uses_shanghai_day_boundary()
    test_message_stream_releases_reader_at_lifetime_limit()
    test_workspace_analytics_member_trends()
    test_audit_retention_policy_and_cleanup()
    print("PLATFORM_UNIT_OK")


if __name__ == "__main__":
    main()
