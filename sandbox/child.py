"""Trusted child launcher that applies rlimits before executing user code."""

from __future__ import annotations

import json
import os
import resource
import sys


def set_limit(name: str, soft: int, hard: int) -> None:
    limit = getattr(resource, name, None)
    if limit is None or (sys.platform == "darwin" and name == "RLIMIT_AS"):
        return
    resource.setrlimit(limit, (soft, hard))


def main() -> None:
    limits = json.loads(sys.argv[1])
    program = sys.argv[2]
    os.umask(0o077)
    set_limit("RLIMIT_CPU", limits["cpu_seconds"], limits["cpu_seconds"] + 1)
    set_limit("RLIMIT_AS", limits["memory_bytes"], limits["memory_bytes"])
    set_limit("RLIMIT_FSIZE", limits["max_file_bytes"], limits["max_file_bytes"])
    set_limit("RLIMIT_NPROC", limits["max_processes"], limits["max_processes"])
    set_limit("RLIMIT_NOFILE", limits["max_open_files"], limits["max_open_files"])
    set_limit("RLIMIT_CORE", 0, 0)
    environment = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
    }
    for name in ("TMPDIR", "NEXAFLOW_OUTPUT_PATH", "NEXAFLOW_SKILLS_DIR"):
        if name in os.environ:
            environment[name] = os.environ[name]
    flags = [sys.executable, "-I", "-B"]
    if os.environ.get("NEXAFLOW_ALLOW_SITE_PACKAGES") != "1":
        flags.append("-S")
    os.execve(sys.executable, [*flags, program], environment)


if __name__ == "__main__":
    main()
