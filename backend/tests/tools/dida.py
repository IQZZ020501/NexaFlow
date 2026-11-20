"""DIDA CLI 0.1.16 HTTP contracts, without an external account or CLI installation."""

import json
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs

import httpx2
from jsonschema import Draft202012Validator

from app.adapters.integrations import client
from app.domain.tools.integrations.dida_catalog import DIDA_OPERATIONS
from app.ports.integrations import IntegrationProviderError

START, END = "2026-11-20T14:00:00+08:00", "2026-11-20T15:00:00+08:00"
PROJECT = {"project_id": "project-1"}
TASK = {**PROJECT, "task_id": "task-1"}
CASES = [
    ("get_preference", {}, "POST", "/preference", None),
    ("get_task", TASK, "GET", "/project/project-1/task/task-1", None),
    (
        "create_task",
        {**PROJECT, "title": "Review"},
        "POST",
        "/task",
        {"projectId": "project-1", "title": "Review"},
    ),
    (
        "update_task",
        {**TASK, "title": "Updated"},
        "POST",
        "/task/task-1",
        {"id": "task-1", "projectId": "project-1", "title": "Updated"},
    ),
    ("complete_task", TASK, "POST", "/project/project-1/task/task-1/complete", None),
    (
        "complete_tasks",
        {**PROJECT, "task_ids": ["task-1"]},
        "POST",
        "/task/completeTasks",
        {"projectId": "project-1", "taskIds": ["task-1"]},
    ),
    ("delete_task", TASK, "DELETE", "/project/project-1/task/task-1", None),
    (
        "move_tasks",
        {
            "moves": [
                {
                    "from_project_id": "project-1",
                    "to_project_id": "project-2",
                    "task_id": "task-1",
                }
            ]
        },
        "POST",
        "/task/move",
        [
            {
                "fromProjectId": "project-1",
                "toProjectId": "project-2",
                "taskId": "task-1",
            }
        ],
    ),
    (
        "assign_task",
        {**TASK, "assignee_username": "member@example.com"},
        "POST",
        "/task/assign",
        {
            "projectId": "project-1",
            "taskId": "task-1",
            "assigneeUsername": "member@example.com",
        },
    ),
    (
        "unassign_task",
        TASK,
        "POST",
        "/task/unassign",
        {"projectId": "project-1", "taskId": "task-1"},
    ),
    (
        "list_completed_tasks",
        {"project_ids": ["project-1"], "start_date": START, "end_date": END},
        "POST",
        "/task/completed",
        {"projectIds": ["project-1"], "startDate": START, "endDate": END},
    ),
    (
        "filter_tasks",
        {"priority": [0, 5], "status": [-1, 0], "tag": ["work"], "kind": ["TEXT"]},
        "POST",
        "/task/filter",
        {"priority": [0, 5], "status": [-1, 0], "tag": ["work"], "kind": ["TEXT"]},
    ),
    (
        "search_tasks",
        {"keywords": "Review", "tags": ["work"], "due_from": START, "due_to": END},
        "POST",
        "/task/search",
        {"keywords": "Review", "tags": ["work"], "dueFrom": START, "dueTo": END},
    ),
    (
        "list_task_comments",
        TASK,
        "GET",
        "/project/project-1/task/task-1/comments",
        None,
    ),
    (
        "add_task_comment",
        {**TASK, "title": "Done"},
        "POST",
        "/project/project-1/task/task-1/comment",
        {"title": "Done"},
    ),
    (
        "delete_task_comment",
        {**TASK, "comment_id": "comment-1"},
        "DELETE",
        "/project/project-1/task/task-1/comment/comment-1",
        None,
    ),
    ("list_projects", {}, "GET", "/project", None),
    ("get_project", PROJECT, "GET", "/project/project-1", None),
    ("get_project_data", PROJECT, "GET", "/project/project-1/data", None),
    ("list_project_members", PROJECT, "GET", "/project/project-1/members", None),
    (
        "create_project",
        {"name": "Work", "view_mode": "kanban", "kind": "TASK"},
        "POST",
        "/project",
        {"name": "Work", "viewMode": "kanban", "kind": "TASK"},
    ),
    (
        "update_project",
        {**PROJECT, "closed": False},
        "POST",
        "/project/project-1",
        {"closed": False},
    ),
    ("delete_project", PROJECT, "DELETE", "/project/project-1", None),
    ("list_project_groups", {}, "GET", "/project/group", None),
    (
        "create_project_group",
        {"name": "Work"},
        "POST",
        "/project/group",
        {"name": "Work"},
    ),
    (
        "update_project_group",
        {"group_id": "group-1", "name": "New"},
        "POST",
        "/project/group/group-1",
        {"name": "New"},
    ),
    (
        "delete_project_group",
        {"group_id": "group-1"},
        "DELETE",
        "/project/group/group-1",
        None,
    ),
    ("list_columns", PROJECT, "GET", "/project/project-1/column", None),
    (
        "create_column",
        {**PROJECT, "name": "Doing"},
        "POST",
        "/project/project-1/column",
        {"name": "Doing"},
    ),
    (
        "update_column",
        {**PROJECT, "column_id": "column-1", "name": "Done"},
        "POST",
        "/project/project-1/column/column-1",
        {"name": "Done"},
    ),
    ("list_tags", {}, "GET", "/tag", None),
    (
        "create_tag",
        {"name": "work", "label": "Work", "sort_order": 0},
        "POST",
        "/tag",
        {"name": "work", "label": "Work", "sortOrder": 0},
    ),
    (
        "update_tag",
        {"name": "work", "parent": "", "type": 0},
        "PUT",
        "/tag",
        {"name": "work", "parent": "", "type": 0},
    ),
    (
        "rename_tag",
        {"name": "work", "new_name": "office", "scope": 1},
        "PUT",
        "/tag/rename",
        {"name": "work", "newName": "office"},
    ),
    ("delete_tag", {"name": "office"}, "DELETE", "/tag/delete", {"name": "office"}),
    ("get_focus", {"focus_id": "focus-1", "type": 0}, "GET", "/focus/focus-1", None),
    ("list_focus", {"from": START, "to": END, "type": 1}, "GET", "/focus", None),
    (
        "create_focus",
        {
            "type": 0,
            "start_time": START,
            "end_time": END,
            "duration": 3600,
            "relation_type": [0],
        },
        "POST",
        "/focus",
        {
            "type": 0,
            "startTime": START,
            "endTime": END,
            "duration": 3600,
            "relationType": [0],
        },
    ),
    (
        "update_focus",
        {"focus_id": "focus-1", "type": 1, "added": False},
        "POST",
        "/focus/focus-1",
        {"type": 1, "added": False},
    ),
    (
        "delete_focus",
        {"focus_id": "focus-1", "type": 0},
        "DELETE",
        "/focus/focus-1",
        None,
    ),
    ("get_habit", {"habit_id": "habit-1"}, "GET", "/habit/habit-1", None),
    ("list_habit_sections", {}, "GET", "/habit/sections", None),
    ("list_habits", {}, "GET", "/habit", None),
    (
        "create_habit",
        {
            "name": "Water",
            "goal": 8,
            "record_enable": True,
            "target_start_date": 20261120,
        },
        "POST",
        "/habit",
        {"name": "Water", "goal": 8, "recordEnable": True, "targetStartDate": 20261120},
    ),
    (
        "update_habit",
        {"habit_id": "habit-1", "record_enable": False, "ex_dates": ["20261121"]},
        "POST",
        "/habit/habit-1",
        {"recordEnable": False, "exDates": ["20261121"]},
    ),
    (
        "create_habit_checkin",
        {"habit_id": "habit-1", "stamp": 20261120, "op_time": START, "value": 1.5},
        "POST",
        "/habit/habit-1/checkin",
        {"stamp": 20261120, "opTime": START, "value": 1.5},
    ),
    (
        "list_habit_checkins",
        {"habit_ids": ["habit-1", "habit-2"], "from": 20261101, "to": 20261120},
        "GET",
        "/habit/checkins",
        None,
    ),
    ("list_calendar_accounts", {}, "GET", "/calendar/account", None),
    ("query_calendar_events", {}, "POST", "/calendar/event/query", None),
    ("list_countdowns", {}, "GET", "/countdown", None),
]


class DidaContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.response = httpx2.Response(200, json={"result": "ok"})

        async def handler(request):
            self.requests.append(request)
            if isinstance(self.response, Exception):
                raise self.response
            return self.response

        def factory(**_kwargs):
            return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))

        destination = patch.object(
            client, "validate_mcp_destination", AsyncMock(return_value=object())
        )
        transport = patch.object(client, "_hardened_http_client_factory", factory)
        destination.start()
        transport.start()
        self.addCleanup(destination.stop)
        self.addCleanup(transport.stop)

    async def call(self, operation, arguments):
        return await client.call_integration(
            "dida",
            operation,
            arguments,
            {"access_token": "private-token"},
            "invocation",
        )

    async def test_all_fifty_cli_business_contracts(self):
        definitions = {entry["name"]: entry for entry in DIDA_OPERATIONS}
        self.assertEqual(len(definitions), 50)
        self.assertEqual(set(definitions), {case[0] for case in CASES})
        self.assertNotIn("list_tasks", definitions)
        for operation, arguments, method, path, body in CASES:
            with self.subTest(operation=operation):
                definition = definitions[operation]
                Draft202012Validator.check_schema(definition["input_schema"])
                Draft202012Validator(definition["input_schema"]).validate(arguments)
                self.assertLessEqual(len(f"dida_{operation}_{'a' * 32}"), 64)
                self.response = httpx2.Response(
                    200,
                    json=["task-1"]
                    if operation == "complete_tasks"
                    else {"result": "ok"},
                )
                await self.call(operation, arguments)
                request = self.requests[-1]
                self.assertEqual(request.method, method)
                self.assertEqual(request.url.host, "api.dida365.com")
                self.assertEqual(request.url.path, "/open/v1" + path)
                self.assertEqual(
                    request.headers["authorization"], "Bearer private-token"
                )
                self.assertNotIn("private-token", str(request.url))
                self.assertEqual(
                    json.loads(request.content) if request.content else None, body
                )
                for identity in ("access_token", "client_secret", "url", "user_id"):
                    self.assertTrue(
                        list(
                            Draft202012Validator(
                                definition["input_schema"]
                            ).iter_errors({**arguments, identity: "forged"})
                        )
                    )

    async def test_task_fields_and_clear_operations_preserve_omission_false_and_null(
        self,
    ):
        await self.call(
            "create_task",
            {
                **PROJECT,
                "title": "Review",
                "priority": 5,
                "due_date": END,
                "time_zone": "Asia/Shanghai",
                "repeat_flag": "RRULE:FREQ=DAILY",
                "repeat_from": "2",
                "items": [{"title": "First", "is_all_day": False, "start_date": START}],
            },
        )
        self.assertEqual(
            json.loads(self.requests[-1].content),
            {
                "projectId": "project-1",
                "title": "Review",
                "priority": 5,
                "dueDate": END,
                "timeZone": "Asia/Shanghai",
                "repeatFlag": "RRULE:FREQ=DAILY",
                "repeatFrom": "2",
                "items": [{"title": "First", "isAllDay": False, "startDate": START}],
            },
        )
        await self.call(
            "update_task",
            {
                **TASK,
                "due_date": None,
                "start_date": None,
                "tags": [],
                "reminders": [],
                "is_all_day": False,
                "parent_id": None,
                "focus_summaries": [{"estimated_pomo": 0, "estimated_duration": 1500}],
            },
        )
        self.assertEqual(
            json.loads(self.requests[-1].content),
            {
                "id": "task-1",
                "projectId": "project-1",
                "dueDate": None,
                "startDate": None,
                "tags": [],
                "reminders": [],
                "isAllDay": False,
                "parentId": "",
                "focusSummaries": [{"estimatedPomo": 0, "estimatedDuration": 1500}],
            },
        )

    async def test_focus_habit_and_tag_query_shapes(self):
        await self.call("list_focus", {"from": START, "to": END, "type": 0})
        self.assertEqual(
            parse_qs(self.requests[-1].url.query.decode()),
            {"from": [START], "to": [END], "type": ["0"]},
        )
        await self.call(
            "list_habit_checkins",
            {"habit_ids": ["one", "two"], "from": 20261101, "to": 20261120},
        )
        self.assertEqual(
            dict(self.requests[-1].url.params),
            {"habitIds": "one,two", "from": "20261101", "to": "20261120"},
        )
        await self.call(
            "rename_tag", {"name": "work", "new_name": "office", "scope": 1}
        )
        self.assertEqual(dict(self.requests[-1].url.params), {"scope": "1"})

    async def test_calendar_default_range_and_partial_account_errors_are_preserved(
        self,
    ):
        partial = {
            "begin": START,
            "end": END,
            "events": [{"title": "Review"}],
            "status": "partial",
            "accountErrors": [
                {"accountId": "expired", "errorCode": "expired", "retryable": False}
            ],
            "errorAccountIds": ["expired"],
        }
        self.response = httpx2.Response(200, json=partial)
        self.assertEqual(await self.call("query_calendar_events", {}), partial)
        self.assertEqual(self.requests[-1].content, b"")
        await self.call(
            "query_calendar_events",
            {"account_id": "account@example.com", "begin": START, "end": END},
        )
        self.assertEqual(
            json.loads(self.requests[-1].content),
            {"accountId": "account@example.com", "begin": START, "end": END},
        )

    async def test_batch_completion_reports_failures_without_retrying_or_truncating(
        self,
    ):
        self.response = httpx2.Response(200, json=["first"])
        self.assertEqual(
            await self.call("complete_tasks", {"task_ids": ["first", "second"]}),
            {"completed": ["first"], "failed": ["second"]},
        )
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(
            json.loads(self.requests[0].content), {"taskIds": ["first", "second"]}
        )

    async def test_column_names_resolve_before_mutation_and_persisted_result_is_checked(
        self,
    ):
        responses = [
            [{"id": "column-1", "name": "Doing"}],
            {"id": "task-1", "columnId": "column-1"},
            {"id": "task-1", "columnId": "column-1"},
        ]

        async def request(method, url, **kwargs):
            self.requests.append((method, url, kwargs.get("body")))
            return responses.pop(0)

        with patch.object(client, "_request", request):
            result = await self.call(
                "update_task", {**TASK, "column_name": "Doing", "column_id": "ignored"}
            )
        self.assertEqual(result["columnId"], "column-1")
        self.assertEqual(
            [request[0] for request in self.requests], ["GET", "POST", "GET"]
        )
        self.assertEqual(
            self.requests[1][2],
            {"id": "task-1", "projectId": "project-1", "columnId": "column-1"},
        )
        self.response = httpx2.Response(200, json=[])
        before = len(self.requests)
        with self.assertRaises(IntegrationProviderError) as error:
            await self.call("update_task", {**TASK, "column_name": "Missing"})
        self.assertFalse(error.exception.uncertain)
        self.assertEqual(len(self.requests), before + 1)
        self.assertEqual(self.requests[-1].method, "GET")

    async def test_ignored_column_or_folder_changes_remain_uncertain(self):
        for operation, arguments in (
            ("update_task", {**TASK, "column_id": None}),
            ("update_project", {**PROJECT, "group_id": None}),
        ):
            with self.subTest(operation=operation):
                self.response = httpx2.Response(
                    200, json={"columnId": "old", "groupId": "old"}
                )
                before = len(self.requests)
                with self.assertRaises(IntegrationProviderError) as error:
                    await self.call(operation, arguments)
                self.assertTrue(error.exception.uncertain)
                self.assertEqual(len(self.requests), before + 2)
                self.assertEqual(self.requests[-2].method, "POST")
                self.assertEqual(self.requests[-1].method, "GET")

    async def test_read_only_post_errors_are_confirmed_and_writes_are_not_replayed(
        self,
    ):
        for response in (
            httpx2.Response(500, json={"error": "private-provider-detail"}),
            httpx2.ReadTimeout("timeout"),
        ):
            self.response = response
            for operation, arguments, writing in (
                ("get_preference", {}, False),
                ("filter_tasks", {}, False),
                ("search_tasks", {}, False),
                ("list_completed_tasks", {}, False),
                ("query_calendar_events", {}, False),
                ("create_task", {**PROJECT, "title": "Review"}, True),
            ):
                with self.subTest(operation=operation, response=response):
                    before = len(self.requests)
                    with self.assertRaises(IntegrationProviderError) as error:
                        await self.call(operation, arguments)
                    self.assertEqual(error.exception.uncertain, writing)
                    self.assertEqual(len(self.requests), before + 1)
                    self.assertNotIn("private-provider-detail", str(error.exception))

    async def test_invalid_paths_dates_and_obsolete_operation_never_dispatch(self):
        for operation, arguments in (
            ("get_task", {**TASK, "project_id": "../other"}),
            ("get_task", {**TASK, "task_id": "x?token=secret"}),
            ("list_focus", {"from": END, "to": START, "type": 0}),
            ("list_focus", {"from": "2026-10-01T00:00:00+08:00", "to": END, "type": 0}),
            (
                "create_focus",
                {"type": 0, "start_time": START, "end_time": "2026-11-20T15:00:00"},
            ),
            ("create_habit_checkin", {"habit_id": "habit-1", "stamp": 20260230}),
            ("query_calendar_events", {"begin": END, "end": START}),
            ("list_tasks", PROJECT),
        ):
            with self.subTest(operation=operation, arguments=arguments):
                with self.assertRaises(IntegrationProviderError):
                    await self.call(operation, arguments)
        self.assertFalse(self.requests)

    def test_schemas_reject_out_of_bounds_and_unrecognized_nested_fields(self):
        definitions = {
            entry["name"]: entry["input_schema"] for entry in DIDA_OPERATIONS
        }
        for operation, arguments in (
            ("complete_tasks", {"task_ids": ["task"] * 51}),
            ("create_task", {**PROJECT, "title": "Review", "priority": 2}),
            ("update_task", {**TASK, "focus_summaries": [{"estimated_pomo": 61}]}),
            (
                "update_task",
                {**TASK, "items": [{"title": "First", "access_token": "forged"}]},
            ),
            (
                "create_focus",
                {"type": 0, "start_time": START, "end_time": END, "tasks": [{}, {}]},
            ),
            ("update_project", PROJECT),
            ("update_focus", {"focus_id": "focus-1", "type": 0}),
            ("filter_tasks", {"status": [1]}),
            ("delete_tag", {"name": "work", "scope": 2}),
        ):
            with self.subTest(operation=operation):
                self.assertTrue(
                    list(
                        Draft202012Validator(definitions[operation]).iter_errors(
                            arguments
                        )
                    )
                )


if __name__ == "__main__":
    unittest.main()
