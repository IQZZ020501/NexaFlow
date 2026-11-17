"""Owner-authorized PKCE and generation-fenced OAuth credential lifecycle."""

import asyncio
import base64
import hashlib
import json
import secrets
from dataclasses import replace
from datetime import UTC, timedelta
from urllib.parse import urlencode

from fastapi import HTTPException

from app.entities.defaults import new_id, utc_now
from app.entities.mcp_oauth import McpOAuthAttempt, McpOAuthConnection
from app.infra.db.repositories.email import smtp as smtp_repository
from app.infra.db.repositories.tools import oauth as repository
from app.infra.db.session import get_session_factory
from app.infra.security.keyring import application_secret_key
from app.infra.security.secrets import decrypt_secret, encrypt_secret
from app.ports.mcp import McpClientError, McpServerBusy
from app.ports.oauth import OAuthExchangeError, oauth_post, validate_oauth_endpoint


def _utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _secrets(connection, settings):
    if not connection.secrets_ciphertext:
        return {}
    return json.loads(
        decrypt_secret(connection.secrets_ciphertext, application_secret_key(settings))
    )


def _encrypt(payload, settings):
    return encrypt_secret(
        json.dumps(payload, separators=(",", ":"), allow_nan=False),
        application_secret_key(settings),
    )


def _private(configuration, settings):
    return (
        configuration.get("network_policy") == "deployment"
        and settings.mcp_allow_private_networks
    )


async def configure(db, server, payload, settings):
    if server.transport == "stdio":
        raise HTTPException(422, "OAuth requires an HTTP MCP transport.")
    existing = await repository.get_connection(db, server.id, lock=True)
    if existing and existing.status != "disconnected":
        raise HTTPException(409, "Disconnect OAuth before changing its configuration.")
    configuration = payload.model_dump(exclude={"client_secret"}) | {
        "resource": server.url,
        "network_policy": server.network_policy,
    }
    try:
        for key in ("authorization_endpoint", "token_endpoint", "revocation_endpoint"):
            await validate_oauth_endpoint(
                configuration[key], allow_private=_private(configuration, settings)
            )
    except OAuthExchangeError as exc:
        raise HTTPException(422, str(exc)) from exc
    connection = existing or McpOAuthConnection(server_id=server.id)
    connection.configuration = configuration
    connection.secrets_ciphertext = _encrypt(
        {"client_secret": payload.client_secret or ""}, settings
    )
    connection.status = "disconnected"
    connection.generation += 1
    connection.refresh_owner = None
    connection.refresh_expires_at = None
    connection.access_expires_at = None
    return await repository.save_connection(db, connection)


async def status(db, server):
    connection = await repository.get_connection(db, server.id)
    if connection is None:
        raise HTTPException(404, "OAuth is not configured for this source.")
    return {
        "status": connection.status,
        "expires_at": connection.access_expires_at,
        "configuration": {
            key: value
            for key, value in connection.configuration.items()
            if key not in {"network_policy", "resource"}
        },
    }


async def authorize(db, server, actor, settings):
    connection = await repository.get_connection(db, server.id, lock=True)
    if connection is None or server.status != "active":
        raise HTTPException(409, "OAuth source is unavailable.")
    if connection.status != "disconnected":
        raise HTTPException(
            409, "Disconnect the existing OAuth grant before reconnecting."
        )
    if connection.configuration["client_auth_method"] != "none" and not _secrets(
        connection, settings
    ).get("client_secret"):
        raise HTTPException(
            422, "Re-enter the OAuth client secret after disconnecting this source."
        )
    site = await smtp_repository.get(db)
    if site is None or not site.site_url:
        raise HTTPException(
            422,
            "Configure the administrator-managed public site URL before connecting OAuth.",
        )
    redirect_uri = site.site_url.rstrip("/") + "/app/mcp/oauth/callback"
    state = f"{server.workspace_id}.{server.id}.{secrets.token_urlsafe(32)}"
    verifier = secrets.token_urlsafe(48)
    connection.generation += 1
    await repository.save_connection(db, connection)
    await repository.save_attempt(
        db,
        McpOAuthAttempt(
            connection_id=connection.id,
            actor_id=actor.id,
            generation=connection.generation,
            state_hash=hashlib.sha256(state.encode()).hexdigest(),
            verifier_ciphertext=_encrypt({"verifier": verifier}, settings),
            redirect_uri=redirect_uri,
            expires_at=utc_now() + timedelta(minutes=10),
        ),
    )
    query = {
        "response_type": "code",
        "client_id": connection.configuration["client_id"],
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        )
        .rstrip(b"=")
        .decode(),
        "code_challenge_method": "S256",
        "resource": connection.configuration["resource"],
    }
    if connection.configuration.get("scopes"):
        query["scope"] = " ".join(connection.configuration["scopes"])
    await db.commit()
    return {
        "authorization_url": connection.configuration["authorization_endpoint"]
        + "?"
        + urlencode(query),
        "redirect_uri": redirect_uri,
    }


