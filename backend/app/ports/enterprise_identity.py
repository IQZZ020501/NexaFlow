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


class EnterpriseProviderError(Exception):
    pass


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
        code_challenge: str,
        *,
        feishu_qr: bool = False,
    ) -> str: ...

    async def resolve_external_principal(
        self,
        connection: EnterpriseIdentityConnection,
        authorization_code: str,
        code_verifier: str,
        *,
        feishu_qr: bool = False,
    ) -> ExternalPrincipal: ...


def build_authorization_url(
    connection: EnterpriseIdentityConnection,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    *,
    feishu_qr: bool = False,
) -> str:
    from app.adapters.identity.enterprise import (
        build_authorization_url as _build_authorization_url,
    )

    return _build_authorization_url(
        connection,
        redirect_uri,
        state,
        code_challenge,
        feishu_qr=feishu_qr,
    )


async def resolve_external_principal(
    connection: EnterpriseIdentityConnection,
    authorization_code: str,
    code_verifier: str,
    *,
    feishu_qr: bool = False,
) -> ExternalPrincipal:
    from app.adapters.identity.enterprise import (
        resolve_external_principal as _resolve_external_principal,
    )

    return await _resolve_external_principal(
        connection,
        authorization_code,
        code_verifier,
        feishu_qr=feishu_qr,
    )


__all__ = [
    "EnterpriseIdentityProvider",
    "EnterpriseProviderError",
    "ExternalPrincipal",
    "build_authorization_url",
    "resolve_external_principal",
]
