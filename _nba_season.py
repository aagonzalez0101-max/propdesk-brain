"""NBA SEASON DATABASE (10/21, user: "every day of the season read and look into each game -- paces, game reports, each player in depth,
how teams fare vs ranks; if we did that last season I would've been crazy"). ESPN game summaries (free) -> sports.db, every game:

    nba_games     game: date, season, teams, score, possessions/pace, officials, closing spread/total (pickcenter)
    nba_box       player-game: starter, minutes, FGM/FGA, 3PM/3PA, FTM/FTA, OREB/DREB/REB, AST, STL, BLK, TO, PF, +/-, PTS, DNP reason
    nba_qtr       player x quarter (from play-by-play): points, FGA, FGM, 3PA, rebounds, assists, dunks made -- 1Q / 1H lines
    nba_out       who was OUT for each team that night (summary injuries) -- with/without splits and role changes
Raw summaries are cached gzipped in data/nba_season/raw/ so anything new can be re-derived without re-downloading.

    python _nba_season.py ingest 2026-10-20            # one date (nightly job: yesterday)
    python _nba_season.py ingest 2025-10-21 2026-06-20 # a range (last season backfill)
    python _nba_season.py status
"""
import sys, os, json, gzip, time, sqlite3, datetime, re, collections
import urllib.request
from concurrent.futures import ThreadPoolExecutor

RAW = os.path.join("data", "nba_season", "raw"); os.makedirs(RAW, exist_ok=True)
DB = "sports.db"
BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"


def get(url, tries=4):
    for k in range(tries):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=40))
        except Exception:
            time.sleep(2 + 4 * k)
    return None


def schema(c):
    c.executescript("""
    create table if not exists nba_games(game_id text primary key, date text, season text, stype text, home text, away text, home_pts int, away_pts int,
        poss real, officials text, spread real, total real, fav text, status text);
    create table if not exists nba_box(game_id text, date text, team text, opp text, home int, player_id text, player text, starter int, min real,
        fgm int, fga int, tpm int, tpa int, ftm int, fta int, oreb int, dreb int, reb int, ast int, stl int, blk int, tov int, pf int, pm int, pts int,
        dnp text, primary key(game_id, player_id));
    create table if not exists nba_qtr(game_id text, player_id text, period int, pts int, fga int, fgm int, tpa int, reb int, ast int, dunks int,
        primary key(game_id, player_id, period));
    create table if not exists nba_out(game_id text, team text, player text, status text, detail text, primary key(game_id, team, player));
    create index if not exists ix_box_player on nba_box(player, date);
    """)


def ma(x):
    try:
        m, a = str(x).split("-"); return int(m), int(a)
    except Exception:
        return 0, 0


def season_of(d):
    y = int(d[:4]); return "%d-%02d" % (y, (y + 1) % 100) if int(d[5:7]) >= 8 else "%d-%02d" % (y - 1, y % 100)


def summary(gid):
    f = os.path.join(RAW, "%s.json.gz" % gid)
    if os.path.exists(f):
        return json.load(gzip.open(f, "rt", encoding="utf-8"))
    s = get("%s/summary?event=%s" % (BASE, gid))
    if s and s.get("boxscore", {}).get("players"):
        json.dump(s, gzip.open(f, "wt", encoding="utf-8"))
    return s


