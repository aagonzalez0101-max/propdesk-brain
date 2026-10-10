"""Pitcher props (K / ER / OUTS) on the September boards, graded against box scores (2026-09-29).
Every board pick, not just WORTH IT -- then sliced by model confidence and by own-rate agreement."""
import json, requests, collections
from concurrent.futures import ThreadPoolExecutor
ns = {}; exec(open("_top5_replay.py", encoding="utf-8").read().split("cand = collections")[0], ns)
boards, days, ids, norm, S, H, imp = ns["boards"], ns["days"], ns["ids"], ns["norm"], ns["S"], ns["H"], ns["imp"]
P = {}
for d in days:
    for p in boards[d].get("picks", []):
        if p.get("market") in ("K", "ER", "OUTS") and norm(p["selection"]) in ids and p.get("calibrated") is not None:
            P[(d, norm(p["selection"]), p["market"], p["line"], p["side"])] = dict(p, day=d)
pids = sorted({ids[k[1]][0] for k in P})
def gl(pid):
    try:
        r = requests.get(S + "/people/%d/stats" % pid, params=dict(stats="gameLog", group="pitching", season=2026),
                         headers=H, timeout=25).json()
        return pid, {x["date"]: x["stat"] for x in ((r.get("stats") or [{}])[0].get("splits") or [])}
    except Exception: return pid, {}
with ThreadPoolExecutor(12) as ex: LOG = dict(ex.map(gl, pids))
F = {"K": "strikeOuts", "ER": "earnedRuns", "OUTS": "outs"}
rows = []
for (d, nm, m, line, side), p in P.items():
    s = LOG.get(ids[nm][0], {}).get(d)
    if not s: continue
    v = s.get(F[m]) or 0
    if v == line: continue
    win = v > line if side == "OVER" else v < line
    rows.append(dict(p, win=win))
json.dump(rows, open("_pitcher_bt.json", "w"), default=str)
def show(lbl, R):
    if not R: return
    w = sum(r["win"] for r in R); n = len(R); hr = w / n
    se = (hr * (1 - hr) / n) ** .5
    print("  %-38s %4d  hit %5.1f%%  (+/- %.1f)   -130 b/e 56.5%%: %s   -150 b/e 60%%: %s" % (
        lbl, n, hr * 100, 1.96 * se * 100, "CLEARS" if hr - 1.96 * se > .565 else ("above" if hr > .565 else "no"),
        "CLEARS" if hr - 1.96 * se > .60 else ("above" if hr > .60 else "no")))
for m in ("K", "ER", "OUTS"):
    R = [r for r in rows if r["market"] == m]
    print("\n%s  (%d graded picks, %s days)" % (m, len(R), len({r['day'] for r in R})))
    show("all", R)
    for lo, hi in ((.5, .6), (.6, .65), (.65, .7), (.7, 1)):
        show("model %.0f-%.0f%%" % (lo * 100, hi * 100), [r for r in R if lo <= r["calibrated"] < hi])
    agree = [r for r in R if r["calibrated"] >= .6 and (r.get("season_rate") or 0) >= .6]
    show("model 60%+ AND own season rate 60%+", agree)
    show("  ...and last-5 60%+", [r for r in agree if (r.get("last5_rate") or 0) >= .6])
    for sd in ("OVER", "UNDER"):
        show("  %s side, model 60%%+ & own 60%%+" % sd, [r for r in agree if r["side"] == sd])
