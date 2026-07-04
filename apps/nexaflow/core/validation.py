import re

from fastapi import HTTPException, status

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,78}[a-z0-9]$|^[a-z0-9]$")


def normalize_email(email: str) -> str:
    email = email.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid email.")
    return email


def normalize_username(username: str) -> str:
    username = username.strip()
    if not username:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid username.")
    return username


def normalize_slug(slug: str) -> str:
    slug = slug.strip().lower()
    if not _SLUG_RE.fullmatch(slug):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Slug must use lowercase letters, numbers, and hyphens.",
        )
    return slug


def normalize_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid name.")
    return name
