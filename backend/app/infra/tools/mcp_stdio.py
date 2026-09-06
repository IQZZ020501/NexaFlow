import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_STDIO_CONFIG_JSON_CHARS = 65_536
MAX_STDIO_ARGS = 64
MAX_STDIO_ARGUMENT_CHARS = 2_000
MAX_STDIO_ENV_VARS = 32
MAX_STDIO_ENV_VALUE_CHARS = 8_000

_ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CONFIG_FIELDS = {"command", "args", "cwd", "env"}


class McpStdioConfigError(ValueError):
    pass


@dataclass(frozen=True)
class McpStdioConfig:
    command: str
    args: tuple[str, ...]
    cwd: str | None
    env: tuple[tuple[str, str], ...]


def _invalid(message: str) -> McpStdioConfigError:
    return McpStdioConfigError(f"Invalid MCP stdio configuration: {message}")


def _path_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field} must be a string.")
    normalized = value.strip()
    if not normalized or len(normalized) > 1_000 or "\0" in normalized:
        raise _invalid(f"{field} is invalid.")
    if not Path(normalized).is_absolute():
        raise _invalid(f"{field} must be an absolute path.")
    return normalized


def _raw_text(value: Any, *, field: str, max_length: int) -> str:
    if not isinstance(value, str) or len(value) > max_length or "\0" in value:
        raise _invalid(f"{field} is invalid.")
    return value


def parse_mcp_stdio_config(value: str | dict[str, Any]) -> McpStdioConfig:
    if isinstance(value, str):
        if len(value) > MAX_STDIO_CONFIG_JSON_CHARS:
            raise _invalid("configuration is too large.")
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise _invalid("configuration must be valid JSON.") from exc
    else:
        payload = value

    if not isinstance(payload, dict):
        raise _invalid("configuration must be an object.")
    unknown_fields = set(payload) - _CONFIG_FIELDS
    if unknown_fields:
        raise _invalid(
            f"unsupported fields: {', '.join(sorted(unknown_fields))}."
        )

    command = _path_text(payload.get("command"), field="command")

    raw_args = payload.get("args", [])
    if not isinstance(raw_args, list) or len(raw_args) > MAX_STDIO_ARGS:
        raise _invalid("args must be a bounded array.")
    args = tuple(
        _raw_text(
            argument,
            field="argument",
            max_length=MAX_STDIO_ARGUMENT_CHARS,
        )
        for argument in raw_args
    )

    raw_cwd = payload.get("cwd")
    cwd = _path_text(raw_cwd, field="cwd") if raw_cwd is not None else None

    raw_env = payload.get("env", {})
    if not isinstance(raw_env, dict) or len(raw_env) > MAX_STDIO_ENV_VARS:
        raise _invalid("env must be a bounded object.")
    env: list[tuple[str, str]] = []
    for name, env_value in raw_env.items():
        if (
            not isinstance(name, str)
            or len(name) > 255
            or not _ENV_NAME_PATTERN.fullmatch(name)
        ):
            raise _invalid("environment variable names are invalid.")
        env.append(
            (
                name,
                _raw_text(
                    env_value,
                    field=f"environment variable {name!r}",
                    max_length=MAX_STDIO_ENV_VALUE_CHARS,
                ),
            )
        )

    config = McpStdioConfig(
        command=command,
        args=args,
        cwd=cwd,
        env=tuple(sorted(env)),
    )
    if len(serialize_mcp_stdio_config(config)) > MAX_STDIO_CONFIG_JSON_CHARS:
        raise _invalid("configuration is too large.")
    return config


def serialize_mcp_stdio_config(config: McpStdioConfig) -> str:
    return json.dumps(
        {
            "command": config.command,
            "args": list(config.args),
            "cwd": config.cwd,
            "env": dict(config.env),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def validate_mcp_stdio_config_runtime(config: McpStdioConfig) -> None:
    command = Path(config.command)
    if not command.is_file() or not os.access(command, os.X_OK):
        raise _invalid("command is not an executable file.")
    if config.cwd is not None and not Path(config.cwd).is_dir():
        raise _invalid("cwd is not a directory.")
