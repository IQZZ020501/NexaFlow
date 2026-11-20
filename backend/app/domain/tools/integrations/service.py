"""Owner-scoped OAuth installation and disconnect, with fenced callbacks."""

import asyncio
import hashlib
import json
import secrets
from datetime import UTC, timedelta
from urllib.parse import urlencode

from fastapi import HTTPException

from app.domain.tools.catalog.service import canonical_definition_hash
from app.domain.tools.integrations.catalog import OPERATIONS, PROVIDERS
from app.domain.tools.integrations.feishu_catalog import FEISHU_CATALOG_REVISION
from app.domain.tools.integrations.redirects import browser_redirect_uri
from app.entities.defaults import new_id, utc_now
from app.entities.tools import Tool, ToolPolicy, ToolSource, ToolVersion
from app.entities.tools.integrations import (
    IntegrationAuthorization,
    IntegrationConnection,
)
from app.infra.db.repositories.tools import integrations as repository
from app.infra.db.repositories.tools import repository as tools
from app.infra.db.repositories.workspaces import repository as workspaces
from app.infra.security.keyring import application_secret_key
from app.infra.security.secrets import decrypt_secret, encrypt_secret
from app.ports import integrations as provider_api
from app.ports.tools import ToolAdapterBusy


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def provider_definition(provider):
    if provider not in PROVIDERS:
        raise HTTPException(404, "Integration not found.")
    return PROVIDERS[provider]


def seal(value, settings):
    return encrypt_secret(
        json.dumps(value, separators=(",", ":")), application_secret_key(settings)
    )


def unseal(value, settings):
    return (
        json.loads(decrypt_secret(value, application_secret_key(settings)))
        if value
        else {}
    )


def _application_matches(provider, connection):
    # Zero means this authorization is independent of a configured application.
    # Retired manually configured Feishu/Dida grants must authorize again.
    return provider not in ("dida", "feishu") or connection.application_revision == 0


async def status(db, workspace_id, user_id, provider):
    provider_definition(provider)
    connection = await repository.connection(db, workspace_id, user_id, provider)
    state = connection.status if connection else "disconnected"
    if (
        connection
        and state == "connected"
        and (
            not _application_matches(provider, connection)
            or connection.access_expires_at
            and utc(connection.access_expires_at) <= utc_now()
            and not connection.refreshable
        )
    ):
        state = "reauthorization_required"
    return {
        "provider": provider,
        "status": state,
        "configured": True,
        "expires_at": connection.access_expires_at if connection else None,
        "source_id": connection.source_id
        if connection and state != "disconnected"
        else None,
    }


async def _archive_source(db, connection):
    if connection.source_id:
        source = await tools.get_tool_source(
            db, connection.workspace_id, connection.source_id
        )
        if source:
            source.status = "archived"
            source.updated_at = utc_now()
            await tools.save_tool_source(db, source)
            for tool in await tools.list_tools_by_source(
                db, connection.workspace_id, source.id
            ):
                tool.status, tool.updated_at = "archived", utc_now()
                await tools.save_tool(db, tool)


