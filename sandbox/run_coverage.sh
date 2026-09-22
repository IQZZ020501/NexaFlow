#!/usr/bin/env bash
# Coverage of the independent job runtime. Process limits and
# OpenSandbox isolation must also be tested behaviorally, not inferred from coverage.
set -euo pipefail
cd "$(dirname "$0")"

export PYTHONPATH="$(cd .. && pwd)"

uv run --project . coverage run --source=sandbox --data-file=.coverage.sandbox \
  --omit="$(pwd)/self_check.py,$(pwd)/tests.py,$(pwd)/renderer_checks/*" -m sandbox.tests
uv run --project . coverage report --data-file=.coverage.sandbox -m
