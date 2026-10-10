"""Does the MLB first-five starter-ERA-gap edge carry over into the POSTSEASON? (2026-09-28)

Regular season 2026 (2,040 games): away F5 win % of decided by ERA gap (+ = away starter better)
  -3 22.9 | -2 32.0 | -1 40.6 | 0 46.6 | +1 55.1 | +2 63.6 | +3 63.0
Here: every postseason game 2019-2025, starters' final regular-season ERA (season is over, no leak),
first-five result from the linescore. Same buckets.
"""
import requests, json, collections, math
from concurrent.futures import ThreadPoolExecutor
H = {"User-Agent": "Mozilla/5.0"}; S = "https://statsapi.mlb.com/api/v1"
REG = {-3: .229, -2: .320, -1: .406, 0: .466, 1: .551, 2: .636, 3: .630}
games = []
for yr in range(2019, 2026):
    d = requests.get(S + "/schedule", params=dict(sportId=1, season=yr, gameType="F,D,L,W",
                     hydrate="probablePitcher,linescore"), headers=H, timeout=60).json()
    for dt in d.get("dates", []):
        for g in dt.get("games", []):
            if g["status"]["detailedState"] != "Final": continue
            inn = (g.get("linescore") or {}).get("innings") or []
            if len(inn) < 5: continue
            ap = (g["teams"]["away"].get("probablePitcher") or {}).get("id")
            hp = (g["teams"]["home"].get("probablePitcher") or {}).get("id")
            if not ap or not hp: continue
            ar = sum((i.get("away") or {}).get("runs") or 0 for i in inn[:5])
            hr = sum((i.get("home") or {}).get("runs") or 0 for i in inn[:5])
            games.append(dict(yr=yr, ap=ap, hp=hp, ar=ar, hr=hr, type=g.get("gameType")))
print("postseason games with both starters + 5 innings: %d" % len(games))
need = sorted({(g["ap"], g["yr"]) for g in games} | {(g["hp"], g["yr"]) for g in games})
def era(k):
    pid, yr = k
    try:
        d = requests.get(S + "/people/%d/stats" % pid, params=dict(stats="season", group="pitching", season=yr,
                         gameType="R"), headers=H, timeout=25).json()
        s = (d.get("stats") or [{}])[0].get("splits") or []
        if not s: return k, None
        st = s[0]["stat"]; return k, (float(st["era"]), float(st.get("inningsPitched") or 0))
    except Exception: return k, None
with ThreadPoolExecutor(10) as ex: E = dict(ex.map(era, need))
b = collections.defaultdict(lambda: [0, 0, 0]); used = 0
for g in games:
    a, h = E.get((g["ap"], g["yr"])), E.get((g["hp"], g["yr"]))
    if not a or not h or a[1] < 40 or h[1] < 40: continue
    used += 1
    k = max(-3, min(3, round(h[0] - a[0])))
    b[k][0] += 1; b[k][1] += g["ar"] > g["hr"]; b[k][2] += g["ar"] == g["hr"]
print("usable (both starters 40+ IP): %d\n" % used)
print("  %-5s %-6s %-8s %-10s %-10s %s" % ("gap", "games", "tie%", "PLAYOFFS", "REG 2026", "difference"))
num = den = 0
for k in sorted(b):
    n, w, t = b[k]; dcd = n - t
    if dcd < 5: continue
    p = w / dcd
    print("  %+-4d  %-6d %-8s %-10s %-10s %+.1fpp" % (k, n, "%.0f%%" % (100 * t / n), "%.1f%%" % (100 * p), "%.1f%%" % (100 * REG[k]), 100 * (p - REG[k])))
# does the gap still SORT outcomes? big gaps (|gap|>=2) backing the better starter
big = [(k, v) for k, v in b.items() if abs(k) >= 2]
bw = sum((v[1] if k > 0 else (v[0] - v[1] - v[2])) for k, v in big); bd = sum(v[0] - v[2] for k, v in big)
print("\n  better starter by 2+ ERA: wins %d of %d decided = %.1f%%   (regular season: ~63-68%%)" % (bw, bd, 100 * bw / bd if bd else 0))
if bd:
    se = math.sqrt(.5 * .5 / bd); print("  vs a coin flip: %+.1fpp, z = %+.2f" % (100 * (bw / bd - .5), (bw / bd - .5) / se))
