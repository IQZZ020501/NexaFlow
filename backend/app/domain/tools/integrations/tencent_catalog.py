"""Explicit Tencent Meeting business tools, based on the official CLI API surface."""


def _text(maximum=256, **constraints):
    return {"type": "string", "minLength": 1, "maxLength": maximum, **constraints}


def _integer(minimum, maximum):
    return {"type": "integer", "minimum": minimum, "maximum": maximum}


def _object(properties, required=(), **constraints):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
        **constraints,
    }


def _operation(name, description, properties, required=(), *, write=False, **rules):
    return {
        "name": name,
        "description": description,
        "write": write,
        "input_schema": _object(properties, required, **rules),
    }


_ID = _text(pattern=r"^[a-zA-Z0-9_-]+$")
_TIME = _text(
    64,
    description="ISO 8601 timestamp with an explicit UTC offset, e.g. 2026-11-20T14:00:00+08:00.",
)
_MEETING = {"meeting_id": _ID}
_TIMES = {"start_time": _TIME, "end_time": _TIME}
_FILE = {"record_file_id": _ID}
_LANGUAGE = {"lang": _text(32), "password": _text(256)}


def _page(maximum=30):
    return {"page_token": _text(2048), "page_size": _integer(1, maximum)}


def _users(maximum, minimum=1):
    return {
        "type": "array",
        "items": _ID,
        "minItems": minimum,
        "maxItems": maximum,
        "uniqueItems": True,
        "description": "Tencent account open_id values, obtained from contact search or meeting participants.",
    }


_SETTINGS = _object(
    {
        "only_user_join_type": {"enum": [1, 2, 3]},
        "auto_in_waiting_room": {"type": "boolean"},
        "allow_screen_shared_watermark": {"type": "boolean"},
        "water_mark_type": {"enum": [0, 1]},
        "audio_watermark": {"type": "boolean"},
        "auto_record_type": {"enum": ["none", "local", "cloud"]},
        "auto_asr": {"type": "boolean"},
    },
    minProperties=1,
)
_RECURRING = _object(
    {
        "recurring_type": {"enum": [0, 1, 2, 3, 4]},
        "until_type": {"enum": [0, 1]},
        "until_count": _integer(1, 500),
        "until_date": _TIME,
    },
    ["recurring_type", "until_type"],
    allOf=[
        {
            "if": {"properties": {"until_type": {"const": 0}}},
            "then": {"required": ["until_date"]},
            "else": {"required": ["until_count"]},
        },
        {
            "if": {"properties": {"recurring_type": {"enum": [3, 4]}}},
            "then": {"properties": {"until_count": {"maximum": 50}}},
        },
    ],
)
_MEETING_FIELDS = {
    "subject": _text(256),
    **_TIMES,
    "password": {"type": "string", "pattern": r"^(?:[0-9]{4,6})?$"},
    "timezone": _text(128),
    "meeting_type": {"enum": [0, 1]},
    "recurring_rule": _RECURRING,
    "settings": _SETTINGS,
}
_RECURRING_REQUIRED = {
    "if": {"properties": {"meeting_type": {"const": 1}}, "required": ["meeting_type"]},
    "then": {"required": ["recurring_rule"]},
}
_RECURRING_TYPE = {
    "if": {
        "anyOf": [{"required": ["recurring_rule"]}, {"required": ["sub_meeting_id"]}]
    },
    "then": {"properties": {"meeting_type": {"const": 1}}},
}
_SEARCH = {"query": _text(50), **_TIMES, **_page()}
_SHARE = {"share_url": _text(2048, pattern=r"^https://"), **_page(5)}


