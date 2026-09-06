from base64 import urlsafe_b64encode
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import secrets

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.identity.service import issue_refresh_session
from app.entities.identity.enterprise import (
    EnterpriseIdentity,
    EnterpriseIdentityConnection,
    EnterpriseLoginState,
)
from app.entities.identity.user import User
from app.entities.workspaces.models import WorkspaceMembership
from app.infra.config.settings import Settings
from app.infra.runtime.model_utils import utc_now
from app.infra.db.repositories.identity import enterprise as identity_repository
from app.infra.db.repositories.identity import users as user_repository
from app.infra.db.repositories.workspaces import repository as workspace_repository
from app.infra.security.auth import hash_password
from app.infra.security.secrets import decrypt_secret, encrypt_secret, secret_hint
from app.infra.observability.system_log import record_system_log
from app.ports.enterprise_identity import (
    EnterpriseProviderError,
    build_authorization_url,
    resolve_external_principal,
)
from app.schemas.identity.enterprise import (
    EnterpriseConnectionResponse,
    EnterpriseConnectionUpdateRequest,
    EnterpriseIdentityResponse,
    EnterpriseProvider,
    PublicEnterpriseConnectionResponse,
    PublicEnterpriseConnectionsResponse,
)
from app.domain.audit.services import record_audit_log
from app.domain.identity.enterprise.services import safe_next_path, validate_connection_fields

LOGIN_STATE_TTL_SECONDS = 600
FEISHU_QR_STATE_PREFIX = "feishu_qr."


