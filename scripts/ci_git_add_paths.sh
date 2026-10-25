#!/usr/bin/env bash
# Stage only paths that exist (avoids git add exit 128 on optional artifacts).
set -euo pipefail
for p in "$@"; do
  if [[ -e "$p" ]]; then
    git add "$p"
  fi
done
