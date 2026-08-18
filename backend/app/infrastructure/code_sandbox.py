import asyncio
from dataclasses import dataclass
import json
from typing import Any

from app.infrastructure.config import Settings

RESULT_MARKER = "__NEXAFLOW_RESULT__="
MAX_RESPONSE_BYTES = 128 * 1024


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

    async def exchange() -> dict[str, Any]:
        reader, writer = await asyncio.open_unix_connection(
            settings.workflow_sandbox_socket,
            limit=MAX_RESPONSE_BYTES,
        )
        try:
            writer.write(
                (json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
            )
            await writer.drain()
            line = await reader.readline()
            if not line or len(line) > MAX_RESPONSE_BYTES:
                raise WorkflowSandboxError("Code sandbox returned an invalid response.")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise WorkflowSandboxError("Code sandbox returned an invalid response.")
            return value
        finally:
            writer.close()
            await writer.wait_closed()

    try:
        response = await asyncio.wait_for(
            exchange(),
            timeout=settings.workflow_sandbox_timeout_seconds + 1,
        )
    except (OSError, TimeoutError, ValueError) as exc:
        raise WorkflowSandboxError("Code sandbox is unavailable.") from exc

    stdout = str(response.get("stdout") or "")
    stderr = str(response.get("stderr") or "")
    exit_code = response.get("exit_code")
    if response.get("ok") is not True or not isinstance(exit_code, int):
        error = response.get("error")
        reason = str(error or stderr or "Code execution failed.")
        if error == "sandbox_busy":
            raise WorkflowSandboxBusyError(reason)
        raise WorkflowSandboxError(reason[:1000])
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
