"""Build fixed Tencent API requests; caller identity always comes from the grant."""

from datetime import datetime

from app.adapters.integrations.validation import resource_identifier
from app.ports.integrations import IntegrationProviderError

# These official read APIs use POST without changing remote account state.
READ_ONLY_POST_OPERATIONS = frozenset(
    {"lookup_email", "lookup_phone", "minutes_by_url", "transcript_url"}
)


def _timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("Timezone required")
    return int(parsed.timestamp())


def _page(arguments, default=30, *, page_type=True):
    return {
        "page_token": arguments.get("page_token", ""),
        "page_size": arguments.get("page_size", default),
        **({"page_type": 1} if page_type else {}),
    }


def _select(arguments, names):
    return {key: arguments[key] for key in names if key in arguments}


def _time_range(arguments, *, iso=False):
    values = _select(arguments, ("start_time", "end_time"))
    timestamps = {key: _timestamp(value) for key, value in values.items()}
    if len(timestamps) == 2 and timestamps["start_time"] >= timestamps["end_time"]:
        raise ValueError("Invalid time range")
    return (
        {
            "from" if key == "start_time" else "to": value
            for key, value in values.items()
        }
        if iso
        else timestamps
    )


def _search(arguments):
    result = {
        **_page(arguments, page_type=False),
        **_time_range(arguments, iso=True),
    }
    if "query" in arguments:
        result.update(
            q=arguments["query"], q_fields=arguments.get("query_field", "all")
        )
    return result


def _meeting_body(arguments, open_id, *, create):
    body = {"userid": open_id, "instanceid": 1}
    body.update(
        _select(
            arguments, ("subject", "password", "timezone", "meeting_type", "settings")
        )
    )
    body.update({key: str(value) for key, value in _time_range(arguments).items()})
    if create:
        body.update(type=0, meeting_type=arguments.get("meeting_type", 0))
    if "recurring_rule" in arguments:
        body["meeting_type"] = 1
        rule = dict(arguments["recurring_rule"])
        if "until_date" in rule:
            rule["until_date"] = _timestamp(rule["until_date"])
        body["recurring_rule"] = rule
    if "sub_meeting_id" in arguments:
        if "recurring_rule" in arguments:
            raise ValueError("Conflicting recurring settings")
        body.update(
            meeting_type=1,
            recurring_rule={
                "sub_meeting_id": resource_identifier(arguments["sub_meeting_id"])
            },
        )
    if "invitees" in arguments:
        body["invitees"] = [{"userid": member} for member in arguments["invitees"]]
    return body


def build_request(operation, arguments, open_id):
    """Return method, fixed path, query and body, without dispatching HTTP."""
    try:
        return _build_request(operation, arguments, resource_identifier(open_id))
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise IntegrationProviderError(
            "Invalid integration operation arguments."
        ) from exc


