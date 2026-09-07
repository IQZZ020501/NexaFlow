"""Shared exception base for upstream-service boundaries.

Ports define their public error types as subclasses of
``ExternalServiceError`` so infrastructure logging can classify failures
raised at service boundaries as external.
"""
from __future__ import annotations


class ExternalServiceError(Exception):
    """Base class for errors caused by an upstream service.

    Subclass this at service boundaries (LLM providers, MCP servers, vector
    stores, ...) so infrastructure can tag those failures as external.
    """
