"""Bounded file-tree imports; archives are data, never installation instructions."""

import stat
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile
from zlib import error as ZlibError

from app.domain.artifacts.services import MAX_ARTIFACT_BYTES, artifact_workspace_path
from app.domain.projects.services import (
    EXCLUDED_WORK_PARTS,
    MAX_PROJECT_BYTES,
    MAX_PROJECT_FILES,
    project_file_path,
)

IGNORED_IMPORT_PARTS = EXCLUDED_WORK_PARTS | {"__MACOSX", ".DS_Store"}


def upload_file_path(path: str) -> str:
    artifact_workspace_path(path)
    if len(path) > 255:
        raise ValueError("Uploaded file path exceeds 255 characters.")
    return project_file_path(path, "work")


def ignored_import_path(path: str) -> bool:
    return any(part in IGNORED_IMPORT_PARTS for part in path.split("/"))


def import_file_tree(uploads: list[tuple[str, bytes]]) -> list[dict]:
    """Expand ZIP entries in memory with the same quotas as the saved work tree."""
    files = {}
    total = 0

    def add(path, content):
        nonlocal total
        project_file_path(path, "work")
        if path in files:
            raise ValueError("Uploaded files contain duplicate paths.")
        if len(content) > MAX_ARTIFACT_BYTES:
            raise ValueError("Each conversation file must not exceed 5 MiB.")
        total += len(content)
        if len(files) >= MAX_PROJECT_FILES or total > MAX_PROJECT_BYTES:
            raise ValueError("Conversation files exceed 64 files or 64 MiB.")
        files[path] = {"path": path, "content": content}

    for filename, content in uploads:
        upload_file_path(filename)
        if "/" in filename or PurePosixPath(filename).suffix.lower() != ".zip":
            add(filename, content)
            continue
        try:
            with ZipFile(BytesIO(content)) as archive:
                entries = archive.infolist()
                if len(entries) > 4096:
                    raise ValueError("ZIP archive contains too many entries.")
                for entry in entries:
                    path = (
                        entry.filename.rstrip("/") if entry.is_dir() else entry.filename
                    )
                    artifact_workspace_path(path)
                    kind = stat.S_IFMT(entry.external_attr >> 16)
                    if (
                        kind not in {0, stat.S_IFREG, stat.S_IFDIR}
                        or entry.flag_bits & 1
                    ):
                        raise ValueError(
                            "ZIP archive contains links, special files or encrypted entries."
                        )
                    if ignored_import_path(path) or entry.is_dir():
                        continue
                    if not 0 <= entry.file_size <= MAX_ARTIFACT_BYTES:
                        raise ValueError(
                            "Each conversation file must not exceed 5 MiB."
                        )
                    if total + entry.file_size > MAX_PROJECT_BYTES:
                        raise ValueError(
                            "Conversation files exceed 64 files or 64 MiB."
                        )
                    with archive.open(entry) as stream:
                        extracted = stream.read(MAX_ARTIFACT_BYTES + 1)
                    if len(extracted) != entry.file_size:
                        raise ValueError("ZIP archive entry size is invalid.")
                    add(path, extracted)
        except (
            BadZipFile,
            RuntimeError,
            NotImplementedError,
            EOFError,
            ZlibError,
        ) as exc:
            raise ValueError("ZIP archive is invalid or unsupported.") from exc
    if not files:
        raise ValueError("No usable files were found in the upload.")
    paths = set(files)
    for path in paths:
        parts = path.split("/")
        if any("/".join(parts[:end]) in paths for end in range(1, len(parts))):
            raise ValueError("Uploaded paths cannot be both a file and a directory.")
    return list(files.values())
