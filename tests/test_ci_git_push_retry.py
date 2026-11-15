"""Integration test for scripts/ci_git_push_retry.sh racing-push recovery."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ci_git_push_retry.sh"


def _run(cmd: list[str], *, cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=merged,
        text=True,
        capture_output=True,
        check=False,
    )


def _git_config_repo(cwd: Path) -> None:
    for key, val in (
        ("user.email", "ci@test.local"),
        ("user.name", "CI Test"),
    ):
        _run(["git", "config", key, val], cwd=cwd).check_returncode()


def _init_bare_with_main(tmp_path: Path) -> tuple[Path, Path]:
    bare = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True)
    subprocess.run(["git", "init", "-b", "main", str(seed)], check=True)
    _git_config_repo(seed)
    _run(["git", "remote", "add", "origin", str(bare)], cwd=seed).check_returncode()
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    _run(["git", "add", "README.md"], cwd=seed).check_returncode()
    _run(["git", "commit", "-m", "seed"], cwd=seed).check_returncode()
    _run(["git", "push", "-u", "origin", "main"], cwd=seed).check_returncode()
    return bare, seed


def _clone_worktree(tmp_path: Path, bare: Path, name: str) -> Path:
    dest = tmp_path / name
    subprocess.run(["git", "clone", "-b", "main", str(bare), str(dest)], check=True)
    _git_config_repo(dest)
    _run(["git", "remote", "set-url", "origin", str(bare)], cwd=dest).check_returncode()
    return dest


@pytest.fixture
def git_race_env(tmp_path: Path):
    bare, _seed = _init_bare_with_main(tmp_path)
    clone_a = _clone_worktree(tmp_path, bare, "workflow_a")
    clone_b = _clone_worktree(tmp_path, bare, "workflow_b")
    return {"bare": bare, "clone_a": clone_a, "clone_b": clone_b, "tmp_path": tmp_path}


def test_push_retry_after_failed_push_with_rebased_commit(git_race_env: dict) -> None:
    """Simulate CI race: commit+rebase succeed, push fails once, retry must still publish."""
    clone_a: Path = git_race_env["clone_a"]
    clone_b: Path = git_race_env["clone_b"]
    bare: Path = git_race_env["bare"]
    tmp_path: Path = git_race_env["tmp_path"]

    fail_flag = tmp_path / "fail_push_once"
    fail_flag.write_text("1", encoding="utf-8")
    wrap_dir = tmp_path / "bin"
    wrap_dir.mkdir()
    git_wrap = wrap_dir / "git"
    git_wrap.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            if [[ "${{1:-}}" == "push" && -f {fail_flag} ]]; then
              rm -f {fail_flag}
              echo "simulated push rejection" >&2
              exit 1
            fi
            exec /usr/bin/git "$@"
            """
        ),
        encoding="utf-8",
    )
    git_wrap.chmod(0o755)

    ledger = clone_a / "data" / "ledger.json"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text('{"plays":[]}\n', encoding="utf-8")
    _run(["git", "add", "data/ledger.json"], cwd=clone_a).check_returncode()

    # Concurrent workflow pushes to main before workflow A's first push attempt.
    other = clone_b / "data" / "other.json"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("{}\n", encoding="utf-8")
    _run(["git", "add", "data/other.json"], cwd=clone_b).check_returncode()
    _run(["git", "commit", "-m", "chore: concurrent NCAAF board"], cwd=clone_b).check_returncode()
    _run(["git", "push", "origin", "HEAD:main"], cwd=clone_b).check_returncode()

    env = {"PATH": f"{wrap_dir}:{os.environ.get('PATH', '')}"}
    proc = subprocess.run(
        ["bash", str(SCRIPT), "chore: update NFL ledger and GitHub Pages site"],
        cwd=clone_a,
        env={**os.environ, **env},
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "No new staged changes" in proc.stdout or "Push succeeded" in proc.stdout

    show = _run(["git", "--git-dir", str(bare), "log", "--oneline", "-5"], cwd=tmp_path)
    show.check_returncode()
    assert "chore: update NFL ledger" in show.stdout

    clone_c = tmp_path / "verify"
    subprocess.run(["git", "clone", "-b", "main", str(bare), str(clone_c)], check=True)
    assert (clone_c / "data" / "ledger.json").is_file()
    assert (clone_c / "data" / "other.json").is_file()


def test_noop_when_nothing_staged_and_not_ahead(git_race_env: dict) -> None:
    clone_a: Path = git_race_env["clone_a"]
    proc = subprocess.run(
        ["bash", str(SCRIPT), "chore: noop"],
        cwd=clone_a,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "No staged changes to commit" in proc.stdout