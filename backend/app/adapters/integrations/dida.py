"""Fixed requests matching @suibiji/dida-cli 0.1.16, without a shared CLI token file."""

from datetime import datetime, timedelta
from urllib.parse import urlencode

from app.adapters.integrations.validation import resource_identifier
from app.ports.integrations import IntegrationProviderError

BASE_URL = "https://api.dida365.com/open/v1"
READ_ONLY_POST_OPERATIONS = frozenset(
    {
        "get_preference",
        "list_completed_tasks",
        "filter_tasks",
        "search_tasks",
        "query_calendar_events",
    }
)
_TASK_FIELDS = "project_id title parent_id content desc is_all_day start_date due_date time_zone reminders repeat_flag repeat_from priority sort_order items tags"
_PROJECT_FIELDS = "name color sort_order view_mode kind"
_TAG_FIELDS = "name color sort_order sort_type parent"
_FOCUS_FIELDS = "type task_id note tasks status start_time end_time pause_duration adjust_time added"
_HABIT_FIELDS = "name icon_res color sort_order status encouragement type goal step unit repeat_rule reminders record_enable section_id target_days target_start_date completed_cycles ex_dates style"


def _camel(value):
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


def _encode(value):
    if isinstance(value, dict):
        return {_camel(key): _encode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_encode(item) for item in value]
    return value


def _body(arguments, names):
    result = {key: arguments[key] for key in names.split() if key in arguments}
    for key in ("parent_id", "column_id", "group_id"):
        if key in result and result[key] is None:
            result[key] = ""
    return _encode(result)


def _time(value):
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("Timezone required")
    return result


def _validate_dates(a, operation):
    if operation == "list_habit_checkins":
        for key in ("from", "to"):
            datetime.strptime(str(a[key]), "%Y%m%d")
        if a["from"] > a["to"]:
            raise ValueError("Invalid date range")
    for key in ("stamp", "target_start_date"):
        if key in a:
            datetime.strptime(str(a[key]), "%Y%m%d")
    for value in a.get("ex_dates", []):
        datetime.strptime(value, "%Y%m%d")
    for key in ("time", "op_time", "completed_time"):
        if key in a:
            _time(a[key])
    for key in ("items", "tasks"):
        for item in a.get(key, []):
            _validate_dates(item, "")
    for start, end in (
        ("start_date", "due_date"),
        ("start_date", "end_date"),
        ("due_from", "due_to"),
        ("start_time", "end_time"),
        ("begin", "end"),
    ):
        values = [
            _time(a[key]) if a.get(key) is not None else None for key in (start, end)
        ]
        if all(value is not None for value in values) and values[0] > values[1]:
            raise ValueError("Invalid time range")
    if operation == "list_focus":
        duration = _time(a["to"]) - _time(a["from"])
        if not timedelta(0) <= duration <= timedelta(days=30):
            raise ValueError("Invalid focus range")


def build_request(operation, a):
    try:
        _validate_dates(a, operation)
        return _build_request(operation, a)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise IntegrationProviderError(
            "Invalid integration operation arguments."
        ) from exc


