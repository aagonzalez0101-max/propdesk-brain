"""September backtest (2026-10-07, user: "can you backtest sept"). Only two markets have September lines on file:
  CS2  (cs2_priced_all.jsonl, from 9/17)  -> the CS2 direction filter as a $10 PrizePicks 2-pick run (3x), 5% stakes, min $1
  MLB  (prop_graded.jsonl, 9/1-9/20)      -> our MLB prop picks at the book's own odds, by market / side / confidence
NHL started 9/29; WNBA September prop lines were never archived -> neither can be backtested before 9/29."""
import json, datetime, collections, math
CT = datetime.timezone(datetime.timedelta(hours=-5))

# ---- CS2
cs = {}
for l in open("cs2_priced_all.jsonl", encoding="utf-8"):
    r = json.loads(l)
    if r.get("result") in ("W", "L") and r.get("actual") is not None:
        cs[(r["match_id"], r["player"], r["stat"], r["maps"], r["line"])] = r
legs = []
for r in cs.values():
    cut = 30.5 if r["kind"] == "k" else 16.5
    if r["line"] >= cut and r["model_mu"] < 0.95 * r["line"] and r["actual"] != r["line"]:
        day = datetime.datetime.fromisoformat(r["start"].replace("Z", "+00:00")).astimezone(CT).date().isoformat()
        legs.append(dict(day=day, game=r["match_id"], who=r["player"], win=r["actual"] < r["line"], conf=0.67 if (r.get("map_winp") or 1) < .45 else 0.62))
seen, L = set(), []
for l in sorted(legs, key=lambda l: -l["conf"]):
    if (l["day"], l["who"]) not in seen:
        seen.add((l["day"], l["who"])); L.append(l)
roll = 10.0
print("CS2 high-line UNDER filter, $10 start, PrizePicks 2-picks 3x, 5%% stakes (min $1)")
for day in sorted({l["day"] for l in L}):
    if day > "2026-09-30":
        break
    S = sorted([l for l in L if l["day"] == day], key=lambda l: -l["conf"]); used = set(); slips = []
    for i, a in enumerate(S):
        if i in used:
            continue
        j = next((j for j in range(i + 1, len(S)) if j not in used and S[j]["game"] != a["game"]), None)
        if j is not None:
            slips.append((a, S[j])); used |= {i, j}
    stake = max(1.0, round(0.05 * roll, 2)); net = 0; w = 0
    for a, b in slips:
        if roll < stake:
            break
        win = a["win"] and b["win"]; d = 2 * stake if win else -stake; roll += d; net += d; w += win
    lw = sum(l["win"] for l in S)
    print("  %s  legs %2d-%-2d  slips %d/%d  %+6.2f -> $%.2f" % (day[5:], lw, len(S) - lw, w, len(slips), net, roll))
allS = [l for l in L if l["day"] <= "2026-09-30"]
print("  CS2 Sept legs %d-%d (%.1f%%)  END $%.2f\n" % (sum(l["win"] for l in allS), len(allS) - sum(l["win"] for l in allS), 100 * sum(l["win"] for l in allS) / len(allS), roll))

# ---- MLB
M = [json.loads(l) for l in open("prop_graded.jsonl", encoding="utf-8")]
M = [r for r in M if r.get("won") is not None and r.get("odds")]
def dec(o): return 1 + (o / 100 if o > 0 else 100 / -o)
def rep(lab, X):
    if not X: return
    w = sum(r["won"] for r in X); roi = sum((dec(r["odds"]) - 1) if r["won"] else -1 for r in X) / len(X)
    be = sum(1 / dec(r["odds"]) for r in X) / len(X)
    print("  %-34s n=%5d  hit %5.1f%%  avg b/e %4.1f%%  ROI %+5.1f%%" % (lab, len(X), 100 * w / len(X), 100 * be, 100 * roi))
print("MLB prop picks 9/1-9/20 at the book's own odds (flat 1u)")
rep("ALL", M)
for k in sorted({r["market"] for r in M}):
    rep("market " + k, [r for r in M if r["market"] == k])
for s in ("OVER", "UNDER"):
    rep("side " + s, [r for r in M if r["side"] == s])
for lo, hi in ((0, .6), (.6, .65), (.65, .7), (.7, .75), (.75, 1.01)):
    rep("calibrated p %.2f-%.2f" % (lo, hi), [r for r in M if lo <= (r.get("cal") or 0) < hi])
rep("cal>=.65 AND season rate>=.65", [r for r in M if (r.get("cal") or 0) >= .65 and (r.get("season") or 0) >= .65])
rep("cal>=.65 AND season rate >= cal", [r for r in M if (r.get("cal") or 0) >= .65 and (r.get("season") or 0) >= (r.get("cal") or 0)])
