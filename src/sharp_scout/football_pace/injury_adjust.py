"""Injury / availability adjustments for football pace projections."""

from __future__ import annotations

from typing import Any

from sharp_scout.football_pace.player_value import PlayerValueTracker, match_player


STATUS_FRAC: dict[str, float] = {
    "out": 1.0,
    "doubtful": 0.72,
    "questionable": 0.38,
    "limited": 0.28,
    "probable": 0.12,
    "inactive": 1.0,
    "injured reserve": 1.0,
    "ir": 1.0,
    "suspended": 1.0,
}


def normalize_injury_status(status: str) -> str:
    s = (status or "").strip().lower()
    if not s or s in ("active", "healthy", "expected to play"):
        return "active"
    for key in STATUS_FRAC:
        if key in s:
            return key
    if "question" in s:
        return "questionable"
    if "doubt" in s:
        return "doubtful"
    return "active"


def status_weight(status: str) -> float:
    return STATUS_FRAC.get(normalize_injury_status(status), 0.0)


def team_injury_deltas(
    tracker: PlayerValueTracker,
    injuries: list[dict[str, Any]],
    *,
    roster_names: list[str] | None = None,
) -> dict[str, float]:
    """Return off_loss and def_loss points for one team (non-negative)."""
    off_loss = 0.0
    def_loss = 0.0
    roster_names = roster_names or []
    for row in injuries:
        status = row.get("status") or ""
        w = status_weight(str(status))
        if w <= 0:
            continue
        raw_name = str(row.get("player") or "")
        matched = match_player(raw_name, roster_names) or raw_name
        pos = str(row.get("position") or "")
        side = _pos_group_side(pos)
        if side == "off":
            off_loss += w * tracker.off_loss_pts(str(row.get("team") or ""), matched, pos)
        elif side == "def":
            def_loss += w * tracker.def_loss_pts(str(row.get("team") or ""), matched, pos)
        else:
            off_loss += w * 0.5 * tracker.off_loss_pts(str(row.get("team") or ""), matched, pos)
            def_loss += w * 0.5 * tracker.def_loss_pts(str(row.get("team") or ""), matched, pos)
    return {"off_loss": off_loss, "def_loss": def_loss}


def _pos_group_side(pos: str) -> str:
    p = (pos or "").upper()
    if p in ("QB", "RB", "WR", "TE", "FB", "T", "G", "C", "OL", "OT", "OG"):
        return "off"
    if p in ("CB", "S", "FS", "SS", "LB", "ILB", "OLB", "EDGE", "DE", "DT", "NT", "DL", "DB"):
        return "def"
    return "unknown"


def apply_injury_adjustment(
    base: dict[str, float],
    *,
    home_off_loss: float,
    home_def_loss: float,
    away_off_loss: float,
    away_def_loss: float,
) -> dict[str, float]:
    """Opponent defensive injuries boost your scoring; own offensive injuries reduce it."""
    home_pts = base["home_pts"] - home_off_loss + away_def_loss
    away_pts = base["away_pts"] - away_off_loss + home_def_loss
    margin = home_pts - away_pts
    total = (
        float(base["total"])
        - home_off_loss
        - away_off_loss
        + home_def_loss
        + away_def_loss
    )
    return {
        **base,
        "home_pts": home_pts,
        "away_pts": away_pts,
        "margin": margin,
        "total": total,
        "home_off_inj": home_off_loss,
        "away_off_inj": away_off_loss,
        "home_def_inj": home_def_loss,
        "away_def_inj": away_def_loss,
    }


def project_with_injuries(
    engine_proj: dict[str, float],
    *,
    home_injuries: list[dict],
    away_injuries: list[dict],
    tracker: PlayerValueTracker,
    home_roster: list[str],
    away_roster: list[str],
) -> dict[str, float]:
    h = team_injury_deltas(tracker, home_injuries, roster_names=home_roster)
    a = team_injury_deltas(tracker, away_injuries, roster_names=away_roster)
    return apply_injury_adjustment(
        engine_proj,
        home_off_loss=h["off_loss"],
        home_def_loss=h["def_loss"],
        away_off_loss=a["off_loss"],
        away_def_loss=a["def_loss"],
    )


def roster_player_names(roster_rows: list[dict]) -> list[str]:
    return [str(r["player"]) for r in roster_rows if r.get("player")]