async def begin(db, workspace_id, actor, provider, settings, *, browser_origin=None):
    provider_definition(provider)
    await workspaces.lock_workspace(db, workspace_id)
    callback_uri = (
        browser_redirect_uri(settings, browser_origin) if provider == "dida" else ""
    )
    connection = await repository.connection(
        db, workspace_id, actor.id, provider, lock=True
    )
    if connection is None:
        connection = IntegrationConnection(
            workspace_id=workspace_id, user_id=actor.id, provider=provider
        )
    if (
        connection.status == "connected"
        and _application_matches(provider, connection)
        and not (
            connection.access_expires_at
            and utc(connection.access_expires_at) <= utc_now()
            and not connection.refreshable
        )
    ):
        raise HTTPException(
            409,
            "This integration is already installed. Uninstall it before connecting another account.",
        )
    await _archive_source(db, connection)
    connection.generation += 1
    connection.application_revision = 0
    connection.secrets_ciphertext = ""
    connection.refreshable = False
    connection.access_expires_at = None
    connection.status = "disconnected"
    connection.refresh_owner = connection.refresh_expires_at = None
    connection.updated_at = utc_now()
    await repository.save_connection(db, connection)
    await repository.clear_authorizations(db, connection.id)
    state = f"{workspace_id}.{provider}.{secrets.token_urlsafe(32)}"
    verifier = secrets.token_urlsafe(48)
    attempt = IntegrationAuthorization(
        connection_id=connection.id,
        state_hash=hashlib.sha256(state.encode()).hexdigest(),
        generation=connection.generation,
        status="registering" if provider in ("dida", "feishu") else "pending",
        redirect_uri=callback_uri,
        secrets_ciphertext=seal({"verifier": verifier}, settings),
        expires_at=utc_now() + timedelta(minutes=5),
    )
    await repository.save_authorization(db, attempt)
    await db.commit()
    if provider == "feishu":
        try:
            response = await provider_api.feishu_authorization("start", {})
        except provider_api.IntegrationProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        current = await repository.connection_by_id(db, connection.id, lock=True)
        current_attempt = await repository.authorization(
            db, attempt.state_hash, lock=True
        )
        if (
            not current
            or current.generation != attempt.generation
            or not current_attempt
            or current_attempt.status != "registering"
            or utc(current_attempt.expires_at) <= utc_now()
        ):
            raise HTTPException(
                409, "Integration authorization was cancelled. Please install again."
            )
        authorization = response["authorization"]
        current_attempt.status = "pending"
        current_attempt.secrets_ciphertext = seal(response["credentials"], settings)
        current_attempt.expires_at = utc_now() + timedelta(
            seconds=authorization["expires_in"]
        )
        current_attempt.next_poll_at = utc_now() + timedelta(
            seconds=authorization["poll_seconds"]
        )
        await repository.save_authorization(db, current_attempt)
        await db.commit()
        return {**authorization, "state": state}
    if provider == "tencent_meeting":
        device_id = secrets.token_hex(32)
        try:
            response = await provider_api.device_authorization(
                "init", {"device_id": device_id}
            )
            code = response.get("auth_code")
            if not isinstance(code, str) or not 1 <= len(code) <= 4096:
                raise provider_api.IntegrationProviderError(
                    "Integration authorization failed. Please authorize again."
                )
        except provider_api.IntegrationProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        current = await repository.connection_by_id(db, connection.id, lock=True)
        if not current or current.generation != attempt.generation:
            raise HTTPException(
                409, "Integration authorization was cancelled. Please install again."
            )
        attempt.secrets_ciphertext = seal(
            {"device_id": device_id, "auth_code": code}, settings
        )
        await repository.save_authorization(db, attempt)
        await db.commit()
        url = (
            "https://meeting.tencent.com/marketplace/tencentmeeting-cli-auth.html?"
            + urlencode({"code": code})
        )
        return {
            "authorization_url": url,
            "state": state,
            "mode": "device",
            "poll_seconds": 5,
        }
    if provider == "dida":
        scopes = PROVIDERS[provider]["scopes"]
        try:
            client_id = await provider_api.register_public_client(
                provider, callback_uri, scopes
            )
        except provider_api.IntegrationProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        current = await repository.connection_by_id(db, connection.id, lock=True)
        current_attempt = await repository.authorization(
            db, attempt.state_hash, lock=True
        )
        if (
            not current
            or current.generation != attempt.generation
            or not current_attempt
            or current_attempt.status != "registering"
            or utc(current_attempt.expires_at) <= utc_now()
        ):
            raise HTTPException(
                409, "Integration authorization was cancelled. Please install again."
            )
        current_attempt.status = "pending"
        current_attempt.secrets_ciphertext = seal(
            {"verifier": verifier, "client_id": client_id}, settings
        )
        await repository.save_authorization(db, current_attempt)
        await db.commit()
    url = provider_api.authorization_url(
        provider, client_id, callback_uri, state, verifier, scopes
    )
    return {
        "authorization_url": url,
        "state": state,
        "mode": "redirect",
        "poll_seconds": 5,
    }


