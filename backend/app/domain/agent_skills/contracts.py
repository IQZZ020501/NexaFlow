from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from app.entities.agent_skills import AgentSkillSnapshot, AgentSkillVersion

AGENT_SKILL_SCHEMA_VERSION = 2


def agent_skill_definition_hash(
    name: str,
    description: str,
    definition: dict[str, Any],
) -> str:
    encoded = json.dumps(
        {
            "schema_version": AGENT_SKILL_SCHEMA_VERSION,
            "name": name,
            "description": description,
            "definition": definition,
        },
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_agent_skill_version(version: AgentSkillVersion) -> None:
    if version.schema_version != AGENT_SKILL_SCHEMA_VERSION:
        raise ValueError("Agent Skill version schema is unsupported.")
    expected = agent_skill_definition_hash(
        version.name,
        version.description,
        version.definition_snapshot,
    )
    if not hmac.compare_digest(expected, version.definition_hash):
        raise ValueError("Agent Skill version is invalid.")


def build_agent_skill_snapshot(
    version: AgentSkillVersion,
    bound_by_user_id: str,
) -> AgentSkillSnapshot:
    validate_agent_skill_version(version)
    return AgentSkillSnapshot(
        schema_version=version.schema_version,
        skill_id=version.skill_id,
        version_id=version.id,
        version_number=version.version_number,
        name=version.name,
        description=version.description,
        definition=version.definition_snapshot,
        definition_hash=version.definition_hash,
        bound_by_user_id=bound_by_user_id,
    )


def agent_skill_snapshot_payload(snapshot: AgentSkillSnapshot) -> dict[str, Any]:
    return {
        "schema_version": snapshot.schema_version,
        "skill_id": snapshot.skill_id,
        "version_id": snapshot.version_id,
        "version_number": snapshot.version_number,
        "name": snapshot.name,
        "description": snapshot.description,
        "definition": snapshot.definition,
        "definition_hash": snapshot.definition_hash,
        "bound_by_user_id": snapshot.bound_by_user_id,
    }


def agent_skill_snapshot_from_payload(payload: dict[str, Any]) -> AgentSkillSnapshot:
    try:
        snapshot = AgentSkillSnapshot(
            schema_version=int(payload["schema_version"]),
            skill_id=str(payload["skill_id"]),
            version_id=str(payload["version_id"]),
            version_number=int(payload["version_number"]),
            name=str(payload["name"]),
            description=str(payload.get("description", "")),
            definition=dict(payload["definition"]),
            definition_hash=str(payload["definition_hash"]),
            bound_by_user_id=str(payload["bound_by_user_id"]),
        )
        validate_agent_skill_version(
            AgentSkillVersion(
                id=snapshot.version_id,
                skill_id=snapshot.skill_id,
                version_number=snapshot.version_number,
                schema_version=snapshot.schema_version,
                name=snapshot.name,
                description=snapshot.description,
                definition_snapshot=snapshot.definition,
                definition_hash=snapshot.definition_hash,
            )
        )
        return snapshot
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Agent Skill snapshot is invalid.") from exc


__all__ = [
    "AGENT_SKILL_SCHEMA_VERSION",
    "agent_skill_definition_hash",
    "agent_skill_snapshot_from_payload",
    "agent_skill_snapshot_payload",
    "build_agent_skill_snapshot",
    "validate_agent_skill_version",
]
