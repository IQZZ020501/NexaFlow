from fastapi import HTTPException, status


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


def normalize_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid name.")
    return name
