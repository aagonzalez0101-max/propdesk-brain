"""Do playoff starters record fewer outs than their own regular-season average? (2026-09-29)"""
import requests, statistics as st
from concurrent.futures import ThreadPoolExecutor
H = {"User-Agent": "Mozilla/5.0"}; S = "https://statsapi.mlb.com/api/v1"
games = []
for yr in (2022, 2023, 2024, 2025):
    d = requests.get(S + "/schedule", params=dict(sportId=1, season=yr, gameType="F,D,L,W"), headers=H, timeout=60).json()
    games += [(yr, g["gamePk"]) for dt in d["dates"] for g in dt["games"] if g["status"]["detailedState"] == "Final"]
def box(a):
    yr, pk = a
    b = requests.get(S + "/game/%d/boxscore" % pk, headers=H, timeout=30).json()
    out = []
    for side in ("away", "home"):
        t = b["teams"][side]; sp = t["pitchers"][0]
        s = t["players"]["ID%d" % sp]["stats"]["pitching"]
        out.append((yr, sp, s.get("outs", 0)))
    return out
with ThreadPoolExecutor(16) as ex: starts = [x for r in ex.map(box, games) for x in r]
def season(a):
    yr, pid = a
    r = requests.get(S + "/people/%d/stats" % pid, params=dict(stats="season", group="pitching", season=yr, gameType="R"),
                     headers=H, timeout=30).json()
    sp = (r.get("stats") or [{}])[0].get("splits") or []
    if not sp: return a, None
    s = sp[0]["stat"]; gs = s.get("gamesStarted", 0)
    if gs < 10: return a, None
    ip = s["inningsPitched"]; w, f = ip.split(".") if "." in ip else (ip, "0")
    # outs per start approximation: regular-season outs / games started (relief outs are small for starters)
    return a, (int(w) * 3 + int(f)) / max(gs, s.get("gamesPlayed", gs)) if s.get("gamesPlayed", gs) > gs * 1.3 else (int(w) * 3 + int(f)) / gs
with ThreadPoolExecutor(16) as ex: SEA = dict(ex.map(season, {(y, p) for y, p, _ in starts}))
diff = [(o - SEA[(y, p)], o, SEA[(y, p)], y) for y, p, o in starts if SEA.get((y, p))]
d = [x[0] for x in diff]
m = st.mean(d); se = st.stdev(d) / len(d) ** .5
print("playoff starts with a 10+ GS regular season: %d" % len(d))
print("avg playoff outs %.1f vs same pitchers' regular-season %.1f  -> %+.2f outs (+/- %.2f), t=%.1f" % (
    st.mean(x[1] for x in diff), st.mean(x[2] for x in diff), m, 1.96 * se, m / se))
for y in (2022, 2023, 2024, 2025):
    dy = [x[0] for x in diff if x[3] == y]; print("  %d  n=%d  %+.2f outs" % (y, len(dy), st.mean(dy)))
import json; json.dump(diff, open("_po_outs.json","w"))
for lo,hi,lbl in ((0,16.5,"short (<16.5 avg outs)"),(16.5,18,"middle (16.5-18)"),(18,99,"workhorse (18+)")):
    X=[x for x in diff if lo<=x[2]<hi]
    if X:
        dd=[x[0] for x in X]; print("  %-24s n=%3d  %+.2f outs   under own avg-0.5: %.0f%%   under own avg+0.5: %.0f%%" % (lbl,len(X),st.mean(dd),
              100*sum(x[1]<x[2]-0.5 for x in X)/len(X),100*sum(x[1]<x[2]+0.5 for x in X)/len(X)))
print("share of playoff starts BELOW own season avg: %.1f%%" % (100 * sum(x < 0 for x in d) / len(d)))
