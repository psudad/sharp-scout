"""NBA public page layout (display-only HTML builder)."""

from __future__ import annotations

from datetime import datetime, time, timezone

from sharp_scout.utils.slate import ET
from sharp_scout.site.nba_page import (
    NO_LIVE_SCAN_MESSAGE,
    OFFICIAL_PACE_MARKET_KINDS,
    PACE_LEAN_MIN_EDGE_PT,
    PACE_SPREAD_SHADOW_KINDS,
    PACE_SPREAD_SHADOW_SECTION_LABEL,
    PLAY_BADGE_LABEL,
    SCORE_MODELING_MIN_EDGE_PT,
    TRACKING_ONLY_BADGE_LABEL,
    _injury_list_summary,
    format_projected_scores_line,
    render_nba_page_html,
    render_nba_props_page_html,
    score_modeling_display_leans,
    score_modeling_display_plays,
    spread_gap_plain_english,
)


def test_injury_summary_lists_season_exclusions_first():
    row = {
        "home": "LAL",
        "away": "POR",
        "home_absences": [],
        "away_absences": [
            {
                "player": "Scoot Henderson",
                "kind": "absence",
                "status_label": "Day-To-Day",
                "margin_pts": -0.8,
            }
        ],
        "home_excluded": [],
        "away_excluded": [
            {
                "player": "Shaedon Sharpe",
                "kind": "excluded_season",
                "status_label": "Out",
            }
        ],
    }
    summary = _injury_list_summary(row)
    assert summary.startswith("Excluded: Shaedon Sharpe")
    assert "-0.8" in summary


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
    assert "3+ pts" not in explain  # rule text kept private


def test_official_pace_display_plays_are_totals_only():
    """Spread can outrank total in gap, but official card display must be totals-only."""
    rows = [
        {
            "away": "BOS",
            "home": "NYK",
            "kickoff": "2026-10-27T00:00:00+00:00",
            "margin": 10.0,
            "total": 230.0,
            "injury_margin": 10.0,
            "injury_total": 230.0,
            "home_absences": [],
            "away_absences": [],
            "lines": {"consensus_spread_home": -3.0, "consensus_total": 220.0},
        }
    ]
    official = score_modeling_display_plays(
        rows, min_edge=SCORE_MODELING_MIN_EDGE_PT, kinds=OFFICIAL_PACE_MARKET_KINDS
    )
    spread_shadow = score_modeling_display_plays(
        rows, min_edge=SCORE_MODELING_MIN_EDGE_PT, kinds=PACE_SPREAD_SHADOW_KINDS
    )
    assert len(official) == 1
    assert official[0]["kind"] == "total"
    assert "Over 220" in official[0]["title"]
    assert len(spread_shadow) == 1
    assert spread_shadow[0]["kind"] == "spread"
    assert "NYK" in spread_shadow[0]["title"] or "BOS" in spread_shadow[0]["title"]


def test_spread_shadow_cards_use_tracking_badge_not_play():
    today_kick = datetime.combine(datetime.now(ET).date(), time(19, 0), tzinfo=ET).isoformat()
    score_rows = [
        {
            "away": "BOS",
            "home": "NYK",
            "kickoff": today_kick,
            "margin": 10.0,
            "total": 230.0,
            "injury_margin": 10.0,
            "injury_total": 230.0,
            "home_absences": [],
            "away_absences": [],
            "lines": {"consensus_spread_home": -3.0, "consensus_total": 220.0},
        }
    ]
    html = render_nba_page_html(
        signals_payload={"ok": True, "demo": False, "generated_at": "2026-10-26T12:00:00+00:00", "signals": [], "possible_signals": []},
        ledger={"plays": []},
        report={},
        analytics_head="",
        score_model_rows=score_rows,
        score_model_summary={"n_graded": 0},
    )
    shadow_start = html.index(PACE_SPREAD_SHADOW_SECTION_LABEL)
    spread_shadow_block = html[shadow_start : html.index("Near-miss tracking")]
    assert TRACKING_ONLY_BADGE_LABEL in spread_shadow_block
    assert f'badge-play">{PLAY_BADGE_LABEL}' not in spread_shadow_block


