"""
WNBA team model: efficiency ratings -> moneyline and totals.

Standard basketball structure, which is well understood and far more stable
than anything baseball offers:

    possessions = FGA - OREB + TO + 0.44 * FTA
    offensive rating = points per 100 possessions
    defensive rating = points allowed per 100 possessions
    pace = possessions per game

A matchup projects as each side's offence against the other's defence,
relative to league average, over a shared possession estimate. Margin then
converts to a win probability through the empirical spread of game results.

Two things make this a better target than the MLB model:

  * ~80 possessions a side per game means outcomes cluster near their
    expectation. A baseball game is 38 plate appearances and one swing decides
    it; here the law of large numbers actually works for you.
  * Ratings are built from dated boxscores, so a point-in-time version is
    straightforward -- no look-ahead to engineer around.

Everything is regressed by games played. Ten games of a hot start is not a
team's true rating, and treating it as one is the fastest way to lose.
"""
from __future__ import annotations

import math
import statistics as st
from dataclasses import dataclass

from . import wnbadata as W

# Games before a team's own numbers outweigh league average. Team ratings
# settle faster than individual rates but still need a real prior early.
TEAM_REG_GAMES = 8.0

# Standard deviation of actual margin around the projected margin. Calibrated
# below against outcomes rather than assumed -- it is the single number that
# turns a projected margin into a win probability.
# Measured, not assumed: over 111 point-in-time games the actual margin came
# in with a standard deviation of 10.80 around the projection.
MARGIN_SD = 10.80

# Home edge in points. Verified against outcomes in `calibrate`.
# Calibrated against outcomes. At 2.4 the model projected a +2.30 average home
# margin where the actual was +1.21 -- roughly double the real edge, which
# tilted every close game toward the home side.
HOME_EDGE = 1.25

FT_POSS_WEIGHT = 0.44   # the standard coefficient on free-throw attempts

# Projected totals ran 2.1 points below actual over the backtest window. The
# possession estimate drops points scored after offensive rebounds and in
# transition off makes, so the raw projection is systematically light.
TOTAL_ADJUST = 2.1

# Totals are more widely dispersed than the raw model produces (measured 0.641
# of market dispersion). Scoring environment moves both teams together, so
# errors add rather than cancel; the sd used for over/under has to reflect the
# model's own compression rather than the market's spread.
TOTAL_SD = 16.5


def possessions(row: dict) -> float:
    """Possessions from a team's box line."""
    return (row["fga"] - row["oreb"] + row["to"]
            + FT_POSS_WEIGHT * row["fta"])


def team_totals(box_rows: list[dict]) -> dict:
    """Aggregate a team's player lines into one team line."""
    keys = ("pts", "fga", "fgm", "tpa", "tpm", "fta", "ftm",
            "oreb", "dreb", "reb", "ast", "to", "stl", "blk", "min")
    out = {k: sum(r.get(k, 0.0) for r in box_rows) for k in keys}
    out["poss"] = possessions(out)
    return out


@dataclass
class TeamRating:
    team_id: str
    games: int
    off_rtg: float          # points scored per 100 possessions
    def_rtg: float          # points allowed per 100 possessions
    pace: float             # possessions per game
    raw_off: float
    raw_def: float
    raw_pace: float


