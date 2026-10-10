"""
MLB data layer -- statsapi.mlb.com. Free, unlimited, no key.

Everything here is cached to disk because the model calls the same endpoints
repeatedly and statsapi is slow enough that it matters.
"""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import requests

BASE = "https://statsapi.mlb.com/api/v1"
ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "mlb"
SEASON = date.today().year

# Park run factors: >1.00 inflates scoring. Multi-year values, roughly
# centred on 1.00. Coors is the extreme outlier that matters most.
PARK_FACTORS = {
    "Coors Field": 1.15, "Great American Ball Park": 1.06, "Fenway Park": 1.05,
    "Chase Field": 1.04, "Globe Life Field": 1.03, "Citizens Bank Park": 1.03,
    "Nationals Park": 1.02, "Camden Yards": 1.02, "Wrigley Field": 1.01,
    "Truist Park": 1.01, "Rogers Centre": 1.01, "Target Field": 1.00,
    "Angel Stadium": 1.00, "Busch Stadium": 0.99, "Dodger Stadium": 0.99,
    "Minute Maid Park": 0.99, "Daikin Park": 0.99, "Yankee Stadium": 1.00,
    "Progressive Field": 0.98, "PNC Park": 0.98, "Comerica Park": 0.98,
    "Kauffman Stadium": 0.98, "American Family Field": 1.00,
    "loanDepot park": 0.96, "Petco Park": 0.96, "Oracle Park": 0.95,
    "T-Mobile Park": 0.95, "Guaranteed Rate Field": 1.01,
    "Rate Field": 1.01, "Oakland Coliseum": 0.94, "Sutter Health Park": 1.05,
    "George M. Steinbrenner Field": 1.04, "Citi Field": 0.97,
}
DEFAULT_PARK = 1.00


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


def _get(endpoint: str, params: dict | None = None, ttl: int = 3600,
         cache_name: str | None = None) -> dict:
    params = params or {}
    if cache_name:
        hit = _cache_get(cache_name, ttl)
        if hit is not None:
            return hit
    try:
        r = requests.get(f"{BASE}{endpoint}", params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError) as e:
        print(f"  [mlb] {endpoint} failed: {e}")
        return {}
    if cache_name:
        _cache_put(cache_name, data)
    return data


def _f(stat: dict, key: str, default: float = 0.0) -> float:
    """statsapi returns numbers as strings like '.318' and '14.0' -- coerce safely."""
    v = stat.get(key, default)
    if v in (None, "", "-", ".---"):
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _ip_to_float(ip) -> float:
    """Innings pitched: '14.1' means 14 and 1/3 innings, not 14.1."""
    if ip in (None, ""):
        return 0.0
    try:
        s = str(ip)
        whole, _, frac = s.partition(".")
        outs = {"0": 0.0, "1": 1 / 3, "2": 2 / 3, "": 0.0}.get(frac, 0.0)
        return float(whole) + outs
    except (TypeError, ValueError):
        return 0.0


# ------------------------------------------------------------------ schedule

def schedule(game_date: str | None = None) -> list[dict]:
    """Today's games with probable pitchers and venue."""
    d = game_date or date.today().isoformat()
    data = _get("/schedule",
                {"sportId": 1, "date": d,
                 "hydrate": "probablePitcher,team,venue,linescore"},
                ttl=900, cache_name=f"sched_{d}")
    dates = data.get("dates", [])
    return dates[0].get("games", []) if dates else []


def game_context(g: dict) -> dict:
    """Flatten one schedule entry into what the model needs."""
    home, away = g["teams"]["home"], g["teams"]["away"]
    venue = g.get("venue", {}).get("name", "")
    return {
        "game_pk": g.get("gamePk"),
        "state": g.get("status", {}).get("abstractGameState", ""),
        "start": g.get("gameDate", ""),
        "venue": venue,
        "park_factor": PARK_FACTORS.get(venue, DEFAULT_PARK),
        "home_team": home["team"]["name"],
        "away_team": away["team"]["name"],
        "home_id": home["team"]["id"],
        "away_id": away["team"]["id"],
        "home_sp": home.get("probablePitcher"),
        "away_sp": away.get("probablePitcher"),
    }


