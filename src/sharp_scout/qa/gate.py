"""QA gate — deterministic data-provenance and play-sanity checks.

Layer 1: block deploy on demo/stale/degenerate ratings.
Layer 2: quarantine (not delete) plays that fail corroboration or look implausible.
"""

from __future__ import annotations

import json
import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sharp_scout.config import ARTIFACTS_DIR, DATA_DIR, get_settings
from sharp_scout.copy.explain import _signal_group_key
from sharp_scout.ledger.tracker import load_ledger, save_ledger
from sharp_scout.sports import SportConfig, get_sport
from sharp_scout.utils.slate import filter_plays_nfl_display_slate, parse_commence

logger = logging.getLogger(__name__)

QA_REPORT_DIR = DATA_DIR / "qa_reports"

# Minimum NFL games on a normal weekly slate (Tue–Sat pre-Sunday).
NFL_GAMEDAY_MIN_GAMES = 4
NCAAF_GAMEDAY_MIN_GAMES = 20
MIN_RATED_TEAMS_NFL = 28
MIN_RATED_TEAMS_NCAAF = 80
MIN_POWER_STDEV = 0.01
MIN_BOOKS_FOR_CORROBORATION = 2
DUPLICATE_P_TRUE_MIN_CLUSTER = 5


@dataclass
class QAIssue:
    code: str
    severity: str  # block | quarantine | warn
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "severity": self.severity, "message": self.message}


@dataclass
class PlayReview:
    play_id: str | None
    matchup: str
    market: str
    side: str
    action: str  # approve | quarantine | void
    issues: list[QAIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "play_id": self.play_id,
            "matchup": self.matchup,
            "market": self.market,
            "side": self.side,
            "action": self.action,
            "issues": [i.to_dict() for i in self.issues],
        }


@dataclass
class QAGateResult:
    sport: str
    layer1_passed: bool
    layer1_issues: list[QAIssue]
    play_reviews: list[PlayReview]
    approved: int = 0
    quarantined: int = 0
    voided: int = 0
    block_deploy: bool = False
    generated_at: str = ""

    def summary(self) -> dict[str, Any]:
        return {
            "sport": self.sport,
            "generated_at": self.generated_at,
            "layer1_passed": self.layer1_passed,
            "block_deploy": self.block_deploy,
            "layer1_issues": [i.to_dict() for i in self.layer1_issues],
            "approved": self.approved,
            "quarantined": self.quarantined,
            "voided": self.voided,
            "play_reviews": [p.to_dict() for p in self.play_reviews],
        }


def _logical_play_key(play: dict[str, Any]) -> str:
    return "|".join(str(p) for p in _signal_group_key(play))


def _matchup(play: dict[str, Any]) -> str:
    return f"{play.get('away_team')}@{play.get('home_team')}"


def _find_game(signals: dict[str, Any], play: dict[str, Any]) -> dict[str, Any] | None:
    eid = str(play.get("event_id") or "")
    for g in signals.get("games") or []:
        if str(g.get("event_id")) == eid:
            return g
    home, away = play.get("home_team"), play.get("away_team")
    for g in signals.get("games") or []:
        if g.get("home_team") == home and g.get("away_team") == away:
            return g
    return None


def _find_event_odds(signals: dict[str, Any], play: dict[str, Any]) -> dict[str, Any] | None:
    """Best-effort event with bookmakers from signals payload."""
    eid = str(play.get("event_id") or "")
    for key in ("events", "games"):
        for ev in signals.get(key) or []:
            if str(ev.get("event_id")) == eid:
                return ev
    return None


def _split_board(signals: dict[str, Any], play: dict[str, Any]) -> dict[str, Any] | None:
    home, away = play.get("home_team"), play.get("away_team")
    for sb in signals.get("split_boards") or []:
        if sb.get("home_team") == home and sb.get("away_team") == away:
            return sb
    return None


