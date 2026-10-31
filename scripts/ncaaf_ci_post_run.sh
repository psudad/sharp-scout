#!/usr/bin/env bash
# Handle run_ncaaf.py exit codes in CI (ncaaf.yml, refresh-board.yml, commit re-runs).
#
# Usage: python scripts/run_ncaaf.py …; scripts/ncaaf_ci_post_run.sh $?
#
# Exit 0 + stamp only when the pipeline published successfully.
# Exit 0 without stamp when publish was blocked (dedicated code below).
# Propagate any other non-zero exit (real failures).

set -euo pipefail

# Must match sharp_scout.ncaaf.publish_gate.EXIT_PUBLISH_BLOCKED
PUBLISH_BLOCKED=3

RC="${1:?pass run_ncaaf.py exit code as first argument}"

if [ "$RC" -eq "$PUBLISH_BLOCKED" ]; then
  echo "::warning::NCAAF pipeline finished but docs publish was blocked (see log above)."
  exit 0
fi

if [ "$RC" -ne 0 ]; then
  exit "$RC"
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/scripts/stamp_ncaaf_rebuild_state.sh"
