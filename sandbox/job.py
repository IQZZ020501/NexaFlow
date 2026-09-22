"""One bounded job inside an OpenSandbox image; never imported by the backend.

Container/VM isolation and egress are OpenSandbox's responsibility. This runner
adds per-program limits and a small result protocol, not a second sandbox broker.
"""

import asyncio
import base64
import hashlib
import importlib.metadata
import json
import math
import os
import re
import resource
import shutil
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
MAX_DEPENDENCY_FILE = 32 * 1024 * 1024
MAX_DEPENDENCY_STORAGE = 128 * 1024 * 1024
MAX_DEPENDENCY_FILES = 4096
BUILTIN_SKILLS = {
    "documents": "docx",
    "pdf": "pdf",
    "pptx": "pptx",
    "spreadsheets": "xlsx",
}
SKILLS_DIR = Path(__file__).parent / "skills"
PACKAGE_DIR = Path("/tmp/nexaflow-skill")
SESSION_DIR = Path("/tmp/nexaflow-session")


def limits(seconds, address_space=True, file_size=MAX_FILE):
    resource.setrlimit(
        resource.RLIMIT_CPU, (math.ceil(seconds), math.ceil(seconds) + 1)
    )
    # V8 reserves a large virtual address range. Its physical memory is bounded
    # by the OpenSandbox container/VM cgroup, not RLIMIT_AS.
    if address_space:
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    # Permit one sentinel byte so an oversized write cannot be silently
    # truncated to an apparently valid 5 MiB artifact by RLIMIT_FSIZE.
    resource.setrlimit(resource.RLIMIT_FSIZE, (file_size + 1,) * 2)
    resource.setrlimit(resource.RLIMIT_NOFILE, (64,) * 2)
    resource.setrlimit(resource.RLIMIT_NPROC, (32,) * 2)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _use_address_space_limit(request):
    shell = request.get("shell")
    return (
        "mcp" not in request
        and request.get("skill") != "pptx"
        and not str(request.get("script", "")).endswith(".js")
        and not (isinstance(shell, dict) and shell.get("manager") == "node")
    )


def _environment_lock(manager, python_packages, node_prefix):
    directory = python_packages if manager == "python" else node_prefix
    content = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory).as_posix().encode()
        if path.is_symlink():
            content.update(b"L\0" + relative + b"\0" + os.readlink(path).encode())
        elif path.is_file():
            content.update(b"F\0" + relative + b"\0")
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    content.update(chunk)
        content.update(b"\0")
    if manager == "python":
        packages = sorted(
            {
                (
                    str(distribution.metadata.get("Name") or "").lower(),
                    str(distribution.version),
                )
                for distribution in importlib.metadata.distributions(
                    path=[str(python_packages)]
                )
                if distribution.metadata.get("Name")
            }
        )
        value = {
            "manager": manager,
            "packages": [
                {"name": name, "version": version} for name, version in packages
            ],
        }
    else:
        lock_path = node_prefix / "package-lock.json"
        document = json.loads(lock_path.read_text()) if lock_path.exists() else {}
        locked = []
        for path, package in document.get("packages", {}).items():
            if not path or not isinstance(package, dict):
                continue
            version = package.get("version")
            if not isinstance(version, str):
                continue
            name = package.get("name")
            if not isinstance(name, str):
                name = path.rsplit("node_modules/", 1)[-1]
            item = {"name": name, "version": version}
            integrity = package.get("integrity")
            if isinstance(integrity, str):
                item["integrity"] = integrity
            locked.append(item)
        locked.sort(key=lambda item: (item["name"], item["version"]))
        value = {"manager": manager, "packages": locked}
    if len(value["packages"]) > 256:
        raise ValueError("Dependency environment contains too many packages.")
    value["content_sha256"] = content.hexdigest()
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return value, hashlib.sha256(encoded).hexdigest()


def _require_bounded_dependency_storage(*directories):
    files = 0
    total = 0
    for directory in directories:
        for path in directory.rglob("*"):
            if path.is_symlink() or not path.is_file():
                continue
            info = path.stat()
            files += 1
            total += info.st_size
            if (
                files > MAX_DEPENDENCY_FILES
                or info.st_size > MAX_DEPENDENCY_FILE
                or total > MAX_DEPENDENCY_STORAGE
            ):
                raise ValueError("Dependency environment exceeds its storage limit.")


