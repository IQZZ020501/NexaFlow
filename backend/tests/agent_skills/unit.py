"""Pure unit tests for the versioned Agent Skill control plane."""

import tests.support  # noqa: F401
from pydantic import ValidationError

from app.application.agents.runs.service import skill_execution_context
from app.domain.agent_skills.access import evaluate_agent_skill_access
from app.domain.agent_skills.contracts import (
    agent_skill_snapshot_from_payload,
    agent_skill_snapshot_payload,
    build_agent_skill_snapshot,
)
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
    assert "Available Skills" in skill_execution_context([restored])
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


def test_packages_and_retired_policies():
    import base64
    from io import BytesIO
    from zipfile import ZipFile

    from app.domain.agent_skills.packages import (
        canonical_skill_files,
        inspect_skill_package,
        validate_skill_files,
    )

    markdown = b"---\nname: research\ndescription: >-\n  Research with optional tools\n---\n\nRead scripts/main.py only when needed."
    package = BytesIO()
    with ZipFile(package, "w") as archive:
        archive.writestr("research/SKILL.md", markdown)
        archive.writestr("research/scripts/main.py", "print(1)")
        archive.writestr("research/assets/image.bin", bytes([0, 255]))
    draft = inspect_skill_package("research.zip", package.getvalue())
    assert draft["description"] == "Research with optional tools"
    assert set(draft["definition"]["files"]) == {
        "SKILL.md",
        "scripts/main.py",
        "assets/image.bin",
    }
    definition = AgentSkillDefinition.model_validate(draft["definition"])
    original = b"---\nname: research\ndescription: Research\nlicense: MIT\nmetadata:\n  author: Example\n---\n\nOriginal body"
    canonical = canonical_skill_files(
        "renamed",
        "Edited description",
        "Edited body",
        {
            **definition.files,
            "SKILL.md": base64.b64encode(original).decode(),
        },
    )
    markdown = base64.b64decode(canonical["SKILL.md"]).decode()
    assert "license: MIT" in markdown and "author: Example" in markdown
    assert "name: renamed" in markdown and "Edited body" in markdown
    assert canonical["assets/image.bin"] == definition.files["assets/image.bin"]
    assert definition.execution_timeout_seconds == 30
    assert (
        "budgets" not in definition.model_dump()
    )  # A bound Skill cannot clamp the entire Run.
    for policy in ("retrieval", "stop", "evaluation", "budgets"):
        try:
            AgentSkillDefinition(instructions="hello", **{policy: {}})
        except ValidationError:
            pass
        else:
            raise AssertionError("Retired RAG policy accepted")
    for path in ("../escape.py", "/absolute", "a//b", "a/./b", "C:/host", "a\\\\b"):
        try:
            validate_skill_files({path: base64.b64encode(b"one").decode()})
        except ValueError:
            pass
        else:
            raise AssertionError("Unsafe package path accepted: " + path)
    for extra in ("../escape", "other/outside", "research/../escape"):
        malicious = BytesIO()
        with ZipFile(malicious, "w") as archive:
            archive.writestr("research/SKILL.md", markdown)
            archive.writestr(extra, "evil")
        try:
            inspect_skill_package("bad.zip", malicious.getvalue())
        except ValueError:
            pass
        else:
            raise AssertionError("Unsafe archive accepted")


def test_package_input_boundaries():
    import base64
    import stat
    import warnings
    from io import BytesIO
    from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

    from app.domain.agent_skills.packages import (
        MAX_PACKAGE_BYTES,
        canonical_skill_files,
        inspect_skill_package,
        validate_skill_files,
    )

    def rejected(call):
        try:
            call()
        except ValueError:
            return
        raise AssertionError("Invalid Skill package input accepted")

    valid = (
        b"---\nname: example\ndescription: Example package\n---\n\nUse optional tools."
    )
    assert inspect_skill_package("SKILL.md", valid)["name"] == "example"
    assert "SKILL.md" in canonical_skill_files("example", "Example", "Body", {})
    for filename, content in (
        ("SKILL.md", b""),
        ("SKILL.md", b"x" * (MAX_PACKAGE_BYTES + 1)),
        ("skill.txt", valid),
        ("bad.zip", b"invalid zip"),
        ("SKILL.md", b"\xff"),
        ("SKILL.md", b"no frontmatter"),
        ("SKILL.md", b"---\nname: [invalid\n---\nBody"),
        ("SKILL.md", b"---\n- item\n---\nBody"),
        ("SKILL.md", b"---\nname: 123\ndescription: Example\n---\nBody"),
        ("SKILL.md", b"---\nname: example\ndescription: Example\n---\n"),
        ("SKILL.md", valid + b"x" * 12001),
    ):
        rejected(lambda: inspect_skill_package(filename, content))
    for files in (
        {f"file-{i}": "AA==" for i in range(65)},
        {"file": "invalid base64"},
        {"file": "A" * (4 * MAX_PACKAGE_BYTES)},
        {"first": base64.b64encode(b"x" * MAX_PACKAGE_BYTES).decode(), "last": "AA=="},
        {"\x00": "AA=="},
    ):
        rejected(lambda: validate_skill_files(files))

    for variant in (
        "missing",
        "multiple",
        "duplicate",
        "symlink",
        "fifo",
        "count",
        "oversize",
    ):
        output = BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
                if variant != "missing":
                    archive.writestr("example/SKILL.md", valid)
                if variant == "multiple":
                    archive.writestr("other/SKILL.md", valid)
                elif variant == "duplicate":
                    archive.writestr("example/SKILL.md", valid)
                elif variant in {"symlink", "fifo"}:
                    entry = ZipInfo("example/unsafe")
                    entry.external_attr = (
                        (stat.S_IFLNK if variant == "symlink" else stat.S_IFIFO) | 0o777
                    ) << 16
                    archive.writestr(entry, "unsafe")
                elif variant == "count":
                    for i in range(82):
                        archive.writestr(f"example/file-{i}", "data")
                elif variant == "oversize":
                    archive.writestr("example/large", b"x" * MAX_PACKAGE_BYTES)
        rejected(lambda: inspect_skill_package("example.zip", output.getvalue()))
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("example/", "")
        archive.writestr("example/SKILL.md", valid)
    assert inspect_skill_package("example.zip", output.getvalue())["name"] == "example"


def main() -> None:
    test_skill_definition_rejects_duplicate_resources()
    test_skill_snapshot_is_hashed_and_round_trips()
    test_skill_access_requires_use_grant_for_members()
    test_packages_and_retired_policies()
    test_package_input_boundaries()
    print("AGENT_SKILLS_UNIT_OK")


if __name__ == "__main__":
    main()
