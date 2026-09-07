"""Provider adapters behind the unified Tool runtime contract."""

import ast
import json
import re
from typing import Any

from app.application.artifacts.service import create_generated_artifact
from app.entities.tools import McpServer, ToolSnapshot
from app.infra.sandbox.client import (
    WorkflowSandboxBusyError,
    WorkflowSandboxError,
    execute_artifact_code,
    execute_skill_artifact,
    execute_workflow_code,
)
from app.infra.config.settings import Settings
from app.entities.defaults import APP_TIMEZONE, utc_now
from app.infra.db.session import get_session_factory
from app.ports.mcp import McpClientError, call_mcp_tool
from app.application.tools.runtime.contracts import (
    ToolAdapter,
    ToolAdapterBusy,
    ToolInvocationContext,
    ToolRuntimeResult,
)
from app.domain.artifacts.services import artifact_format_from_filename
from app.domain.tools.mcp.service import mcp_server_connection

DIRECT_ARTIFACT_CONTENT_FORMATS = frozenset(
    "file txt md markdown html htm css csv tsv json jsonl xml yaml yml toml "
    "ini cfg conf env py pyi ipynb java js jsx mjs cjs ts tsx c h cc cpp "
    "cxx hpp go rs rb php swift kt kts scala sh bash zsh fish ps1 sql "
    "graphql gql vue svelte dart lua r cs fs fsx vb gradle properties svg "
    "tex rtf log po pot".split()
)


def _is_direct_artifact_content(artifact_format: str, code: str) -> bool:
    return artifact_format in DIRECT_ARTIFACT_CONTENT_FORMATS and not (
        "output_path" in code or "NEXAFLOW_OUTPUT_PATH" in code
    )


def _redirect_legacy_artifact_path(code: str, filename: str) -> str:
    """Repair the legacy model pattern that saves the requested file under /tmp."""

    escaped_filename = re.escape(filename)
    return re.sub(
        rf"(['\"])/tmp/[^'\"\n]*{escaped_filename}\1",
        "output_path",
        code,
    )


_UNAVAILABLE_ARTIFACT_IMPORTS = {
    "reportlab": (
        "PDF generation uses PyMuPDF in this runtime: import pymupdf. "
        "reportlab is not installed."
    ),
    "fpdf": (
        "PDF generation uses PyMuPDF in this runtime: import pymupdf. "
        "fpdf is not installed."
    ),
    "weasyprint": (
        "PDF generation uses PyMuPDF in this runtime: import pymupdf. "
        "weasyprint is not installed."
    ),
}


def _artifact_code_preflight(code: str, artifact_format: str) -> str | None:
    try:
        tree = ast.parse(code, filename="<artifact-tool>")
    except SyntaxError as exc:
        location = f"line {exc.lineno}" if exc.lineno else "the submitted code"
        return f"Artifact generator has a syntax error at {location}: {exc.msg}."

    imported_modules: set[str] = set()
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name.split(".", 1)[0])
                imported_names.add(alias.asname or alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module.split(".", 1)[0])
            imported_names.update(alias.asname or alias.name for alias in node.names)

    for module, message in _UNAVAILABLE_ARTIFACT_IMPORTS.items():
        if module in imported_modules:
            return (
                f"{message} Do not repeat the same generator code; replace that "
                "import and retry."
            )

    if artifact_format == "pdf":
        references_fitz = any(
            isinstance(node, ast.Name) and node.id == "fitz"
            for node in ast.walk(tree)
        )
        if references_fitz and "fitz" not in imported_names:
            return (
                "PDF generator references 'fitz' without importing it. Add "
                "'import pymupdf as fitz' at the top, then retry once; do not "
                "repeat the same code."
            )
    return None


def _artifact_error_message(error: Exception) -> str:
    message = str(error).strip()
    for line in reversed(message.splitlines()):
        candidate = line.strip()
        if re.match(
            r"(?:ModuleNotFoundError|ImportError|NameError|SyntaxError|"
            r"PermissionError|RuntimeError|ValueError|TypeError):",
            candidate,
        ):
            return candidate[:1000]
    return message[:1000]

def _failure(code: str, message: str) -> ToolRuntimeResult:
    return ToolRuntimeResult(
        ok=False,
        data=None,
        summary=message,
        error_code=code,
        error_message=message,
        outcome="confirmed",
        usage={},
    )
