"""FORM + DEFENSE + LINE-GAP BACKTEST (11/16, user: "what if you backtested where the season form clears, plus the last 5, plus the
exploit of defense ... even if the last 2 games have been ass ... and if PP's price was better than any market").

TEST 1 (NBA + NHL archived PP closing lines, lines.db -> box): season hit rate at the line (this season, before the day), last 5, and the
position-aware defense factor (_stack Data.dvp: what this player TYPE did vs this defense / own rate). Soft defense (>= +8%) backs an
OVER, tough (<= -8%) backs an UNDER. 'Bounce' = season + defense agree but the last 2 games both went the other way.
Split by the sharp market at the same line where lines.db has one.

TEST 2 (every graded line in pp_history.jsonl, all sports): PP's closing number vs the sharp books' MAIN line that day (the line whose
de-vig p_over is closest to 50%). When PP sits above it, the under is the side PP gives away; below it, the over. Hit rate by gap size.
    python _form_def_bt.py
"""
import json, sqlite3, collections, re, datetime
import _stack as S
from _opp_bt import legs

norm = lambda s: re.sub(r"[^a-z]", "", (s or "").lower())
SH = {"nba": {"Points": "points", "Rebounds": "rebounds", "Assists": "assists", "3-PT Made": "threes made", "Pts+Rebs+Asts": "pts & rebs & asts"},
      "nhl": {"Shots On Goal": "shots on goal", "Points": "points", "Assists": "assists", "Goals": "goals"}}


def sharp_index():
    L = sqlite3.connect("lines.db")
    ix = collections.defaultdict(dict)          # (sport, player, stat, day) -> {(book, line): (ts, p)}
    for book, sp, pl, st, ln, p, ts in L.execute("select book, sport, player, stat, line, p_over, ts from sharp"):
        k = (sp, pl, st, ts[:10]); kk = (book, ln)
        if kk not in ix[k] or ts > ix[k][kk][0]:
            ix[k][kk] = (ts, p)
    return ix


def test1(ix):
    rec = []
    for sp in ("nba", "nhl"):
        days = legs(sp)
        S.first_line = lambda *a: None
        for day in sorted(days):
            D = S.Data(day, sp)
            prev = (datetime.date.fromisoformat(day) - datetime.timedelta(days=1)).isoformat()
            for leg in days[day]:
                key = S.pkey(sp, leg["player"])
                gs = [g for g in D.G.get(key, []) if g["season"] == S.CUR]
                if len(gs) < 5:
                    continue
                e = S.stats_for(sp)[leg["stat"]]; ln = leg["line"]
                v = [S.val(g["s"], e) for g in gs]                       # oldest -> newest
                f = D.dvp(key, e, leg["opp"])
                mk = None
                st = SH[sp].get(leg["stat"])
                if st:
                    b = ix.get((sp.upper(), norm(leg["player"]), st, day)) or ix.get((sp.upper(), norm(leg["player"]), st, prev)) or {}
                    ps = [p for (bk, l_), (_, p) in b.items() if l_ == ln]
                    mk = sum(ps) / len(ps) if ps else None
                for side in ("over", "under"):
                    w = (lambda x: x > ln) if side == "over" else (lambda x: x < ln)
                    rec.append(dict(sp=sp, day=day, side=side, season=sum(map(w, v)) / len(v), l5=sum(map(w, v[-5:])),
                                    last2_bad=not w(v[-1]) and not w(v[-2]),
                                    defn=None if f is None else (f if side == "over" else -f),     # + = defense favours this side
                                    mkt=None if mk is None else (mk if side == "over" else 1 - mk),
                                    won=(leg["act"] > ln) if side == "over" else (leg["act"] < ln)))
        print("  %s done: %d side-rows" % (sp, sum(1 for r in rec if r["sp"] == sp)))
    return rec


def rep(lab, X):
    n = len(X); w = sum(r["won"] for r in X)
    return "  %-62s %4d-%-4d %5.1f%%" % (lab, w, n - w, 100 * w / n) if n else "  %-62s   --" % lab


