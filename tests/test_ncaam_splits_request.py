"""NCAAB splits request must ask AN for the full D1 board, not featured games."""

from __future__ import annotations

from datetime import date

import httpx

from sharp_scout.ncaam import splits


def test_raw_games_requests_d1_division(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return httpx.Response(200, json={"games": [{"id": 1}]})

    real_client = httpx.Client
    monkeypatch.setattr(
        splits.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)
    )
    games, status = splits._raw_games(date(2026, 11, 7), token=None, cookie=None)
    assert status == 200 and games == [{"id": 1}]
    assert seen["division"] == "D1" and seen["date"] == "20261107"
