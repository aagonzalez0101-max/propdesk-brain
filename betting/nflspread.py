"""Price NFL spreads, alt spreads and totals off the MEASURED margin distribution.

The closing spread is an unbiased estimate -- home covers 47.6% across 5,295
games and stays near 50% at every spread level -- so there is no edge in
disagreeing with it. The edge, if any, is in the ALT lines, because NFL margins
are violently lumpy and a normal curve misprices them:

    margin 3 -> 14.7% of all games
    margin 7 ->  8.9%
    margin 6 ->  6.4%
    3 and 7 together are 23.5% of every NFL game ever played

So buying or selling through 3 is worth several times what a bell curve says,
and that is knowable without predicting anything.

Method: measure the residual r = margin - spread across history, then for any
alt line L, P(cover L) = P(r > L - spread). The residual distribution is what
carries the key numbers, and it is measured, not assumed.
"""
from __future__ import annotations

import collections
import json
import os

from . import nfldata as ND

CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "_nfl_residual.json")


def build_residuals(min_season: int = 2006, near: float | None = None,
                    window: float = 2.0) -> dict:
    """Residuals, optionally CONDITIONED on games whose spread sits near `near`.

    Pooling every spread level together smears the key numbers: measured
    2026-09-15, the pooled fit priced EVERY half-point buy at the same +4.4pp,
    so -3.5 -> -2.5 looked identical to -8.5 -> -7.5. Margins cluster on 3 and 7
    RELATIVE TO THE SPREAD, so the distribution has to be fit on games priced in
    the same neighbourhood. `near` is the market spread (feed convention);
    `window` is how many points either side to include.
    """
    return _build(min_season, near, window)


def _build(min_season: int = 2006, near: float | None = None,
           window: float = 2.0) -> dict:
    """P(margin - spread = r) for each integer r, measured on real games.

    Spread convention in the nflverse feed: positive = HOME favoured by that
    many points, and `margin` is the home margin. So home covers when
    margin > spread. Both were verified against the 47.6% base rate; getting
    the sign wrong produces 22%, which is how the error announces itself.
    """
    g = [x for x in ND.games(min_season=min_season)
         if x.get("margin") is not None and x.get("spread") is not None]
    if near is not None:
        g = [x for x in g if abs(abs(x["spread"]) - abs(near)) <= window] or g
    # Keep HALF-POINT granularity. Rounding r to an integer collapses the
    # push cases -- with a market of -3.5, a margin of exactly 3 gives r = -0.5,
    # which is precisely the outcome that makes buying off 3 valuable. Rounding
    # it away made -3.0 and -2.5 price identically.
    c = collections.Counter()
    for x in g:
        c[round((x["margin"] - x["spread"]) * 2) / 2.0] += 1
    n = sum(c.values())
    return {"n": n, "dist": {str(k): v / n for k, v in sorted(c.items())}}


def residuals(force: bool = False) -> dict:
    if not force and os.path.exists(CACHE):
        return json.load(open(CACHE, encoding="utf-8"))
    r = build_residuals()
    json.dump(r, open(CACHE, "w"))
    return r


_COND_CACHE: dict = {}


def cover_cond(spread: float, line: float, min_season: int = 2006,
               window: float = 2.0) -> tuple:
    """cover() using residuals fit on games priced NEAR this spread."""
    key = (round(abs(spread)), min_season, window)
    if key not in _COND_CACHE:
        _COND_CACHE[key] = _build(min_season, near=spread, window=window)
    return cover(spread, line, _COND_CACHE[key])


def cover(spread: float, line: float, res: dict | None = None) -> tuple:
    """(P(cover), P(push), P(lose)) for taking `line` when the market is `spread`.

    Both are quoted from the HOME side: spread -3.5 means home favoured by 3.5,
    and line -7.5 means you are laying 7.5 with them. An integer line can push.
    """
    res = res or residuals()
    d = {float(k): v for k, v in res["dist"].items()}
    # Arguments are in the COMMON convention: -3.5 means that side lays 3.5.
    # The feed stores the opposite sign, so the residual r = margin - feed_spread
    # = margin + line_market, and covering an alt line needs r > market - alt.
    # Getting this backwards makes laying 10.5 look EASIER than laying 3.5,
    # which is how the error announces itself.
    need = spread - line
    win = sum(v for r, v in d.items() if r > need + 1e-9)
    push = sum(v for r, v in d.items() if abs(r - need) < 1e-9)
    return win, push, 1.0 - win - push


def ladder(spread: float, lo: float = -14.5, hi: float = 14.5) -> list:
    """Every half-point line from lo to hi, with its measured cover probability."""
    res = residuals()
    out = []
    x = lo
    while x <= hi + 1e-9:
        w, p, l = cover(spread, x, res)
        out.append((round(x, 1), w, p, l))
        x += 0.5
    return out


def point_value(spread: float, frm: float, to: float) -> float:
    """Percentage points of cover probability gained moving from `frm` to `to`."""
    res = residuals()
    return cover(spread, to, res)[0] - cover(spread, frm, res)[0]
