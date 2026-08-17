#!/usr/bin/env bash
# Run every backend regression suite under coverage and print the merged report.
# Usage: scripts/coverage.sh [--report-only]
set -euo pipefail
cd "$(dirname "$0")/.."

SUITES=(unit logger identity workspaces teams knowledge llm agents workflows tools mcp_transports test_main agent_access workflow_run_coverage workflow_node_coverage workspace_admin_coverage knowledge_domain_coverage knowledge_api_coverage agent_services_coverage agent_runtime_coverage infra_unit_coverage)

if [[ "${1:-}" != "--report-only" ]]; then
  rm -f .coverage .coverage.*
  COVERAGE_RUN_ID="$$"
  export COVERAGE_RUN_ID
  run_coverage_suite() {
    local suite="$1"
    local log_path="/tmp/nexaflow-coverage-${COVERAGE_RUN_ID}-${suite}.log"
    if KNOWLEDGE_STORAGE_DIR="/tmp/app-test-knowledge-storage-$suite" \
      uv run coverage run --source=app --data-file=".coverage.$suite" -m "tests.$suite" \
      >"$log_path" 2>&1; then
      echo "$suite tests passed"
      rm -f "$log_path"
      return 0
    fi
    cat "$log_path" >&2
    rm -f "$log_path"
    return 1
  }
  export -f run_coverage_suite
  # ponytail: four workers avoid local service starvation; override after measuring CI capacity.
  if ! printf '%s\n' "${SUITES[@]}" | xargs -P "${COVERAGE_JOBS:-4}" -n 1 \
    bash -c 'run_coverage_suite "$1"' _; then
    echo "one or more suites failed" >&2
    exit 1
  fi
fi

uv run coverage combine .coverage.*
uv run coverage report -m
