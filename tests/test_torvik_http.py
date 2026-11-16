"""Barttorvik HTTP client: whitelisted User-Agent and optional CI live probe."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import httpx
import pytest

from sharp_scout.ncaam import ratings as ratings_mod
from sharp_scout.ncaam.ratings import (
    BARTTORVIK_USER_AGENT,
    TORVIK_URL,
    barttorvik_headers,
    fetch_torvik_csv,
)

_WHITELIST_TOKEN = "jayegg-tr17"


def test_barttorvik_user_agent_constant_includes_whitelist_token():
    assert _WHITELIST_TOKEN in BARTTORVIK_USER_AGENT
    assert BARTTORVIK_USER_AGENT.startswith("SharpScout/1.0 ")
    assert "Mozilla" not in BARTTORVIK_USER_AGENT


def test_barttorvik_headers():
    h = barttorvik_headers()
    assert h == {"User-Agent": BARTTORVIK_USER_AGENT}
    assert _WHITELIST_TOKEN in h["User-Agent"]


def test_fetch_torvik_csv_uses_barttorvik_user_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(ratings_mod, "NCAAM_DATA", tmp_path)
    dest = tmp_path / "ratings_20261116.csv"
    captured: dict[str, object] = {}

    class Resp:
        content = b"rank,team,conf,rec,adjoe,adjde,adjt\n1,Duke,ACC,0-0,115,95,68\n"

        def raise_for_status(self):
            return None

        headers: dict[str, str] = {}

    def client_factory(**kw):
        captured.update(kw)
        client = MagicMock()
        client.get.return_value = Resp()
        client.__enter__ = lambda s: s
        client.__exit__ = lambda *a: None
        return client

    monkeypatch.setattr(ratings_mod.httpx, "Client", client_factory)
    fetch_torvik_csv(dest=dest)
    headers = captured.get("headers") or {}
    assert _WHITELIST_TOKEN in headers.get("User-Agent", "")


@pytest.mark.skipif(
    os.environ.get("TORVIK_WHITELIST_PROBE") != "1",
    reason="Set TORVIK_WHITELIST_PROBE=1 for one live GitHub-side probe",
)
def test_torvik_whitelist_live_probe_from_ci():
    """Exactly one unconditional GET when CI sets TORVIK_WHITELIST_PROBE=1."""
    resp = httpx.get(TORVIK_URL, headers=barttorvik_headers(), timeout=60.0, follow_redirects=True)
    assert resp.status_code == 200, resp.text[:200]
    assert _WHITELIST_TOKEN in BARTTORVIK_USER_AGENT
    lines = [ln for ln in resp.text.splitlines() if ln.strip()]
    assert len(lines) >= 300, f"expected full team_results CSV, got {len(lines)} lines"