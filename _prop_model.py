"""PROP MODEL (11/21, user: "make a model idc how ... top 10-15 per day as long as they pass the proj model").
One gradient-boosted classifier over every archived PP closing standard line (edge_rows.json: NBA + NHL, as-of features).
Each row is turned into TWO candidates (over, under); features are signed to the side so the model learns "this side wins".
Strict walk-forward: for each day D the model is trained only on days < D, then ranks D's candidates; we take the top N
(one side per line, one leg per player) and require the projection to agree with the side. Graded vs the actual box.
    python _prop_model.py backtest [edge_rows.json]     # walk-forward top-N record by day, both halves
"""
import sys, json, math, collections, statistics
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

FEATS = ["so", "l5o", "l10o", "avg_rel", "med_rel", "po", "pu", "z", "defn", "min5", "min_tr", "rest", "move", "mkt", "gap", "last2o", "n", "line"]
STATS = None


def side_feats(r, side):
    """signed so every 'rate' feature means 'this side'."""
    g = lambda k: (np.nan if r.get(k) is None else float(r[k]))
    o = side == "over"
    l5 = g("l5o") / max(min(5, r.get("n") or 5), 1)               # l5o is a COUNT (0-5); avg_rel/med_rel are (x - line)/line around 0
    f = [g("so") if o else 1 - g("so"), l5 if o else 1 - l5, g("l10o") if o else 1 - g("l10o"),
         g("avg_rel") if o else -g("avg_rel"),
         g("med_rel") if o else -g("med_rel"),
         g("po") if o else g("pu"), g("pu") if o else g("po"), g("z") if o else -g("z"),
         g("defn") if o else -g("defn"), g("min5"), g("min_tr"), g("rest"),
         (-g("move")) if o else g("move"),                       # + = PP moved toward this side
         g("mkt") if o else (1 - g("mkt") if r.get("mkt") is not None else np.nan),
         g("gap") if o else -g("gap"), (g("last2o") if o else 2 - g("last2o")) if r.get("last2o") is not None else np.nan,
         g("n"), g("line"), 1.0 if o else 0.0, 1.0 if r["sp"] == "nba" else 0.0]
    f += [1.0 if r["stat"] == s else 0.0 for s in STATS]
    return f


def win(r, side):
    if r["act"] == r["line"]:
        return None
    return (r["act"] > r["line"]) if side == "over" else (r["act"] < r["line"])


def proj_ok(r, side):
    """projection must agree: avg AND median vs the line on the side we take (when known)."""
    a, m = r.get("avg_rel"), r.get("med_rel")
    if a is None or m is None:
        return False
    return (a > 0 and m > 0) if side == "over" else (a < 0 and m < 0)       # 11/21 fix: centred on 0, not 1