def report1(R):
    for sp in ("nba", "nhl"):
        for side in ("over", "under"):
            X = [r for r in R if r["sp"] == sp and r["side"] == side]
            print("\n%s %s  (2-pick break-even 57.7%%)" % (sp.upper(), side.upper()))
            base = [r for r in X if r["season"] >= .6 and r["l5"] >= 3]
            soft = lambda r: r["defn"] is not None and r["defn"] >= .08
            print(rep("season 60%+ & L5 3/5+ (no defense)", base))
            print(rep("season 60%+ & L5 3/5+ & defense favours side (8%+)", [r for r in base if soft(r)]))
            print(rep("season 60%+ & L5 4/5+ & defense favours side", [r for r in base if r["l5"] >= 4 and soft(r)]))
            print(rep("season 60%+ & L5 3/5+ & defense AGAINST side", [r for r in base if r["defn"] is not None and r["defn"] <= -.08]))
            print(rep("BOUNCE: season 60%+ & defense favours & last 2 both wrong", [r for r in X if r["season"] >= .6 and soft(r) and r["last2_bad"]]))
            print(rep("defense favours side alone", [r for r in X if soft(r)]))
            combo = [r for r in base if soft(r)]
            for lo, hi, lab in ((0, .48, "<48%"), (.48, .52, "48-52%"), (.52, 1.01, "52%+")):
                print(rep("   combo, market %s" % lab, [r for r in combo if r["mkt"] is not None and lo <= r["mkt"] < hi]))
            print(rep("   combo, no market price", [r for r in combo if r["mkt"] is None]))


def test2(ix):
    out = []
    for l in open("pp_history.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if r["res_close"] == "push":
            continue
        st = {"Receiving Yards": "receiving yards", "Rush Yards": "rushing yards", "Receptions": "receptions", "Pass Yards": "passing yards",
              "Shots On Goal": "shots on goal", "Points": "points", "Assists": "assists", "Goals": "goals", "Goalie Saves": "saves",
              "Rebounds": "rebounds", "3-PT Made": "threes made", "Pts+Rebs+Asts": "pts & rebs & asts", "Total Bases": "bases",
              "Pitcher Strikeouts": "strikeouts", "Rush Attempts": "rush attempts", "Pass Completions": "pass completions",
              "Pass Attempts": "pass attempts"}.get(r["stat"])
        if not st:
            continue
        prev = (datetime.date.fromisoformat(r["day"]) - datetime.timedelta(days=1)).isoformat()
        b = ix.get((r["sport"], norm(r["player"]), st, r["day"])) or ix.get((r["sport"], norm(r["player"]), st, prev))
        if not b:
            continue
        main = min(b.items(), key=lambda kv: abs(kv[1][1] - .5))[0][1]
        gap = r["close"] - main
        if gap == 0:
            continue
        side = "under" if gap > 0 else "over"
        out.append(dict(sp=r["sport"], gap=abs(gap), side=side, won=r["res_close"] == side))
    print("\nTEST 2 -- PP's number vs the sharp MAIN line; the side PP gives away  (n=%d)" % len(out))
    for lo, hi, lab in ((0, .75, "0.5 off"), (.75, 1.25, "1 off"), (1.25, 2.25, "1.5-2 off"), (2.25, 99, "2.5+ off")):
        print(rep("gap %s" % lab, [r for r in out if lo <= r["gap"] < hi]))
    for sp in sorted({r["sp"] for r in out}):
        X = [r for r in out if r["sp"] == sp]
        if len(X) >= 30:
            print(rep("  %s (all gaps)" % sp, X) + "   | under-side %s / over-side %s" % (
                rep("", [r for r in X if r["side"] == "under"]).split()[-1], rep("", [r for r in X if r["side"] == "over"]).split()[-1]))


if __name__ == "__main__":
    ix = sharp_index()
    test2(ix)
    R = test1(ix)
    report1(R)
    json.dump(R, open("form_def_bt.json", "w"))
