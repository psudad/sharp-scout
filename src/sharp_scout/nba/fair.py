"""Sharp fair prices for NBA — Pinnacle no-vig with multi-book consensus fallback."""

from __future__ import annotations

import logging
from typing import Any

from sharp_scout.config import get_settings
from sharp_scout.phase3.market import fair_probs_from_two_way, shift_prob_to_line
from sharp_scout.sports import NBA
from sharp_scout.utils.odds import american_to_implied_prob

logger = logging.getLogger(__name__)

# --- Moneyline (h2h) anchor guard -------------------------------------------------
# Sharp books tried in order for a moneyline anchor. Exchanges (Betfair) are never used:
# a day ahead their empty markets come back as placeholder prices (-10000 / 1.01 decimal).
ML_ANCHOR_BOOKS: tuple[str, ...] = ("pinnacle", "circa", "circa_sports")
ML_EXCLUDED_BOOK_PREFIXES: tuple[str, ...] = ("betfair",)
# Either price at -2000 or shorter, or +2000 or longer, is treated as a placeholder.
ML_PRICE_LIMIT = 2000.0
# Sum of the two implied probabilities (overround) must look like a real two-way market.
ML_OVERROUND_MIN = 1.00
ML_OVERROUND_MAX = 1.10


def _pair_outcomes(outcomes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_side: dict[str, dict[str, Any]] = {}
    for o in outcomes:
        side = str(o.get("side") or "").lower()
        if side:
            by_side[side] = o
    return by_side


def _ml_book_excluded(book_key: str) -> bool:
    k = str(book_key or "").lower()
    return any(k.startswith(prefix) for prefix in ML_EXCLUDED_BOOK_PREFIXES)


def _h2h_side(outcome: dict[str, Any], event: dict[str, Any]) -> str | None:
    """Map a moneyline outcome to ``home`` / ``away`` by its side, else by team name."""
    side = str(outcome.get("side") or "").strip().lower()
    if side in ("home", "away"):
        return side
    name = outcome.get("name") or outcome.get("side")
    if not name:
        return None
    from sharp_scout.nba.teams import normalize_nba_team

    team = normalize_nba_team(str(name))
    home = event.get("home_team")
    away = event.get("away_team")
    home_n = normalize_nba_team(str(home)) if home else None
    away_n = normalize_nba_team(str(away)) if away else None
    if team and home_n and team == home_n and team != away_n:
        return "home"
    if team and away_n and team == away_n and team != home_n:
        return "away"
    return None


def _ml_price_ok(price: Any) -> float | None:
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None
    if p != p or abs(p) < 100.0:  # NaN or not a valid American price
        return None
    if p <= -ML_PRICE_LIMIT or p >= ML_PRICE_LIMIT:
        return None
    return p


def validated_h2h_prices(
    outcomes: list[dict[str, Any]] | None,
    event: dict[str, Any],
) -> tuple[dict[str, float] | None, str | None]:
    """Return ({"home": price, "away": price}, None) or (None, reject_reason)."""
    outcomes = outcomes or []
    prices: dict[str, float] = {}
    for o in outcomes:
        side = _h2h_side(o, event)
        if side is None:
            return None, f"unmatched outcome {o.get('name') or o.get('side')!r}"
        if side in prices:
            return None, f"two outcomes for {side}"
        p = _ml_price_ok(o.get("price"))
        if p is None:
            return None, f"placeholder or invalid price {o.get('price')!r} ({side})"
        prices[side] = p
    if set(prices) != {"home", "away"}:
        return None, "missing home or away price"
    overround = american_to_implied_prob(prices["home"]) + american_to_implied_prob(prices["away"])
    if not (ML_OVERROUND_MIN <= overround <= ML_OVERROUND_MAX):
        return None, f"implied total {overround:.3f} outside {ML_OVERROUND_MIN:.2f}-{ML_OVERROUND_MAX:.2f}"
    return prices, None


def _h2h_fair_from_prices(prices: dict[str, float]) -> tuple[float, float]:
    return fair_probs_from_two_way(prices["home"], prices["away"])


def h2h_sharp_anchor(event: dict[str, Any]) -> dict[str, Any] | None:
    """First sharp book (Pinnacle, Circa) with a sane, side-matched moneyline. Never Betfair."""
    books = event.get("bookmakers") or {}
    order = [k for k in ML_ANCHOR_BOOKS if k in books]
    order += [
        k
        for k, bm in books.items()
        if k not in order and bm.get("is_sharp") and not _ml_book_excluded(k)
    ]
    for key in order:
        if _ml_book_excluded(key):
            continue
        outcomes = ((books.get(key) or {}).get("markets") or {}).get("h2h")
        if not outcomes:
            continue
        prices, why = validated_h2h_prices(outcomes, event)
        if prices is None:
            logger.info(
                "NBA ML anchor rejected %s for %s@%s: %s",
                key,
                event.get("away_team"),
                event.get("home_team"),
                why,
            )
            continue
        ph, pa = _h2h_fair_from_prices(prices)
        return {
            "book": key,
            "source": key,
            "outcomes": [
                {"side": "home", "price": prices["home"], "point": None, "p_fair": ph},
                {"side": "away", "price": prices["away"], "point": None, "p_fair": pa},
            ],
        }
    return None


def h2h_consensus_fair(event: dict[str, Any], *, min_books: int = 2) -> dict[str, Any] | None:
    """Median no-vig home win prob across books with a sane moneyline (no exchanges)."""
    homes: list[float] = []
    used: list[str] = []
    for key, bm in (event.get("bookmakers") or {}).items():
        if _ml_book_excluded(key):
            continue
        outcomes = (bm.get("markets") or {}).get("h2h")
        if not outcomes:
            continue
        prices, _why = validated_h2h_prices(outcomes, event)
        if prices is None:
            continue
        ph, _pa = _h2h_fair_from_prices(prices)
        homes.append(ph)
        used.append(key)
    if len(homes) < max(2, int(min_books or 2)):
        return None
    s = sorted(homes)
    mid = len(s) // 2
    ph = s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2
    return {
        "book": "consensus",
        "source": "consensus",
        "books": sorted(used),
        "outcomes": [
            {"side": "home", "point": None, "p_fair": ph},
            {"side": "away", "point": None, "p_fair": 1.0 - ph},
        ],
    }


def h2h_fair_reference(event: dict[str, Any], *, min_books: int | None = None) -> dict[str, Any] | None:
    """Guarded moneyline fair: sharp anchor, else median of >=2 sane books, else None (skip)."""
    anchor = h2h_sharp_anchor(event)
    if anchor:
        return anchor
    return h2h_consensus_fair(event, min_books=2 if min_books is None else max(2, min_books))


def sharp_two_way_fair(
    event: dict[str, Any],
    market: str,
) -> dict[str, Any] | None:
    """Pinnacle-first no-vig two-way fair (same preference order as sides pipeline).

    Moneylines (h2h) go through the guarded anchor (:func:`h2h_sharp_anchor`); spreads and
    totals are unchanged.
    """
    if market == "h2h":
        return h2h_sharp_anchor(event)
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
    if market == "h2h":
        return h2h_consensus_fair(event, min_books=2 if min_books is None else max(2, min_books))
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
    if market == "h2h":
        return h2h_fair_reference(event, min_books=min_books)
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
    exclude_books: set[str] | None = None,
) -> float | None:
    """Median no-vig over probability for a player prop line across books."""
    settings = get_settings()
    need = settings.nba_prop_consensus_min_books if min_books is None else min_books
    skip = {b.lower() for b in (exclude_books or set())}
    pk = _norm(player)
    acc: list[float] = []
    for book_key, bm in (event.get("bookmakers") or {}).items():
        if book_key.lower() in skip:
            continue
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