def backtest(path="edge_rows.json", N=(5, 10, 15), min_train_days=10):
    global STATS
    R = [r for r in json.load(open(path)) if r.get("real") and r.get("act") is not None]
    STATS = sorted({r["stat"] for r in R})
    days = sorted({r["day"] for r in R})
    byday = collections.defaultdict(list)
    for r in R:
        byday[r["day"]].append(r)
    res = {n: [] for n in N}            # (day, wins, losses)
    picks_log = []
    for i, d in enumerate(days):
        if i < min_train_days:
            continue
        tr = [(side_feats(r, s), win(r, s)) for dd in days[:i] for r in byday[dd] for s in ("over", "under")]
        tr = [(f, w) for f, w in tr if w is not None]
        X = np.array([f for f, _ in tr], dtype=float); y = np.array([int(w) for _, w in tr])
        m = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=80, l2_regularization=1.0)
        m.fit(X, y)
        cand = []
        for r in byday[d]:
            for s in ("over", "under"):
                cand.append((r, s))
        P = m.predict_proba(np.array([side_feats(r, s) for r, s in cand], dtype=float))[:, 1]
        ranked = sorted(zip(P, cand), key=lambda t: -t[0])
        used = set(); chosen = []
        for p, (r, s) in ranked:
            if (r["sp"], r["player"]) in used or not proj_ok(r, s):
                continue
            used.add((r["sp"], r["player"])); chosen.append((p, r, s))
            if len(chosen) >= max(N):
                break
        for n in N:
            w = [win(r, s) for p, r, s in chosen[:n]]
            w = [x for x in w if x is not None]
            res[n].append((d, sum(w), len(w) - sum(w)))
        for p, r, s in chosen[:max(N)]:
            picks_log.append(dict(day=d, sp=r["sp"], player=r["player"], stat=r["stat"], line=r["line"], side=s, p=round(float(p), 3),
                                  act=r["act"], win=win(r, s)))
    json.dump(picks_log, open("prop_model_bt.json", "w"), indent=0)
    tested = [d for d, _, _ in res[N[0]]]
    half = tested[len(tested) // 2]
    print("PROP MODEL walk-forward: %d days tested (%s..%s), split at %s; break-even 57.7%%" % (len(tested), tested[0], tested[-1], half))
    for n in N:
        A = [(w, l) for d, w, l in res[n] if d < half]; B = [(w, l) for d, w, l in res[n] if d >= half]
        f = lambda X: (sum(w for w, _ in X), sum(l for _, l in X))
        (aw, al), (bw, bl) = f(A), f(B)
        tw, tl = aw + bw, al + bl
        z = (tw / (tw + tl) - .577) / math.sqrt(.577 * .423 / (tw + tl))
        print("  top %-2d/day   first half %d-%d (%.1f%%)   second half %d-%d (%.1f%%)   all %d-%d (%.1f%%)  z vs b/e %+.1f" % (
            n, aw, al, 100 * aw / max(aw + al, 1), bw, bl, 100 * bw / max(bw + bl, 1), tw, tl, 100 * tw / max(tw + tl, 1), z))
    # by sport/side for top 15
    agg = collections.defaultdict(lambda: [0, 0])
    for p in picks_log:
        if p["win"] is None:
            continue
        for k in (p["sp"] + " " + p["side"], p["sp"] + " " + p["stat"]):
            agg[k][0] += p["win"]; agg[k][1] += 1
    print("  top-%d split:" % max(N))
    for k, (w, n) in sorted(agg.items(), key=lambda t: -t[1][1])[:14]:
        print("     %-28s %3d/%-3d %.1f%%" % (k, w, n, 100 * w / n))


if __name__ == "__main__":
    if sys.argv[1:2] == ["backtest"]:
        backtest(sys.argv[2] if len(sys.argv) > 2 else "edge_rows_1116.json")


# ---------------- nightly: score today's board, top 10, slips, log; grade the paper ledger ----------------
PAPER = "prop_model_paper.jsonl"


def today_rows(day):
    """same features as _edge_research.build, for today's PP standard lines (no result yet)."""
    import datetime, sqlite3, statistics
    import _stack as S
    import _edge_research as E
    L = sqlite3.connect("lines.db")
    out = []
    for sp, lg in (("nba", 7), ("nhl", 8)):
        ST = S.stats_for(sp)
        try:
            B = S.board(day, sp)
        except Exception as e:
            print(sp, "board unavailable:", e)
            continue
        D = S.Data(day, sp)
        now = datetime.datetime.now(S.CT)
        for b in B:
            st, pl = b["stat"], b["player"]
            if st not in ST or st not in E.REAL[sp]:
                continue
            if datetime.datetime.fromisoformat(b["start"]).astimezone(S.CT) <= now:
                continue
            k = S.pkey(sp, pl)
            ln = float(b["line"])
            r = S.check(D, dict(sport=sp, player=pl, team=b.get("team"), opp=b.get("opp"), stat=st, line=ln, start=b["start"]), day)
            gs = [g for g in D.G.get(k, []) if g["season"] == S.CUR]
            if not r or len(gs) < 5:
                continue
            e = ST[st]
            v = [S.val(g["s"], e) for g in gs]
            m = [g["min"] for g in gs]
            if statistics.mean(m[-5:]) < (20 if sp == "nba" else 14):
                continue
            first = L.execute("select line from pp where league=? and player=? and stat=? and kind='standard' and start=? order by first_seen limit 1",
                              (lg, pl, st, b["start"])).fetchone()
            mk = None
            if st in E.SH[sp]:
                lo = (now - datetime.timedelta(hours=8)).isoformat()
                ps = [p for (p,) in L.execute("select p_over from sharp where sport=? and player=? and stat=? and line=? and ts>=? and ts<?",
                                              (sp.upper(), E.norm(pl), E.SH[sp][st], ln, lo, b["start"]))]
                mk = sum(ps) / len(ps) if ps else None
            out.append(dict(sp=sp, day=day, player=pl, team=b.get("team"), opp=b.get("opp"), start=b["start"], stat=st, line=ln, act=None, real=True,
                            so=sum(x > ln for x in v) / len(v), l5o=sum(x > ln for x in v[-5:]), l10o=sum(x > ln for x in v[-10:]) / len(v[-10:]),
                            avg_rel=(statistics.mean(v) - ln) / max(ln, 1), med_rel=(statistics.median(v) - ln) / max(ln, 1),
                            po=r["po"], pu=r["pu"], z=r["z"], defn=D.dvp(k, e, b.get("opp")), min5=statistics.mean(m[-5:]),
                            min_tr=statistics.mean(m[-3:]) / statistics.mean(m),
                            rest=(datetime.date.fromisoformat(day) - datetime.date.fromisoformat(gs[-1]["date"][:10])).days,
                            move=ln - (first[0] if first else ln), mkt=mk, gap=None, last2o=sum(x > ln for x in v[-2:]), n=len(v)))
    return out


def tonight(day, train_path="edge_rows.json", N=10):
    global STATS
    import datetime
    T = [r for r in json.load(open(train_path)) if r.get("real") and r.get("act") is not None]
    rows = today_rows(day)
    STATS = sorted({r["stat"] for r in T} | {r["stat"] for r in rows})
    tr = [(side_feats(r, s), win(r, s)) for r in T for s in ("over", "under")]
    tr = [(f, w) for f, w in tr if w is not None]
    m = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=80, l2_regularization=1.0)
    m.fit(np.array([f for f, _ in tr], dtype=float), np.array([int(w) for _, w in tr]))
    cand = [(r, s) for r in rows for s in ("over", "under")]
    if not cand:
        print("no lines to score")
        return [], []
    P = m.predict_proba(np.array([side_feats(r, s) for r, s in cand], dtype=float))[:, 1]
    used = set()
    top = []
    for p, (r, s) in sorted(zip(P, cand), key=lambda t: -t[0]):
        if (r["sp"], r["player"]) in used or not proj_ok(r, s):
            continue
        used.add((r["sp"], r["player"]))
        top.append((float(p), r, s))
        if len(top) >= N:
            break
    game = lambda r: tuple(sorted([r.get("team") or "", r.get("opp") or ""]))
    pool = list(top)
    slips = []
    while len(pool) >= 2:
        a = pool.pop(0)
        b = next((x for x in pool if game(x[1]) != game(a[1])), None)
        if not b:
            break
        pool.remove(b)
        slips.append((a, b))
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    with open(PAPER, "a", encoding="utf-8") as f:
        for i, (p, r, s) in enumerate(top, 1):
            f.write(json.dumps(dict(kind="leg", day=day, rank=i, sp=r["sp"], player=r["player"], team=r.get("team"), opp=r.get("opp"),
                                    stat=r["stat"], line=r["line"], side=s, p=round(p, 3), start=r["start"], logged=ts, result=None)) + "\n")
        for j, (a, b) in enumerate(slips, 1):
            f.write(json.dumps(dict(kind="slip", day=day, slip=j, legs=[[x[1]["player"], x[1]["stat"], x[1]["line"], x[2]] for x in (a, b)],
                                    logged=ts, result=None)) + "\n")
    print("PROP MODEL TOP %d -- %s (paper; backtest top-10 62.6%% walk-forward, halves 63.8%% / 61.4%%)" % (N, day))
    for i, (p, r, s) in enumerate(top, 1):
        print("  %2d. [%s] %-24s %-16s %s%-5g model %.0f%%  season %.0f%% this side  %s" % (
            i, r["sp"].upper(), r["player"][:24], r["stat"][:16], s[0].upper(), r["line"], 100 * p,
            100 * (r["so"] if s == "over" else 1 - r["so"]), r["start"][11:16]))
    print("  slips (2-picks, distinct games):")
    for j, (a, b) in enumerate(slips, 1):
        print("   %d. %s %s%g %s  +  %s %s%g %s" % (j, a[1]["player"], a[2][0].upper(), a[1]["line"], a[1]["stat"],
                                               b[1]["player"], b[2][0].upper(), b[1]["line"], b[1]["stat"]))
    # 11/21 user plan (replay 10/21-11/18: +$580 on $2,030, best of every combo tested): top 3 legs ->
    # main 2-man $30 (#1+#2), round robin 2-mans $10 (#1+#2, #1+#3, #2+#3), 3-man power $10 (#1+#2+#3) = $70/night
    if len(top) >= 3:
        lab = lambda x: "%s %s%g %s" % (x[1]["player"], x[2][0].upper(), x[1]["line"], x[1]["stat"])
        t1, t2, t3 = top[:3]
        plan = [("MAIN 2-man", 30, (t1, t2)), ("RR 2-man", 10, (t1, t2)), ("RR 2-man", 10, (t1, t3)), ("RR 2-man", 10, (t2, t3)),
                ("3-man POWER", 10, (t1, t2, t3))]
        print("  TONIGHT'S PLAN ($70, tag MODEL):")
        with open(PAPER, "a", encoding="utf-8") as f:
            for name, stake, legs in plan:
                print("   $%-3d %-12s %s" % (stake, name, "  +  ".join(lab(x) for x in legs)))
                f.write(json.dumps(dict(kind="plan", day=day, name=name, stake=stake, legs=[[x[1]["player"], x[1]["stat"], x[1]["line"], x[2]] for x in legs],
                                        logged=ts, result=None)) + "\n")
        try:
            import _notify
            _notify.send("CARD", "**MODEL PLAN %s ($70)**\n" % day + "\n".join("$%d %s: %s" % (st, nm, " + ".join(lab(x) for x in lg)) for nm, st, lg in plan))
        except Exception as e:
            print("post failed:", e)
    return top, slips