# ------------------------------------------------------------------- pitcher

def pitcher_stats(person_id: int, season: int = SEASON) -> dict | None:
    """Season pitching line plus handedness. Returns None if no data."""
    data = _get(f"/people/{person_id}",
                {"hydrate": f"stats(group=pitching,type=season,season={season})"},
                ttl=21600, cache_name=f"p2_{person_id}_{season}")
    people = data.get("people") or []
    if not people:
        return None
    p = people[0]
    hand = p.get("pitchHand", {}).get("code", "R")
    splits = (p.get("stats") or [{}])[0].get("splits") or []
    if not splits:
        return {"id": person_id, "name": p.get("fullName", "?"), "hand": hand, "ip": 0.0}
    s = splits[0].get("stat", {})
    ip = _ip_to_float(s.get("inningsPitched"))
    return {
        "id": person_id,
        "name": p.get("fullName", "?"),
        "hand": hand,
        "ip": ip,
        "gs": _f(s, "gamesStarted"),
        "k": _f(s, "strikeOuts"),
        "bb": _f(s, "baseOnBalls"),
        "hbp": _f(s, "hitByPitch"),
        "hr": _f(s, "homeRuns"),
        "er": _f(s, "earnedRuns"),
        "bf": _f(s, "battersFaced"),
        "era": _f(s, "era"),
        "whip": _f(s, "whip"),
        "h": _f(s, "hits"),
        "2b": _f(s, "doubles"),
        "3b": _f(s, "triples"),
    }


def pitcher_recent_starts(person_id: int, n: int = 6, season: int = SEASON) -> list[dict]:
    """Last n starts -- used to see how deep he actually goes and recent form."""
    data = _get(f"/people/{person_id}",
                {"hydrate": f"stats(group=pitching,type=gameLog,season={season})"},
                ttl=21600, cache_name=f"plog_{person_id}_{season}")
    people = data.get("people") or []
    if not people or not people[0].get("stats"):
        return []
    splits = people[0]["stats"][0].get("splits", [])
    starts = [s for s in splits if s.get("stat", {}).get("gamesStarted")]
    starts = starts[-n:]
    return [{
        "date": s.get("date"),
        "ip": _ip_to_float(s["stat"].get("inningsPitched")),
        "k": _f(s["stat"], "strikeOuts"),
        "bb": _f(s["stat"], "baseOnBalls"),
        "er": _f(s["stat"], "earnedRuns"),
        "hr": _f(s["stat"], "homeRuns"),
        "bf": _f(s["stat"], "battersFaced"),
    } for s in starts]


# ---------------------------------------------------------------------- team

def team_hitting(team_id: int, season: int = SEASON) -> dict:
    data = _get(f"/teams/{team_id}/stats",
                {"stats": "season", "group": "hitting", "season": season},
                ttl=21600, cache_name=f"th_{team_id}_{season}")
    try:
        s = data["stats"][0]["splits"][0]["stat"]
    except (KeyError, IndexError):
        return {}
    return {
        "pa": _f(s, "plateAppearances"), "ops": _f(s, "ops"),
        "obp": _f(s, "obp"), "slg": _f(s, "slg"), "avg": _f(s, "avg"),
        "runs": _f(s, "runs"), "hr": _f(s, "homeRuns"),
        "k": _f(s, "strikeOuts"), "bb": _f(s, "baseOnBalls"),
        "games": _f(s, "gamesPlayed"),
    }


def team_hitting_vs_hand(team_id: int, hand: str, season: int = SEASON) -> dict:
    """
    Team batting split against LHP ('vl') or RHP ('vr').

    Platoon splits are one of the largest real effects in baseball and one of
    the most commonly ignored -- a lineup can swing 60+ points of OPS.
    """
    code = "vl" if hand.upper().startswith("L") else "vr"
    data = _get(f"/teams/{team_id}/stats",
                {"stats": "statSplits", "group": "hitting",
                 "sitCodes": code, "season": season},
                ttl=21600, cache_name=f"ths_{team_id}_{code}_{season}")
    try:
        for sp in data["stats"][0]["splits"]:
            if sp["split"]["code"] == code:
                s = sp["stat"]
                return {"pa": _f(s, "plateAppearances"), "ops": _f(s, "ops"),
                        "obp": _f(s, "obp"), "slg": _f(s, "slg")}
    except (KeyError, IndexError):
        pass
    return {}


