"""NBA PLAY-BY-PLAY STYLE DB (10/23, user: "read the play by play for each game and log it all -- know how each player plays, not just
a number stat on ESPN"). Every cached ESPN summary (data/nba_season/raw, filled nightly by _nba_season.py) is parsed into:

    nba_shots   every FG attempt: player, team, opp, quarter, clock, shot TYPE (cutting dunk / alley oop / driving layup / tip /
                step-back / pull-up / hook / floater / catch-and-shoot three...), class (dunk, lob, putback, rim, floater, mid, three),
                distance, made, assisted_by (the passer), court x/y
    nba_events  rebounds (off/def), turnovers, fouls committed, shooting fouls drawn (free-throw trips), substitutions in/out

    python _nba_pbp.py build                 # parse every cached game not parsed yet (nightly after _nba_season.py ingest)
    python _nba_pbp.py profile "Zach Edey"   # how he scores: shot mix, lobs, putbacks, who feeds him, FT trips, by-quarter role,
                                             # and the same splits vs no-big lineups / vs this opponent
"""
import sys, os, re, gzip, json, glob, sqlite3, collections, statistics as st

DB = "nba_pbp.db"          # 10/23: laptop-only file (173 MB) -- kept out of sports.db so the cloud bundle stays small
RAW = os.path.join("data", "nba_season", "raw")


def schema(c):
    c.executescript("""
    create table if not exists nba_shots(game_id text, date text, season text, period int, clock real, player_id text, player text, team text, opp text,
        type text, cls text, dist real, made int, pts int, assist_id text, assist text, x real, y real, primary key(game_id, period, clock, player_id, type));
    create table if not exists nba_events(game_id text, date text, period int, clock real, kind text, player_id text, player text, team text, other_id text,
        other text, detail text);
    create table if not exists nba_pbp_done(game_id text primary key);
    create index if not exists ix_shots_player on nba_shots(player, date);
    create index if not exists ix_events_player on nba_events(player, kind);
    """)


def secs(clock):
    try:
        m, s = str(clock).split(":"); return int(m) * 60 + float(s)
    except Exception:
        try:
            return float(clock)
        except Exception:
            return None


def shot_class(typ, text, pts_att):
    t = (typ or "").lower(); x = (text or "").lower()
    if "three point" in x:                                       # 10/23: pointsAttempted=3 also tags and-ones (Kessler "threes")
        return "three"
    if "alley oop" in t and "dunk" in t:
        return "lob dunk"
    if "dunk" in t:
        return "dunk"
    if "tip" in t or "putback" in t:
        return "putback"
    if "alley oop" in t:
        return "lob layup"
    if "layup" in t or "finger roll" in t:
        return "rim"
    if "hook" in t:
        return "hook"
    if "float" in t:
        return "floater"
    return "mid"


def parse(gid, s, c):
    comp = (s.get("header") or {}).get("competitions", [{}])[0]
    teams = {t["id"]: t["team"]["abbreviation"] for t in comp.get("competitors", [])}
    date = (comp.get("date") or "")[:10]
    season = "%d-%02d" % (int(date[:4]), (int(date[:4]) + 1) % 100) if date and int(date[5:7]) >= 8 else ("%d-%02d" % (int(date[:4]) - 1, int(date[:4]) % 100) if date else "")
    names = {}
    for t in (s.get("boxscore") or {}).get("players", []):
        for a in t["statistics"][0]["athletes"]:
            names[a["athlete"]["id"]] = (a["athlete"]["displayName"], t["team"]["abbreviation"])
    opp_of = lambda tm: next((v for v in teams.values() if v != tm), None)
    for p in s.get("plays", []):
        typ = (p.get("type") or {}).get("text", ""); txt = p.get("text", "")
        per = (p.get("period") or {}).get("number"); clk = secs((p.get("clock") or {}).get("displayValue"))
        parts = [x["athlete"]["id"] for x in p.get("participants", []) if x.get("athlete")]
        if not parts:
            continue
        pid = parts[0]; nm, tm = names.get(pid, (None, teams.get((p.get("team") or {}).get("id"))))
        if p.get("shootingPlay") and "Free Throw" not in typ:
            dist = re.search(r"(\d+)-foot", txt)
            ast = parts[1] if (len(parts) > 1 and p.get("scoringPlay") and "assist" in txt.lower()) else None
            co = p.get("coordinate") or {}
            c.execute("insert or replace into nba_shots values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (gid, date, season, per, clk, pid, nm, tm, opp_of(tm), typ, shot_class(typ, txt, p.get("pointsAttempted")),
                       float(dist.group(1)) if dist else None, int(bool(p.get("scoringPlay"))), int(p.get("pointsAttempted") or 0),
                       ast, names.get(ast, (None,))[0] if ast else None,
                       co.get("x") if abs(co.get("x") or 0) < 1e6 else None, co.get("y") if abs(co.get("y") or 0) < 1e6 else None))
            continue
        kind = None; other = parts[1] if len(parts) > 1 else None
        if "Rebound" in typ and "Team" not in typ:
            kind = "oreb" if "Offensive" in typ else "dreb"
        elif "Turnover" in typ or "Traveling" in typ:
            kind = "tov"
        elif typ.startswith("Free Throw"):
            kind = "ft" + ("_made" if p.get("scoringPlay") else "_miss")
        elif "Shooting Foul" in typ:
            kind = "shooting_foul"                                  # parts[0] = fouler; the shooter shows up on the free throws
        elif "Foul" in typ:
            kind = "foul"
        elif typ == "Substitution":
            kind = "sub_in"                                         # parts[0] enters, parts[1] leaves
        if kind:
            c.execute("insert into nba_events values (?,?,?,?,?,?,?,?,?,?,?)",
                      (gid, date, per, clk, kind, pid, nm, tm, other, names.get(other, (None,))[0] if other else None, typ))
    c.execute("insert or replace into nba_pbp_done values (?)", (gid,))


