"""
Turn a raw Odds API board into one honest probability per outcome.

Twenty books quote twenty different prices at twenty different hold levels.
Averaging them naively is wrong: a 5%-hold retail book and a 1%-hold exchange
do not deserve equal say. This module de-vigs each book on its own, then
weights them by how much their price is worth listening to.

The exchange cluster (Novig / Kalshi / Polymarket / ProphetX) is the anchor.
Those are real-money exchanges and prediction markets -- their consensus is
the closest thing to true probability available for free, and Novig is the
book actually being bet.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .oddsapi import EXCHANGE_BOOKS, RETAIL_BOOKS, SHARP_BOOKS
from .oddsmath import (american_to_prob, devig, hold_pct, min_price_for_edge,
                       prob_to_american)

# How much each class of book counts toward the fair-value consensus.
# Exchanges dominate because their hold is near zero and their prices are set
# by people risking money against each other, not by a margin-taking book.
BOOK_WEIGHTS: dict[str, float] = {
    "novig": 3.0,
    "prophetx": 2.5,
    "kalshi": 2.5,
    "polymarket": 2.5,
    "betopenly": 2.0,
    "pinnacle": 3.0,
    "lowvig": 1.5,
    "betonlineag": 1.2,
    "betanysports": 1.0,
    "circasports": 2.0,
}
DEFAULT_WEIGHT = 0.6  # retail books


def book_weight(key: str) -> float:
    return BOOK_WEIGHTS.get(key, DEFAULT_WEIGHT)


@dataclass
class Quote:
    """One book's price on one side."""
    book: str
    price: float
    point: float | None = None

    @property
    def raw_prob(self) -> float:
        return american_to_prob(self.price)


@dataclass
class TwoWayMarket:
    """
    A two-sided market (moneyline, a total's over/under, a prop's over/under)
    across every book that quotes it.
    """
    key: str                       # e.g. "h2h", "totals", "pitcher_strikeouts"
    label_a: str                   # e.g. home team, or "Over"
    label_b: str
    point: float | None = None
    quotes_a: list[Quote] = field(default_factory=list)
    quotes_b: list[Quote] = field(default_factory=list)

    # ------------------------------------------------------------- per book

    def paired(self) -> list[tuple[str, float, float]]:
        """(book, price_a, price_b) for books quoting BOTH sides -- required to de-vig."""
        by_b = {q.book: q.price for q in self.quotes_b}
        return [(q.book, q.price, by_b[q.book]) for q in self.quotes_a if q.book in by_b]

    def per_book_fair(self, method: str = "power",
                      exclude: set[str] | None = None) -> dict[str, float]:
        """
        De-vigged probability of side A, per book.

        `exclude` drops books from the calculation. Essential when judging a
        specific book's price: if Novig helps set the consensus, then Novig is
        partly grading its own homework and any real edge is shrunk toward
        zero. The benchmark must be the market MINUS the book being bet.
        """
        out = {}
        for book, pa, pb in self.paired():
            if exclude and book in exclude:
                continue
            try:
                out[book] = devig([american_to_prob(pa), american_to_prob(pb)], method)[0]
            except (ValueError, ZeroDivisionError):
                continue
        return out

    def holds(self) -> dict[str, float]:
        return {
            book: hold_pct([american_to_prob(pa), american_to_prob(pb)])
            for book, pa, pb in self.paired()
        }

    # ------------------------------------------------------------ consensus

    def fair_prob(self, method: str = "power",
                  exchanges_only: bool = False,
                  exclude: set[str] | None = None) -> float | None:
        """
        Weighted-consensus true probability for side A.

        With exchanges_only=True this uses just the exchange cluster, which is
        the cleanest read but is missing on thinner markets. `exclude` removes
        books -- use it to keep the book you are betting out of its own
        benchmark.
        """
        fairs = self.per_book_fair(method, exclude=exclude)
        if exchanges_only:
            fairs = {b: p for b, p in fairs.items() if b in EXCHANGE_BOOKS}
        if not fairs:
            return None
        num = sum(p * book_weight(b) for b, p in fairs.items())
        den = sum(book_weight(b) for b in fairs)
        return num / den if den else None

    def exchange_fair(self, method: str = "power") -> float | None:
        return self.fair_prob(method, exchanges_only=True)

    def consensus(self, method: str = "power") -> dict:
        """Everything worth knowing about where this market sits."""
        fairs = self.per_book_fair(method)
        ex = {b: p for b, p in fairs.items() if b in EXCHANGE_BOOKS}
        rt = {b: p for b, p in fairs.items() if b in RETAIL_BOOKS}
        blended = self.fair_prob(method)
        return {
            "n_books": len(fairs),
            "fair_a": blended,
            "fair_b": (1.0 - blended) if blended is not None else None,
            "exchange_fair_a": (sum(ex.values()) / len(ex)) if ex else None,
            "retail_fair_a": (sum(rt.values()) / len(rt)) if rt else None,
            "spread_pp": (max(fairs.values()) - min(fairs.values())) * 100 if fairs else None,
            "per_book": fairs,
            "holds": self.holds(),
        }

    # ----------------------------------------------------------- best price

    def best(self, side: str = "a") -> Quote | None:
        """Best available price on a side. Highest American value always wins."""
        qs = self.quotes_a if side == "a" else self.quotes_b
        return max(qs, key=lambda q: q.price) if qs else None

    def novig_quote(self, side: str = "a") -> Quote | None:
        qs = self.quotes_a if side == "a" else self.quotes_b
        return next((q for q in qs if q.book == "novig"), None)

    def disagreement_pp(self, method: str = "power") -> float | None:
        """
        Exchange fair minus retail fair, in percentage points.

        Large positive means the soft books are pricing side A cheaper than the
        exchanges think it should be -- the classic stale-line spot.
        """
        c = self.consensus(method)
        if c["exchange_fair_a"] is None or c["retail_fair_a"] is None:
            return None
        return (c["exchange_fair_a"] - c["retail_fair_a"]) * 100.0


