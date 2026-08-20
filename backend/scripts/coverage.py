from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


SUITES = (
    "unit",
    "logger",
    "smtp",
    "email",
    "system_governance",
    "identity",
    "workspaces",
    "teams",
    "knowledge",
    "llm",
    "agents",
    "workflows",
    "tools",
    "mcp_transports",
    "test_main",
    "agent_access",
    "workflow_run_coverage",
    "workflow_node_coverage",
    "workspace_admin_coverage",
    "knowledge_domain_coverage",
    "knowledge_api_coverage",
    "agent_services_coverage",
    "agent_runtime_coverage",
    "infra_unit_coverage",
)
COMMAND_TIMEOUT_SECONDS = 30 * 60


def _run_suite(suite: str, run_id: int) -> tuple[str, int, Path]:
    log_path = Path(tempfile.gettempdir()) / f"nexaflow-coverage-{run_id}-{suite}.log"
    environment = os.environ.copy()
    environment["COVERAGE_RUN_ID"] = str(run_id)
    environment["KNOWLEDGE_STORAGE_DIR"] = str(
        Path(tempfile.gettempdir()) / f"app-test-knowledge-storage-{suite}"
    )
    with log_path.open("wb") as log:
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "coverage",
                    "run",
                    "--concurrency=thread,greenlet",
                    "--source=app",
                    f"--data-file=.coverage.{suite}",
                    "-m",
                    f"tests.{suite}",
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                env=environment,
                check=False,
                timeout=COMMAND_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            log.write(
                f"{suite} timed out after {COMMAND_TIMEOUT_SECONDS} seconds\n".encode()
            )
            return suite, 124, log_path
    return suite, result.returncode, log_path


def _run_suites(jobs: int) -> bool:
    run_id = os.getpid()
    passed = True
    # ponytail: four workers avoid local service starvation; tune after measuring CI.
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        futures = [executor.submit(_run_suite, suite, run_id) for suite in SUITES]
        for future in as_completed(futures):
            suite, returncode, log_path = future.result()
            if returncode == 0:
                print(f"{suite} tests passed", flush=True)
            else:
                passed = False
                sys.stderr.write(log_path.read_text(errors="replace"))
            log_path.unlink(missing_ok=True)
    return passed


def _coverage_files() -> list[str]:
    return [str(path) for path in sorted(Path.cwd().glob(".coverage.*"))]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()

    os.chdir(Path(__file__).resolve().parents[1])
    if not args.report_only:
        Path(".coverage").unlink(missing_ok=True)
        for path in Path.cwd().glob(".coverage.*"):
            path.unlink()
        try:
            jobs = max(1, int(os.environ.get("COVERAGE_JOBS", "4")))
        except ValueError:
            parser.error("COVERAGE_JOBS must be an integer")
        if not _run_suites(jobs):
            print("one or more suites failed", file=sys.stderr)
            return 1

    files = _coverage_files()
    try:
        if files:
            subprocess.run(
                [sys.executable, "-m", "coverage", "combine", *files],
                check=True,
                timeout=COMMAND_TIMEOUT_SECONDS,
            )
        elif not Path(".coverage").exists():
            print("no coverage data found", file=sys.stderr)
            return 1
        return subprocess.run(
            [sys.executable, "-m", "coverage", "report", "--fail-under=97", "-m"],
            check=False,
            timeout=COMMAND_TIMEOUT_SECONDS,
        ).returncode
    except subprocess.TimeoutExpired:
        print(
            f"coverage command timed out after {COMMAND_TIMEOUT_SECONDS} seconds",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
