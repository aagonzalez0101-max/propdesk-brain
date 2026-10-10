"""Golf model tuning (2026-10-01): grid over half-life / prior weight / prior level, walk-forward RMSE and bias, plus bias by
skill tier (were elite players projected too high?)."""
import math, statistics as st, json, sys
from collections import defaultdict
import _golf as G
R = G.load()
by = defaultdict(list)
for r in R:
    by[(r["event"], r["round"])].append(r)
keys = sorted(by, key=lambda k: (by[k][0]["start"], k[0], k[1]))
maxround = {}
for e, rd in by:
    maxround[e] = max(maxround.get(e, 0), rd)

def run(half, prior, pw, tiers=False):
    G.HALF, G.PRIOR, G.PRIOR_W = half, prior, pw
    M = G.Model(); ev_rounds = defaultdict(list); errs = []; tier = defaultdict(list)
    for k in keys:
        rows = by[k]
        if len(rows) < 20: continue
        ev, rd = k; name, par = rows[0]["name"], rows[0]["par"]
        fexp = M.field_expect(name, par, ev_rounds[ev]); favg = st.mean(r["strokes"] for r in rows)
        for r in rows:
            sk = M.player_skill(r["player_id"])
            if M.skill[r["player_id"]][1] >= 8:
                e = r["strokes"] - (fexp + sk); errs.append(e)
                if tiers: tier[min(4, max(0, int((sk + 2.0) / 1.0)))].append((e, rd))
        for r in rows: M.update(r["player_id"], r["strokes"] - favg)
        ev_rounds[ev].append(favg)
        if rd == maxround[ev]: M.event_hist[name].append(st.mean(ev_rounds[ev]))
    rm = math.sqrt(sum(e * e for e in errs) / len(errs))
    return rm, st.mean(errs), tier

best = None
for half in (20, 40, 80, 160):
    for pw in (3, 6, 12):
        for prior in (0.5, 0.8, 1.2):
            rm, b, _ = run(half, prior, pw)
            if not best or rm < best[0]: best = (rm, b, half, pw, prior)
            print("half %-4d pw %-3d prior %.1f  RMSE %.3f  bias %+.3f" % (half, pw, prior, rm, b), flush=True)
print("\nBEST: RMSE %.3f bias %+.3f  half=%d pw=%d prior=%.1f" % best)
rm, b, tier = run(best[2], best[4], best[3], tiers=True)
labels = {0: "elite (skill < -1)", 1: "very good (-1..0)", 2: "average (0..+1)", 3: "below (+1..+2)", 4: "weak (+2+)"}
print("\nbias by skill tier (actual - projected; negative = we projected too HIGH):")
for t in sorted(tier):
    es = [e for e, _ in tier[t]]; r1 = [e for e, rd in tier[t] if rd == 1]; r2 = [e for e, rd in tier[t] if rd > 1]
    print("  %-22s n=%-6d bias %+.2f   R1 %+.2f   R2+ %+.2f" % (labels[t], len(es), st.mean(es), st.mean(r1) if r1 else 0, st.mean(r2) if r2 else 0))
json.dump(dict(half=best[2], pw=best[3], prior=best[4], rmse=best[0], bias=best[1]), open("_golf_tuned.json", "w"))
