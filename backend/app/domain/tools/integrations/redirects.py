"""Browser OAuth callbacks stay on the deployment's trusted frontend origin."""

from urllib.parse import urlsplit

from fastapi import HTTPException

_CALLBACK_PATH = "/app/tools/integrations/callback"
_LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1"}


def _origin(value):
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 2048
        or any(ord(char) <= 32 or char == "\\" for char in value)
    ):
        raise ValueError("Invalid origin")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Invalid origin")
    host = parsed.hostname.encode("idna").decode("ascii")
    host = f"[{host}]" if ":" in host else host
    port = parsed.port
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Invalid port")
    suffix = (
        f":{port}"
        if port not in {None, 443 if parsed.scheme == "https" else 80}
        else ""
    )
    return f"{parsed.scheme}://{host}{suffix}"


def browser_redirect_uri(settings, browser_origin=None):
    try:
        trusted = _origin(settings.public_app_url)
        origin = _origin(browser_origin) if browser_origin is not None else trusted
        if origin != trusted:
            expected, current = urlsplit(trusted), urlsplit(origin)
            if not (
                settings.environment == "development"
                and expected.hostname in _LOOPBACK_NAMES
                and current.hostname in _LOOPBACK_NAMES
                and expected.scheme == current.scheme
                and expected.port == current.port
            ):
                raise ValueError("Untrusted origin")
        return origin + _CALLBACK_PATH
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(
            400, "Integration authorization origin is not allowed."
        ) from exc
