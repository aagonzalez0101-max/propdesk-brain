"""GOBLIN SCREENER (11/23, user: "build the goblin screener and backtest it" -- goblins as a bankroll builder).
Every archived PP goblin closing line (NBA league 7, NHL league 8), graded on the box score. AS-OF features (games before that day):
    own   his hit rate at the goblin number this season (n >= 5)        l10  hit rate over his last 10
    min   lowest value in his last 10 (a goblin under his floor never needs a career night)
    gap   standard line - goblin line (how deep the goblin is)          stat / sport
A slice is a builder only if it hits >= 80% in BOTH halves (n >= 40 each) -- a 1.7x goblin pair needs ~77% per leg.
    python _goblin_screen.py backtest
    python _goblin_screen.py today          # today's goblins that sit in a passing slice
"""
import sys, json, sqlite3, datetime, collections, statistics
import _stack as S

CT = S.CT
STATS = {"Points", "Rebounds", "Assists", "3-PT Made", "Pts+Rebs+Asts", "Pts+Rebs", "Pts+Asts", "Rebs+Asts", "Shots On Goal"}


def logs():
    c = sqlite3.connect("sports.db"); P = collections.defaultdict(list)
    for d, p, *v in c.execute("select g.date,b.player," + ",".join("b." + k for k in S.COLS) +
                              " from nba_box b join nba_games g on g.game_id=b.game_id where g.season='2026-27' and g.stype='regular' and b.min>0"):
        P[("nba", S.nn(p))].append((d, dict(zip(S.COLS, [x or 0 for x in v]))))
    for d, p, st in c.execute("select date,player,stats from player_games where sport='NHL' and date>='2026-10-01'"):
        j = json.loads(st)
        if j.get("gtype") == "reg":
            P[("nhl", S.nn(p))].append((d, {k: float(j.get(k) or 0) for k in S.NHL_COLS}))
    for k in P:
        P[k].sort(key=lambda x: x[0])
    return P


def closes(day_from, day_to):
    L = sqlite3.connect("lines.db"); out = {}
    for lg, sp in ((7, "nba"), (8, "nhl")):
        for pl, st, kind, ln, start, ls in L.execute("select player,stat,kind,line,start,last_seen from pp where league=? and kind in ('goblin','standard') "
                                                      "and start>=? and start<?", (lg, day_from, day_to)):
            if st not in STATS or st not in S.stats_for(sp):
                continue
            day = datetime.datetime.fromisoformat(start).astimezone(CT).date().isoformat()
            k = (sp, day, pl, st, kind)
            if kind == "goblin":                             # several goblin rungs can exist: keep each line
                k = k + (ln,)
            if k not in out or (ls or "") > out[k][1]:
                out[k] = (ln, ls or "")
    return out


def features(P, sp, day, pl, st, ln, std):
    g = [s for d, s in P.get((sp, S.nn(pl)), []) if d < day]
    if len(g) < 5:
        return None
    e = S.stats_for(sp)[st]; v = [S.val(s, e) for s in g]
    return dict(own=sum(x > ln for x in v) / len(v), l10=sum(x > ln for x in v[-10:]) / len(v[-10:]), floor=min(v[-10:]),
                n=len(v), gap=(std - ln) if std is not None else None)


def backtest():
    P = logs(); C = closes("2026-10-21", "2026-11-23")
    std = {(sp, d, pl, st): v[0] for (sp, d, pl, st, kind, *r), v in C.items() if kind == "standard"}
    rows = []
    for (sp, day, pl, st, kind, *rest), (ln, _) in C.items():
        if kind != "goblin":
            continue
        act = next((S.val(s, S.stats_for(sp)[st]) for d, s in P.get((sp, S.nn(pl)), []) if d == day), None)
        if act is None:
            continue
        f = features(P, sp, day, pl, st, ln, std.get((sp, day, pl, st)))
        if f:
            f.update(sp=sp, day=day, pl=pl, st=st, ln=ln, win=act > ln); rows.append(f)
    days = sorted({r["day"] for r in rows}); mid = days[len(days) // 2]
    print("GOBLIN SCREEN backtest: %d graded goblins with 5+ prior games (%s..%s), split at %s" % (len(rows), days[0], days[-1], mid))
    print("all: %.1f%%" % (100 * sum(r["win"] for r in rows) / len(rows)))
    conds = {
        "own>=85%": lambda r: r["own"] >= .85, "own>=90%": lambda r: r["own"] >= .90, "own=100%": lambda r: r["own"] >= .999,
        "l10=10/10": lambda r: r["l10"] >= .999, "l10>=9/10": lambda r: r["l10"] >= .9,
        "floor>line": lambda r: r["floor"] > r["ln"], "gap>=2": lambda r: (r["gap"] or 0) >= 2, "gap>=3": lambda r: (r["gap"] or 0) >= 3,
        "nba": lambda r: r["sp"] == "nba", "nhl": lambda r: r["sp"] == "nhl", "n>=10": lambda r: r["n"] >= 10,
        "single stat": lambda r: "+" not in r["st"], "combo stat": lambda r: "+" in r["st"],
    }
    import itertools
    out = []
    for k in (1, 2, 3):
        for combo in itertools.combinations(conds, k):
            X = [r for r in rows if all(conds[c](r) for c in combo)]
            a = [r["win"] for r in X if r["day"] < mid]; b = [r["win"] for r in X if r["day"] >= mid]
            if len(a) >= 40 and len(b) >= 40:
                out.append((min(sum(a) / len(a), sum(b) / len(b)), combo, len(a), sum(a) / len(a), len(b), sum(b) / len(b)))
    out.sort(reverse=True)
    print("\nbest slices (worst half shown first; a builder needs >= 80% in BOTH halves):")
    for m, combo, na, pa, nb, pb in out[:15]:
        print("  %-40s 1st %.1f%% (n=%d) | 2nd %.1f%% (n=%d)  %s" % (" + ".join(combo), 100 * pa, na, 100 * pb, nb, "<== BUILDER" if m >= .80 else ""))
    json.dump(rows, open("data/goblin_screen_bt.json", "w"))


if __name__ == "__main__":
    if sys.argv[1:2] == ["backtest"]:
        backtest()
