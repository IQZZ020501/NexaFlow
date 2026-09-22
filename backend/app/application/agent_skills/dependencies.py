"""Explicit, approval-backed dependency installation for executable Skills."""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal

from app.application.agent_skills.execution import load_authorized_run_skill
from app.application.tools.runtime.contracts import (
    ToolInvocationContext,
    ToolRuntimeResult,
)
from app.infra.sandbox.client import WorkflowSandboxError, _execution_fields
from app.ports.execution import build_execution_platform

DependencyManager = Literal["python", "node"]
MAX_DEPENDENCIES = 16
PYTHON_PACKAGE_DOMAINS = ("pypi.org", "files.pythonhosted.org")
NODE_PACKAGE_DOMAINS = ("registry.npmjs.org",)

_PYTHON_REQUIREMENT = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"
    r"(?:\[[A-Za-z0-9][A-Za-z0-9._-]*(?:,[A-Za-z0-9][A-Za-z0-9._-]*)*\])?"
    r"==[0-9][A-Za-z0-9._+!-]{0,127}"
)
_NODE_REQUIREMENT = re.compile(
    r"(?:@[a-z0-9][a-z0-9._-]{0,127}/)?[a-z0-9][a-z0-9._-]{0,127}"
    r"@[0-9]+\.[0-9]+\.[0-9]+"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?"
)


@dataclass(frozen=True)
class DependencyInstallPlan:
    manager: DependencyManager
    packages: tuple[str, ...]
    command: str
    bootstrap_id: str
    network_domains: tuple[str, ...]


def dependency_install_plan(
    manager: str,
    packages: list[str],
) -> DependencyInstallPlan:
    if manager not in {"python", "node"}:
        raise ValueError("Dependency manager must be python or node.")
    if (
        not isinstance(packages, list)
        or not packages
        or len(packages) > MAX_DEPENDENCIES
        or any(not isinstance(item, str) for item in packages)
    ):
        raise ValueError("Dependency installation requires 1 to 16 packages.")
    normalized = tuple(sorted(set(packages)))
    pattern = _PYTHON_REQUIREMENT if manager == "python" else _NODE_REQUIREMENT
    if any(pattern.fullmatch(item) is None for item in normalized):
        raise ValueError(
            "Dependencies must use exact registry versions; URLs, paths, ranges, "
            "tags, options, and unpinned packages are not allowed."
        )
    if manager == "python":
        command = (
            'uv pip install --target "$NEXAFLOW_PYTHON_PACKAGES" '
            "--only-binary :all: --upgrade "
            + " ".join(normalized)
        )
        domains = PYTHON_PACKAGE_DOMAINS
    else:
        command = (
            'npm install --prefix "$NEXAFLOW_NODE_PREFIX" --ignore-scripts '
            "--no-audit --no-fund --save-exact "
            + " ".join(normalized)
        )
        domains = NODE_PACKAGE_DOMAINS
    canonical = json.dumps(
        {"manager": manager, "packages": normalized},
        sort_keys=True,
        separators=(",", ":"),
    )
    return DependencyInstallPlan(
        manager=manager,
        packages=normalized,
        command=command,
        bootstrap_id=hashlib.sha256(canonical.encode()).hexdigest(),
        network_domains=domains,
    )


def skill_environment_id(version_id: str) -> str:
    return hashlib.sha256(version_id.encode()).hexdigest()[:32]


def dependency_shell_request(
    snapshot,
    plan: DependencyInstallPlan,
) -> dict:
    return {
        "execution_session": "agent_run",
        "skill_environment": skill_environment_id(snapshot.version_id),
        "files": snapshot.definition["files"],
        "shell": {
            "manager": plan.manager,
            "command": plan.command,
            "bootstrap_id": plan.bootstrap_id,
        },
        "network_domains": list(plan.network_domains),
        "limits": {
            "timeout_ms": round(
                snapshot.definition.get("execution_timeout_seconds", 30) * 1000
            )
        },
    }


def _require_package_domains(settings, plan: DependencyInstallPlan) -> None:
    missing = sorted(set(plan.network_domains) - set(settings.opensandbox_egress_domains))
    if missing:
        raise ValueError(
            "Skill dependency installation is disabled until these package registry "
            "domains are deployment-approved: "
            + ", ".join(missing)
            + "."
        )


async def execute_skill_dependency_install(
    settings,
    arguments: dict,
    context: ToolInvocationContext,
) -> ToolRuntimeResult:
    snapshot = await load_authorized_run_skill(
        settings,
        context,
        arguments["version_id"],
    )
    plan = dependency_install_plan(arguments["manager"], arguments["packages"])
    _require_package_domains(settings, plan)
    response = await build_execution_platform(settings).execute(
        dependency_shell_request(snapshot, plan),
        timeout_seconds=snapshot.definition.get("execution_timeout_seconds", 30),
        max_output_bytes=256 * 1024,
    )
    try:
        stdout, stderr, exit_code = _execution_fields(response)
    except WorkflowSandboxError as exc:
        raise ValueError(str(exc)) from exc
    environment_hash = response.get("environment_hash")
    environment_lock = response.get("environment_lock")
    if (
        not isinstance(environment_hash, str)
        or not re.fullmatch(r"[a-f0-9]{64}", environment_hash)
        or not isinstance(environment_lock, dict)
    ):
        raise ValueError("Dependency installer returned an invalid environment lock.")
    return ToolRuntimeResult(
        ok=True,
        data={
            "manager": plan.manager,
            "packages": list(plan.packages),
            "environment_hash": environment_hash,
            "environment_lock": environment_lock,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
        },
        summary="Skill dependencies installed.",
        error_code=None,
        error_message=None,
        outcome="confirmed",
        usage={"exit_code": exit_code},
    )


__all__ = [
    "DependencyInstallPlan",
    "dependency_install_plan",
    "dependency_shell_request",
    "execute_skill_dependency_install",
    "skill_environment_id",
]
