#!/usr/bin/env bash
# Run the full frontend suite under coverage and print total line coverage.
#
# Must run serial with --isolate: bun's parallel worker mode inflates the
# executable-line count (LF) in its lcov output, and the merged report
# under-represents coverage. `--isolate` gives each file a fresh global
# object (no cross-file state leaks) while keeping a single-process,
# consistent LF.
#
# Usage: scripts/coverage.sh [--detail]
set -euo pipefail
cd "$(dirname "$0")/.."

COV_DIR="$(mktemp -d)"
trap 'rm -rf "$COV_DIR"' EXIT

bun test --isolate --coverage --coverage-reporter=lcov --coverage-dir="$COV_DIR" >/dev/null 2>&1

python3 - "$COV_DIR" "${1:-}" <<'EOF'
import glob
import sys

cov_dir, detail = sys.argv[1], sys.argv[2] == "--detail"
files: dict[str, tuple[int, int]] = {}
tot_lf = tot_lh = 0
for path in glob.glob(f"{cov_dir}/**/*lcov*", recursive=True):
    cur = None
    lf = lh = 0
    with open(path) as handle:
        for line in handle:
            if line.startswith("SF:"):
                cur = line[3:].strip()
            elif line.startswith("LF:"):
                lf = int(line[3:])
            elif line.startswith("LH:"):
                lh = int(line[3:])
            elif line.startswith("end_of_record"):
                files[cur] = (lf, lh)
                tot_lf += lf
                tot_lh += lh
print(f"FRONTEND TOTAL LINES: {tot_lh}/{tot_lf} = {100 * tot_lh / tot_lf:.2f}%")
below = sorted(
    ((k, v) for k, v in files.items() if v[0] > 0 and v[1] / v[0] < 0.95),
    key=lambda kv: kv[1][0] - kv[1][1],
    reverse=True,
)
print(f"files below 95%: {len(below)}")
if detail:
    for k, (lf, lh) in below:
        print(f"  {100 * lh / lf:5.1f}% miss={lf - lh:4d} {k}")
EOF
