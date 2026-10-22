"""NBA NO-BIGS DUNK SCREEN (10/22, user: "Kessler had 10 dunks -- GSW had no bigs, it was lob all night, we need to find more like that").
When a team is missing its bigs, do the OTHER team's bigs dunk / score / make shots more?

    python _nba_dunks.py test        # backtest 2024-25 + 2025-26: dunk-big games vs a depleted frontcourt vs normal
    python _nba_dunks.py [date]      # tonight: which opponents are missing bigs + every PP Dunks / FGM / Points line on the bigs facing them

big        = season reb per 36 >= 9.5 and 15+ min a game (centers / rim bigs)
depleted   = the opponent is missing big minutes: OUT bigs whose season average was 15+ min, summed >= 20 min
dunk big   = a big who averaged 0.8+ dunks a game that season (the lob finishers -- Kessler, Gafford, Lively...)
"""
import sys, json, sqlite3, collections, statistics as st, datetime, urllib.request, time

DB = "sports.db"
CT = datetime.timezone(datetime.timedelta(hours=-5))


def season_profiles(c):
    """per (season, player): games, min/g, reb/36, dunks/g -- from nba_box + nba_qtr"""
    P = {}
    q = """select g.season, b.player, count(*), avg(b.min), sum(b.reb)*36.0/sum(b.min), sum(coalesce(d.dk,0))*1.0/count(*), b.team
           from nba_box b join nba_games g using(game_id)
           left join (select game_id, player_id, sum(dunks) dk from nba_qtr group by 1,2) d on d.game_id=b.game_id and d.player_id=b.player_id
           where g.stype in ('regular','post','play-in') and b.min>0 group by g.season, b.player"""
    for season, pl, n, m, r36, dk, tm in c.execute(q):
        P[(season, pl)] = dict(n=n, min=m or 0, r36=r36 or 0, dk=dk or 0, team=tm)
    return P


def is_big(p):
    return p and p["n"] >= 10 and p["min"] >= 15 and p["r36"] >= 9.5


def depleted_map(c, P):
    """game_id -> {team: big minutes missing}"""
    out = collections.defaultdict(lambda: collections.defaultdict(float))
    for gid, season, tm, pl, status in c.execute("select o.game_id, g.season, o.team, o.player, o.status from nba_out o join nba_games g using(game_id)"):
        if (status or "").lower() != "out":
            continue
        p = P.get((season, pl))
        if is_big(p):
            out[gid][tm] += p["min"]
    return out


def test():
    c = sqlite3.connect(DB, timeout=60)
    P = season_profiles(c); D = depleted_map(c, P)
    rows = c.execute("""select b.game_id, g.season, b.player, b.team, b.opp, b.min, b.pts, b.fgm, b.reb, coalesce(d.dk,0)
                        from nba_box b join nba_games g using(game_id)
                        left join (select game_id, player_id, sum(dunks) dk from nba_qtr group by 1,2) d on d.game_id=b.game_id and d.player_id=b.player_id
                        where g.stype in ('regular','post','play-in') and b.min>=15""").fetchall()
    grp = collections.defaultdict(list)
    for gid, season, pl, tm, opp, m, pts, fgm, reb, dk in rows:
        p = P.get((season, pl))
        if not (is_big(p) and p["dk"] >= 0.8):
            continue
        miss = D.get(gid, {}).get(opp, 0)
        k = "opp missing 20+ big min" if miss >= 20 else "normal"
        grp[k].append((m, dk, fgm, pts, reb, dk - p["dk"], dk >= 2, dk >= 3))
    print("DUNK BIGS (reb/36 >= 9.5, 0.8+ dunks/g), 2024-25 + 2025-26 regular + playoffs, 15+ min games")
    for k in ("normal", "opp missing 20+ big min"):
        g = grp[k]
        if not g:
            continue
        tm = sum(x[0] for x in g)
        print("  %-26s n=%5d | dunks/36 %.2f  FGM/36 %.2f  pts/36 %.1f  reb/36 %.1f | dunks vs own avg %+.2f | 2+ dunks %.0f%%  3+ %.0f%%"
              % (k, len(g), 36 * sum(x[1] for x in g) / tm, 36 * sum(x[2] for x in g) / tm, 36 * sum(x[3] for x in g) / tm, 36 * sum(x[4] for x in g) / tm,
                 st.mean(x[5] for x in g), 100 * st.mean(x[6] for x in g), 100 * st.mean(x[7] for x in g)))
    # significance on the per-game dunk residual
    a = [x[5] for x in grp["opp missing 20+ big min"]]; b = [x[5] for x in grp["normal"]]
    if len(a) > 30:
        se = (st.pvariance(a) / len(a) + st.pvariance(b) / len(b)) ** 0.5
        print("  lift in dunks vs own average: %+.2f per game (t = %.1f)" % (st.mean(a) - st.mean(b), (st.mean(a) - st.mean(b)) / se))


def today(day=None):
    day = day or datetime.datetime.now(CT).date().isoformat()
    c = sqlite3.connect(DB, timeout=60)
    P = season_profiles(c)
    inj = json.load(urllib.request.urlopen(urllib.request.Request("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries",
                                                                  headers={"User-Agent": "Mozilla/5.0"}), timeout=30))
    ab = {r[0]: r[1] for r in c.execute("select distinct player, team from nba_box where date >= '2025-10-01'")}
    missing = collections.defaultdict(list)
    for t in inj.get("injuries", []):
        for i in t.get("injuries", []):
            nm = i["athlete"]["displayName"]; p = P.get(("2025-26", nm))
            if is_big(p) and (i.get("status") or "").lower() in ("out", "doubtful", "day-to-day"):
                missing[t["displayName"]].append((nm, i["status"], round(p["min"]), round(p["r36"], 1)))
    print("BIGS OUT / QUESTIONABLE (2025-26 bigs, 15+ min):")
    for tm, L in missing.items():
        print("  %-24s %s" % (tm, L))
    d = None
    for w in (0, 30, 60):
        time.sleep(w)
        try:
            d = json.load(urllib.request.urlopen(urllib.request.Request("https://partner-api.prizepicks.com/projections?league_id=7&per_page=1000",
                                                                        headers={"User-Agent": "Mozilla/5.0"}), timeout=40)); break
        except Exception as e:
            print("PP retry", e)
    if not d:
        return
    PL = {x["id"]: x["attributes"] for x in d["included"] if x["type"] == "new_player"}
    print("\nPP DUNKS lines tonight (dunk bigs marked):")
    for p in d["data"]:
        a = p["attributes"]
        if a["stat_type"] != "Dunks" or not a["start_time"].startswith(day):
            continue
        pl = PL.get(p["relationships"]["new_player"]["data"]["id"], {}); nm = pl.get("name", "")
        pr = P.get(("2025-26", nm)) or {}
        print("  %-24s %-4s vs %-4s %-8s %4s | 2025-26 dunks/g %.2f  min %.0f  %s"
              % (nm, pl.get("team"), a.get("description"), a["odds_type"], a["line_score"], pr.get("dk", 0), pr.get("min", 0), "BIG" if is_big(pr) else ""))


if __name__ == "__main__":
    a = sys.argv[1:]
    test() if a[:1] == ["test"] else today(a[0] if a else None)
