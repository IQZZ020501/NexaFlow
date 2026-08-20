from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator


SmtpSecurity = Literal["none", "starttls", "ssl"]


def _trim(value: str) -> str:
    normalized = value.strip()
    if "\r" in normalized or "\n" in normalized:
        raise ValueError("Line breaks are not allowed.")
    return normalized


def _email(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Invalid email address.")
    normalized = _trim(value).lower()
    if (
        not normalized
        or "@" not in normalized
        or normalized.startswith("@")
        or normalized.endswith("@")
        or normalized.count("@") != 1
        or any(character.isspace() for character in normalized)
    ):
        raise ValueError("Invalid email address.")
    local, domain = normalized.split("@", 1)
    if not local or not domain:
        raise ValueError("Invalid email address.")
    return normalized


def normalize_site_url(value: str) -> str:
    normalized = _trim(value).rstrip("/")
    if not normalized:
        return ""
    parsed = urlsplit(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Invalid public site URL.")
    return normalized


class SmtpSettingsResponse(BaseModel):
    host: str
    port: int
    username: str
    security: SmtpSecurity
    from_email: str
    from_name: str
    site_url: str
    enabled: bool
    timeout_seconds: float
    has_password: bool
    password_hint: str | None
    configured: bool
    identity_configured: bool
    updated_at: datetime


class SmtpSettingsUpdateRequest(BaseModel):
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=4096)
    clear_password: bool = False
    security: SmtpSecurity | None = None
    from_email: str | None = Field(default=None, max_length=255)
    from_name: str | None = Field(default=None, max_length=120)
    site_url: str | None = Field(default=None, max_length=2048)
    enabled: bool | None = None
    timeout_seconds: float | None = Field(default=None, gt=0, le=120)

    @field_validator("host", "username", "from_name", mode="before")
    @classmethod
    def trim_text(cls, value: str | None) -> str | None:
        return _trim(value) if isinstance(value, str) else value

    @field_validator("from_email", mode="before")
    @classmethod
    def normalize_from_email(cls, value: str | None) -> str | None:
        if isinstance(value, str) and not value.strip():
            return ""
        return _email(value) if isinstance(value, str) else value

    @field_validator("site_url", mode="before")
    @classmethod
    def normalize_site_url(cls, value: str | None) -> str | None:
        return normalize_site_url(value) if isinstance(value, str) else value


class SmtpTestRequest(BaseModel):
    to_email: str = Field(min_length=3, max_length=255)

    @field_validator("to_email", mode="before")
    @classmethod
    def normalize_to_email(cls, value: str) -> str:
        return _email(value)
