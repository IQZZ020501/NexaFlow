"""The installed capability surface is explicit and independent of credentials."""

from app.domain.tools.integrations.dida_catalog import DIDA_OPERATIONS
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
    "dida": DIDA_OPERATIONS,
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
