"""TWO PRIOR SEASONS FOR EVERY SPORT (2026-09-30). User: "add 2024 and 2025 to each player so we get a real h2h read".

    python _backfill.py all        # every step below, in order (each is resumable -- rerun after a crash)
    python _backfill.py mlb|wnba|nfl|mls|nba

What each step adds to sports.db
  mlb   2024 + 2025 game logs, every player on a 40-man/full-season roster those years (statsapi, reg + post)
  wnba  2024 game logs for every current roster player (ESPN gamelog)
  nfl   2024 weekly player stats (nflverse stats_player_week_2024.csv)
  mls   MLS 2024 matches (FotMob) -> soccer rows
  nba   2024-25 box scores (ESPN scoreboard walk) -> nba_logs.json -> NBA rows, season label from the date
NHL (2024-25, 2025-26) and the top-5 European leagues (2024/25, 2025/26) already have two full prior seasons.
"""
import sys, os, json, time, datetime, subprocess, urllib.request
from concurrent.futures import ThreadPoolExecutor
import _db

H = {"User-Agent": "Mozilla/5.0"}


def log(*a):
    print(datetime.datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def mlb(c, seasons=(2025, 2024)):
    import requests
    S = "https://statsapi.mlb.com/api/v1"
    for season in seasons:
        have = {r[0] for r in c.execute("SELECT DISTINCT player_id FROM player_games WHERE sport='MLB' AND season=?", (str(season),))}
        ids = set()
        for t in requests.get(S + "/teams", params={"sportId": 1, "season": season}, headers=H, timeout=30).json()["teams"]:
            ro = requests.get(S + "/teams/%d/roster" % t["id"], params={"rosterType": "fullSeason", "season": season}, headers=H, timeout=30).json()
            for p in ro.get("roster", []):
                ids.add((p["person"]["id"], p["person"]["fullName"], t["name"], p["position"]["abbreviation"]))
        todo = [x for x in ids if str(x[0]) not in have]
        log("MLB %d: %d roster players, %d to fetch" % (season, len(ids), len(todo)))

        def one(x):
            pid, name, team, pos = x
            out = []
            for grp in (("pitching",) if pos == "P" else ("hitting",)) if pos != "TWP" else ("hitting", "pitching"):
                for attempt in range(3):
                    try:
                        d = requests.get(S + "/people/%d/stats" % pid, params=dict(stats="gameLog", group=grp, season=season,
                                         gameType="R,F,D,L,W"), headers=H, timeout=30).json()
                        break
                    except Exception:
                        time.sleep(2 + 3 * attempt)
                else:
                    continue
                for s in (d.get("stats") or [{}])[0].get("splits", []):
                    st = s["stat"]; st["group"] = grp
                    out.append(("MLB", "MLB", str(season), s["date"], str(s.get("game", {}).get("gamePk")), str(pid), name,
                                (s.get("team") or {}).get("name", team), (s.get("opponent") or {}).get("name"), int(bool(s.get("isHome"))),
                                st.get("plateAppearances") or st.get("battersFaced"), json.dumps(st)))
            return out
        n = 0
        with ThreadPoolExecutor(8) as ex:
            for rows in ex.map(one, todo):
                _db.put_pg(c, rows); n += 1
                if n % 200 == 0:
                    log("  MLB %d: %d / %d players" % (season, n, len(todo)))
        log("MLB %d done" % season)


def wnba(c, season=2024):
    import _bball as B
    have = {r[0] for r in c.execute("SELECT DISTINCT player_id FROM player_games WHERE sport='WNBA' AND season=?", (str(season),))}
    ro = B.roster("wnba")
    todo = [(aid, team, name) for aid, team, name in ro.values() if str(aid) not in have]
    log("WNBA %d: %d players to fetch" % (season, len(todo)))

    def one(x):
        aid, team, name = x
        try:
            d = B.g("https://site.web.api.espn.com/apis/common/v3/sports/basketball/wnba/athletes/%s/gamelog?season=%d" % (aid, season))
        except Exception:
            return []
        n = [s.lower() for s in d.get("names", [])]
        if not n:
            return []
        tp = [i for i, s in enumerate(n) if s.startswith("threepointfieldgoalsmade")]
        out = []
        for st_ in d.get("seasonTypes", []):
            post = "post" in (st_.get("displayName") or "").lower()
            for cat in st_.get("categories", []):
                for e in cat.get("events", []):
                    s = e["stats"]; m = d["events"][e["eventId"]]
                    try:
                        g = dict(date=m["gameDate"][:10], opp=m["opponent"]["abbreviation"], home=m.get("atVs") == "vs",
                                 min=float(s[n.index("minutes")]), pts=float(s[n.index("points")]), reb=float(s[n.index("totalrebounds")]),
                                 ast=float(s[n.index("assists")]), tpm=float(s[tp[0]].split("-")[0]) if tp else 0.0, post=post)
                    except (ValueError, IndexError, KeyError):
                        continue
                    t_ = (m.get("team") or {}).get("abbreviation") or team
                    out.append(("WNBA", "WNBA", str(season), g["date"], "%s_%s" % (g["date"], g["opp"]), str(aid), name, t_, g["opp"],
                                int(g["home"]), g["min"], json.dumps({k: g[k] for k in ("pts", "reb", "ast", "tpm", "post")})))
        return out
    with ThreadPoolExecutor(6) as ex:
        for rows in ex.map(one, todo):
            _db.put_pg(c, rows)
    log("WNBA %d done" % season)


def nfl(c, season=2024):
    f = "nfl_%d_weekly.csv" % season
    if not os.path.exists(f):
        u = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_%d.csv" % season
        open(f, "wb").write(urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=120).read())
    import csv
    rows = []
    for r in csv.DictReader(open(f, encoding="utf-8")):
        keep = {k: r[k] for k in ("position", "completions", "attempts", "passing_yards", "passing_tds", "interceptions", "passing_interceptions",
                                  "carries", "rushing_yards", "rushing_tds", "receptions", "targets", "receiving_yards", "receiving_tds") if k in r}
        team = r.get("recent_team") or r.get("team", "")
        rows.append(("NFL", "NFL", str(season), "W%02d" % int(r["week"]), "%s_W%s_%s" % (season, r["week"], team),
                     r.get("player_id") or r["player_display_name"], r["player_display_name"], team, r.get("opponent_team"), None, None,
                     json.dumps(keep)))
    _db.put_pg(c, rows)
    log("NFL %d: %d player-weeks" % (season, len(rows)))


