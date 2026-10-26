"""NBA sharp-money snapshot tagging (display-only, offline)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sharp_scout.nba.sharp_splits.filter import (
    SHARP_MONEY_GAP_PT,
    alignment_for_play,
    annotate_signals_with_sharp_money,
    summarize_sharp_money,
)
from sharp_scout.nba.sharp_splits.store import find_game_splits, load_snapshot

ET = ZoneInfo("America/New_York")


def _sample_game_splits() -> dict:
    return {
        "away": "MIN",
        "home": "CLE",
        "spread": {"bets": [74, 26], "money": [76, 24]},
        "total": {"bets": [85, 15], "money": [88, 12]},
        "ml": {"bets": [60, 40], "money": [79, 21]},
    }


def test_sharp_gap_threshold_with_sharps_on_away_spread():
    g = _sample_game_splits()
    # away: money 76 - bets 74 = 2 (< 10) -> not with sharps on away
    play = {"market": "spreads", "side": "away", "play_type": "side"}
    assert alignment_for_play(play, g)["sharp_money_tag"] == "no_signal"


def test_sharp_with_sharps_when_gap_meets_threshold():
    g = _sample_game_splits()
    # home spread: money 24, bets 26 -> play side home: gap -2; away opp: 76-74=2
    g["spread"] = {"bets": [40, 60], "money": [55, 45]}  # home gap 45-60 = -15, away 55-40=15
    play = {"market": "spreads", "side": "away", "play_type": "side"}
    assert alignment_for_play(play, g)["sharp_money_tag"] == "with_sharps"
    play_home = {"market": "spreads", "side": "home", "play_type": "side"}
    assert alignment_for_play(play_home, g)["sharp_money_tag"] == "against_sharps"


def test_sharp_against_sharps_on_total_under():
    g = _sample_game_splits()
    # total under index 1: money 12, bets 15 -> -3; over opp: 88-85=3
    play = {"market": "totals", "side": "under", "play_type": "side"}
    assert alignment_for_play(play, g)["sharp_money_tag"] == "no_signal"
    g["total"] = {"bets": [50, 50], "money": [70, 30]}  # under gap -20, over +20
    assert alignment_for_play(play, g)["sharp_money_tag"] == "against_sharps"


def test_props_always_no_data():
    assert alignment_for_play({"play_type": "prop", "market": "player_points"}, _sample_game_splits())[
        "sharp_money_tag"
    ] == "no_data"


def test_h2h_uses_ml_splits():
    g = _sample_game_splits()
    play = {"market": "h2h", "side": "away", "play_type": "side"}
    # away ml gap 79-60 = 19
    assert alignment_for_play(play, g)["sharp_money_tag"] == "with_sharps"


def test_find_game_splits_latest_before_tip(tmp_path: Path):
    early = {
        "version": 1,
        "pulled_at": "2026-10-26T08:20:00-04:00",
        "game_date": "2026-10-26",
        "games": [{"away": "Suns", "home": "Thunder", "spread": {"bets": [32, 68], "money": [29, 71]}}],
    }
    late = {
        "version": 1,
        "pulled_at": "2026-10-26T14:00:00-04:00",
        "game_date": "2026-10-26",
        "games": [{"away": "Suns", "home": "Thunder", "spread": {"bets": [30, 70], "money": [20, 80]}}],
    }
    (tmp_path / "2026-10-26-0820.json").write_text(json.dumps(early))
    (tmp_path / "2026-10-26-1400.json").write_text(json.dumps(late))
    kickoff = datetime(2026, 10, 27, 0, 0, tzinfo=timezone.utc)  # Oct 26 8pm ET
    snaps = [load_snapshot(p) for p in sorted(tmp_path.glob("*.json"))]
    snaps = [s for s in snaps if s]
    game, pulled = find_game_splits(
        away_team="PHX",
        home_team="OKC",
        kickoff=kickoff.isoformat(),
        snapshots=snaps,
    )
    assert game is not None
    assert pulled == datetime(2026, 10, 26, 14, 0, tzinfo=ET)
    assert game["spread"]["money"][1] == 80


def test_snapshot_after_tip_is_ignored(tmp_path: Path):
    snap = {
        "version": 1,
        "pulled_at": "2026-10-26T19:30:00-04:00",
        "game_date": "2026-10-26",
        "games": [{"away": "Bulls", "home": "Celtics", "spread": {"bets": [50, 50], "money": [90, 10]}}],
    }
    (tmp_path / "2026-10-26-1930.json").write_text(json.dumps(snap))
    kickoff = datetime(2026, 10, 26, 23, 30, tzinfo=timezone.utc)  # 7:30pm ET
    snaps = [load_snapshot(tmp_path / "2026-10-26-1930.json")]
    game, _ = find_game_splits(
        away_team="CHI",
        home_team="BOS",
        kickoff=kickoff.isoformat(),
        snapshots=snaps,
    )
    assert game is None


def test_committed_snapshot_loads():
    from sharp_scout.nba.sharp_splits.store import SPLITS_DIR

    path = SPLITS_DIR / "2026-10-26-0820.json"
    assert path.exists()
    snap = load_snapshot(path)
    assert snap is not None
    assert len(snap["games"]) == 9


def test_annotate_signal_from_snapshot():
    sig = {
        "event_id": "x",
        "away_team": "PHX",
        "home_team": "OKC",
        "kickoff": "2026-10-27T00:00:00Z",
        "market": "spreads",
        "side": "home",
        "play_type": "side",
    }
    annotate_signals_with_sharp_money([], [sig])
    assert sig.get("sharp_money_tag") in ("with_sharps", "against_sharps", "no_signal", "no_data")
    # OKC home spread from real file: money 71 - bets 68 = 3
    assert sig["sharp_money_tag"] == "no_signal"


def test_summarize_sharp_money_graded_only():
    ledger = {
        "plays": [
            {
                "status": "win",
                "play_type": "side",
                "market": "spreads",
                "sharp_money_tag": "with_sharps",
                "pnl_units": 1.0,
            },
            {
                "status": "loss",
                "play_type": "side",
                "market": "totals",
                "sharp_money_tag": "with_sharps",
                "pnl_units": -1.0,
            },
            {"status": "paper", "play_type": "side", "sharp_money_tag": "with_sharps"},
            {"status": "win", "play_type": "prop", "sharp_money_tag": "no_data"},
        ]
    }
    out = summarize_sharp_money(ledger)
    assert out["with_sharps"]["n"] == 2
    assert out["with_sharps"]["record"] == "1-1-0"
    assert out["with_sharps"]["units"] == 0.0


def test_gap_constant_is_ten():
    assert SHARP_MONEY_GAP_PT == 10


def test_nba_page_renders_sharp_money_section():
    from sharp_scout.site.nba_page import render_nba_page_html

    payload = {
        "ok": True,
        "demo": False,
        "generated_at": "2026-10-26T12:00:00+00:00",
        "signals": [
            {
                "away_team": "PHX",
                "home_team": "OKC",
                "kickoff": "2026-10-27T00:00:00Z",
                "market": "spreads",
                "side": "home",
                "play_type": "side",
                "edge": 0.05,
                "price": -110,
                "units": 1.0,
                "book": "fanduel",
                "line": -9.5,
            }
        ],
        "possible_signals": [],
    }
    html = render_nba_page_html(
        signals_payload=payload,
        ledger={"plays": []},
        report={},
        analytics_head="",
    )
    assert "Sharp money (display only)" in html
    assert "With sharps" in html or "No signal" in html
    assert "Price-edge picks" in html
    assert "Model / sharp" in html
