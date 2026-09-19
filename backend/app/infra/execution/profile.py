"""Non-secret execution profile frozen with an Agent run."""

import hashlib
import hmac
import json

from app.infra.config.settings import Settings


def execution_profile(settings: Settings) -> dict:
    payload = {
        "schema_version": 1,
        "runtime": "opensandbox/dns+nft/v1",
        "image": settings.opensandbox_image,
        "egress_domains": sorted(settings.opensandbox_egress_domains),
    }
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