def accept_tokens(connection, response, settings, previous=None):
    previous = previous or {}

    def invalid(field):
        value = response.get(field)
        return provider_api.IntegrationProviderError(
            "Integration returned invalid authorization data.",
            reason=f"invalid_token_field:{field}:{type(value).__name__}",
        )

    if (
        not isinstance(response.get("token_type", "bearer"), str)
        or response.get("token_type", "bearer").lower() != "bearer"
    ):
        raise invalid("token_type")
    token = response.get("access_token")
    refresh = response.get("refresh_token", previous.get("refresh_token"))
    if connection.provider == "dida":
        refresh = None
    token_limit = 64 * 1024 if connection.provider == "feishu" else 8000
    for field, value in (("access_token", token), ("refresh_token", refresh)):
        if value is not None and (
            not isinstance(value, str)
            or not 1 <= len(value) <= token_limit
            or any(ord(c) <= 32 for c in value)
        ):
            raise invalid(field)
    if not token:
        raise invalid("access_token")
    credentials = {
        "access_token": token,
        **({"refresh_token": refresh} if refresh else {}),
    }
    if connection.provider == "feishu":
        for key in ("brand", "client_id", "client_secret"):
            value = previous.get(key)
            if (
                not isinstance(value, str)
                or not value
                or any(ord(char) <= 32 for char in value)
            ):
                raise invalid(key)
            credentials[key] = value
    if connection.provider == "tencent_meeting":
        for key in ("open_id", "sdk_id"):
            value = response.get(key, previous.get(key))
            if (
                not isinstance(value, str)
                or not 1 <= len(value) <= 256
                or any(ord(c) <= 32 for c in value)
            ):
                raise provider_api.IntegrationProviderError(
                    "Integration returned invalid authorization data."
                )
            credentials[key] = value
        credentials["device_id"] = previous["device_id"]
        try:
            expiry = int(response["access_token_expire_time"])
            lifetime = expiry - int(utc_now().timestamp())
        except (KeyError, TypeError, ValueError) as exc:
            raise provider_api.IntegrationProviderError(
                "Integration returned invalid authorization data."
            ) from exc
    else:
        lifetime = response.get("expires_in")
    if lifetime is not None and (
        type(lifetime) is not int or not 1 <= lifetime <= 366 * 86400
    ):
        raise invalid("expires_in")
    connection.secrets_ciphertext = seal(credentials, settings)
    connection.refreshable = bool(refresh) and connection.provider != "dida"
    connection.access_expires_at = (
        utc_now() + timedelta(seconds=lifetime) if lifetime else None
    )
    connection.refresh_owner = connection.refresh_expires_at = None
    connection.status = "connected"
    connection.updated_at = utc_now()


async def install_tools(db, connection):
    definition = PROVIDERS[connection.provider]
    source = (
        await tools.get_tool_source(db, connection.workspace_id, connection.source_id)
        if connection.source_id
        else None
    )
    source = source or ToolSource(
        workspace_id=connection.workspace_id,
        kind="integration",
        name=definition["name"],
        created_by_user_id=connection.user_id,
    )
    source.status, source.updated_at = "active", utc_now()
    await tools.save_tool_source(db, source)
    connection.source_id = source.id
    for operation in OPERATIONS[connection.provider]:
        tool = await tools.get_tool_by_source_key(
            db, connection.workspace_id, source.id, operation["name"]
        )
        tool = tool or Tool(
            workspace_id=connection.workspace_id,
            source_id=source.id,
            kind="integration",
            stable_key=operation["name"],
            function_name=f"{connection.provider}_{operation['name']}_{source.id.replace('-', '')}",
            created_by_user_id=connection.user_id,
        )
        await tools.save_tool(db, tool)
        spec = {
            "connection_id": connection.id,
            "provider": connection.provider,
            "operation": operation["name"],
            "generation": connection.generation,
        }
        if connection.provider == "feishu":
            spec["catalog_revision"] = FEISHU_CATALOG_REVISION
        digest = canonical_definition_hash(
            {"operation": operation, "execution_spec": spec}
        )
        current = (
            await tools.get_tool_version(
                db, connection.workspace_id, tool.current_version_id
            )
            if tool.current_version_id
            else None
        )
        if current and current.definition_hash == digest:
            continue
        versions = await tools.list_tool_versions(db, connection.workspace_id, tool.id)
        version = ToolVersion(
            workspace_id=connection.workspace_id,
            tool_id=tool.id,
            revision=len(versions) + 1,
            display_name=f"{definition['name']}: {operation['name']}",
            description=operation["description"],
            input_schema=operation["input_schema"],
            execution_spec=spec,
            definition_hash=digest,
            created_by_user_id=connection.user_id,
        )
        await tools.save_tool_version(db, version)
        policy = await tools.get_tool_policy(db, connection.workspace_id, tool.id)
        revision = policy.revision + 1 if policy else 1
        policy = policy or ToolPolicy(
            workspace_id=connection.workspace_id, tool_id=tool.id
        )
        policy.tool_version_id, policy.definition_hash = version.id, digest
        policy.revision = revision
        policy.approval = "each_call" if operation["write"] else "auto"
        policy.effect = "external_write" if operation["write"] else "external_read"
        policy.allowed_access_sources = ["console"]
        policy.workflow_callable = False
        policy.parallel_safe = not operation["write"]
        await tools.save_tool_policy(db, policy)
        tool.current_version_id, tool.status, tool.availability = (
            version.id,
            "active",
            "available",
        )
        tool.updated_at = utc_now()
        await tools.save_tool(db, tool)
    operation_names = {
        operation["name"] for operation in OPERATIONS[connection.provider]
    }
    for tool in await tools.list_tools_by_source(
        db, connection.workspace_id, source.id
    ):
        if tool.stable_key not in operation_names and tool.status != "archived":
            tool.status, tool.availability = "archived", "unavailable"
            tool.updated_at = utc_now()
            await tools.save_tool(db, tool)
    await repository.save_connection(db, connection)


