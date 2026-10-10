"""OUT-OF-SAMPLE test of the 'ML only when the model has it at 60%+' rule (2026-09-28).

Data: v3_big.jsonl -- 1,591 games 2026-05-01..08-29, point-in-time v3 components, REAL closing odds,
final scores. The rule was found on September boards; these months were never used to find it.
Model reproduced from pp/board.py: margin ~ OLS(market, sp, off, ars, wx); raw = ncdf(fit/4.62);
side chosen on RAW; calibrated via pp/calibration.ML. Coefficients WALK-FORWARD: refit each day on
games strictly before it (production fits on everything, which would leak the future here).
"""
import json, math, sys, collections
sys.path.insert(0, "pp"); sys.path.insert(0, ".")
import calibration as C
SD = 4.62
ncdf = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
def probit(p):
    lo, hi = -8.0, 8.0
    for _ in range(80):
        m = (lo + hi) / 2
        if ncdf(m) < p: lo = m
        else: hi = m
    return (lo + hi) / 2
imp = lambda o: (-o) / ((-o) + 100) if o < 0 else 100 / (o + 100)
dec = lambda o: (100 / -o) + 1 if o < 0 else o / 100 + 1
def feats(r): return [probit(r["mktp"]) * SD, (r.get("as_ra9") or 0) - (r.get("hs_ra9") or 0),
                      (r.get("h_off") or 1) - (r.get("a_off") or 1), (r.get("h_ars") or 1) - (r.get("a_ars") or 1), (r.get("wx") or 1) - 1]
def ols(X, y):
    import numpy as np
    A = np.column_stack([np.ones(len(X)), np.array(X)]); return np.linalg.lstsq(A, np.array(y), rcond=None)[0]
rows = [json.loads(l) for l in open("v3_big.jsonl", encoding="utf-8") if l.strip()]
rows = [r for r in rows if r.get("act_h") is not None and r.get("mktp") and r.get("mkt") and r.get("mkta") and r["act_h"] != r["act_a"]]
rows.sort(key=lambda r: r["day"])
bets = []
days = sorted({r["day"] for r in rows})
for d in days:
    past = [r for r in rows if r["day"] < d]
    if len(past) < 250: continue
    B = ols([feats(r) for r in past], [r["act_h"] - r["act_a"] for r in past])
    for r in (x for x in rows if x["day"] == d):
        fx = feats(r); fit = B[0] + sum(B[i + 1] * fx[i] for i in range(5))
        raw_h = ncdf(fit / SD); cal_h = C.for_market("ML", raw_h)
        home = raw_h > r["mktp"]
        raw = raw_h if home else 1 - raw_h; cal = cal_h if home else 1 - cal_h
        o = r["mkt"] if home else r["mkta"]
        # the market prob for the chosen side at ITS OWN price (vig in), like the board compares
        m = imp(o)
        won = (r["act_h"] > r["act_a"]) == home
        bets.append(dict(day=d, raw=raw, cal=cal, o=o, m=m, won=won, ev=raw * dec(o) - 1))
print("walk-forward scored games: %d  (%s .. %s)\n" % (len(bets), bets[0]["day"], bets[-1]["day"]))
def rep(sub, lbl):
    if not sub: print("  %-40s 0" % lbl); return
    w = sum(b["won"] for b in sub); roi = sum((dec(b["o"]) - 1) if b["won"] else -1 for b in sub) / len(sub)
    be = sum(b["m"] for b in sub) / len(sub)
    z = (w / len(sub) - be) / math.sqrt(be * (1 - be) / len(sub))
    print("  %-40s %4d bets  %4d-%-4d  win %5.1f%% vs %5.1f%% needed  ROI %+6.1f%%  z %+.2f" % (lbl, len(sub), w, len(sub) - w, 100 * w / len(sub), 100 * be, 100 * roi, z))
stable = [b for b in bets if b["raw"] > b["m"] and b["cal"] > b["m"]]
rep(stable, "sign-stable, every edge")
rep([b for b in stable if b["cal"] >= 0.60], "THE RULE: model 60%+")
rep([b for b in stable if b["cal"] >= 0.65], "model 65%+")
rep([b for b in stable if b["o"] > 0], "plus-money (the rule forbids)")
rep([b for b in stable if b["raw"] - b["m"] >= 0.10], "big edges 10pp+ (the 'WORTH IT' zone)")
print("\n  THE RULE by month:")
bym = collections.defaultdict(list)
for b in stable:
    if b["cal"] >= 0.60: bym[b["day"][:7]].append(b)
for mth in sorted(bym): rep(bym[mth], "   " + mth)
json.dump([b for b in stable if b["cal"] >= 0.60], open("_ml60_bets.json", "w"))
