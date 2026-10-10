"""
NFL games with closing lines, from the nflverse games file.

This is the cleanest data source in the project. One free CSV carries results,
closing moneylines, spreads, totals, AND context (rest days, roof, surface,
temperature, wind, starting QBs, coaches, referee) for every game since 1999.

Compare what the other sports needed: MLB took a 90-minute point-in-time
backfill against a retail consensus; soccer needed a separate odds source
because ESPN keeps none; CFB died precisely because no free closing line
existed. Here it is one download.

Sample sizes that matter:
    7548 games total, 1999-2026
    5407 with a closing moneyline   (MLB's validated ML model used 1591)
    7388 with a closing spread

The QB columns are the reason this is worth more than the raw count suggests.
Quarterback is the largest single source of week-to-week team strength change
in the sport, and a model that cannot see a QB change will misprice exactly the
games where the market has moved most.
"""
from __future__ import annotations

import csv
import io
import json
import urllib.request
from pathlib import Path

GAMES_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
CACHE = Path(__file__).resolve().parent.parent / "data" / "nfl"


def _num(v):
    v = (v or "").strip()
    if v in ("", "NA", "None"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def fetch(refresh=False) -> list[dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / "games.csv"
    if refresh or not path.exists() or path.stat().st_size < 1000:
        req = urllib.request.Request(GAMES_URL, headers={"User-Agent": "Mozilla/5.0"})
        txt = urllib.request.urlopen(req, timeout=90).read().decode("utf-8", "replace")
        path.write_text(txt, encoding="utf-8")
    else:
        txt = path.read_text(encoding="utf-8", errors="replace")
    return list(csv.DictReader(io.StringIO(txt)))


def games(min_season=2006, played_only=True, need_ml=True) -> list[dict]:
    """Normalised rows. 2006+ by default: earlier seasons have sparse odds."""
    out = []
    for r in fetch():
        season = _num(r.get("season"))
        if season is None or season < min_season:
            continue
        hs, as_ = _num(r.get("home_score")), _num(r.get("away_score"))
        if played_only and (hs is None or as_ is None):
            continue
        hml, aml = _num(r.get("home_moneyline")), _num(r.get("away_moneyline"))
        if need_ml and (hml is None or aml is None):
            continue
        out.append({
            "game_id": r.get("game_id"), "season": int(season),
            "week": int(_num(r.get("week")) or 0),
            "game_type": r.get("game_type"), "date": r.get("gameday"),
            "away": r.get("away_team"), "home": r.get("home_team"),
            "as": as_, "hs": hs,
            "margin": (hs - as_) if (hs is not None and as_ is not None) else None,
            "total": (hs + as_) if (hs is not None and as_ is not None) else None,
            "hml": hml, "aml": aml,
            "spread": _num(r.get("spread_line")),      # home-negative convention
            "total_line": _num(r.get("total_line")),
            "over_odds": _num(r.get("over_odds")), "under_odds": _num(r.get("under_odds")),
            "home_rest": _num(r.get("home_rest")), "away_rest": _num(r.get("away_rest")),
            "div_game": _num(r.get("div_game")),
            "roof": r.get("roof"), "surface": r.get("surface"),
            "temp": _num(r.get("temp")), "wind": _num(r.get("wind")),
            "home_qb": r.get("home_qb_name"), "away_qb": r.get("away_qb_name"),
            "home_coach": r.get("home_coach"), "away_coach": r.get("away_coach"),
        })
    return out


def upcoming(season=2026) -> list[dict]:
    """Scheduled games with lines but no score yet -- next week's board."""
    out = []
    for r in fetch():
        if _num(r.get("season")) != season:
            continue
        if _num(r.get("home_score")) is not None:
            continue
        out.append({
            "game_id": r.get("game_id"), "season": season,
            "week": int(_num(r.get("week")) or 0),
            "date": r.get("gameday"), "time": r.get("gametime"),
            "away": r.get("away_team"), "home": r.get("home_team"),
            "hml": _num(r.get("home_moneyline")), "aml": _num(r.get("away_moneyline")),
            "spread": _num(r.get("spread_line")), "total_line": _num(r.get("total_line")),
            "home_qb": r.get("home_qb_name"), "away_qb": r.get("away_qb_name"),
            "roof": r.get("roof"), "home_rest": _num(r.get("home_rest")),
            "away_rest": _num(r.get("away_rest")), "div_game": _num(r.get("div_game")),
        })
    return out


def implied(american):
    return (-american / (-american + 100.0)) if american < 0 else (100.0 / (american + 100.0))


def devig_ml(hml, aml):
    ih, ia = implied(hml), implied(aml)
    tot = ih + ia
    return ih / tot, ia / tot


if __name__ == "__main__":
    import collections
    g = games()
    print("%d games with closing moneylines, %d-%d"
          % (len(g), min(x["season"] for x in g), max(x["season"] for x in g)))
    hw = sum(1 for x in g if x["margin"] > 0)
    push = sum(1 for x in g if x["margin"] == 0)
    print("home win rate: %.1f%%   ties: %d" % (hw / len(g) * 100, push))
    print("mean margin  : %+.2f   mean total: %.1f"
          % (sum(x["margin"] for x in g) / len(g),
             sum(x["total"] for x in g) / len(g)))
    hold = []
    for x in g:
        ih, ia = implied(x["hml"]), implied(x["aml"])
        hold.append(ih + ia - 1)
    print("mean bookmaker hold: %.2f%%" % (sum(hold) / len(hold) * 100))
    by = collections.Counter(x["season"] for x in g)
    print("\nby season:", " ".join("%d:%d" % (k, v) for k, v in sorted(by.items())))
    json.dump(g, open("nfl_rows.json", "w"))
    print("\nsaved -> nfl_rows.json")
