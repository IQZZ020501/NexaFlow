"""Canonical SKILL.md packages; all archive paths and sizes are trust boundaries."""

import base64
import binascii
import re
import stat
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

import yaml

MAX_PACKAGE_BYTES = 2 * 1024 * 1024
MAX_FILES = 64


def validate_skill_path(name: str) -> str:
    if (
        not isinstance(name, str)
        or not name
        or len(name) > 255
        or "\\" in name
        or "\0" in name
    ):
        raise ValueError("Invalid Skill file path.")
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in name.split("/"))
        or ":" in name
    ):
        raise ValueError("Skill files must use relative, normalized paths.")
    return name


def validate_skill_files(files: dict[str, str]) -> dict[str, str]:
    if len(files) > MAX_FILES:
        raise ValueError("Skill package exceeds 64 files.")
    total = 0
    for name, encoded in files.items():
        validate_skill_path(name)
        if len(encoded) > (MAX_PACKAGE_BYTES + 2) // 3 * 4:
            raise ValueError("Skill package exceeds 2 MiB.")
        try:
            total += len(base64.b64decode(encoded, validate=True))
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Skill files must be valid base64.") from exc
        if total > MAX_PACKAGE_BYTES:
            raise ValueError("Skill package exceeds 2 MiB.")
    return files


def _markdown_parts(content: bytes):
    try:
        text = content.decode("utf-8-sig").replace("\r\n", "\n")
    except UnicodeDecodeError as exc:
        raise ValueError("SKILL.md must be UTF-8.") from exc
    match = re.match(r"\A---\n(.{0,8192}?)\n---(?:\n|$)", text, flags=re.DOTALL)
    if not match:
        raise ValueError(
            "SKILL.md requires YAML frontmatter with name and description."
        )
    try:
        metadata = yaml.safe_load(match[1])
    except yaml.YAMLError as exc:
        raise ValueError("Invalid SKILL.md YAML frontmatter.") from exc
    if not isinstance(metadata, dict):
        raise ValueError("Invalid SKILL.md YAML frontmatter.")
    return metadata, text[match.end() :].strip()


def parse_skill_markdown(content: bytes):
    metadata, instructions = _markdown_parts(content)
    name = metadata.get("name")
    description = metadata.get("description")
    if (
        not isinstance(name, str)
        or not 1 <= len(name.strip()) <= 120
        or not isinstance(description, str)
        or not 1 <= len(description.strip()) <= 500
    ):
        raise ValueError("SKILL.md requires a bounded name and description.")
    if not 1 <= len(instructions) <= 12000:
        raise ValueError("Skill instructions must contain 1–12,000 characters.")
    return name.strip(), description.strip(), instructions


def canonical_skill_files(
    name: str, description: str, instructions: str, files: dict[str, str]
) -> dict[str, str]:
    """Keep SKILL.md and editable fields consistent without discarding metadata."""
    validate_skill_files(files)
    metadata = {}
    if "SKILL.md" in files:
        metadata, _ = _markdown_parts(base64.b64decode(files["SKILL.md"]))
    metadata.update(name=name, description=description)
    markdown = (
        "---\n"
        + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)
        + "---\n\n"
        + instructions.strip()
        + "\n"
    ).encode()
    parse_skill_markdown(markdown)
    return validate_skill_files(
        {**files, "SKILL.md": base64.b64encode(markdown).decode()}
    )


def inspect_skill_package(filename: str, content: bytes):
    if not content or len(content) > MAX_PACKAGE_BYTES:
        raise ValueError("Skill upload must be between 1 byte and 2 MiB.")
    if filename.lower().endswith(".md"):
        files = {"SKILL.md": base64.b64encode(content).decode()}
    elif filename.lower().endswith(".zip"):
        files = {}
        total = 0
        try:
            with ZipFile(BytesIO(content)) as archive:
                if len(archive.infolist()) > MAX_FILES + 16:
                    raise ValueError("Skill package exceeds 64 files.")
                for entry in archive.infolist():
                    name = (
                        entry.filename.rstrip("/") if entry.is_dir() else entry.filename
                    )
                    validate_skill_path(name)
                    mode = entry.external_attr >> 16
                    if (
                        stat.S_ISLNK(mode)
                        or (
                            stat.S_IFMT(mode)
                            and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))
                        )
                        or entry.flag_bits & 1
                    ):
                        raise ValueError(
                            "Skill archives cannot contain links, special files or encrypted entries."
                        )
                    if entry.is_dir():
                        continue
                    total += entry.file_size
                    if total > MAX_PACKAGE_BYTES or len(files) >= MAX_FILES:
                        raise ValueError(
                            "Skill package exceeds its size or file-count limit."
                        )
                    if name in files:
                        raise ValueError("Skill archive contains duplicate paths.")
                    with archive.open(entry) as stream:
                        data = stream.read(MAX_PACKAGE_BYTES + 1)
                    if len(data) != entry.file_size:
                        raise ValueError("Invalid Skill archive size.")
                    files[name] = base64.b64encode(data).decode()
        except (BadZipFile, RuntimeError, NotImplementedError) as exc:
            raise ValueError("Invalid Skill ZIP archive.") from exc
        roots = [
            name for name in files if name == "SKILL.md" or name.endswith("/SKILL.md")
        ]
        if len(roots) != 1:
            raise ValueError("Skill archive must contain exactly one SKILL.md.")
        prefix = roots[0][: -len("SKILL.md")]
        if any(not name.startswith(prefix) for name in files):
            raise ValueError("Skill archive contains files outside its package root.")
        files = {name[len(prefix) :]: data for name, data in files.items()}
    else:
        raise ValueError("Upload SKILL.md or a ZIP package.")
    validate_skill_files(files)
    if "SKILL.md" not in files:
        raise ValueError("Skill archive is missing SKILL.md.")
    name, description, instructions = parse_skill_markdown(
        base64.b64decode(files["SKILL.md"])
    )
    return {
        "name": name,
        "description": description,
        "definition": {"instructions": instructions, "files": files},
    }
