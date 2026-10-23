"""NBA LINEUPS / SMALL-BALL (10/23, user: "aside from bigs, who plays small -- we can get a real edge"). Rebuilds who is ON THE FLOOR
for every second of every cached game (starters + substitutions in play order, repaired whenever a player who isn't "on" makes a
play), then records each stint's 5-man units and every player's production inside it.

    nba_stints   game, team, period, start/end (seconds into the game), the 5 on the floor, opponent's 5, small (no real big),
                 opp_small, points for/against
    nba_stint_stats  per player per stint: seconds, pts, reb, oreb, ast, fga, dunks

    python _nba_lineups.py build              # parse every cached game (nightly after _nba_season.py ingest)
    python _nba_lineups.py team GS            # small-ball share + most-used units (this season and last)
    python _nba_lineups.py vs_small           # MEASURE: bigs' (and guards') per-36 production when the OPPONENT is small vs not
    python _nba_lineups.py player "Zach Edey" # his per-36 with/without opponent small, his most common partners
"""
import sys, os, re, gzip, json, glob, sqlite3, collections, statistics as st
import _nba_dunks as DK

DB = "sports.db"
RAW = os.path.join("data", "nba_season", "raw")


def schema(c):
    c.executescript("""
    create table if not exists nba_stints(game_id text, date text, season text, team text, opp text, period int, t0 real, t1 real,
        unit text, opp_unit text, small int, opp_small int, pf int, pa int);
    create table if not exists nba_stint_stats(game_id text, season text, team text, opp text, player text, secs real, pts int, reb int, oreb int,
        ast int, fga int, dunks int, opp_small int);
    create table if not exists nba_lineups_done(game_id text primary key);
    create index if not exists ix_ss_player on nba_stint_stats(player, season);
    """)


def gsec(period, clock):
    try:
        if ":" in str(clock):
            m, s = str(clock).split(":"); left = int(m) * 60 + float(s)
        else:
            left = float(clock)
    except Exception:
        return None
    base = 4 * 720 + (period - 5) * 300 if period > 4 else (period - 1) * 720
    length = 300 if period > 4 else 720
    return base + (length - left)


def parse(gid, s, c, BIG):
    comp = (s.get("header") or {}).get("competitions", [{}])[0]
    date = (comp.get("date") or "")[:10]
    if not date:
        return
    y = int(date[:4]); season = "%d-%02d" % (y, (y + 1) % 100) if int(date[5:7]) >= 8 else "%d-%02d" % (y - 1, y % 100)
    tid = {t["id"]: t["team"]["abbreviation"] for t in comp.get("competitors", [])}
    if len(tid) != 2:
        return
    team_of, name, on = {}, {}, collections.defaultdict(set)
    for t in (s.get("boxscore") or {}).get("players", []):
        ab = t["team"]["abbreviation"]
        for a in t["statistics"][0]["athletes"]:
            pid = a["athlete"]["id"]; team_of[pid] = ab; name[pid] = a["athlete"].get("displayName")
            if a.get("starter"):
                on[ab].add(pid)
    teams = list(tid.values())
    opp = {teams[0]: teams[1], teams[1]: teams[0]}
    is_small = lambda ab: not any(name.get(p) in BIG for p in on[ab])
    acc = {}                                        # (team, pid) -> [secs, pts, reb, oreb, ast, fga, dunks, opp_small_secs]
    stints = []; cur = {ab: dict(t0=0.0, pf=0, pa=0) for ab in teams}
    last_t = 0.0; score = {ab: 0 for ab in teams}

    def tick(t):
        nonlocal last_t
        dt = max(0.0, t - last_t)
        for ab in teams:
            os_ = is_small(opp[ab])
            for p in on[ab]:
                a = acc.setdefault((ab, p), [0.0, 0, 0, 0, 0, 0, 0, 0.0])
                a[0] += dt
                if os_:
                    a[7] += dt
        last_t = t

    def close(ab, t, period):
        u = sorted(name.get(p, p) for p in on[ab]); ou = sorted(name.get(p, p) for p in on[opp[ab]])
        if t > cur[ab]["t0"]:
            stints.append((gid, date, season, ab, opp[ab], period, cur[ab]["t0"], t, "|".join(u), "|".join(ou),
                           int(is_small(ab)), int(is_small(opp[ab])), score[ab] - cur[ab]["pf"], score[opp[ab]] - cur[ab]["pa"]))
        cur[ab] = dict(t0=t, pf=score[ab], pa=score[opp[ab]])

    period = 1
    for p in s.get("plays", []):
        per = (p.get("period") or {}).get("number") or period
        t = gsec(per, (p.get("clock") or {}).get("displayValue"))
        if t is None:
            continue
        if per != period:
            period = per
        tick(t)
        typ = (p.get("type") or {}).get("text", ""); txt = p.get("text", "")
        parts = [x["athlete"]["id"] for x in p.get("participants", []) if x.get("athlete")]
        if typ == "Substitution" and len(parts) >= 2:
            pin, pout = parts[0], parts[1]; ab = team_of.get(pin) or team_of.get(pout)
            if ab:
                close(ab, t, per)
                on[ab].discard(pout); on[ab].add(pin)
            continue
        # repair: anyone who makes a play must be on the floor
        for q in parts[:1]:
            ab = team_of.get(q)
            if ab and q not in on[ab]:
                close(ab, t, per)
                if len(on[ab]) >= 5:
                    on[ab].pop()
                on[ab].add(q)
        if parts:
            ab = team_of.get(parts[0])
            if ab:
                a = acc.setdefault((ab, parts[0]), [0.0, 0, 0, 0, 0, 0, 0, 0.0])
                if p.get("shootingPlay") and "Free Throw" not in typ:
                    a[5] += 1
                    if p.get("scoringPlay"):
                        a[1] += int(p.get("scoreValue") or 0)
                        if "Dunk" in typ:
                            a[6] += 1
                        if len(parts) > 1 and "assist" in txt.lower():
                            b = acc.setdefault((ab, parts[1]), [0.0, 0, 0, 0, 0, 0, 0, 0.0]); b[4] += 1
                elif typ.startswith("Free Throw") and p.get("scoringPlay"):
                    a[1] += 1
                elif "Rebound" in typ and "Team" not in typ:
                    a[2] += 1; a[3] += "Offensive" in typ
        if p.get("scoringPlay"):
            h, aw = p.get("homeScore"), p.get("awayScore")
            home = next((tid[k] for k, v in ((x["id"], x.get("homeAway")) for x in comp["competitors"]) if v == "home"), None)
            if home and h is not None:
                score[home] = h; score[opp[home]] = aw
    for ab in teams:
        close(ab, last_t, period)
    c.executemany("insert into nba_stints values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", stints)
    c.executemany("insert into nba_stint_stats values (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  [(gid, season, ab, opp[ab], name.get(pid, pid), a[0], a[1], a[2], a[3], a[4], a[5], a[6], int(a[7] > a[0] / 2))
                   for (ab, pid), a in acc.items() if a[0] > 0])
    c.execute("insert or replace into nba_lineups_done values (?)", (gid,))


