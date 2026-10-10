"""
stats.wnba.com client -- the advanced-stats source, free.

Two things make this endpoint work where a naive request fails:

  1. It demands browser-ish headers, specifically `x-nba-stats-origin` and
     `x-nba-stats-token`. Without them the connection is reset before any
     response.
  2. It rate-limits hard. A single call succeeds; three in a row get the
     connection dropped. So every request goes through one session, spaced by
     a minimum interval, with exponential backoff on failure.

What this unlocks that ESPN box scores cannot give:
  * shot distribution BY ZONE, for offence and for defence allowed
  * four factors, advanced team and player ratings
  * true usage, assist and rebound percentages

That is the difference between "Team A scores a lot" and "Team A takes 41% of
its shots from three and Team B allows the highest three-point rate in the
league" -- the zone-versus-zone read that actually finds mispriced sides.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "wnbastats"
BASE_URL = "https://stats.wnba.com/stats/"

HEADERS = {
    "Host": "stats.wnba.com",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.wnba.com/",
    "Origin": "https://www.wnba.com",
    "Connection": "keep-alive",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

# Minimum seconds between calls. Below about 2s the host starts resetting
# connections, and a reset costs far more time than the wait.
MIN_INTERVAL = 2.5
MAX_RETRIES = 4

_session: requests.Session | None = None
_last_call = 0.0

# Parameters every leaguedash endpoint expects. Omitting one returns an error
# rather than a default, so they are all sent explicitly.
COMMON = {
    "LeagueID": "10",          # 10 = WNBA
    "Season": "2026",
    "SeasonType": "Regular Season",
    "PerMode": "PerGame",
    "MeasureType": "Base",
    "Outcome": "", "Location": "", "Month": "0", "SeasonSegment": "",
    "DateFrom": "", "DateTo": "", "OpponentTeamID": "0", "VsConference": "",
    "VsDivision": "", "GameSegment": "", "Period": "0", "LastNGames": "0",
    "TeamID": "0", "Conference": "", "Division": "", "GameScope": "",
    "PlayerExperience": "", "PlayerPosition": "", "StarterBench": "",
    "PlusMinus": "N", "PaceAdjust": "N", "Rank": "N", "TwoWay": "0",
    "ShotClockRange": "",
}
PLAYER_EXTRA = {"DraftYear": "", "DraftPick": "", "College": "",
                "Country": "", "Height": "", "Weight": "", "Age": "0"}


def _sess() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(HEADERS)
    return _session


def _cache_key(endpoint: str, params: dict) -> str:
    blob = endpoint + "|" + json.dumps(
        {k: v for k, v in sorted(params.items()) if v != ""}, sort_keys=True)
    import hashlib
    return f"{endpoint}_{hashlib.sha1(blob.encode()).hexdigest()[:12]}"


def get(endpoint: str, params: dict, ttl: int = 21600) -> dict:
    """One rate-limited, cached, retrying call."""
    global _last_call
    key = _cache_key(endpoint, params)
    path = CACHE / f"{key}.json"
    if path.exists() and (time.time() - path.stat().st_mtime) < ttl:
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            pass

    for attempt in range(MAX_RETRIES):
        wait = MIN_INTERVAL - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
        try:
            r = _sess().get(BASE_URL + endpoint, params=params, timeout=30)
            _last_call = time.time()
            if r.status_code == 200:
                data = r.json()
                CACHE.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data))
                return data
            if r.status_code in (429, 503):
                time.sleep(2 ** attempt * 2)
                continue
            return {}
        except (requests.RequestException, ValueError):
            _last_call = time.time()
            time.sleep(2 ** attempt * 2)      # reset: back off and retry
    return {}


def _rows(data: dict, idx: int = 0) -> list[dict]:
    """Flatten a resultSets block into dicts."""
    rs = data.get("resultSets")
    if not rs:
        return []
    if isinstance(rs, dict):
        # shot-location endpoints nest headers two deep
        hdr = rs.get("headers") or []
        cols: list[str] = []
        prefix = ""
        for h in hdr:
            if isinstance(h, dict):
                names = h.get("columnNames") or []
                if h.get("columnsToSkip") is not None or len(names) < 5:
                    # the first header row labels the zone groups
                    cols_group = names
                    continue
                cols += names
        rows = rs.get("rowSet") or []
        return [dict(zip(cols, r)) if cols else {} for r in rows]
    block = rs[idx]
    return [dict(zip(block["headers"], r)) for r in block["rowSet"]]


def team_advanced(season: str = "2026") -> list[dict]:
    """Off/def rating, pace, AST%, OREB%, DREB% per team."""
    return _rows(get("leaguedashteamstats",
                     {**COMMON, "Season": season, "MeasureType": "Advanced"}))


def team_four_factors(season: str = "2026") -> list[dict]:
    """eFG%, FTA rate, TOV%, OREB% -- the four factors, per team."""
    return _rows(get("leaguedashteamstats",
                     {**COMMON, "Season": season, "MeasureType": "Four Factors"}))


def team_opponent(season: str = "2026") -> list[dict]:
    """What each team ALLOWS -- the defensive profile."""
    return _rows(get("leaguedashteamstats",
                     {**COMMON, "Season": season, "MeasureType": "Opponent"}))


def player_advanced(season: str = "2026") -> list[dict]:
    """Usage rate, true shooting, assist and rebound percentages."""
    return _rows(get("leaguedashplayerstats",
                     {**COMMON, **PLAYER_EXTRA, "Season": season,
                      "MeasureType": "Advanced"}))


def team_shot_zones(season: str = "2026", opponent: bool = False) -> dict:
    """
    Shot distribution and accuracy BY ZONE -- restricted area, paint,
    mid-range, corner three, above the break.

    `opponent=True` returns what a team ALLOWS by zone, which is the other
    half of the zone-versus-zone read.
    """
    return get("leaguedashteamshotlocations",
               {**COMMON, "Season": season, "DistanceRange": "By Zone",
                "MeasureType": "Opponent" if opponent else "Base"})
