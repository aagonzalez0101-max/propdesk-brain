"""THE DATABASE -- every player-game and team-game we have, one SQLite file (sports.db). 2026-09-30.

    python _db.py build            # import everything already downloaded (NHL, soccer, NBA, NFL, WNBA/NBA team boxes)
    python _db.py fetch-mlb        # add every MLB hitter/pitcher game this season (statsapi, cached, resumable)
    python _db.py fetch-wnba       # add every WNBA player game (ESPN gamelogs)
    python _db.py update           # nightly: new NHL box scores, soccer matches, MLB/WNBA games since the last load
    python _db.py stats            # what's in it
    python _db.py q "SELECT ..."   # any query

Tables
  player_games(sport, league, season, date, game_id, player_id, player, team, opp, home, minutes, stats JSON)
  team_games(sport, league, season, date, game_id, team, opp, home, stats JSON)   -- for=stats, against=opp_stats
Everything is keyed so re-imports never duplicate (UNIQUE sport+game_id+player_id / sport+game_id+team).
"""
import sys, os, json, csv, sqlite3, datetime, glob
from concurrent.futures import ThreadPoolExecutor

DB = "sports.db"


def con():
    c = sqlite3.connect(DB, timeout=300)          # backfills + site builds share the file (2026-09-30 lock)
    c.execute("""CREATE TABLE IF NOT EXISTS player_games(sport TEXT, league TEXT, season TEXT, date TEXT, game_id TEXT,
                 player_id TEXT, player TEXT, team TEXT, opp TEXT, home INTEGER, minutes REAL, stats TEXT,
                 UNIQUE(sport, game_id, player_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS team_games(sport TEXT, league TEXT, season TEXT, date TEXT, game_id TEXT,
                 team TEXT, opp TEXT, home INTEGER, stats TEXT, opp_stats TEXT, UNIQUE(sport, game_id, team))""")
    c.execute("CREATE INDEX IF NOT EXISTS pg_player ON player_games(sport, player)")
    c.execute("CREATE INDEX IF NOT EXISTS pg_team ON player_games(sport, team, date)")
    c.execute("CREATE INDEX IF NOT EXISTS tg_team ON team_games(sport, team, date)")
    return c