TENCENT_OPERATIONS = [
    _operation(
        "list_meetings",
        "List upcoming and ongoing Tencent meetings. Follow next_page_token to read another page.",
        {
            **_page(20),
            "start_time": _TIME,
            "is_show_all_sub_meetings": {"enum": [0, 1]},
        },
    ),
    _operation(
        "get_meeting",
        "Read Tencent meeting details by meeting_id.",
        _MEETING,
        ["meeting_id"],
    ),
    _operation(
        "get_by_code",
        "Find Tencent meeting details by the displayed meeting code.",
        {"meeting_code": _text(12, pattern=r"^[0-9]{9,12}$")},
        ["meeting_code"],
    ),
    _operation(
        "list_ended",
        "List ended Tencent meetings in a time range, with pagination.",
        {**_TIMES, **_page()},
    ),
    _operation(
        "search_meetings",
        "Search Tencent meetings by subject, meeting code, or ISO 8601 time range.",
        {
            **_SEARCH,
            "meeting_code": _text(12, pattern=r"^[0-9]{9,12}$"),
            "query_field": {"enum": ["subject", "all"]},
        },
    ),
    _operation(
        "create_meeting",
        "Create a scheduled Tencent meeting. meeting_type=1 requires recurring_rule. Invitees are open_id values; this sends invitations. Times require an explicit UTC offset.",
        {**_MEETING_FIELDS, "invitees": _users(100)},
        ["subject", "start_time", "end_time"],
        write=True,
        allOf=[_RECURRING_REQUIRED, _RECURRING_TYPE],
    ),
    _operation(
        "update_meeting",
        "Update only the supplied Tencent meeting fields. Use sub_meeting_id for a single recurring occurrence; do not combine it with recurring_rule. Times require a UTC offset.",
        {**_MEETING, **_MEETING_FIELDS, "sub_meeting_id": _ID},
        ["meeting_id"],
        write=True,
        minProperties=2,
        allOf=[
            {"not": {"required": ["sub_meeting_id", "recurring_rule"]}},
            _RECURRING_TYPE,
            {
                "if": {
                    "properties": {"meeting_type": {"const": 1}},
                    "required": ["meeting_type"],
                },
                "then": {
                    "anyOf": [
                        {"required": ["recurring_rule"]},
                        {"required": ["sub_meeting_id"]},
                    ]
                },
            },
        ],
    ),
    _operation(
        "cancel_meeting",
        "Cancel a Tencent meeting. meeting_type=0 cancels a normal meeting or specified occurrence; meeting_type=1 cancels the entire recurring series.",
        {**_MEETING, "meeting_type": {"enum": [0, 1]}, "sub_meeting_id": _ID},
        ["meeting_id"],
        write=True,
        allOf=[
            {
                "if": {
                    "properties": {"meeting_type": {"const": 1}},
                    "required": ["meeting_type"],
                },
                "then": {"not": {"required": ["sub_meeting_id"]}},
            }
        ],
    ),
    _operation(
        "list_invitees",
        "List a Tencent meeting's invited members, including their roles.",
        {**_MEETING, **_page()},
        ["meeting_id"],
    ),
    _operation(
        "add_invitees",
        "Add invited Tencent meeting members using their open_id values.",
        {**_MEETING, "invitees": _users(100)},
        ["meeting_id", "invitees"],
        write=True,
    ),
    _operation(
        "remove_invitees",
        "Remove invited Tencent meeting members using their open_id values.",
        {**_MEETING, "invitees": _users(100)},
        ["meeting_id", "invitees"],
        write=True,
    ),
    _operation(
        "replace_invites",
        "Replace the entire Tencent meeting invitation list. An empty list clears all invitees.",
        {**_MEETING, "invitees": _users(100, 0)},
        ["meeting_id", "invitees"],
        write=True,
    ),
    _operation(
        "search_records",
        "List or search accessible Tencent recordings by meeting, keyword or time. Default time window is the last 30 days. Follow the returned page token.",
        {
            **_SEARCH,
            **_MEETING,
            "meeting_code": _text(12, pattern=r"^[0-9]{9,12}$"),
            "file_type": {
                "enum": ["video", "audio", "transcript", "upload", "external", "all"]
            },
            "query_field": {
                "enum": [
                    "subject",
                    "creator",
                    "transcript_content",
                    "smart_minutes",
                    "timeline",
                    "todo",
                    "all",
                ]
            },
        },
    ),
    _operation(
        "record_download",
        "Get paginated download addresses for a Tencent meeting_record_id returned by recording search. This does not download files on the server.",
        {"meeting_record_id": _ID, **_page()},
        ["meeting_record_id"],
    ),
    _operation(
        "record_minutes",
        "Read AI smart minutes for an accessible Tencent recording file.",
        {**_FILE, **_LANGUAGE},
        ["record_file_id"],
    ),
    _operation(
        "record_todos",
        "Read structured action items extracted from a Tencent recording.",
        {**_FILE, **_LANGUAGE},
        ["record_file_id"],
    ),
    _operation(
        "transcript_get",
        "Read a recording transcript. Use pid and limit for bounded paragraph reads; these are not page tokens.",
        {**_FILE, **_MEETING, "pid": _text(64), "limit": _integer(1, 100)},
        ["record_file_id"],
    ),
    _operation(
        "transcript_find",
        "Search for a keyword in a Tencent recording transcript.",
        {**_FILE, **_MEETING, "text": _text(256)},
        ["record_file_id", "text"],
    ),
    _operation(
        "transcript_part",
        "Read transcript paragraphs, speaker identifiers and timestamps for a recording.",
        {**_FILE, **_MEETING},
        ["record_file_id"],
    ),
    _operation(
        "record_timeline",
        "Read the AI timeline of a Tencent recording file.",
        {**_FILE, "lang": _text(32)},
        ["record_file_id"],
    ),
    _operation(
        "minutes_by_url",
        "Read paginated AI minutes accessible through a Tencent recording share URL.",
        {**_SHARE, **_LANGUAGE},
        ["share_url"],
    ),
    _operation(
        "transcript_url",
        "Read paginated transcripts accessible through a Tencent recording share URL.",
        _SHARE,
        ["share_url"],
    ),
    _operation(
        "participants",
        "Read Tencent meeting attendance, join/leave times and member roles, up to 100 records per page.",
        {**_MEETING, **_TIMES, **_page(100), "sub_meeting_id": _ID},
        ["meeting_id"],
    ),
    _operation(
        "waiting_log",
        "Read paginated waiting-room attendance records for a Tencent meeting.",
        {**_MEETING, **_page(100)},
        ["meeting_id"],
    ),
    _operation(
        "export_members",
        "Start an asynchronous export of Tencent attendance records. Use the returned job_id with export_result. Creates an export job.",
        {
            **_MEETING,
            **_TIMES,
            "sub_meeting_id": _ID,
            "file_type": {"enum": ["xlsx", "json"]},
        },
        ["meeting_id"],
        write=True,
    ),
    _operation(
        "export_result",
        "Read the status and download address of an attendance export job; do not restart the export while it is pending.",
        {"job_id": _ID},
        ["job_id"],
    ),
    _operation(
        "search_contacts",
        "Search the connected user's enterprise directory by username, optionally filtering department and job title. Requires enterprise permissions.",
        {"username": _text(), "job_title": _text(), "department_name": _text()},
        ["username"],
    ),
    _operation(
        "lookup_email",
        "Look up enterprise members' open_id values by email address. Read-only; requires directory permissions.",
        {
            "emails": {
                "type": "array",
                "items": _text(320),
                "minItems": 1,
                "maxItems": 50,
                "uniqueItems": True,
            }
        },
        ["emails"],
    ),
    _operation(
        "lookup_phone",
        "Look up enterprise members' open_id values by phone number. Read-only; requires directory permissions.",
        {
            "phones": {
                "type": "array",
                "items": _text(32),
                "minItems": 1,
                "maxItems": 50,
                "uniqueItems": True,
            }
        },
        ["phones"],
    ),
    _operation(
        "call_members",
        "Call up to 20 members into an ongoing Tencent meeting. Sends invitations; requires host privileges.",
        {**_MEETING, "users": _users(20)},
        ["meeting_id", "users"],
        write=True,
    ),
    _operation(
        "kick_members",
        "Remove up to 20 members from an ongoing Tencent meeting. allow_rejoin controls whether they can return. Requires host privileges.",
        {**_MEETING, "users": _users(20), "allow_rejoin": {"type": "boolean"}},
        ["meeting_id", "users"],
        write=True,
    ),
    _operation(
        "waiting_control",
        "Manage waiting-room members: enter-meeting admits them, back-to-waiting moves them out of the meeting, expel removes them. allow_rejoin applies only to expel. Requires host privileges.",
        {
            **_MEETING,
            "users": _users(20),
            "operate_type": {"enum": ["enter-meeting", "back-to-waiting", "expel"]},
            "allow_rejoin": {"type": "boolean"},
        },
        ["meeting_id", "users", "operate_type"],
        write=True,
    ),
    _operation(
        "search_minutes",
        "Search accessible Yuanbao AI meeting minutes by keyword and ISO 8601 time range. Default time window is the last year.",
        {**_SEARCH, **_page(50)},
    ),
    _operation(
        "get_minutes",
        "Read Yuanbao AI meeting minutes by minute_id or meeting_id; use sub_meeting_id for a recurring occurrence.",
        {
            **_MEETING,
            "minute_id": _ID,
            "sub_meeting_id": _ID,
            "overview": {"type": "boolean"},
            "summary_points": {"type": "boolean"},
            "todos": {"type": "boolean"},
            **_page(),
        },
        anyOf=[{"required": ["minute_id"]}, {"required": ["meeting_id"]}],
    ),
    _operation(
        "live_minutes",
        "Read paginated real-time rolling Yuanbao meeting minutes by minute_id.",
        {"minute_id": _ID, **_page(300)},
        ["minute_id"],
    ),
]