def _replace_dependency_directory(staged, target):
    backup = target.parent / f".{target.name}.backup"
    shutil.rmtree(backup, ignore_errors=True)
    target.rename(backup)
    try:
        staged.rename(target)
    except BaseException:
        if not target.exists() and backup.exists():
            backup.rename(target)
        raise
    shutil.rmtree(backup)


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
    environment_id = request.get("skill_environment")
    if environment_id is not None and (
        not isinstance(environment_id, str)
        or re.fullmatch(r"[a-f0-9]{32}", environment_id) is None
    ):
        raise ValueError("Invalid Skill environment.")
    shell = request.get("shell")
    if shell is not None:
        if environment_id is None or not isinstance(shell, dict):
            raise ValueError("Skill shell requires an isolated environment.")
        if shell.get("manager") not in {"python", "node"}:
            raise ValueError("Invalid dependency manager.")
        if (
            not isinstance(shell.get("command"), str)
            or not shell["command"].strip()
            or len(shell["command"]) > 4096
            or "\x00" in shell["command"]
        ):
            raise ValueError("Invalid Skill shell command.")
        if (
            not isinstance(shell.get("bootstrap_id"), str)
            or re.fullmatch(r"[a-f0-9]{64}", shell["bootstrap_id"]) is None
        ):
            raise ValueError("Invalid Skill dependency identity.")
    package_dir = PACKAGE_DIR / environment_id if environment_id else PACKAGE_DIR
    environment_dir = SESSION_DIR / environment_id if environment_id else None
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
        if skill == "pptx":
            node_binary = shutil.which("node")
            if node_binary is not None:
                env["NEXAFLOW_NODE_BINARY"] = node_binary
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
        runtime_package = package_dir
        if bundle_files and environment_id:
            runtime_package = directory / "skill"
            shutil.copytree(package_dir, runtime_package)
        if bundle_files:
            env["NEXAFLOW_SKILL_DIR"] = str(runtime_package)
        python_packages = None
        node_prefix = None
        if environment_dir is not None:
            python_packages = environment_dir / "python"
            node_prefix = environment_dir / "node"
            python_packages.mkdir(parents=True, exist_ok=True)
            node_prefix.mkdir(parents=True, exist_ok=True)
            env["NEXAFLOW_PYTHON_PACKAGES"] = str(python_packages)
            env["NEXAFLOW_NODE_PREFIX"] = str(node_prefix)
            env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
            env["PIP_NO_INPUT"] = "1"
            env["NPM_CONFIG_AUDIT"] = "false"
            env["NPM_CONFIG_FUND"] = "false"
            env["NPM_CONFIG_IGNORE_SCRIPTS"] = "true"
        staged_dependency_dir = None
        staged_python_packages = python_packages
        staged_node_prefix = node_prefix
        if shell is not None:
            assert environment_dir is not None
            assert python_packages is not None and node_prefix is not None
            marker_dir = environment_dir / ".bootstrap"
            marker_dir.mkdir(parents=True, exist_ok=True)
            marker = marker_dir / f"{shell['bootstrap_id']}.json"
            if marker.exists():
                stored = json.loads(marker.read_text())
                current_lock, current_hash = _environment_lock(
                    shell["manager"], python_packages, node_prefix
                )
                if stored.get("environment_hash") == current_hash:
                    return {
                        "ok": True,
                        "exit_code": 0,
                        "stdout": "",
                        "stderr": "",
                        "bootstrap_skipped": True,
                        "environment_lock": current_lock,
                        "environment_hash": current_hash,
                    }
            manager = shell["manager"]
            dependency_dir = python_packages if manager == "python" else node_prefix
            staged_dependency_dir = environment_dir / (
                f".{manager}.{shell['bootstrap_id']}.staging"
            )
            shutil.rmtree(staged_dependency_dir, ignore_errors=True)
            shutil.copytree(dependency_dir, staged_dependency_dir)
            if manager == "python":
                staged_python_packages = staged_dependency_dir
                env["NEXAFLOW_PYTHON_PACKAGES"] = str(staged_dependency_dir)
            else:
                staged_node_prefix = staged_dependency_dir
                env["NEXAFLOW_NODE_PREFIX"] = str(staged_dependency_dir)
            command = [
                "/bin/bash",
                "--noprofile",
                "--norc",
                "-c",
                shell["command"],
            ]
            stdin = b""
        elif request.get("script"):
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
                    "-B",
                    "-c",
                    (
                        "import runpy, sys; from pathlib import Path; "
                        "p = sys.argv[1]; "
                        "sys.path[:0] = [str(Path(p).parent), sys.argv[2]]; "
                        "sys.path.insert(2, sys.argv[3]) if sys.argv[3] else None; "
                        "sys.argv = [p]; "
                        "runpy.run_path(p, run_name='__main__')"
                    ),
                    str(runtime_package / script),
                    str(runtime_package),
                    str(python_packages) if python_packages is not None else "",
                ]
            else:
                if node_prefix is not None and (node_prefix / "node_modules").exists():
                    (runtime_package / "node_modules").symlink_to(
                        node_prefix / "node_modules",
                        target_is_directory=True,
                    )
                command = ["/usr/local/bin/node", str(runtime_package / script)]
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
                    # npm runs on V8 and reserves a large virtual heap just like
                    # a JavaScript Skill; the sandbox cgroup remains authoritative.
                    _use_address_space_limit(request),
                    MAX_DEPENDENCY_FILE if shell is not None else MAX_FILE,
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
        if shell is not None and response["ok"]:
            assert environment_dir is not None
            assert python_packages is not None and node_prefix is not None
            assert staged_dependency_dir is not None
            assert staged_python_packages is not None
            assert staged_node_prefix is not None
            try:
                _require_bounded_dependency_storage(
                    staged_python_packages,
                    staged_node_prefix,
                )
                environment_lock, environment_hash = _environment_lock(
                    shell["manager"],
                    staged_python_packages,
                    staged_node_prefix,
                )
                target = (
                    python_packages if shell["manager"] == "python" else node_prefix
                )
                _replace_dependency_directory(staged_dependency_dir, target)
            except BaseException:
                shutil.rmtree(staged_dependency_dir, ignore_errors=True)
                raise
            response["environment_lock"] = environment_lock
            response["environment_hash"] = environment_hash
            marker.write_text(
                json.dumps(
                    {
                        "environment_lock": environment_lock,
                        "environment_hash": environment_hash,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        elif staged_dependency_dir is not None:
            shutil.rmtree(staged_dependency_dir, ignore_errors=True)
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
