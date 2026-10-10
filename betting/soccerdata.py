"""
Historical soccer results with closing odds, from football-data.co.uk.

ESPN carries soccer results for free but keeps no odds at all -- 0 of 15 on a
spot check, the same wall that killed the CFB build. Without a closing price
there is nothing to measure a model against, so ESPN is useless here.

football-data.co.uk publishes one CSV per league-season with full-time scores
AND several books' closing prices, including Pinnacle (PSH/PSD/PSA). Pinnacle
is the sharp benchmark: low margin, high limits, and the number every serious
soccer study is scored against. That makes these files better ground truth than
anything used for the MLB work, where the best available was a retail consensus.

Columns that matter:
    Date, HomeTeam, AwayTeam
    FTHG / FTAG   full-time goals
    FTR           H / D / A
    PSH/PSD/PSA   Pinnacle closing (preferred)
    B365H/D/A     Bet365 closing (fallback for older seasons)
    AvgH/D/A      market average
"""
from __future__ import annotations

import csv
import io
import json
import os
import urllib.request
from pathlib import Path

BASE = "https://www.football-data.co.uk/mmz4281"
CACHE = Path(__file__).resolve().parent.parent / "data" / "soccer"

# code -> readable name. These are the leagues with deep, reliable odds columns.
LEAGUES = {
    "E0": "Premier League", "E1": "Championship",
    "SP1": "La Liga", "SP2": "La Liga 2",
    "D1": "Bundesliga", "D2": "Bundesliga 2",
    "I1": "Serie A", "I2": "Serie B",
    "F1": "Ligue 1", "F2": "Ligue 2",
    "N1": "Eredivisie", "P1": "Primeira Liga",
    "B1": "Belgian Pro League", "T1": "Super Lig", "G1": "Greek Super League",
    "SC0": "Scottish Premiership",
}


def _fetch(season: str, code: str) -> str:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / ("%s_%s.csv" % (season, code))
    if path.exists() and path.stat().st_size > 200:
        return path.read_text(encoding="utf-8", errors="replace")
    url = "%s/%s/%s.csv" % (BASE, season, code)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    txt = urllib.request.urlopen(req, timeout=45).read().decode("utf-8", "replace")
    path.write_text(txt, encoding="utf-8")
    return txt


def _f(row, key):
    v = (row.get(key) or "").strip()
    try:
        return float(v)
    except ValueError:
        return None


def matches(season: str, code: str) -> list[dict]:
    """One league-season. Rows without a score or a closing price are dropped."""
    try:
        txt = _fetch(season, code)
    except Exception:
        return []
    out = []
    for r in csv.DictReader(io.StringIO(txt)):
        hg, ag = _f(r, "FTHG"), _f(r, "FTAG")
        if hg is None or ag is None:
            continue
        # Pinnacle first, then Bet365, then the market average.
        for pre in ("PS", "B365", "Avg"):
            h, d, a = _f(r, pre + "H"), _f(r, pre + "D"), _f(r, pre + "A")
            if h and d and a:
                book = pre
                break
        else:
            continue
        out.append({
            "season": season, "league": code, "league_name": LEAGUES.get(code, code),
            "date": (r.get("Date") or "").strip(),
            "home": (r.get("HomeTeam") or "").strip(),
            "away": (r.get("AwayTeam") or "").strip(),
            "hg": hg, "ag": ag,
            "result": (r.get("FTR") or "").strip(),
            "odds_book": book, "oh": h, "od": d, "oa": a,
        })
    return out


def load(seasons=("2223", "2324", "2425", "2526", "2627"),
         codes=None, verbose=True) -> list[dict]:
    codes = codes or list(LEAGUES)
    rows = []
    for s in seasons:
        got = 0
        for c in codes:
            m = matches(s, c)
            rows += m
            got += len(m)
        if verbose:
            print("  %s: %5d matches" % (s, got), flush=True)
    return rows


def devig(oh, od, oa):
    """Three-way de-vig, multiplicative. Returns (p_home, p_draw, p_away)."""
    ih, id_, ia = 1.0 / oh, 1.0 / od, 1.0 / oa
    tot = ih + id_ + ia
    return ih / tot, id_ / tot, ia / tot


if __name__ == "__main__":
    rows = load()
    print("\ntotal: %d matches" % len(rows))
    if rows:
        import collections
        by = collections.Counter(r["league_name"] for r in rows)
        for k, v in by.most_common():
            print("  %-24s %5d" % (k, v))
        books = collections.Counter(r["odds_book"] for r in rows)
        print("\nclosing price source:", dict(books))
        res = collections.Counter(r["result"] for r in rows)
        n = sum(res.values())
        print("outcomes: H %.1f%%  D %.1f%%  A %.1f%%"
              % (res["H"] / n * 100, res["D"] / n * 100, res["A"] / n * 100))
        with open("soccer_rows.json", "w") as f:
            json.dump(rows, f)
        print("saved -> soccer_rows.json")
