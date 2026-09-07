from fastapi import HTTPException, status

from app.entities.identity.enterprise import ENTERPRISE_IDENTITY_PROVIDERS


def safe_next_path(value: str | None) -> str:
    if (
        value
        and len(value) <= 2048
        and value.startswith("/")
        and not value.startswith("//")
        and not any(
            character == "\\"
            or character.isspace()
            or ord(character) < 32
            or 127 <= ord(character) <= 159
            for character in value
        )
    ):
        return value
    return "/app/apps"


def validate_connection_fields(
    provider: str,
    client_id: str | None,
    tenant_id: str | None,
    agent_id: str | None,
) -> None:
    if provider not in ENTERPRISE_IDENTITY_PROVIDERS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unsupported provider.")
    if (
        (provider != "feishu" and not (tenant_id or "").strip())
        or (provider != "wecom" and not (client_id or "").strip())
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Client and tenant identifiers are required.",
        )
    if provider == "wecom" and not (agent_id or "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "WeCom agent ID is required.")
