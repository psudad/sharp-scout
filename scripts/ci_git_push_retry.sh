#!/usr/bin/env bash
# Commit staged changes, pull --rebase, push. On rebase conflict: reset to origin/main,
# optionally rerun a pipeline command, restage, retry (up to 2 retries after the first).
set -euo pipefail

COMMIT_MSG="${1:?commit message required}"
shift || true
RERUN=("$@")
# Space-separated paths to restage after a conflict reset (optional)
ADD_PATHS="${ADD_PATHS:-}"

MAX_ATTEMPTS=3
attempt=1

while (( attempt <= MAX_ATTEMPTS )); do
  if [[ -n "$ADD_PATHS" ]]; then
    # shellcheck disable=SC2086
    "$(dirname "$0")/ci_git_add_paths.sh" $ADD_PATHS
  fi
  if git diff --staged --quiet; then
    echo "No staged changes to commit"
    exit 0
  fi
  git commit -m "$COMMIT_MSG"
  if git pull --rebase origin main; then
    if git push origin HEAD:main; then
      echo "Push succeeded on attempt ${attempt}"
      exit 0
    fi
    echo "Push failed on attempt ${attempt}"
  else
    echo "Rebase conflict on attempt ${attempt} — resetting to origin/main"
    git rebase --abort 2>/dev/null || true
    git fetch origin main
    git reset --hard origin/main
    if ((${#RERUN[@]} > 0)); then
      echo "Re-running: ${RERUN[*]}"
      "${RERUN[@]}"
    fi
  fi
  ((attempt++)) || true
done

echo "Failed to push after ${MAX_ATTEMPTS} attempts"
exit 1
