#!/usr/bin/env bash
# Run the sandbox extended tests under coverage and print the merged report.
#
# Excluded from measurement:
# - sandbox/child.py: executed via os.execve with `-S` (no site import), so a
#   coverage tracer cannot be injected; its rlimit behavior is verified
#   behaviorally by self_check (file-size / open-file / wall-clock limits).
# - sandbox/launcher.py: Linux root namespace/chroot setup cannot retain the
#   host coverage tracer; the CI embedded-Worker self-check exercises it.
# - sandbox/self_check.py, sandbox/tests.py: test code, not product code.
set -euo pipefail
cd "$(dirname "$0")"

COV="$(uv run --project . which coverage)"
export SANDBOX_COVERAGE_BIN="$COV"
export PYTHONPATH="$(cd .. && pwd)"

rm -f .coverage.sandbox*
OMIT="$(pwd)/child.py,$(pwd)/launcher.py,$(pwd)/self_check.py,$(pwd)/tests.py"
"$COV" run --source=sandbox --parallel-mode --data-file=.coverage.sandbox \
  --omit="$OMIT" -m sandbox.tests
"$COV" combine .coverage.sandbox*
"$COV" report -m
