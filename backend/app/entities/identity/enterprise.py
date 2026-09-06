from dataclasses import dataclass, field
from datetime import datetime

from app.infra.runtime.model_utils import new_id, utc_now

ENTERPRISE_IDENTITY_PROVIDERS = {"feishu", "dingtalk", "wecom"}


@dataclass
class EnterpriseIdentityConnection:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    provider: str = ""
    name: str = ""
    client_id: str = ""
    client_secret_ciphertext: str = ""
    client_secret_hint: str = ""
    tenant_id: str = ""
    agent_id: str | None = None
    enabled: bool = False
    created_by_user_id: str | None = None
    updated_by_user_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class EnterpriseIdentity:
    id: str = field(default_factory=new_id)
    connection_id: str = ""
    user_id: str | None = None
    subject_id: str = ""
    display_name: str = ""
    email: str | None = None
    status: str = "pending"
    last_login_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class EnterpriseLoginState:
    id: str = field(default_factory=new_id)
    connection_id: str = ""
    state_hash: str = ""
    browser_nonce_hash: str = ""
    code_verifier_ciphertext: str = ""
    next_path: str = "/app/apps"
    expires_at: datetime = field(default_factory=utc_now)
    used_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
