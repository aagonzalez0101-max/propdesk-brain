"""LoL esports data from Riot's own API -- schedule, series structure, kills.

Why this exists: Leaguepedia rate-limits hard, lags a day behind on ingestion,
and answers a throttle with an empty list. Riot's official endpoints have none
of those problems, and they carry two things Leaguepedia does not:

  * game `state` == "unneeded" when a series ends before the full Bo-N, which
    is exactly the void condition for an Underdog "Maps 1+2+3" prop;
  * live telemetry, so a finished game is queryable within minutes.

The catch is that livestats only covers major leagues (LCK/LPL/LEC/LTA/LCP).
Tier-2 and tier-3 return empty, so Leaguepedia stays the fallback for those.

The public x-api-key below is the one Riot's own web client ships; it is not a
credential and grants nothing beyond the public read endpoints.
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import os
import re
import time
import urllib.request

KEY = "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z"
ESPORTS = "https://esports-api.lolesports.com/persisted/gw/"
FEED = "https://feed.lolestports.com/livestats/v1/".replace("lolestports", "lolesports")
CACHE = "data/cache/lolriot"
MAJORS = ("LCK", "LPL", "LEC", "LTA North", "LTA South", "LCP", "LCK CL")


def _raw(url, ttl=3600, name=None):
    os.makedirs(CACHE, exist_ok=True)
    key = name or re.sub(r"[^A-Za-z0-9_.-]", "_", url)[-120:]
    p = os.path.join(CACHE, key + ".json")
    if ttl and os.path.exists(p) and time.time() - os.path.getmtime(p) < ttl:
        return open(p, encoding="utf-8").read()
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0", "Accept": "*/*",
        "Accept-Encoding": "gzip", "x-api-key": KEY})
    r = urllib.request.urlopen(req, timeout=45)
    b = r.read()
    if r.headers.get("Content-Encoding") == "gzip":
        b = gzip.decompress(b)
    t = b.decode("utf-8", "replace")
    open(p, "w", encoding="utf-8").write(t)
    return t


def schedule(league_id=None, page=None):
    u = ESPORTS + "getSchedule?hl=en-US"
    if league_id:
        u += "&leagueId=%s" % league_id
    if page:
        u += "&pageToken=%s" % page
    return json.loads(_raw(u, ttl=300))["data"]["schedule"]


def leagues():
    d = json.loads(_raw(ESPORTS + "getLeagues?hl=en-US", ttl=86400))
    return d["data"]["leagues"]


def event_games(match_id):
    """[(number, game_id, state)] -- state 'unneeded' means the map was never played."""
    d = json.loads(_raw(ESPORTS + "getEventDetails?hl=en-US&id=%s" % match_id, ttl=3600))
    gs = d["data"]["event"]["match"]["games"]
    return [(g["number"], g["id"], g["state"]) for g in gs]


def game_kills(game_id, start_iso, max_minutes=420, step=5):
    """Final per-player kills for one game, as {side: [(name, kills)]}.

    The window endpoint serves a ~10 minute slice starting at `startingTime`,
    and there is no "give me the final state" call. Two traps follow:

      * game N of a series starts hours after the MATCH start, so a search
        window sized for game 1 returns nothing for games 3-5;
      * a slice that lands mid-game returns real but PARTIAL kills, which look
        like a valid final line (game 2 of one LCK series read 3 total kills).

    Kills only ever increase within a game, so the fix is to sweep a wide range
    and keep the frame with the highest total rather than the last one that
    happened to answer. A frame flagged gameState "finished" ends the sweep.
    """
    base = dt.datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    best, best_total = None, -1
    for minutes in range(5, max_minutes + 1, step):
        ts = (base + dt.timedelta(minutes=minutes)).replace(
            second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            d = json.loads(_raw("%swindow/%s?startingTime=%s" % (FEED, game_id, ts),
                                ttl=86400 * 7, name="w_%s_%d" % (game_id, minutes)))
        except Exception:
            continue
        frames = d.get("frames") or []
        if not frames:
            continue
        f = frames[-1]
        meta = d.get("gameMetadata", {})
        out, total = {}, 0
        for side, mkey in (("blueTeam", "blueTeamMetadata"), ("redTeam", "redTeamMetadata")):
            names = [p.get("summonerName", "") for p in
                     meta.get(mkey, {}).get("participantMetadata", [])]
            ks = [p["kills"] for p in f[side]["participants"]]
            out[side] = list(zip(names, ks))
            total += sum(ks)
        if total > best_total:
            best, best_total = out, total
        if f.get("gameState") == "finished" and total >= best_total:
            break
    return best


def player_name(raw):
    """Strip the team tag Riot prefixes to summoner names ('T1 Faker' -> 'Faker')."""
    return raw.split(" ", 1)[1] if " " in raw else raw
