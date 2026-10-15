"""MARKET HISTORY (10/15, user: "a lot of the markets have no history, get that up ASAP").
Grades EVERY archived PrizePicks standard line (lines.db, since 9/30) against the real result (sports.db): for each player + stat + game
day, the OPENING line (first seen) and the CLOSING line (last seen) -> over / under / push. Gives every market a base rate today, and
every future rule a ready-made backtest set.

    python _history.py build      # (re)grade everything -> pp_history.jsonl
    python _history.py report     # hit rates per league x stat (opening line), n >= 30
"""
import sys, os, re, json, sqlite3, datetime, collections

OUT = "pp_history.jsonl"
SPORT = {9: "NFL", 15: "CFB", 8: "NHL", 82: "SOCCER", 7: "NBA", 3: "WNBA", 2: "MLB"}
# PP stat -> list of sports.db keys summed (per sport)
STAT = {
    "NFL": {"Receiving Yards": ["receiving_yards"], "Rush Yards": ["rushing_yards"], "Pass Yards": ["passing_yards"], "Receptions": ["receptions"],
            "Rush Attempts": ["carries"], "Rec Targets": ["targets"], "Pass Attempts": ["attempts"], "Pass Completions": ["completions"],
            "Rush+Rec Yds": ["rushing_yards", "receiving_yards"], "Pass+Rush Yds": ["passing_yards", "rushing_yards"], "Pass TDs": ["passing_tds"]},
    "CFB": {"Receiving Yards": ["rec_yds"], "Rush Yards": ["rush_yds"], "Pass Yards": ["pass_yds"], "Receptions": ["rec"], "Rush Attempts": ["carries"],
            "Pass Attempts": ["att"], "Pass Completions": ["cmp"], "Rush+Rec Yds": ["rush_yds", "rec_yds"], "Pass+Rush Yds": ["pass_yds", "rush_yds"]},
    "NHL": {"Shots On Goal": ["sog"], "Points": ["points"], "Assists": ["assists"], "Goals": ["goals"], "Hits": ["hits"], "Blocked Shots": ["blocks"],
            "Goalie Saves": ["saves"], "Power Play Points": ["pp_goals"]},
    "SOCCER": {"Passes Attempted": ["passes"], "Goalie Saves": ["saves"], "Shots": ["shots"], "Shots On Target": ["sot"]},
    "NBA": {"Points": ["pts"], "Rebounds": ["reb"], "Assists": ["ast"], "3-PT Made": ["tpm"], "Pts+Rebs+Asts": ["pts", "reb", "ast"], "Pts+Rebs": ["pts", "reb"],
            "Pts+Asts": ["pts", "ast"], "Rebs+Asts": ["reb", "ast"], "Steals": ["stl"], "Blocked Shots": ["blk"], "Turnovers": ["to"], "Blks+Stls": ["blk", "stl"]},
    "MLB": {"Hits": ["hits"], "Total Bases": ["totalBases"], "Hits+Runs+RBIs": ["hits", "runs", "rbi"], "Runs": ["runs"], "RBIs": ["rbi"],
            "Pitcher Strikeouts": ["strikeOuts"], "Walks": ["baseOnBalls"]},
}
STAT["WNBA"] = {k: v for k, v in STAT["NBA"].items() if all(x in ("pts", "reb", "ast", "tpm") for x in v)}
norm = lambda s: re.sub(r"[^a-z]", "", (s or "").lower().replace("jr.", "").replace(" iii", "").replace(" ii", ""))


def short(name):
    """'Vasily Podkolzin' -> 'vpodkolzin' (NHL rows are 'V. Podkolzin')"""
    p = (name or "").replace(".", " ").split()
    return norm(p[0][:1] + p[-1]) if len(p) >= 2 else norm(name)


