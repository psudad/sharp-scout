#!/usr/bin/env bash
# Run NCAAF pipeline then apply CI post-run rules (stamp / blocked warning / fail).
# Keeps set -e off only for run_ncaaf.py so exit 3 (publish blocked) is captured.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

set +e
python "$ROOT/scripts/run_ncaaf.py" "$@"
rc=$?
set -e
exec "$ROOT/scripts/ncaaf_ci_post_run.sh" "$rc"
