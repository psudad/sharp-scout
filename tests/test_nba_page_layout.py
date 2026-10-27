"""NBA public page layout (display-only HTML builder)."""

from __future__ import annotations

from sharp_scout.site.nba_page import (
    NO_LIVE_SCAN_MESSAGE,
    PACE_LEAN_MIN_EDGE_PT,
    SCORE_MODELING_MIN_EDGE_PT,
    format_projected_scores_line,
    render_nba_page_html,
    score_modeling_display_leans,
    score_modeling_display_plays,
    spread_gap_plain_english,
)


def test_projected_scores_and_gap_copy():
    line = format_projected_scores_line(
        home="BOS",
        away="BKN",
        margin=20.6,
        total=225.0,
        inj_margin=18.0,
        inj_total=223.0,
    )
    assert "Projected: BOS" in line
    assert "after injuries" in line
    explain = spread_gap_plain_english(home="BOS", margin=20.6, consensus_spread_home=-11.5)
    assert "gap 9.1 pts" in explain
    assert "3+ pts" in explain


def test_score_modeling_display_uses_three_point_threshold():
    rows = [
        {
            "away": "DAL",
            "home": "MIA",
            "kickoff": "2026-10-27T00:00:00+00:00",
            "margin": 2.0,
            "total": 232.0,
            "injury_margin": 2.0,
            "injury_total": 230.0,
            "home_absences": [],
            "away_absences": [],
            "lines": {"consensus_spread_home": -3.0, "consensus_total": 240.75},
        },
        {
            "away": "MIN",
            "home": "LAL",
            "kickoff": "2026-10-27T01:00:00+00:00",
            "margin": -2.0,
            "total": 226.0,
            "injury_margin": -2.0,
            "injury_total": 226.0,
            "home_absences": [],
            "away_absences": [],
            "lines": {"consensus_spread_home": -4.5, "consensus_total": 225.0},
        },
    ]
    plays = score_modeling_display_plays(rows, min_edge=SCORE_MODELING_MIN_EDGE_PT)
    assert len(plays) == 2
    assert plays[0]["gap"] >= plays[1]["gap"]
    titles = {p["title"] for p in plays}
    assert "DAL @ MIA: Under 240.75" in titles
    assert "MIN +4.5" in titles


def test_render_nba_page_price_edge_and_score_modeling_sections():
    payload = {
        "ok": True,
        "demo": False,
        "generated_at": "2026-10-26T12:00:00+00:00",
        "signals": [
            {
                "away_team": "WAS",
                "home_team": "CHA",
                "kickoff": "2026-10-27T00:00:00Z",
                "market": "totals",
                "side": "over",
                "play_type": "side",
                "line": 227.5,
                "edge": 0.04,
                "price": -110,
                "units": 1.0,
                "book": "fanduel",
                "p_true": 0.55,
                "model_alignment": "agree",
                "sharp_money_tag": "with_sharps",
            }
        ],
        "possible_signals": [],
    }
    score_rows = [
        {
            "away": "DAL",
            "home": "MIA",
            "kickoff": "2026-10-27T00:00:00+00:00",
            "margin": 2.0,
            "total": 232.0,
            "injury_margin": 2.0,
            "injury_total": 232.0,
            "home_absences": [],
            "away_absences": [],
            "lines": {"consensus_spread_home": -3.0, "consensus_total": 240.75},
        }
    ]
    summary = {
        "n_graded": 10,
        "ats_vs_close": {"ge_3": {"wins": 6, "losses": 4, "pushes": 0}},
        "ou_vs_close": {"ge_3": {"wins": 5, "losses": 5, "pushes": 0}},
    }
    html = render_nba_page_html(
        signals_payload=payload,
        ledger={"plays": []},
        report={},
        analytics_head="",
        score_model_rows=score_rows,
        score_model_summary=summary,
    )
    idx_sharp = html.index("Sharp Scout model")
    idx_pace = html.index("Pace of Play model")
    idx_plays = html.index("Today&apos;s plays")
    idx_diag = html.index("Diagnostics")
    assert idx_sharp < idx_plays < idx_pace < idx_diag
    assert "WAS @ CHA: Over 227.5" in html
    assert "Today&apos;s play" in html
    assert "DAL @ MIA: Under 240.75" in html
    assert "Injury-adj" in html or "Injury " in html
    assert "Projected:" in html
    assert "Results tracking" in html
    assert "Today&apos;s slate projections" in html
    assert "Game lines" not in html.split("Diagnostics")[0]


def test_pace_leans_use_band_between_one_five_and_three():
    rows = [
        {
            "away": "GSW",
            "home": "DEN",
            "kickoff": "2026-10-27T02:00:00+00:00",
            "margin": 5.0,
            "total": 240.0,
            "injury_margin": 5.0,
            "injury_total": 240.0,
            "home_absences": [],
            "away_absences": [],
            "lines": {"consensus_spread_home": -3.0, "consensus_total": None},
        }
    ]
    plays = score_modeling_display_plays(rows)
    leans = score_modeling_display_leans(rows)
    assert not plays
    assert len(leans) == 1
    assert PACE_LEAN_MIN_EDGE_PT <= leans[0]["gap"] < SCORE_MODELING_MIN_EDGE_PT


def test_render_nba_page_no_live_scan_message():
    html = render_nba_page_html(
        signals_payload=None,
        ledger={"plays": []},
        report={},
        analytics_head="",
    )
    assert NO_LIVE_SCAN_MESSAGE in html
    assert "10:30 AM" in html
