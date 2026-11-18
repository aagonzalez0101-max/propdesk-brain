"""EDGE RESEARCH (11/16, user: "find a version where overs win ... same with unders how can we make it better ... only the legs we'd
actually play realistically and record that as well").

One feature table for every archived PP CLOSING standard line (lines.db) in NBA + NHL, graded vs the box, features AS-OF the day:
season hit rate, L5/L10, stack checks (po/pu, proj z), position defense (Data.dvp), minutes trend, rest (back-to-back), PP line move
(open -> close), sharp market at the same line + PP-vs-sharp-main-line gap.
REALISTIC = legs we'd actually play: NBA pts/reb/ast/combos/3PM with 20+ min; NHL SOG/points/assists with 14+ min; 5+ games this season.
Every rule is FOUND on the first half of the days and must HOLD on the second half (walk-forward), or it is not reported as a rule.
    python _edge_research.py build     # -> edge_rows.json  (slow: one Data() load per day)
    python _edge_research.py           # report
"""
import sys, json, sqlite3, datetime, collections, statistics, re
import _stack as S

CT = S.CT
norm = lambda s: re.sub(r"[^a-z]", "", (s or "").lower())
REAL = {"nba": {"Points", "Rebounds", "Assists", "Pts+Rebs+Asts", "Pts+Rebs", "Pts+Asts", "Rebs+Asts", "3-PT Made"},
        "nhl": {"Shots On Goal", "Points", "Assists"}}
SH = {"nba": {"Points": "points", "Rebounds": "rebounds", "Assists": "assists", "3-PT Made": "threes made", "Pts+Rebs+Asts": "pts & rebs & asts"},
      "nhl": {"Shots On Goal": "shots on goal", "Points": "points", "Assists": "assists"}}