def put_pg(c, rows):
    c.executemany("INSERT OR IGNORE INTO player_games VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows); c.commit()


def put_tg(c, rows):
    c.executemany("INSERT OR IGNORE INTO team_games VALUES (?,?,?,?,?,?,?,?,?,?)", rows); c.commit()


# ------------------------------------------------------------------ importers from files we already have
def imp_nhl(c):
    if not os.path.exists("_nhl_hist_rows.json"):
        return
    R = json.load(open("_nhl_hist_rows.json"))
    skip = {"gid", "season", "date", "team", "opp", "home", "pid", "name", "toi"}
    put_pg(c, [("NHL", "NHL", r["season"], r["date"], str(r["gid"]), str(r["pid"]), r["name"], r["team"], r["opp"], int(bool(r["home"])),
                r.get("toi"), json.dumps({k: v for k, v in r.items() if k not in skip})) for r in R])
    T = {}
    for r in R:
        T[(r["gid"], r["team"])] = ("NHL", "NHL", r["season"], r["date"], str(r["gid"]), r["team"], r["opp"], int(bool(r["home"])),
                                    json.dumps({"sog": r["team_sog"], "goals": r["team_goals"]}), json.dumps({"sog": r["opp_sog"], "goals": r["opp_goals"]}))
    put_tg(c, list(T.values()))
    print("NHL: %d player-games, %d team-games" % (len(R), len(T)))


def imp_soccer(c):
    if not os.path.exists("_soccer_hist_rows.json"):
        return
    R = json.load(open("_soccer_hist_rows.json"))
    pg, T = [], {}
    for r in R:
        st = {k: r.get(k) for k in ("passes", "shots", "sot", "saves", "gk")}
        pg.append(("SOCCER", r["lg"], r["season"], r["date"], str(r["mid"]), str(r["pid"]), r["name"], str(r["team"]), str(r["opp"]),
                   int(bool(r["home"])), r.get("mins"), json.dumps(st)))
        if r.get("t_passes") is not None:
            T[(r["mid"], r["team"])] = ("SOCCER", r["lg"], r["season"], r["date"], str(r["mid"]), str(r["team"]), str(r["opp"]), int(bool(r["home"])),
                                        json.dumps({k[2:]: v for k, v in r.items() if k.startswith("t_")}),
                                        json.dumps({k[2:]: v for k, v in r.items() if k.startswith("o_")}))
    put_pg(c, pg); put_tg(c, list(T.values()))
    print("SOCCER: %d player-games, %d team-games" % (len(pg), len(T)))


def imp_nba_players(c):
    if not os.path.exists("nba_logs.json"):
        return
    L = json.load(open("nba_logs.json"))
    rows = []
    for v in L.values():
        for g in v:
            st = {k: g.get(k) for k in ("pts", "reb", "ast", "stl", "blk", "to", "tpm", "fga", "fta", "starter")}
            rows.append(("NBA", "NBA", "2025-26", g["date"], str(g["game"]), str(g["pid"]), g["name"], str(g["team"]), str(g["opp"]),
                         None, g.get("min"), json.dumps(st)))
    put_pg(c, rows)
    print("NBA: %d player-games" % len(rows))


def imp_bball_teams(c):
    import _bball_card as C
    for lg in ("wnba", "nba"):
        rows = C.team_games(lg)
        put_tg(c, [(lg.upper(), lg.upper(), r["date"][:4], r["date"], "%s_%s" % (r["date"], "".join(sorted([r["team"], r["opp"]]))), r["team"], r["opp"],
                    None, json.dumps(r["f"]), json.dumps(r["a"])) for r in rows])
        print("%s: %d team-games" % (lg.upper(), len(rows)))


def imp_nfl(c):
    rows = []
    for f, season in (("nfl_2025_weekly.csv", "2025"), ("nfl_2026_weekly.csv", "2026")):
        if not os.path.exists(f):
            continue
        for r in csv.DictReader(open(f, encoding="utf-8")):
            keep = {k: r[k] for k in ("position", "completions", "attempts", "passing_yards", "passing_tds", "interceptions", "carries",
                                       "rushing_yards", "rushing_tds", "receptions", "targets", "receiving_yards", "receiving_tds") if k in r}
            rows.append(("NFL", "NFL", season, "W%02d" % int(r["week"]), "%s_W%s_%s" % (season, r["week"], r.get("recent_team", r.get("team", ""))),
                         r.get("player_id") or r["player_display_name"], r["player_display_name"], r.get("recent_team") or r.get("team"),
                         r.get("opponent_team"), None, None, json.dumps(keep)))
    put_pg(c, rows)
    print("NFL: %d player-games" % len(rows))


# ------------------------------------------------------------------ fetchers for what we don't have yet
def fetch_mlb(c, season=2026):
    import requests
    H = {"User-Agent": "Mozilla/5.0"}; S = "https://statsapi.mlb.com/api/v1"
    # season-filtered: with 2024-25 backfilled, an unfiltered set skipped every veteran and lost 2026 (fixed 2026-10-01)
    have = {r[0] for r in c.execute("SELECT DISTINCT player_id FROM player_games WHERE sport='MLB' AND season=?", (str(season),))}
    ids = set()
    for t in requests.get(S + "/teams", params={"sportId": 1, "season": season}, headers=H, timeout=30).json()["teams"]:
        for p in requests.get(S + "/teams/%d/roster" % t["id"], params={"rosterType": "fullSeason", "season": season}, headers=H, timeout=30).json().get("roster", []):
            ids.add((p["person"]["id"], p["person"]["fullName"], t["name"], p["position"]["abbreviation"]))
    todo = [x for x in ids if str(x[0]) not in have]
    print("MLB: %d players on 2026 rosters, %d to fetch" % (len(ids), len(todo)), flush=True)

    def one(x):
        pid, name, team, pos = x
        out = []
        for grp in (("pitching",) if pos == "P" else ("hitting",)):
            try:
                d = requests.get(S + "/people/%d/stats" % pid, params=dict(stats="gameLog", group=grp, season=season, gameType="R,F,D,L,W"), headers=H, timeout=30).json()
            except Exception:
                continue
            for s in (d.get("stats") or [{}])[0].get("splits", []):
                st = s["stat"]; st["group"] = grp
                out.append(("MLB", "MLB", str(season), s["date"], str(s.get("game", {}).get("gamePk")), str(pid), name, (s.get("team") or {}).get("name", team),
                            (s.get("opponent") or {}).get("name"), int(bool(s.get("isHome"))), st.get("plateAppearances") or st.get("battersFaced"),
                            json.dumps(st)))
        return out
    done = 0
    with ThreadPoolExecutor(8) as ex:
        for rows in ex.map(one, todo):
            put_pg(c, rows); done += 1
            if done % 100 == 0:
                print("  %d / %d" % (done, len(todo)), flush=True)
    print("MLB fetch complete")


def fetch_wnba(c, refresh=False):
    """refresh=True re-pulls every current roster player (INSERT OR IGNORE keeps it idempotent) -- the nightly update
    deletes the last 3 days first, so skipping 'known' players silently dropped their newest games (fixed 2026-10-01)."""
    import _bball as B
    have = set() if refresh else {r[0] for r in c.execute("SELECT DISTINCT player_id FROM player_games WHERE sport='WNBA'")}
    ro = B.roster("wnba")
    todo = [(aid, team, name) for aid, team, name in ro.values() if str(aid) not in have]
    print("WNBA: %d players to fetch" % len(todo), flush=True)

    def one(x):
        aid, team, name = x
        return [("WNBA", "WNBA", str(g["season"]), g["date"], "%s_%s" % (g["date"], g["opp"]), str(aid), name, team, g["opp"], int(bool(g["home"])),
                 g["min"], json.dumps({k: g[k] for k in ("pts", "reb", "ast", "tpm", "post")})) for g in B.logs("wnba", aid)]
    with ThreadPoolExecutor(6) as ex:
        for rows in ex.map(one, todo):
            put_pg(c, rows)
    print("WNBA fetch complete")


def update(c):
    """Nightly: re-run the history pullers (each is resumable and only fetches what's new), then re-import."""
    import subprocess
    for cmd in (["python", "_nhl_hist.py", "fetch"], ["python", "_nhl_hist.py", "build"], ["python", "_soccer_hist.py", "fetch"],
                ["python", "_soccer_hist.py", "build"], ["python", "_bball_card.py", "fetch", "wnba", (datetime.date.today() - datetime.timedelta(days=7)).isoformat(), datetime.date.today().isoformat()],
                ["python", "_bball_card.py", "fetch", "nba", (datetime.date.today() - datetime.timedelta(days=7)).isoformat(), datetime.date.today().isoformat()]):
        print(">", " ".join(cmd), flush=True)
        subprocess.run(cmd)
    imp_nhl(c); imp_soccer(c); imp_bball_teams(c)
    c.execute("DELETE FROM player_games WHERE sport IN ('MLB','WNBA') AND date >= ?", ((datetime.date.today() - datetime.timedelta(days=3)).isoformat(),))
    c.commit()
    fetch_mlb_recent(c); fetch_wnba(c, refresh=True)


def fetch_mlb_recent(c):
    """MLB players who already exist: pull again (their logs are small) -- keeps the season current."""
    c.execute("DELETE FROM player_games WHERE sport='MLB' AND season='2026'"); c.commit()
    fetch_mlb(c)


def stats(c):
    for sp, n, p, d0, d1 in c.execute("SELECT sport, COUNT(*), COUNT(DISTINCT player_id), MIN(date), MAX(date) FROM player_games GROUP BY sport"):
        print("%-7s %8d player-games  %6d players   %s -> %s" % (sp, n, p, d0, d1))
    for sp, n, t in c.execute("SELECT sport, COUNT(*), COUNT(DISTINCT team) FROM team_games GROUP BY sport"):
        print("%-7s %8d team-games    %6d teams" % (sp, n, t))
    print("file: %s (%.0f MB)" % (DB, os.path.getsize(DB) / 1e6))


if __name__ == "__main__":
    a = sys.argv[1:]
    c = con()
    if a[0] == "build":
        imp_nhl(c); imp_soccer(c); imp_nba_players(c); imp_bball_teams(c); imp_nfl(c); stats(c)
    elif a[0] == "fetch-mlb":
        fetch_mlb(c); stats(c)
    elif a[0] == "fetch-wnba":
        fetch_wnba(c); stats(c)
    elif a[0] == "update":
        update(c); stats(c)
    elif a[0] == "stats":
        stats(c)
    elif a[0] == "q":
        for row in c.execute(" ".join(a[1:])):
            print(row)
