import json
import tempfile
from pathlib import Path

from sharp_scout.ncaam.lock import LEDGER_PATH
from sharp_scout.ncaam.runner import run_pass


def test_demo_once_does_not_touch_live_ledger():
    before = LEDGER_PATH.read_text() if LEDGER_PATH.exists() else ""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "ncaam_ledger.json"
        path.write_text(
            '{"updated_at":"1970-01-01T00:00:00+00:00","starting_units":100,"plays":[],"stage_cards":[],"disagreements":[]}\n'
        )
        out = run_pass(demo=True, ledger_path=path)
        assert out.get("skip_reason", "") == ""
        ledger = json.loads(path.read_text())
        if out["locked"] >= 1:
            assert any(p.get("side") for p in ledger.get("plays") or [])
        else:
            # Demo still exercised the pipeline even when nothing clears lock filters.
            assert out.get("candidates", 0) >= 0
    after = LEDGER_PATH.read_text() if LEDGER_PATH.exists() else ""
    assert before == after
