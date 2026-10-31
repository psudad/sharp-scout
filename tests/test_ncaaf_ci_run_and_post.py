"""CI shell chains for run_ncaaf.py + ncaaf_ci_post_run.sh (refresh-board RERUN)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from sharp_scout.ncaaf.publish_gate import EXIT_PUBLISH_BLOCKED

ROOT = Path(__file__).resolve().parents[1]


def _refresh_board_rerun_string(cfb_args: str = "--build-site") -> str:
    """Mirror refresh-board.yml commit-step RERUN NCAAF fragment + trailing sentinel."""
    rerun = ""
    rerun += f"scripts/ncaaf_ci_run_and_post.sh {cfb_args} && "
    rerun += "touch TRAILED"
    return rerun


def _install_ci_chain(tmp_path: Path, *, run_exit: int) -> tuple[Path, Path]:
    scripts = tmp_path / "scripts"
    data = tmp_path / "data"
    scripts.mkdir()
    data.mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "ncaaf_ci_run_and_post.sh", scripts / "ncaaf_ci_run_and_post.sh")
    shutil.copy(ROOT / "scripts" / "ncaaf_ci_post_run.sh", scripts / "ncaaf_ci_post_run.sh")
    for name in (
        "ncaaf_ci_run_and_post.sh",
        "ncaaf_ci_post_run.sh",
    ):
        (scripts / name).chmod(0o755)
    (scripts / "run_ncaaf.py").write_text(
        "#!/usr/bin/env python3\nimport sys\n"
        f"sys.exit({run_exit})\n"
    )
    (scripts / "run_ncaaf.py").chmod(0o755)
    stamp = data / "ncaaf_rebuild_state.json"
    (scripts / "stamp_ncaaf_rebuild_state.sh").write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '{{"last_rebuild": "2099-01-01T00:00:00+00:00"}}\\n' > "{stamp}"
"""
    )
    (scripts / "stamp_ncaaf_rebuild_state.sh").chmod(0o755)
    trailing = tmp_path / "TRAILED"
    return trailing, stamp


def _run_rerun(tmp_path: Path, rerun: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", rerun],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("run_exit", [1, 2])
def test_refresh_board_rerun_stops_on_real_failure(tmp_path, run_exit: int):
    trailing, stamp = _install_ci_chain(tmp_path, run_exit=run_exit)
    proc = _run_rerun(tmp_path, _refresh_board_rerun_string())
    assert proc.returncode == run_exit
    assert not trailing.exists()
    assert not stamp.exists()


def test_refresh_board_rerun_continues_on_publish_blocked(tmp_path):
    trailing, stamp = _install_ci_chain(tmp_path, run_exit=EXIT_PUBLISH_BLOCKED)
    proc = _run_rerun(tmp_path, _refresh_board_rerun_string())
    assert proc.returncode == 0
    assert "publish was blocked" in proc.stdout
    assert trailing.exists()
    assert not stamp.exists()


def test_refresh_board_rerun_stamps_and_continues_on_success(tmp_path):
    trailing, stamp = _install_ci_chain(tmp_path, run_exit=0)
    proc = _run_rerun(tmp_path, _refresh_board_rerun_string())
    assert proc.returncode == 0
    assert trailing.exists()
    assert stamp.exists()
    assert "2099" in stamp.read_text()


def test_broken_set_e_masking_pattern_regression(tmp_path):
    """Old refresh-board RERUN masked post_run failures under set +e."""
    trailing, stamp = _install_ci_chain(tmp_path, run_exit=1)
    broken = (
        "set +e; python scripts/run_ncaaf.py --build-site; "
        "scripts/ncaaf_ci_post_run.sh $?; set -e && touch TRAILED"
    )
    proc = _run_rerun(tmp_path, broken)
    assert proc.returncode == 0
    assert trailing.exists(), "regression: broken chain must not reach trailing on crash"
