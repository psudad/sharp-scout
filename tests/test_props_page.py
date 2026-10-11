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
    assert "No unlocked NFL props right now" in html
    assert "No locked props right now" in html and "No props have been graded yet" in html
    assert "0-0" in html


def test_page_shows_locked_and_graded_and_hides_locked_from_edges():
    ledger = {"plays": [
        {**_prop("Locked", 0.08), "status": "pending", "kickoff": "2099-10-04T20:00:00+00:00"},
        {**_prop("Won", 0.07), "status": "win", "prop_result": 6, "pnl_units": 1.4,
         "settled_at": "2026-10-03T00:00:00+00:00"},
        {**_prop("Lost", 0.07), "status": "loss", "prop_result": 2, "pnl_units": -1.5,
         "settled_at": "2026-10-03T01:00:00+00:00"},
    ]}
    html = _render_props_page(
        {"generated_at": "2026-10-04T14:00:00+00:00", "plays": [_prop("Locked", 0.08), _prop("Fresh", 0.1)]},
        analytics_head="", now=NOW, props_ledger=ledger,
    )
    assert "LOCKED" in html and "WIN" in html and "LOSS" in html
    assert "1-1" in html and "Fresh" in html
    # Locked prop appears in the locked table only, not duplicated in the edges table
    assert html.count("Locked</td>") == 1


def test_props_migrate_out_of_main_ledger(tmp_path):
    import json
    from sharp_scout.ledger.tracker import migrate_props_from_main_ledger

    main, props = tmp_path / "ledger.json", tmp_path / "props_ledger.json"
    main.write_text(json.dumps({"plays": [
        {"id": "a", "market": "spreads", "status": "pending"},
        {"id": "b", "market": "player_receptions", "play_type": "prop", "status": "win"},
    ]}))
    assert migrate_props_from_main_ledger(main, props) == 1
    assert [p["id"] for p in json.loads(main.read_text())["plays"]] == ["a"]
    assert [p["id"] for p in json.loads(props.read_text())["plays"]] == ["b"]
    assert migrate_props_from_main_ledger(main, props) == 0
