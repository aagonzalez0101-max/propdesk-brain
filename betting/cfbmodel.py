"""
CFB team ratings -> margin and win probability.

The core problem college football has that the NFL does not: TALENT SPREAD.
Alabama and Kent State are in the same division. Margins run three touchdowns
routinely, so a rating system built on average margin gets dominated by
blowouts where the winner emptied the bench in the third quarter.

Two design choices follow from that:

  * Rate on YARDS PER PLAY, not points. Points include garbage time, special
    teams and turnover luck; yards per play is closer to repeatable quality.
    Turnovers get a separate, heavily regressed term because turnover margin
    is famously unstable year to year.
  * CAP the margin each game contributes. A 63-3 win says a team is good; it
    does not say they are five times better than a 42-14 win implies.

Opponent adjustment matters far more here than in the WNBA, where everyone
plays everyone. A CFB team plays twelve of 130-odd opponents, so raw averages
mostly measure schedule. This runs an iterative adjustment: rate each team,
then re-rate against the quality of who they actually played, repeat.
"""
from __future__ import annotations

import math
import statistics as st

from . import cfbdata as C

# Games before a team's own numbers outweigh the prior. Higher than the WNBA's
# 8 because CFB samples are shorter (12 games) and noisier.
REG_GAMES = 4.0

# Blowouts get capped. Beyond ~28 the extra margin is bench units.
MARGIN_CAP = 28.0

# Turnover margin is close to random year over year, so it is worth points in
# the game it happened and almost nothing as a predictor. Heavy shrink.
TO_WEIGHT = 0.35

# Points per yard-per-play advantage, fitted below in `calibrate`.
YPP_TO_POINTS = 13.0

# Standard deviation of actual margin around projection. CFB is far wider than
# the WNBA's 10.8 -- calibrated in `backtest`.
MARGIN_SD = 16.5

HOME_EDGE = 2.4          # points; verified against outcomes


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def collect(year: int, through_week: int, seasontype: int = 2) -> list[dict]:
    """Every completed FBS game with box scores, weeks 1..through_week."""
    rows = []
    for wk in range(1, through_week + 1):
        for g in C.week(year, wk, seasontype):
            if not g["final"]:
                continue
            ts = C.team_stats(g["id"])
            h, a = str(g["home_id"]), str(g["away_id"])
            if h not in ts or a not in ts:
                continue
            if ts[h]["plays"] < 30 or ts[a]["plays"] < 30:
                continue
            rows.append({**g, "week": wk, "hs": ts[h], "as": ts[a]})
    return rows


def ratings(rows: list[dict], iterations: int = 6) -> dict:
    """
    Opponent-adjusted offensive and defensive yards-per-play, plus a net rating
    in points.

    Iterative because a raw average mostly measures schedule: a team can look
    elite by beating nobody. Each pass re-rates every team against the current
    estimate of who they played, and the estimates converge.
    """
    lg_ypp = st.mean([r[k]["ypp"] for r in rows for k in ("hs", "as")]) or 5.5
    teams = {t for r in rows for t in (str(r["home_id"]), str(r["away_id"]))}
    off = {t: lg_ypp for t in teams}
    dfn = {t: lg_ypp for t in teams}

    for _ in range(iterations):
        o_new = {t: [] for t in teams}
        d_new = {t: [] for t in teams}
        for r in rows:
            h, a = str(r["home_id"]), str(r["away_id"])
            # what each offence did, adjusted for the defence it faced
            o_new[h].append(r["hs"]["ypp"] - (dfn[a] - lg_ypp))
            o_new[a].append(r["as"]["ypp"] - (dfn[h] - lg_ypp))
            d_new[h].append(r["as"]["ypp"] - (off[a] - lg_ypp))
            d_new[a].append(r["hs"]["ypp"] - (off[h] - lg_ypp))
        for t in teams:
            n = len(o_new[t])
            w = n / (n + REG_GAMES)
            off[t] = w * st.mean(o_new[t]) + (1 - w) * lg_ypp
            dfn[t] = w * st.mean(d_new[t]) + (1 - w) * lg_ypp

    # turnover margin per game, heavily regressed
    to = {t: [] for t in teams}
    for r in rows:
        h, a = str(r["home_id"]), str(r["away_id"])
        to[h].append(r["as"]["turnovers"] - r["hs"]["turnovers"])
        to[a].append(r["hs"]["turnovers"] - r["as"]["turnovers"])
    out = {}
    for t in teams:
        n = len(to[t])
        tom = (st.mean(to[t]) * (n / (n + 8.0))) if n else 0.0
        net = (off[t] - dfn[t]) * YPP_TO_POINTS + tom * TO_WEIGHT * 4.0
        out[t] = {"off_ypp": off[t], "def_ypp": dfn[t], "to_margin": tom,
                  "net": net, "games": n}
    return {"teams": out, "lg_ypp": lg_ypp}


def project(home_id: str, away_id: str, R: dict, neutral: bool = False) -> dict:
    h = R["teams"].get(str(home_id))
    a = R["teams"].get(str(away_id))
    if not h or not a:
        return {}
    margin = h["net"] - a["net"] + (0.0 if neutral else HOME_EDGE)
    return {"margin": margin, "p_home": _norm_cdf(margin / MARGIN_SD),
            "home_net": h["net"], "away_net": a["net"]}
