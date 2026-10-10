"""Grade every ML pick the boards have ever produced, by verdict tier.

live_paper.jsonl only holds the handful of tickets actually placed, which is
too small to say anything. The boards hold every ML pick the model made
whether or not it was bet, and that is the population the tier record should
be measured on.
"""
import json, io, sys, glob, os, urllib.request, collections
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace", write_through=True)

# one pick per (day, game, selection) -- keep the LAST build of each day so a
# rebuilt board does not double-count the same game
picks = {}
for path in sorted(glob.glob("pp/boards/*.json")):
    try:
        b = json.load(open(path, encoding="utf-8"))
    except Exception as exc:
        # a board written by a run that died mid-dump is truncated, not wrong;
        # the versioned rebuild of the same day supersedes it, so skip and say so
        print("  SKIP corrupt board %s (%s)" % (os.path.basename(path), exc))
        continue
    day = b.get("day") or os.path.basename(path)[:10]
    for r in b.get("picks", []):
        if r.get("market") != "ML":
            continue
        if r.get("verdict") not in ("STRONG", "WORTH IT", "CONSIDER"):
            continue
        picks[(day, r["game"], r["selection"])] = r

print("distinct ML picks on the boards: %d" % len(picks))

finals = {}
for day in sorted({k[0] for k in picks}):
    u = ("https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=%s"
         "&fields=dates,games,teams,home,away,score,team,name,status,detailedState" % day)
    try:
        s = json.load(urllib.request.urlopen(u, timeout=45))
    except Exception as exc:
        print("  %s: %s" % (day, exc)); continue
    for d in s["dates"]:
        for g in d["games"]:
            h, a = g["teams"]["home"], g["teams"]["away"]
            finals[(day, "%s @ %s" % (a["team"]["name"], h["team"]["name"]))] = (
                a.get("score"), h.get("score"), g["status"]["detailedState"])

def dec(o):
    return 1 + (o / 100 if o > 0 else 100 / -o)

tier = collections.defaultdict(lambda: [0, 0, 0.0])
graded = []
for (day, game, sel), r in sorted(picks.items()):
    f = finals.get((day, game))
    if not f or f[2] != "Final" or f[0] is None:
        continue
    a, h = f[0], f[1]
    picked_home = sel == game.split(" @ ")[1]
    won = (h > a) if picked_home else (a > h)
    t = tier[r["verdict"]]
    t[0 if won else 1] += 1
    t[2] += (dec(r["odds"]) - 1) if won else -1
    graded.append((day, game, sel, r["verdict"], r["odds"], won,
                   r.get("calibrated"), r.get("market_prob")))

print("\n%-10s %6s %6s %8s %9s" % ("verdict", "W", "L", "units", "ROI"))
allt = [0, 0, 0.0]
for v in ("STRONG", "WORTH IT", "CONSIDER"):
    t = tier[v]
    n = t[0] + t[1]
    if not n: continue
    allt[0] += t[0]; allt[1] += t[1]; allt[2] += t[2]
    print("%-10s %6d %6d %8.2f %8.1f%%" % (v, t[0], t[1], t[2], 100 * t[2] / n))
n = allt[0] + allt[1]
print("%-10s %6d %6d %8.2f %8.1f%%" % ("ALL", allt[0], allt[1], allt[2],
                                       100 * allt[2] / max(n, 1)))

# calibration: does the model's probability track reality?
print("\ncalibration by model probability")
bk = collections.defaultdict(lambda: [0, 0, 0.0])
for g in graded:
    p = g[6]
    if p is None: continue
    k = "%.2f-%.2f" % (int(p * 20) / 20.0, int(p * 20) / 20.0 + 0.05)
    bk[k][0] += 1; bk[k][1] += g[5]; bk[k][2] += p
for k in sorted(bk):
    v = bk[k]
    print("  %-12s n=%3d  model %.1f%%  actual %.1f%%" %
          (k, v[0], 100 * v[2] / v[0], 100 * v[1] / v[0]))

json.dump(graded, open("_mltier.json", "w"), default=str)
print("\nlast 10 graded:")
for g in graded[-10:]:
    print("  %s %-42s %-9s %+6.0f %s" % (g[0], (g[2])[:42], g[3], g[4], "W" if g[5] else "L"))
