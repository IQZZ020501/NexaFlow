"""Pin project-authored Skill instructions into immutable Tool definitions."""

from pathlib import Path

BUILTIN_GUIDE_NAMES = frozenset(
    {"documents", "pdf", "pptx", "spreadsheets", "skill-creator"}
)


def skill_instructions(skill_name: str) -> str:
    if skill_name not in BUILTIN_GUIDE_NAMES:
        raise ValueError("Unknown built-in Skill guide.")
    # The business image needs only Markdown; executable helpers stay in the guest.
    packaged = Path(__file__).with_name("guides") / skill_name / "SKILL.md"
    source = (
        Path(__file__).resolve().parents[5] / "sandbox/skills" / skill_name / "SKILL.md"
    )
    instructions = (packaged if packaged.is_file() else source).read_text(
        encoding="utf-8"
    )
    if not instructions.strip() or len(instructions.encode("utf-8")) > 16_000:
        raise ValueError("Built-in Skill instructions are empty or too large.")
    return instructions
