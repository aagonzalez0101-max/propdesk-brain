"""Soccer BOTH TEAMS TO SCORE, priced off Pinnacle's closing 1X2 + over/under 2.5.

The 1X2 fixes the goal SUPREMACY, the over/under fixes the goal TOTAL. Two numbers -> two Poisson
rates (home, away) -> P(BTTS) = (1 - e^-lh)(1 - e^-la). No player or team model; the sharp market
supplies both inputs. Then: (1) does that fair number match reality, and (2) does the gut method
-- each team's own BTTS% -- add anything on top of it?
"""
import glob, io, csv, math, sys, collections
import numpy as np
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", write_through=True)
from scipy.stats import poisson
from scipy.optimize import minimize

def f(x):
    try: return float(x)
    except Exception: return None

# Precompute a grid of Poisson rate pairs once; each match is then a nearest-neighbour lookup.
# (A Nelder-Mead fit per match took >10 minutes on 30k matches.)
from scipy.spatial import cKDTree
_k = np.arange(11)
_L = np.linspace(0.15, 3.6, 140)
_G, _P = [], []
_tot = np.add.outer(_k, _k)
for lh in _L:
    ph = poisson.pmf(_k, lh)
    for la in _L:
        M = np.outer(ph, poisson.pmf(_k, la))
        _G.append((np.tril(M, -1).sum(), np.triu(M, 1).sum(), M[_tot >= 3].sum()))
        _P.append((lh, la))
_G = np.array(_G); _P = np.array(_P); _tree = cKDTree(_G)

def rates(pH, pA, pO):
    return _P[_tree.query([pH, pA, pO])[1]]

rows = []
for fn in sorted(glob.glob("soccer_fd/*.csv")):
    for x in csv.DictReader(io.StringIO(open(fn, encoding="latin-1").read())):
        o = [f(x.get(c)) for c in ("PSCH", "PSCD", "PSCA", "PC>2.5", "PC<2.5")]
        hg, ag = f(x.get("FTHG")), f(x.get("FTAG"))
        if None in o or hg is None or ag is None or min(o) <= 1: continue
        ih, idr, ia = 1 / o[0], 1 / o[1], 1 / o[2]; s = ih + idr + ia
        io_, iu = 1 / o[3], 1 / o[4]
        rows.append(dict(date=x.get("Date"), fn=fn, home=x.get("HomeTeam"), away=x.get("AwayTeam"),
                         pH=ih / s, pA=ia / s, pO=io_ / (io_ + iu), btts=int(hg > 0 and ag > 0)))
print("matches with Pinnacle closing 1X2 + O/U 2.5: %d" % len(rows))
_idx = _tree.query(np.array([[r["pH"], r["pA"], r["pO"]] for r in rows]))[1]
for r, i in zip(rows, _idx):
    lh, la = _P[i]
    r["fair"] = (1 - math.exp(-lh)) * (1 - math.exp(-la))
b = np.array([r["btts"] for r in rows]); p = np.array([r["fair"] for r in rows])
print("actual BTTS rate %.1f%% | mean fair %.1f%% | bias %+.1fpp" % (100 * b.mean(), 100 * p.mean(), 100 * (b.mean() - p.mean())))
print("\n  %-14s %-8s %-10s %s" % ("fair BTTS", "n", "fair", "actual"))
for lo in np.arange(0.30, 0.75, 0.05):
    m = (p >= lo) & (p < lo + 0.05)
    if m.sum() > 200:
        print("  %-14s %-8d %-10s %s" % ("%.0f-%.0f%%" % (100 * lo, 100 * lo + 5), m.sum(),
              "%.1f%%" % (100 * p[m].mean()), "%.1f%%" % (100 * b[m].mean())))
# the gut method: each team's own prior BTTS% (last 20), walk-forward, on top of the fair number
hist = collections.defaultdict(list); X = []
for r in rows:  # files are season-ordered; within file date-ordered
    h, a = hist[r["home"]], hist[r["away"]]
    if len(h) >= 10 and len(a) >= 10:
        X.append((r["fair"], (np.mean(h[-20:]) + np.mean(a[-20:])) / 2, r["btts"]))
    hist[r["home"]].append(r["btts"]); hist[r["away"]].append(r["btts"])
X = np.array(X); resid = X[:, 2] - X[:, 0]; g = X[:, 1] - X[:, 0]
sl = np.polyfit(g, resid, 1)[0]; se = np.std(resid - sl * g) / (np.std(g) * math.sqrt(len(X)))
print("\n  GUT METHOD (teams' own recent BTTS%%) on top of the fair number: n=%d, slope %+.3f, t = %+.2f" % (len(X), sl, sl / se))
q = np.quantile(g, [0.2, 0.4, 0.6, 0.8])
for i, (lo, hi) in enumerate(zip([-9] + list(q), list(q) + [9])):
    m = (g >= lo) & (g < hi)
    print("   quintile %d  team-rate minus fair %+.3f   fair %.1f%%  actual %.1f%%" % (i + 1, g[m].mean(), 100 * X[m, 0].mean(), 100 * X[m, 2].mean()))
import pickle; pickle.dump(rows, open("_btts_rows.pkl", "wb"))
