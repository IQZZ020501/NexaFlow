import secrets
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_settings, require_global_admin
from app.api.v1.endpoints.auth import get_request_ip, set_refresh_cookie
from app.application.enterprise_identity import (
    EnterpriseLoginRejected,
    begin_login,
    bind_identity,
    complete_login,
    list_connections,
    list_identities,
    list_public_connections,
    upsert_connection,
)
from app.entities.user import User
from app.infrastructure.config import Settings
from app.infrastructure.enterprise_login_rate_limit import (
    EnterpriseLoginRateLimitExceeded,
    EnterpriseLoginRateLimitUnavailable,
    enforce_enterprise_login_rate_limit,
)
from app.infrastructure.session import get_db
from app.schemas.enterprise_identity import (
    EnterpriseConnectionResponse,
    EnterpriseConnectionUpdateRequest,
    EnterpriseIdentityBindingRequest,
    EnterpriseIdentityResponse,
    EnterpriseProvider,
    EnterpriseQrLoginResponse,
    PublicEnterpriseConnectionsResponse,
)

public_router = APIRouter(prefix="/auth/enterprise", tags=["enterprise identity"])
admin_router = APIRouter(prefix="/enterprise-identity", tags=["enterprise identity"])
SSO_NONCE_COOKIE = "nexaflow_sso_nonce"
SSO_COOKIE_PATH = "/api/v1/auth/enterprise"


def _set_nonce_cookie(response: Response, nonce: str, settings: Settings) -> None:
    response.set_cookie(
        SSO_NONCE_COOKIE,
        nonce,
        max_age=600,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        path=SSO_COOKIE_PATH,
    )


def _clear_nonce_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        SSO_NONCE_COOKIE,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        path=SSO_COOKIE_PATH,
    )


def _login_error_redirect(
    settings: Settings, error: str, workspace_id: str | None
) -> RedirectResponse:
    query = urlencode(
        {key: value for key, value in {"error": error, "workspace": workspace_id}.items() if value}
    )
    response = RedirectResponse(
        f"{settings.public_app_url.rstrip('/')}/login?{query}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    _clear_nonce_cookie(response, settings)
    return response


async def _enforce_rate_limit(request: Request, settings: Settings) -> None:
    try:
        await enforce_enterprise_login_rate_limit(settings, get_request_ip(request))
    except EnterpriseLoginRateLimitExceeded as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many enterprise login attempts.",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except EnterpriseLoginRateLimitUnavailable as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Enterprise login rate limiter is unavailable.",
        ) from exc


@public_router.get("/connections", response_model=PublicEnterpriseConnectionsResponse)
async def read_public_connections(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
) -> PublicEnterpriseConnectionsResponse:
    return await list_public_connections(db, workspace_id)


@public_router.get("/{connection_id}/start")
async def start_enterprise_login(
    connection_id: str,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
    next_path: Annotated[str | None, Query(alias="next", max_length=2048)] = None,
    nonce: Annotated[str | None, Cookie(alias=SSO_NONCE_COOKIE)] = None,
) -> RedirectResponse:
    await _enforce_rate_limit(request, settings)
    browser_nonce = nonce or secrets.token_urlsafe(32)
    destination = await begin_login(db, connection_id, browser_nonce, next_path, settings)
    response = RedirectResponse(destination, status_code=status.HTTP_302_FOUND)
    _set_nonce_cookie(response, browser_nonce, settings)
    return response


@public_router.post("/{connection_id}/qr", response_model=EnterpriseQrLoginResponse)
async def prepare_enterprise_qr_login(
    connection_id: str,
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
    next_path: Annotated[str | None, Query(alias="next", max_length=2048)] = None,
    nonce: Annotated[str | None, Cookie(alias=SSO_NONCE_COOKIE)] = None,
) -> EnterpriseQrLoginResponse:
    await _enforce_rate_limit(request, settings)
    browser_nonce = nonce or secrets.token_urlsafe(32)
    authorization_url = await begin_login(
        db,
        connection_id,
        browser_nonce,
        next_path,
        settings,
        feishu_qr=True,
    )
    _set_nonce_cookie(response, browser_nonce, settings)
    return EnterpriseQrLoginResponse(authorization_url=authorization_url)


@public_router.get("/callback/{provider}")
async def finish_enterprise_login(
    provider: EnterpriseProvider,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
    state_value: Annotated[str, Query(alias="state", min_length=20, max_length=255)],
    code: Annotated[str | None, Query(min_length=1, max_length=4096)] = None,
    auth_code: Annotated[str | None, Query(alias="authCode", min_length=1, max_length=4096)] = None,
    nonce: Annotated[str | None, Cookie(alias=SSO_NONCE_COOKIE)] = None,
) -> RedirectResponse:
    authorization_code = auth_code if provider == "dingtalk" else code
    if not authorization_code:
        return _login_error_redirect(settings, "provider_error", None)
    try:
        refresh_token, workspace_id, next_path = await complete_login(
            db,
            provider,
            state_value,
            nonce,
            authorization_code,
            settings,
            ip_address=get_request_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except EnterpriseLoginRejected as exc:
        return _login_error_redirect(settings, exc.code, exc.workspace_id)
    query = urlencode({"workspace": workspace_id, "next": next_path})
    response = RedirectResponse(
        f"{settings.public_app_url.rstrip('/')}/auth/complete?{query}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    set_refresh_cookie(response, refresh_token, settings)
    _clear_nonce_cookie(response, settings)
    return response


@admin_router.get(
    "/workspaces/{workspace_id}/connections",
    response_model=list[EnterpriseConnectionResponse],
)
async def read_connections(
    workspace_id: str,
    _: Annotated[User, Depends(require_global_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[EnterpriseConnectionResponse]:
    return await list_connections(db, workspace_id, settings)


@admin_router.put(
    "/workspaces/{workspace_id}/connections/{provider}",
    response_model=EnterpriseConnectionResponse,
)
async def write_connection(
    workspace_id: str,
    provider: EnterpriseProvider,
    payload: EnterpriseConnectionUpdateRequest,
    actor: Annotated[User, Depends(require_global_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EnterpriseConnectionResponse:
    return await upsert_connection(db, workspace_id, provider, payload, actor, settings)


@admin_router.get(
    "/workspaces/{workspace_id}/identities",
    response_model=list[EnterpriseIdentityResponse],
)
async def read_identities(
    workspace_id: str,
    _: Annotated[User, Depends(require_global_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[EnterpriseIdentityResponse]:
    return await list_identities(db, workspace_id)


@admin_router.put(
    "/workspaces/{workspace_id}/identities/{identity_id}/binding",
    response_model=EnterpriseIdentityResponse,
)
async def write_identity_binding(
    workspace_id: str,
    identity_id: str,
    payload: EnterpriseIdentityBindingRequest,
    actor: Annotated[User, Depends(require_global_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EnterpriseIdentityResponse:
    return await bind_identity(db, workspace_id, identity_id, payload.user_id, actor)
