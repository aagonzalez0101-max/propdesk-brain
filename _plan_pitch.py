"""The honest $100 September plan, with PITCHER props added (2026-09-29).
Pitcher legs come from _pitcher_bt.json at their BOARD odds (the price the pick carried)."""
import json, random, collections
ns = {}; exec(open("_plan_honest.py", encoding="utf-8").read().split("random.seed(3)")[0], ns)
days, base = ns["days"], ns["day_returns"]
dec = lambda o: (100 / -o) + 1 if o < 0 else o / 100 + 1
R = json.load(open("_pitcher_bt.json"))
ok = lambda r: r["calibrated"] >= .6 and (r.get("season_rate") or 0) >= .6
SETS = {"outs U": [r for r in R if r["market"] == "OUTS" and r["side"] == "UNDER" and ok(r)],
        "K": [r for r in R if r["market"] == "K" and ok(r)],
        "ER": [r for r in R if r["market"] == "ER" and ok(r)]}
def extra(dd, keys):
    return [(dec(r["odds"]) - 1) if r["win"] else -1 for k in keys for r in SETS[k] if r["day"] == dd and r.get("odds") is not None]
def month(keys):
    B = 100.0; W = L = 0; flat = 0.0
    for dd in days:
        s = B
        for r in base(dd, "-160", "straight") + extra(dd, keys):
            B += s * 0.05 * r; flat += r; W += r > 0; L += r <= 0
    return B, W, L, flat / max(W + L, 1)
def three(keys, runs=10000):
    pool = [base(dd, "-160", "straight") + extra(dd, keys) for dd in days]; out = []
    for _ in range(runs):
        B = 100.0
        for _ in range(91):
            s = B
            for r in random.choice(pool): B += s * 0.05 * r
        out.append(B)
    out.sort(); return out[len(out) // 10], out[len(out) // 2], out[9 * len(out) // 10]
random.seed(3)
print("%-44s %-9s %-7s %-12s %s" % ("plan", "record", "ROI", "Sept $100->", "3 months: bad / MEDIAN / good"))
for lbl, keys in (("BASE: props -160 + ML 60%+", []), ("+ pitching outs UNDERS", ["outs U"]),
                  ("+ strikeout props", ["K"]), ("+ earned-runs props", ["ER"]), ("+ outs U + K + ER (everything)", ["outs U", "K", "ER"])):
    B, W, L, roi = month(keys); a, b, c = three(keys)
    print("%-44s %-9s %+5.1f%%  $%-11.0f $%.0f / $%.0f / $%.0f" % (lbl, "%d-%d" % (W, L), roi * 100, B, a, b, c))
