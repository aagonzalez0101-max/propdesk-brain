"""
Point-in-time statistics: what was actually knowable on a given date.

The reason this exists: backtesting with season-to-date stats fetched today
lets the model see the future. Replaying August 1st, it already knows how
every pitcher performed for the following three weeks. Measured on real
closing prices, that leak showed up as a clean gradient -- totals returned
+34% ROI on games 21-31 days old and +2% on games 1-10 days old. Same model,
same rule; the only difference was how much future had leaked in.

This module rebuilds every input from dated game logs, summing only games
played strictly BEFORE the target date. Same function names and return shapes
as `mlbdata`, so it can be swapped in as a drop-in provider and the model runs
unchanged.

Two honest limitations, both stated rather than hidden:

  * Platoon splits are unavailable by date -- statsapi has no dated split
    logs. In as-of mode the platoon delta is zero, so the backtest runs a
    slightly weaker model than the live one.
  * Bullpen quality is derived from team totals scaled by the league-wide
    reliever/overall ratio, because game logs don't separate starters from
    relievers without pulling every boxscore.
"""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

from . import mlbdata as D
from .mlbdata import DEFAULT_PARK, PARK_FACTORS, _f, _ip_to_float  # re-exported

CACHE = Path(__file__).resolve().parent.parent / "data" / "cache" / "asof"

# Relievers run slightly worse than a full staff league-wide; used to scale a
# team's overall pitching into a bullpen estimate without boxscore pulls.
RP_OVER_ALL = 1.03


def _before(log_date: str | None, cutoff: str) -> bool:
    """True when a logged game happened strictly before the cutoff date."""
    return bool(log_date) and log_date < cutoff


# --------------------------------------------------------------- game logs

_LOG_MEMO: dict = {}


def pitcher_log(pid: int, season: int) -> list[dict]:
    """Dated pitching game log, cached whole then filtered in memory."""
    memo_key = ("p", pid, season)
    if memo_key in _LOG_MEMO:
        return _LOG_MEMO[memo_key]
    data = D._get(f"/people/{pid}",
                  {"hydrate": f"stats(group=pitching,type=gameLog,season={season})"},
                  ttl=604800, cache_name=f"plog2_{pid}_{season}")
    people = data.get("people") or []
    if not people or not people[0].get("stats"):
        return []
    out = []
    for s in people[0]["stats"][0].get("splits", []):
        st = s.get("stat", {})
        out.append({
            "date": s.get("date"),
            "ip": _ip_to_float(st.get("inningsPitched")),
            "k": _f(st, "strikeOuts"), "bb": _f(st, "baseOnBalls"),
            "hbp": _f(st, "hitByPitch"), "hr": _f(st, "homeRuns"),
            "er": _f(st, "earnedRuns"), "bf": _f(st, "battersFaced"),
            "h": _f(st, "hits"), "gs": _f(st, "gamesStarted"),
        })
    _LOG_MEMO[memo_key] = out
    return out


def team_log(team_id: int, season: int, group: str) -> list[dict]:
    """Dated team game log for 'hitting' or 'pitching'."""
    memo_key = ("t", team_id, season, group)
    if memo_key in _LOG_MEMO:
        return _LOG_MEMO[memo_key]
    data = D._get(f"/teams/{team_id}/stats",
                  {"stats": "gameLog", "group": group, "season": season},
                  ttl=604800, cache_name=f"tlog_{team_id}_{group}_{season}")
    try:
        splits = data["stats"][0]["splits"]
    except (KeyError, IndexError):
        return []
    out = []
    for s in splits:
        st = s.get("stat", {})
        row = {"date": s.get("date")}
        if group == "hitting":
            row.update({
                "pa": _f(st, "plateAppearances"), "ab": _f(st, "atBats"),
                "h": _f(st, "hits"), "2b": _f(st, "doubles"),
                "3b": _f(st, "triples"), "hr": _f(st, "homeRuns"),
                "bb": _f(st, "baseOnBalls"), "k": _f(st, "strikeOuts"),
                "tb": _f(st, "totalBases"), "runs": _f(st, "runs"),
            })
        else:
            row.update({
                "ip": _ip_to_float(st.get("inningsPitched")),
                "er": _f(st, "earnedRuns"), "k": _f(st, "strikeOuts"),
                "bb": _f(st, "baseOnBalls"), "hr": _f(st, "homeRuns"),
            })
        out.append(row)
    _LOG_MEMO[memo_key] = out
    return out