async def _post(connection, settings, values, *, revoke=False):
    configuration = connection.configuration
    credentials = _secrets(connection, settings)
    return await oauth_post(
        configuration["revocation_endpoint" if revoke else "token_endpoint"],
        values,
        client_auth=configuration["client_auth_method"],
        client_id=configuration["client_id"],
        client_secret=credentials.get("client_secret", ""),
        allow_private=_private(configuration, settings),
    )


def _accept_tokens(connection, response, credentials, settings):
    token = response.get("access_token")
    refresh = response.get("refresh_token", credentials.get("refresh_token"))
    lifetime = response.get("expires_in")
    if (
        not isinstance(token, str)
        or not 1 <= len(token) <= 8000
        or not isinstance(response.get("token_type"), str)
        or response["token_type"].lower() != "bearer"
        or (
            refresh is not None
            and (not isinstance(refresh, str) or not 1 <= len(refresh) <= 8000)
        )
        or (
            lifetime is not None
            and (type(lifetime) is not int or not 1 <= lifetime <= 366 * 86400)
        )
    ):
        raise OAuthExchangeError("OAuth server returned invalid token metadata.")
    connection.secrets_ciphertext = _encrypt(
        {
            "client_secret": credentials.get("client_secret", ""),
            "access_token": token,
            **({"refresh_token": refresh} if refresh else {}),
        },
        settings,
    )
    connection.access_expires_at = (
        utc_now() + timedelta(seconds=lifetime) if lifetime else None
    )
    connection.status = "connected"
    connection.refresh_owner = None
    connection.refresh_expires_at = None
    connection.updated_at = utc_now()


async def _revoke_late_tokens(db, connection, response, credentials, settings):
    witness = replace(connection)
    _accept_tokens(witness, response, credentials, settings)
    await repository.queue_revocation(db, witness)
    await db.commit()


async def callback(db, server, actor, payload, settings):
    connection = await repository.get_connection(db, server.id, lock=True)
    attempt = await repository.get_attempt(
        db, hashlib.sha256(payload.state.encode()).hexdigest(), lock=True
    )
    if (
        connection is None
        or attempt is None
        or attempt.connection_id != connection.id
        or attempt.actor_id != actor.id
        or attempt.generation != connection.generation
        or _utc(attempt.expires_at) <= utc_now()
        or server.status != "active"
    ):
        raise HTTPException(400, "OAuth state is invalid or expired.")
    if attempt.status == "completed":
        return await status(db, server)
    if attempt.status != "pending":
        raise HTTPException(
            409,
            "OAuth callback was already used; reconnect if authorization did not complete.",
        )
    verifier = json.loads(
        decrypt_secret(attempt.verifier_ciphertext, application_secret_key(settings))
    )["verifier"]
    attempt.verifier_ciphertext = ""
    attempt.status = "processing"
    await repository.save_attempt(db, attempt)
    await db.commit()
    try:
        response = await _post(
            connection,
            settings,
            {
                "grant_type": "authorization_code",
                "code": payload.code,
                "redirect_uri": attempt.redirect_uri,
                "code_verifier": verifier,
                "resource": connection.configuration["resource"],
            },
        )
        current = await repository.get_connection(db, server.id, lock=True)
        if current is None or current.generation != attempt.generation:
            await _revoke_late_tokens(
                db,
                connection,
                response,
                {
                    "client_secret": _secrets(connection, settings).get(
                        "client_secret", ""
                    )
                },
                settings,
            )
            raise OAuthExchangeError(
                "OAuth source changed during authorization; reconnect."
            )
        _accept_tokens(
            current,
            response,
            {"client_secret": _secrets(current, settings).get("client_secret", "")},
            settings,
        )
        await repository.save_connection(db, current)
        attempt.status = "completed"
        await repository.save_attempt(db, attempt)
        await db.commit()
    except OAuthExchangeError as exc:
        await db.rollback()
        stored = await repository.get_attempt(db, attempt.state_hash, lock=True)
        if stored:
            stored.status = "failed"
            await repository.save_attempt(db, stored)
        await db.commit()
        raise HTTPException(400, str(exc)) from exc
    return await status(db, server)