def build():
    L = sqlite3.connect("lines.db"); c = sqlite3.connect("sports.db")
    # 11/17 FIX: sharp snapshots run hourly INCLUDING during games (47% of NFL game-day snapshots were after kickoff = live prices).
    # Only prices strictly before the PP start time count.
    ix = collections.defaultdict(list)
    for book, sp, pl, st, ln, p, ts in L.execute("select book, sport, player, stat, line, p_over, ts from sharp where sport in ('NBA','NHL')"):
        ix[(sp, pl, st)].append((datetime.datetime.fromisoformat(ts), book, ln, p))

    def pregame(sp, pl, st, start):
        t0 = datetime.datetime.fromisoformat(start); lo = t0 - datetime.timedelta(days=2); b = {}
        for ts, book, ln, p in ix.get((sp, pl, st), []):
            if lo <= ts < t0 and ((book, ln) not in b or ts > b[(book, ln)][0]):
                b[(book, ln)] = (ts, p)
        return b
    rows = []
    for sp, lg in (("nba", 7), ("nhl", 8)):
        ST = S.stats_for(sp)
        lines = {}
        for pl, team, st, line, start, fs, ls in L.execute("select player, team, stat, line, start, first_seen, last_seen from pp where league=? and kind='standard'", (lg,)):
            if st not in ST or not pl or not start:
                continue
            day = datetime.datetime.fromisoformat(start).astimezone(CT).date().isoformat()
            k = (day, S.pkey(sp, pl), st)
            o = lines.setdefault(k, dict(open=(fs or "~", line), close=(ls or "", line), pl=pl, team=team, start=start))
            if (fs or "~") < o["open"][0]:
                o["open"] = (fs, line)
            if (ls or "") > o["close"][0]:
                o["close"] = (ls, line)
        box = {}
        if sp == "nba":
            for d, p, tm, opp, *v in c.execute("select b.date, b.player, b.team, b.opp, " + ",".join("b." + k for k in S.COLS) + " from nba_box b where b.min>0"):
                box[(d, S.nn(p))] = (tm, opp, dict(zip(S.COLS, [x or 0 for x in v])))
        else:
            for d, p, tm, opp, mn, st in c.execute("select date, player, team, opp, minutes, stats from player_games where sport='NHL' and date>='2026-09-25'"):
                j = json.loads(st)
                if j.get("gtype") == "reg" and mn:
                    box[(d, S.pkey("nhl", p))] = (tm, opp, {k: float(j.get(k) or 0) for k in S.NHL_COLS})
        byday = collections.defaultdict(list)
        for (day, k, st), o in lines.items():
            if (day, k) in box:
                byday[day].append((k, st, o))
        S.first_line = lambda *a: None
        for day in sorted(byday):
            D = S.Data(day, sp)
            prev = (datetime.date.fromisoformat(day) - datetime.timedelta(days=1)).isoformat()
            for k, st, o in byday[day]:
                tm, opp, s = box[(day, k)]
                ln = o["close"][1]; act = S.val(s, ST[st])
                if act == ln:
                    continue
                leg = dict(sport=sp, player=o["pl"], team=tm, opp=opp, stat=st, line=ln, start=o["start"])
                r = S.check(D, leg, day)
                gs = [g for g in D.G.get(k, []) if g["season"] == S.CUR]
                if not r or len(gs) < 5:
                    continue
                e = ST[st]; v = [S.val(g["s"], e) for g in gs]; m = [g["min"] for g in gs]
                rest = (datetime.date.fromisoformat(day) - datetime.date.fromisoformat(gs[-1]["date"][:10])).days
                f = D.dvp(k, e, opp)
                mk = gap = None
                if st in SH[sp]:
                    b = pregame(sp.upper(), norm(o["pl"]), SH[sp][st], o["start"])
                    ps = [p for (bk, l_), (_, p) in b.items() if l_ == ln]
                    mk = sum(ps) / len(ps) if ps else None
                    if b:
                        gap = ln - min(b.items(), key=lambda kv: abs(kv[1][1] - .5))[0][1]
                rows.append(dict(sp=sp, day=day, player=o["pl"], stat=st, line=ln, act=act, over=int(act > ln),
                                 real=st in REAL[sp] and statistics.mean(m[-5:]) >= (20 if sp == "nba" else 14),
                                 so=sum(x > ln for x in v) / len(v), l5o=sum(x > ln for x in v[-5:]), l10o=sum(x > ln for x in v[-10:]) / len(v[-10:]),
                                 avg_rel=(statistics.mean(v) - ln) / max(ln, 1), med_rel=(statistics.median(v) - ln) / max(ln, 1),
                                 po=r["po"], pu=r["pu"], z=r["z"], defn=f, min5=statistics.mean(m[-5:]), min_tr=statistics.mean(m[-3:]) / statistics.mean(m),
                                 rest=rest, move=ln - o["open"][1], mkt=mk, gap=gap, last2o=sum(x > ln for x in v[-2:]), n=len(v)))
            print("  %s %s: %d rows so far" % (sp, day, len(rows)), flush=True)
    json.dump(rows, open("edge_rows.json", "w"))
    print("built %d rows" % len(rows))


def rec(X, side):
    w = sum(r["over"] if side == "over" else 1 - r["over"] for r in X)
    return w, len(X)


def fmt(w, n):
    return "%3d-%-3d %5.1f%%" % (w, n - w, 100 * w / n) if n else "   --       "