# -------------------------------------------------------------------- league

def league_averages(season: int = SEASON) -> dict:
    """
    League-wide hitting and pitching baselines.

    These anchor every regression in the model, so they're computed from the
    actual season rather than hardcoded from memory.
    """
    cached = _cache_get(f"lg_{season}", 43200)
    if cached:
        return cached

    hit = _get("/teams/stats",
               {"stats": "season", "group": "hitting", "season": season, "sportIds": 1},
               ttl=43200, cache_name=f"lgh_{season}")
    pit = _get("/teams/stats",
               {"stats": "season", "group": "pitching", "season": season, "sportIds": 1},
               ttl=43200, cache_name=f"lgp_{season}")

    tot = {"runs": 0.0, "pa": 0.0, "games": 0.0, "ops_w": 0.0,
           "ip": 0.0, "k": 0.0, "bb": 0.0, "hr": 0.0, "er": 0.0, "bf": 0.0}
    try:
        for sp in hit["stats"][0]["splits"]:
            s = sp["stat"]
            pa = _f(s, "plateAppearances")
            tot["runs"] += _f(s, "runs")
            tot["pa"] += pa
            tot["games"] += _f(s, "gamesPlayed")
            tot["ops_w"] += _f(s, "ops") * pa
    except (KeyError, IndexError):
        pass
    try:
        for sp in pit["stats"][0]["splits"]:
            s = sp["stat"]
            tot["ip"] += _ip_to_float(s.get("inningsPitched"))
            tot["k"] += _f(s, "strikeOuts")
            tot["bb"] += _f(s, "baseOnBalls")
            tot["hr"] += _f(s, "homeRuns")
            tot["er"] += _f(s, "earnedRuns")
            tot["bf"] += _f(s, "battersFaced")
    except (KeyError, IndexError):
        pass

    games = tot["games"] or 1.0
    ip = tot["ip"] or 1.0
    out = {
        "season": season,
        "runs_per_team_game": tot["runs"] / games,
        "league_ops": (tot["ops_w"] / tot["pa"]) if tot["pa"] else 0.710,
        "era": (tot["er"] / ip) * 9.0,
        "k9": (tot["k"] / ip) * 9.0,
        "bb9": (tot["bb"] / ip) * 9.0,
        "hr9": (tot["hr"] / ip) * 9.0,
        "k_rate": (tot["k"] / tot["bf"]) if tot["bf"] else 0.22,
        "bf_per_ip": (tot["bf"] / ip) if ip else 4.3,
    }
    # FIP constant makes league FIP equal league ERA.
    out["fip_constant"] = out["era"] - (
        (13 * tot["hr"] + 3 * tot["bb"] - 2 * tot["k"]) / ip
    )
    _cache_put(f"lg_{season}", out)
    return out


# ------------------------------------------------- team pitching / bullpen

def team_pitching_split(team_id: int, role: str = "rp", season: int = SEASON) -> dict:
    """
    Team pitching by role: 'rp' = bullpen, 'sp' = rotation.

    Bullpen quality is a large, persistent, and frequently mispriced effect --
    especially on F5 markets, where a good bullpen is IRRELEVANT. Knowing which
    teams are carried by their pen tells you when the F5 line and the full-game
    line should disagree.
    """
    data = _get(f"/teams/{team_id}/stats",
                {"stats": "statSplits", "group": "pitching",
                 "sitCodes": role, "season": season},
                ttl=21600, cache_name=f"tps_{team_id}_{role}_{season}")
    try:
        s = data["stats"][0]["splits"][0]["stat"]
    except (KeyError, IndexError):
        return {}
    ip = _ip_to_float(s.get("inningsPitched"))
    return {"ip": ip, "era": _f(s, "era"), "k": _f(s, "strikeOuts"),
            "bb": _f(s, "baseOnBalls"), "hr": _f(s, "homeRuns"),
            "er": _f(s, "earnedRuns")}


