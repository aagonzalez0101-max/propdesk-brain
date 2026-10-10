"""NBA PROP BACKTEST (2026-09-30) -- points / rebounds / assists / PRA on the 2025-26 season (nba_logs.json).
Fit on games before 2026-01-15, judged after. Same safeguards as NHL/soccer: point-in-time only, three line proxies,
targets = every game of a player who STARTED 4 of his previous 5 (knowable pre-game), minutes NOT filtered on the target.

    python _nba_bt.py
"""
import json, math, collections, datetime
import numpy as np

L = json.load(open("nba_logs.json"))
rows = [g for v in L.values() for g in v if g.get("min") is not None]
SPLIT = "2026-01-15"
for g in rows:
    g["pra"] = (g.get("pts") or 0) + (g.get("reb") or 0) + (g.get("ast") or 0)
# team-game allowed table: what each opponent gives up, per stat
tg = collections.defaultdict(lambda: collections.defaultdict(float))
for g in rows:
    k = (g["game"], g["opp"])                 # stats scored AGAINST team g["opp"]
    for s in ("pts", "reb", "ast", "pra"):
        tg[k][s] += g.get(s) or 0
    tg[k]["date"] = g["date"]; tg[k]["team"] = g["opp"]
allowed = collections.defaultdict(list)
for (gid, team), v in tg.items():
    allowed[team].append(v)
for v in allowed.values():
    v.sort(key=lambda x: x["date"])
lgday = sorted(tg.values(), key=lambda x: x["date"])


def opp_factor(team, date, s):
    p = [x[s] for x in allowed[team] if x["date"] < date][-10:]
    lg = [x[s] for x in lgday if x["date"] < date][-600:]
    if len(p) < 5 or len(lg) < 100:
        return None
    return (sum(p) / len(p)) / (sum(lg) / len(lg))


team_dates = collections.defaultdict(set)
for g in rows:
    team_dates[g["team"]].add(g["date"])
by_p = collections.defaultdict(list)
for g in rows:
    by_p[g["pid"]].append(g)
for v in by_p.values():
    v.sort(key=lambda g: g["date"])


def line_of(hist, mode):
    m = sum(hist) / len(hist)
    if mode == "median":
        md = float(np.median(hist)); return md - 0.5 if md.is_integer() else math.floor(md) + 0.5
    if mode == "minus":
        return math.floor(m - 0.4) + 0.5
    return math.floor(m) + 0.5


def run(stat, mode):
    X = []
    for pid, G in by_p.items():
        for i, g in enumerate(G):
            prev = G[:i]
            if len(prev) < 10 or sum(bool(h.get("starter")) for h in prev[-5:]) < 4:
                continue
            full = [h for h in prev if (h.get("min") or 0) >= 0.85 * (sum(x["min"] for x in prev[-5:]) / 5)][-15:]
            hist = [h[stat] for h in full]
            if len(hist) < 8 or sum(hist) / len(hist) < (8 if stat in ("pts", "pra") else 3):
                continue
            f = opp_factor(g["opp"], g["date"], stat)
            if f is None:
                continue
            y = (datetime.date.fromisoformat(g["date"]) - datetime.timedelta(days=1)).isoformat()
            X.append(dict(date=g["date"], actual=g[stat], base=sum(hist) / len(hist), hist=hist, f=f,
                          b2b=1.0 if y in team_dates[g["team"]] else 0.0))
    tr = [x for x in X if x["date"] < SPLIT]; te = [x for x in X if x["date"] >= SPLIT]
    A = np.array([[math.log(x["f"]), x["b2b"], 1] for x in tr]); yv = np.array([math.log(x["actual"] + 1) - math.log(x["base"] + 1) for x in tr])
    b, *_ = np.linalg.lstsq(A, yv, rcond=None)
    res = yv - A @ b; se = np.sqrt(np.diag(res @ res / (len(yv) - 3) * np.linalg.inv(A.T @ A)))
    out = []
    for x in te:
        Ln = line_of(x["hist"], mode)
        if x["actual"] == Ln:
            continue
        mu = math.exp(math.log(x["base"] + 1) + b[0] * math.log(x["f"]) + b[1] * x["b2b"] + b[2]) - 1
        sd = max(float(np.std(x["hist"])), 1.0)
        po = 0.5 * math.erfc((Ln - mu) / (sd * math.sqrt(2)))
        out.append((po, x["actual"] > Ln))
    fair = sum(o[1] for o in out) / len(out)
    print("%-4s line=%-6s opp t=%+.1f b2b t=%+.1f const %+.3f | overs %.1f%% at line | " % (
        stat, mode, b[0] / se[0], b[1] / se[1], b[2], 100 * fair), end="")
    for lo, hi in ((.58, .62), (.62, .68), (.68, 1.01)):
        sel = [(o[0] >= .5) == o[1] for o in out if lo <= max(o[0], 1 - o[0]) < hi]
        ov = sum(o[0] >= .5 for o in out if lo <= max(o[0], 1 - o[0]) < hi)
        if sel:
            print("%d-%d%%: %.1f%% n=%d (%d%% ov)  " % (lo * 100, hi * 100, 100 * sum(sel) / len(sel), len(sel), 100 * ov / len(sel)), end="")
    print()


if __name__ == "__main__":
    for s in ("pts", "reb", "ast", "pra"):
        for m in ("median", "minus", "mean"):
            run(s, m)