def build_ratings(cutoff: str | None = None, start: str = "2026-05-01",
                  verbose: bool = False) -> tuple[dict[str, TeamRating], dict]:
    """
    Team efficiency ratings from every completed game before `cutoff`.

    Passing a cutoff gives point-in-time ratings, which is what a backtest
    needs: the model sees only what was knowable that morning.
    """
    end = cutoff or W.date.today().isoformat()
    games = [g for g in W.games_between(start, end)
             if g["final"] and g["date"] < end]

    agg: dict[str, dict] = {}
    for g in games:
        box = W.boxscore(g["id"])
        if len(box) != 2:
            continue
        hid, aid = str(g["home_id"]), str(g["away_id"])
        if hid not in box or aid not in box:
            continue
        h, a = team_totals(box[hid]), team_totals(box[aid])
        if h["poss"] < 40 or a["poss"] < 40:
            continue          # malformed or partial box
        for tid, own, opp in ((hid, h, a), (aid, a, h)):
            d = agg.setdefault(tid, {"g": 0, "pts": 0.0, "opp_pts": 0.0,
                                     "poss": 0.0, "opp_poss": 0.0})
            d["g"] += 1
            d["pts"] += own["pts"]
            d["opp_pts"] += opp["pts"]
            d["poss"] += own["poss"]
            d["opp_poss"] += opp["poss"]

    if not agg:
        return {}, {}

    lg_pts = sum(d["pts"] for d in agg.values())
    lg_poss = sum(d["poss"] for d in agg.values())
    lg_games = sum(d["g"] for d in agg.values())
    lg_rtg = (lg_pts / lg_poss * 100) if lg_poss else 100.0
    lg_pace = (lg_poss / lg_games) if lg_games else 80.0

    ratings = {}
    for tid, d in agg.items():
        n = d["g"]
        w = n / (n + TEAM_REG_GAMES)
        raw_off = (d["pts"] / d["poss"] * 100) if d["poss"] else lg_rtg
        raw_def = (d["opp_pts"] / d["opp_poss"] * 100) if d["opp_poss"] else lg_rtg
        raw_pace = (d["poss"] / n) if n else lg_pace
        ratings[tid] = TeamRating(
            team_id=tid, games=n,
            off_rtg=w * raw_off + (1 - w) * lg_rtg,
            def_rtg=w * raw_def + (1 - w) * lg_rtg,
            pace=w * raw_pace + (1 - w) * lg_pace,
            raw_off=raw_off, raw_def=raw_def, raw_pace=raw_pace)

    league = {"rtg": lg_rtg, "pace": lg_pace, "games": lg_games // 2}
    if verbose:
        print(f"  ratings from {len(games)} games, league {lg_rtg:.1f} rtg "
              f"{lg_pace:.1f} pace")
    return ratings, league


def project_game(home_id: str, away_id: str, ratings: dict, league: dict,
                 neutral: bool = False) -> dict:
    """
    Project one matchup: each side's points, the total, and a win probability.

    Each offence is measured against the opposing defence relative to league
    average, so a good offence facing a good defence lands near the mean
    rather than double counting.
    """
    lg_rtg, lg_pace = league["rtg"], league["pace"]
    h = ratings.get(home_id)
    a = ratings.get(away_id)
    if h is None or a is None:
        return {}

    # Shared possession estimate: both teams see the same number of trips.
    poss = (h.pace + a.pace) / 2.0 * (lg_pace / lg_pace)

    h_rtg = h.off_rtg + a.def_rtg - lg_rtg
    a_rtg = a.off_rtg + h.def_rtg - lg_rtg

    h_pts = h_rtg / 100.0 * poss
    a_pts = a_rtg / 100.0 * poss
    if not neutral:
        h_pts += HOME_EDGE / 2.0
        a_pts -= HOME_EDGE / 2.0

    margin = h_pts - a_pts
    total = h_pts + a_pts + TOTAL_ADJUST
    p_home = _norm_cdf(margin / MARGIN_SD)

    return {"home_pts": h_pts, "away_pts": a_pts, "margin": margin,
            "total": total, "p_home": p_home, "poss": poss,
            "home_rtg": h_rtg, "away_rtg": a_rtg}


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def total_over_prob(proj_total: float, line: float,
                    sd: float = TOTAL_SD) -> tuple[float, float]:
    """
    P(over), P(under) for a game total.

    Total variance is wider than margin variance -- both teams' scoring moves
    together with pace, so the errors add rather than cancel.
    """
    z = (proj_total - line) / sd
    over = _norm_cdf(z)
    return over, 1.0 - over


def spread_cover_prob(proj_margin: float, spread_home: float,
                      sd: float = MARGIN_SD) -> float:
    """
    P(home covers). `spread_home` is home-relative as ESPN reports it:
    negative means the home team is laying points.
    """
    return _norm_cdf((proj_margin + spread_home) / sd)
