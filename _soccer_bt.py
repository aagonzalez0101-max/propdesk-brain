"""SOCCER PROP BACKTEST -- the MLB standard applied to PrizePicks soccer (2026-09-30).

    python _soccer_bt.py

Markets: passes attempted, shots, shots on target, goalie saves (the four the user bets).
Everything is POINT-IN-TIME: a match only sees rows dated before it.

Line: PrizePicks sets soccer lines at the player's recent average (measured on 60 live lines 2026-09-30: median gap
~0). So the proxy line = mean of the player's previous 15 starts, rounded to the nearest 0.5; integer lines push.

Features per player-match (all from BEFORE the match):
  base   = player's mean over his previous 15 starts (60+ min)
  opp    = opponent's last-10 average of what it concedes (passes allowed / shots conceded / SOT conceded) or, for
           saves, what it creates (SOT created) -- divided by that league's average to date
  script = (team rolling xG diff) - (opponent rolling xG diff), last 10 matches each
  home   = 1/0
Model: log(actual+1) - log(base+1) = b1*log(opp) + b2*script + b3*home, fit on 2024/25 ONLY; judged on 2025/26 +
2026/27. A pick is made when the predicted mean sits far enough from the line; scored at PrizePicks break-evens
(57.7% 2-pick power, 54.5% 6-flex).
"""
import json, math, collections, datetime
import numpy as np

R = json.load(open("_soccer_hist_rows.json"))
MK = {"passes": ("passes", "o_passes"), "shots": ("shots", "o_shots"), "sot": ("sot", "o_sot"), "saves": ("saves", "o_sot")}
# what the opponent CONCEDES for outfield stats = the player's own team numbers vs that opponent; for saves = the
# opponent's shots on target created. Built from the team-match table below.

# ---------------- team-match table: one row per (match, team)
TM = {}
for r in R:
    k = (r["mid"], r["team"])
    if k not in TM and r.get("t_passes") is not None:
        TM[k] = dict(mid=r["mid"], lg=r["lg"], date=r["date"], team=r["team"], opp=r["opp"],
                     passes=r.get("t_passes"), shots=r.get("t_shots"), sot=r.get("t_sot"), xg=r.get("t_xg"),
                     o_passes=r.get("o_passes"), o_shots=r.get("o_shots"), o_sot=r.get("o_sot"), o_xg=r.get("o_xg"))
by_team = collections.defaultdict(list)
for t in TM.values():
    by_team[t["team"]].append(t)
for v in by_team.values():
    v.sort(key=lambda t: t["date"])
by_lg = collections.defaultdict(list)
for t in TM.values():
    by_lg[t["lg"]].append(t)
for v in by_lg.values():
    v.sort(key=lambda t: t["date"])


def team_prior(team, date, n=10):
    return [t for t in by_team.get(team, []) if t["date"] < date][-n:]


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


_lg_cache = {}


def league_avg(lg, date, key):
    k = (lg, date, key)
    if k not in _lg_cache:
        prior = [t[key] for t in by_lg[lg] if t["date"] < date and t.get(key) is not None][-400:]
        _lg_cache[k] = sum(prior) / len(prior) if len(prior) >= 40 else None
    return _lg_cache[k]


def strength(team, date):
    p = team_prior(team, date)
    if len(p) < 5:
        return None
    return mean([t["xg"] for t in p]) - mean([t["o_xg"] for t in p])


# ---------------- player histories
by_player = collections.defaultdict(list)
_seen = set()
for r in R:
    if (r.get("mins") or 0) > 0 and (r["mid"], r["pid"]) not in _seen:
        _seen.add((r["mid"], r["pid"]))
        by_player[r["pid"]].append(r)
for v in by_player.values():
    v.sort(key=lambda r: r["date"])

# what the opponent concedes, seen from the player's side: for passes/shots/sot the opponent's matches' "o_" numbers
# (what teams did AGAINST it); for saves, the opponent's own SOT created.
CONC = {"passes": "o_passes", "shots": "o_shots", "sot": "o_sot", "saves": "sot"}
LGKEY = {"passes": "passes", "shots": "shots", "sot": "sot", "saves": "sot"}


def dataset(market):
    X = []
    for pid, rows in by_player.items():
        for i, r in enumerate(rows):
            if r.get(market) is None or (market == "saves") != r["gk"]:
                continue
            prev = rows[:i]
            if len(prev) < 5 or sum((h.get("mins") or 0) >= 60 for h in prev[-5:]) < 4:
                continue                               # not an established starter going in -> no PP line expected
            starts = [h for h in prev if (h.get("mins") or 0) >= 60][-15:]
            hist = [h[market] for h in starts if h.get(market) is not None]
            if len(hist) < 8:
                continue
            base = sum(hist) / len(hist)
            if market == "saves" and base < 1:
                continue
            op = team_prior(r["opp"], r["date"])
            la = league_avg(r["lg"], r["date"], LGKEY[market])
            oc = mean([t[CONC[market]] for t in op]) if len(op) >= 5 else None
            s_t, s_o = strength(r["team"], r["date"]), strength(r["opp"], r["date"])
            if oc is None or la is None or s_t is None or s_o is None:
                continue
            X.append(dict(season=r["season"], lg=r["lg"], date=r["date"], name=r["name"], actual=r[market], base=base,
                          hist=hist, opp=oc / la, script=s_t - s_o, home=1.0 if r["home"] else 0.0))
    return X


