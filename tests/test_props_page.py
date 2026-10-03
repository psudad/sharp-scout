from datetime import datetime, timezone

from sharp_scout.site.build import _render_props_page, props_board_rows

NOW = datetime(2026, 10, 4, 15, 0, tzinfo=timezone.utc)


def _prop(player, edge, *, market="player_receptions", side="over", line=4.5, book="dk",
          kickoff="2026-10-04T17:00:00+00:00"):
    return {
        "player_name": player, "team": "CHI", "home_team": "CHI", "away_team": "NYJ",
        "market": market, "side": side, "line": line, "book": book, "price": -110,
        "p_true": 0.58, "p_mkt": 0.5, "edge": edge, "model_mean": 5.3, "kickoff": kickoff,
    }


def test_rows_sorted_by_edge_and_deduped_to_best_offer():
    payload = {"plays": [
        _prop("A", 0.05),
        _prop("B", 0.12),
        _prop("A", 0.09, book="fd", line=4.0),
    ]}
    rows = props_board_rows(payload, now=NOW)
    assert [(r["player_name"], r["edge"]) for r in rows] == [("B", 0.12), ("A", 0.09)]
    assert rows[1]["book"] == "fd" and rows[1]["n_offers"] == 2


def test_finished_games_and_demo_payloads_are_dropped():
    old = _prop("Old", 0.3, kickoff="2026-09-28T00:15:00+00:00")
    assert props_board_rows({"plays": [old, _prop("New", 0.1)]}, now=NOW)[0]["player_name"] == "New"
    assert props_board_rows({"demo": True, "plays": [_prop("New", 0.1)]}, now=NOW) == []


def test_page_renders_table_and_shadow_banner():
    html = _render_props_page(
        {"generated_at": "2026-10-04T14:00:00+00:00", "plays": [_prop("B", 0.12)]},
        analytics_head="", now=NOW,
    )
    assert "NFL Props" in html and "SHADOW MODE" in html
    assert "Over 4.5" in html and "12.0%" in html


def test_page_empty_state():
    html = _render_props_page({}, analytics_head="", now=NOW)
    assert "No NFL props for upcoming games yet" in html
