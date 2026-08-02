#!/usr/bin/env bash
# Enables the repository Git hooks (`.githooks/`) for this checkout.
set -euo pipefail

git config core.hooksPath .githooks
echo "Git hooks path set to .githooks"
