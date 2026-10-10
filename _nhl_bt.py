"""NHL PROP BACKTEST -- goalie saves + skater shots on goal (2026-09-30). Same rules as the soccer backtest:
point-in-time features only, fit on 2024-25, judged on 2025-26 (+ the new season), several line definitions.

    python _nhl_bt.py [median|mean|minus]

Line proxy: measured 2026-09-30 on 59 live UD/PP shots-on-goal lines -> line = last-20 median (gap -0.08 UD, -0.24 PP).
  median : median of the last 20 relevant games, as an x.5 line (median 2 -> 2.5 half the time, 1.5 the other: we
           use median - 0.5 when the median is an integer, i.e. the line sits just under it)
  mean   : last-20 mean rounded to x.5
  minus  : floor(mean - 0.4) + 0.5
Features (all BEFORE the game): base = last-20 mean; opp = opponent's last-10 shots-for (saves) or shots-against (SOG)
over the league average to date; own = own team's last-10 shots-against (saves only); home; b2b = team played the day
before. Targets: every game a skater dressed in (TOI > 0); goalies only games they STARTED (starter confirmation is
known before the line matters).
"""
import sys, json, math, collections, datetime
import numpy as np

MODE = sys.argv[1] if len(sys.argv) > 1 else "median"
R = json.load(open("_nhl_hist_rows.json"))
# team-game table
TG = {}
for r in R:
    k = (r["gid"], r["team"])
    if k not in TG:
        TG[k] = dict(date=r["date"], team=r["team"], opp=r["opp"], sf=r["team_sog"], sa=r["opp_sog"])
by_team = collections.defaultdict(list)
for t in TG.values():
    by_team[t["team"]].append(t)
for v in by_team.values():
    v.sort(key=lambda t: t["date"])
allg = sorted(TG.values(), key=lambda t: t["date"])
_lg = {}


def lg_avg(date):
    if date not in _lg:
        p = [t["sf"] for t in allg if t["date"] < date][-600:]
        _lg[date] = sum(p) / len(p) if len(p) > 100 else None
    return _lg[date]


def prior(team, date, n=10):
    return [t for t in by_team[team] if t["date"] < date][-n:]


def played_yesterday(team, date):
    y = (datetime.date.fromisoformat(date) - datetime.timedelta(days=1)).isoformat()
    return any(t["date"] == y for t in by_team[team])


def line_of(hist):
    m = sum(hist) / len(hist)
    if MODE == "mean":
        return max(0.5, math.floor(m) + 0.5)
    if MODE == "minus":
        return max(0.5, math.floor(m - 0.4) + 0.5)
    md = float(np.median(hist))
    return max(0.5, md - 0.5 if md.is_integer() else math.floor(md) + 0.5)


def data(market):
    by_p = collections.defaultdict(list)
    for r in R:
        if market == "saves":
            if r["pos"] == "G" and r.get("starter") and r.get("saves") is not None:
                by_p[r["pid"]].append(r)
        else:
            if r["pos"] != "G" and (r.get("toi") or 0) > 0 and r.get("sog") is not None:
                by_p[r["pid"]].append(r)
    key = "saves" if market == "saves" else "sog"
    X = []
    for pid, rows in by_p.items():
        rows.sort(key=lambda r: r["date"])
        for i, r in enumerate(rows):
            hist = [h[key] for h in rows[max(0, i - 20):i]]
            if len(hist) < 12:
                continue
            base = sum(hist) / len(hist)
            if market == "sog" and base < 1.0:
                continue                       # books post SOG lines for regular shooters, not 4th-liners
            la = lg_avg(r["date"])
            po, pw = prior(r["opp"], r["date"]), prior(r["team"], r["date"])
            if la is None or len(po) < 5 or len(pw) < 5:
                continue
            if market == "saves":
                opp = (sum(t["sf"] for t in po) / len(po)) / la
                own = (sum(t["sa"] for t in pw) / len(pw)) / la
            else:
                opp = (sum(t["sa"] for t in po) / len(po)) / la
                own = 1.0
            X.append(dict(season=r["season"], date=r["date"], name=r["name"], actual=r[key], base=base, hist=hist,
                          opp=opp, own=own, home=1.0 if r["home"] else 0.0, b2b=1.0 if played_yesterday(r["team"], r["date"]) else 0.0))
    return X