async def sync_tools(db, workspace_id, actor, provider):
    provider_definition(provider)
    connection = await repository.connection(
        db, workspace_id, actor.id, provider, lock=True
    )
    state = await status(db, workspace_id, actor.id, provider)
    if not connection or state["status"] != "connected":
        raise HTTPException(
            409, "Integration is not installed for this user. Please install again."
        )
    await install_tools(db, connection)
    await db.commit()
    return await status(db, workspace_id, actor.id, provider)


async def complete(db, workspace_id, actor, provider, payload, settings):
    connection = await repository.connection(
        db, workspace_id, actor.id, provider, lock=True
    )
    attempt = await repository.authorization(
        db, hashlib.sha256(payload.state.encode()).hexdigest(), lock=True
    )
    if (
        not connection
        or not attempt
        or attempt.connection_id != connection.id
        or attempt.generation != connection.generation
        or utc(attempt.expires_at) <= utc_now()
        or not _application_matches(provider, connection)
    ):
        raise HTTPException(
            400,
            "Integration authorization is invalid or expired. Please install again.",
        )
    if attempt.status == "completed":
        return await status(db, workspace_id, actor.id, provider)
    if attempt.status != "pending":
        raise HTTPException(
            409, "Integration authorization was already used. Please install again."
        )
    if (
        provider in ("tencent_meeting", "feishu")
        and utc(attempt.next_poll_at) > utc_now()
    ):
        return await status(db, workspace_id, actor.id, provider)
    if provider == "dida" and not payload.code:
        raise HTTPException(422, "Integration authorization code is required.")
    values = unseal(attempt.secrets_ciphertext, settings)
    attempt.status, attempt.secrets_ciphertext = "processing", ""
    await repository.save_authorization(db, attempt)
    await db.commit()
    try:
        if provider == "tencent_meeting":
            response = await provider_api.device_authorization("poll", values)
        elif provider == "feishu":
            response = await provider_api.feishu_authorization("poll", values)
        else:
            response = await provider_api.exchange_tokens(
                provider,
                values["client_id"],
                "",
                grant_type="authorization_code",
                code=payload.code,
                redirect_uri=attempt.redirect_uri,
                code_verifier=values["verifier"],
                **(
                    {"scope": " ".join(PROVIDERS[provider]["scopes"])}
                    if provider == "dida"
                    else {}
                ),
            )
        current = await repository.connection_by_id(db, connection.id, lock=True)
        if (
            not current
            or current.generation != attempt.generation
            or not _application_matches(provider, current)
        ):
            raise HTTPException(
                409, "Integration authorization was cancelled. Please install again."
            )
        if provider == "feishu" and response.get("pending"):
            next_values = response["credentials"]
            attempt.status = "pending"
            attempt.secrets_ciphertext = seal(next_values, settings)
            attempt.next_poll_at = utc_now() + timedelta(
                seconds=next_values["poll_seconds"]
            )
            authorization = response.get("authorization")
            if authorization:
                attempt.expires_at = utc_now() + timedelta(
                    seconds=authorization["expires_in"]
                )
            await repository.save_authorization(db, attempt)
            await db.commit()
            result = await status(db, workspace_id, actor.id, provider)
            if authorization:
                result["authorization"] = {**authorization, "state": payload.state}
            return result
        if provider == "tencent_meeting" and not response.get("open_id"):
            attempt.status = "pending"
            attempt.secrets_ciphertext = seal(values, settings)
            attempt.next_poll_at = utc_now() + timedelta(seconds=5)
            await repository.save_authorization(db, attempt)
            await db.commit()
            return await status(db, workspace_id, actor.id, provider)
        accept_tokens(current, response, settings, values)
        await install_tools(db, current)
        attempt.status = "completed"
        await repository.save_authorization(db, attempt)
        await db.commit()
        return await status(db, workspace_id, actor.id, provider)
    except (provider_api.IntegrationProviderError, asyncio.CancelledError) as exc:
        await db.rollback()
        failed = await repository.authorization(db, attempt.state_hash, lock=True)
        if (
            failed
            and failed.generation == attempt.generation
            and failed.status == "processing"
        ):
            failed.status = "failed"
            failed.secrets_ciphertext = seal(
                {
                    "failure_reason": getattr(exc, "reason", None)
                    or type(exc).__name__,
                    "stage": values.get("stage"),
                },
                settings,
            )
            await repository.save_authorization(db, failed)
            await db.commit()
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise HTTPException(502, str(exc)) from exc


