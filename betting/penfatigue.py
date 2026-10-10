"""
Bullpen fatigue -- innings the relief corps has absorbed in recent days.

The fitted margin model put bullpen quality at +0.928, essentially level with
the starter's +0.897, while the hand-built v3 treats the pen as a leftover
covering whatever innings the starter doesn't. That mis-weighting is the
clearest signal in the fit.

Season bullpen RA9 also says nothing about AVAILABILITY. A pen that threw six
innings yesterday and five the day before is not the pen its season line
describes -- the best arms are unavailable and the innings fall to whoever is
left. That is knowable before first pitch and is the kind of thing a market
prices roughly rather than precisely.

Measured as relief innings over the trailing 3 days, relative to a normal load
of ~3 per day.
"""
from __future__ import annotations

from datetime import date, timedelta

from . import mlbdata as D

NORMAL_PEN_IP_PER_DAY = 3.1


def recent_relief_ip(team_id: int, day: str, lookback: int = 3) -> dict:
    """Relief innings thrown by a team over the previous `lookback` days."""
    d0 = date.fromisoformat(day)
    total = 0.0
    games = 0
    for k in range(1, lookback + 1):
        dd = (d0 - timedelta(days=k)).isoformat()
        try:
            sched = D.schedule(dd)
        except Exception:
            continue
        for g in sched:
            try:
                c = D.game_context(g)
            except Exception:
                continue
            if str(c.get("home_id")) != str(team_id) and str(c.get("away_id")) != str(team_id):
                continue
            if c.get("state") != "Final":
                continue
            try:
                bx = D._get(f"/game/{c['game_pk']}/boxscore", {}, ttl=604800,
                            cache_name=f"bx_{c['game_pk']}")
            except Exception:
                continue
            side = "home" if str(c["home_id"]) == str(team_id) else "away"
            t = bx.get("teams", {}).get(side, {})
            pitchers = t.get("pitchers", []) or []
            games += 1
            for pid in pitchers[1:]:            # skip the starter
                p = t.get("players", {}).get(f"ID{pid}", {})
                ip = p.get("stats", {}).get("pitching", {}).get("inningsPitched")
                if ip:
                    try:
                        whole, _, frac = str(ip).partition(".")
                        total += float(whole) + (float(frac) / 3.0 if frac else 0.0)
                    except ValueError:
                        pass
    expected = NORMAL_PEN_IP_PER_DAY * lookback
    return {"ip": total, "games": games,
            "fatigue": (total - expected) / expected if expected else 0.0}
