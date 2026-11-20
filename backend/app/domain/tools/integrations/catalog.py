"""The installed capability surface is explicit and independent of credentials."""

from app.domain.tools.integrations.tencent_catalog import TENCENT_OPERATIONS

PROVIDERS = {
    "dida": {"name": "Dida365", "scopes": ["tasks:read", "tasks:write"]},
    "feishu": {
        "name": "Feishu",
        "scopes": [
            "offline_access",
            "docx:document:readonly",
            "im:message:send_as_user",
        ],
    },
    "tencent_meeting": {"name": "Tencent Meeting", "scopes": []},
}


def _string(length=256):
    return {"type": "string", "minLength": 1, "maxLength": length}


def _operation(name, description, properties, required=(), *, write=False):
    return {
        "name": name,
        "description": description,
        "write": write,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": list(required),
            "additionalProperties": False,
        },
    }


OPERATIONS = {
    "dida": [
        _operation(
            "list_projects", "List the connected user's Dida365 task lists.", {}
        ),
        _operation(
            "list_tasks",
            "Read tasks in a Dida365 list.",
            {"project_id": _string()},
            ["project_id"],
        ),
        _operation(
            "create_task",
            "Create a task in the connected user's Dida365 list. due_date uses yyyy-MM-dd'T'HH:mm:ssZ.",
            {
                "project_id": _string(),
                "title": _string(500),
                "content": _string(8000),
                "due_date": _string(64),
                "time_zone": _string(128),
            },
            ["project_id", "title"],
            write=True,
        ),
        _operation(
            "complete_task",
            "Mark a Dida365 task as completed.",
            {"project_id": _string(), "task_id": _string()},
            ["project_id", "task_id"],
            write=True,
        ),
    ],
    "feishu": [
        _operation(
            "read_document",
            "Read a Feishu cloud document accessible to the connected user.",
            {"document_id": _string()},
            ["document_id"],
        ),
        _operation(
            "send_message",
            "Send a text message to a Feishu user identified by open_id, as the connected user.",
            {"open_id": _string(), "text": _string(8000)},
            ["open_id", "text"],
            write=True,
        ),
    ],
    "tencent_meeting": TENCENT_OPERATIONS,
}