def _build_request(operation, a):
    method, query, body = "GET", {}, None
    project = (
        f"/project/{resource_identifier(a['project_id'])}" if "project_id" in a else ""
    )
    task = (
        f"{project}/task/{resource_identifier(a['task_id'])}" if "task_id" in a else ""
    )
    if operation == "get_preference":
        method, path = "POST", "/preference"
    elif operation == "list_projects":
        path = "/project"
    elif operation in {
        "get_project",
        "get_project_data",
        "list_project_members",
        "delete_project",
    }:
        path = (
            project
            + {
                "get_project": "",
                "get_project_data": "/data",
                "list_project_members": "/members",
                "delete_project": "",
            }[operation]
        )
        method = "DELETE" if operation == "delete_project" else "GET"
    elif operation in {"create_project", "update_project"}:
        method, path = "POST", "/project" if operation == "create_project" else project
        body = _body(
            a,
            _PROJECT_FIELDS
            + (" group_id closed" if operation == "update_project" else ""),
        )
    elif operation in {
        "get_task",
        "complete_task",
        "delete_task",
        "list_task_comments",
        "add_task_comment",
        "delete_task_comment",
    }:
        path = task
        if operation == "complete_task":
            method, path = "POST", task + "/complete"
        elif operation == "delete_task":
            method = "DELETE"
        elif operation == "list_task_comments":
            path += "/comments"
        elif operation == "add_task_comment":
            method, path, body = "POST", task + "/comment", {"title": a["title"]}
        elif operation == "delete_task_comment":
            method, path = (
                "DELETE",
                task + "/comment/" + resource_identifier(a["comment_id"]),
            )
    elif operation in {"create_task", "update_task"}:
        method, path = "POST", "/task"
        body = _body(a, _TASK_FIELDS)
        if operation == "update_task":
            path += "/" + resource_identifier(a["task_id"])
            body.update(
                _body(a, "column_id kind focus_summaries status completed_time"),
                id=a["task_id"],
            )
    elif operation in {
        "complete_tasks",
        "move_tasks",
        "assign_task",
        "unassign_task",
        "list_completed_tasks",
        "filter_tasks",
        "search_tasks",
    }:
        endpoint, fields = {
            "complete_tasks": ("completeTasks", "project_id task_ids"),
            "move_tasks": ("move", "moves"),
            "assign_task": ("assign", "project_id task_id assignee_username"),
            "unassign_task": ("unassign", "project_id task_id"),
            "list_completed_tasks": ("completed", "project_ids start_date end_date"),
            "filter_tasks": (
                "filter",
                "project_ids start_date end_date priority tag kind status",
            ),
            "search_tasks": (
                "search",
                "keywords project_ids tags status due_from due_to",
            ),
        }[operation]
        method, path = "POST", "/task/" + endpoint
        body = _body(a, fields)
        if operation == "move_tasks":
            body = body["moves"]
    elif operation in {
        "list_project_groups",
        "create_project_group",
        "update_project_group",
        "delete_project_group",
    }:
        path = "/project/group"
        if operation in {"update_project_group", "delete_project_group"}:
            path += "/" + resource_identifier(a["group_id"])
        if operation == "delete_project_group":
            method = "DELETE"
        elif operation != "list_project_groups":
            method, body = "POST", {"name": a["name"]}
    elif operation in {"list_columns", "create_column", "update_column"}:
        path = project + "/column"
        if operation == "update_column":
            path += "/" + resource_identifier(a["column_id"])
        if operation != "list_columns":
            method, body = "POST", {"name": a["name"]}
    elif operation in {
        "list_tags",
        "create_tag",
        "update_tag",
        "rename_tag",
        "delete_tag",
    }:
        path = "/tag"
        if operation == "create_tag":
            method, body = "POST", _body(a, _TAG_FIELDS + " label")
        elif operation == "update_tag":
            method, body = "PUT", _body(a, _TAG_FIELDS + " type")
        elif operation in {"rename_tag", "delete_tag"}:
            path += "/rename" if operation == "rename_tag" else "/delete"
            method = "PUT" if operation == "rename_tag" else "DELETE"
            query, body = (
                {"scope": a.get("scope", 0)},
                _body(a, "name new_name" if operation == "rename_tag" else "name"),
            )
    elif operation in {
        "get_focus",
        "list_focus",
        "create_focus",
        "update_focus",
        "delete_focus",
    }:
        path = "/focus"
        if operation in {"get_focus", "update_focus", "delete_focus"}:
            path += "/" + resource_identifier(a["focus_id"])
        if operation in {"get_focus", "delete_focus"}:
            query = {"type": a["type"]}
            method = "DELETE" if operation == "delete_focus" else "GET"
        elif operation == "list_focus":
            query = {key: a[key] for key in ("from", "to", "type")}
        else:
            method, body = (
                "POST",
                _body(
                    a,
                    _FOCUS_FIELDS
                    + (
                        " duration relation_type" if operation == "create_focus" else ""
                    ),
                ),
            )
    elif operation in {
        "get_habit",
        "list_habit_sections",
        "list_habits",
        "create_habit",
        "update_habit",
        "create_habit_checkin",
        "list_habit_checkins",
    }:
        path = "/habit"
        if operation in {"get_habit", "update_habit", "create_habit_checkin"}:
            path += "/" + resource_identifier(a["habit_id"])
        if operation == "list_habit_sections":
            path += "/sections"
        elif operation == "list_habit_checkins":
            path += "/checkins"
            query = {
                "habitIds": ",".join(
                    resource_identifier(value) for value in a["habit_ids"]
                ),
                "from": a["from"],
                "to": a["to"],
            }
        elif operation == "create_habit_checkin":
            method, path, body = (
                "POST",
                path + "/checkin",
                _body(a, "stamp time op_time value goal status"),
            )
        elif operation in {"create_habit", "update_habit"}:
            method, body = "POST", _body(a, _HABIT_FIELDS)
    elif operation == "list_calendar_accounts":
        path = "/calendar/account"
    elif operation == "query_calendar_events":
        method, path = "POST", "/calendar/event/query"
        body = _body(a, "account_id begin end") or None
    elif operation == "list_countdowns":
        path = "/countdown"
    else:
        raise IntegrationProviderError("Unsupported integration operation.")
    return method, path, query, body


