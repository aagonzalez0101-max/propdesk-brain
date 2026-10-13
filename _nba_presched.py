"""NBA preseason schedule helper (10/13, user: "the last preseason is fucked"). Curry's 2nd-to-last / last preseason games: 2024 16 + 28 min,
2025 27 + 30 min -- starters stretch out right before the opener, so preseason UNDERS are blocked in a team's last 2 preseason games.
    import _nba_presched as S; S.late_preseason("GS", "2026-10-13")   -> True if that game is one of GS's last 2 preseason games
"""
import json, os, datetime, urllib.request

CACHE = "_nba_presched.json"
ABBR_ID = None


def _g(u):
    return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read())


def _load():
    if os.path.exists(CACHE) and json.load(open(CACHE)).get("day") == datetime.date.today().isoformat():
        return json.load(open(CACHE))["teams"]
    teams = {}
    for t in _g("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams")["sports"][0]["leagues"][0]["teams"]:
        ab, tid = t["team"]["abbreviation"], t["team"]["id"]
        try:
            ev = _g("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/%s/schedule?season=2027&seasontype=1" % tid).get("events", [])
            # ESPN dates are UTC; a 9 PM CT tip shows as the next day -> store the CT date
            teams[ab] = sorted((datetime.datetime.fromisoformat(e["date"].replace("Z", "+00:00")) - datetime.timedelta(hours=5)).date().isoformat() for e in ev)
        except Exception:
            pass
    json.dump(dict(day=datetime.date.today().isoformat(), teams=teams), open(CACHE, "w"))
    return teams


FIX = {"GSW": "GS", "NYK": "NY", "SAS": "SA", "NOP": "NO", "UTA": "UTAH", "WAS": "WSH", "PHX": "PHX"}


def late_preseason(team, day, n=2):
    T = _load()
    dates = T.get(FIX.get(team, team)) or T.get(team)
    return bool(dates) and day in dates[-n:]