def report():
    R = [r for r in json.load(open("edge_rows.json")) if r["real"]]
    for sp in ("nba", "nhl"):
        X = [r for r in R if r["sp"] == sp]
        days = sorted({r["day"] for r in X}); half = days[len(days) // 2]
        A = [r for r in X if r["day"] < half]; B = [r for r in X if r["day"] >= half]
        print("\n%s REALISTIC legs: %d (%s..%s), discovery < %s <= validation" % (sp.upper(), len(X), days[0], days[-1], half))
        for side in ("over", "under"):
            o = side == "over"
            F = {   # each rule = a lambda on a row, written for this side
                "base (every realistic leg)": lambda r: True,
                "season 60%+": lambda r: (r["so"] if o else 1 - r["so"]) >= .6,
                "season 70%+ & L10 70%+": lambda r: (r["so"] if o else 1 - r["so"]) >= .7 and (r["l10o"] if o else 1 - r["l10o"]) >= .7,
                "stack 4+ agree, 0 against": lambda r: (r["po"] >= 4 and r["pu"] == 0) if o else (r["pu"] >= 4 and r["po"] == 0),
                "proj z beyond +-0.5": lambda r: r["z"] > .5 if o else r["z"] < -.5,
                "defense favours (8%+)": lambda r: r["defn"] is not None and (r["defn"] >= .08 if o else r["defn"] <= -.08),
                "defense favours 15%+": lambda r: r["defn"] is not None and (r["defn"] >= .15 if o else r["defn"] <= -.15),
                "minutes rising (L3 >= 110% season)": lambda r: r["min_tr"] >= 1.10,
                "minutes falling (L3 <= 90%)": lambda r: r["min_tr"] <= .90,
                "back-to-back (rest 1)": lambda r: r["rest"] == 1,
                "rested (2+ days)": lambda r: r["rest"] >= 2,
                "PP raised line (close > open)": lambda r: r["move"] > 0,
                "PP dropped line (close < open)": lambda r: r["move"] < 0,
                "market 52%+ this side": lambda r: r["mkt"] is not None and (r["mkt"] if o else 1 - r["mkt"]) >= .52,
                "market 55%+ this side": lambda r: r["mkt"] is not None and (r["mkt"] if o else 1 - r["mkt"]) >= .55,
                "PP gives this side vs books (gap)": lambda r: r["gap"] is not None and (r["gap"] < 0 if o else r["gap"] > 0),
                "median beats line by 15%+": lambda r: (r["med_rel"] >= .15) if o else (r["med_rel"] <= -.15),
                "last 2 went the OTHER way, season 60%+": lambda r: (r["last2o"] == 0 and r["so"] >= .6) if o else (r["last2o"] == 2 and r["so"] <= .4),
                "low line (<= 5.5)": lambda r: r["line"] <= 5.5,
                "big line (>= 20.5)": lambda r: r["line"] >= 20.5,
                "starter minutes (30+)": lambda r: r["min5"] >= 30,
            }
            print("\n  %s  (2-pick b/e 57.7%%)            %-15s %-15s %-15s" % (side.upper(), "discovery", "validation", "all"))
            singles = {}
            for name, f in F.items():
                a, b, t = rec([r for r in A if f(r)], side), rec([r for r in B if f(r)], side), rec([r for r in X if f(r)], side)
                singles[name] = f
                flag = "  <== HOLDS" if a[1] >= 15 and b[1] >= 15 and a[0] / a[1] >= .577 and b[0] / b[1] >= .577 else ""
                print("   %-40s %s %s %s%s" % (name, fmt(*a), fmt(*b), fmt(*t), flag))
            # pairs: found on discovery (58%+, n>=25), shown on validation
            names = [n for n in F if n != "base (every realistic leg)"]
            cands = []
            for i, n1 in enumerate(names):
                for n2 in names[i + 1:]:
                    f = lambda r, f1=F[n1], f2=F[n2]: f1(r) and f2(r)
                    a = rec([r for r in A if f(r)], side)
                    if a[1] >= 25 and a[0] / a[1] >= .60:
                        b = rec([r for r in B if f(r)], side)
                        cands.append((a[0] / a[1], n1 + " + " + n2, a, b, rec([r for r in X if f(r)], side)))
            print("   pairs that hit 60%%+ on discovery (n>=25) -- validation is the real test:")
            for _, name, a, b, t in sorted(cands, reverse=True)[:12]:
                flag = "  <== HOLDS" if b[1] >= 15 and b[0] / b[1] >= .577 else ""
                print("     %-58s %s %s %s%s" % (name[:58], fmt(*a), fmt(*b), fmt(*t), flag))


if __name__ == "__main__":
    if sys.argv[1:2] == ["build"]:
        build()
    report()