def bigs(c):
    P = DK.season_profiles(c)
    return {p for (s, p), v in P.items() if DK.is_big(v)}


def build():
    c = sqlite3.connect(DB, timeout=60); schema(c)
    BIG = bigs(c)
    done = {r[0] for r in c.execute("select game_id from nba_lineups_done")}
    files = [f for f in glob.glob(os.path.join(RAW, "*.json.gz")) if os.path.basename(f).split(".")[0] not in done]
    n = 0
    for f in files:
        gid = os.path.basename(f).split(".")[0]
        try:
            parse(gid, json.load(gzip.open(f, "rt", encoding="utf-8")), c, BIG); n += 1
        except Exception as e:
            print("lineups %s: %s" % (gid, e))
        if n % 200 == 0:
            c.commit()
    c.commit()
    print("lineups built: %d new games | stints %d" % (n, c.execute("select count(*) from nba_stints").fetchone()[0]))


def team(ab):
    c = sqlite3.connect(DB, timeout=60)
    for season in ("2025-26", "2026-27"):
        R = c.execute("select t1-t0, small, unit, pf, pa from nba_stints where team=? and season=?", (ab, season)).fetchall()
        if not R:
            continue
        tot = sum(r[0] for r in R); sm = sum(r[0] for r in R if r[1])
        print("%s %s: SMALL (no real big on the floor) %.0f%% of minutes | net while small %+.1f per 48" %
              (ab, season, 100 * sm / tot, 48 * 60 * sum(r[3] - r[4] for r in R if r[1]) / max(sm, 1)))
        u = collections.Counter()
        for d, smf, unit, *_ in R:
            u[unit] += d
        for unit, d in u.most_common(4):
            print("   %5.0f min  %s" % (d / 60, unit.replace("|", ", ")))


def vs_small():
    c = sqlite3.connect(DB, timeout=60); BIG = bigs(c)
    G = collections.defaultdict(lambda: [0.0, 0, 0, 0, 0])
    for player, secs, pts, reb, oreb, dk, osm in c.execute("select player, secs, pts, reb, oreb, dunks, opp_small from nba_stint_stats where season in ('2024-25','2025-26') and secs>=600"):
        role = "BIG" if player in BIG else "non-big"
        g = G[(role, osm)]; g[0] += secs; g[1] += pts; g[2] += reb; g[3] += oreb; g[4] += dk
    print("PER 36 by OPPONENT lineup (opp small = no real big on the floor for most of his minutes), 2 seasons:")
    for (role, osm), g in sorted(G.items()):
        m = g[0] / 60
        print("  %-7s vs %-11s %7.0f min | pts %.1f reb %.1f oreb %.1f dunks %.2f" % (role, "SMALL opp" if osm else "normal opp", m, 36 * g[1] / m, 36 * g[2] / m, 36 * g[3] / m, 36 * g[4] / m))


def player(nm):
    c = sqlite3.connect(DB, timeout=60)
    for osm in (0, 1):
        r = c.execute("select sum(secs), sum(pts), sum(reb), sum(oreb), sum(ast), sum(dunks), count(*) from nba_stint_stats where player=? and opp_small=?", (nm, osm)).fetchone()
        if r[0]:
            m = r[0] / 60
            print("%s vs %s: %d games, %.0f min | per 36: pts %.1f reb %.1f oreb %.1f ast %.1f dunks %.2f" % (nm, "SMALL opp" if osm else "normal opp", r[6], m, 36 * r[1] / m, 36 * r[2] / m, 36 * r[3] / m, 36 * r[4] / m, 36 * r[5] / m))
    pr = collections.Counter()
    for unit, d in c.execute("select unit, t1-t0 from nba_stints where unit like ?", ("%" + nm + "%",)):
        for x in unit.split("|"):
            if x != nm:
                pr[x] += d
    print("most minutes with:", ", ".join("%s %.0f" % (k, v / 60) for k, v in pr.most_common(5)))


if __name__ == "__main__":
    a = sys.argv[1:]
    {"build": build, "vs_small": vs_small}.get(a[0] if a else "", lambda: None)() if a and a[0] in ("build", "vs_small") else None
    if a[:1] == ["team"]:
        team(a[1])
    elif a[:1] == ["player"]:
        player(a[1])
    elif not a:
        print(__doc__)