# --------------------------------------------------------------- parsing

def parse_h2h(event: dict) -> TwoWayMarket | None:
    """Build the moneyline market from one Odds API event object."""
    home, away = event.get("home_team"), event.get("away_team")
    if not home or not away:
        return None
    m = TwoWayMarket(key="h2h", label_a=home, label_b=away)
    for bm in event.get("bookmakers", []):
        for mkt in bm.get("markets", []):
            if mkt.get("key") != "h2h":
                continue
            for o in mkt.get("outcomes", []):
                q = Quote(bm["key"], o["price"])
                if o["name"] == home:
                    m.quotes_a.append(q)
                elif o["name"] == away:
                    m.quotes_b.append(q)
    return m if m.paired() else None


def parse_market_key(event: dict, market_key: str,
                     label_a: str, label_b: str) -> TwoWayMarket | None:
    """
    Generic two-way parser for markets whose outcome names are fixed strings,
    e.g. h2h_1st_5_innings (team names) or totals (Over/Under).
    """
    m = TwoWayMarket(key=market_key, label_a=label_a, label_b=label_b)
    for bm in event.get("bookmakers", []):
        for mkt in bm.get("markets", []):
            if mkt.get("key") != market_key:
                continue
            for o in mkt.get("outcomes", []):
                q = Quote(bm["key"], o["price"], o.get("point"))
                if o["name"] == label_a:
                    m.quotes_a.append(q)
                elif o["name"] == label_b:
                    m.quotes_b.append(q)
    return m if m.paired() else None


def parse_player_props(event: dict, market_key: str) -> dict[str, list[TwoWayMarket]]:
    """
    Player props keyed by player name.

    Props use `description` for the player and `name` for Over/Under, and each
    book may hang a different line on the same player -- so we group by
    (player, point) and return a list of markets per player.
    """
    buckets: dict[tuple[str, float | None], TwoWayMarket] = {}
    for bm in event.get("bookmakers", []):
        for mkt in bm.get("markets", []):
            if mkt.get("key") != market_key:
                continue
            for o in mkt.get("outcomes", []):
                player = o.get("description")
                if not player:
                    continue
                pt = o.get("point")
                bk = (player, pt)
                if bk not in buckets:
                    buckets[bk] = TwoWayMarket(
                        key=market_key, label_a="Over", label_b="Under", point=pt
                    )
                q = Quote(bm["key"], o["price"], pt)
                if o["name"] == "Over":
                    buckets[bk].quotes_a.append(q)
                elif o["name"] == "Under":
                    buckets[bk].quotes_b.append(q)

    out: dict[str, list[TwoWayMarket]] = {}
    for (player, _pt), m in buckets.items():
        if m.paired():
            out.setdefault(player, []).append(m)
    for v in out.values():
        v.sort(key=lambda m: (m.point if m.point is not None else 0))
    return out


