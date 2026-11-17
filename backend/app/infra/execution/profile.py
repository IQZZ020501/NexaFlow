"""Non-secret execution profile frozen with an Agent run."""

import hashlib
import hmac
import json

from app.infra.config.settings import Settings


def sandbox_resource_profile(tools, skills) -> str:
    builtins = {tool.get("execution_spec", {}).get("builtin") for tool in tools}
    if builtins & {"artifact", "python_artifact", "skill", "skill_dependency_install"}:
        return "heavy"
    return "standard" if skills or builtins & {"shell", "skill_script"} else "small"


def execution_profile(settings: Settings) -> dict:
    payload = {
        "schema_version": 1,
        "runtime": "opensandbox/dns+nft/v1",
        "image": settings.opensandbox_image,
        "egress_domains": sorted(settings.opensandbox_egress_domains),
    }
    if settings.opensandbox_hosts:
        payload["schema_version"] = 2
        payload["hosts"] = sorted(
            [
                {
                    "id": host.id,
                    "url": host.url,
                    "max_sandboxes": host.max_sandboxes,
                    "memory_budget_mib": host.memory_budget_mib,
                    "cpu_budget": host.cpu_budget,
                }
                for host in settings.opensandbox_hosts
            ],
            key=lambda host: host["id"],
        )
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {**payload, "fingerprint": fingerprint}


def require_execution_profile(settings: Settings, snapshot: dict | None) -> None:
    if (
        not isinstance(snapshot, dict)
        or not hmac.compare_digest(
            str(snapshot.get("fingerprint", "")),
            execution_profile(settings)["fingerprint"],
        )
        or snapshot != execution_profile(settings)
    ):
        raise ValueError(
            "Execution image or network profile changed after run creation."
        )