def team_hitting_home_away(team_id: int, season: int = SEASON) -> dict:
    """
    Home vs road hitting splits.

    Road OPS is naturally park-neutral (a team plays road games across ~15
    different parks), so it is the cleanest read on true offensive talent.
    Raw season OPS is contaminated by half a season in the team's own park --
    which is why Colorado always looks better than it is.
    """
    data = _get(f"/teams/{team_id}/stats",
                {"stats": "statSplits", "group": "hitting",
                 "sitCodes": "h,a", "season": season},
                ttl=21600, cache_name=f"thha_{team_id}_{season}")
    out = {}
    try:
        for sp in data["stats"][0]["splits"]:
            code = sp["split"]["code"]
            s = sp["stat"]
            out[code] = {"ops": _f(s, "ops"), "pa": _f(s, "plateAppearances")}
    except (KeyError, IndexError):
        pass
    return out


def pitcher_career(person_id: int) -> dict:
    """
    Career pitching line.

    Essential for separating a rookie from a veteran. A callup with 60 career
    batters faced should be regressed toward REPLACEMENT level, not league
    average -- pitchers who reach the majors without a track record are, on
    average, worse than the league. Regressing them to average systematically
    overrates every spot starter and rookie debut on the slate.
    """
    data = _get(f"/people/{person_id}",
                {"hydrate": "stats(group=pitching,type=career)"},
                ttl=604800, cache_name=f"pcar_{person_id}")
    people = data.get("people") or []
    if not people or not people[0].get("stats"):
        return {}
    splits = people[0]["stats"][0].get("splits") or []
    if not splits:
        return {}
    s = splits[0].get("stat", {})
    ip = _ip_to_float(s.get("inningsPitched"))
    return {"ip": ip, "k": _f(s, "strikeOuts"), "bb": _f(s, "baseOnBalls"),
            "hbp": _f(s, "hitByPitch"), "hr": _f(s, "homeRuns"),
            "bf": _f(s, "battersFaced"), "era": _f(s, "era")}


# ------------------------------------------------------------------- batters

def batter_stats(person_id: int, season: int = SEASON) -> dict | None:
    """Season hitting line plus which side he bats from."""
    data = _get(f"/people/{person_id}",
                {"hydrate": f"stats(group=hitting,type=season,season={season})"},
                ttl=21600, cache_name=f"b_{person_id}_{season}")
    people = data.get("people") or []
    if not people:
        return None
    p = people[0]
    side = p.get("batSide", {}).get("code", "R")
    splits = (p.get("stats") or [{}])[0].get("splits") or []
    base = {"id": person_id, "name": p.get("fullName", "?"), "side": side, "pa": 0.0}
    if not splits:
        return base
    s = splits[0].get("stat", {})
    base.update({
        "pa": _f(s, "plateAppearances"), "ab": _f(s, "atBats"),
        "h": _f(s, "hits"), "2b": _f(s, "doubles"), "3b": _f(s, "triples"),
        "hr": _f(s, "homeRuns"), "bb": _f(s, "baseOnBalls"),
        "hbp": _f(s, "hitByPitch"), "k": _f(s, "strikeOuts"),
        "tb": _f(s, "totalBases"), "rbi": _f(s, "rbi"), "r": _f(s, "runs"),
        "avg": _f(s, "avg"), "obp": _f(s, "obp"), "slg": _f(s, "slg"),
    })
    return base


def batter_career(person_id: int) -> dict:
    """Career hitting line -- the prior a short season regresses toward."""
    data = _get(f"/people/{person_id}",
                {"hydrate": "stats(group=hitting,type=career)"},
                ttl=604800, cache_name=f"bcar_{person_id}")
    people = data.get("people") or []
    if not people or not people[0].get("stats"):
        return {}
    splits = people[0]["stats"][0].get("splits") or []
    if not splits:
        return {}
    s = splits[0].get("stat", {})
    return {"pa": _f(s, "plateAppearances"), "h": _f(s, "hits"),
            "2b": _f(s, "doubles"), "3b": _f(s, "triples"),
            "hr": _f(s, "homeRuns"), "bb": _f(s, "baseOnBalls"),
            "k": _f(s, "strikeOuts"), "tb": _f(s, "totalBases")}


