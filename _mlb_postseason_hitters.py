"""Do hitter prop rates (HRR 0.5+, Hits 0.5+) carry over from the regular season into the postseason?
Every postseason box score 2021-2025 vs the SAME hitters' same-season regular-season game logs."""
import requests, collections, statistics, math
from concurrent.futures import ThreadPoolExecutor
H = {"User-Agent": "Mozilla/5.0"}; S = "https://statsapi.mlb.com/api/v1"
pks = []
for yr in range(2021, 2026):
    d = requests.get(S + "/schedule", params=dict(sportId=1, season=yr, gameType="F,D,L,W"), headers=H, timeout=60).json()
    for dt in d.get("dates", []):
        for g in dt.get("games", []):
            if g["status"]["detailedState"] == "Final": pks.append((yr, g["gamePk"]))
def box(k):
    yr, pk = k
    try: b = requests.get(S + "/game/%d/boxscore" % pk, headers=H, timeout=30).json()
    except Exception: return []
    out = []
    for side in ("away", "home"):
        for p in (b["teams"][side].get("players") or {}).values():
            st = (p.get("stats") or {}).get("batting") or {}
            if (st.get("plateAppearances") or 0) >= 3:
                out.append((yr, p["person"]["id"], (st.get("hits") or 0) + (st.get("runs") or 0) + (st.get("rbi") or 0), st.get("hits") or 0))
    return out
with ThreadPoolExecutor(12) as ex: post = [r for part in ex.map(box, pks) for r in part]
print("postseason hitter-games (3+ PA): %d from %d games" % (len(post), len(pks)))
keys = sorted({(yr, pid) for yr, pid, _, _ in post})
def reg(k):
    yr, pid = k
    try:
        d = requests.get(S + "/people/%d/stats" % pid, params=dict(stats="gameLog", group="hitting", season=yr, gameType="R"), headers=H, timeout=25).json()
        sp = (d.get("stats") or [{}])[0].get("splits") or []
        v = [((s["stat"].get("hits") or 0) + (s["stat"].get("runs") or 0) + (s["stat"].get("rbi") or 0), s["stat"].get("hits") or 0)
             for s in sp if (s["stat"].get("plateAppearances") or 0) >= 3]
        return k, v
    except Exception: return k, []
with ThreadPoolExecutor(12) as ex: R = dict(ex.map(reg, keys))
exp_hrr = obs_hrr = exp_h = obs_h = n = 0
for yr, pid, hrr, h in post:
    v = R.get((yr, pid)) or []
    if len(v) < 40: continue
    n += 1
    exp_hrr += sum(1 for a, _ in v if a > 0.5) / len(v); obs_hrr += hrr > 0.5
    exp_h += sum(1 for _, b in v if b > 0.5) / len(v); obs_h += h > 0.5
print("scored (hitter had 40+ regular-season starts): %d\n" % n)
for lbl, e, o in (("HRR 0.5+", exp_hrr, obs_hrr), ("Hits 0.5+", exp_h, obs_h)):
    pe, po = e / n, o / n
    z = (po - pe) / math.sqrt(pe * (1 - pe) / n)
    print("  %-10s regular-season rate says %.1f%% | postseason actual %.1f%% | %+.1fpp, z = %+.2f" % (lbl, 100 * pe, 100 * po, 100 * (po - pe), z))
