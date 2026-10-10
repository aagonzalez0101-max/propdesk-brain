"""
College football data layer -- ESPN. Free, no key.

Why CFB is the right football market to build first, despite NFL being the
priority: VOLUME. Week 1 of 2026 carried 99 games against the NFL's 16. A
forward test that needs 300 games takes three weeks here and a full season
there. Since no free historical closing lines exist for either league, a
forward log is the ONLY way to ever prove a market -- so the league that
accumulates one fastest is the league to build in.

Two things to know about this feed:

  * A full Chrome User-Agent gets 403. Plain "Mozilla/5.0" passes. This cost
    an hour of false negatives before it was spotted.
  * ESPN keeps NO odds for CFB. Not on live games, not on finished ones --
    checked 18 completed 2025 games, zero had a pickcenter entry. This is the
    opposite of MLB, where closing lines are retained forever and made the
    whole backtest possible. CFB validation therefore has to be forward-only.

`groups=80` restricts to FBS. Without it the scoreboard returns every division
and the ratings get polluted by FCS blowouts.
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "cfb"
HEADERS = {"User-Agent": "Mozilla/5.0"}          # NOT a full Chrome UA -- 403s

SB = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
SUM = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary"
TEAMS = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams"
FBS = 80


def _get(url: str, params: dict, name: str, ttl: int) -> dict:
    p = CACHE / f"{name}.json"
    if p.exists() and (time.time() - p.stat().st_mtime) < ttl:
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            pass
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=30)
        r.raise_for_status()
        d = r.json()
    except (requests.RequestException, ValueError) as e:
        print(f"  [cfb] {url} failed: {e}")
        return {}
    CACHE.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d))
    return d


def _f(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _eff(s: str) -> tuple[float, float]:
    """'7-15' third-down efficiency -> (made, attempts)."""
    try:
        a, b = str(s).split("-")
        return float(a), float(b)
    except (ValueError, AttributeError):
        return 0.0, 0.0


def week(year: int, wk: int, seasontype: int = 2) -> list[dict]:
    """One week of FBS games. seasontype 2 = regular, 3 = postseason."""
    d = _get(SB, {"dates": year, "seasontype": seasontype, "week": wk,
                  "groups": FBS, "limit": 400},
             f"wk_{year}_{seasontype}_{wk}", ttl=2592000)
    return [game_context(e) for e in (d.get("events") or [])]


def games_on(day: str) -> list[dict]:
    key = day.replace("-", "")
    ttl = 900 if day >= date.today().isoformat() else 2592000
    d = _get(SB, {"dates": key, "groups": FBS, "limit": 400}, f"day_{key}", ttl)
    return [game_context(e) for e in (d.get("events") or [])]


def game_context(ev: dict) -> dict:
    comp = ev["competitions"][0]
    home = away = None
    for t in comp["competitors"]:
        rec = {"id": t["team"]["id"], "name": t["team"]["displayName"],
               "abbr": t["team"].get("abbreviation", ""),
               "score": int(t.get("score", 0) or 0),
               "rank": (t.get("curatedRank") or {}).get("current")}
        if t.get("homeAway") == "home":
            home = rec
        else:
            away = rec
    st = comp.get("status", {}).get("type", {})
    return {"id": ev["id"], "date": ev["date"][:10], "start": ev["date"],
            "state": st.get("state", ""), "final": st.get("state") == "post",
            "neutral": comp.get("neutralSite", False),
            "home_id": home["id"], "home_team": home["name"],
            "home_score": home["score"], "home_rank": home["rank"],
            "away_id": away["id"], "away_team": away["name"],
            "away_score": away["score"], "away_rank": away["rank"]}


def team_stats(event_id: str) -> dict:
    """
    Team box score for one game, keyed by team id.

    Returns yards, plays, turnovers and the down-efficiency splits -- enough to
    build yards-per-play and success-rate proxies without play-by-play.
    """
    s = _get(SUM, {"event": event_id}, f"sum_{event_id}", ttl=2592000)
    out = {}
    for t in (s.get("boxscore", {}).get("teams", []) or []):
        tid = str(t.get("team", {}).get("id", ""))
        d = {x.get("name"): x.get("displayValue") for x in (t.get("statistics") or [])}
        td, ta = _eff(d.get("thirdDownEff"))
        fd, fa = _eff(d.get("fourthDownEff"))
        cmp_, att = _eff(d.get("completionAttempts"))
        rush_att = _f(d.get("rushingAttempts"))
        plays = att + rush_att                       # sacks land in rushing here
        out[tid] = {
            "first_downs": _f(d.get("firstDowns")),
            "total_yards": _f(d.get("totalYards")),
            "pass_yards": _f(d.get("netPassingYards")),
            "rush_yards": _f(d.get("rushingYards")),
            "rush_att": rush_att, "pass_att": att, "completions": cmp_,
            "plays": plays,
            "ypp": (_f(d.get("totalYards")) / plays) if plays else 0.0,
            "third_made": td, "third_att": ta,
            "fourth_made": fd, "fourth_att": fa,
            "turnovers": _f(d.get("turnovers")),
            "penalty_yards": _eff(d.get("totalPenaltiesYards"))[1],
        }
    return out


def teams() -> list[dict]:
    d = _get(TEAMS, {"limit": 500, "groups": FBS}, "teams", ttl=2592000)
    out = []
    try:
        for g in d["sports"][0]["leagues"][0]["teams"]:
            t = g["team"]
            out.append({"id": t["id"], "name": t["displayName"],
                        "abbr": t.get("abbreviation", "")})
    except (KeyError, IndexError, TypeError):
        pass
    return out