def batter_vs_hand(person_id: int, hand: str, season: int = SEASON) -> dict:
    """
    Batter's platoon split against LHP/RHP.

    Individual platoon splits are noisy -- a season is a few hundred PA at
    most against one hand -- so the model regresses these hard. But the effect
    is real and large for some hitters, and books do not always price it.
    """
    code = "vl" if hand.upper().startswith("L") else "vr"
    data = _get(f"/people/{person_id}/stats",
                {"stats": "statSplits", "group": "hitting",
                 "sitCodes": code, "season": season},
                ttl=21600, cache_name=f"bs_{person_id}_{code}_{season}")
    try:
        for sp in data["stats"][0]["splits"]:
            if sp["split"]["code"] == code:
                s = sp["stat"]
                return {"pa": _f(s, "plateAppearances"), "h": _f(s, "hits"),
                        "2b": _f(s, "doubles"), "3b": _f(s, "triples"),
                        "hr": _f(s, "homeRuns"), "bb": _f(s, "baseOnBalls"),
                        "k": _f(s, "strikeOuts"), "ops": _f(s, "ops")}
    except (KeyError, IndexError):
        pass
    return {}


def posted_lineup(game_pk: int) -> dict:
    """
    Confirmed batting orders, once the teams post them (~2-4h before start).

    Returns {'home': [ids in order], 'away': [...]} or empty when not yet out.
    """
    data = _get(f"/game/{game_pk}/boxscore", ttl=1800, cache_name=f"bx_{game_pk}")
    out = {}
    for side in ("home", "away"):
        try:
            order = data["teams"][side].get("battingOrder") or []
        except (KeyError, TypeError):
            order = []
        if order:
            out[side] = [int(x) for x in order[:9]]
    return out


def projected_lineup(team_id: int, n_games: int = 7,
                     season: int = SEASON) -> list[int]:
    """
    Most likely batting order, built from recent starts.

    Lineups aren't posted until a couple of hours before first pitch, but prop
    lines are up long before that. This reconstructs the probable order from
    who has actually been batting where over the last week -- each player is
    placed at his most common recent slot.
    """
    cache = f"projlu_{team_id}_{season}"
    hit = _cache_get(cache, 10800)
    if hit is not None:
        return hit

    from collections import defaultdict
    slots: dict[int, list[int]] = defaultdict(list)
    from datetime import timedelta
    today = date.today()
    seen = 0
    for d in range(1, 21):
        if seen >= n_games:
            break
        day = (today - timedelta(days=d)).isoformat()
        data = _get("/schedule", {"sportId": 1, "date": day, "teamId": team_id},
                    ttl=86400, cache_name=f"sch_{team_id}_{day}")
        for dt in data.get("dates", []):
            for g in dt.get("games", []):
                if g.get("status", {}).get("abstractGameState") != "Final":
                    continue
                side = ("home" if g["teams"]["home"]["team"]["id"] == team_id
                        else "away")
                lu = posted_lineup(g["gamePk"]).get(side) or []
                if len(lu) >= 9:
                    for i, pid in enumerate(lu[:9]):
                        slots[pid].append(i + 1)
                    seen += 1

    if not slots:
        return []
    # Rank players by how often they played, then settle them into their
    # median slot, resolving collisions in order of appearance count.
    import statistics as st
    ranked = sorted(slots.items(), key=lambda kv: (-len(kv[1]), st.median(kv[1])))
    order: list[int] = []
    for pid, ss in ranked[:9]:
        order.append(pid)
    order.sort(key=lambda pid: st.median(slots[pid]))
    _cache_put(cache, order)
    return order