def parse(gid, date, stype, s, c):
    comp = (s.get("header") or {}).get("competitions", [{}])[0]
    teams = {t["id"]: t for t in comp.get("competitors", [])}
    home = next((t for t in teams.values() if t.get("homeAway") == "home"), {}); away = next((t for t in teams.values() if t.get("homeAway") == "away"), {})
    ab = {tid: t["team"]["abbreviation"] for tid, t in teams.items()}
    # team possessions from the team box: FGA + 0.44 FTA - OREB + TO, averaged over both sides
    poss = []
    for t in s["boxscore"].get("teams", []):
        S = {x["name"]: x.get("displayValue") for x in t.get("statistics", [])}
        fga = ma(S.get("fieldGoalsMade-fieldGoalsAttempted"))[1]; fta = ma(S.get("freeThrowsMade-freeThrowsAttempted"))[1]
        try:
            poss.append(fga + 0.44 * fta - float(S.get("offensiveRebounds") or 0) + float(S.get("totalTurnovers") or S.get("turnovers") or 0))
        except Exception:
            pass
    pc = (s.get("pickcenter") or [{}])
    pc = pc[0] if pc else {}
    officials = [o.get("displayName") for o in (s.get("gameInfo") or {}).get("officials", [])]
    c.execute("insert or replace into nba_games values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (gid, date, season_of(date), stype, ab.get(home.get("id")), ab.get(away.get("id")), int(home.get("score") or 0), int(away.get("score") or 0),
               sum(poss) / len(poss) if poss else None, json.dumps(officials), pc.get("spread"), pc.get("overUnder"),
               ((pc.get("homeTeamOdds") or {}).get("favorite") and ab.get(home.get("id"))) or ((pc.get("awayTeamOdds") or {}).get("favorite") and ab.get(away.get("id"))),
               comp.get("status", {}).get("type", {}).get("name")))
    pid_team = {}
    for t in s["boxscore"]["players"]:
        tm = t["team"]["abbreviation"]; tid = t["team"]["id"]
        opp = next((ab[x] for x in ab if x != tid), None)
        st = t["statistics"][0]; lab = st["labels"]
        for a in st["athletes"]:
            d = dict(zip(lab, a.get("stats") or [])); pid = a["athlete"]["id"]; pid_team[pid] = tm
            fgm, fga = ma(d.get("FG")); tpm, tpa = ma(d.get("3PT")); ftm, fta = ma(d.get("FT"))
            n = lambda k: int(str(d.get(k) or 0).replace("+", "")) if str(d.get(k) or "0").lstrip("+-").isdigit() else 0
            c.execute("insert or replace into nba_box values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (gid, date, tm, opp, int(tid == home.get("id")), pid, a["athlete"]["displayName"], int(bool(a.get("starter"))),
                       float(d.get("MIN") or 0) if str(d.get("MIN") or "0").replace(".", "").isdigit() else 0.0,
                       fgm, fga, tpm, tpa, ftm, fta, n("OREB"), n("DREB"), n("REB"), n("AST"), n("STL"), n("BLK"), n("TO"), n("PF"), n("+/-"), n("PTS"),
                       a.get("reason") if a.get("didNotPlay") else None))
    # play-by-play -> quarter splits
    Q = collections.defaultdict(lambda: [0, 0, 0, 0, 0, 0, 0])      # pts fga fgm tpa reb ast dunks
    for p in s.get("plays", []):
        per = (p.get("period") or {}).get("number"); parts = [x["athlete"]["id"] for x in p.get("participants", []) if x.get("athlete")]
        if not per or not parts:
            continue
        typ = (p.get("type") or {}).get("text", ""); txt = p.get("text", "")
        shooter = parts[0]
        if p.get("shootingPlay") and "Free Throw" not in typ:
            q = Q[(shooter, per)]; q[1] += 1
            if "three point" in txt.lower() or (p.get("pointsAttempted") == 3):
                q[3] += 1
            if p.get("scoringPlay"):
                q[2] += 1
                if "Dunk" in typ:
                    q[6] += 1
                if len(parts) > 1:
                    Q[(parts[1], per)][5] += 1                      # the assister
        if p.get("scoringPlay"):
            Q[(shooter, per)][0] += int(p.get("scoreValue") or 0)
        if "Rebound" in typ and "Team" not in typ:
            Q[(shooter, per)][4] += 1
    for (pid, per), q in Q.items():
        if pid in pid_team:
            c.execute("insert or replace into nba_qtr values (?,?,?,?,?,?,?,?,?,?)", (gid, pid, per, *q))
    for t in s.get("injuries", []) or []:
        tm = (t.get("team") or {}).get("abbreviation")
        for i in t.get("injuries", []):
            c.execute("insert or replace into nba_out values (?,?,?,?,?)", (gid, tm, (i.get("athlete") or {}).get("displayName"), i.get("status"),
                                                                           ((i.get("details") or {}).get("type") or i.get("shortComment") or "")[:120]))


def events(day):
    sb = get("%s/scoreboard?dates=%s" % (BASE, day.replace("-", "")))
    out = []
    for e in (sb or {}).get("events", []):
        if e["status"]["type"]["state"] == "post":
            out.append((e["id"], day, {1: "pre", 2: "regular", 3: "post", 5: "play-in"}.get((e.get("season") or {}).get("type"), str((e.get("season") or {}).get("type")))))
    return out


def ingest(d0, d1=None):
    d1 = d1 or d0
    c = sqlite3.connect(DB, timeout=60); schema(c)
    days = []
    d = datetime.date.fromisoformat(d0)
    while d <= datetime.date.fromisoformat(d1):
        days.append(d.isoformat()); d += datetime.timedelta(days=1)
    with ThreadPoolExecutor(6) as ex:
        evs = [e for lst in ex.map(events, days) for e in lst]
    done = {r[0] for r in c.execute("select game_id from nba_games")}
    todo = [e for e in evs if e[0] not in done]
    print("%s..%s: %d finished games, %d new" % (d0, d1, len(evs), len(todo)), flush=True)
    n = 0
    with ThreadPoolExecutor(6) as ex:
        for (gid, day, stype), s in zip(todo, ex.map(lambda e: summary(e[0]), todo)):
            if not s or not s.get("boxscore", {}).get("players"):
                continue
            try:
                parse(gid, day, stype, s, c); n += 1
            except Exception as e:
                print("parse %s: %s" % (gid, e))
            if n % 50 == 0:
                c.commit(); print("  %d games stored (%s)" % (n, day), flush=True)
    c.commit()
    print("stored %d games" % n)


def status():
    c = sqlite3.connect(DB, timeout=60); schema(c)
    for row in c.execute("select season, stype, count(*), min(date), max(date) from nba_games group by season, stype order by season"):
        print(row)
    print("box rows %d | quarter rows %d | outs %d" % tuple(c.execute("select (select count(*) from nba_box),(select count(*) from nba_qtr),(select count(*) from nba_out)").fetchone()))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["ingest"]:
        ingest(a[1], a[2] if len(a) > 2 else None)
    else:
        status()