async def uninstall(db, workspace_id, actor, provider):
    provider_definition(provider)
    connection = await repository.connection(
        db, workspace_id, actor.id, provider, lock=True
    )
    if connection:
        await _archive_source(db, connection)
        connection.generation += 1
        connection.status, connection.secrets_ciphertext = "disconnected", ""
        connection.access_expires_at = None
        connection.refreshable = False
        connection.refresh_owner = connection.refresh_expires_at = None
        connection.updated_at = utc_now()
        await repository.save_connection(db, connection)
        await repository.clear_authorizations(db, connection.id)
        await db.commit()
    return await status(db, workspace_id, actor.id, provider)


async def credentials(db, connection_id, workspace_id, user_id, generation, settings):
    connection = await repository.connection_by_id(db, connection_id, lock=True)
    if (
        not connection
        or connection.workspace_id != workspace_id
        or connection.user_id != user_id
        or connection.generation != generation
        or connection.status != "connected"
    ):
        raise provider_api.IntegrationProviderError(
            "Integration is not installed for this user. Please install again."
        )
    if not _application_matches(connection.provider, connection):
        raise provider_api.IntegrationProviderError(
            "Integration application changed. Please install again."
        )
    values = unseal(connection.secrets_ciphertext, settings)
    if not connection.access_expires_at or utc(
        connection.access_expires_at
    ) > utc_now() + timedelta(seconds=60):
        await db.commit()
        return values
    if (
        connection.refresh_owner
        and connection.refresh_expires_at
        and utc(connection.refresh_expires_at) > utc_now()
    ):
        raise ToolAdapterBusy("Integration authorization is refreshing.")
    if (
        not connection.refreshable
        or not values.get("refresh_token")
        or connection.refresh_owner
    ):
        connection.status = "reauthorization_required"
        await repository.save_connection(db, connection)
        await db.commit()
        raise provider_api.IntegrationProviderError(
            "Integration authorization expired. Please install again."
        )
    owner = new_id()
    connection.refresh_owner, connection.refresh_expires_at = (
        owner,
        utc_now() + timedelta(seconds=30),
    )
    await repository.save_connection(db, connection)
    await db.commit()
    try:
        if connection.provider == "tencent_meeting":
            response = await provider_api.device_authorization(
                "refresh",
                {
                    key: values[key]
                    for key in ("device_id", "refresh_token", "open_id", "sdk_id")
                },
            )
        else:
            response = await provider_api.feishu_authorization("refresh", values)
        current = await repository.connection_by_id(db, connection_id, lock=True)
        if (
            not current
            or current.generation != generation
            or current.refresh_owner != owner
        ):
            raise provider_api.IntegrationProviderError(
                "Integration authorization changed. Please install again."
            )
        accept_tokens(current, response, settings, values)
        await repository.save_connection(db, current)
        await db.commit()
        return unseal(current.secrets_ciphertext, settings)
    except provider_api.IntegrationProviderError:
        await db.rollback()
        current = await repository.connection_by_id(db, connection_id, lock=True)
        if (
            current
            and current.generation == generation
            and current.refresh_owner == owner
        ):
            current.status = "reauthorization_required"
            current.refresh_owner = current.refresh_expires_at = None
            await repository.save_connection(db, current)
            await db.commit()
        raise


async def require_reauthorization(db, connection_id, generation):
    connection = await repository.connection_by_id(db, connection_id, lock=True)
    if (
        connection
        and connection.generation == generation
        and connection.status == "connected"
    ):
        connection.status = "reauthorization_required"
        connection.updated_at = utc_now()
        await repository.save_connection(db, connection)
        await db.commit()