OFFSET = {"passes": -1.0, "shots": 0.2, "sot": -0.15, "saves": -0.2}   # PP line minus 15-start avg, measured live
LINE_MODE = "measured"


def line_of(base, market="passes", hist=None):
    if LINE_MODE == "mean":
        x = base
    elif LINE_MODE == "median":
        x = float(np.median(hist))
    else:
        x = base + OFFSET.get(market, 0)
    return max(0.5, round(x * 2) / 2)


def p_over(mu, line, hist, disp):
    """P(X > line) from a negative binomial with the player's own dispersion (counts), or normal for passes."""
    if disp == "normal":
        sd = max(np.std(hist), 1.0)
        z = (line - mu) / sd
        return 0.5 * math.erfc(z / math.sqrt(2))
    lam = max(mu, 0.05)
    k = int(math.floor(line))
    cdf = sum(math.exp(-lam) * lam ** j / math.factorial(j) for j in range(k + 1))
    return 1 - cdf


def run(market):
    X = dataset(market)
    tr = [x for x in X if x["season"] in ("2024/2025", "2025") and x["lg"] != "MLS" or (x["lg"] == "MLS" and x["season"] == "2025")]
    te = [x for x in X if x not in tr]
    tr = [x for x in X if (x["lg"] != "MLS" and x["season"] == "2024/2025") or (x["lg"] == "MLS" and x["season"] == "2025")]
    te = [x for x in X if (x["lg"] != "MLS" and x["season"] in ("2025/2026", "2026/2027")) or (x["lg"] == "MLS" and x["season"] == "2026")]
    def design(D):
        A = np.array([[math.log(max(d["opp"], 0.2)), d["script"], d["home"]] for d in D])
        y = np.array([math.log(d["actual"] + 1) - math.log(d["base"] + 1) for d in D])
        return A, y
    A, y = design(tr)
    A1 = np.column_stack([A, np.ones(len(A))])
    b, *_ = np.linalg.lstsq(A1, y, rcond=None)
    # t-stats on the training fit
    res = y - A1 @ b
    s2 = res @ res / (len(y) - A1.shape[1])
    se = np.sqrt(np.diag(s2 * np.linalg.inv(A1.T @ A1)))
    print("\n=== %s: train %d / test %d player-matches ===" % (market.upper(), len(tr), len(te)))
    for nm, bi, si in zip(("log(opp)", "script", "home", "const"), b, se):
        print("   %-9s %+.4f  (t=%+.1f)" % (nm, bi, bi / si))
    disp = "normal" if market == "passes" else "count"
    rows = []
    for d in te:
        L = line_of(d["base"], market, d["hist"])
        if d["actual"] == L:
            continue
        mu = math.exp(math.log(d["base"] + 1) + b[0] * math.log(max(d["opp"], 0.2)) + b[1] * d["script"] + b[2] * d["home"] + b[3]) - 1
        po = p_over(mu, L, d["hist"], disp)
        po0 = p_over(d["base"], L, d["hist"], disp)        # the no-adjustment baseline
        rows.append((po, po0, d["actual"] > L, d))
    print("   baseline (no adjustment) picks the side with P>=0.577: ", end="")
    report([(max(r[1], 1 - r[1]), (r[1] >= .5) == r[2]) for r in rows if max(r[1], 1 - r[1]) >= .577])
    for lo, hi in ((.54, .577), (.577, .62), (.62, .68), (.68, 1.01)):
        sel = [(max(r[0], 1 - r[0]), (r[0] >= .5) == r[2]) for r in rows if lo <= max(r[0], 1 - r[0]) < hi]
        print("   model P %.0f-%.0f%%: " % (lo * 100, hi * 100), end=""); report(sel)
    for key in ("season", "lg"):
        g = collections.defaultdict(list)
        for r in rows:
            if max(r[0], 1 - r[0]) >= .577:
                g[r[3][key]].append((max(r[0], 1 - r[0]), (r[0] >= .5) == r[2]))
        print("   by %-6s: " % key + "  ".join("%s %d-%d" % (k, sum(x[1] for x in v), len(v) - sum(x[1] for x in v))
                                             for k, v in sorted(g.items())))
    ov = [r for r in rows if max(r[0], 1 - r[0]) >= .577]
    if ov:
        print("   of model picks >=57.7%%: %.0f%% overs" % (100 * sum(r[0] >= .5 for r in ov) / len(ov)))
    return b, rows


def report(sel):
    if not sel:
        print("none"); return
    n = len(sel); w = sum(x[1] for x in sel); p = w / n
    z = (p - .577) / math.sqrt(.577 * .423 / n)
    print("%5d picks  hit %.1f%%  (vs 57.7%% b/e: z=%+.1f)  flex-6 b/e 54.5%%: %s" % (n, 100 * p, z, "above" if p > .545 else "below"))


if __name__ == "__main__":
    import sys
    out = {}
    for mode in (sys.argv[1:] or ["measured", "mean", "median"]):
        LINE_MODE = mode
        print("")
        print("################ LINE = %s ################" % mode)
        for m in ("passes", "shots", "sot", "saves"):
            b, rows = run(m)
            out["%s_%s" % (mode, m)] = [float(x) for x in b]
    json.dump(out, open("_soccer_bt_coef.json", "w"), indent=1)
