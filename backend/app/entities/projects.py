"""Private persistent project files, independent from their execution guests."""

from dataclasses import dataclass, field
from datetime import datetime

from app.entities.defaults import new_id, utc_now


@dataclass
class AgentProject:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    created_by_user_id: str = ""
    name: str = ""
    revision: int = 0
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class ProjectFileVersion:
    id: str = field(default_factory=new_id)
    project_id: str = ""
    path: str = ""
    role: str = "work"
    revision: int = 0
    previous_version_id: str | None = None
    deleted: bool = False
    content_hash: str = ""
    content: bytes = b""
    size_bytes: int = 0
    run_id: str | None = None
    invocation_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class ProjectRunState:
    run_id: str = ""
    project_id: str = ""
    file_heads: dict = field(default_factory=dict)
    dependency_locks: dict = field(default_factory=dict)
    updated_at: datetime = field(default_factory=utc_now)
