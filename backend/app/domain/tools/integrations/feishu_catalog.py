"""Small discovery surface over the frozen official Feishu CLI API directory."""

FEISHU_CATALOG_REVISION = "lark-cli-1.0.100-c5fbf1a-1"


def _tool(name, description, properties, required=(), *, write=False):
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


_OPERATION = {"type": "string", "minLength": 1, "maxLength": 128}
FEISHU_OPERATIONS = [
    _tool(
        "list_operations",
        "Find official Feishu CLI operations by domain or English keywords. Covers messaging, mail, calendar, docs, sheets, Base, slides, whiteboard, wiki, drive, minutes, meetings, tasks, approval, attendance, contact and OKR. Inspect the operation before executing it; each call reads one page.",
        {
            "domain": {"type": "string", "maxLength": 32},
            "query": {"type": "string", "maxLength": 256},
            "offset": {"type": "integer", "minimum": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
    ),
    _tool(
        "describe_operation",
        "Read a Feishu operation's exact params_schema and body_schema, read/write effect and required platform scopes before using read_api or write_api. Resource IDs and pagination fields go in params; JSON request content goes in body. All calls use the connected user's identity.",
        {"operation": _OPERATION},
        ["operation"],
    ),
    *[
        _tool(
            name,
            description,
            {
                "operation": _OPERATION,
                "params": {"type": "object"},
                "body": {"type": "object"},
            },
            ["operation"],
            write=write,
        )
        for name, write, description in (
            (
                "read_api",
                False,
                "Execute an inspected read-only Feishu CLI operation, including read-only POST queries. Use its exact params_schema and body_schema. Writes are rejected. Pagination is explicit; no automatic full-account export.",
            ),
            (
                "write_api",
                True,
                "Execute an inspected Feishu CLI write operation as the connected user. Confirm the requested action and target first. Use its exact params_schema and body_schema. Creates, updates, sends, deletes, approvals and permission changes follow the conversation's approval mode. Never repeat an uncertain write.",
            ),
        )
    ],
]
