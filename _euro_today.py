"""Today's Euroleague alt-line OVERS -> calibrated fair price per player (2026-10-08). Uses the walk-forward table from
`_euro.py props` (458k lines, 2014-now): raw last-15 hit rate -> the rate that actually happened -> fair American odds.
Courtside alt overs are a bet only when Courtside pays MORE than this fair price."""
import json, datetime, collections, requests, sys
CT = datetime.timezone(datetime.timedelta(hours=-5))
# raw-bucket -> actual hit rate (Euroleague props backtest 10/8)
CAL = {"pts": [(.5, .541), (.6, .632), (.7, .710), (.8, .778), (.9, .826)], "reb": [(.5, .521), (.6, .607), (.7, .699), (.8, .753), (.9, .820)],
       "ast": [(.5, .514), (.6, .621), (.7, .716), (.8, .795), (.9, .849)], "pra": [(.5, .532), (.6, .632), (.7, .723), (.8, .796), (.9, .862)]}
ALT = {"pts": (8, 10, 12, 15, 18, 20, 25), "reb": (3, 4, 5, 6, 8), "ast": (2, 3, 4, 5, 6), "pra": (10, 15, 20, 25, 30)}
def cal(st, p):
    v = None
    for lo, a in CAL[st]:
        if p >= lo: v = a
    return v
am = lambda p: ("-%d" % round(100 * p / (1 - p))) if p > .5 else ("+%d" % round(100 * (1 - p) / p))
P = [json.loads(l) for l in open("euro_players.jsonl", encoding="utf-8")]
by = collections.defaultdict(list)
for r in P:
    r["pra"] = r["pts"] + r["reb"] + r["ast"]; by[(r["team"], r["pid"])].append(r)
day = sys.argv[1] if len(sys.argv) > 1 else datetime.datetime.now(CT).date().isoformat()
G = json.load(open("_euro/E2026_games.json", encoding="utf-8"))["data"]
now = datetime.datetime.now(datetime.timezone.utc)
for g in G:
    if g.get("played") or not g["date"].startswith(day):
        continue
    h, a = g["local"]["club"], g["road"]["club"]
    print("\n%s @ %s   (%s local)" % (a["name"], h["name"], g["date"][11:16]))
    for team in (a["code"], h["code"]):
        rows = []
        for (t, pid), gl in by.items():
            if t != team:
                continue
            gl = sorted(gl, key=lambda r: r["date"]); last = [x for x in gl if x["mins"] >= 10][-15:]
            if len(last) < 6 or gl[-1]["season"] < "E2025" or sum(x["mins"] for x in last) / len(last) < 18:
                continue
            best = []
            for st, xs in ALT.items():
                for X in xs:
                    raw = (sum(x[st] >= X for x in last) + .5) / (len(last) + 1)
                    if .6 <= raw:
                        c = cal(st, raw); best.append((st, X, c))
            # the highest threshold per stat that still calibrates >= 70%
            pick = {}
            for st, X, c in best:
                if c >= .70 and (st not in pick or X > pick[st][0]):
                    pick[st] = (X, c)
            if pick:
                rows.append((gl[-1]["name"], len(last), pick))
        for nm, n, pick in sorted(rows, key=lambda x: x[0]):
            print("  %-26s %s" % (nm[:26], "   ".join("%s %d+ %.0f%% fair %s" % (st.upper(), X, 100 * c, am(c)) for st, (X, c) in sorted(pick.items()))))
