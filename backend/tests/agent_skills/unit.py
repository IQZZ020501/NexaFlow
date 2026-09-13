"""Pure unit tests for the versioned Agent Skill control plane."""

from pydantic import ValidationError

import tests.support  # noqa: F401
from app.application.agents.runs.executor import (
    _apply_skill_runtime_limits,
    _skill_evaluation_requirements,
    _skill_retrieval_stop_requirements,
)
from app.application.agents.runs.service import skill_execution_context
from app.domain.agent_skills.access import evaluate_agent_skill_access
from app.domain.agent_skills.contracts import (
    agent_skill_snapshot_from_payload,
    agent_skill_snapshot_payload,
    build_agent_skill_snapshot,
)
from app.domain.agents.access.publications import build_agent_resource_snapshot
from app.entities.agent_skills import AgentSkill, AgentSkillVersion
from app.entities.identity.user import User
from app.entities.workspaces.resource_permissions import ResourcePermission
from app.schemas.agent_skills.contracts import AgentSkillDefinition


def test_skill_definition_rejects_duplicate_resources() -> None:
    try:
        AgentSkillDefinition(
            intents=["research"],
            instructions="Use evidence.",
            knowledge_base_ids=["kb-1", "kb-1"],
        )
    except ValidationError:
        return
    raise AssertionError("duplicate Agent Skill resources were accepted")


def test_skill_snapshot_is_hashed_and_round_trips() -> None:
    definition = AgentSkillDefinition(
        intents=["research"],
        instructions="Use evidence.",
        evaluation={"require_grounding": True, "min_evidence_count": 1},
        knowledge_base_ids=["kb-1"],
    ).model_dump(mode="json")
    version = AgentSkillVersion(
        id="version-1",
        workspace_id="ws-1",
        skill_id="skill-1",
        version_number=1,
        name="Research",
        description="Evidence-backed research",
        definition_snapshot=definition,
        definition_hash="",
        published_by_user_id="owner-1",
    )
    from app.domain.agent_skills.contracts import agent_skill_definition_hash

    version.definition_hash = agent_skill_definition_hash(
        version.name, version.description, definition
    )
    snapshot = build_agent_skill_snapshot(version, "owner-1")
    restored = agent_skill_snapshot_from_payload(agent_skill_snapshot_payload(snapshot))
    assert restored == snapshot
    assert "SkillBundle policies" in skill_execution_context([restored])
    assert "Research" in skill_execution_context([restored])


def test_skill_access_requires_use_grant_for_members() -> None:
    skill = AgentSkill(
        id="skill-1",
        workspace_id="ws-1",
        created_by_user_id="owner-1",
    )
    member = User(id="member-1", username="member")
    view_grant = ResourcePermission(
        workspace_id="ws-1",
        resource_type="agent_skill",
        resource_id="skill-1",
        user_id="member-1",
        permission="view",
    )
    use_grant = ResourcePermission(
        workspace_id="ws-1",
        resource_type="agent_skill",
        resource_id="skill-1",
        user_id="member-1",
        permission="use",
    )
    assert not evaluate_agent_skill_access(skill, member, "member", view_grant).can_use
    assert evaluate_agent_skill_access(skill, member, "member", use_grant).can_use


def test_skill_runtime_policies_use_the_strictest_pinned_values() -> None:
    definition = AgentSkillDefinition(
        intents=["research"],
        instructions="Use evidence.",
        knowledge_base_ids=["kb-1"],
        retrieval={"max_calls": 2, "max_rounds": 1, "min_evidence_items": 2},
        budgets={
            "max_runtime_seconds": 30,
            "max_turns": 3,
            "max_tool_calls": 1,
            "max_model_tokens": 2000,
        },
        stop={"max_no_progress_rounds": 1},
        evaluation={"require_grounding": True, "min_evidence_count": 1},
    ).model_dump(mode="json")
    from datetime import timedelta

    from app.domain.agent_skills.contracts import agent_skill_definition_hash
    from app.entities.defaults import utc_now

    version = AgentSkillVersion(
        id="version-policy",
        workspace_id="ws-1",
        skill_id="skill-policy",
        version_number=1,
        name="Policy",
        description="",
        definition_snapshot=definition,
        published_by_user_id="owner-1",
    )
    version.definition_hash = agent_skill_definition_hash(
        version.name, version.description, definition
    )
    snapshot = build_agent_skill_snapshot(version, "owner-1")
    deadline = utc_now() + timedelta(seconds=300)
    adjusted = _apply_skill_runtime_limits(
        deadline, 8, 12, 6, 3, 2, 100_000, [snapshot]
    )
    assert adjusted[1:] == (3, 1, 1, 1, 1, 2_000)
    assert (adjusted[0] - utc_now()).total_seconds() <= 30.5
    assert _skill_evaluation_requirements([snapshot]) == (True, 2)
    assert _skill_retrieval_stop_requirements([snapshot]) == (2, False)
    resource_snapshot = build_agent_resource_snapshot([], [], [snapshot])
    assert resource_snapshot["knowledge_base_ids"] == ["kb-1"]
    assert resource_snapshot["skills"][0]["version_id"] == "version-policy"


def main() -> None:
    test_skill_definition_rejects_duplicate_resources()
    test_skill_snapshot_is_hashed_and_round_trips()
    test_skill_access_requires_use_grant_for_members()
    test_skill_runtime_policies_use_the_strictest_pinned_values()
    print("AGENT_SKILLS_UNIT_OK")


if __name__ == "__main__":
    main()
