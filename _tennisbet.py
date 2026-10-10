"""Tennis MONEYLINE: the betting backtest the 2026-09-04 run never did.

`tennisval.log` reported Brier skill +0.0367 vs the market's +0.0483 ("model beats market: no")
and an encompassing term of c = -0.0217, t = -6.01, then called that "model ADDS information".
It does -- but the SIGN IS NEGATIVE, which is the same shape as [[project-mlb-ml-inverted]]:
the model is wrong in a predictable direction, so the play would be to FADE it, not follow it.

Brier skill and encompassing are diagnostics. The gate is whether betting it makes money at the
CLOSING PRICE, after vig. That is what this measures, in both directions.
"""
import sys, io, math
import numpy as np
import pandas as pd
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", write_through=True)

K_BASE, SURF_W, BURN_IN = 24.0, 0.35, 20

d = pd.read_pickle("tennis_all.pkl")
d = d[d["mktp"].notna() & d["odds1"].notna() & d["odds2"].notna()].copy()
d = d.sort_values("date").reset_index(drop=True)
print("%d priced matches, %s .. %s" % (len(d), d["date"].min().date(), d["date"].max().date()))

elo, elo_s, n_played = {}, {}, {}
rating = lambda p, s: (1 - SURF_W) * elo.get(p, 1500.0) + SURF_W * elo_s.get((p, s), 1500.0)
mp, rd = [], []
for r in d.itertuples(index=False):
    r1, r2 = rating(r.p1, r.surface), rating(r.p2, r.surface)
    mp.append(1.0 / (1.0 + 10 ** ((r2 - r1) / 400.0)))
    rd.append(n_played.get(r.p1, 0) >= BURN_IN and n_played.get(r.p2, 0) >= BURN_IN)
    for (a, b, ya) in ((r.p1, r.p2, r.y), (r.p2, r.p1, 1 - r.y)):
        e = 1.0 / (1.0 + 10 ** ((elo.get(b, 1500.0) - elo.get(a, 1500.0)) / 400.0))
        elo[a] = elo.get(a, 1500.0) + K_BASE * (ya - e)
        es = 1.0 / (1.0 + 10 ** ((elo_s.get((b, r.surface), 1500.0) - elo_s.get((a, r.surface), 1500.0)) / 400.0))
        elo_s[(a, r.surface)] = elo_s.get((a, r.surface), 1500.0) + K_BASE * (ya - es)
        n_played[a] = n_played.get(a, 0) + 1
d["model"], d["ready"] = mp, rd
u = d[d["ready"]].copy()
# de-vig the two-way price so "edge" is against a fair number, not against the hold
inv = 1 / u["odds1"] + 1 / u["odds2"]
u["fair1"] = (1 / u["odds1"]) / inv
u["hold"] = inv - 1
print("walk-forward sample: %d | mean hold %.2f%%\n" % (len(u), 100 * u["hold"].mean()))


def bet(sub, side):
    """side 'follow' backs the model's edge; 'fade' backs the opposite side."""
    if side == "follow":
        on1 = sub["model"] > sub["fair1"]
    else:
        on1 = sub["model"] < sub["fair1"]
    odds = np.where(on1, sub["odds1"], sub["odds2"])
    won = np.where(on1, sub["y"] == 1, sub["y"] == 0)
    ret = np.where(won, odds - 1.0, -1.0)
    return len(sub), ret.mean(), won.mean()


print("  %-10s %-9s %-10s %-11s %-11s" % ("edge", "n", "win%", "ROI follow", "ROI fade"))
for lo, hi in ((0.02, 0.04), (0.04, 0.06), (0.06, 0.08), (0.08, 0.12), (0.12, 1.0)):
    gap = (u["model"] - u["fair1"]).abs()
    sub = u[(gap >= lo) & (gap < hi)]
    if len(sub) < 500:
        continue
    n, rf, wf = bet(sub, "follow")
    _, rv, wv = bet(sub, "fade")
    print("  %-10s %-9d %-10s %-11s %-11s" % ("%.0f-%.0f%%" % (100 * lo, 100 * hi), n,
          "%.1f%%" % (100 * wf), "%+.2f%%" % (100 * rf), "%+.2f%%" % (100 * rv)))
n, rf, wf = bet(u, "follow")
_, rv, _ = bet(u, "fade")
print("  %-10s %-9d %-10s %-11s %-11s" % ("ALL", n, "%.1f%%" % (100 * wf), "%+.2f%%" % (100 * rf), "%+.2f%%" % (100 * rv)))
se = np.std(np.where(np.array(u["model"] > u["fair1"]), 1, 1)) / math.sqrt(len(u))
print("\n  a fair coin at this vig returns %.2f%%" % (-100 * u["hold"].mean() / (1 + u["hold"].mean())))
print("\n  BY TOUR:")
for t in ("atp", "wta"):
    s = u[u["tour"] == t]
    n, rf, wf = bet(s, "follow"); _, rv, _ = bet(s, "fade")
    print("   %-5s n=%-7d follow %+.2f%%   fade %+.2f%%" % (t, n, 100 * rf, 100 * rv))
print("\n  BY ERA (has the edge decayed?):")
for yr0, yr1 in ((2002, 2010), (2010, 2016), (2016, 2021), (2021, 2027)):
    s = u[(u["date"].dt.year >= yr0) & (u["date"].dt.year < yr1)]
    if len(s) < 1000:
        continue
    n, rf, wf = bet(s, "follow"); _, rv, _ = bet(s, "fade")
    print("   %d-%d  n=%-7d follow %+.2f%%   fade %+.2f%%" % (yr0, yr1 - 1, n, 100 * rf, 100 * rv))
