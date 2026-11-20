"""Resource identifiers may occupy only a single URL path segment."""

import re

from app.ports.integrations import IntegrationProviderError


def resource_identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,256}", value):
        raise IntegrationProviderError("Invalid integration resource identifier.")
    return value
