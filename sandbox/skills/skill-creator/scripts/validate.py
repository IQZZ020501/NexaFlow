"""Check a draft Skill's import structure without executing its scripts."""

import argparse
import json
import re
import stat
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

import yaml

MAX_BYTES = 2 * 1024 * 1024
MAX_FILES = 64


def valid_path(name):
    if (
        not name
        or len(name) > 255
        or "\\" in name
        or "\0" in name
        or ":" in name
        or PurePosixPath(name).is_absolute()
        or any(part in {"", ".", ".."} for part in name.split("/"))
    ):
        raise ValueError("Skill paths must be normalized relative paths.")


def validate(source: Path) -> dict:
    files = {}
    size = 0

    def add(name, data):
        nonlocal size
        valid_path(name)
        if name in files:
            raise ValueError("Duplicate Skill file path.")
        size += len(data)
        if len(files) >= MAX_FILES or size > MAX_BYTES:
            raise ValueError("Skill exceeds 64 files or 2 MiB expanded contents.")
        files[name] = data

    if source.is_symlink():
        raise ValueError("Skill source cannot be a link.")
    if source.is_dir():
        for item in source.rglob("*"):
            if item.is_symlink() or not (item.is_dir() or item.is_file()):
                raise ValueError("Skill cannot contain links or special files.")
            if item.is_file():
                if item.stat().st_size > MAX_BYTES:
                    raise ValueError("Skill file exceeds 2 MiB.")
                add(item.relative_to(source).as_posix(), item.read_bytes())
    elif source.suffix.lower() == ".zip":
        if source.stat().st_size > MAX_BYTES:
            raise ValueError("Skill ZIP upload exceeds 2 MiB.")
        with ZipFile(source) as archive:
            if len(archive.infolist()) > MAX_FILES + 16:
                raise ValueError("Skill ZIP contains too many entries.")
            for item in archive.infolist():
                valid_path(
                    item.filename.rstrip("/") if item.is_dir() else item.filename
                )
                mode = item.external_attr >> 16
                if (
                    item.flag_bits & 1
                    or stat.S_ISLNK(mode)
                    or (
                        stat.S_IFMT(mode)
                        and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))
                    )
                ):
                    raise ValueError(
                        "Skill ZIP contains a link, special or encrypted entry."
                    )
                if item.is_dir():
                    continue
                if item.file_size > MAX_BYTES - size:
                    raise ValueError("Skill expanded contents exceed 2 MiB.")
                with archive.open(item) as stream:
                    content = stream.read(MAX_BYTES + 1)
                if len(content) != item.file_size:
                    raise ValueError("Invalid ZIP entry size.")
                add(item.filename, content)
    elif source.suffix.lower() == ".md":
        if source.stat().st_size > MAX_BYTES:
            raise ValueError("Skill Markdown exceeds 2 MiB.")
        add("SKILL.md", source.read_bytes())
    else:
        raise ValueError("Use a Skill directory, Markdown file or ZIP.")

    roots = [name for name in files if name == "SKILL.md" or name.endswith("/SKILL.md")]
    if len(roots) != 1:
        raise ValueError("Exactly one SKILL.md is required.")
    prefix = roots[0][: -len("SKILL.md")]
    if any(not name.startswith(prefix) for name in files):
        raise ValueError("Files outside the Skill package root.")
    markdown = files[roots[0]].decode("utf-8-sig").replace("\r\n", "\n")
    match = re.match(r"\A---\n(.{0,8192}?)\n---(?:\n|$)", markdown, flags=re.DOTALL)
    if not match:
        raise ValueError("SKILL.md requires YAML frontmatter.")
    metadata = yaml.safe_load(match[1])
    if not isinstance(metadata, dict):
        raise ValueError("Skill frontmatter must be an object.")
    for key, limit in (("name", 120), ("description", 500)):
        if (
            not isinstance(metadata.get(key), str)
            or not 1 <= len(metadata[key].strip()) <= limit
        ):
            raise ValueError("Invalid bounded Skill " + key + ".")
    if not 1 <= len(markdown[match.end() :].strip()) <= 12000:
        raise ValueError("Skill body must contain 1–12,000 characters.")
    return {
        "status": "passed",
        "name": metadata["name"].strip(),
        "files": len(files),
        "expanded_bytes": size,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    print(json.dumps(validate(parser.parse_args().source), ensure_ascii=False))


if __name__ == "__main__":
    main()
