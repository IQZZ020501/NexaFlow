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
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.application.resource_folders.service import (
    descendant_folder_ids,
    move_resource,
)
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


def main() -> None:
    test_resource_folder_descendants_cover_nested_children()
    test_resource_folder_rejects_moving_builtin_tools()
    test_team_to_response()
    test_workspace_daily_quota_uses_shanghai_day_boundary()
    test_message_stream_releases_reader_at_lifetime_limit()
    print("PLATFORM_UNIT_OK")


if __name__ == "__main__":
    main()
