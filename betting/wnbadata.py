"""
WNBA data layer -- ESPN. Free, no key.

Why WNBA is a better modelling target than MLB or NFL preseason:

  * Usage is PREDICTABLE. A starter plays 30-34 minutes almost every night.
    In baseball the equivalent -- innings pitched -- swings from 3 to 7 and
    decides the whole prop; in NFL preseason a first overall pick threw seven
    passes while a backup threw thirty-two. Minutes are the stable version of
    that variable, which is what makes player props modellable here.

  * More events per game. Roughly 80 possessions a side against 38 plate
    appearances, so outcomes concentrate around their expectation instead of
    being dominated by noise.

  * It is fully BACKTESTABLE. ESPN keeps closing odds (spread, total, both
    moneylines) on completed games alongside full boxscores, so the model can
    be scored against real prices -- the exact thing that was impossible for
    MLB player props, where no historical prop lines exist for free.

Everything is cached to disk; a finished game never changes.
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "wnba"
HEADERS = {"User-Agent": "Mozilla/5.0"}

SB = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"
SUM = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/summary"
GAMELOG = ("https://site.web.api.espn.com/apis/common/v3/sports/basketball/"
           "wnba/athletes/{pid}/gamelog")
TEAMS = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/teams"

SEASON = date.today().year


def _cache_get(name: str, ttl: int):
    p = CACHE / f"{name}.json"
    if p.exists() and (time.time() - p.stat().st_mtime) < ttl:
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return None
    return None


def _cache_put(name: str, data) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / f"{name}.json").write_text(json.dumps(data))


def _get(url: str, params: dict | None = None, ttl: int = 3600,
         name: str | None = None) -> dict:
    if name:
        hit = _cache_get(name, ttl)
        if hit is not None:
            return hit
    try:
        r = requests.get(url, params=params or {}, timeout=30, headers=HEADERS)
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError) as e:
        print(f"  [wnba] {url} failed: {e}")
        return {}
    if name:
        _cache_put(name, data)
    return data


def _f(v, default: float = 0.0) -> float:
    """ESPN returns stats as strings, sometimes '12-19' or '--'."""
    if v in (None, "", "--", "-"):
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _made_att(v: str) -> tuple[float, float]:
    """'9-18' -> (9, 18)."""
    try:
        m, a = str(v).split("-")
        return float(m), float(a)
    except (ValueError, AttributeError):
        return 0.0, 0.0


# ------------------------------------------------------------------ schedule

def scoreboard(day: str) -> list[dict]:
    """All games on a date, finished or not."""
    key = day.replace("-", "")
    # Finished days never change; today's board does.
    ttl = 900 if day >= date.today().isoformat() else 2592000
    data = _get(SB, {"dates": key, "limit": 100}, ttl=ttl, name=f"sb_{key}")
    return data.get("events", []) or []


def game_context(ev: dict) -> dict:
    """Flatten one scoreboard event."""
    comp = ev["competitions"][0]
    home = away = None
    for t in comp["competitors"]:
        rec = {"id": t["team"]["id"], "name": t["team"]["displayName"],
               "abbr": t["team"].get("abbreviation", ""),
               "score": int(t.get("score", 0) or 0)}
        if t.get("homeAway") == "home":
            home = rec
        else:
            away = rec
    state = comp.get("status", {}).get("type", {}).get("state", "")
    return {
        "id": ev["id"], "date": ev["date"][:10], "start": ev["date"],
        "state": state, "final": state == "post",
        "home_id": home["id"], "home_team": home["name"], "home_score": home["score"],
        "away_id": away["id"], "away_team": away["name"], "away_score": away["score"],
        "neutral": comp.get("neutralSite", False),
    }


def games_between(start: str, end: str) -> list[dict]:
    """Every game in a date range, as flattened contexts."""
    out = []
    d = datetime.strptime(start, "%Y-%m-%d").date()
    stop = datetime.strptime(end, "%Y-%m-%d").date()
    while d <= stop:
        for ev in scoreboard(d.isoformat()):
            try:
                out.append(game_context(ev))
            except (KeyError, IndexError, TypeError):
                continue
        d += timedelta(days=1)
    return out


# --------------------------------------------------------------- boxscores

def summary(event_id: str, ttl: int = 2592000) -> dict:
    return _get(SUM, {"event": event_id}, ttl=ttl, name=f"sum_{event_id}")


def closing_odds(event_id: str) -> dict | None:
    """
    Closing spread, total and moneylines from ESPN's pickcenter.

    This is what makes the whole market backtestable -- a real, two-sided
    price that existed before the game, kept on the finished game forever.
    """
    s = summary(event_id)
    pc = s.get("pickcenter") or []
    if not pc:
        return None
    book = next((p for p in pc if "draftkings" in
                 str(p.get("provider", {}).get("name", "")).lower()), pc[0])
    h = (book.get("homeTeamOdds") or {}).get("moneyLine")
    a = (book.get("awayTeamOdds") or {}).get("moneyLine")
    return {
        "book": book.get("provider", {}).get("name", "?"),
        "spread": book.get("spread"),
        "total": book.get("overUnder"),
        "ml_home": float(h) if h is not None else None,
        "ml_away": float(a) if a is not None else None,
        "details": book.get("details"),
    }


BOX_KEYS = ["MIN", "PTS", "FG", "3PT", "FT", "REB", "AST", "TO", "STL",
            "BLK", "OREB", "DREB", "PF", "+/-"]


def boxscore(event_id: str) -> dict:
    """
    Player lines for one game, keyed by team id.

    Returns {team_id: [{player, id, min, pts, reb, ast, ...}, ...]}
    """
    s = summary(event_id)
    groups = s.get("boxscore", {}).get("players", []) or []
    out: dict[str, list[dict]] = {}
    for grp in groups:
        tid = str(grp.get("team", {}).get("id", ""))
        rows = []
        for cat in grp.get("statistics", []):
            labels = cat.get("labels") or BOX_KEYS
            for a in cat.get("athletes", []):
                stats = a.get("stats") or []
                if not stats:
                    continue
                d = dict(zip(labels, stats))
                fgm, fga = _made_att(d.get("FG", "0-0"))
                tpm, tpa = _made_att(d.get("3PT", "0-0"))
                ftm, fta = _made_att(d.get("FT", "0-0"))
                rows.append({
                    "id": a["athlete"]["id"],
                    "name": a["athlete"]["displayName"],
                    "starter": a.get("starter", False),
                    "min": _f(d.get("MIN")), "pts": _f(d.get("PTS")),
                    "reb": _f(d.get("REB")), "ast": _f(d.get("AST")),
                    "stl": _f(d.get("STL")), "blk": _f(d.get("BLK")),
                    "to": _f(d.get("TO")), "pf": _f(d.get("PF")),
                    "fgm": fgm, "fga": fga, "tpm": tpm, "tpa": tpa,
                    "ftm": ftm, "fta": fta,
                    "oreb": _f(d.get("OREB")), "dreb": _f(d.get("DREB")),
                })
        if rows:
            out[tid] = rows
    return out


def player_gamelog(player_id: str, ttl: int = 21600,
                   regular_season_only: bool = True) -> list[dict]:
    """
    Dated game log for one player, regular season by default.

    ESPN splits this across two places and the obvious one is a decoy: the
    top-level `events` map holds only metadata (date, opponent, score) with
    `stats: None`. The actual stat lines live under
    `seasonTypes -> categories -> events`, keyed by eventId, grouped by month.
    Joining the two gives dated lines.

    Preseason is filtered out by default -- those are the games where a
    starter plays six minutes, and mixing them into a rate estimate poisons it.
    """
    data = _get(GAMELOG.format(pid=player_id), ttl=ttl, name=f"glog_{player_id}")
    labels = data.get("labels") or []
    meta = data.get("events") or {}

    out = []
    for st in data.get("seasonTypes") or []:
        if regular_season_only and "regular" not in str(st.get("displayName", "")).lower():
            continue
        for cat in st.get("categories") or []:
            for ev in cat.get("events") or []:
                stats = ev.get("stats") or []
                if not stats:
                    continue
                d = dict(zip(labels, stats))
                eid = str(ev.get("eventId", ""))
                fgm, fga = _made_att(d.get("FG", "0-0"))
                tpm, tpa = _made_att(d.get("3PT", "0-0"))
                ftm, fta = _made_att(d.get("FT", "0-0"))
                out.append({
                    "event_id": eid,
                    "date": str((meta.get(eid) or {}).get("gameDate", ""))[:10],
                    "min": _f(d.get("MIN")), "pts": _f(d.get("PTS")),
                    "reb": _f(d.get("REB")), "ast": _f(d.get("AST")),
                    "stl": _f(d.get("STL")), "blk": _f(d.get("BLK")),
                    "to": _f(d.get("TO")), "pf": _f(d.get("PF")),
                    "fgm": fgm, "fga": fga, "tpm": tpm, "tpa": tpa,
                    "ftm": ftm, "fta": fta,
                })
    out.sort(key=lambda r: r["date"])
    return out


def teams() -> list[dict]:
    data = _get(TEAMS, {"limit": 50}, ttl=2592000, name="teams")
    out = []
    try:
        for grp in data["sports"][0]["leagues"][0]["teams"]:
            t = grp["team"]
            out.append({"id": t["id"], "name": t["displayName"],
                        "abbr": t.get("abbreviation", "")})
    except (KeyError, IndexError, TypeError):
        pass
    return out
