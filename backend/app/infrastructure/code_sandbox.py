import asyncio
import base64
import binascii
from dataclasses import dataclass
import hashlib
import hmac
import json
from typing import Any

from app.infrastructure.config import Settings

RESULT_MARKER = "__NEXAFLOW_RESULT__="
MAX_RESPONSE_BYTES = 128 * 1024
MAX_ARTIFACT_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_ARTIFACT_BYTES = 5 * 1024 * 1024


class WorkflowSandboxError(RuntimeError):
    pass


class WorkflowSandboxBusyError(WorkflowSandboxError):
    pass


@dataclass(frozen=True)
class WorkflowSandboxResult:
    result: Any
    stdout: str
    stderr: str
    exit_code: int


@dataclass(frozen=True)
class ArtifactSandboxResult:
    content: bytes
    format: str
    filename: str
    size_bytes: int
    sha256: str
    stdout: str
    stderr: str
    exit_code: int


def _program(user_code: str) -> str:
    encoded = json.dumps(user_code, ensure_ascii=False)
    marker = json.dumps(RESULT_MARKER)
    return (
        "import json, sys\n"
        "inputs = json.loads(sys.stdin.read())\n"
        f"exec(compile({encoded}, '<workflow-code-node>', 'exec'), globals())\n"
        "if 'result' not in globals():\n"
        "    raise RuntimeError(\"code node must assign a JSON-serializable 'result'\")\n"
        f"print({marker} + json.dumps({{'result': result}}, ensure_ascii=False, "
        "separators=(',', ':')))\n"
    )


def _artifact_program(user_code: str) -> str:
    encoded = json.dumps(user_code, ensure_ascii=False)
    return (
        "import os\n"
        "output_path = os.environ['NEXAFLOW_OUTPUT_PATH']\n"
        "skills_dir = os.environ['NEXAFLOW_SKILLS_DIR']\n"
        f"exec(compile({encoded}, '<artifact-tool>', 'exec'), globals())\n"
    )


async def _exchange(
    settings: Settings,
    request: dict[str, Any],
    max_response_bytes: int,
) -> dict[str, Any]:
    async def exchange() -> dict[str, Any]:
        reader, writer = await asyncio.open_unix_connection(
            settings.workflow_sandbox_socket,
            limit=max_response_bytes,
        )
        try:
            writer.write(
                (json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
            )
            await writer.drain()
            line = await reader.readline()
            if not line or len(line) > max_response_bytes:
                raise WorkflowSandboxError("Code sandbox returned an invalid response.")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise WorkflowSandboxError("Code sandbox returned an invalid response.")
            return value
        finally:
            writer.close()
            await writer.wait_closed()

    try:
        return await asyncio.wait_for(
            exchange(),
            timeout=settings.workflow_sandbox_timeout_seconds + 1,
        )
    except (OSError, TimeoutError, ValueError) as exc:
        raise WorkflowSandboxError("Code sandbox is unavailable.") from exc


def _execution_fields(response: dict[str, Any]) -> tuple[str, str, int]:
    stdout = str(response.get("stdout") or "")
    stderr = str(response.get("stderr") or "")
    exit_code = response.get("exit_code")
    if response.get("ok") is not True or not isinstance(exit_code, int):
        error = response.get("error")
        reason = str(error or stderr or "Code execution failed.")
        if error == "sandbox_busy":
            raise WorkflowSandboxBusyError(reason)
        raise WorkflowSandboxError(reason[:1000])
    return stdout, stderr, exit_code


async def execute_workflow_code(
    settings: Settings,
    code: str,
    inputs: dict[str, Any],
) -> WorkflowSandboxResult:
    request = {
        "code": _program(code),
        "stdin": json.dumps(inputs, ensure_ascii=False, separators=(",", ":")),
        "limits": {"timeout_ms": round(settings.workflow_sandbox_timeout_seconds * 1000)},
    }

    response = await _exchange(settings, request, MAX_RESPONSE_BYTES)
    stdout, stderr, exit_code = _execution_fields(response)
    marker_index = stdout.rfind(RESULT_MARKER)
    if marker_index < 0:
        raise WorkflowSandboxError("Code node did not return a result.")
    result_line = stdout[marker_index + len(RESULT_MARKER) :].strip()
    try:
        payload = json.loads(result_line)
    except json.JSONDecodeError as exc:
        raise WorkflowSandboxError("Code node returned invalid JSON.") from exc
    if not isinstance(payload, dict) or "result" not in payload:
        raise WorkflowSandboxError("Code node returned invalid JSON.")
    logs = stdout[:marker_index].rstrip("\n")
    return WorkflowSandboxResult(
        result=payload["result"],
        stdout=logs,
        stderr=stderr,
        exit_code=exit_code,
    )


async def execute_artifact_code(
    settings: Settings,
    code: str,
    artifact_format: str,
    filename: str,
    skills: list[str],
) -> ArtifactSandboxResult:
    response = await _exchange(
        settings,
        {
            "code": _artifact_program(code),
            "artifact": {"format": artifact_format, "filename": filename},
            "skills": skills,
            "limits": {
                "timeout_ms": round(settings.workflow_sandbox_timeout_seconds * 1000),
                "max_file_bytes": MAX_ARTIFACT_BYTES,
            },
        },
        MAX_ARTIFACT_RESPONSE_BYTES,
    )
    stdout, stderr, exit_code = _execution_fields(response)
    artifact = response.get("artifact")
    if not isinstance(artifact, dict):
        raise WorkflowSandboxError("Code sandbox returned an invalid artifact.")
    try:
        content = base64.b64decode(artifact.get("content_base64"), validate=True)
    except (TypeError, ValueError, binascii.Error) as exc:
        raise WorkflowSandboxError("Code sandbox returned an invalid artifact.") from exc
    size_bytes = artifact.get("size_bytes")
    digest = artifact.get("sha256")
    if (
        artifact.get("format") != artifact_format
        or artifact.get("filename") != filename
        or not isinstance(size_bytes, int)
        or isinstance(size_bytes, bool)
        or size_bytes != len(content)
        or not 0 < size_bytes <= MAX_ARTIFACT_BYTES
        or not isinstance(digest, str)
        or not hmac.compare_digest(digest, hashlib.sha256(content).hexdigest())
    ):
        raise WorkflowSandboxError("Code sandbox returned an invalid artifact.")
    return ArtifactSandboxResult(
        content=content,
        format=artifact_format,
        filename=filename,
        size_bytes=size_bytes,
        sha256=digest,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
    )