def test_render_nba_page_official_upcoming_excludes_spread_candidates():
    today_kick = datetime.combine(datetime.now(ET).date(), time(19, 0), tzinfo=ET).isoformat()
    score_rows = [
        {
            "away": "BOS",
            "home": "NYK",
            "kickoff": today_kick,
            "margin": 10.0,
            "total": 230.0,
            "injury_margin": 10.0,
            "injury_total": 230.0,
            "home_absences": [],
            "away_absences": [],
            "lines": {"consensus_spread_home": -3.0, "consensus_total": 220.0},
        }
    ]
    html = render_nba_page_html(
        signals_payload={"ok": True, "demo": False, "generated_at": "2026-10-26T12:00:00+00:00", "signals": [], "possible_signals": []},
        ledger={"plays": []},
        report={},
        analytics_head="",
        score_model_rows=score_rows,
        score_model_summary={"n_graded": 0},
    )
    official_start = html.index("Upcoming plays (official card — totals only)")
    shadow_start = html.index(PACE_SPREAD_SHADOW_SECTION_LABEL)
    official_block = html[official_start:shadow_start]
    spread_shadow_block = html[shadow_start : html.index("Near-miss tracking")]
    assert "Over 220" in official_block
    assert "NYK -3" not in official_block and "NYK +3" not in official_block
    assert "BOS +3" not in official_block
    assert any(x in spread_shadow_block for x in ("NYK -3", "NYK +3", "BOS +3", "BOS -3"))
    assert "lean" not in official_block.lower()


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


def _patch_nba_page_now(monkeypatch, when: datetime) -> None:
    from sharp_scout.nba import slate_et as slate_et_mod
    from sharp_scout.site import nba_page as nba_page_mod

    real = datetime

    class _FixedDatetime(real):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return when.replace(tzinfo=None)
            return when.astimezone(tz)

    monkeypatch.setattr(nba_page_mod, "datetime", _FixedDatetime)
    monkeypatch.setattr(slate_et_mod, "datetime", _FixedDatetime)


