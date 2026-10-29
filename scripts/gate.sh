#!/usr/bin/env bash
# The whole gate, in order; the first red stops it. Lint holds complexity <= 10, nesting <= 3 and 40 statements per
# function (pyproject.toml) as errors: this code was written under the rules, so no budget is pinned. The suite runs on
# recorded model replies only (REPLAY=1: a cache miss is an error, never a live call).
# GATE_MUTANTS=changed runs only the mutants a change touches (`Gate: live`); unset runs every one (`Gate: development`).
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/ruff check .
npx --no-install jscpd . --format python --min-lines 5 --min-tokens 50 --threshold 0 --silent \
  --ignore "**/.venv/**,**/node_modules/**,**/data/**,**/cache/**,**/docs/**,**/.claude/**"
REPLAY=1 .venv/bin/python -m pytest
node test/floorguard.test.js
node test/floorguard.js
EG_MUTANTS=${GATE_MUTANTS:-} node test/mutants.js
