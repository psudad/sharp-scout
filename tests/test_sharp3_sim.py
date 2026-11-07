"""Sharp 3 Monte Carlo projection (replaces fabricated sim_rec)."""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sharp_scout.ncaam import sharp3
from sharp_scout.ncaam import ratings as ratings_mod
from sharp_scout.ncaam.ratings import (
    TORVIK_URL,
    cache_date_from_path,
    content_sha256,
    load_ratings,
    ratings_provenance_for_path,
    verify_retrieval_record,
    write_successful_retrieval_meta,
)
from sharp_scout.ncaam.sharp3_sim import (
    DISPLAY_MAX_ACQUISITION_AGE_DAYS,
    DISPLAY_POLICY_ID,
    format_sim_rec,
    is_legacy_fabricated_sim_rec,
    is_valid_sim_projection,
    lab_sim_display_text,
    monte_carlo_projection,
    run_margin_monte_carlo_core,
    validate_ratings_for_sharp3_display,
)


FIXTURE_CSV = Path("tests/fixtures/ncaam/torvik_sample.csv")
FIXTURE_RATINGS = load_ratings(FIXTURE_CSV)
FIXTURE_BODY = FIXTURE_CSV.read_bytes()
GAME = {"espn_id": "401", "home_team": "Duke", "away_team": "North Carolina", "neutral_site": False}
EVAL_NOW = datetime(2026, 11, 7, 15, 0, tzinfo=timezone.utc)
CSV_ROW = b"team,adjoe,adjde,adjt\nDuke,120,90,70\n"


def _verified_path(tmp_path, *, name: str, body: bytes, retrieved_at: datetime) -> Path:
    p = tmp_path / name
    p.write_bytes(body)
    write_successful_retrieval_meta(
        p,
        source_url=TORVIK_URL,
        content_digest=hashlib.sha256(body).hexdigest(),
        retrieved_at=retrieved_at,
    )
    return p


def _core(**kw):
    kw.setdefault("ratings", FIXTURE_RATINGS)
    return run_margin_monte_carlo_core(GAME, side="home", market="spreads", line=-4.5, **kw)


def test_sharp3_module_has_no_random_sim_record():
    src = inspect.getsource(importlib.import_module("sharp_scout.ncaam.sharp3"))
    assert "sim_record" not in src
    assert "random.Random" not in src


def test_fetch_writes_retrieval_meta_runner_integration(tmp_path, monkeypatch):
    monkeypatch.setattr(ratings_mod, "NCAAM_DATA", tmp_path)
    dest = tmp_path / "ratings_20261107.csv"
    retrieved = datetime(2026, 11, 7, 14, 0, tzinfo=timezone.utc)

    class Resp:
        content = CSV_ROW
        headers = {"last-modified": "Sat, 07 Nov 2026 14:00:18 GMT"}

        def raise_for_status(self):
            return None

    client = MagicMock()
    client.get.return_value = Resp()
    client.__enter__ = lambda s: s
    client.__exit__ = lambda *a: None
    monkeypatch.setattr(ratings_mod.httpx, "Client", lambda **kw: client)
    ratings_mod.fetch_torvik_csv(dest=dest)
    ok, reason, _ = verify_retrieval_record(dest)
    assert ok and reason == ""
    prov = ratings_provenance_for_path(dest)
    assert prov["retrieval_verified"] is True
    assert prov["content_sha256"] == content_sha256(dest)
    assert prov["retrieved_at_utc"].startswith("2026-11-07")
    assert prov["ratings_snapshot_as_of"] is None


def test_acquisition_fresh_today_and_stale_yesterday(tmp_path):
    body = CSV_ROW
    fresh = _verified_path(tmp_path, name="ratings_20261107.csv", body=body, retrieved_at=EVAL_NOW)
    prov = ratings_provenance_for_path(fresh)
    ok, _ = validate_ratings_for_sharp3_display(prov, now=EVAL_NOW)
    assert ok
    old = _verified_path(
        tmp_path,
        name="ratings_20261104.csv",
        body=body,
        retrieved_at=datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc),
    )
    prov_old = ratings_provenance_for_path(old)
    ok, reason = validate_ratings_for_sharp3_display(prov_old, now=EVAL_NOW)
    assert not ok and reason == "retrieval_stale_for_display"
    assert DISPLAY_MAX_ACQUISITION_AGE_DAYS == 1


def test_yesterday_retrieval_is_fresh(tmp_path):
    body = CSV_ROW
    p = _verified_path(
        tmp_path,
        name="ratings_20261106.csv",
        body=body,
        retrieved_at=datetime(2026, 11, 6, 23, 0, tzinfo=timezone.utc),
    )
    ok, _ = validate_ratings_for_sharp3_display(ratings_provenance_for_path(p), now=EVAL_NOW)
    assert ok


def test_missing_retrieval_metadata(tmp_path):
    p = tmp_path / "ratings_20261107.csv"
    p.write_bytes(CSV_ROW)
    prov = ratings_provenance_for_path(p)
    assert not prov["retrieval_verified"]
    ok, reason = validate_ratings_for_sharp3_display(prov, now=EVAL_NOW)
    assert not ok and reason == "retrieval_metadata_missing"


def test_digest_mismatch_renamed_or_tampered(tmp_path):
    p = _verified_path(tmp_path, name="ratings_20261107.csv", body=CSV_ROW, retrieved_at=EVAL_NOW)
    assert verify_retrieval_record(p)[0]
    p.write_bytes(CSV_ROW + b"# tampered\n")
    ok, reason, _ = verify_retrieval_record(p)
    assert not ok and reason == "retrieval_digest_mismatch"
    ok2, reason2 = validate_ratings_for_sharp3_display(ratings_provenance_for_path(p), now=EVAL_NOW)
    assert not ok2 and reason2 == "retrieval_digest_mismatch"


