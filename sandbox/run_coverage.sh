#!/usr/bin/env bash
# Run the sandbox extended tests under coverage and print the merged report.
#
# Excluded from measurement:
# - sandbox/child.py: executed via os.execve with `-S` (no site import), so a
#   coverage tracer cannot be injected; its rlimit behavior is verified
#   behaviorally by self_check (file-size / open-file / wall-clock limits).
# - sandbox/self_check.py, sandbox/tests.py: test code, not product code.
set -euo pipefail
cd "$(dirname "$0")"

if command -v coverage >/dev/null 2>&1; then
  COV="coverage"
else
  COV="$(cd ../backend && uv run which coverage)"
fi
export SANDBOX_COVERAGE_BIN="$COV"
export PYTHONPATH="$(cd .. && pwd)"

rm -f .coverage.sandbox*
OMIT="$(pwd)/child.py,$(pwd)/self_check.py,$(pwd)/tests.py"
"$COV" run --source=sandbox --parallel-mode --data-file=.coverage.sandbox \
  --omit="$OMIT" -m sandbox.tests
"$COV" combine .coverage.sandbox*
"$COV" report -m
