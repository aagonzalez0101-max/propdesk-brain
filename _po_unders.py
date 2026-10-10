"""MLB POSTSEASON hitter UNDERS screen (built 2026-09-29).
Measured (project_mlb_postseason): playoff overs run below regular-season rates -- Hits 0.5+ -4.5pp,
HRR 0.5+ -5.2pp over 3,432 hitter-games. Lines/prices are set off the regular season, so the under
inherits that gap. Rate = 2026 regular-season starts (3+ PA), shrunk toward the league rate.
    python _po_unders.py
"""
import json, sys, requests, concurrent.futures as cf
from _price import underdog, norm
MLB = "https://statsapi.mlb.com/api/v1"
H = {"User-Agent": "Mozilla/5.0"}
DROP = {"Hits": 0.045, "Hits + Runs + RBIs": 0.052}
LEAGUE = {"Hits": 0.62, "Hits + Runs + RBIs": 0.72}     # league start-game over rates, shrink target
GAMES = ("PHI @ ATL", "CWS @ HOU", "BOS @ NYY", "CHC @ SD")  # WC: same four series, game 2 on 9/30
dec = lambda o: 1 + (o / 100 if o > 0 else 100 / -o)

def pid(name):
    r = requests.get(MLB + "/people/search", params={"names": name, "sportIds": 1}, headers=H, timeout=20).json()
    p = r.get("people") or []
    return p[0]["id"] if p else None

def log(i):
    r = requests.get(MLB + "/people/%d/stats" % i, params={"stats": "gameLog", "season": 2026, "group": "hitting",
                                                            "gameType": "R"}, headers=H, timeout=20).json()
    s = r["stats"][0]["splits"] if r.get("stats") else []
    return [x for x in s if x["stat"].get("plateAppearances", 0) >= 3]

def job(item):
    (k, v) = item
    stat = v["stat"]; side = v["sides"].get("under")
    if not side or side[0] is None: return None
    i = pid(v["player"])
    if not i: return None
    G = log(i)
    if len(G) < 30: return None
    val = (lambda s: s["hits"]) if stat == "Hits" else (lambda s: s["hits"] + s["runs"] + s["rbi"])
    n = len(G); o = sum(val(g["stat"]) > 0.5 for g in G)
    k12 = 20
    rate = (o + LEAGUE[stat] * k12) / (n + k12)
    last = G[-1]["date"]
    p_under = 1 - (rate - DROP[stat])
    am = side[0]
    return dict(player=v["player"], game=v["game"], stat=stat, over=o, n=n, rate=rate, p_under=p_under,
                price=am, be=1 / dec(am), ev=p_under * dec(am) - 1, last=last)

ud = underdog()
items = [(k, v) for k, v in ud.items() if v.get("game") in GAMES and k[2] == 0.5 and v["stat"] in DROP]
with cf.ThreadPoolExecutor(8) as ex:
    R = [r for r in ex.map(job, items) if r]
R.sort(key=lambda r: -r["ev"])
json.dump(R, open("_po_unders.json", "w"), indent=1)
print("%-22s %-10s %-6s %8s %6s %7s %6s %6s %s" % ("hitter", "game", "stat", "season", "under", "UD", "b/e", "EV", "last"))
for r in R[:25]:
    print("%-22s %-10s %-6s %3d/%-4d %5.0f%% %+7d %5.0f%% %+5.0f%% %s" % (r["player"][:22], r["game"], "H" if r["stat"] == "Hits" else "HRR",
          r["over"], r["n"], r["p_under"] * 100, r["price"], r["be"] * 100, r["ev"] * 100, r["last"]))
