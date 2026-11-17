"""Pure project path, quota and optimistic-write rules."""

from app.domain.artifacts.services import (
    MAX_ARTIFACT_BYTES,
    artifact_format_from_filename,
    artifact_workspace_path,
)

MAX_PROJECT_FILES = 64
MAX_PROJECT_BYTES = 64 * 1024 * 1024
MAX_PROJECT_HISTORY_BYTES = 256 * 1024 * 1024
MAX_PROJECT_PATHS = 256
EXCLUDED_WORK_PARTS = frozenset(
    {".git", ".venv", "venv", "node_modules", "__pycache__", ".cache", ".nexaflow"}
)


class ProjectFileConflict(ValueError):
    pass


def project_file_path(path: str, role: str) -> str:
    artifact_workspace_path(path)
    artifact_format_from_filename(path.rsplit("/", 1)[-1])
    if role not in {"source", "work"}:
        raise ValueError("Project file role must be source or work.")
    if role == "work" and any(part in EXCLUDED_WORK_PARTS for part in path.split("/")):
        raise ValueError(
            "Environments, dependency caches and Git metadata are not project files."
        )
    return path


def require_file_base(current, expected_version_id):
    if (current.id if current else None) != expected_version_id:
        raise ProjectFileConflict(
            "Project file changed; reload its latest version before writing."
        )


def validate_project_tree(files):
    active = [item for item in files if not item.deleted]
    if len(active) > MAX_PROJECT_FILES or len(files) > MAX_PROJECT_PATHS:
        raise ValueError("Project file count exceeds its limit.")
    if sum(item.size_bytes for item in active) > MAX_PROJECT_BYTES:
        raise ValueError("Project files exceed 64 MiB.")
    paths = {(item.role, item.path) for item in active}
    for item in active:
        project_file_path(item.path, item.role)
        if not 0 < item.size_bytes <= MAX_ARTIFACT_BYTES:
            raise ValueError("Each project file must be between 1 byte and 5 MiB.")
        parts = item.path.split("/")
        if any(
            (item.role, "/".join(parts[:end])) in paths for end in range(1, len(parts))
        ):
            raise ProjectFileConflict(
                "Project paths cannot be both a file and a parent directory."
            )
