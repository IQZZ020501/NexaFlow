#!/usr/bin/env bash
# Run every backend regression suite under coverage and print the merged report.
# Usage: scripts/coverage.sh [--report-only]
set -euo pipefail
cd "$(dirname "$0")/.."

SUITES=(unit logger identity workspaces teams knowledge llm agents workflows mcp_transports test_main agent_access workflow_run_coverage workflow_node_coverage workspace_admin_coverage knowledge_domain_coverage knowledge_api_coverage agent_services_coverage agent_runtime_coverage infra_unit_coverage)

if [[ "${1:-}" != "--report-only" ]]; then
  rm -f .coverage .coverage.*
  pids=()
  for suite in "${SUITES[@]}"; do
    KNOWLEDGE_STORAGE_DIR="/tmp/app-test-knowledge-storage-$suite" \
      uv run coverage run --source=app --data-file=".coverage.$suite" -m "tests.$suite" &
    pids+=("$!")
  done
  failed=0
  for pid in "${pids[@]}"; do
    wait "$pid" || failed=1
  done
  if [[ "$failed" -ne 0 ]]; then
    echo "one or more suites failed" >&2
    exit 1
  fi
fi

uv run coverage combine .coverage.*
uv run coverage report -m