def nfl_week(day):
    return "W%02d" % (1 + (datetime.date.fromisoformat(day) - datetime.date(2026, 9, 8)).days // 7)


def build():
    L = sqlite3.connect("lines.db"); S = sqlite3.connect("sports.db")
    # actuals index: (sport, key, day) -> stats ; key = full norm name and short name
    idx = {}
    for sp in set(SPORT.values()):
        q = "select player, date, game_id, stats from player_games where sport=? and (date >= '2026-09-25' or date like 'W%%')"
        for pl, d, gid, st in S.execute(q, (sp,)):
            if sp == "NFL" and not str(gid).startswith("2026_"):
                continue
            s = json.loads(st)
            for k in {norm(pl), short(pl)}:
                idx[(sp, k, d)] = s
    rows = collections.defaultdict(list)
    for lg, pl, team, stat, line, start, fs, ls in L.execute(
            "select league, player, team, stat, line, start, first_seen, last_seen from pp where kind='standard' and league in (%s)" % ",".join(map(str, SPORT))):
        sp = SPORT[lg]
        if stat not in STAT[sp] or not start:
            continue
        day = datetime.datetime.fromisoformat(start).astimezone(datetime.timezone(datetime.timedelta(hours=-5))).date().isoformat()
        rows[(sp, pl, team, stat, day)].append((fs, ls, float(line)))
    n = 0
    with open(OUT, "w", encoding="utf-8") as f:
        for (sp, pl, team, stat, day), v in rows.items():
            v.sort()
            op, cl = v[0][2], max(v, key=lambda x: x[1])[2]
            dkey = nfl_week(day) if sp == "NFL" else day
            s = None
            for d_ in ([dkey] if sp == "NFL" else [day, (datetime.date.fromisoformat(day) + datetime.timedelta(days=1)).isoformat()]):
                s = idx.get((sp, norm(pl), d_)) or idx.get((sp, short(pl), d_))
                if s:
                    break
            if not s:
                continue
            vals = [s.get(k) for k in STAT[sp][stat]]
            if any(x is None for x in vals):
                continue
            act = sum(float(x) for x in vals)
            res = lambda ln: "push" if act == ln else ("over" if act > ln else "under")
            f.write(json.dumps(dict(sport=sp, player=pl, team=team, stat=stat, day=day, open=op, close=cl, actual=act,
                                    res_open=res(op), res_close=res(cl), moves=len({x[2] for x in v})), ensure_ascii=False) + "\n")
            n += 1
    print("graded %d PP standard lines -> %s" % (n, OUT))


def report(min_n=30):
    R = [json.loads(x) for x in open(OUT, encoding="utf-8") if x.strip()]
    g = collections.defaultdict(lambda: [0, 0, 0])
    for r in R:
        k = (r["sport"], r["stat"]); g[k][0] += r["res_open"] == "over"; g[k][1] += r["res_open"] == "under"
        g[k][2] += (r["close"] != r["open"]) and ((r["close"] > r["open"]) == (r["res_open"] == "over"))
    print("%-7s %-18s %5s %7s %7s" % ("sport", "stat", "n", "OVER%", "UNDER%"))
    for (sp, st), (o, u, mv) in sorted(g.items(), key=lambda x: (x[0][0], -(x[1][0] + x[1][1]))):
        n = o + u
        if n >= min_n:
            print("%-7s %-18s %5d %6.1f%% %6.1f%%%s" % (sp, st, n, 100 * o / n, 100 * u / n, "   <-- 57.7%+ side" if max(o, u) / n >= 0.577 else ""))
    # line moves: does the direction PP moves the line predict the result?
    mv = [r for r in R if r["close"] != r["open"]]
    agree = sum((r["close"] > r["open"]) == (r["res_open"] == "over") for r in mv if r["res_open"] != "push")
    tot = sum(1 for r in mv if r["res_open"] != "push")
    if tot:
        print("\nLINE MOVES: %d lines moved after opening; the result went the way PP moved it %d times (%.1f%%)" % (tot, agree, 100 * agree / tot))


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "report"
    if a == "build":
        build()
    report()
