"""College football player game logs and usage-floor prop screening.

Built the same way as nflprops.py, for the same reason: a counting prop is a
RATE times an OPPORTUNITY, and the opportunity is what actually decides it. A
back who touches the ball fifteen times clears a modest yardage line almost
always; the risk is not a bad game, it is never getting the carries.

That matters more in college than the NFL because of blowouts. Notre Dame at
-20.6 pulls its starters in the fourth quarter, so a starter's volume prop is
capped by the scoreline rather than by his ability. Any floor measured here is
therefore CONDITIONAL on reaching the usage threshold, and the screen reports
how often a player actually reaches it -- that is the forecastable part.

Data is ESPN's game summary, already cached from the team-ratings collection,
so this costs no new requests for 2025.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict

from betting import cfbdata as C


def _f(x, d=0.0):
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return d


def _split(x):
    """'7/20' -> (7.0, 20.0)"""
    try:
        a, b = str(x).split("/")
        return float(a), float(b)
    except Exception:
        return 0.0, 0.0


def player_rows(game_id: str) -> list[dict]:
    """One row per player per game, with the volume + production fields."""
    s = C._get(C.SUM, {"event": game_id}, "sum_%s" % game_id, 60 * 60 * 24 * 30)
    out = {}
    for blk in (s.get("boxscore", {}).get("players") or []):
        team = (blk.get("team") or {}).get("displayName", "")
        tid = str((blk.get("team") or {}).get("id", ""))
        for grp in blk.get("statistics", []):
            name = grp.get("name")
            keys = grp.get("keys") or []
            for ath in grp.get("athletes", []):
                a = ath.get("athlete") or {}
                pid = str(a.get("id", ""))
                if not pid:
                    continue
                st = dict(zip(keys, ath.get("stats") or []))
                r = out.setdefault(pid, {
                    "game": game_id, "player_id": pid,
                    "player": a.get("displayName", ""), "team": team, "team_id": tid,
                    "att": 0.0, "cmp": 0.0, "pass_yds": 0.0, "pass_td": 0.0, "int": 0.0,
                    "carries": 0.0, "rush_yds": 0.0, "rush_td": 0.0, "long_rush": 0.0,
                    "rec": 0.0, "rec_yds": 0.0, "rec_td": 0.0, "long_rec": 0.0,
                })
                if name == "passing":
                    c, at = _split(st.get("completions/passingAttempts"))
                    r["cmp"], r["att"] = c, at
                    r["pass_yds"] = _f(st.get("passingYards"))
                    r["pass_td"] = _f(st.get("passingTouchdowns"))
                    r["int"] = _f(st.get("interceptions"))
                elif name == "rushing":
                    r["carries"] = _f(st.get("rushingAttempts"))
                    r["rush_yds"] = _f(st.get("rushingYards"))
                    r["rush_td"] = _f(st.get("rushingTouchdowns"))
                    r["long_rush"] = _f(st.get("longRushing"))
                elif name == "receiving":
                    r["rec"] = _f(st.get("receptions"))
                    r["rec_yds"] = _f(st.get("receivingYards"))
                    r["rec_td"] = _f(st.get("receivingTouchdowns"))
                    r["long_rec"] = _f(st.get("longReception"))
    return list(out.values())


def collect(games: list[dict], out_path="cfb_players.json") -> list[dict]:
    rows = []
    for i, g in enumerate(games):
        try:
            for r in player_rows(str(g["id"])):
                r["date"] = g.get("date")
                r["week"] = g.get("week")
                rows.append(r)
        except Exception:
            continue
        if (i + 1) % 100 == 0:
            print("  %d/%d games, %d player-games" % (i + 1, len(games), len(rows)), flush=True)
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f)
    os.replace(tmp, out_path)
    return rows


# (usage stat, floor, prop stat, threshold, label)
FLOORS = [
    ("carries", 12, "rush_yds", 29.5, "over 29.5 rush yds"),
    ("carries", 12, "rush_yds", 49.5, "over 49.5 rush yds"),
    ("carries", 15, "rush_yds", 59.5, "over 59.5 rush yds"),
    ("rec", 3, "rec_yds", 29.5, "over 29.5 rec yds"),
    ("rec", 4, "rec_yds", 39.5, "over 39.5 rec yds"),
    ("att", 20, "pass_yds", 174.5, "over 174.5 pass yds"),
    ("att", 25, "pass_yds", 224.5, "over 224.5 pass yds"),
    ("att", 20, "cmp", 12.5, "over 12.5 completions"),
]


def base_rates(rows: list[dict]) -> list[dict]:
    """League-wide P(clears the line | reached the usage floor)."""
    out = []
    for ustat, floor, pstat, thr, label in FLOORS:
        elig = [r for r in rows if r[ustat] >= floor]
        if not elig:
            continue
        hit = sum(1 for r in elig if r[pstat] > thr)
        out.append({"usage": "%s>=%d" % (ustat, floor), "prop": label,
                    "n": len(elig), "rate": hit / len(elig)})
    return out
