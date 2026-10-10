"""
Dota 2 data layer -- OpenDota. Free, no key, a real JSON API.

This is by far the best esports data source available. Valorant needed HTML
scraping off vlr.gg; CS2 has no free per-player source at all (HLTV 403s,
bo3.gg exposes no player endpoint). OpenDota returns 147 fields per player per
match, including the ones that matter here: kills, deaths, assists, duration,
gold and xp per minute, hero, and lane role.

The modelling shape is different from Valorant in one important way. Valorant
kills scale with ROUNDS -- a discrete, tightly-distributed count (21.1 per map,
sd 3.7). Dota kills scale with GAME DURATION, which is continuous and far more
variable (a stomp ends in 25 minutes, a hard-fought game runs past 50). So the
volume term is noisier here, and the model has to lean harder on per-minute
rates than on predicting length.

Role also matters far more. Underdog's own lines show it: a position-1 carry is
priced at 18.5 kills where a position-5 hard support sits at 5.5. That is a 3x
spread inside one match -- much wider than Valorant's duelist-to-controller gap.
Getting a player's position right is most of the projection.

Rate limit: 60 calls/minute unauthenticated. Everything is cached; a finished
match never changes.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "dota"
BASE = "https://api.opendota.com/api"
HEADERS = {"User-Agent": "Mozilla/5.0"}
MIN_INTERVAL = 2.5                    # 60/min ceiling; 1.1 still tripped 429s
_last = 0.0


def _get(path: str, params: dict | None = None, ttl: int = 2592000):
    global _last
    import hashlib
    blob = path + json.dumps(params or {}, sort_keys=True)
    name = f"{path.strip('/').replace('/','_')}_{hashlib.sha1(blob.encode()).hexdigest()[:10]}"
    p = CACHE / f"{name}.json"
    if p.exists() and (time.time() - p.stat().st_mtime) < ttl:
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            pass
    wait = MIN_INTERVAL - (time.time() - _last)
    if wait > 0:
        time.sleep(wait)
    try:
        r = requests.get(f"{BASE}{path}", params=params or {}, headers=HEADERS, timeout=40)
        _last = time.time()
        r.raise_for_status()
        d = r.json()
    except (requests.RequestException, ValueError) as e:
        print(f"  [dota] {path} failed: {e}")
        return []
    CACHE.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d))
    return d


def pro_matches(less_than: int | None = None) -> list[dict]:
    """Recent professional matches, 100 at a time. Paginate with less_than."""
    p = {"less_than_match_id": less_than} if less_than else {}
    return _get("/proMatches", p, ttl=3600)


def match(match_id: int) -> dict:
    """Full match detail including every player's line."""
    return _get(f"/matches/{match_id}")


def pro_players() -> list[dict]:
    """Registered pro players -- maps account_id to name and team."""
    return _get("/proPlayers", ttl=86400)


def player_lines(m: dict) -> list[dict]:
    """
    Flatten one match into per-player rows with the fields a kills model needs.

    `duration` is seconds; kills-per-minute is the rate that actually
    transfers between games, since a 25-minute stomp and a 55-minute grind
    produce very different raw kill counts from identical play.
    """
    if not isinstance(m, dict):          # error responses come back as []
        return []
    dur = (m.get("duration") or 0) / 60.0
    if dur <= 0:
        return []
    out = []
    for p in (m.get("players") or []):
        k = p.get("kills")
        if k is None:
            continue
        out.append({
            "match_id": m.get("match_id"), "start": m.get("start_time"),
            "league": (m.get("league") or {}).get("name") or m.get("league_name"),
            "duration_min": dur, "radiant": bool(p.get("isRadiant")),
            "won": bool(p.get("win")),
            "account_id": p.get("account_id"), "name": p.get("name") or p.get("personaname"),
            "hero_id": p.get("hero_id"), "lane_role": p.get("lane_role"),
            "kills": k, "deaths": p.get("deaths"), "assists": p.get("assists"),
            "kpm": k / dur,
            "gpm": p.get("gold_per_min"), "xpm": p.get("xp_per_min"),
            "last_hits": p.get("last_hits"), "hero_damage": p.get("hero_damage"),
            "net_worth": p.get("net_worth"),
        })
    return out


def player_matches(account_id: int, limit: int = 40) -> list[dict]:
    """
    One player's recent matches directly.

    Far more efficient than walking /proMatches: that feed is dominated by
    tier-2 and tier-3 events, so scanning 220 of them found zero games for the
    players we actually wanted. Six targeted calls beat two hundred blind ones.
    """
    return _get(f"/players/{account_id}/matches",
                {"limit": limit, "significant": 0}, ttl=3600)


# Lobby types that count as competitive. 0/6/7 are public, solo-queue and
# ranked -- pro players farm kills there and it badly inflates a kills average
# (QBFY: 4.66 K/game in practice, 6.19 in ranked; WoE: 7.58 vs 12.25).
#
# The `significant=1` query parameter is SILENTLY IGNORED on
# /players/{id}/matches -- passing it returns byte-identical output to
# significant=0, which is how this contamination survived a check.
COMPETITIVE_LOBBIES = {1, 2, 5}


def competitive_games(account_id: int, limit: int = 60) -> list[dict]:
    """A player's recent games, public and ranked queues removed."""
    ms = player_matches(account_id, limit)
    if not isinstance(ms, list):
        return []
    return [m for m in ms if isinstance(m, dict)
            and m.get("lobby_type") in COMPETITIVE_LOBBIES
            and m.get("kills") is not None
            and (m.get("duration") or 0) > 900]