def _ratings_map(signals: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for r in signals.get("ratings") or []:
        team = r.get("team")
        if team:
            out[str(team)] = float(r.get("power") or 0.0)
    return out


def _count_books_on_market(signals: dict[str, Any], play: dict[str, Any]) -> int:
    """Count distinct books offering this market from raw signals if present."""
    market = play.get("market")
    side = play.get("side")
    line = play.get("line")
    books: set[str] = set()
    for sig in signals.get("signals") or []:
        if (
            sig.get("event_id") == play.get("event_id")
            and sig.get("market") == market
            and sig.get("side") == side
        ):
            if line is None or sig.get("line") == line:
                if sig.get("book"):
                    books.add(str(sig["book"]))
    if books:
        return len(books)
    # Fallback: count from validated + candidates on same logical bet
    for sig in signals.get("signals") or []:
        if (
            _logical_play_key(sig) == _logical_play_key(play)
            and sig.get("book")
        ):
            books.add(str(sig["book"]))
    return len(books)


def _validated_keys(signals: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for s in signals.get("plays") or []:
        if s.get("filter_passed"):
            keys.add(_logical_play_key(s))
    return keys


def _duplicate_p_true_clusters(signals: dict[str, Any]) -> set[float]:
    """p_true values that appear suspiciously often (degenerate sim inputs)."""
    from collections import Counter

    counts: Counter[float] = Counter()
    for s in signals.get("signals") or []:
        pt = s.get("p_true")
        if pt is not None:
            counts[round(float(pt), 4)] += 1
    return {p for p, n in counts.items() if n >= DUPLICATE_P_TRUE_MIN_CLUSTER}


def review_signals(
    signals: dict[str, Any],
    *,
    sport: str = "nfl",
    allow_demo: bool = False,
) -> list[QAIssue]:
    """Layer 1 — data provenance checks on a pipeline payload."""
    issues: list[QAIssue] = []
    sport_cfg = get_sport(sport)

    if signals.get("demo") and not allow_demo:
        issues.append(
            QAIssue("demo_mode", "block", "Pipeline ran in demo mode — not safe to deploy")
        )

    n_games = int(signals.get("n_games") or len(signals.get("games") or []))
    min_games = NFL_GAMEDAY_MIN_GAMES if sport_cfg.key == "nfl" else NCAAF_GAMEDAY_MIN_GAMES
    if n_games < min_games:
        issues.append(
            QAIssue(
                "low_game_count",
                "block",
                f"Only {n_games} games in slate (need ≥{min_games} for {sport_cfg.display})",
            )
        )

    ratings = signals.get("ratings") or []
    n_teams = len(ratings)
    min_teams = MIN_RATED_TEAMS_NFL if sport_cfg.key == "nfl" else MIN_RATED_TEAMS_NCAAF
    powers = [float(r.get("power") or 0) for r in ratings]
    power_stdev = statistics.pstdev(powers) if len(powers) > 1 else 0.0

    if n_teams < min_teams:
        issues.append(
            QAIssue(
                "flat_ratings_count",
                "block",
                f"Only {n_teams} rated teams (need ≥{min_teams}) — likely skip-pbp or demo ratings",
            )
        )
    if power_stdev < MIN_POWER_STDEV:
        issues.append(
            QAIssue(
                "flat_ratings_spread",
                "block",
                f"Rating power stdev {power_stdev:.4f} < {MIN_POWER_STDEV} — degenerate/demo table",
            )
        )

    if not signals.get("demo") and int(signals.get("n_splits_games") or 0) == 0:
        issues.append(
            QAIssue(
                "no_splits",
                "warn",
                "Action Network splits unavailable — Phase 4 confirmation may be incomplete",
            )
        )

    return issues


def review_play(
    play: dict[str, Any],
    signals: dict[str, Any],
    *,
    sport: str = "nfl",
    validated_keys: set[str] | None = None,
    dup_p_true: set[float] | None = None,
) -> PlayReview:
    """Layer 2 — sanity review for a single pending ledger play."""
    issues: list[QAIssue] = []
    matchup = _matchup(play)
    validated_keys = validated_keys if validated_keys is not None else _validated_keys(signals)
    dup_p_true = dup_p_true if dup_p_true is not None else _duplicate_p_true_clusters(signals)
    logical = _logical_play_key(play)

    kickoff = parse_commence(play.get("kickoff") or play.get("commence_time"))
    games = signals.get("games") or []
    slate_plays = filter_plays_nfl_display_slate([play], events=games) if sport == "nfl" else [play]
    if kickoff is None:
        issues.append(QAIssue("missing_kickoff", "quarantine", "Play has no parseable kickoff"))
    elif not slate_plays:
        issues.append(
            QAIssue(
                "stale_kickoff",
                "void",
                f"Kickoff {kickoff.date()} outside current display week — stale/orphan play",
            )
        )

    game = _find_game(signals, play)
    if game is None:
        issues.append(
            QAIssue("orphan_event", "void", "Game not found in latest pipeline output")
        )
    elif logical not in validated_keys:
        issues.append(
            QAIssue(
                "not_revalidated",
                "void",
                "Play no longer passes Phase 4 filters in the latest pipeline run",
            )
        )

    ratings = _ratings_map(signals)
    home, away = play.get("home_team"), play.get("away_team")
    for team in (home, away):
        if team not in ratings:
            issues.append(
                QAIssue("unrated_team", "quarantine", f"Team {team} missing from power ratings")
            )

    n_books = _count_books_on_market(signals, play)
    if n_books < MIN_BOOKS_FOR_CORROBORATION:
        issues.append(
            QAIssue(
                "single_book",
                "quarantine",
                f"Only {n_books} book(s) on this line — no multi-book corroboration",
            )
        )

    pt = play.get("p_true")
    if pt is not None and round(float(pt), 4) in dup_p_true:
        issues.append(
            QAIssue(
                "duplicate_p_true",
                "quarantine",
                f"p_true={float(pt):.4f} appears in a suspicious cluster — degenerate sim inputs?",
            )
        )

    market = play.get("market")
    side = play.get("side")
    settings = get_settings()
    if market == "spreads":
        p_true = play.get("p_true")
        p_mkt = play.get("p_mkt")
        if p_true is not None and p_mkt is not None:
            prob_gap = abs(float(p_true) - float(p_mkt))
            if prob_gap >= settings.spread_model_prob_gap:
                issues.append(
                    QAIssue(
                        "spread_model_conflict",
                        "quarantine",
                        f"Model cover prob {float(p_true):.1%} vs sharp market "
                        f"{float(p_mkt):.1%} (Δ{prob_gap:.0%}) — implausible disagreement",
                    )
                )

        model_spread = play.get("model_spread")
        if model_spread is None and game is not None:
            model_spread = game.get("model_spread")
        line = play.get("line")
        if model_spread is not None and line is not None and side in ("home", "away"):
            home_line = float(line) if side == "home" else -float(line)
            line_gap = abs(float(model_spread) - home_line)
            if line_gap >= settings.spread_model_line_gap:
                issues.append(
                    QAIssue(
                        "spread_model_conflict",
                        "quarantine",
                        f"Model spread {float(model_spread):+.1f} vs market home line "
                        f"{home_line:+.1f} (Δ{line_gap:.1f} pts) — implausible disagreement",
                    )
                )
    if market == "h2h" and game is not None:
        p_home_win = game.get("p_home_win")
        p_true = float(play.get("p_true") or 0)
        if p_home_win is not None:
            p_home = float(p_home_win)
            if side == "away" and p_home > 0.5 and p_true < 0.5:
                issues.append(
                    QAIssue(
                        "ml_model_conflict",
                        "quarantine",
                        f"Model favors {home} to win ({p_home:.1%}) but play is {away} ML "
                        f"(p_true={p_true:.1%})",
                    )
                )
            elif side == "home" and p_home < 0.5 and p_true < 0.5:
                issues.append(
                    QAIssue(
                        "ml_model_conflict",
                        "quarantine",
                        f"Model favors {away} to win ({1 - p_home:.1%}) but play is {home} ML "
                        f"(p_true={p_true:.1%})",
                    )
                )

        sb = _split_board(signals, play)
        if sb:
            spread = (sb.get("markets") or {}).get("spread") or {}
            se = spread.get("sharp_edge") or {}
            gap = float(se.get("diff_pct") or 0)
            se_side = se.get("side")
            if (
                se.get("available")
                and gap >= get_settings().money_ticket_gap
                and se_side
                and se_side != side
            ):
                issues.append(
                    QAIssue(
                        "cross_market_conflict",
                        "quarantine",
                        f"Spread sharp money on {se.get('team')} (+{gap:.0%} gap) "
                        f"conflicts with ML play on {play.get('away_team' if side == 'away' else 'home_team')}",
                    )
                )

            ml = (sb.get("markets") or {}).get("moneyline") or {}
            ml_se = ml.get("sharp_edge") or {}
            ml_gap = float(ml_se.get("diff_pct") or 0)
            if ml_se.get("available") and ml_gap < get_settings().money_ticket_gap:
                issues.append(
                    QAIssue(
                        "weak_ml_confirmation",
                        "quarantine",
                        f"ML handle gap only +{ml_gap:.0%} (need ≥{get_settings().money_ticket_gap:.0%})",
                    )
                )

    book = str(play.get("book") or "")
    all_known = set(settings.sharp_books + settings.retail_books)
    if book and book not in all_known:
        close = play.get("close_price")
        price = play.get("price")
        if close is not None and price is not None and abs(float(price) - float(close)) > 15:
            issues.append(
                QAIssue(
                    "offshore_outlier",
                    "quarantine",
                    f"Offshore book {book} price {price:+.0f} diverges from "
                    f"{play.get('close_book')} close {close:+.0f}",
                )
            )

    # Determine action: void > quarantine > approve
    severities = {i.severity for i in issues}
    if "void" in severities:
        action = "void"
    elif "quarantine" in severities:
        action = "quarantine"
    else:
        action = "approve"

    return PlayReview(
        play_id=play.get("id"),
        matchup=matchup,
        market=str(market or ""),
        side=str(side or ""),
        action=action,
        issues=issues,
    )


def apply_qa_gate(
    sport: str = "nfl",
    *,
    signals: dict[str, Any] | None = None,
    apply: bool = True,
    allow_demo: bool = False,
    ledger_path: Path | None = None,
) -> QAGateResult:
    """Run full QA gate: review signals + pending ledger plays, optionally apply."""
    sport_cfg = get_sport(sport)
    if signals is None:
        sig_path = ARTIFACTS_DIR / sport_cfg.artifact_name
        if sig_path.exists():
            signals = json.loads(sig_path.read_text())
        else:
            docs_path = DATA_DIR.parent / "docs" / sport_cfg.artifact_name
            if docs_path.exists():
                signals = json.loads(docs_path.read_text())
            else:
                signals = {}

    layer1 = review_signals(signals, sport=sport, allow_demo=allow_demo)
    layer1_passed = not any(i.severity == "block" for i in layer1)

    path = ledger_path or (DATA_DIR / sport_cfg.ledger_name)
    ledger = load_ledger(path)
    games = signals.get("games") or []
    pending = [
        p
        for p in ledger.get("plays") or []
        if (p.get("status") or "pending") == "pending"
    ]
    if sport == "nfl":
        pending = filter_plays_nfl_display_slate(pending, events=games)
    elif sport == "ncaaf":
        from sharp_scout.utils.slate import filter_plays_college_week

        pending = filter_plays_college_week(pending)

    validated_keys = _validated_keys(signals)
    dup_p_true = _duplicate_p_true_clusters(signals)

    play_reviews: list[PlayReview] = []
    approved = quarantined = voided = 0
    now = datetime.now(timezone.utc).isoformat()

    for play in pending:
        review = review_play(
            play,
            signals,
            sport=sport,
            validated_keys=validated_keys,
            dup_p_true=dup_p_true,
        )
        play_reviews.append(review)
        if review.action == "approve":
            approved += 1
        elif review.action == "quarantine":
            quarantined += 1
            if apply:
                play["status"] = "quarantined"
                play["qa_at"] = now
                play["qa_notes"] = [i.to_dict() for i in review.issues]
        elif review.action == "void":
            voided += 1
            if apply:
                play["status"] = "void"
                play["qa_at"] = now
                play["qa_notes"] = [i.to_dict() for i in review.issues]

    # Also void pending plays outside display week that weren't in the filtered list
    if apply:
        all_pending = [
            p
            for p in ledger.get("plays") or []
            if (p.get("status") or "pending") == "pending"
        ]
        display_ids = {id(p) for p in pending}
        for play in all_pending:
            if id(play) in display_ids:
                continue
            review = review_play(
                play,
                signals,
                sport=sport,
                validated_keys=validated_keys,
                dup_p_true=dup_p_true,
            )
            if review.action in ("void", "quarantine"):
                play_reviews.append(review)
                if review.action == "void":
                    voided += 1
                    play["status"] = "void"
                else:
                    quarantined += 1
                    play["status"] = "quarantined"
                play["qa_at"] = now
                play["qa_notes"] = [i.to_dict() for i in review.issues]

        save_ledger(ledger, path)

    result = QAGateResult(
        sport=sport,
        layer1_passed=layer1_passed,
        layer1_issues=layer1,
        play_reviews=play_reviews,
        approved=approved,
        quarantined=quarantined,
        voided=voided,
        block_deploy=not layer1_passed,
        generated_at=now,
    )

    QA_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = QA_REPORT_DIR / f"{sport}_qa_{now[:10]}.json"
    report_path.write_text(json.dumps(result.summary(), indent=2) + "\n")
    logger.info(
        "QA gate (%s): layer1=%s approved=%d quarantined=%d voided=%d",
        sport,
        "PASS" if layer1_passed else "FAIL",
        approved,
        quarantined,
        voided,
    )
    return result
