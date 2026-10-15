"""Durable ownership of a Run's private execution environment."""

from dataclasses import dataclass, field
from datetime import datetime

from app.entities.defaults import new_id, utc_now


@dataclass
class ExecutionSession:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    run_id: str = ""
    purpose: str = "run"
    owner_key: str = ""
    sandbox_id: str | None = None
    image: str = ""
    profile_fingerprint: str = ""
    state: str = "creating"
    staged_packages: list[str] = field(default_factory=list)
    environments: dict = field(default_factory=dict)
    capacity_token: str | None = None
    consumer_key: str | None = None
    holder: str | None = None
    holder_expires_at: datetime | None = None
    expires_at: datetime = field(default_factory=utc_now)
    last_used_at: datetime = field(default_factory=utc_now)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class ExecutionRun:
    deadline_at: datetime
    worker_task_id: str | None
    access_source: str
    consumer_id: str
    resource_profile: str = "standard"
