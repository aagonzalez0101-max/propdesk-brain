"""Re-evaluated plan (2026-09-28): props + run lines, moneyline ONLY when it's 'good asf'.
Step 1: find whether ANY moneyline tier on the September boards actually made money.
Step 2: replay props (+ that ML tier, if one exists) from $100 at 5% of the morning roll."""
import json, importlib.util, sys, collections
spec = importlib.util.spec_from_file_location("t5", "_top5_replay.py")
src = open("_top5_replay.py", encoding="utf-8").read().split("def run(")[0]   # reuse data + grader, skip its report
ns = {}; exec(src, ns)
days, cand, grade, dec, imp = ns["days"], ns["cand"], ns["grade"], ns["dec"], ns["imp"]
allml = []
for d in days:
    for p in ns["boards"][d].get("picks", []):
        if p.get("market") != "ML" or p.get("odds") is None or p.get("raw") is None or p.get("calibrated") is None: continue
        r = grade(d, p)
        if r is None: continue
        allml.append(dict(d=d, o=p["odds"], won=r, ev=p.get("ev", 0), cal=p["calibrated"], raw=p["raw"],
                          mkt=imp(p["odds"]), v=p.get("verdict"), stable=p["raw"] > imp(p["odds"]) and p["calibrated"] > imp(p["odds"])))
def rep(sub, lbl):
    if not sub: print("  %-44s   0 bets" % lbl); return
    w = sum(x["won"] for x in sub); roi = sum((dec(x["o"]) - 1) if x["won"] else -1 for x in sub) / len(sub)
    print("  %-44s %3d bets  %3d-%-3d  ROI %+6.1f%%" % (lbl, len(sub), w, len(sub) - w, 100 * roi))
print("STEP 1 -- every September board moneyline, by how 'good' the model said it was:\n")
rep(allml, "all moneylines on the board")
st = [x for x in allml if x["stable"]]
rep(st, "sign-stable")
for v in ("STRONG", "WORTH IT", "CONSIDER"): rep([x for x in st if x["v"] == v], "  verdict " + v)
for lo, hi in ((0, .05), (.05, .10), (.10, .20), (.20, 9)): rep([x for x in st if lo <= x["ev"] < hi], "  EV %.0f-%.0f%%" % (100 * lo, 100 * hi) if hi < 9 else "  EV 20%+")
for lo in (.55, .60, .65): rep([x for x in st if x["cal"] >= lo], "  model win prob %.0f%%+" % (100 * lo))
rep([x for x in st if x["o"] > 0], "  plus-money only"); rep([x for x in st if x["o"] < 0], "  favourites only")

print("\nSTEP 2 -- the new plan, replayed from $100 at 5% of the morning roll:\n")
def good_ml(d):
    return [p for p in ns["boards"][d].get("picks", []) if p.get("market") == "ML" and p.get("odds") is not None
            and p.get("raw") is not None and p.get("calibrated") is not None
            and p["raw"] > imp(p["odds"]) and p["calibrated"] > imp(p["odds"]) and p["calibrated"] >= 0.60]
def play(label, nprops, ml_on):
    B = 100.0; lo = 100.0; n = w = 0; flat = 0.0; nm = 0
    for d in days:
        props = sorted([p for p in cand.get(d, []) if p["market"] != "ML"], key=lambda p: -p.get("ev", 0))[:nprops]
        mls = good_ml(d) if ml_on else []
        start = B
        for p in props + mls:
            r = grade(d, p)
            if r is None: continue
            n += 1; w += r; nm += p["market"] == "ML"
            ret = (dec(p["odds"]) - 1) if r else -1
            flat += ret; B += start * 0.05 * ret
        lo = min(lo, B)
    print("  %-46s %3d bets (%2d ML)  %3d-%-3d  ROI %+6.1f%%   $100 -> $%-5.0f low $%.0f" % (label, n, nm, w, n - w, 100 * flat / max(n, 1), B, lo))
play("old: top 5/day ML or props", 5, False) if False else None
play("props only, top 4/day", 4, False)
play("props top 4/day + ML only if model 60%+", 4, True)
play("props top 5/day + ML only if model 60%+", 5, True)
