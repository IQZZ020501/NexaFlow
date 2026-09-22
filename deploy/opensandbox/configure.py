"""Generate a private OpenSandbox 0.2.3 config on a dedicated execution host.

This deliberately does not load NexaFlow's .env, start Docker, or deploy services.
The operator supplies only the execution control-plane API key via the environment.
"""

import argparse
import json
import os
import sys
from pathlib import Path


def server_config(state_dir: Path, api_key: str, *, development: bool) -> str:
    if not api_key.strip():
        raise ValueError("OPENSANDBOX_API_KEY is required.")
    quoted = json.dumps
    secure_runtime = (
        ""
        if development
        else '\n[secure_runtime]\ntype = "kata"\ndocker_runtime = "kata-runtime"\n'
    )
    return f"""# Generated for opensandbox-server==0.2.3; keep this file private.
[server]
host = "127.0.0.1"
port = 8088
api_key = {quoted(api_key)}
max_sandbox_timeout_seconds = 360

[runtime]
type = "docker"
execd_image = "opensandbox/execd:v1.0.22"

[store]
type = "sqlite"
path = {quoted(str(state_dir / "sandboxes.db"))}

[storage]
allowed_host_paths = []

[docker]
network_mode = "bridge"
pids_limit = 96
no_new_privileges = true
drop_capabilities = ["AUDIT_WRITE", "MKNOD", "NET_ADMIN", "NET_RAW", "SYS_ADMIN", "SYS_MODULE", "SYS_PTRACE", "SYS_TIME", "SYS_TTY_CONFIG"]
sandbox_env = {{}}
sandbox_binds = []

[ingress]
mode = "direct"

[egress]
image = "opensandbox/egress:v1.1.7"
mode = "dns+nft"
disable_ipv6 = true
readiness_timeout = 30
{secure_runtime}"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument(
        "--development",
        action="store_true",
        help="Explicitly use ordinary Docker for local checks; never use for multi-tenant production.",
    )
    arguments = parser.parse_args()
    if sys.platform == "win32":
        parser.error("Run the execution host under Linux or WSL2.")
    directory = arguments.state_dir.expanduser().resolve()
    if directory == Path(directory.anchor) or directory == Path.home():
        parser.error("Use a dedicated private state directory.")
    try:
        config = server_config(
            directory,
            os.getenv("OPENSANDBOX_API_KEY", ""),
            development=arguments.development,
        )
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = directory.stat()
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError(
                "State directory must be owned by this user with mode 0700."
            )
        target = directory / "server.toml"
        # No accidental overwrite of an operator's existing configuration.
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(config)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Created private configuration: {target}")


if __name__ == "__main__":
    main()
