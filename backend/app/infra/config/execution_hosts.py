"""Explicit operator-owned execution hosts; credentials never enter snapshots."""

import json
import os
import re
from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class SandboxHost:
    id: str
    url: str
    api_key: str = field(repr=False)
    max_sandboxes: int = 4
    memory_budget_mib: int = 0
    cpu_budget: int = 0


def parse_hosts(value: str) -> tuple[SandboxHost, ...]:
    if not value.strip():
        return ()
    try:
        items = json.loads(value)
        if not isinstance(items, list) or not 1 <= len(items) <= 16:
            raise ValueError
        hosts = []
        for item in items:
            if not isinstance(item, dict) or set(item) - {
                "id",
                "url",
                "api_key_env",
                "max_sandboxes",
                "memory_budget_mib",
                "cpu_budget",
            }:
                raise ValueError
            key_env = item["api_key_env"]
            if not isinstance(key_env, str) or not re.fullmatch(
                r"[A-Z][A-Z0-9_]{0,127}", key_env
            ):
                raise ValueError
            key = os.environ.get(key_env, "")
            if not key:
                raise ValueError
            if (
                not isinstance(item["id"], str)
                or not isinstance(item["url"], str)
                or any(
                    type(item.get(name, default)) is not int
                    or item.get(name, default) < minimum
                    for name, default, minimum in (
                        ("max_sandboxes", 4, 1),
                        ("memory_budget_mib", 0, 0),
                        ("cpu_budget", 0, 0),
                    )
                )
            ):
                raise ValueError
            hosts.append(
                SandboxHost(
                    id=item["id"],
                    url=item["url"].rstrip("/"),
                    api_key=key,
                    max_sandboxes=item.get("max_sandboxes", 4),
                    memory_budget_mib=item.get("memory_budget_mib", 0),
                    cpu_budget=item.get("cpu_budget", 0),
                )
            )
        return tuple(hosts)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise RuntimeError(
            "OPENSANDBOX_HOSTS must be a bounded host list with valid credential environment references."
        ) from exc


def host_settings(settings):
    for host in settings.opensandbox_hosts:
        yield replace(
            settings,
            opensandbox_host_id=host.id,
            opensandbox_url=host.url,
            opensandbox_api_key=host.api_key,
            opensandbox_max_sandboxes=host.max_sandboxes,
            opensandbox_memory_budget_mib=host.memory_budget_mib,
            opensandbox_cpu_budget=host.cpu_budget,
            opensandbox_warm_pool_size=0,
        )
