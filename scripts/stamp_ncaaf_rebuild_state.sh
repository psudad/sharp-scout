#!/usr/bin/env bash
# Record a successful full NCAAF board rebuild for staleness / backup gates.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/data"
printf '{"last_rebuild": "%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%S+00:00)" > "$ROOT/data/ncaaf_rebuild_state.json"
