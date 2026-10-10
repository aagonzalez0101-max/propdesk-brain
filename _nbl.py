"""Australian NBL from ESPN (free; box scores exist from the 2023-24 season on). 2026-10-07, overseas-basketball backtest.
    python _nbl.py pull     # every game day Sep-Apr since 2023 -> nbl_games.jsonl + nbl_players.jsonl (same shape as the Euroleague files)"""
import json, os, sys, time, datetime, requests

SB = "https://site.api.espn.com/apis/site/v2/sports/basketball/nbl/scoreboard?dates=%s"
SM = "https://site.api.espn.com/apis/site/v2/sports/basketball/nbl/summary?event=%s"
CACHE = "_nbl"


def get(u):
    for a in range(4):
        try:
            r = requests.get(u, timeout=30)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        time.sleep(2 + 2 * a)
    return None


def pull():
    os.makedirs(CACHE, exist_ok=True)
    games, players = [], []
    d = datetime.date(2023, 9, 1); end = datetime.date.today()
    while d <= end:
        if d.month in (5, 6, 7, 8):
            d += datetime.timedelta(days=1); continue
        j = get(SB % d.strftime("%Y%m%d")) or {}
        for e in j.get("events", []):
            c = e["competitions"][0]
            if not e["status"]["type"].get("completed"):
                continue
            t = {x["homeAway"]: x for x in c["competitors"]}
            season = "N%d" % (d.year if d.month >= 9 else d.year - 1)
            g = dict(season=season, code=e["id"], date=d.isoformat(), home=t["home"]["team"]["abbreviation"], away=t["away"]["team"]["abbreviation"],
                     hs=int(t["home"]["score"]), as_=int(t["away"]["score"]))
            games.append(g)
            f = os.path.join(CACHE, "%s.json" % e["id"])
            s = json.load(open(f, encoding="utf-8")) if os.path.exists(f) else get(SM % e["id"])
            if s and not os.path.exists(f):
                json.dump(s, open(f, "w", encoding="utf-8"))
            for grp in (s or {}).get("boxscore", {}).get("players", []):
                team = grp["team"]["abbreviation"]; opp = g["away"] if team == g["home"] else g["home"]
                st = grp["statistics"][0]; lab = st["labels"]
                for a in st["athletes"]:
                    if not a.get("stats") or not a.get("athlete"):
                        continue
                    v = dict(zip(lab, a["stats"]))
                    try:
                        mins = float(v.get("MIN") or 0)
                    except ValueError:
                        mins = 0
                    if mins <= 0:
                        continue
                    players.append(dict(season=season, code=e["id"], date=g["date"], team=team, opp=opp, home=int(team == g["home"]),
                                        pid=a["athlete"].get("id") or a["athlete"].get("displayName"), name=a["athlete"].get("displayName"), mins=mins, pts=float(v["PTS"]), reb=float(v["REB"]),
                                        ast=float(v["AST"]), tpm=float(v["3PT"].split("-")[0]), start=bool(a.get("starter"))))
        d += datetime.timedelta(days=1)
    json.dump(None, open(os.path.join(CACHE, "_done"), "w"))
    with open("nbl_games.jsonl", "w") as f:
        for g in games:
            f.write(json.dumps(g) + "\n")
    with open("nbl_players.jsonl", "w", encoding="utf-8") as f:
        for p in players:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print("NBL games %d  player-games %d" % (len(games), len(players)))


if __name__ == "__main__":
    pull()
