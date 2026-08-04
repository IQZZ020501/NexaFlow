import json

from app.infrastructure.secrets import decrypt_secret, encrypt_secret

SECRET_BUNDLE_PREFIX = "credential-v1:"


def legacy_credential_config(provider_type: str, api_base: str) -> dict[str, str]:
    if not api_base:
        return {}
    if provider_type == "azure_openai":
        return {
            "azure_endpoint": api_base,
            "api_version": "2024-10-21",
        }
    if provider_type == "google_genai":
        return {}
    if provider_type in {"anthropic", "ollama"}:
        return {"api_base": api_base.removesuffix("/v1")}
    return {"api_base": api_base}


def encrypt_credential_secrets(
    secrets: dict[str, str],
    secret_key: str,
) -> str | None:
    if not secrets:
        return None
    payload = json.dumps(secrets, ensure_ascii=True, separators=(",", ":"))
    return encrypt_secret(f"{SECRET_BUNDLE_PREFIX}{payload}", secret_key)


def decrypt_credential_secrets(
    ciphertext: str | None,
    secret_key: str,
) -> dict[str, str]:
    if ciphertext is None:
        return {}
    payload = decrypt_secret(ciphertext, secret_key)
    if not payload.startswith(SECRET_BUNDLE_PREFIX):
        return {"api_key": payload}
    value = json.loads(payload.removeprefix(SECRET_BUNDLE_PREFIX))
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str)
        for key, item in value.items()
    ):
        raise ValueError("Stored model credentials are invalid.")
    return value