def year_by_year(pid: int) -> list[dict]:
    """Season-by-season pitching totals, for a clean prior-seasons career."""
    data = D._get(f"/people/{pid}",
                  {"hydrate": "stats(group=pitching,type=yearByYear)"},
                  ttl=2592000, cache_name=f"yby_{pid}")
    people = data.get("people") or []
    if not people or not people[0].get("stats"):
        return []
    # A traded player gets one row PER TEAM plus a combined row with no team.
    # Gausman's 2018 appears three times: Baltimore 124.0, Atlanta 59.2, and a
    # teamless 183.2 that is the sum. Adding all of them double-counts every
    # season a pitcher changed clubs -- it inflated his career to 2318 IP
    # against a true 2061. So prefer the combined row when one exists, and
    # only sum per-team rows when it doesn't.
    by_season: dict[int, dict] = {}
    per_team: dict[int, list[dict]] = {}
    for s in people[0]["stats"][0].get("splits", []):
        if (s.get("sport") or {}).get("id") not in (1, None):
            continue                      # major-league seasons only
        st = s.get("stat", {})
        season = int(s.get("season", 0) or 0)
        row = {
            "season": season,
            "ip": _ip_to_float(st.get("inningsPitched")),
            "k": _f(st, "strikeOuts"), "bb": _f(st, "baseOnBalls"),
            "hbp": _f(st, "hitByPitch"), "hr": _f(st, "homeRuns"),
            "bf": _f(st, "battersFaced"), "h": _f(st, "hits"),
        }
        if s.get("team") is None or not (s.get("team") or {}).get("id"):
            by_season[season] = row       # combined row wins outright
        else:
            per_team.setdefault(season, []).append(row)

    for season, rows in per_team.items():
        if season in by_season:
            continue
        merged = {"season": season}
        for k in ("ip", "k", "bb", "hbp", "hr", "bf", "h"):
            merged[k] = sum(r[k] for r in rows)
        by_season[season] = merged

    return [by_season[s] for s in sorted(by_season)]


# ------------------------------------------------------------- the provider

def batter_log(pid: int, season: int) -> list[dict]:
    """Dated hitting game log, cached whole then filtered in memory."""
    memo_key = ("b", pid, season)
    if memo_key in _LOG_MEMO:
        return _LOG_MEMO[memo_key]
    data = D._get(f"/people/{pid}",
                  {"hydrate": f"stats(group=hitting,type=gameLog,season={season})"},
                  ttl=604800, cache_name=f"blog_{pid}_{season}")
    people = data.get("people") or []
    if not people or not people[0].get("stats"):
        return []
    out = []
    for s in people[0]["stats"][0].get("splits", []):
        st = s.get("stat", {})
        out.append({
            "date": s.get("date"),
            "pa": _f(st, "plateAppearances"), "ab": _f(st, "atBats"),
            "h": _f(st, "hits"), "2b": _f(st, "doubles"),
            "3b": _f(st, "triples"), "hr": _f(st, "homeRuns"),
            "bb": _f(st, "baseOnBalls"), "hbp": _f(st, "hitByPitch"),
            "k": _f(st, "strikeOuts"), "tb": _f(st, "totalBases"),
            "rbi": _f(st, "rbi"), "r": _f(st, "runs"),
        })
    _LOG_MEMO[memo_key] = out
    return out


