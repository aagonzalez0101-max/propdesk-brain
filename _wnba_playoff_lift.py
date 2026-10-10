"""How much do WNBA starters' numbers rise in the playoffs? (asked 2026-09-28)

Season-rate screens picked all UNDERS on stars going into playoff games, while those stars' minutes
jumped (Stewart 32->38, Wilson 31->35). This measures the playoff/regular-season ratio for starters
(24+ reg-season minutes, 2+ playoff games) over 2023-2026, from ESPN gamelogs. Cached per request.
"""
import requests, json, os, statistics, collections
from concurrent.futures import ThreadPoolExecutor
H = {"User-Agent": "Mozilla/5.0"}
W = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba"
CW = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/wnba"
CACHE = "_wnba_gl_cache.json"
cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}

ath = []
for t in requests.get(W + "/teams", headers=H, timeout=25).json()["sports"][0]["leagues"][0]["teams"]:
    for a in requests.get(W + "/teams/%s/roster" % t["team"]["id"], headers=H, timeout=25).json().get("athletes", []):
        ath.append(a.get("id"))

def fetch(key):
    aid, yr = key
    k = "%s|%s" % (aid, yr)
    if k in cache: return k, cache[k]
    try:
        gl = requests.get(CW + "/athletes/%s/gamelog" % aid, params=dict(season=yr), headers=H, timeout=25).json()
    except Exception:
        return k, None
    names = [x.lower() for x in gl.get("names") or []]
    reg, po = [], []
    for sg in gl.get("seasonTypes") or []:
        isp = "post" in sg.get("displayName", "").lower()
        for cat in sg.get("categories", []):
            for e in cat.get("events", []):
                st = dict(zip(names, e.get("stats", [])))
                try: row = [float(st[c]) for c in ("minutes", "points", "totalrebounds", "assists")]
                except Exception: continue
                (po if isp else reg).append(row)
    return k, dict(reg=reg, po=po)

keys = [(a, y) for a in ath for y in (2023, 2024, 2025, 2026)]
with ThreadPoolExecutor(12) as ex:
    for k, v in ex.map(fetch, keys):
        if v is not None: cache[k] = v
json.dump(cache, open(CACHE, "w"))

R = collections.defaultdict(list); n = 0
for k, v in cache.items():
    reg, po = v["reg"], v["po"]
    if len(reg) < 20 or len(po) < 2: continue
    if statistics.mean(r[0] for r in reg) < 24: continue
    n += 1
    for i, s in enumerate(("MIN", "PTS", "REB", "AST")):
        a = statistics.mean(r[i] for r in reg); b = statistics.mean(r[i] for r in po)
        if a > 0: R[s].append(b / a)
    R["PRA"].append(sum(statistics.mean(r[i] for r in po) for i in (1, 2, 3)) /
                    sum(statistics.mean(r[i] for r in reg) for i in (1, 2, 3)))
print("player-seasons: starters (24+ reg min) with 2+ playoff games, 2023-2026: %d\n" % n)
print("  PLAYOFF avg / REGULAR-SEASON avg, median across player-seasons")
out = {}
for s in ("MIN", "PTS", "REB", "AST", "PRA"):
    v = sorted(R[s]); m = statistics.median(v); out[s] = m
    print("   %-4s x%.3f (%+.1f%%)   middle half x%.2f - x%.2f" % (s, m, 100 * (m - 1), v[len(v) // 4], v[3 * len(v) // 4]))
json.dump(out, open("_wnba_playoff_lift.json", "w"))
