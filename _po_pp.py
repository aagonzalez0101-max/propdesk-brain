"""PrizePicks STANDARD hitter lines for today's playoff games: season rate (starts), playoff drop,
career vs TODAY'S starter, career postseason. (2026-09-29)"""
import requests, json, concurrent.futures as cf
from _price import prizepicks, norm
H = {"User-Agent": "Mozilla/5.0"}; S = "https://statsapi.mlb.com/api/v1"; DAY = "2026-09-29"
DROP = {"Hits": .045, "Hits+Runs+RBIs": .052, "Total Bases": .05}
sch = requests.get(S + "/schedule", params=dict(sportId=1, date=DAY, hydrate="probablePitcher,lineups"), headers=H, timeout=30).json()
who = {}   # hitter id -> (team side, opposing starter id/name, lineup spot or None)
rosters = {}
for g in sch["dates"][0]["games"]:
    for side, opp in (("away", "home"), ("home", "away")):
        sp = g["teams"][opp].get("probablePitcher") or {}
        tid = g["teams"][side]["team"]["id"]
        ro = requests.get(S + "/teams/%d/roster" % tid, params={"rosterType": "active"}, headers=H, timeout=20).json()["roster"]
        lu = [p["id"] for p in (g.get("lineups") or {}).get(side + "Players", [])]
        for p in ro:
            if p["position"]["abbreviation"] != "P":
                who[norm(p["person"]["fullName"])] = (p["person"]["id"], p["person"]["fullName"], sp.get("id"), sp.get("fullName"),
                                                      (lu.index(p["person"]["id"]) + 1) if p["person"]["id"] in lu else ("-" if lu else "?"))
pp = prizepicks(2)
legs = [(k, v["standard"]) for k, v in pp.items() if "standard" in v and k[1] in DROP and k[0] in who]
def val(stat, s):
    return s["hits"] if stat == "Hits" else s["totalBases"] if stat == "Total Bases" else s["hits"] + s["runs"] + s["rbi"]
def job(a):
    (nm, stat), line = a
    pid, full, spid, spn, spot = who[nm]
    g = requests.get(S + "/people/%d/stats" % pid, params=dict(stats="gameLog", season=2026, group="hitting", gameType="R"), headers=H, timeout=20).json()
    G = [x["stat"] for x in (g["stats"][0]["splits"] if g.get("stats") else []) if x["stat"].get("plateAppearances", 0) >= 3]
    if len(G) < 30: return None
    over = sum(val(stat, s) > line for s in G) / len(G)
    po_over = over - DROP[stat]
    vs = "-"
    if spid:
        v = requests.get(S + "/people/%d/stats" % pid, params=dict(stats="vsPlayer", opposingPlayerId=spid, group="hitting"), headers=H, timeout=20).json()
        t = [x["stat"] for st in v.get("stats", []) if st.get("type", {}).get("displayName") == "vsPlayerTotal" for x in st.get("splits", [])]
        if t: vs = "%s-for-%s" % (t[0].get("hits", 0), t[0].get("atBats", 0))
    c = requests.get(S + "/people/%d/stats" % pid, params=dict(stats="career", group="hitting", gameType="P"), headers=H, timeout=20).json()
    cs = [x["stat"] for st in c.get("stats", []) for x in st.get("splits", [])]
    post = "%s AVG in %s PA" % (cs[0].get("avg"), cs[0].get("plateAppearances")) if cs else "none"
    side = "Less" if po_over < .5 else "More"
    p = 1 - po_over if side == "Less" else po_over
    return dict(name=full, stat=stat, line=line, side=side, p=p, n=len(G), season_over=over, vs=vs, sp=spn, post=post, spot=spot)
with cf.ThreadPoolExecutor(10) as ex:
    R = [r for r in ex.map(job, legs) if r]
R.sort(key=lambda r: -r["p"])
json.dump(R, open("_po_pp.json", "w"), indent=1)
print("%-20s %-15s %4s %-4s %5s  %-8s %-16s %-10s %-22s %s" % ("hitter", "stat", "line", "side", "p", "season", "vs starter", "", "career postseason", "spot"))
for r in R[:22]:
    print("%-20s %-15s %4s %-4s %4.0f%%  %3.0f%% ov  %-16s %-10s %-22s %s" % (r["name"][:20], r["stat"], r["line"], r["side"], r["p"] * 100,
          r["season_over"] * 100, r["vs"] + " vs", (r["sp"] or "")[:10], r["post"], r["spot"]))