class AsOf:
    """
    Drop-in replacement for the `mlbdata` module, frozen at a cutoff date.

    Swap it into the model with `mlbmodel.D = AsOf("2026-08-01")` and every
    projection is built only from games played before that morning.
    """

    DEFAULT_PARK = DEFAULT_PARK
    PARK_FACTORS = PARK_FACTORS

    def __init__(self, cutoff: str, season: int | None = None):
        self.cutoff = cutoff
        self.season = season or int(cutoff[:4])
        self._lg = None

    # ---- passthroughs the model also uses -------------------------------
    def _get(self, *a, **k):
        return D._get(*a, **k)

    def schedule(self, game_date=None):
        return D.schedule(game_date)

    def game_context(self, g):
        return D.game_context(g)

    def posted_lineup(self, pk):
        return D.posted_lineup(pk)

    # ---- batters ---------------------------------------------------------
    def batter_stats(self, pid: int, season: int | None = None) -> dict | None:
        """Season hitting line accumulated only from games before the cutoff.

        This did not exist. `lineupoff` fell through to the live `mlbdata`
        module, so every backtest of the v3 lineup term read end-of-season
        batter lines -- the model saw the future for the exact games it was
        being scored on.
        """
        season = season or self.season
        info = D._get(f"/people/{pid}", {}, ttl=2592000, cache_name=f"binfo_{pid}")
        people = info.get("people") or []
        name = people[0].get("fullName", "?") if people else "?"
        side = (people[0].get("batSide", {}).get("code", "R") if people else "R")

        agg = {"pa": 0.0, "ab": 0.0, "h": 0.0, "2b": 0.0, "3b": 0.0, "hr": 0.0,
               "bb": 0.0, "hbp": 0.0, "k": 0.0, "tb": 0.0, "rbi": 0.0, "r": 0.0}
        for row in batter_log(pid, season):
            if not _before(row["date"], self.cutoff):
                continue
            for k in agg:
                agg[k] += row.get(k, 0.0) or 0.0

        out = {"id": pid, "name": name, "side": side}
        out.update(agg)
        ab, bb, hbp = agg["ab"], agg["bb"], agg["hbp"]
        sf = max(0.0, agg["pa"] - ab - bb - hbp)
        out["avg"] = agg["h"] / ab if ab else 0.0
        denom = ab + bb + hbp + sf
        out["obp"] = (agg["h"] + bb + hbp) / denom if denom else 0.0
        out["slg"] = agg["tb"] / ab if ab else 0.0
        return out

    # ---- pitchers --------------------------------------------------------
    def pitcher_stats(self, pid: int, season: int | None = None) -> dict | None:
        season = season or self.season
        info = D._get(f"/people/{pid}", {}, ttl=2592000, cache_name=f"pinfo_{pid}")
        people = info.get("people") or []
        name = people[0].get("fullName", "?") if people else "?"
        hand = (people[0].get("pitchHand", {}).get("code", "R")
                if people else "R")

        agg = {"ip": 0.0, "k": 0.0, "bb": 0.0, "hbp": 0.0, "hr": 0.0,
               "er": 0.0, "bf": 0.0, "h": 0.0, "gs": 0.0}
        for row in pitcher_log(pid, season):
            if not _before(row["date"], self.cutoff):
                continue
            for k in agg:
                agg[k] += row.get(k, 0.0)

        ip = agg["ip"]
        return {
            "id": pid, "name": name, "hand": hand, **agg,
            "era": (agg["er"] / ip * 9.0) if ip > 0 else 0.0,
            "whip": ((agg["h"] + agg["bb"]) / ip) if ip > 0 else 0.0,
            "2b": 0.0, "3b": 0.0,
        }

    def pitcher_career(self, pid: int) -> dict:
        """Career through the cutoff: all prior seasons plus this season to date."""
        prior = {"ip": 0.0, "k": 0.0, "bb": 0.0, "hbp": 0.0, "hr": 0.0,
                 "bf": 0.0, "h": 0.0}
        for yr in year_by_year(pid):
            if yr["season"] >= self.season:
                continue
            for k in prior:
                prior[k] += yr.get(k, 0.0)
        cur = self.pitcher_stats(pid)
        for k in prior:
            prior[k] += (cur or {}).get(k, 0.0)
        ip = prior["ip"]
        prior["era"] = 0.0
        return prior if ip > 0 else {}

    def pitcher_recent_starts(self, pid: int, n: int = 6,
                              season: int | None = None) -> list[dict]:
        season = season or self.season
        starts = [r for r in pitcher_log(pid, season)
                  if r.get("gs") and _before(r["date"], self.cutoff)]
        return starts[-n:]

    # ---- teams -----------------------------------------------------------
    def _team_hit_agg(self, team_id: int) -> dict:
        agg = {"pa": 0.0, "ab": 0.0, "h": 0.0, "2b": 0.0, "3b": 0.0,
               "hr": 0.0, "bb": 0.0, "k": 0.0, "tb": 0.0, "runs": 0.0,
               "games": 0.0}
        for row in team_log(team_id, self.season, "hitting"):
            if not _before(row["date"], self.cutoff):
                continue
            for k in agg:
                if k == "games":
                    continue
                agg[k] += row.get(k, 0.0)
            agg["games"] += 1
        return agg

    def team_hitting(self, team_id: int, season: int | None = None) -> dict:
        a = self._team_hit_agg(team_id)
        ab, pa = a["ab"], a["pa"]
        if pa <= 0:
            return {}
        obp = ((a["h"] + a["bb"]) / pa) if pa else 0.0
        slg = (a["tb"] / ab) if ab else 0.0
        return {"pa": pa, "ops": obp + slg, "obp": obp, "slg": slg,
                "avg": (a["h"] / ab) if ab else 0.0,
                "runs": a["runs"], "hr": a["hr"], "k": a["k"], "bb": a["bb"],
                "games": a["games"]}

    def team_hitting_vs_hand(self, team_id: int, hand: str,
                             season: int | None = None) -> dict:
        # No dated split logs exist. Returning empty makes the model's platoon
        # delta zero rather than silently reusing a full-season (future-aware)
        # split -- a slightly weaker model, but an honest one.
        return {}

    def team_hitting_home_away(self, team_id: int,
                               season: int | None = None) -> dict:
        return {}

    def team_pitching_split(self, team_id: int, role: str = "rp",
                            season: int | None = None) -> dict:
        agg = {"ip": 0.0, "er": 0.0, "k": 0.0, "bb": 0.0, "hr": 0.0}
        for row in team_log(team_id, self.season, "pitching"):
            if not _before(row["date"], self.cutoff):
                continue
            for k in agg:
                agg[k] += row.get(k, 0.0)
        if agg["ip"] <= 0:
            return {}
        era = agg["er"] / agg["ip"] * 9.0
        if role == "rp":
            # Scale the whole staff into a bullpen estimate; separating
            # starters would mean pulling every boxscore in the season.
            era *= RP_OVER_ALL
            agg["ip"] *= 0.45
        else:
            agg["ip"] *= 0.55
        return {**agg, "era": era}

    # ---- league ----------------------------------------------------------
    def league_averages(self, season: int | None = None) -> dict:
        if self._lg is not None:
            return self._lg

        CACHE.mkdir(parents=True, exist_ok=True)
        path = CACHE / f"lg_{self.cutoff}.json"
        if path.exists():
            try:
                self._lg = json.loads(path.read_text())
                return self._lg
            except json.JSONDecodeError:
                pass

        teams = D._get("/teams", {"sportId": 1, "season": self.season},
                       ttl=2592000, cache_name=f"teams_{self.season}")
        ids = [t["id"] for t in teams.get("teams", [])]

        hit = {"pa": 0.0, "ab": 0.0, "h": 0.0, "tb": 0.0, "bb": 0.0,
               "runs": 0.0, "games": 0.0, "hr": 0.0, "k": 0.0,
               "2b": 0.0, "3b": 0.0}
        pit = {"ip": 0.0, "er": 0.0, "k": 0.0, "bb": 0.0, "hr": 0.0}
        for tid in ids:
            a = self._team_hit_agg(tid)
            for k in hit:
                hit[k] += a.get(k, 0.0)
            for row in team_log(tid, self.season, "pitching"):
                if not _before(row["date"], self.cutoff):
                    continue
                for k in pit:
                    pit[k] += row.get(k, 0.0)

        games = hit["games"] or 1.0
        ip = pit["ip"] or 1.0
        pa = hit["pa"] or 1.0
        ab = hit["ab"] or 1.0
        bf = pa  # league batters faced equals league plate appearances

        obp = (hit["h"] + hit["bb"]) / pa
        slg = hit["tb"] / ab
        era = pit["er"] / ip * 9.0
        out = {
            "season": self.season,
            "runs_per_team_game": hit["runs"] / games,
            "league_ops": obp + slg,
            "era": era,
            "k9": pit["k"] / ip * 9.0,
            "bb9": pit["bb"] / ip * 9.0,
            "hr9": pit["hr"] / ip * 9.0,
            "k_rate": pit["k"] / bf,
            "bf_per_ip": bf / ip,
            "fip_constant": era - ((13 * pit["hr"] + 3 * pit["bb"]
                                    - 2 * pit["k"]) / ip),
        }
        self._lg = out
        path.write_text(json.dumps(out))
        return out

    def league_hitting_rates(self, season: int | None = None) -> dict:
        lg = self.league_averages()
        teams = D._get("/teams", {"sportId": 1, "season": self.season},
                       ttl=2592000, cache_name=f"teams_{self.season}")
        agg = {"pa": 0.0, "h": 0.0, "2b": 0.0, "3b": 0.0, "hr": 0.0,
               "bb": 0.0, "k": 0.0, "tb": 0.0, "games": 0.0}
        for t in teams.get("teams", []):
            a = self._team_hit_agg(t["id"])
            for k in agg:
                agg[k] += a.get(k, 0.0)
        pa = agg["pa"] or 1.0
        singles = agg["h"] - agg["2b"] - agg["3b"] - agg["hr"]
        return {
            "pa": pa, "h_rate": agg["h"] / pa, "1b_rate": singles / pa,
            "2b_rate": agg["2b"] / pa, "3b_rate": agg["3b"] / pa,
            "hr_rate": agg["hr"] / pa, "bb_rate": agg["bb"] / pa,
            "k_rate": agg["k"] / pa, "tb_per_pa": agg["tb"] / pa,
            "pa_per_team_game": pa / (agg["games"] or 1.0),
        }