def grade_paper():
    """settle paper legs/slips whose box score is in (NBA nba_box, NHL player_games)."""
    import sqlite3
    import _stack as S
    c = sqlite3.connect("sports.db")
    rows = [json.loads(l) for l in open(PAPER, encoding="utf-8") if l.strip()]
    box = {}
    for r in rows:
        if r.get("result") is not None or r["kind"] != "leg":
            continue
        key = (r["sp"], r["day"])
        if key not in box:
            box[key] = {}
            if r["sp"] == "nba":
                for p, *v in c.execute("select player," + ",".join(S.COLS) + " from nba_box where date=? and min>0", (r["day"],)):
                    box[key][S.nn(p)] = dict(zip(S.COLS, [x or 0 for x in v]))
            else:
                for p, st in c.execute("select player, stats from player_games where sport='NHL' and date=?", (r["day"],)):
                    j = json.loads(st)
                    box[key][S.nn(p)] = {k: float(j.get(k) or 0) for k in S.NHL_COLS}
        s = box[key].get(S.nn(r["player"]))
        if s is None:
            continue
        act = S.val(s, S.stats_for(r["sp"])[r["stat"]])
        r["actual"] = act
        r["result"] = "P" if act == r["line"] else ("W" if (act > r["line"]) == (r["side"] == "over") else "L")
    legres = {(r["day"], r["player"], r["stat"]): r["result"] for r in rows if r["kind"] == "leg"}
    for r in rows:
        if r["kind"] == "slip" and r.get("result") is None:
            rs = [legres.get((r["day"], p, st)) for p, st, ln, sd in r["legs"]]
            if all(x in ("W", "L", "P") for x in rs):
                r["result"] = "L" if "L" in rs else ("W" if all(x == "W" for x in rs) else "P")
    for r in rows:                                                        # plan slips: power payouts 2-man 3x, 3-man 6x; push = leg dropped
        if r["kind"] == "plan" and r.get("result") is None:
            rs = [legres.get((r["day"], p, st)) for p, st, ln, sd in r["legs"]]
            if all(x in ("W", "L", "P") for x in rs):
                live = [x for x in rs if x != "P"]
                mult = {3: 6, 2: 3, 1: 1, 0: 1}[len(live)]
                r["result"] = "L" if "L" in live else "W"
                r["net"] = -r["stake"] if r["result"] == "L" else round(r["stake"] * (mult - 1), 2)
    open(PAPER, "w", encoding="utf-8").write("".join(json.dumps(r) + "\n" for r in rows))
    Pl = [r for r in rows if r["kind"] == "plan" and r.get("net") is not None]
    if Pl:
        print("MODEL PLAN paper: %d slips, net %+.2f" % (len(Pl), sum(r["net"] for r in Pl)))
    Lg = [r for r in rows if r["kind"] == "leg" and r.get("result") in ("W", "L")]
    Sl = [r for r in rows if r["kind"] == "slip" and r.get("result") in ("W", "L")]
    w = sum(r["result"] == "W" for r in Lg)
    print("PROP MODEL paper record: legs %d-%d (%.1f%%) | slips %d-%d" % (w, len(Lg) - w, 100 * w / max(len(Lg), 1),
          sum(r["result"] == "W" for r in Sl), sum(r["result"] == "L" for r in Sl)))


if __name__ == "__main__" and sys.argv[1:2] == ["tonight"]:
    import datetime as _d
    tonight(sys.argv[2] if len(sys.argv) > 2 else _d.date.today().isoformat(), sys.argv[3] if len(sys.argv) > 3 else "edge_rows.json")
if __name__ == "__main__" and sys.argv[1:2] == ["grade"]:
    grade_paper()
