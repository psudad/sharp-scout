"""Sharp fair prices for NBA — Pinnacle no-vig with multi-book consensus fallback."""

from __future__ import annotations

from typing import Any

from sharp_scout.config import get_settings
from sharp_scout.phase3.market import fair_probs_from_two_way, shift_prob_to_line
from sharp_scout.sports import NBA


def _pair_outcomes(outcomes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_side: dict[str, dict[str, Any]] = {}
    for o in outcomes:
        side = str(o.get("side") or "").lower()
        if side:
            by_side[side] = o
    return by_side


def sharp_two_way_fair(
    event: dict[str, Any],
    market: str,
) -> dict[str, Any] | None:
    """Pinnacle-first no-vig two-way fair (same preference order as sides pipeline)."""
    books = event.get("bookmakers") or {}
    preference = ["pinnacle", "circa", "circa_sports", "betfair_ex_eu"]
    chosen = None
    for key in preference:
        if key in books and market in (books[key].get("markets") or {}):
            chosen = (key, books[key]["markets"][market])
            break
    if chosen is None:
        for key, bm in books.items():
            if bm.get("is_sharp") and market in (bm.get("markets") or {}):
                chosen = (key, bm["markets"][market])
                break
    if chosen is None:
        return None
    book, outcomes = chosen
    if len(outcomes) < 2:
        return None
    a, b = outcomes[0], outcomes[1]
    if a.get("price") is None or b.get("price") is None:
        return None
    pa, pb = fair_probs_from_two_way(float(a["price"]), float(b["price"]))
    return {
        "book": book,
        "source": "pinnacle",
        "outcomes": [
            {**a, "p_fair": pa},
            {**b, "p_fair": pb},
        ],
    }


def consensus_two_way_fair(
    event: dict[str, Any],
    market: str,
    *,
    min_books: int | None = None,
) -> dict[str, Any] | None:
    """Median no-vig probability per side across all books quoting the market."""
    settings = get_settings()
    need = settings.nba_prop_consensus_min_books if min_books is None else min_books
    books = event.get("bookmakers") or {}
    acc: dict[str, list[float]] = {}
    ref_lines: dict[str, list[float]] = {}
    for bm in books.values():
        outcomes = (bm.get("markets") or {}).get(market) or []
        paired = _pair_outcomes(outcomes)
        if len(paired) < 2:
            continue
        sides = sorted(paired.keys())
        if len(sides) != 2:
            continue
        oa, ob = paired[sides[0]], paired[sides[1]]
        if oa.get("price") is None or ob.get("price") is None:
            continue
        # Totals/spreads may differ by line across books — bucket by rounded line key
        line_key = str(oa.get("point"))
        fa, fb = fair_probs_from_two_way(float(oa["price"]), float(ob["price"]))
        acc.setdefault(sides[0], []).append(fa)
        acc.setdefault(sides[1], []).append(fb)
        ref_lines.setdefault(sides[0], []).append(float(oa.get("point") or 0))
        ref_lines.setdefault(sides[1], []).append(float(ob.get("point") or 0))

    if not acc or min(len(v) for v in acc.values()) < need:
        return None

    def median(xs: list[float]) -> float:
        s = sorted(xs)
        mid = len(s) // 2
        return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2

    sides = sorted(acc.keys())
    return {
        "book": "consensus",
        "source": "consensus",
        "outcomes": [
            {"side": sides[0], "p_fair": median(acc[sides[0]]), "point": median(ref_lines[sides[0]])},
            {"side": sides[1], "p_fair": median(acc[sides[1]]), "point": median(ref_lines[sides[1]])},
        ],
    }


def fair_reference(
    event: dict[str, Any],
    market: str,
    *,
    min_books: int | None = None,
) -> dict[str, Any] | None:
    sharp = sharp_two_way_fair(event, market)
    if sharp:
        return sharp
    return consensus_two_way_fair(event, market, min_books=min_books)


def fair_prob_at_line(
    ref: dict[str, Any],
    *,
    market: str,
    side: str,
    line: float | None,
    sd: float | None = None,
) -> tuple[float | None, float | None, str | None]:
    """Return (p_fair, line_gain, ref_book) for a side at the offered line."""
    sd = sd or (NBA.margin_sd if market == "spreads" else NBA.total_sd)
    ref_map = {str(o.get("side")).lower(): o for o in ref.get("outcomes") or []}
    side_l = str(side).lower()
    if side_l not in ref_map:
        return None, None, ref.get("book")
    o = ref_map[side_l]
    p_ref = o.get("p_fair")
    if p_ref is None:
        return None, None, ref.get("book")
    p_fair, gain = shift_prob_to_line(
        float(p_ref),
        market=market,
        side=side_l,
        ref_line=o.get("point"),
        line=line,
        sd=sd,
    )
    return p_fair, gain, ref.get("book")


def prop_consensus_over_prob(
    event: dict[str, Any],
    market: str,
    player: str,
    line: float,
    *,
    min_books: int | None = None,
) -> float | None:
    """Median no-vig over probability for a player prop line across books."""
    settings = get_settings()
    need = settings.nba_prop_consensus_min_books if min_books is None else min_books
    pk = _norm(player)
    acc: list[float] = []
    for bm in (event.get("bookmakers") or {}).values():
        outcomes = (bm.get("markets") or {}).get(market) or []
        pair: dict[str, float] = {}
        for o in outcomes:
            name = o.get("description") or o.get("player") or o.get("name") or ""
            if _norm(name) != pk:
                continue
            side = str(o.get("side") or o.get("name") or "").lower()
            if o.get("point") is None or o.get("price") is None:
                continue
            if float(o["point"]) != float(line):
                continue
            if side in ("over", "under"):
                pair[side] = float(o["price"])
        if "over" in pair and "under" in pair:
            fo, _ = fair_probs_from_two_way(pair["over"], pair["under"])
            acc.append(fo)
    if len(acc) < need:
        return None
    s = sorted(acc)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def _norm(name: str) -> str:
    return " ".join((name or "").lower().split())
