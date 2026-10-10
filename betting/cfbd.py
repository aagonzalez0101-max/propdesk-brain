"""
collegefootballdata.com client -- the layer ESPN cannot provide.

ESPN gives box scores, which is enough for in-season efficiency ratings. What
it cannot give is the TALENT PRIOR, and in college football that prior is the
whole early-season game. A team with three games played has almost no usable
efficiency sample, so the model regresses toward league average -- treating a
blue-chip roster and a Sun Belt roster identically. That is obviously wrong,
and it is wrong in exactly the weeks we are betting now.

CFBD supplies four things worth having, roughly in order of value here:

  recruiting/teams     247-style composite team talent score
  player/portal        transfer portal moves, in and out
  player/returning     % of last year's production coming back
  stats/season/advanced success rate, explosiveness, havoc -- better than the
                       yards-per-play proxy cfbmodel currently uses

Auth is a bearer token. Free tier is generous but not unlimited, so every call
is cached to disk; a finished season never changes.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "cfbd"
load_dotenv(ROOT / ".env")
API_KEY = os.getenv("CFBD_API_KEY", "")
BASE = "https://api.collegefootballdata.com"


def _get(path: str, params: dict, ttl: int = 2592000) -> list | dict:
    import hashlib
    blob = path + "|" + json.dumps(params, sort_keys=True)
    name = f"{path.strip('/').replace('/','_')}_{hashlib.sha1(blob.encode()).hexdigest()[:10]}"
    p = CACHE / f"{name}.json"
    if p.exists() and (time.time() - p.stat().st_mtime) < ttl:
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            pass
    if not API_KEY:
        print("  [cfbd] no CFBD_API_KEY in .env")
        return []
    try:
        r = requests.get(f"{BASE}{path}", params=params, timeout=40,
                         headers={"Authorization": f"Bearer {API_KEY}",
                                  "Accept": "application/json"})
        r.raise_for_status()
        d = r.json()
    except (requests.RequestException, ValueError) as e:
        print(f"  [cfbd] {path} failed: {e}")
        return []
    CACHE.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d))
    return d


def talent(year: int) -> dict:
    """Composite team talent score, keyed by school name."""
    return {r["team"]: float(r["talent"]) for r in _get("/talent", {"year": year})
            if r.get("talent") is not None}


def recruiting(year: int) -> dict:
    """Recruiting class rating and rank, keyed by school."""
    return {r["team"]: {"rank": r.get("rank"), "points": r.get("points")}
            for r in _get("/recruiting/teams", {"year": year})}


def returning_production(year: int) -> dict:
    """% of last season's production back, keyed by school."""
    return {r["team"]: r for r in _get("/player/returning", {"year": year})}


def portal(year: int) -> list[dict]:
    """Transfer portal entries for a season."""
    return _get("/player/portal", {"year": year})


def advanced_season(year: int, team: str | None = None) -> list[dict]:
    """Success rate, explosiveness, havoc -- season aggregates."""
    p = {"year": year, "excludeGarbageTime": "true"}
    if team:
        p["team"] = team
    return _get("/stats/season/advanced", p)


def sp_ratings(year: int) -> dict:
    """SP+ ratings -- a public benchmark to sanity-check ours against."""
    return {r["team"]: r for r in _get("/ratings/sp", {"year": year})}
