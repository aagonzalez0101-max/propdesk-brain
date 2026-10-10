"""
League of Legends data layer -- Leaguepedia (Fandom) cargo tables. Free, no key.

Leaguepedia stores every pro game in queryable SQL-ish "cargo" tables. The one
that matters is ScoreboardPlayers: one row per player per game with kills,
deaths, assists, CS, champion, role and a timestamp.

Two things to know:

  * It rate-limits aggressively and returns {"error": {"code": "ratelimited"}}
    rather than an HTTP error, so a naive caller sees an empty result and
    concludes the player has no games. Every call is spaced and retried.
  * `limit` caps at 500 per request. Longer pulls need offset paging.

Why LoL is worth building despite Valorant already working: Underdog carried
NINE LoL matches with unders available on a single day, versus two Valorant.
It is the deepest esports board they offer that we can actually model, because
unlike CS2 the per-player data is public.

Modelling shape: kills scale with GAME DURATION like Dota, not with rounds like
Valorant. But LoL role assignment is far cleaner than Dota's -- the five
positions are fixed and reported, so the role prior is reliable.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests


class RateLimited(RuntimeError):
    """Leaguepedia refused the query because we asked too fast.

    This exists because the API answers a throttle with HTTP 200 and an error
    BODY. The old code swallowed that and returned [], making a rate limit
    indistinguishable from "no rows match" -- a date-paginated collector reads
    that as end-of-data and silently stops early. Callers must be able to tell
    the two apart, so exhausting the retries now raises instead of returning [].
    """


ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "lol"
BASE = "https://lol.fandom.com/api.php"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; research/1.0)"}
MIN_INTERVAL = 2.5
MAX_RETRIES = 4
_last = 0.0


def _cargo(tables: str, fields: str, where: str = "", order: str = "",
           limit: int = 500, offset: int = 0, ttl: int = 21600):
    global _last
    import hashlib
    p = {"action": "cargoquery", "format": "json", "tables": tables,
         "fields": fields, "limit": limit, "offset": offset}
    if where:
        p["where"] = where
    if order:
        p["order_by"] = order
    last_err = "unknown"
    key = hashlib.sha1(json.dumps(p, sort_keys=True).encode()).hexdigest()[:14]
    fp = CACHE / f"{key}.json"
    if fp.exists() and (time.time() - fp.stat().st_mtime) < ttl:
        try:
            return json.loads(fp.read_text())
        except json.JSONDecodeError:
            pass
    for attempt in range(MAX_RETRIES):
        wait = MIN_INTERVAL - (time.time() - _last)
        if wait > 0:
            time.sleep(wait)
        try:
            r = requests.get(BASE, params=p, headers=HEADERS, timeout=40)
            _last = time.time()
            d = r.json()
        except (requests.RequestException, ValueError):
            _last = time.time()
            time.sleep(4 * (attempt + 1))
            continue
        # rate limiting arrives as a 200 with an error body, not an HTTP error
        if "error" in d:
            last_err = str(d["error"].get("code", "error"))
            time.sleep(15 * (attempt + 1))
            continue
        rows = [x["title"] for x in d.get("cargoquery", [])]
        CACHE.mkdir(parents=True, exist_ok=True)
        fp.write_text(json.dumps(rows))
        return rows
    raise RateLimited("gave up after %d attempts (%s)" % (MAX_RETRIES, last_err))


FIELDS = ("Link=player,Team=team,Champion=champ,Role=role,Kills=k,Deaths=d,"
          "Assists=a,CS=cs,Gold=gold,DateTime_UTC=dt,GameId=gid")


def player_games(player: str, limit: int = 60) -> list[dict]:
    """Recent games for one player, newest first."""
    safe = player.replace('"', '')
    return _cargo("ScoreboardPlayers", FIELDS,
                  where=f'ScoreboardPlayers.Link="{safe}"',
                  order="ScoreboardPlayers.DateTime_UTC DESC", limit=limit)


def team_games(team: str, limit: int = 200) -> list[dict]:
    safe = team.replace('"', '')
    return _cargo("ScoreboardPlayers", FIELDS,
                  where=f'ScoreboardPlayers.Team="{safe}"',
                  order="ScoreboardPlayers.DateTime_UTC DESC", limit=limit)


def search_player(fragment: str, limit: int = 25) -> list[dict]:
    """Find the canonical Link for a display name."""
    safe = fragment.replace('"', '')
    return _cargo("ScoreboardPlayers", "Link=player,Team=team,DateTime_UTC=dt",
                  where=f'ScoreboardPlayers.Link LIKE "%{safe}%"',
                  order="ScoreboardPlayers.DateTime_UTC DESC", limit=limit)
