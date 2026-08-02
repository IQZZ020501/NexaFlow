from base64 import urlsafe_b64encode
from hashlib import sha256

from cryptography.fernet import Fernet


def _fernet(secret_key: str) -> Fernet:
    return Fernet(urlsafe_b64encode(sha256(secret_key.encode()).digest()))


def encrypt_secret(value: str, secret_key: str) -> str:
    return _fernet(secret_key).encrypt(value.encode()).decode()


def decrypt_secret(value: str, secret_key: str) -> str:
    return _fernet(secret_key).decrypt(value.encode()).decode()


def secret_hint(value: str) -> str:
    if len(value) <= 4:
        return "****"
    return f"****{value[-4:]}"
