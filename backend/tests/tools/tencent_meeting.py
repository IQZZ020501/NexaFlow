"""Tencent business API contracts: no account credentials or external requests."""

import json
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs

import httpx2
from jsonschema import Draft202012Validator

from app.adapters.integrations import client
from app.domain.tools.integrations.tencent_catalog import TENCENT_OPERATIONS
from app.ports.integrations import IntegrationProviderError

START, END = "2026-11-20T14:00:00+08:00", "2026-11-20T15:00:00+08:00"
MEETING = {"meeting_id": "meeting-123"}
FILE = {"record_file_id": "record-123"}
PAGE = {"page_token": "next+/=opaque", "page_size": 2}
CASES = [
    ("list_meetings", {**PAGE, "start_time": START}, "GET", "/v1/meetings"),
    ("get_meeting", MEETING, "GET", "/v1/meetings/meeting-123"),
    ("get_by_code", {"meeting_code": "123456789"}, "GET", "/v1/meetings"),
    (
        "list_ended",
        {**PAGE, "start_time": START, "end_time": END},
        "GET",
        "/v1/history/meetings/owner",
    ),
    (
        "search_meetings",
        {**PAGE, "query": "Review", "start_time": START, "end_time": END},
        "GET",
        "/v1/meetings/search-meetings",
    ),
    (
        "create_meeting",
        {
            "subject": "Review",
            "start_time": START,
            "end_time": END,
            "invitees": ["member-1"],
        },
        "POST",
        "/v1/meetings",
    ),
    (
        "update_meeting",
        {**MEETING, "settings": {"auto_in_waiting_room": False}},
        "PUT",
        "/v1/meetings/meeting-123",
    ),
    (
        "cancel_meeting",
        {**MEETING, "meeting_type": 1},
        "POST",
        "/v1/meetings/meeting-123/cancel",
    ),
    ("list_invitees", {**MEETING, **PAGE}, "GET", "/v1/meetings/meeting-123/invitees"),
    (
        "add_invitees",
        {**MEETING, "invitees": ["member-1"]},
        "POST",
        "/v1/meetings/meeting-123/modify-invitees",
    ),
    (
        "remove_invitees",
        {**MEETING, "invitees": ["member-1"]},
        "POST",
        "/v1/meetings/meeting-123/modify-invitees",
    ),
    (
        "replace_invites",
        {**MEETING, "invitees": []},
        "PUT",
        "/v1/meetings/meeting-123/invitees",
    ),
    (
        "search_records",
        {**MEETING, **PAGE, "query": "Review", "start_time": START, "end_time": END},
        "GET",
        "/v1/mcp/records/search",
    ),
    (
        "record_download",
        {"meeting_record_id": "group-123", **PAGE},
        "GET",
        "/v1/mcp/addresses",
    ),
    (
        "record_minutes",
        {**FILE, "password": "share-password"},
        "GET",
        "/v1/smart/minutes/record-123",
    ),
    ("record_todos", FILE, "GET", "/v1/mcp/smart/todos/record-123"),
    (
        "transcript_get",
        {**FILE, "pid": "paragraph-2", "limit": 20},
        "GET",
        "/v1/records/mcp/transcripts/details",
    ),
    (
        "transcript_find",
        {**FILE, "text": "decision"},
        "GET",
        "/v1/records/mcp/transcripts/search",
    ),
    (
        "transcript_part",
        {**FILE, **MEETING},
        "GET",
        "/v1/records/mcp/transcripts/paragraphs",
    ),
    ("record_timeline", FILE, "GET", "/v1/mcp/asr/get-recording-timeline-mcp"),
    (
        "minutes_by_url",
        {"share_url": "https://meeting.tencent.com/share/example", **PAGE},
        "POST",
        "/v1/mcp/smart/minutes/list-by-url",
    ),
    (
        "transcript_url",
        {"share_url": "https://meeting.tencent.com/share/example", **PAGE},
        "POST",
        "/v1/mcp/records/transcripts/list-by-url",
    ),
    (
        "participants",
        {**MEETING, **PAGE},
        "GET",
        "/v1/meetings/meeting-123/participants",
    ),
    ("waiting_log", {**MEETING, **PAGE}, "GET", "/v1/meeting/meeting-123/waiting-room"),
    (
        "export_members",
        {**MEETING, "start_time": START, "end_time": END},
        "POST",
        "/v1/meetings/export-participants-list",
    ),
    ("export_result", {"job_id": "job-123"}, "GET", "/v1/export/job-123"),
    (
        "search_contacts",
        {"username": "Member", "department_name": "Engineering"},
        "GET",
        "/v1/contacts/members/search",
    ),
    (
        "lookup_email",
        {"emails": ["member@example.com"]},
        "POST",
        "/v1/contacts/members/lookup-by-email",
    ),
    (
        "lookup_phone",
        {"phones": ["13800000000"]},
        "POST",
        "/v1/contacts/members/lookup-by-phone",
    ),
    (
        "call_members",
        {**MEETING, "users": ["member-1"]},
        "POST",
        "/v1/meetings/meeting-123/batch-call",
    ),
    (
        "kick_members",
        {**MEETING, "users": ["member-1"], "allow_rejoin": False},
        "PUT",
        "/v1/real-control/meetings/meeting-123/kickout",
    ),
    (
        "waiting_control",
        {
            **MEETING,
            "users": ["member-1"],
            "operate_type": "expel",
            "allow_rejoin": False,
        },
        "PUT",
        "/v1/real-control/meetings/meeting-123/waiting-room",
    ),
    (
        "search_minutes",
        {**PAGE, "query": "Review"},
        "GET",
        "/v1/mcp/asr/search-minutes-mcp",
    ),
    ("get_minutes", {**MEETING, **PAGE}, "GET", "/v1/mcp/asr/get-minutes-mcp"),
    (
        "live_minutes",
        {"minute_id": "minute-123", **PAGE},
        "GET",
        "/v1/mcp/asr/get-transient-minutes-mcp",
    ),
]


class TencentContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.response = httpx2.Response(200, json={"result": "ok"})
        self.grant = {
            "access_token": "secret-token",
            "open_id": "owner",
            "device_id": "original-device",
        }

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
            "tencent_meeting", operation, arguments, self.grant, "invocation"
        )

    async def test_every_advertised_tool_has_a_valid_bounded_contract_and_request(self):
        definitions = {entry["name"]: entry for entry in TENCENT_OPERATIONS}
        self.assertEqual(len(definitions), 35)
        self.assertEqual(set(definitions), {case[0] for case in CASES})
        for operation, arguments, method, path in CASES:
            with self.subTest(operation=operation):
                definition = definitions[operation]
                Draft202012Validator.check_schema(definition["input_schema"])
                Draft202012Validator(definition["input_schema"]).validate(arguments)
                self.assertLessEqual(len(f"tencent_meeting_{operation}_{'a' * 32}"), 64)
                result = await self.call(operation, arguments)
                self.assertEqual(result, {"result": "ok"})
                request = self.requests[-1]
                self.assertEqual(request.method, method)
                self.assertEqual(request.url.host, "api.meeting.qq.com")
                self.assertEqual(request.url.path, path)
                self.assertEqual(request.headers["Tmeet-Open-Source"], "CLI")
                self.assertEqual(
                    request.headers["Tmeet-Unique-ID"], "owner*original-device"
                )
                self.assertEqual(request.headers["OpenId"], "owner")
                self.assertNotIn("secret-token", str(request.url))
                values = (
                    json.loads(request.content)
                    if request.content
                    else dict(request.url.params)
                )
                if "operator_id" in values:
                    self.assertEqual(values["operator_id"], "owner")
                    self.assertIn(values["operator_id_type"], (2, "2"))
                if "userid" in values:
                    self.assertEqual(values["userid"], "owner")
                if "page_token" in arguments:
                    self.assertEqual(values["page_token"], PAGE["page_token"])
                    self.assertEqual(int(values["page_size"]), 2)
                for identity in (
                    "operator_id",
                    "userid",
                    "access_token",
                    "device_id",
                    "url",
                ):
                    errors = list(
                        Draft202012Validator(definition["input_schema"]).iter_errors(
                            {**arguments, identity: "forged"}
                        )
                    )
                    self.assertTrue(errors, identity)

    async def test_meeting_times_and_recurring_settings_are_converted_without_changing_omitted_fields(
        self,
    ):
        await self.call(
            "create_meeting",
            {
                "subject": "Review",
                "start_time": START,
                "end_time": END,
                "meeting_type": 1,
                "recurring_rule": {
                    "recurring_type": 2,
                    "until_type": 1,
                    "until_count": 7,
                },
                "invitees": ["member-1"],
                "settings": {"auto_in_waiting_room": True},
            },
        )
        self.assertEqual(
            json.loads(self.requests[-1].content),
            {
                "userid": "owner",
                "instanceid": 1,
                "type": 0,
                "subject": "Review",
                "start_time": "1795154400",
                "end_time": "1795158000",
                "meeting_type": 1,
                "recurring_rule": {
                    "recurring_type": 2,
                    "until_type": 1,
                    "until_count": 7,
                },
                "invitees": [{"userid": "member-1"}],
                "settings": {"auto_in_waiting_room": True},
            },
        )
        await self.call(
            "update_meeting",
            {**MEETING, "password": "", "settings": {"auto_in_waiting_room": False}},
        )
        self.assertEqual(
            json.loads(self.requests[-1].content),
            {
                "userid": "owner",
                "instanceid": 1,
                "password": "",
                "settings": {"auto_in_waiting_room": False},
            },
        )
        await self.call(
            "update_meeting",
            {**MEETING, "sub_meeting_id": "occurrence-1", "start_time": START},
        )
        body = json.loads(self.requests[-1].content)
        self.assertEqual(body["recurring_rule"], {"sub_meeting_id": "occurrence-1"})
        self.assertNotIn("end_time", body)

    async def test_invite_mutations_preserve_the_official_payload_shapes(self):
        for operation, field in (
            ("add_invitees", "add_invitees"),
            ("remove_invitees", "delete_invitees"),
        ):
            await self.call(operation, {**MEETING, "invitees": ["member-1"]})
            self.assertEqual(
                json.loads(self.requests[-1].content),
                {
                    "operator_id": "owner",
                    "operator_id_type": 2,
                    "instanceid": 1,
                    field: [{"userid": "member-1"}],
                },
            )
        await self.call("replace_invites", {**MEETING, "invitees": []})
        self.assertEqual(json.loads(self.requests[-1].content)["invitees"], [])

    async def test_control_operations_use_open_id_members_and_explicit_allow_rejoin(
        self,
    ):
        for action, code in (
            ("enter-meeting", 1),
            ("back-to-waiting", 2),
            ("expel", 3),
        ):
            await self.call(
                "waiting_control",
                {**MEETING, "users": ["member-1"], "operate_type": action},
            )
            body = json.loads(self.requests[-1].content)
            self.assertEqual(body["operate_type"], code)
            self.assertEqual(
                body["users"],
                [{"to_operator_id": "member-1", "to_operator_id_type": 2}],
            )
            self.assertNotIn("allow_rejoin", body)
        with self.assertRaises(IntegrationProviderError):
            await self.call(
                "waiting_control",
                {
                    **MEETING,
                    "users": ["member-1"],
                    "operate_type": "enter-meeting",
                    "allow_rejoin": False,
                },
            )

    async def test_read_only_post_errors_are_confirmed_but_writes_remain_uncertain(
        self,
    ):
        for response in (
            httpx2.Response(500, json={"private": "do-not-echo"}),
            httpx2.ReadTimeout("do-not-echo"),
        ):
            for operation, arguments, uncertain in (
                ("lookup_email", {"emails": ["member@example.com"]}, False),
                (
                    "minutes_by_url",
                    {"share_url": "https://meeting.tencent.com/share/example"},
                    False,
                ),
                (
                    "create_meeting",
                    {"subject": "Review", "start_time": START, "end_time": END},
                    True,
                ),
                ("cancel_meeting", MEETING, True),
                ("export_members", MEETING, True),
            ):
                with self.subTest(
                    operation=operation, response=type(response).__name__
                ):
                    self.response = response
                    before = len(self.requests)
                    with self.assertRaises(IntegrationProviderError) as error:
                        await self.call(operation, arguments)
                    self.assertEqual(error.exception.uncertain, uncertain)
                    self.assertNotIn("do-not-echo", str(error.exception))
                    self.assertEqual(
                        len(self.requests), before + 1, "no automatic write retries"
                    )

    async def test_invalid_paths_and_times_never_dispatch(self):
        for operation, arguments in (
            ("get_meeting", {"meeting_id": "../other"}),
            ("record_minutes", {"record_file_id": "x/y"}),
            ("export_result", {"job_id": "?token=other"}),
            (
                "create_meeting",
                {"subject": "Review", "start_time": END, "end_time": START},
            ),
            (
                "create_meeting",
                {
                    "subject": "Review",
                    "start_time": "2026-11-20T14:00:00",
                    "end_time": END,
                },
            ),
            (
                "create_meeting",
                {"subject": "Review", "start_time": "invalid", "end_time": END},
            ),
            ("not_a_tool", {}),
        ):
            with self.subTest(operation=operation, arguments=arguments):
                with self.assertRaises(IntegrationProviderError):
                    await self.call(operation, arguments)
        self.assertEqual(self.requests, [])

    async def test_search_time_filters_and_transcript_ranges_retain_the_expected_types(
        self,
    ):
        await self.call(
            "search_meetings", {"query": "budget", "start_time": START, "end_time": END}
        )
        query = parse_qs(self.requests[-1].url.query.decode())
        self.assertEqual(query["from"], [START])
        self.assertEqual(query["to"], [END])
        self.assertEqual(query["q"], ["budget"])
        await self.call(
            "transcript_get", {**FILE, "pid": "next-paragraph", "limit": 20}
        )
        query = dict(self.requests[-1].url.params)
        self.assertEqual(query["pid"], "next-paragraph")
        self.assertEqual(query["limit"], "20")
        self.assertNotIn("page_token", query)
        await self.call(
            "export_members", {**MEETING, "start_time": START, "end_time": END}
        )
        body = json.loads(self.requests[-1].content)
        self.assertEqual(body["start_time"], 1795154400)
        self.assertEqual(body["file_type"], "xlsx")

    async def test_omitted_search_times_use_provider_defaults_without_boundary_drift(
        self,
    ):
        for operation in ("search_records", "search_minutes"):
            await self.call(operation, {"page_size": 1})
            query = dict(self.requests[-1].url.params)
            self.assertNotIn("from", query)
            self.assertNotIn("to", query)

    def test_schemas_reject_oversized_batches_unsafe_settings_and_missing_identifiers(
        self,
    ):
        definitions = {entry["name"]: entry for entry in TENCENT_OPERATIONS}
        for operation, arguments in (
            ("list_meetings", {"page_size": 21}),
            ("participants", {**MEETING, "page_size": 101}),
            ("add_invitees", {**MEETING, "invitees": []}),
            (
                "call_members",
                {**MEETING, "users": [f"member-{index}" for index in range(21)]},
            ),
            ("add_invitees", {**MEETING, "invitees": ["same", "same"]}),
            ("update_meeting", MEETING),
            ("update_meeting", {**MEETING, "settings": {"unrecognized": True}}),
            ("update_meeting", {**MEETING, "meeting_type": 1}),
            (
                "update_meeting",
                {**MEETING, "meeting_type": 0, "sub_meeting_id": "one-instance"},
            ),
            (
                "cancel_meeting",
                {**MEETING, "meeting_type": 1, "sub_meeting_id": "one-instance"},
            ),
            ("get_minutes", {}),
            (
                "create_meeting",
                {
                    "subject": "Review",
                    "start_time": START,
                    "end_time": END,
                    "meeting_type": 1,
                },
            ),
            (
                "create_meeting",
                {
                    "subject": "Review",
                    "start_time": START,
                    "end_time": END,
                    "meeting_type": 1,
                    "recurring_rule": {
                        "recurring_type": 4,
                        "until_type": 1,
                        "until_count": 51,
                    },
                },
            ),
        ):
            with self.subTest(operation=operation):
                self.assertTrue(
                    list(
                        Draft202012Validator(
                            definitions[operation]["input_schema"]
                        ).iter_errors(arguments)
                    )
                )


if __name__ == "__main__":
    unittest.main()
