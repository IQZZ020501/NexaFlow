"""The same safe mount identity is used in Skill guidance and execution."""

import hashlib
import re


def skill_mount_name(name: str, version_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].rstrip("-") or "skill"
    return f"{slug}-{hashlib.sha256(version_id.encode()).hexdigest()[:16]}"