def build():
    if os.environ.get("PROPDESK_CLOUD"):
        print("play-by-play: laptop only (nba_pbp.db is not in the cloud bundle)"); return
    c = sqlite3.connect(DB, timeout=60); schema(c)
    done = {r[0] for r in c.execute("select game_id from nba_pbp_done")}
    files = [f for f in glob.glob(os.path.join(RAW, "*.json.gz")) if os.path.basename(f).split(".")[0] not in done]
    n = 0
    for f in files:
        gid = os.path.basename(f).split(".")[0]
        try:
            parse(gid, json.load(gzip.open(f, "rt", encoding="utf-8")), c); n += 1
        except Exception as e:
            print("parse %s: %s" % (gid, e))
        if n % 200 == 0:
            c.commit()
    c.commit()
    print("play-by-play parsed: %d new games | shots %d | events %d" % (n, c.execute("select count(*) from nba_shots").fetchone()[0],
                                                                   c.execute("select count(*) from nba_events").fetchone()[0]))


def profile(name, season="2025-26", opp=None):
    c = sqlite3.connect(DB, timeout=60)
    S = c.execute("select game_id, cls, made, assist, period, opp, dist from nba_shots where player=? and season=?", (name, season)).fetchall()
    cur = c.execute("select game_id, cls, made, assist, period, opp, dist from nba_shots where player=? and season='2026-27'", (name,)).fetchall()
    if not S and not cur:
        print("no play-by-play for", name); return
    def mix(X, label):
        if not X:
            return
        g = len({x[0] for x in X}); cl = collections.Counter(x[1] for x in X); mk = collections.Counter(x[1] for x in X if x[2])
        ast = sum(1 for x in X if x[2] and x[3]); made = sum(x[2] for x in X)
        print("  %s (%d games): %.1f FGA/g | %s" % (label, g, len(X) / g, " ".join("%s %.1f/g (%.0f%%)" % (k, cl[k] / g, 100 * mk[k] / cl[k]) for k in
              ("lob dunk", "dunk", "putback", "rim", "lob layup", "hook", "floater", "mid", "three") if cl[k])))
        print("     assisted on %.0f%% of makes | top passers: %s" % (100 * ast / max(made, 1), ", ".join("%s %d" % kv for kv in collections.Counter(x[3] for x in X if x[3]).most_common(3))))
        q = collections.Counter(x[4] for x in X)
        print("     shots by quarter: %s" % " ".join("Q%d %.0f%%" % (k, 100 * q[k] / len(X)) for k in sorted(q) if k <= 4))
    print("PLAY-BY-PLAY PROFILE: %s" % name)
    mix(S, season)
    mix(cur, "2026-27")
    if opp:
        mix([x for x in S + cur if x[5] == opp], "vs %s" % opp)
    E = c.execute("select kind, count(*), count(distinct game_id) from nba_events where player=? and date between ? and ? group by kind",
                  (name, season[:4] + "-10-01", str(int(season[:4]) + 1) + "-08-01")).fetchall()
    ev = {k: (n, g) for k, n, g in E}
    if ev:
        g = max(v[1] for v in ev.values())
        print("  per game: oreb %.1f  dreb %.1f  FT made %.1f / missed %.1f  TO %.1f  fouls %.1f" % tuple(ev.get(k, (0, 1))[0] / g for k in ("oreb", "dreb", "ft_made", "ft_miss", "tov", "foul")))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["build"]:
        build()
    elif a[:1] == ["profile"]:
        profile(a[1], opp=a[2] if len(a) > 2 else None)
    else:
        print(__doc__)