def mls(c):
    import _soccer_hist as SH
    if (130, "MLS", "2024") not in SH.MLS:
        SH.MLS.insert(0, (130, "MLS", "2024"))
    SH.fetch()
    SH.build()
    _db.imp_soccer(c)
    log("MLS 2024 done")


def nba(c):
    subprocess.run(["python", "_nba.py", "pull", "2024-10-22", "2025-06-25"], check=False)
    L = json.load(open("nba_logs.json", encoding="utf-8"))
    rows = []
    for v in L.values():
        for g in v:
            y = int(g["date"][:4]); season = "%d-%02d" % ((y, (y + 1) % 100) if g["date"][5:7] >= "08" else (y - 1, y % 100))
            st = {k: g.get(k) for k in ("pts", "reb", "ast", "stl", "blk", "to", "tpm", "fga", "fta", "starter")}
            rows.append(("NBA", "NBA", season, g["date"], str(g["game"]), str(g["pid"]), g["name"], str(g["team"]), str(g["opp"]),
                         None, g.get("min"), json.dumps(st)))
    _db.put_pg(c, rows)
    log("NBA rows now: %d" % c.execute("SELECT COUNT(*) FROM player_games WHERE sport='NBA'").fetchone()[0])


STEPS = {"mlb": mlb, "wnba": wnba, "nfl": nfl, "mls": mls, "nba": nba}

if __name__ == "__main__":
    want = sys.argv[1:] or ["all"]
    if want == ["all"]:
        want = ["nfl", "wnba", "mlb", "mls", "nba"]
    c = _db.con()
    for k in want:
        try:
            STEPS[k](c)
        except Exception as e:
            import traceback; traceback.print_exc()
            log("%s FAILED: %s (rerun `python _backfill.py %s`)" % (k, e, k))
    _db.stats(c)
