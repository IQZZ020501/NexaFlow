"""One bounded job inside an OpenSandbox image; never imported by the backend.

Container/VM isolation and egress are OpenSandbox's responsibility. This runner
adds per-program limits and a small result protocol, not a second sandbox broker.
"""

import asyncio
import base64
import hashlib
import json
import math
import os
import re
import resource
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath

MAX_INPUT = 8 * 1024 * 1024
MAX_LOG = 128 * 1024
MAX_FILE = 5 * 1024 * 1024
BUILTIN_SKILLS = {
    "documents": "docx",
    "pdf": "pdf",
    "pptx": "pptx",
    "spreadsheets": "xlsx",
}
SKILLS_DIR = Path(__file__).parent / "skills"
PACKAGE_DIR = Path("/tmp/nexaflow-skill")


def limits(seconds, address_space=True):
    resource.setrlimit(
        resource.RLIMIT_CPU, (math.ceil(seconds), math.ceil(seconds) + 1)
    )
    # V8 reserves a large virtual address range. Its physical memory is bounded
    # by the OpenSandbox container/VM cgroup, not RLIMIT_AS.
    if address_space:
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    # Permit one sentinel byte so an oversized write cannot be silently
    # truncated to an apparently valid 5 MiB artifact by RLIMIT_FSIZE.
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_FILE + 1,) * 2)
    resource.setrlimit(resource.RLIMIT_NOFILE, (64,) * 2)
    resource.setrlimit(resource.RLIMIT_NPROC, (32,) * 2)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


async def mcp_request(request):
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters, stdio_client

    config = request["config"]
    transport = stdio_client(
        StdioServerParameters(
            command=config["command"],
            args=config.get("args", []),
            cwd=config.get("cwd"),
            env=config.get("env", {}),
        )
    )
    async with Client(
        transport, cache=None, read_timeout_seconds=request["timeout"]
    ) as client:
        if request["operation"] == "discover":
            tools = []
            cursor = None
            for _ in range(32):
                page = await client.list_tools(cursor=cursor, cache_mode="reload")
                tools.extend(page.tools)
                if len(tools) > 64:
                    raise ValueError("MCP server exposes too many tools.")
                cursor = page.next_cursor
                if cursor is None:
                    return {
                        "tools": [
                            tool.model_dump(
                                mode="json", by_alias=True, exclude_none=True
                            )
                            for tool in tools
                        ]
                    }
            raise ValueError("MCP server returned too many tool pages.")
        result = await client.call_tool(
            request["name"], request["arguments"], meta=request.get("meta")
        )
        return result.model_dump(mode="json", by_alias=True, exclude_none=True)


def child(request):
    if "mcp" in request:
        print(json.dumps(asyncio.run(mcp_request(request["mcp"])), ensure_ascii=False))
    else:
        exec(
            compile(request["code"], "<nexaflow-program>", "exec"),
            {"__name__": "__main__"},
        )


