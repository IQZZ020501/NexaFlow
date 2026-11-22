"""Enterprise identity provider port.

Public error and principal types plus delegate entry points for the
external identity providers (Feishu, DingTalk, WeCom). The concrete
HTTP implementations live in ``app.adapters.identity.enterprise``; this
module never imports adapters at module load.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.entities.identity.enterprise import EnterpriseIdentityConnection
    from app.infra.config.settings import Settings


class EnterpriseProviderError(Exception):
    def __init__(
        self,
        message: str,
        *,
        operation: str | None = None,
        http_status: int | None = None,
        provider_code: int | None = None,
        missing_field: str | None = None,
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.http_status = http_status
        self.provider_code = provider_code
        self.missing_field = missing_field


@dataclass(frozen=True)
class ExternalPrincipal:
    subject_id: str
    tenant_id: str
    display_name: str
    email: str | None = None


class EnterpriseIdentityProvider(Protocol):
    def build_authorization_url(
        self,
        connection: EnterpriseIdentityConnection,
        redirect_uri: str,
        state: str,
    ) -> str: ...

    async def resolve_external_principal(
        self,
        connection: EnterpriseIdentityConnection,
        client_secret: str,
        code: str,
        redirect_uri: str,
        *,
        settings: Settings,
    ) -> ExternalPrincipal: ...


def build_authorization_url(
    connection: EnterpriseIdentityConnection,
    redirect_uri: str,
    state: str,
) -> str:
    from app.adapters.identity.enterprise import (
        build_authorization_url as _build_authorization_url,
    )

    return _build_authorization_url(
        connection,
        redirect_uri,
        state,
    )


async def resolve_external_principal(
    connection: EnterpriseIdentityConnection,
    client_secret: str,
    code: str,
    redirect_uri: str,
    *,
    settings: Settings,
) -> ExternalPrincipal:
    from app.adapters.identity.enterprise import (
        resolve_external_principal as _resolve_external_principal,
    )

    return await _resolve_external_principal(
        connection,
        client_secret,
        code,
        redirect_uri,
        settings=settings,
    )


__all__ = [
    "EnterpriseIdentityProvider",
    "EnterpriseProviderError",
    "ExternalPrincipal",
    "build_authorization_url",
    "resolve_external_principal",
]
