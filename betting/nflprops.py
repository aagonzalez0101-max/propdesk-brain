"""
Find the highest-probability NFL player props -- for a contest, not for value.

This exists because the $1M challenge is a different game from betting. There
is no price to beat: you split your bankroll across both sides of one prop a
week and keep whatever lands on the right side. Final wealth is the product of
twenty rounds, so it is governed entirely by RAW probability, not by edge.

    keep per round = p^2 + (1-p)^2

    70% legs -> $19 left from $1,000,000
    90% legs -> $18,891
    95% legs -> $135,822

A 90% prop at -900 is worthless to a bettor and is the single best pick here.
So this module ranks by hit rate and ignores price entirely.

The measured floors (2023-25, 54,476 player-games):

    RB with 12+ carries  -> over 29.5 rush yards   95.6%
    WR/TE with 6+ targets-> over 2.5 receptions    94.5%
    QB with 20+ attempts -> over 14.5 completions  89.3%
    QB with 20+ attempts -> over 149.5 pass yards  87.8%

Every one is CONDITIONAL on the usage floor. The failure mode is not a bad
game, it is the player never reaching the floor -- injury, an early blowout, a
snap-count surprise. So the screen ranks players by how reliably they have hit
the usage floor itself, which is the only part that is actually forecastable.
"""
from __future__ import annotations

import csv
import io
import statistics as st
import urllib.request
from collections import defaultdict

BASE = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/"

# (position, usage stat, floor, prop stat, threshold, label, measured hit rate)
FLOORS = [
    ("RB", "carries", 12, "rushing_yards", 29.5, "over 29.5 rush yds", 0.956),
    ("RB", "carries", 12, "rushing_yards", 39.5, "over 39.5 rush yds", 0.868),
    ("WR", "targets", 6, "receptions", 2.5, "over 2.5 receptions", 0.945),
    ("TE", "targets", 6, "receptions", 2.5, "over 2.5 receptions", 0.945),
    ("WR", "targets", 6, "receiving_yards", 29.5, "over 29.5 rec yds", 0.870),
    ("QB", "attempts", 20, "completions", 14.5, "over 14.5 completions", 0.893),
    ("QB", "attempts", 20, "passing_yards", 149.5, "over 149.5 pass yds", 0.878),
]


def load(season):
    url = BASE + "stats_player_week_%d.csv" % season
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    txt = urllib.request.urlopen(req, timeout=120).read().decode("utf-8", "replace")
    return [r for r in csv.DictReader(io.StringIO(txt)) if r.get("season_type") == "REG"]


def _f(x, k):
    try:
        return float(x.get(k) or 0)
    except (TypeError, ValueError):
        return 0.0


def screen(seasons=(2025,), min_games=8):
    """Rank players by P(hits the usage floor) x P(clears the line | floor).

    The second term is the league-wide measured rate; the first is what varies
    between players and is the whole reason one pick is safer than another.
    """
    rows = []
    for s in seasons:
        try:
            rows += load(s)
        except Exception:
            pass
    by = defaultdict(list)
    for r in rows:
        by[(r.get("player_display_name"), r.get("position"))].append(r)

    out = []
    for (name, pos), games in by.items():
        if not name or len(games) < min_games:
            continue
        for p, ustat, floor, pstat, thr, label, base_rate in FLOORS:
            if pos != p:
                continue
            hit_floor = [g for g in games if _f(g, ustat) >= floor]
            if len(hit_floor) / len(games) < 0.55:
                continue
            # This player's own rate above the line, given he hit the floor --
            # SHRUNK toward the league base rate. A raw 17-for-17 is not 100%;
            # with that sample the honest estimate is nearer 90%. The contest
            # payoff is convex in p, so treating 90% as 100% is a real error,
            # not a rounding one. Beta prior worth ~10 games at the league rate.
            k = 10.0
            wins = sum(1 for g in hit_floor if _f(g, pstat) > thr)
            own = (wins + k * base_rate) / (len(hit_floor) + k) if hit_floor else 0.0
            # same treatment for the usage floor, prior centred on 0.75
            floor_hits = len(hit_floor)
            floor_rate = (floor_hits + k * 0.75) / (len(games) + k)
            combined = floor_rate * own
            out.append({
                "player": name, "pos": pos, "prop": label,
                "games": len(games), "floor_rate": floor_rate,
                "rate_given_floor": own, "league_base": base_rate,
                "combined": combined,
                "usage": "%s >= %d" % (ustat, floor),
                "mean_usage": st.mean([_f(g, ustat) for g in games]),
            })
    out.sort(key=lambda r: -r["combined"])
    return out


if __name__ == "__main__":
    import sys
    rows = screen()
    print("Highest-probability NFL props by combined rate (2025 usage)\n")
    print("  %-24s%-4s%-24s%9s%9s%9s"
          % ("player", "pos", "prop", "floor%", "given%", "COMBINED"))
    seen = set()
    for r in rows:
        if r["player"] in seen:
            continue
        seen.add(r["player"])
        print("  %-24s%-4s%-24s%8.0f%%%8.0f%%%8.0f%%"
              % (r["player"][:24], r["pos"], r["prop"],
                 r["floor_rate"] * 100, r["rate_given_floor"] * 100,
                 r["combined"] * 100))
        if len(seen) >= 25:
            break
    print("\n  floor%%  = how often he reaches the usage floor at all")
    print("  given%% = how often he clears the line WHEN he reaches it")
    print("  COMBINED = the number that actually matters for the contest")