def execute(request):
    max_log = 2 * 1024 * 1024 if "mcp" in request else MAX_LOG
    seconds = request.get("limits", {}).get("timeout_ms", 5000) / 1000
    if not 0.1 <= seconds <= (300 if "mcp" in request else 120):
        raise ValueError("Invalid execution timeout.")
    skill = request.get("skill")
    artifact = request.get("artifact")
    if skill and (
        skill not in BUILTIN_SKILLS
        or not artifact
        or artifact.get("format") != BUILTIN_SKILLS[skill]
    ):
        raise ValueError("Invalid built-in Skill.")
    selected = request.get("skills", [])
    if not isinstance(selected, list) or any(
        name not in BUILTIN_SKILLS for name in selected
    ):
        raise ValueError("Unavailable runtime Skill.")
    if artifact and (
        not isinstance(artifact.get("filename"), str)
        or not re.fullmatch(r"[^/\\\x00]{1,255}", artifact["filename"])
        or artifact["filename"] in {".", ".."}
    ):
        raise ValueError("Invalid artifact filename.")
    with tempfile.TemporaryDirectory(prefix="nexaflow-job-") as temporary:
        directory = Path(temporary)
        output = directory / (artifact["filename"] if artifact else "output")
        env = {
            "PATH": f"{Path(sys.executable).parent}:/usr/local/bin:/usr/bin:/bin",
            "HOME": temporary,
            "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "NEXAFLOW_OUTPUT_PATH": str(output),
            "NEXAFLOW_SKILLS_DIR": str(SKILLS_DIR),
        }
        # Only version-pinned package files arrive here, never host paths.
        bundle_files = request.get("files", {})
        if not isinstance(bundle_files, dict) or len(bundle_files) > 64:
            raise ValueError("Invalid Skill files.")
        for name in bundle_files:
            path = PurePosixPath(name)
            if (
                path.is_absolute()
                or any(part in {".", ".."} for part in name.split("/"))
                or "\\" in name
            ):
                raise ValueError("Invalid Skill file path.")
        if bundle_files:
            env["NEXAFLOW_SKILL_DIR"] = str(PACKAGE_DIR)
        if request.get("script"):
            script = request["script"]
            if script not in bundle_files or PurePosixPath(script).suffix not in {
                ".py",
                ".js",
            }:
                raise ValueError("Script is not in the pinned package.")
            if script.endswith(".py"):
                # Isolated Python normally hides the script directory. Expose
                # only the pinned package so bundled helper imports still work.
                command = [
                    sys.executable,
                    "-I",
                    "-c",
                    "import runpy, sys; from pathlib import Path; "
                    "p = sys.argv[1]; sys.path[:0] = [str(Path(p).parent), sys.argv[2]]; "
                    "sys.argv = [p]; runpy.run_path(p, run_name='__main__')",
                    str(PACKAGE_DIR / script),
                    str(PACKAGE_DIR),
                ]
            else:
                command = ["/usr/local/bin/node", str(PACKAGE_DIR / script)]
            stdin = request.get("stdin", "").encode()
        elif skill:
            command = [
                sys.executable,
                "-I",
                str(SKILLS_DIR / skill / "scripts" / "render.py"),
            ]
            stdin = request.get("stdin", "").encode()
        elif "mcp" in request:
            command = [sys.executable, "-I", str(Path(__file__).resolve()), "--child"]
            stdin = json.dumps(request).encode()
        else:
            command = [sys.executable, "-I", "-c", request["code"]]
            stdin = request.get("stdin", "").encode()
        input_path = directory / "stdin"
        input_path.write_bytes(stdin)
        with (
            input_path.open("rb") as input_stream,
            (directory / "stdout").open("w+b") as stdout,
            (directory / "stderr").open("w+b") as stderr,
        ):
            process = subprocess.Popen(
                command,
                stdin=input_stream,
                stdout=stdout,
                stderr=stderr,
                cwd=directory,
                env=env,
                start_new_session=True,
                preexec_fn=lambda: limits(
                    seconds,
                    "mcp" not in request
                    and not str(request.get("script", "")).endswith(".js"),
                ),
            )
            try:
                deadline = time.monotonic() + seconds
                while process.poll() is None:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Program execution timed out.")
                    if (
                        os.fstat(stdout.fileno()).st_size
                        + os.fstat(stderr.fileno()).st_size
                        > max_log
                    ):
                        raise ValueError("Program output exceeds 128 KiB.")
                    time.sleep(0.02)
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            stdout.seek(0)
            stderr.seek(0)
            logs = stdout.read(max_log + 1)
            errors = stderr.read(max_log + 1)
            if len(logs) + len(errors) > max_log:
                raise ValueError("Program output exceeds 128 KiB.")
            response = {
                "ok": process.returncode == 0,
                "exit_code": process.returncode,
                "stdout": logs.decode("utf-8", errors="replace"),
                "stderr": errors.decode("utf-8", errors="replace"),
            }
        if "mcp" in request and response["ok"]:
            response["mcp"] = json.loads(response["stdout"])
            response["stdout"] = ""
        if artifact and response["ok"]:
            descriptor = os.open(output, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_FILE:
                    raise ValueError(
                        "Artifact must be a regular file between 1 byte and 5 MiB."
                    )
                content = stream.read(MAX_FILE + 1)
            if not 0 < len(content) <= MAX_FILE:
                raise ValueError("Artifact exceeds 5 MiB.")
            response["artifact"] = {
                **artifact,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "content_base64": base64.b64encode(content).decode(),
            }
        return response


def main():
    if sys.argv[1] == "--child":
        child(json.loads(sys.stdin.read(MAX_INPUT + 1)))
        return
    payload = Path(sys.argv[1]).read_bytes()
    try:
        if len(payload) > MAX_INPUT:
            raise ValueError("Execution input exceeds 8 MiB.")
        response = execute(json.loads(payload))
    except Exception as exc:
        response = {
            "ok": False,
            "exit_code": 1,
            "error": f"{type(exc).__name__}: {exc}"[:1000],
        }
    Path("/tmp/nexaflow-response.json").write_text(
        json.dumps(response, ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
