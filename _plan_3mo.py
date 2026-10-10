"""Where would $100 be after 3 months (Oct-Dec length, ~91 days) if the plan's days look like September's?
Day-level bootstrap of REAL September outcomes -- not a backtest of July/August (no priced history there)."""
import random, statistics, json
src = open("_plan_replay.py", encoding="utf-8").read().split('print("\nSTEP 2')[0]
ns = {}; exec(src.replace('print(', 'noprint('), dict(ns, noprint=lambda *a, **k: None), ns) if False else None
exec(open("_top5_replay.py", encoding="utf-8").read().split("def run(")[0], ns)
days, cand, grade, dec, imp, boards = ns["days"], ns["cand"], ns["grade"], ns["dec"], ns["imp"], ns["boards"]
def good_ml(d):
    return [p for p in boards[d].get("picks", []) if p.get("market") == "ML" and p.get("odds") is not None
            and p.get("raw") is not None and p.get("calibrated") is not None
            and p["raw"] > imp(p["odds"]) and p["calibrated"] > imp(p["odds"]) and p["calibrated"] >= 0.60]
dayret = []            # each day's list of per-bet returns (net per $1)
for d in days:
    props = sorted([p for p in cand.get(d, []) if p["market"] != "ML"], key=lambda p: -p.get("ev", 0))[:5]
    r = []
    for p in props + good_ml(d):
        g = grade(d, p)
        if g is None: continue
        r.append((dec(p["odds"]) - 1) if g else -1.0)
    dayret.append(r)
# real-money ledger days too
L = {}
for l in open("live_paper.jsonl", encoding="utf-8"):
    x = json.loads(l)
    if x.get("stake") and x.get("net") is not None and (x.get("kind") == "LIVE" or x.get("mode") == "LIVE" or x.get("funding") in ("cash", "bonus")):
        L.setdefault(x.get("date") or str(x.get("ts"))[:10], []).append(float(x["net"]) / float(x["stake"]))
real = list(L.values())
def boot(pool, days_n=91, frac=0.05, runs=10000, drop_top=False):
    if drop_top:
        best = max((r for d in pool for r in d)); pool = [[r for r in d if r != best] for d in pool]
    out = []
    for _ in range(runs):
        B = 100.0
        for _ in range(days_n):
            dd = random.choice(pool); s = B
            for r in dd: B += s * frac * r
            B = max(B, 0.0)
        out.append(B)
    out.sort(); q = lambda p: out[int(p * len(out))]
    return q(.10), q(.25), q(.50), q(.75), q(.90), sum(1 for x in out if x < 100) / len(out)
random.seed(11)
print("  3 months (91 days) from $100, 5%% of the roll per bet, days resampled from REAL September results\n")
print("  %-38s %-8s %-8s %-9s %-9s %-9s %s" % ("which September", "bad 10%", "25%", "MEDIAN", "75%", "good 10%", "chance below $100"))
for lbl, pool, dt in (("THE PLAN (props top 5 + ML 60%+)", dayret, False),
                      ("your real-money bets", real, False),
                      ("your real bets, minus the 31.6x parlay", real, True)):
    a, b, c, d, e, f = boot(pool, drop_top=dt)
    print("  %-38s $%-7.0f $%-7.0f $%-8.0f $%-8.0f $%-8.0f %.0f%%" % (lbl, a, b, c, d, e, 100 * f))