async def call_integration(operation, arguments, credentials, request):
    headers = {"Authorization": f"Bearer {credentials['access_token']}"}

    async def dispatch(name, values):
        method, path, query, body = build_request(name, values)
        url = BASE_URL + path + ("?" + urlencode(query) if query else "")
        return await request(
            method,
            url,
            headers=headers,
            body=body,
            provider="dida",
            side_effecting=method != "GET" and name not in READ_ONLY_POST_OPERATIONS,
        )

    a = dict(arguments)
    if operation == "update_task" and "column_name" in a:
        columns = await dispatch("list_columns", {"project_id": a["project_id"]})
        column = (
            next(
                (
                    item
                    for item in columns
                    if isinstance(item, dict) and item.get("name") == a["column_name"]
                ),
                None,
            )
            if isinstance(columns, list)
            else None
        )
        if not column or not column.get("id"):
            raise IntegrationProviderError("Invalid integration operation arguments.")
        a["column_id"] = resource_identifier(column["id"])
    result = await dispatch(operation, a)
    if operation == "complete_tasks":
        if not isinstance(result, list) or any(
            not isinstance(value, str) for value in result
        ):
            raise IntegrationProviderError(
                "Integration response was unavailable.", uncertain=True
            )
        return {
            "completed": result,
            "failed": [value for value in a["task_ids"] if value not in result],
        }
    verification = None
    if operation == "update_task" and "column_id" in a:
        verification = (
            "get_task",
            {key: a[key] for key in ("project_id", "task_id")},
            "columnId",
            a["column_id"] or "",
        )
    elif operation == "update_project" and "group_id" in a:
        verification = (
            "get_project",
            {"project_id": a["project_id"]},
            "groupId",
            a["group_id"] or "",
        )
    if verification:
        name, values, field, expected = verification
        try:
            result = await dispatch(name, values)
            if not isinstance(result, dict) or (result.get(field) or "") != expected:
                raise IntegrationProviderError("Integration response was unavailable.")
        except IntegrationProviderError as exc:
            raise IntegrationProviderError(
                "Integration change could not be confirmed. Check the platform result before retrying.",
                uncertain=True,
                unauthorized=exc.unauthorized,
            ) from exc
    return result