def test_copied_csv_without_meta_not_verified(tmp_path):
    src = _verified_path(tmp_path, name="ratings_20261107.csv", body=CSV_ROW, retrieved_at=EVAL_NOW)
    copy = tmp_path / "ratings_latest.csv"
    copy.write_bytes(src.read_bytes())
    prov = ratings_provenance_for_path(copy)
    assert not prov["retrieval_verified"]


def test_failed_refresh_does_not_renew_meta(tmp_path, monkeypatch):
    monkeypatch.setattr(ratings_mod, "NCAAM_DATA", tmp_path)

    class _FakeDateTime:
        @staticmethod
        def now(tz=None):
            return EVAL_NOW.astimezone(tz) if tz is not None else EVAL_NOW

    monkeypatch.setattr(ratings_mod, "datetime", _FakeDateTime)
    stale_day = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    old = _verified_path(tmp_path, name="ratings_20261104.csv", body=CSV_ROW, retrieved_at=stale_day)

    def _boom(**_kw):
        raise OSError("network down")

    monkeypatch.setattr(ratings_mod, "fetch_torvik_csv", _boom)
    got = ratings_mod.ensure_daily_ratings()
    assert got == old
    meta = json.loads(ratings_mod._meta_path_for(old).read_text())
    assert meta["retrieved_at_utc"].startswith("2026-11-04")
    assert not (tmp_path / "ratings_20261107.csv.meta.json").exists()


def test_cache_date_not_used_for_freshness(tmp_path):
    p = tmp_path / "ratings_20261107.csv"
    p.write_bytes(CSV_ROW)
    assert cache_date_from_path(p) == EVAL_NOW.date()
    assert not ratings_provenance_for_path(p)["retrieval_verified"]


def test_production_monte_carlo_with_fresh_retrieval(tmp_path):
    p = _verified_path(tmp_path, name="ratings_20261107.csv", body=FIXTURE_BODY, retrieved_at=EVAL_NOW)
    prov = ratings_provenance_for_path(p)
    out = monte_carlo_projection(
        GAME,
        side="home",
        market="spreads",
        line=-4.5,
        ratings=load_ratings(p),
        ratings_provenance=prov,
        now=EVAL_NOW,
    )
    assert out["status"] == "ok"
    assert is_valid_sim_projection(out)
    assert out["ratings_display_policy"] == DISPLAY_POLICY_ID
    assert out["ratings_provenance"]["ratings_snapshot_as_of"] is None


def test_core_deterministic_reproducibility():
    a = _core(n=1500)
    b = _core(n=1500)
    assert a == b
    assert a["reproducibility"]["seed_inputs"] == "sharp3-sim|401|home|spreads|-4.5"


def test_evaluate_uses_runner_provenance_path(tmp_path, monkeypatch):
    p = _verified_path(tmp_path, name="ratings_20261107.csv", body=FIXTURE_BODY, retrieved_at=EVAL_NOW)
    prov = ratings_provenance_for_path(p)
    event = {
        "bookmakers": {
            "draftkings": {
                "markets": {
                    "spreads": [
                        {"side": "home", "point": -4.5, "price": -110},
                        {"side": "away", "point": 4.5, "price": -110},
                    ]
                }
            }
        }
    }
    sp = {
        "spread": {
            "home": {"money_pct": 30, "ticket_pct": 40, "line": -4.5, "price": -110},
            "away": {"money_pct": 70, "ticket_pct": 30, "line": 4.5, "price": -110},
        },
        "ml": {},
    }
    ev = sharp3.evaluate(
        {"espn_id": "99", "home_team": "Duke", "away_team": "North Carolina"},
        sp,
        event,
        is_mid_major_by_side={"home": False, "away": False},
        ratings=load_ratings(p),
        ratings_provenance=prov,
        now=EVAL_NOW,
    )
    assert ev["sim_projection"]["status"] == "ok"


def test_legacy_sim_rec_not_displayed():
    assert is_legacy_fabricated_sim_rec("978-22")
    legacy = {"sim_rec": "795-205"}
    assert "legacy synthetic" in (lab_sim_display_text(legacy) or "")
    assert "795-205" not in (lab_sim_display_text(legacy) or "")


def test_lab_builder_hides_legacy_sim_rec_in_html(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_ncaam_lab", Path(__file__).resolve().parents[1] / "scripts" / "build_ncaam_lab.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    data = tmp_path / "data"
    (data / "ncaam").mkdir(parents=True)
    now = datetime.now(timezone.utc)
    day = now.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).date()
    (data / "ncaam" / f"systems_{day.strftime('%Y%m%d')}.json").write_text(
        json.dumps(
            {
                "updated_at": now.isoformat(),
                "splits": {"n_with_money": 1, "n_games": 1},
                "games": {
                    "g1": {
                        "tip": (now + __import__("datetime").timedelta(hours=2)).isoformat(),
                        "home_team": "Louisville",
                        "away_team": "Morehead St.",
                        "has_splits": True,
                        "sharp3": {"sim_rec": "795-205", "result": "play", "side": "away", "line": 37.5},
                    }
                },
            }
        )
    )
    (data / "ncaam_ledger.json").write_text('{"plays":[]}')
    monkeypatch.setattr(mod, "DATA", data)
    page = mod.build(tmp_path / "page.html", now=now, fixture_sim_demo=True).read_text()
    assert "795-205" not in page
    assert "legacy synthetic" in page
