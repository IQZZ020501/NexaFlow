"""DIDA CLI 0.1.16 business capabilities, exposed through the personal integration."""


def _text(maximum=256, *, empty=False, **rules):
    return {
        "type": "string",
        "minLength": 0 if empty else 1,
        "maxLength": maximum,
        **rules,
    }


def _integer(minimum=0, maximum=9007199254740991):
    return {"type": "integer", "minimum": minimum, "maximum": maximum}


def _array(item, maximum=100, *, minimum=0):
    return {"type": "array", "items": item, "minItems": minimum, "maxItems": maximum}


def _object(properties, required=(), **rules):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
        **rules,
    }


def _operation(
    name, command, description, properties=None, required=(), *, write=False, **rules
):
    return {
        "name": name,
        "description": f"{description} DIDA CLI: dida {command}.",
        "write": write,
        "input_schema": _object(properties or {}, required, **rules),
    }


_ID = _text(pattern=r"^[a-zA-Z0-9_-]+$")
_CLEAR_ID = {
    **_text(empty=True, pattern=r"^[a-zA-Z0-9_-]*$"),
    "type": ["string", "null"],
    "description": "An existing ID; null or an empty string requests removal of the association.",
}
_TIME = _text(
    64,
    pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})$",
    description="ISO 8601 time with an explicit offset, e.g. 2026-11-20T14:00:00+08:00.",
)
_STAMP = {
    **_integer(19000101, 29991231),
    "description": "Calendar date as YYYYMMDD, e.g. 20261120.",
}
_ORDER = _integer(-9007199254740991)
_BOOL = {"type": "boolean"}
_NUMBER = {"type": "number"}
_PRIORITY = {"type": "integer", "enum": [0, 1, 3, 5]}
_STATUS = {"type": "integer", "enum": [-1, 0, 2]}
_TASK_KIND = {"type": "string", "enum": ["TEXT", "NOTE", "CHECKLIST"]}
_PROJECT = {"project_id": _ID}
_TASK = {**_PROJECT, "task_id": _ID}
_NAME = {"name": _text(500)}
_CHECKLIST = _object(
    {
        "id": _ID,
        "title": _text(500),
        "status": {"type": "integer", "enum": [0, 1]},
        "completed_time": _TIME,
        "is_all_day": _BOOL,
        "sort_order": _ORDER,
        "start_date": _TIME,
        "time_zone": _text(128),
    },
    ["title"],
)
_TASK_FIELDS = {
    **_PROJECT,
    "title": _text(500),
    "parent_id": _CLEAR_ID,
    "content": _text(8000, empty=True),
    "desc": _text(8000, empty=True),
    "is_all_day": _BOOL,
    "start_date": _TIME,
    "due_date": _TIME,
    "time_zone": _text(128),
    "reminders": _array(_text(256)),
    "repeat_flag": _text(2048, empty=True),
    "repeat_from": {"type": "string", "enum": ["0", "1", "2"]},
    "priority": _PRIORITY,
    "sort_order": _ORDER,
    "items": _array(_CHECKLIST, 500),
    "tags": _array(_text()),
}
_PROJECT_FIELDS = {
    **_NAME,
    "color": _text(64),
    "sort_order": _ORDER,
    "view_mode": {"type": "string", "enum": ["list", "kanban", "timeline"]},
    "kind": {"type": "string", "enum": ["TASK", "NOTE"]},
}
_FILTER = {"project_ids": _array(_ID), "start_date": _TIME, "end_date": _TIME}
_TAG_FIELDS = {
    "name": _text(),
    "color": _text(64, empty=True),
    "sort_order": _ORDER,
    "sort_type": _text(),
    "parent": _text(empty=True),
}
_FOCUS_TYPE = {
    "type": "integer",
    "enum": [0, 1],
    "description": "0: pomodoro; 1: timing.",
}
_FOCUS_BRIEF = _object(
    {
        "task_id": _ID,
        "title": _text(500),
        "habit_id": _ID,
        "timer_id": _ID,
        "timer_name": _text(500),
        "project_name": _text(500),
        "tags": _array(_text()),
        "start_time": _TIME,
        "end_time": _TIME,
    }
)
_FOCUS_FIELDS = {
    "type": _FOCUS_TYPE,
    "task_id": _ID,
    "note": _text(5000, empty=True),
    "tasks": _array(_FOCUS_BRIEF, 1),
    "status": _integer(),
    "start_time": _TIME,
    "end_time": _TIME,
    "pause_duration": _integer(),
    "adjust_time": _ORDER,
    "added": _BOOL,
}
_HABIT_FIELDS = {
    **_NAME,
    "icon_res": _text(),
    "color": _text(64),
    "sort_order": _ORDER,
    "status": _integer(),
    "encouragement": _text(2000, empty=True),
    "type": _text(),
    "goal": _NUMBER,
    "step": _NUMBER,
    "unit": _text(),
    "repeat_rule": _text(2048),
    "reminders": _array(_text(256)),
    "record_enable": _BOOL,
    "section_id": _ID,
    "target_days": _integer(),
    "target_start_date": _STAMP,
    "completed_cycles": _integer(),
    "ex_dates": _array(_text(8, pattern=r"^\d{8}$"), 366),
    "style": _integer(),
}