def p_over(mu, L, market):
    if market == "saves":                        # saves ~ normal with sd ~ sqrt(1.4 mu) (measured spread of saves)
        sd = math.sqrt(1.4 * max(mu, 1))
        return 0.5 * math.erfc((L - mu) / (sd * math.sqrt(2)))
    k = int(math.floor(L)); lam = max(mu, .05)
    return 1 - sum(math.exp(-lam) * lam ** j / math.factorial(j) for j in range(k + 1))


def run(market):
    X = data(market)
    tr = [x for x in X if x["season"] == "2024"]
    te = [x for x in X if x["season"] in ("2025", "2026")]
    feats = (lambda d: [math.log(d["opp"]), math.log(d["own"]), d["home"], d["b2b"]]) if market == "saves" else             (lambda d: [math.log(d["opp"]), d["home"], d["b2b"]])
    A = np.array([feats(d) + [1] for d in tr]); y = np.array([math.log(d["actual"] + 1) - math.log(d["base"] + 1) for d in tr])
    b, *_ = np.linalg.lstsq(A, y, rcond=None)
    res = y - A @ b; s2 = res @ res / (len(y) - A.shape[1]); se = np.sqrt(np.diag(s2 * np.linalg.inv(A.T @ A)))
    print("\n=== %s  (line=%s)  train %d / test %d ===" % (market.upper(), MODE, len(tr), len(te)))
    names = ("log(opp)", "log(own)", "home", "b2b", "const") if market == "saves" else ("log(opp)", "home", "b2b", "const")
    for nm, bi, si in zip(names, b, se):
        print("   %-9s %+.4f (t=%+.1f)" % (nm, bi, bi / si if si else 0))
    rows = []
    for d in te:
        L = line_of(d["hist"])
        if d["actual"] == L:
            continue
        mu = math.exp(math.log(d["base"] + 1) + np.dot(b, feats(d) + [1])) - 1
        rows.append((p_over(mu, L, market), p_over(d["base"], L, market), d["actual"] > L, d, L))
    base_over = sum(r[2] for r in rows) / len(rows)
    print("   overs hit on %.1f%% of test games at this line (a fair line is ~50%%)" % (100 * base_over))
    def rep(lbl, sel):
        if not sel:
            print("   %-24s none" % lbl); return
        n = len(sel); w = sum(sel); p = w / n
        print("   %-24s %6d picks  hit %.1f%%  z vs 53.5%% (UD 2-pick): %+.1f  vs 57.7%% (PP): %+.1f" % (
            lbl, n, 100 * p, (p - .535) / math.sqrt(.535 * .465 / n), (p - .577) / math.sqrt(.577 * .423 / n)))
    rep("no-adjust baseline >=58%", [(r[1] >= .5) == r[2] for r in rows if max(r[1], 1 - r[1]) >= .58])
    for lo, hi in ((.54, .58), (.58, .62), (.62, .68), (.68, 1.01)):
        rep("model %d-%d%%" % (lo * 100, hi * 100), [(r[0] >= .5) == r[2] for r in rows if lo <= max(r[0], 1 - r[0]) < hi])
    for side in ("over", "under"):
        rep("model >=58%% %s only" % side, [(r[0] >= .5) == r[2] for r in rows if max(r[0], 1 - r[0]) >= .58 and ((r[0] >= .5) == (side == "over"))])
    by = collections.defaultdict(list)
    for r in rows:
        if max(r[0], 1 - r[0]) >= .58:
            by[r[3]["season"]].append((r[0] >= .5) == r[2])
    print("   by season: " + "  ".join("%s %d-%d" % (k, sum(v), len(v) - sum(v)) for k, v in sorted(by.items())))
    return rows


if __name__ == "__main__":
    for m in (sys.argv[2:] or ["saves", "sog"]):
        run(m)