async def queue_disconnect(db, server_id):
    connection = await repository.get_connection(db, server_id, lock=True)
    if connection is None:
        return
    if connection.status != "disconnected":
        await repository.queue_revocation(db, connection)
    # The outbox owns all secrets until revocation. Public configuration stays;
    # confidential clients must re-enter their secret before the next login.
    connection.secrets_ciphertext = ""
    connection.status = "disconnected"
    connection.generation += 1
    connection.refresh_owner = None
    connection.refresh_expires_at = None
    connection.access_expires_at = None
    await repository.save_connection(db, connection)


async def access_token(server, settings):
    """Never replay a refresh whose previous worker may have sent it.

    Claim and commit before network I/O. Expired claims require reauthorization
    because a rotated refresh token may have been lost with the old worker.
    """
    for _ in range(20):
        owner = new_id()
        async with get_session_factory()() as db:
            current = await repository.get_connection(db, server.id, lock=True)
            if current is None or current.status not in {"connected", "refreshing"}:
                raise McpClientError(
                    "MCP OAuth requires reconnection.", request_sent=False
                )
            if current.status == "refreshing":
                if (
                    current.refresh_expires_at is None
                    or _utc(current.refresh_expires_at) <= utc_now()
                ):
                    current.status = "reauthorization_required"
                    await repository.save_connection(db, current)
                    await db.commit()
                    raise McpClientError(
                        "MCP OAuth refresh outcome is unknown; reconnect the source.",
                        request_sent=False,
                    )
            else:
                credentials = _secrets(current, settings)
                if current.access_expires_at is None or _utc(
                    current.access_expires_at
                ) > utc_now() + timedelta(seconds=30):
                    return credentials["access_token"]
                if not credentials.get("refresh_token"):
                    current.status = "reauthorization_required"
                    await repository.save_connection(db, current)
                    await db.commit()
                    raise McpClientError(
                        "MCP OAuth access expired; reconnect the source.",
                        request_sent=False,
                    )
                current.status = "refreshing"
                current.refresh_owner = owner
                current.refresh_expires_at = utc_now() + timedelta(seconds=30)
                await repository.save_connection(db, current)
                await db.commit()
                break
        await asyncio.sleep(0.1)
    else:
        raise McpServerBusy("MCP OAuth credentials are refreshing.")
    try:
        response = await _post(
            current,
            settings,
            {
                "grant_type": "refresh_token",
                "refresh_token": credentials["refresh_token"],
                "resource": current.configuration["resource"],
            },
        )
        async with get_session_factory()() as db:
            latest = await repository.get_connection(db, server.id, lock=True)
            if (
                latest is None
                or latest.status != "refreshing"
                or latest.refresh_owner != owner
                or latest.generation != current.generation
            ):
                await _revoke_late_tokens(db, current, response, credentials, settings)
                raise OAuthExchangeError("MCP OAuth changed during refresh.")
            _accept_tokens(latest, response, credentials, settings)
            await repository.save_connection(db, latest)
            await db.commit()
        return response["access_token"]
    except OAuthExchangeError as exc:
        async with get_session_factory()() as db:
            latest = await repository.get_connection(db, server.id, lock=True)
            if latest and latest.refresh_owner == owner:
                latest.status = "reauthorization_required"
                latest.refresh_owner = None
                await repository.save_connection(db, latest)
                await db.commit()
        raise McpClientError(
            "MCP OAuth refresh failed; reconnect the source.", request_sent=False
        ) from exc


async def recover_revocations(settings):
    # Claim due work for two minutes, releasing DB locks before HTTP. Duplicate
    # revocation is safe; code and refresh exchanges above are never retried.
    async with get_session_factory()() as db:
        await repository.expire_attempts(db, utc_now())
        due = await repository.due_revocations(db, utc_now(), limit=2)
        for item in due:
            item.attempts += 1
            item.next_attempt_at = utc_now() + timedelta(seconds=120)
            await repository.retry_revocation(db, item)
        await db.commit()
    for item in due:
        try:
            payload = _secrets(item, settings)
            for kind in ("refresh_token", "access_token"):
                if payload.get(kind):
                    await _post(
                        item,
                        settings,
                        {"token": payload[kind], "token_type_hint": kind},
                        revoke=True,
                    )
            async with get_session_factory()() as db:
                await repository.delete_revocation(db, item.id)
                await db.commit()
        except OAuthExchangeError:
            async with get_session_factory()() as db:
                item.next_attempt_at = utc_now() + timedelta(
                    seconds=min(3600, 30 * 2 ** min(item.attempts, 7))
                )
                await repository.retry_revocation(db, item)
                await db.commit()