# ------------------------------------------------------------ recommendation

@dataclass
class Edge:
    """A priced opinion: what we think vs what the market pays."""
    market: str
    selection: str
    point: float | None
    model_prob: float
    market_prob: float
    fair_price: float
    best_price: float
    best_book: str
    novig_price: float | None
    min_price: float          # worst price still clearing the EV threshold
    ev_pct: float
    edge_pp: float
    stake: float = 0.0
    note: str = ""

    def __str__(self) -> str:
        pt = f" {self.point}" if self.point is not None else ""
        return (f"{self.selection}{pt} [{self.market}] "
                f"model {self.model_prob:.1%} vs mkt {self.market_prob:.1%} "
                f"| need {self.min_price:+.0f} | EV {self.ev_pct:+.1f}%")


def build_edge(market_name: str, selection: str, point: float | None,
               model_p: float, mkt: TwoWayMarket, side: str,
               min_ev_pct: float = 2.0, method: str = "power") -> Edge | None:
    """Compare a model probability against a market and package the result."""
    fair_a = mkt.fair_prob(method)
    if fair_a is None:
        return None
    market_p = fair_a if side == "a" else 1.0 - fair_a

    best = mkt.best(side)
    if best is None:
        return None
    nv = mkt.novig_quote(side)

    from .oddsmath import ev_percent
    return Edge(
        market=market_name,
        selection=selection,
        point=point,
        model_prob=model_p,
        market_prob=market_p,
        fair_price=prob_to_american(model_p),
        best_price=best.price,
        best_book=best.book,
        novig_price=nv.price if nv else None,
        min_price=min_price_for_edge(model_p, min_ev_pct),
        ev_pct=ev_percent(model_p, best.price),
        edge_pp=(model_p - market_p) * 100.0,
    )


def parse_totals(event: dict) -> TwoWayMarket | None:
    """
    Game totals (over/under runs).

    Books hang different numbers on the same game -- one at 8.5, another at 9 --
    and comparing across them would be meaningless. So we group by point and
    return the line the most books agree on, which is the one with the
    tightest, most reliable consensus.
    """
    buckets: dict[float, TwoWayMarket] = {}
    for bm in event.get("bookmakers", []):
        for mkt in bm.get("markets", []):
            if mkt.get("key") != "totals":
                continue
            for o in mkt.get("outcomes", []):
                pt = o.get("point")
                if pt is None:
                    continue
                if pt not in buckets:
                    buckets[pt] = TwoWayMarket(key="totals", label_a="Over",
                                               label_b="Under", point=pt)
                q = Quote(bm["key"], o["price"], pt)
                if o["name"] == "Over":
                    buckets[pt].quotes_a.append(q)
                elif o["name"] == "Under":
                    buckets[pt].quotes_b.append(q)

    priced = [m for m in buckets.values() if m.paired()]
    if not priced:
        return None
    return max(priced, key=lambda m: len(m.paired()))


def archive_market(sport: str, event: str, market: TwoWayMarket) -> None:
    """
    Persist every quoted price on a market to the local line archive.

    Historical player-prop lines are not available for free anywhere. The only
    way to ever backtest a prop model against real closing prices is to record
    them yourself, starting now -- so this runs on every market we fetch, at
    no extra API cost, and the archive is worth more every day it runs.
    """
    from . import db

    for side, quotes in (("a", market.quotes_a), ("b", market.quotes_b)):
        label = market.label_a if side == "a" else market.label_b
        for q in quotes:
            db.snapshot_line(sport, event, market.key, label,
                             q.book, q.price, market.point)