DIDA_OPERATIONS = [
    _operation(
        "get_preference",
        "preference get",
        "Read the connected user's time zone and preferences.",
    ),
    _operation("get_task", "task get", "Read a task.", _TASK, _TASK),
    _operation(
        "create_task",
        "task create",
        "Create a task with dates, priority, recurrence, checklist items and tags.",
        _TASK_FIELDS,
        ["project_id", "title"],
        write=True,
    ),
    _operation(
        "update_task",
        "task update",
        "Update only supplied task fields. Null dates clear them; empty arrays clear tags/reminders. Use list_columns to find column IDs.",
        {
            **_TASK_FIELDS,
            "task_id": _ID,
            "column_id": _CLEAR_ID,
            "column_name": _text(500),
            "kind": _TASK_KIND,
            "start_date": {**_TIME, "type": ["string", "null"]},
            "due_date": {**_TIME, "type": ["string", "null"]},
            "focus_summaries": _array(
                _object(
                    {
                        "estimated_pomo": _integer(0, 60),
                        "estimated_duration": _integer(),
                    },
                    minProperties=1,
                ),
                1,
            ),
            "status": _STATUS,
            "completed_time": _TIME,
        },
        _TASK,
        write=True,
        minProperties=3,
    ),
    _operation(
        "complete_task",
        "task complete",
        "Mark a task completed.",
        _TASK,
        _TASK,
        write=True,
    ),
    _operation(
        "complete_tasks",
        "task complete-batch",
        "Complete at most 50 tasks in one list; omitted project_id means inbox. Returns completed and failed IDs; do not repeat successful IDs.",
        {**_PROJECT, "task_ids": _array(_ID, 50, minimum=1)},
        ["task_ids"],
        write=True,
    ),
    _operation(
        "delete_task", "task delete", "Delete a task.", _TASK, _TASK, write=True
    ),
    _operation(
        "move_tasks",
        "task move",
        "Move tasks between lists.",
        {
            "moves": _array(
                _object(
                    {"from_project_id": _ID, "to_project_id": _ID, "task_id": _ID},
                    ["from_project_id", "to_project_id", "task_id"],
                ),
                minimum=1,
            )
        },
        ["moves"],
        write=True,
    ),
    _operation(
        "assign_task",
        "task assign",
        "Assign a task to a username returned by list_project_members.",
        {**_TASK, "assignee_username": _text()},
        [*_TASK, "assignee_username"],
        write=True,
    ),
    _operation(
        "unassign_task",
        "task unassign",
        "Remove a task's assignee.",
        _TASK,
        _TASK,
        write=True,
    ),
    _operation(
        "list_completed_tasks",
        "task completed",
        "Read completed tasks, optionally filtered by list and date range.",
        _FILTER,
    ),
    _operation(
        "filter_tasks",
        "task filter",
        "Filter tasks by list, due date, priority, tags, kind or status.",
        {
            **_FILTER,
            "priority": _array(_PRIORITY, 4, minimum=1),
            "tag": _array(_text()),
            "kind": _array(_TASK_KIND, 3, minimum=1),
            "status": _array(_STATUS, 3, minimum=1),
        },
    ),
    _operation(
        "search_tasks",
        "task search",
        "Search tasks by keywords, lists, tags, status and due date range.",
        {
            "keywords": _text(2000),
            "project_ids": _array(_ID),
            "tags": _array(_text()),
            "status": _array(_STATUS, 3, minimum=1),
            "due_from": _TIME,
            "due_to": _TIME,
        },
    ),
    _operation(
        "list_task_comments", "task comment list", "Read task comments.", _TASK, _TASK
    ),
    _operation(
        "add_task_comment",
        "task comment add",
        "Add a task comment.",
        {**_TASK, "title": _text(8000)},
        [*_TASK, "title"],
        write=True,
    ),
    _operation(
        "delete_task_comment",
        "task comment delete",
        "Delete a task comment.",
        {**_TASK, "comment_id": _ID},
        [*_TASK, "comment_id"],
        write=True,
    ),
    _operation(
        "list_projects", "project list", "List the connected user's task lists."
    ),
    _operation(
        "get_project", "project get", "Read task list details.", _PROJECT, _PROJECT
    ),
    _operation(
        "get_project_data",
        "project data",
        "Read a task list with its unfinished tasks and columns.",
        _PROJECT,
        _PROJECT,
    ),
    _operation(
        "list_project_members",
        "project members",
        "Read list members and usernames for assigning tasks.",
        _PROJECT,
        _PROJECT,
    ),
    _operation(
        "create_project",
        "project create",
        "Create a task list.",
        _PROJECT_FIELDS,
        ["name"],
        write=True,
    ),
    _operation(
        "update_project",
        "project update",
        "Update supplied list fields; closed archives or reopens a list. Use list_project_groups to find folder IDs.",
        {**_PROJECT_FIELDS, **_PROJECT, "group_id": _CLEAR_ID, "closed": _BOOL},
        _PROJECT,
        write=True,
        minProperties=2,
    ),
    _operation(
        "delete_project",
        "project delete",
        "Delete a task list.",
        _PROJECT,
        _PROJECT,
        write=True,
    ),
    _operation("list_project_groups", "project group list", "List task list folders."),
    _operation(
        "create_project_group",
        "project group create",
        "Create a task list folder.",
        _NAME,
        _NAME,
        write=True,
    ),
    _operation(
        "update_project_group",
        "project group update",
        "Rename a task list folder.",
        {"group_id": _ID, **_NAME},
        ["group_id", "name"],
        write=True,
    ),
    _operation(
        "delete_project_group",
        "project group delete",
        "Delete a task list folder.",
        {"group_id": _ID},
        ["group_id"],
        write=True,
    ),
    _operation(
        "list_columns",
        "project column list",
        "List columns in a task list.",
        _PROJECT,
        _PROJECT,
    ),
    _operation(
        "create_column",
        "project column create",
        "Create a column in a task list.",
        {**_PROJECT, **_NAME},
        [*_PROJECT, "name"],
        write=True,
    ),
    _operation(
        "update_column",
        "project column update",
        "Rename a column.",
        {**_PROJECT, "column_id": _ID, **_NAME},
        [*_PROJECT, "column_id", "name"],
        write=True,
    ),
    _operation("list_tags", "tag list", "Read tags."),
    _operation(
        "create_tag",
        "tag create",
        "Create a tag.",
        {**_TAG_FIELDS, "label": _text()},
        ["name", "label"],
        write=True,
    ),
    _operation(
        "update_tag",
        "tag update",
        "Update supplied tag fields.",
        {**_TAG_FIELDS, "type": _integer()},
        ["name"],
        write=True,
        minProperties=2,
    ),
    _operation(
        "rename_tag",
        "tag rename",
        "Rename a tag. scope 0 includes all accessible tasks; 1 excludes shared lists.",
        {
            "name": _text(),
            "new_name": _text(),
            "scope": {"type": "integer", "enum": [0, 1]},
        },
        ["name", "new_name"],
        write=True,
    ),
    _operation(
        "delete_tag",
        "tag delete",
        "Delete a tag association. scope 0 includes all accessible tasks; 1 excludes shared lists.",
        {"name": _text(), "scope": {"type": "integer", "enum": [0, 1]}},
        ["name"],
        write=True,
    ),
    _operation(
        "get_focus",
        "focus get",
        "Read a focus record.",
        {"focus_id": _ID, "type": _FOCUS_TYPE},
        ["focus_id", "type"],
    ),
    _operation(
        "list_focus",
        "focus list",
        "Read focus records in a range of at most 30 days.",
        {"from": _TIME, "to": _TIME, "type": _FOCUS_TYPE},
        ["from", "to", "type"],
    ),
    _operation(
        "create_focus",
        "focus create",
        "Create a focus record; durations are seconds.",
        {**_FOCUS_FIELDS, "duration": _integer(), "relation_type": _array(_integer())},
        ["type", "start_time", "end_time"],
        write=True,
    ),
    _operation(
        "update_focus",
        "focus update",
        "Update only supplied focus fields; durations are seconds.",
        {**_FOCUS_FIELDS, "focus_id": _ID},
        ["focus_id", "type"],
        write=True,
        minProperties=3,
    ),
    _operation(
        "delete_focus",
        "focus delete",
        "Delete a focus record.",
        {"focus_id": _ID, "type": _FOCUS_TYPE},
        ["focus_id", "type"],
        write=True,
    ),
    _operation(
        "get_habit", "habit get", "Read a habit.", {"habit_id": _ID}, ["habit_id"]
    ),
    _operation("list_habit_sections", "habit section list", "Read habit sections."),
    _operation("list_habits", "habit list", "Read habits."),
    _operation(
        "create_habit",
        "habit create",
        "Create a habit with goals, recurrence, reminders and recording settings.",
        _HABIT_FIELDS,
        ["name"],
        write=True,
    ),
    _operation(
        "update_habit",
        "habit update",
        "Update only supplied habit fields.",
        {**_HABIT_FIELDS, "habit_id": _ID},
        ["habit_id"],
        write=True,
        minProperties=2,
    ),
    _operation(
        "create_habit_checkin",
        "habit checkin",
        "Create or update a daily habit check-in.",
        {
            "habit_id": _ID,
            "stamp": _STAMP,
            "time": _TIME,
            "op_time": _TIME,
            "value": _NUMBER,
            "goal": _NUMBER,
            "status": _integer(),
        },
        ["habit_id", "stamp"],
        write=True,
    ),
    _operation(
        "list_habit_checkins",
        "habit checkins",
        "Read habit check-ins by date range.",
        {"habit_ids": _array(_ID, minimum=1), "from": _STAMP, "to": _STAMP},
        ["habit_ids", "from", "to"],
    ),
    _operation(
        "list_calendar_accounts",
        "calendar account list",
        "Read connected third-party calendar accounts.",
    ),
    _operation(
        "query_calendar_events",
        "calendar event query",
        "Read calendar events. Omit filters for all accounts over the server's default next three months. An explicit range may span at most three months; preserve partial status and account errors.",
        {"account_id": _text(), "begin": _TIME, "end": _TIME},
    ),
    _operation(
        "list_countdowns", "countdown list", "Read countdowns and anniversaries."
    ),
]
