#!/usr/bin/env bash
# Merge a PR only when its head carries gate/local = success (scripts/ci.sh): the one way anything reaches main.
# Usage: scripts/merge.sh <pr-number>
set -euo pipefail
repo=$(gh repo view --json nameWithOwner -q .nameWithOwner)
sha=$(gh api "repos/$repo/pulls/$1" -q .head.sha)
state=$(gh api "repos/$repo/commits/$sha/statuses" -q '[.[] | select(.context=="gate/local")][0].state')
[ "$state" = success ] || { echo "PR $1 head $sha: gate/local is '${state:-absent}' — run scripts/ci.sh first"; exit 1; }
# in `development` every mutant must have run: a pass of the fast gate (GATE=fast) does not count
mode=${GATE_MODE:-development}
desc=$(gh api "repos/$repo/commits/$sha/statuses" -q '[.[] | select(.context=="gate/local")][0].description')
[ "$mode" = live ] || ! grep -qE '^(fast|gate:fast) ' <<<"$desc" || { echo "PR $1: Gate is ${mode:-development}, but gate/local ran the fast gate — run scripts/ci.sh with GATE unset"; exit 1; }
gh api -X PUT "repos/$repo/pulls/$1/merge" -f merge_method=merge -f sha="$sha" >/dev/null
echo "merged PR $1 at $sha"
