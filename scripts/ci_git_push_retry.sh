#!/usr/bin/env bash
# Commit staged changes, pull --rebase, push. On rebase conflict: reset to origin/main,
# optionally rerun a pipeline command, restage, retry (up to 2 retries after the first).
#
# Also refuses to commit (and treats as a retryable conflict) any file containing
# git conflict markers. `git pull --rebase --autostash` can leave
# "<<<<<<< Updated upstream / >>>>>>> Stashed changes" in the worktree even
# when the rebase itself reports success; a later pass then committed them.
set -euo pipefail

COMMIT_MSG="${1:?commit message required}"
shift || true
RERUN=("$@")
# Space-separated paths to restage after a conflict reset (optional)
ADD_PATHS="${ADD_PATHS:-}"

MAX_ATTEMPTS=5
attempt=1

conflict_marker_files() {
  # List tracked or staged files that contain conflict markers.
  local files=""
  local f
  while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    if [[ -f "$f" ]] && grep -q -E '^<<<<<<< |^>>>>>>> ' "$f"; then
      files+="$f"$'\n'
    fi
  done < <(git diff --staged --name-only --diff-filter=ACMR; git ls-files)
  if [[ -n "$files" ]]; then
    printf '%s' "$files" | sort -u
  fi
}

reset_and_rerun() {
  echo "Resetting to origin/main and rerunning"
  git rebase --abort 2>/dev/null || true
  git merge --abort 2>/dev/null || true
  git fetch origin main
  git reset --hard origin/main
  if ((${#RERUN[@]} > 0)); then
    echo "Re-running: ${RERUN[*]}"
    "${RERUN[@]}"
  fi
}

while (( attempt <= MAX_ATTEMPTS )); do
  if [[ -n "$ADD_PATHS" ]]; then
    # shellcheck disable=SC2086
    "$(dirname "$0")/ci_git_add_paths.sh" $ADD_PATHS
  fi
  if git diff --staged --quiet; then
    echo "No staged changes to commit"
    exit 0
  fi

  marked="$(conflict_marker_files || true)"
  if [[ -n "$marked" ]]; then
    echo "REFUSING to commit files that contain git conflict markers:"
    printf '%s\n' "$marked"
    echo "Rebase/autostash conflict on attempt ${attempt} — will not keep markers"
    reset_and_rerun
  else
    git commit -m "$COMMIT_MSG"
    # --autostash: pipeline steps can leave tracked files modified that are not part of
    # this commit (e.g. NBA injury refresh); plain --rebase refused with "unstaged changes".
    if git pull --rebase --autostash origin main; then
      marked="$(conflict_marker_files || true)"
      if [[ -n "$marked" ]]; then
        echo "Autostash/rebase left conflict markers after a 'successful' pull:"
        printf '%s\n' "$marked"
        echo "Not pushing this state. Resetting."
        reset_and_rerun
      elif git push origin HEAD:main; then
        echo "Push succeeded on attempt ${attempt}"
        exit 0
      else
        echo "Push failed on attempt ${attempt}"
      fi
    else
      echo "Rebase conflict on attempt ${attempt} — resetting to origin/main"
      reset_and_rerun
    fi
  fi
  if (( attempt < MAX_ATTEMPTS )); then
    backoff=$((4 ** attempt))
    echo "Backing off ${backoff}s before retry"
    sleep "$backoff"
  fi
  ((attempt++)) || true
done

echo "Failed to push after ${MAX_ATTEMPTS} attempts"
exit 1
