"""CBB SEASON DATABASE (11/5, user: "we gotta make one for cbb now"). Men's D-I, ESPN game summaries (free) -> sports.db:

    cbb_games   game: date, season, stype, home, away, scores, possessions, closing spread/total (pickcenter)
    cbb_box     player-game: starter, minutes, FGM/FGA, 3PM/3PA, FTM/FTA, OREB/DREB/REB, AST, STL, BLK, TO, PF, PTS, DNP
Same layout as nba_games/nba_box (reuses _nba_season helpers). Raw summaries cached in data/cbb_season/raw/.

    python _cbb_season.py ingest 2026-11-03             # one date (nightly: yesterday)
    python _cbb_season.py ingest 2025-11-03 2026-04-07  # last season backfill (~6k games)
    python _cbb_season.py status
"""
import sys, os, json, gzip, sqlite3, datetime
from concurrent.futures import ThreadPoolExecutor
import _nba_season as N

RAW = os.path.join("data", "cbb_season", "raw"); os.makedirs(RAW, exist_ok=True)
DB = "sports.db"
BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball"


def schema(c):
    c.executescript("""
    create table if not exists cbb_games(game_id text primary key, date text, season text, stype text, home text, away text, home_pts int, away_pts int,
        poss real, spread real, total real, status text);
    create table if not exists cbb_box(game_id text, date text, team text, opp text, home int, player_id text, player text, starter int, min real,
        fgm int, fga int, tpm int, tpa int, ftm int, fta int, oreb int, dreb int, reb int, ast int, stl int, blk int, tov int, pf int, pts int,
        dnp text, primary key(game_id, player_id));
    create index if not exists ix_cbb_player on cbb_box(player, date);
    """)


def summary(gid):
    f = os.path.join(RAW, "%s.json.gz" % gid)
    if os.path.exists(f):
        try:
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:                               # 11/6: half-written file from a killed run -> refetch
            os.remove(f)
    s = N.get("%s/summary?event=%s" % (BASE, gid))
    if s and s.get("boxscore", {}).get("players"):
        json.dump(s, gzip.open(f, "wt", encoding="utf-8"))
    return s


def parse(gid, date, stype, s, c):
    comp = (s.get("header") or {}).get("competitions", [{}])[0]
    teams = {t["id"]: t for t in comp.get("competitors", [])}
    home = next((t for t in teams.values() if t.get("homeAway") == "home"), {}); away = next((t for t in teams.values() if t.get("homeAway") == "away"), {})
    ab = {tid: t["team"].get("abbreviation") for tid, t in teams.items()}
    poss = []
    for t in s["boxscore"].get("teams", []):
        S = {x["name"]: x.get("displayValue") for x in t.get("statistics", [])}
        fga = N.ma(S.get("fieldGoalsMade-fieldGoalsAttempted"))[1]; fta = N.ma(S.get("freeThrowsMade-freeThrowsAttempted"))[1]
        try:
            poss.append(fga + 0.44 * fta - float(S.get("offensiveRebounds") or 0) + float(S.get("totalTurnovers") or S.get("turnovers") or 0))
        except Exception:
            pass
    pc = (s.get("pickcenter") or [{}]); pc = pc[0] if pc else {}
    c.execute("insert or replace into cbb_games values (?,?,?,?,?,?,?,?,?,?,?,?)",
              (gid, date, N.season_of(date), stype, ab.get(home.get("id")), ab.get(away.get("id")), int(home.get("score") or 0), int(away.get("score") or 0),
               sum(poss) / len(poss) if poss else None, pc.get("spread"), pc.get("overUnder"), comp.get("status", {}).get("type", {}).get("name")))
    for t in s["boxscore"]["players"]:
        tm = t["team"].get("abbreviation"); tid = t["team"].get("id")
        if not tid:
            continue
        opp = next((ab[x] for x in ab if x != tid), None)
        if not t.get("statistics"):
            continue
        st = t["statistics"][0]; lab = st["labels"]
        for a in st["athletes"]:
            d = dict(zip(lab, a.get("stats") or [])); pid = a["athlete"]["id"]
            fgm, fga = N.ma(d.get("FG")); tpm, tpa = N.ma(d.get("3PT")); ftm, fta = N.ma(d.get("FT"))
            n = lambda k: int(str(d.get(k) or 0).replace("+", "")) if str(d.get(k) or "0").lstrip("+-").isdigit() else 0
            c.execute("insert or replace into cbb_box values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (gid, date, tm, opp, int(tid == home.get("id")), pid, a["athlete"]["displayName"], int(bool(a.get("starter"))),
                       float(d.get("MIN") or 0) if str(d.get("MIN") or "0").replace(".", "").isdigit() else 0.0,
                       fgm, fga, tpm, tpa, ftm, fta, n("OREB"), n("DREB"), n("REB"), n("AST"), n("STL"), n("BLK"), n("TO"), n("PF"), n("PTS"),
                       a.get("reason") if a.get("didNotPlay") else None))


def events(day):
    sb = N.get("%s/scoreboard?dates=%s&groups=50&limit=400" % (BASE, day.replace("-", "")))
    out = []
    for e in (sb or {}).get("events", []):
        if e["status"]["type"]["state"] == "post":
            out.append((e["id"], day, {2: "regular", 3: "post"}.get((e.get("season") or {}).get("type"), str((e.get("season") or {}).get("type")))))
    return out


def ingest(d0, d1=None):
    d1 = d1 or d0
    c = sqlite3.connect(DB, timeout=60); schema(c)
    days = []; d = datetime.date.fromisoformat(d0)
    while d <= datetime.date.fromisoformat(d1):
        days.append(d.isoformat()); d += datetime.timedelta(days=1)
    with ThreadPoolExecutor(6) as ex:
        evs = [e for lst in ex.map(events, days) for e in lst]
    done = {r[0] for r in c.execute("select game_id from cbb_games")}
    todo = [e for e in evs if e[0] not in done]
    print("%s..%s: %d finished games, %d new" % (d0, d1, len(evs), len(todo)), flush=True)
    n = 0
    with ThreadPoolExecutor(8) as ex:
        for (gid, day, stype), s in zip(todo, ex.map(lambda e: summary(e[0]), todo)):
            if not s or not s.get("boxscore", {}).get("players"):
                continue
            try:
                parse(gid, day, stype, s, c); n += 1
            except Exception as e:
                print("parse %s: %s" % (gid, e))
            if n % 25 == 0:
                c.commit()                                  # 11/5: short write locks so screens can read mid-backfill
            if n % 500 == 0:
                print("  %d games stored (%s)" % (n, day), flush=True)
    c.commit()
    print("stored %d games" % n)


def status():
    c = sqlite3.connect(DB, timeout=60); schema(c)
    for row in c.execute("select season, stype, count(*), min(date), max(date) from cbb_games group by season, stype order by season"):
        print(row)
    print("box rows %d" % c.execute("select count(*) from cbb_box").fetchone())


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["ingest"]:
        ingest(a[1], a[2] if len(a) > 2 else None)
    else:
        status()
