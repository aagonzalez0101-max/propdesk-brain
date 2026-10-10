"""Tennis FIRST SET: priced off the sharp match line, plus the 'fast starter' test.

1. MAPPING. From 104k bo3 matches with closing match odds, measure the real P(win set 1) as a
   function of the de-vigged MATCH probability. A set is shorter than a match, so set-1
   probability sits closer to 50%. This gives a fair set-1 price from Pinnacle's own match line
   with no player model at all.
2. FAST STARTERS. The betting guides' main claim: some players win first sets more than their
   match odds imply. Walk-forward: each player's prior residual (set-1 wins minus mapping) --
   does it predict the NEXT set 1 beyond the mapping?
"""
import sys, io, math, collections
import numpy as np, pandas as pd
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", write_through=True)

d = pd.read_pickle("tennis_all.pkl")
d = d[d["mktp"].notna() & d["set1_p1"].notna() & (d["best_of"] == 3)].copy()
d = d.sort_values("date").reset_index(drop=True)
d["s1"] = d["set1_p1"].astype(float)
print("bo3 matches with match odds + set-1 result: %d" % len(d))

# --- 1. mapping, fit on the first 60%, checked on the last 40% ---
cut = int(len(d) * 0.6)
tr, te = d.iloc[:cut], d.iloc[cut:]
bins = np.linspace(0, 1, 21)
tr_b = pd.cut(tr["mktp"], bins)
m = tr.groupby(tr_b, observed=True)["s1"].mean()
mids = np.array([iv.mid for iv in m.index]); vals = m.values
fmap = lambda p: np.interp(p, mids, vals)
print("\n  MATCH prob -> SET 1 prob (fit 2000-%d, checked after):" % tr["date"].dt.year.max())
print("  %-12s %-12s %-12s %s" % ("match prob", "set1 fit", "set1 test", "n test"))
for lo in (0.10, 0.25, 0.40, 0.50, 0.60, 0.75, 0.90):
    s = te[(te["mktp"] >= lo - 0.025) & (te["mktp"] < lo + 0.025)]
    if len(s) > 200:
        print("  %-12s %-12s %-12s %d" % ("%.0f%%" % (100 * lo), "%.1f%%" % (100 * fmap(lo)),
              "%.1f%%" % (100 * s["s1"].mean()), len(s)))
d["s1fair"] = fmap(d["mktp"])

# --- 2. fast starters, walk-forward ---
res = collections.defaultdict(lambda: [0.0, 0])
rows = []
for r in d.itertuples(index=False):
    a = res[r.p1]; b = res[r.p2]
    if a[1] >= 15 and b[1] >= 15:
        rows.append((r.s1fair, a[0] / a[1] - b[0] / b[1], r.s1, r.date))
    e = r.s1fair
    res[r.p1][0] += r.s1 - e; res[r.p1][1] += 1
    res[r.p2][0] += (1 - r.s1) - (1 - e); res[r.p2][1] += 1
x = pd.DataFrame(rows, columns=["fair", "fs", "y", "date"])
print("\n  FAST-STARTER test (both players 15+ prior sets): n=%d" % len(x))
x["resid"] = x["y"] - x["fair"]
b = np.polyfit(x["fs"], x["resid"], 1)[0]
se = np.std(x["resid"] - b * x["fs"]) / (np.std(x["fs"]) * math.sqrt(len(x)))
print("  set-1 result minus fair, regressed on the fast-start gap: slope %+.3f, t = %+.2f" % (b, b / se))
x["q"] = pd.qcut(x["fs"], 5, labels=False)
print("  %-26s %-8s %-10s %s" % ("fast-start gap quintile", "n", "fair", "actual"))
for q in range(5):
    s = x[x["q"] == q]
    print("  %-26s %-8d %-10s %s" % ("Q%d (%+.3f)" % (q + 1, s["fs"].mean()), len(s),
          "%.1f%%" % (100 * s["fair"].mean()), "%.1f%%" % (100 * s["y"].mean())))