class EnterpriseLoginRejected(Exception):
    def __init__(self, code: str, workspace_id: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.workspace_id = workspace_id


def _digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _base_url(settings: Settings) -> str:
    return settings.public_app_url.rstrip("/")


async def _provision_enterprise_user(
    db: AsyncSession,
    connection: EnterpriseIdentityConnection,
    identity: EnterpriseIdentity,
) -> User:
    account_key = _digest(f"{connection.id}:{identity.subject_id}")[:24]
    username = f"{connection.provider}_{account_key}"
    user = await user_repository.create_user(
        db,
        User(
            username=username,
            email=f"{username}@sso.nexaflow.invalid",
            name=(identity.display_name.strip() or username)[:120],
            password_hash=hash_password(secrets.token_urlsafe(48)),
            must_change_password=False,
        ),
    )
    await user_repository.create_workspace_membership(
        db,
        WorkspaceMembership(
            workspace_id=connection.workspace_id,
            user_id=user.id,
            role="member",
        ),
    )
    identity.user_id = user.id
    identity.status = "active"
    await identity_repository.save_identity(db, identity)
    record_audit_log(
        db,
        user,
        "enterprise_identity.provision",
        "user",
        user.id,
        user.name,
        {"provider": connection.provider, "connection_id": connection.id},
        workspace_id=connection.workspace_id,
    )
    return user


def callback_url(settings: Settings, provider: str) -> str:
    return f"{_base_url(settings)}/api/v1/auth/enterprise/callback/{provider}"


def _connection_response(
    connection: EnterpriseIdentityConnection, settings: Settings
) -> EnterpriseConnectionResponse:
    return EnterpriseConnectionResponse(
        id=connection.id,
        workspace_id=connection.workspace_id,
        provider=connection.provider,  # type: ignore[arg-type]
        name=connection.name,
        client_id=connection.client_id,
        tenant_id=connection.tenant_id,
        agent_id=connection.agent_id,
        enabled=connection.enabled,
        has_client_secret=bool(connection.client_secret_ciphertext),
        client_secret_hint=connection.client_secret_hint or None,
        callback_url=callback_url(settings, connection.provider),
        login_url=f"{_base_url(settings)}/login?workspace={connection.workspace_id}",
        updated_at=connection.updated_at,
    )


async def list_connections(
    db: AsyncSession, workspace_id: str, settings: Settings
) -> list[EnterpriseConnectionResponse]:
    if await workspace_repository.get_workspace_by_id(db, workspace_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    return [
        _connection_response(item, settings)
        for item in await identity_repository.list_connections(db, workspace_id)
    ]


async def upsert_connection(
    db: AsyncSession,
    workspace_id: str,
    provider: EnterpriseProvider,
    payload: EnterpriseConnectionUpdateRequest,
    actor: User,
    settings: Settings,
) -> EnterpriseConnectionResponse:
    workspace = await workspace_repository.get_workspace_by_id(db, workspace_id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    validate_connection_fields(provider, payload.client_id, payload.tenant_id, payload.agent_id)
    submitted_tenant_id = (payload.tenant_id or "").strip()
    client_id = (
        submitted_tenant_id
        if provider == "wecom"
        else (payload.client_id or "").strip()
    )
    if not payload.name.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Name is required.")
    if payload.client_secret is not None and not payload.client_secret.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Client secret is required.")
    connection = await identity_repository.get_connection_by_provider(db, workspace_id, provider)
    creating = connection is None
    reset_identities = False
    disable_sessions = False
    if connection is None:
        if payload.client_secret is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Client secret is required.")
        connection = EnterpriseIdentityConnection(
            workspace_id=workspace_id,
            provider=provider,
            created_by_user_id=actor.id,
        )
        tenant_id = submitted_tenant_id
    else:
        tenant_id = (
            connection.tenant_id
            if provider == "feishu" and payload.tenant_id is None
            else submitted_tenant_id
        )
        if provider == "feishu" and connection.client_id != client_id:
            tenant_id = ""
        reset_identities = (
            connection.client_id != client_id
            or connection.tenant_id != tenant_id
        )
        disable_sessions = connection.enabled and not payload.enabled
    connection.name = payload.name.strip()
    connection.client_id = client_id
    connection.tenant_id = tenant_id
    connection.agent_id = (payload.agent_id or "").strip() or None
    connection.enabled = payload.enabled
    connection.updated_by_user_id = actor.id
    connection.updated_at = utc_now()
    if payload.client_secret is not None:
        connection.client_secret_ciphertext = encrypt_secret(
            payload.client_secret, settings.model_secret_key
        )
        connection.client_secret_hint = secret_hint(payload.client_secret)
    connection = await identity_repository.save_connection(db, connection)
    reset_count = (
        await identity_repository.reset_identities_for_connection(db, connection.id)
        if reset_identities
        else 0
    )
    if disable_sessions:
        await identity_repository.delete_sessions_for_connection(db, connection.id)
    record_audit_log(
        db,
        actor,
        "enterprise_identity.connection_create" if creating else "enterprise_identity.connection_update",
        "enterprise_identity_connection",
        connection.id,
        connection.name,
        {
            "provider": provider,
            "enabled": connection.enabled,
            "identity_bindings_reset": reset_count,
        },
        workspace_id=workspace_id,
    )
    await db.commit()
    return _connection_response(connection, settings)


async def list_public_connections(
    db: AsyncSession, workspace_id: str | None = None
) -> PublicEnterpriseConnectionsResponse:
    workspace_name = None
    if workspace_id is None:
        connections = await identity_repository.list_enabled_connections(db)
    else:
        workspace_name = await identity_repository.get_active_workspace_name(db, workspace_id)
        if workspace_name is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
        connections = await identity_repository.list_connections(
            db, workspace_id, enabled_only=True
        )
    return PublicEnterpriseConnectionsResponse(
        workspace_id=workspace_id,
        workspace_name=workspace_name,
        connections=[
            PublicEnterpriseConnectionResponse(
                id=item.id,
                provider=item.provider,  # type: ignore[arg-type]
                name=item.name,
                start_url=f"/api/v1/auth/enterprise/{item.id}/start",
            )
            for item in connections
        ],
    )


async def list_identities(
    db: AsyncSession, workspace_id: str
) -> list[EnterpriseIdentityResponse]:
    connections = {
        item.id: item for item in await identity_repository.list_connections(db, workspace_id)
    }
    identities = await identity_repository.list_identities(db, workspace_id)
    users = {
        user.id: user
        for user in await user_repository.list_users_by_ids(
            db, list({item.user_id for item in identities if item.user_id})
        )
    }
    return [
        EnterpriseIdentityResponse(
            id=item.id,
            connection_id=item.connection_id,
            provider=connections[item.connection_id].provider,  # type: ignore[arg-type]
            user_id=item.user_id,
            username=users[item.user_id].username if item.user_id in users else None,
            user_name=users[item.user_id].name if item.user_id in users else None,
            subject_id=item.subject_id,
            display_name=item.display_name,
            email=item.email,
            status=item.status,
            last_login_at=item.last_login_at,
            created_at=item.created_at,
        )
        for item in identities
    ]


async def bind_identity(
    db: AsyncSession,
    workspace_id: str,
    identity_id: str,
    user_id: str | None,
    actor: User,
) -> EnterpriseIdentityResponse:
    identity = await identity_repository.get_identity_by_id(db, identity_id)
    if identity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Enterprise identity not found.")
    connection = await identity_repository.get_connection_by_id(db, identity.connection_id)
    if connection is None or connection.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Enterprise identity not found.")
    user = None
    if user_id:
        member = await workspace_repository.get_workspace_member_row(db, workspace_id, user_id)
        if member is None or not member[1].is_active:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Active workspace member required.")
        user = member[1]
    if identity.user_id != (user.id if user else None):
        await user_repository.delete_refresh_sessions_for_enterprise_identity(
            db, identity.id
        )
    identity.user_id = user.id if user else None
    identity.status = "active" if user else "disabled"
    identity.updated_at = utc_now()
    try:
        identity = await identity_repository.save_identity(db, identity)
        record_audit_log(
            db,
            actor,
            "enterprise_identity.bind" if user else "enterprise_identity.unbind",
            "enterprise_identity",
            identity.id,
            identity.display_name or identity.subject_id,
            {"provider": connection.provider, "user_id": user.id if user else None},
            workspace_id=workspace_id,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This user already has an identity for the selected provider.",
        ) from exc
    return EnterpriseIdentityResponse(
        id=identity.id,
        connection_id=identity.connection_id,
        provider=connection.provider,  # type: ignore[arg-type]
        user_id=identity.user_id,
        username=user.username if user else None,
        user_name=user.name if user else None,
        subject_id=identity.subject_id,
        display_name=identity.display_name,
        email=identity.email,
        status=identity.status,
        last_login_at=identity.last_login_at,
        created_at=identity.created_at,
    )


async def begin_login(
    db: AsyncSession,
    connection_id: str,
    browser_nonce: str,
    next_path: str | None,
    settings: Settings,
    *,
    feishu_qr: bool = False,
) -> str:
    connection = await identity_repository.get_connection_by_id(db, connection_id, enabled_only=True)
    if connection is None or await identity_repository.get_active_workspace_name(
        db, connection.workspace_id
    ) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Enterprise login is not available.")
    if feishu_qr and connection.provider != "feishu":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Enterprise QR login is not available.")
    raw_state = f"{FEISHU_QR_STATE_PREFIX if feishu_qr else ''}{secrets.token_urlsafe(32)}"
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = urlsafe_b64encode(sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()
    now = utc_now()
    await identity_repository.delete_expired_login_states(db, now)
    await identity_repository.save_login_state(
        db,
        EnterpriseLoginState(
            connection_id=connection.id,
            state_hash=_digest(raw_state),
            browser_nonce_hash=_digest(browser_nonce),
            code_verifier_ciphertext=encrypt_secret(code_verifier, settings.model_secret_key),
            next_path=safe_next_path(next_path),
            expires_at=now + timedelta(seconds=LOGIN_STATE_TTL_SECONDS),
        ),
    )
    await db.commit()
    return build_authorization_url(
        connection,
        callback_url(settings, connection.provider),
        raw_state,
        code_challenge,
        feishu_qr=feishu_qr,
    )


async def complete_login(
    db: AsyncSession,
    provider: EnterpriseProvider,
    raw_state: str,
    browser_nonce: str | None,
    code: str,
    settings: Settings,
    *,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, str, str]:
    now = utc_now()
    login_state = await identity_repository.lock_login_state(db, _digest(raw_state))
    if (
        login_state is None
        or login_state.used_at is not None
        or _utc(login_state.expires_at) <= now
        or browser_nonce is None
        or not secrets.compare_digest(login_state.browser_nonce_hash, _digest(browser_nonce))
    ):
        await db.rollback()
        raise EnterpriseLoginRejected("invalid_state")
    login_state.used_at = now
    await identity_repository.save_login_state(db, login_state)
    connection = await identity_repository.get_connection_by_id(
        db, login_state.connection_id, enabled_only=True
    )
    if connection is None or connection.provider != provider:
        await db.commit()
        raise EnterpriseLoginRejected("invalid_state")
    await db.commit()
    authenticated_client_id = connection.client_id

    try:
        principal = await resolve_external_principal(
            connection,
            decrypt_secret(connection.client_secret_ciphertext, settings.model_secret_key),
            code,
            callback_url(settings, provider),
            decrypt_secret(login_state.code_verifier_ciphertext, settings.model_secret_key),
            feishu_qr=raw_state.startswith(FEISHU_QR_STATE_PREFIX),
        )
    except EnterpriseProviderError as exc:
        raise EnterpriseLoginRejected("provider_error", connection.workspace_id) from exc

    connection = await identity_repository.lock_connection_by_id(
        db, connection.id, enabled_only=True
    )
    if (
        connection is None
        or connection.provider != provider
        or connection.client_id != authenticated_client_id
    ):
        await db.rollback()
        raise EnterpriseLoginRejected("invalid_state")
    if connection.tenant_id and not secrets.compare_digest(
        principal.tenant_id, connection.tenant_id
    ):
        await db.rollback()
        raise EnterpriseLoginRejected("tenant_mismatch", connection.workspace_id)
    if not connection.tenant_id:
        if provider != "feishu":
            await db.rollback()
            raise EnterpriseLoginRejected("tenant_mismatch", connection.workspace_id)
        connection.tenant_id = principal.tenant_id
        connection.updated_at = now
        connection = await identity_repository.save_connection(db, connection)

    identity = await identity_repository.lock_identity_by_subject(
        db, connection.id, principal.subject_id
    )
    if identity is None:
        identity = EnterpriseIdentity(connection_id=connection.id, subject_id=principal.subject_id)
    identity.display_name = principal.display_name[:255]
    identity.email = principal.email[:255] if principal.email else None
    identity.last_login_at = now
    identity.updated_at = now
    try:
        identity = await identity_repository.save_identity(db, identity)
    except IntegrityError:
        await db.rollback()
        identity = await identity_repository.lock_identity_by_subject(
            db, connection.id, principal.subject_id
        )
        if identity is None:
            raise
        identity.display_name = principal.display_name[:255]
        identity.email = principal.email[:255] if principal.email else None
        identity.last_login_at = now
        identity.updated_at = now
        identity = await identity_repository.save_identity(db, identity)

    user: User | None = None
    if identity.user_id is None:
        if identity.status == "disabled":
            await db.commit()
            raise EnterpriseLoginRejected("identity_disabled", connection.workspace_id)
        user = await _provision_enterprise_user(db, connection, identity)
    if identity.user_id is None or identity.status != "active":
        await db.commit()
        raise EnterpriseLoginRejected("identity_disabled", connection.workspace_id)

    user = user or await user_repository.get_user_by_id(db, identity.user_id)
    membership = await workspace_repository.get_workspace_membership(
        db, connection.workspace_id, identity.user_id
    )
    if user is None or not user.is_active or membership is None:
        await db.commit()
        raise EnterpriseLoginRejected("access_denied", connection.workspace_id)
    refresh_token = await issue_refresh_session(
        db,
        user,
        settings,
        ip_address=ip_address,
        user_agent=user_agent,
        enterprise_identity_id=identity.id,
    )
    record_system_log(
        db,
        level="info",
        event="auth.enterprise_login_succeeded",
        message="Enterprise login succeeded.",
        path=f"/api/v1/auth/enterprise/callback/{provider}",
        method="GET",
        status_code=status.HTTP_303_SEE_OTHER,
        user_id=user.id,
        username=user.username,
        ip_address=ip_address,
        details={"connection_id": connection.id, "workspace_id": connection.workspace_id},
    )
    await db.commit()
    return refresh_token, connection.workspace_id, login_state.next_path
