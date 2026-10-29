#!/usr/bin/env bash
# The one CI job: scripts/gate.sh in a FRESH CLONE of the pushed SHA (nothing from this checkout), posted to GitHub as
# the status `gate/local`. scripts/merge.sh refuses without it. GATE_MODE picks the mutants: `development` (the default)
# runs every one, `live` only those the change touches.
# Usage: scripts/ci.sh [ref]   (default: the current branch's pushed head)
set -euo pipefail
repo=$(gh repo view --json nameWithOwner -q .nameWithOwner)
ref=${1:-origin/$(git rev-parse --abbrev-ref HEAD)}
git fetch -q origin
sha=$(git rev-parse "$ref")
mode=${GATE_MODE:-development}
if [ "$mode" = live ]; then sel=changed; else sel=; fi
post(){ gh api -X POST "repos/$repo/statuses/$sha" -f state="$1" -f context=gate/local -f description="$2" >/dev/null; }
post pending "fresh clone + scripts/gate.sh (${mode:-development})"
dir=$(mktemp -d); log="$dir/gate.log"; start=$(date +%s)
if git clone -q "https://github.com/$repo.git" "$dir/repo" && cd "$dir/repo" && git checkout -q --detach "$sha" \
   && npm ci --silent >"$log" 2>&1 && uv sync -q --locked >>"$log" 2>&1 \
   && GATE_MUTANTS=$sel scripts/gate.sh >>"$log" 2>&1; then
  post success "gate exit 0 in $(( ($(date +%s) - start) / 60 )) min: $(grep -m1 'mutants:' "$log" | cut -c1-80)"
  echo "gate/local success on $sha (${mode:-development})"
else
  post failure "gate failed: log $log"
  tail -20 "$log"; echo "gate/local FAILURE on $sha (log $log)"; exit 1
fi
