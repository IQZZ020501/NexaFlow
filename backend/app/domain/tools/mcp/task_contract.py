"""Explicit connector lifecycle contract, frozen in the authorized tool version."""

import copy
import hashlib
import json

from app.schemas.tools.tasks import McpTaskContract

TASK_ANNOTATION = "nexaflowLongTask"
REMOTE_TERMINAL = frozenset({"succeeded", "failed", "cancelled"})


def server_binding(server):
    return hashlib.sha256(
        json.dumps(
            {
                "url": server.url,
                "transport": server.transport,
                "network_policy": server.network_policy,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()


def apply_task_contracts(discovery, contracts):
    """Remote annotations cannot opt themselves into a privileged lifecycle."""
    definitions = copy.deepcopy(discovery)
    by_name = {item.get("name"): item for item in definitions}
    unavailable = set()
    for item in definitions:
        item.pop("long_task", None)
        annotations = dict(item.get("annotations") or {})
        annotations.pop(TASK_ANNOTATION, None)
        item["annotations"] = annotations or None
    for submit, payload in contracts.items():
        if submit not in by_name:
            continue
        contract = McpTaskContract.model_validate(payload)
        controls = (contract.status_tool, contract.result_tool, contract.cancel_tool)
        if submit in controls:
            raise ValueError("Submit and control tools must be distinct.")
        if any(name not in by_name for name in controls):
            unavailable.add(submit)
            continue
        hashes = {
            name: hashlib.sha256(
                json.dumps(
                    by_name[name], sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest()
            for name in controls
        }
        by_name[submit]["long_task"] = {
            **contract.model_dump(),
            "controller_hashes": hashes,
        }
    return [item for item in definitions if item.get("name") not in unavailable]


def parse_task_status(payload, request_key, remote_id=None):
    if not isinstance(payload, dict) or payload.get("request_id") != request_key:
        raise ValueError("Remote task response does not match its request identity.")
    identity = payload.get("task_id")
    state = payload.get("status")
    if (
        not isinstance(identity, str)
        or not 1 <= len(identity) <= 512
        or any(ord(c) < 32 for c in identity)
        or (remote_id is not None and identity != remote_id)
    ):
        raise ValueError("Remote task response has an invalid task identity.")
    if state not in {"queued", "running", *REMOTE_TERMINAL}:
        raise ValueError("Remote task response has an unsupported status.")
    return identity, state
