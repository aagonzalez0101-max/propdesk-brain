"""Dota 2 MAPS 1-2 kills model -- walk-forward backtest on every pro series since July (2026-10-08, user: "we need hella like we
did for CS2"). There is no archive of past PrizePicks Dota lines, so this tests CALIBRATION: for each player in each series, the
model (last 30 maps before the series, pair-resampled) gives P(maps 1-2 kills > L) for lines around his average; we check how often
that actually happened. A calibrated model is what makes the live line comparison meaningful.
    python _dota_bt.py
"""
import json, random, collections, datetime

R = [json.loads(l) for l in open("dota_matches.jsonl", encoding="utf-8")]
by_match = collections.defaultdict(list)
for r in R:
    by_match[r["match_id"]].append(r)
# series = consecutive maps between the same two teams within 10 hours
maps = []
for mid, rows in by_match.items():
    t = sorted({r["team"] or "?" for r in rows})
    if len(t) == 2 and "?" not in t:
        maps.append((rows[0]["date"], mid, tuple(t), rows))
maps.sort(key=lambda x: x[1])                                   # match ids increase with time
series, cur = [], None
for d, mid, teams, rows in maps:
    if cur and cur["teams"] == teams and mid - cur["last"] < 3_000_000:
        cur["maps"].append(rows); cur["last"] = mid
    else:
        cur = dict(teams=teams, maps=[rows], last=mid, first=mid); series.append(cur)
hist = collections.defaultdict(list)                             # player -> [(match_id, kills)]
for d, mid, teams, rows in maps:
    for r in rows:
        hist[r["name"]].append((mid, r["kills"]))
random.seed(3)
out = []
for s in series:
    if len(s["maps"]) < 2:
        continue
    m1, m2 = s["maps"][0], s["maps"][1]
    k2 = collections.Counter()
    for r in m1 + m2:
        k2[r["name"]] += r["kills"]
    for nm, actual in k2.items():
        prev = [k for mid, k in hist[nm] if mid < s["first"]][-30:]
        if len(prev) < 12:
            continue
        sims = [random.choice(prev) + random.choice(prev) for _ in range(2000)]
        mu = sum(sims) / len(sims)
        for f in (0.75, 0.9, 1.0, 1.1, 1.25):
            L = round(mu * f) + 0.5
            po = sum(x > L for x in sims) / len(sims)
            side = "over" if po >= .5 else "under"; p = max(po, 1 - po)
            out.append(dict(p=p, side=side, win=(actual > L) == (side == "over"), f=f, mu=mu, L=L))
print("DOTA walk-forward: %d series with 2+ maps, %d player-line tests" % (sum(1 for s in series if len(s["maps"]) >= 2), len(out)))
print("  model says      n      actually hit")
for lo, hi in ((.5, .55), (.55, .6), (.6, .65), (.65, .7), (.7, .75), (.75, .8), (.8, .9), (.9, 1.01)):
    X = [o for o in out if lo <= o["p"] < hi]
    if X:
        print("  %3.0f-%3.0f%%   %6d   %5.1f%%   (overs %d / unders %d)" % (100 * lo, 100 * min(hi, 1), len(X), 100 * sum(o["win"] for o in X) / len(X),
              sum(o["side"] == "over" for o in X), sum(o["side"] == "under" for o in X)))
for side in ("over", "under"):
    X = [o for o in out if o["side"] == side and o["p"] >= .62]
    print("  %s, model 62%%+: n=%d hit %.1f%%" % (side, len(X), 100 * sum(o["win"] for o in X) / max(len(X), 1)))