def league_hitting_rates(season: int = SEASON) -> dict:
    """
    League-wide per-plate-appearance outcome rates.

    These are the priors every batter is regressed toward and the denominator
    in the log5 matchup adjustment, so they're computed from the live season
    rather than hardcoded.
    """
    cached = _cache_get(f"lgh_rates_{season}", 43200)
    if cached:
        return cached

    data = _get("/teams/stats",
                {"stats": "season", "group": "hitting", "season": season,
                 "sportIds": 1},
                ttl=43200, cache_name=f"lgh_{season}")
    tot = {k: 0.0 for k in ("pa", "ab", "h", "2b", "3b", "hr", "bb", "k", "tb", "r", "rbi")}
    try:
        for sp in data["stats"][0]["splits"]:
            s = sp["stat"]
            tot["pa"] += _f(s, "plateAppearances"); tot["ab"] += _f(s, "atBats")
            tot["h"] += _f(s, "hits"); tot["2b"] += _f(s, "doubles")
            tot["3b"] += _f(s, "triples"); tot["hr"] += _f(s, "homeRuns")
            tot["bb"] += _f(s, "baseOnBalls"); tot["k"] += _f(s, "strikeOuts")
            tot["tb"] += _f(s, "totalBases"); tot["r"] += _f(s, "runs")
            tot["rbi"] += _f(s, "rbi")
    except (KeyError, IndexError):
        pass

    pa = tot["pa"] or 1.0
    singles = tot["h"] - tot["2b"] - tot["3b"] - tot["hr"]
    out = {
        "pa": pa,
        "h_rate": tot["h"] / pa,
        "1b_rate": singles / pa,
        "2b_rate": tot["2b"] / pa,
        "3b_rate": tot["3b"] / pa,
        "hr_rate": tot["hr"] / pa,
        "bb_rate": tot["bb"] / pa,
        "k_rate": tot["k"] / pa,
        "tb_per_pa": tot["tb"] / pa,
        "pa_per_team_game": 0.0,
    }
    # Team plate appearances per game -- drives how many trips each slot gets.
    try:
        games = sum(_f(sp["stat"], "gamesPlayed") for sp in data["stats"][0]["splits"])
        out["pa_per_team_game"] = pa / games if games else 38.0
    except (KeyError, IndexError):
        out["pa_per_team_game"] = 38.0
    _cache_put(f"lgh_rates_{season}", out)
    return out


def batter_vs_pitcher(batter_id: int, pitcher_id: int,
                      season: int | None = None) -> dict:
    """
    Career head-to-head history between this hitter and this pitcher.

    Worth including, but worth weighting honestly: these samples are typically
    5-30 plate appearances. At 12 PA the sample moves a projection by about a
    percent once regressed properly. It is a tiebreaker and a talking point,
    not a driver -- and treating a 3-for-6 history as predictive is one of the
    most common ways bettors talk themselves into a bad number.
    """
    params = {"stats": "vsPlayerTotal", "group": "hitting",
              "opposingPlayerId": pitcher_id}
    if season:
        params["season"] = season
    data = _get(f"/people/{batter_id}/stats", params, ttl=86400,
                cache_name=f"bvp_{batter_id}_{pitcher_id}")
    best = {}
    try:
        for stt in data.get("stats", []):
            for sp in stt.get("splits", []):
                s = sp.get("stat", {})
                pa = _f(s, "plateAppearances")
                if pa > best.get("pa", 0):
                    best = {"pa": pa, "ab": _f(s, "atBats"), "h": _f(s, "hits"),
                            "hr": _f(s, "homeRuns"), "k": _f(s, "strikeOuts"),
                            "bb": _f(s, "baseOnBalls"),
                            "avg": _f(s, "avg"), "ops": _f(s, "ops")}
    except (KeyError, TypeError):
        pass
    return best


def prefetch_batters(batter_ids: list[int], pitcher_id: int, hand: str,
                     workers: int = 12) -> None:
    """
    Warm the disk cache for a whole lineup concurrently.

    Pricing one hitter needs five independent lookups (season, career, platoon
    split, head-to-head, and the boxscore behind the projected order). Done
    serially for eighteen hitters that is ninety round trips to a slow API and
    the daily run takes minutes. These calls don't depend on each other, so
    they're fetched in parallel and every later call is a local cache hit.
    """
    from concurrent.futures import ThreadPoolExecutor

    def warm(pid: int) -> None:
        try:
            batter_stats(pid)
            batter_career(pid)
            batter_vs_hand(pid, hand)
            if pitcher_id:
                batter_vs_pitcher(pid, pitcher_id)
        except Exception:
            pass  # a cold cache entry is not worth failing the run over

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(warm, [int(p) for p in batter_ids]))