def test_render_nba_page_price_edge_and_score_modeling_sections(monkeypatch):
    # Freeze slate "now" before evening tip so upcoming_slate_items keeps the play visible.
    fixed_now = datetime(2026, 10, 26, 20, 0, tzinfo=timezone.utc)
    _patch_nba_page_now(monkeypatch, fixed_now)
    today_kick = datetime.combine(fixed_now.astimezone(ET).date(), time(19, 0), tzinfo=ET).isoformat()
    payload = {
        "ok": True,
        "demo": False,
        "generated_at": "2026-10-26T12:00:00+00:00",
        "signals": [
            {
                "away_team": "WAS",
                "home_team": "CHA",
                "kickoff": today_kick,
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
    idx_sharp = html.index('id="sharp-scout-heading"')
    idx_pace = html.index('id="pace-heading"')
    idx_pace_plays = html.index("Upcoming plays (official card — totals only)")
    idx_sharp_plays = html.index('<div class="section-label">Upcoming plays</div>', idx_sharp)
    idx_diag = html.index("Diagnostics")
    assert idx_pace < idx_pace_plays < idx_sharp < idx_sharp_plays < idx_diag
    assert "nba-props.html" not in html
    assert "nav-test-badge" in html
    assert "WAS @ CHA: Over 227.5" in html
    assert f'tier-badge badge-play">{PLAY_BADGE_LABEL}' in html
    assert "Tonight&apos;s play" not in html
    assert "DAL @ MIA: Under 240.75" in html
    assert "Projections &amp; detail" in html
    assert "Near-miss tracking (not bets), projections &amp; history" in html
    assert "Player props (separate)" not in html
    assert "nba-rec-chip" in html
    assert "Export tables" not in html.split("Diagnostics")[0]


def test_score_modeling_skips_when_raw_qualifies_but_injury_vetoes():
    """Regression: raw-only gap must not crash when injury adj fails raw-gate merge."""
    rows = [
        {
            "away": "SAC",
            "home": "SAS",
            "kickoff": "2026-10-27T02:00:00+00:00",
            "margin": 16.4,
            "total": 233.0,
            "injury_margin": 15.1,
            "injury_total": 231.6,
            "home_absences": [],
            "away_absences": [],
            "lines": {"consensus_spread_home": -18.5, "consensus_total": 232.5},
        },
        {
            "away": "POR",
            "home": "LAL",
            "kickoff": "2026-10-27T03:00:00+00:00",
            "margin": 1.2,
            "total": 233.4,
            "injury_margin": 5.4,
            "injury_total": 233.1,
            "home_absences": [],
            "away_absences": [],
            "lines": {"consensus_spread_home": -2.0, "consensus_total": 233.5},
        },
    ]
    assert score_modeling_display_plays(rows, min_edge=SCORE_MODELING_MIN_EDGE_PT) == []
    assert score_modeling_display_leans(rows) == []


def test_build_nba_page_with_mixed_qualifying_rows_does_not_crash():
    from sharp_scout.site.nba_page import build_nba_page

    build_nba_page()


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
    assert "1:07 PM" in html
    assert "no-cache" in html.lower()


def test_render_nba_page_groups_plays_by_et_date():
    ref_day = datetime(2026, 10, 27, 15, 0, tzinfo=ET)
    payload = {
        "ok": True,
        "demo": False,
        "generated_at": "2026-10-27T19:00:00+00:00",
        "signals": [],
        "possible_signals": [],
    }
    score_rows = [
        {
            "away": "PHI",
            "home": "IND",
            "kickoff": "2026-10-29T00:00:00Z",
            "margin": 2.0,
            "total": 232.0,
            "injury_margin": 2.0,
            "injury_total": 232.0,
            "home_absences": [],
            "away_absences": [],
            "lines": {"consensus_spread_home": -3.0, "consensus_total": 240.75},
        },
        {
            "away": "DAL",
            "home": "MIA",
            "kickoff": "2026-10-28T02:00:00Z",
            "margin": 2.0,
            "total": 232.0,
            "injury_margin": 2.0,
            "injury_total": 232.0,
            "home_absences": [],
            "away_absences": [],
            "lines": {"consensus_spread_home": -3.0, "consensus_total": 240.75},
        },
    ]
    from unittest.mock import patch

    with patch("sharp_scout.site.nba_page.datetime") as mock_dt:
        mock_dt.now.return_value = ref_day
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        html = render_nba_page_html(
            signals_payload=payload,
            ledger={"plays": []},
            report={},
            analytics_head="",
            score_model_rows=score_rows,
            score_model_summary={"n_graded": 0},
        )
    t_pos = html.index("Tonight, Tue Oct 27")
    m_pos = html.index("Tomorrow, Wed Oct 28")
    assert t_pos < m_pos
    assert html.index("DAL @ MIA") < html.index("PHI @ IND")


def test_render_nba_props_page_empty_when_no_props():
    today_kick = datetime.combine(datetime.now(ET).date(), time(19, 0), tzinfo=ET).isoformat()
    payload = {
        "ok": True,
        "demo": False,
        "generated_at": "2026-10-26T12:00:00+00:00",
        "signals": [
            {
                "away_team": "WAS",
                "home_team": "CHA",
                "kickoff": today_kick,
                "market": "totals",
                "side": "over",
                "play_type": "side",
                "line": 227.5,
                "edge": 0.04,
                "price": -110,
                "units": 1.0,
                "book": "fanduel",
            }
        ],
        "possible_signals": [],
    }
    html = render_nba_props_page_html(
        signals_payload=payload,
        ledger={"plays": []},
        report={},
        analytics_head="",
    )
    assert "No NBA prop picks on today&apos;s slate" in html
    assert "tab-nba-props" not in html
    assert "WAS @ CHA" not in html
