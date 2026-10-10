"""Original golf model vs the 10/8 rework, on every graded PrizePicks strokes line (2026-10-08).
Rework = skip multi-course events + add the tee-window wind draw (+0.041 strokes per km/h vs the field), using the ACTUAL
historical wind at each player's real tee time (Open-Meteo archive) -- the live screen uses the forecast instead."""
import json, math, statistics as st, collections
import _golf as G, _golf_wind as W

C = [json.loads(l) for l in open("calls_log.jsonl", encoding="utf-8")]
C = [r for r in C if r["sport"] == "GOLF" and r.get("actual") is not None and r.get("proj") is not None and r["actual"] != r["line"]]
geo = json.load(open(W.GEO)) if __import__("os").path.exists(W.GEO) else {}
cache = {}
def event_info(eid):
    if eid in cache:
        return cache[eid]
    lb = G.g("https://site.web.api.espn.com/apis/site/v2/sports/golf/leaderboard?event=%s" % eid)["events"][0]
    cname = (lb.get("courses") or [{}])[0].get("name"); loc = geo.get(cname) or W.geocode(cname)
    tees = collections.defaultdict(dict)
    for c in lb["competitions"][0]["competitors"]:
        for ls in c.get("linescores") or []:
            if ls.get("teeTime"):
                tees[ls["period"]][c["athlete"].get("displayName")] = ls["teeTime"]
    days = sorted({t[:10] for d in tees.values() for t in d.values()})
    w = G.g("https://archive-api.open-meteo.com/v1/archive?latitude=%s&longitude=%s&start_date=%s&end_date=%s&hourly=wind_speed_10m,wind_gusts_10m,precipitation&timezone=UTC"
            % (loc["lat"], loc["lon"], days[0], days[-1]))["hourly"]
    w = dict(time=w["time"], ws=w["wind_speed_10m"], gust=w["wind_gusts_10m"], rain=w["precipitation"])
    dw = {}
    for rd, d in tees.items():
        win = {p: W.window(w, t) for p, t in d.items()}; win = {p: v for p, v in win.items() if v}
        if len(win) >= 20:
            m = st.mean(v[0] for v in win.values())
            for p, v in win.items():
                dw[(rd, p)] = v[0] - m
    cache[eid] = (dw, len(lb.get("courses") or []) > 1)
    return cache[eid]

rows = []
for r in C:
    dw, multi = event_info(r["event_id"])
    d = dw.get((r["round"], r["player"]))
    rows.append(dict(r, dw=d, multi=multi))
def rep(lab, X, side):
    if X:
        w = sum((x["actual"] > x["line"]) == (side(x) == "over") for x in X)
        print("  %-52s n=%3d  hit %5.1f%%" % (lab, len(X), 100 * w / len(X)))
orig = lambda x: "over" if x["proj"] > x["line"] else "under"
new = lambda x: "over" if x["proj"] + 0.041 * (x["dw"] or 0) > x["line"] else "under"
print("GOLF: original vs rework on graded PrizePicks strokes lines (wind = actual at his tee time)")
rep("ORIGINAL, every line", rows, orig)
S = [x for x in rows if not x["multi"]]
rep("REWORK step 1: skip multi-course", S, orig)
rep("REWORK step 2: + wind draw (single-course)", S, new)
rep("  rework, only where the side CHANGED", [x for x in S if orig(x) != new(x)], new)
rep("  WAVE tier: |wind draw| >= 4 km/h", [x for x in S if x["dw"] is not None and abs(x["dw"]) >= 4],
    lambda x: "over" if x["dw"] > 0 else "under")
rep("  WAVE tier: |wind draw| >= 2 km/h", [x for x in S if x["dw"] is not None and abs(x["dw"]) >= 2],
    lambda x: "over" if x["dw"] > 0 else "under")
print("  wind draws available: %d of %d single-course lines; spread %s" % (sum(1 for x in S if x["dw"] is not None), len(S),
      sorted(round(x["dw"], 1) for x in S if x["dw"] is not None)[::max(1, len(S) // 10)]))