def _build_request(operation, a, open_id):
    method, body, query = "GET", None, {}
    operator = {"operator_id": open_id, "operator_id_type": 2}
    user = {"userid": open_id, "instanceid": 1}
    meeting_id = resource_identifier(a["meeting_id"]) if "meeting_id" in a else None
    file_id = (
        resource_identifier(a["record_file_id"]) if "record_file_id" in a else None
    )
    if operation == "list_meetings":
        path, query = "/v1/meetings", {**user, **_page(a, 20)}
        if "start_time" in a and not a.get("page_token"):
            query["pos"] = _timestamp(a["start_time"])
        query.update(_select(a, ("is_show_all_sub_meetings",)))
    elif operation == "get_meeting":
        path, query = (
            f"/v1/meetings/{resource_identifier(meeting_id)}",
            {**operator, "instanceid": 1},
        )
    elif operation == "get_by_code":
        path, query = "/v1/meetings", {**user, "meeting_code": a["meeting_code"]}
    elif operation == "list_ended":
        path, query = f"/v1/history/meetings/{open_id}", {**_page(a), **_time_range(a)}
    elif operation == "search_meetings":
        path, query = (
            "/v1/meetings/search-meetings",
            {**operator, **_search(a), **_select(a, ("meeting_code",))},
        )
    elif operation in {"create_meeting", "update_meeting"}:
        create = operation == "create_meeting"
        method = "POST" if create else "PUT"
        path = (
            "/v1/meetings"
            if create
            else f"/v1/meetings/{resource_identifier(meeting_id)}"
        )
        body = _meeting_body(a, open_id, create=create)
    elif operation == "cancel_meeting":
        method, path = "POST", f"/v1/meetings/{resource_identifier(meeting_id)}/cancel"
        body = {
            **user,
            "meetingId": meeting_id,
            "reason_code": 0,
            "meeting_type": a.get("meeting_type", 0),
            **_select(a, ("sub_meeting_id",)),
        }
    elif operation == "list_invitees":
        path, query = (
            f"/v1/meetings/{resource_identifier(meeting_id)}/invitees",
            {**user, **_page(a)},
        )
    elif operation in {"add_invitees", "remove_invitees", "replace_invites"}:
        invitees = [{"userid": member} for member in a["invitees"]]
        if operation == "replace_invites":
            method, path = (
                "PUT",
                f"/v1/meetings/{resource_identifier(meeting_id)}/invitees",
            )
            body = {**user, "meeting_id": meeting_id, "invitees": invitees}
        else:
            method, path = (
                "POST",
                f"/v1/meetings/{resource_identifier(meeting_id)}/modify-invitees",
            )
            field = "add_invitees" if operation == "add_invitees" else "delete_invitees"
            body = {**operator, "instanceid": 1, field: invitees}
    elif operation == "search_records":
        path = "/v1/mcp/records/search"
        query = {
            **operator,
            **_search(a),
            "file_type": a.get("file_type", "all"),
            **_select(a, ("meeting_id", "meeting_code")),
        }
    elif operation == "record_download":
        path, query = (
            "/v1/mcp/addresses",
            {**operator, **_page(a), "meeting_record_id": a["meeting_record_id"]},
        )
    elif operation in {"record_minutes", "record_todos"}:
        path = (
            f"/v1/smart/minutes/{resource_identifier(file_id)}"
            if operation == "record_minutes"
            else f"/v1/mcp/smart/todos/{resource_identifier(file_id)}"
        )
        query = {**operator, "lang": a.get("lang", "default")}
        if operation == "record_todos":
            query["record_file_id"] = file_id
        if "password" in a:
            query["pwd"] = a["password"]
    elif operation in {"transcript_get", "transcript_find", "transcript_part"}:
        suffix = {
            "transcript_get": "details",
            "transcript_find": "search",
            "transcript_part": "paragraphs",
        }[operation]
        path, query = (
            f"/v1/records/mcp/transcripts/{suffix}",
            {
                **operator,
                "record_file_id": resource_identifier(file_id),
                **_select(a, ("meeting_id", "pid", "limit", "text")),
            },
        )
    elif operation == "record_timeline":
        path, query = (
            "/v1/mcp/asr/get-recording-timeline-mcp",
            {
                **operator,
                "record_file_id": resource_identifier(file_id),
                **_select(a, ("lang",)),
            },
        )
    elif operation in {"minutes_by_url", "transcript_url"}:
        method = "POST"
        path = (
            "/v1/mcp/smart/minutes/list-by-url"
            if operation == "minutes_by_url"
            else "/v1/mcp/records/transcripts/list-by-url"
        )
        body = {
            **operator,
            **_page(a, 5, page_type=False),
            "share_url": a["share_url"],
            **_select(a, ("lang",)),
        }
        if "password" in a:
            body["pwd"] = a["password"]
    elif operation in {"participants", "waiting_log"}:
        path = (
            f"/v1/meetings/{resource_identifier(meeting_id)}/participants"
            if operation == "participants"
            else f"/v1/meeting/{resource_identifier(meeting_id)}/waiting-room"
        )
        query = {
            **operator,
            **_page(a, 100),
            **_time_range(a),
            **_select(a, ("sub_meeting_id",)),
        }
    elif operation == "export_members":
        method, path = "POST", "/v1/meetings/export-participants-list"
        body = {
            **operator,
            "meeting_id": resource_identifier(meeting_id),
            "file_type": a.get("file_type", "xlsx"),
            **_time_range(a),
            **_select(a, ("sub_meeting_id",)),
        }
    elif operation == "export_result":
        path, query = f"/v1/export/{resource_identifier(a['job_id'])}", operator
    elif operation == "search_contacts":
        path, query = (
            "/v1/contacts/members/search",
            {**operator, **_select(a, ("username", "job_title", "department_name"))},
        )
    elif operation in {"lookup_email", "lookup_phone"}:
        field = "emails" if operation == "lookup_email" else "phones"
        method, path = (
            "POST",
            f"/v1/contacts/members/lookup-by-{'email' if field == 'emails' else 'phone'}",
        )
        body = {
            **operator,
            "users_email" if field == "emails" else "users_phone": a[field],
        }
    elif operation in {"call_members", "kick_members", "waiting_control"}:
        users = [
            {"to_operator_id": member, "to_operator_id_type": 2}
            for member in a["users"]
        ]
        body = {**operator, "users": users}
        if operation == "call_members":
            method, path = (
                "POST",
                f"/v1/meetings/{resource_identifier(meeting_id)}/batch-call",
            )
        else:
            body["instanceid"] = 1
            method = "PUT"
            if operation == "kick_members":
                path = f"/v1/real-control/meetings/{resource_identifier(meeting_id)}/kickout"
                body["allow_rejoin"] = a.get("allow_rejoin", True)
            else:
                path = f"/v1/real-control/meetings/{resource_identifier(meeting_id)}/waiting-room"
                body["operate_type"] = {
                    "enter-meeting": 1,
                    "back-to-waiting": 2,
                    "expel": 3,
                }[a["operate_type"]]
                if "allow_rejoin" in a:
                    if a["operate_type"] != "expel":
                        raise ValueError("allow_rejoin requires expel")
                    body["allow_rejoin"] = a["allow_rejoin"]
    elif operation == "search_minutes":
        path, query = "/v1/mcp/asr/search-minutes-mcp", {**operator, **_search(a)}
        query.pop("q_fields", None)
    elif operation == "get_minutes":
        path = "/v1/mcp/asr/get-minutes-mcp"
        query = {
            **operator,
            **_page(a, 10, page_type=False),
            **_select(a, ("minute_id", "meeting_id", "sub_meeting_id")),
            "short_summary": "false",
        }
        query.update(
            {
                key: str(a.get(key, True)).lower()
                for key in ("overview", "summary_points", "todos")
            }
        )
    elif operation == "live_minutes":
        path, query = (
            "/v1/mcp/asr/get-transient-minutes-mcp",
            {
                **operator,
                **_page(a, 100, page_type=False),
                "minute_id": a["minute_id"],
                "pagination_type": 2,
            },
        )
    else:
        raise IntegrationProviderError("Unsupported integration operation.")
    return method, path, {key: str(value) for key, value in query.items()}, body
