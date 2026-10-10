"""GOLF -- does tee-time WIND move a round's score vs the field? (2026-10-08, user: "tweak until ready or paperable")
The classic golf-prop edge: half the field tees off in calm morning air, half in afternoon wind (or the reverse). PrizePicks sets
strokes lines per player before the weather is known well. If the wave a player draws predicts his score relative to the field,
a free forecast (Open-Meteo) at his tee time is an input the line misses.

    python _golf_wind.py build    # geocode host courses + Open-Meteo hourly archive wind for every event -> _golf_wind.json
    python _golf_wind.py test     # relative score vs wind in his 5-hour tee window minus the round's average wind
Free, no key: geocoding-api.open-meteo.com + archive-api.open-meteo.com.
"""
import sys, os, json, re, time, datetime, collections, statistics as st, urllib.request, urllib.parse

H = {"User-Agent": "Mozilla/5.0"}
g = lambda u: json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=60).read())
GEO, WIND = "_golf_geo.json", "_golf_wind.json"


def clean(name):
    n = re.sub(r"\(.*?\)", " ", name or "")
    for w in ("Golf Club", "Golf Links", "Golf Course", "Country Club", "Golf & Country Club", "Golf Resort", "Resort", "G&CC", "GC", "CC",
              "Golf", "Club", "Links", "Course", "Stadium", "The ", "TPC "):
        n = n.replace(w, " ")
    return " ".join(n.split())


def geocode(name):
    tries = [name, clean(name)] + clean(name).split()[:1]
    for q in tries:
        if not q or len(q) < 3:
            continue
        try:
            r = g("https://geocoding-api.open-meteo.com/v1/search?count=1&name=" + urllib.parse.quote(q)).get("results") or []
        except Exception:
            r = []
        if r:
            return dict(q=q, lat=r[0]["latitude"], lon=r[0]["longitude"], place=r[0].get("name"), country=r[0].get("country"))
        time.sleep(0.2)
    return None


def build():
    R = [json.loads(l) for l in open("golf_rounds.jsonl", encoding="utf-8")]
    ev = {}
    for r in R:
        if r.get("courses"):
            ev.setdefault(r["event"], dict(course=r["courses"][0], start=r["start"], multi=len(r["courses"]) > 1))
    geo = json.load(open(GEO)) if os.path.exists(GEO) else {}
    for e in ev.values():
        if e["course"] not in geo:
            geo[e["course"]] = geocode(e["course"]); time.sleep(0.3)
    json.dump(geo, open(GEO, "w"), indent=0)
    print("courses %d, geocoded %d" % (len(geo), sum(1 for v in geo.values() if v)))
    wind = json.load(open(WIND)) if os.path.exists(WIND) else {}
    for eid, e in ev.items():
        loc = geo.get(e["course"])
        if not loc or eid in wind:
            continue
        s = datetime.date.fromisoformat(e["start"]); en = s + datetime.timedelta(days=4)
        try:
            w = g("https://archive-api.open-meteo.com/v1/archive?latitude=%s&longitude=%s&start_date=%s&end_date=%s&hourly=wind_speed_10m,wind_gusts_10m,precipitation&timezone=UTC"
                  % (loc["lat"], loc["lon"], s, en))["hourly"]
            wind[eid] = dict(time=w["time"], ws=w["wind_speed_10m"], gust=w["wind_gusts_10m"], rain=w["precipitation"], multi=e["multi"])
        except Exception as ex:
            print("wind fail", eid, ex)
        time.sleep(0.25)
    json.dump(wind, open(WIND, "w"))
    print("events with wind: %d / %d" % (len(wind), len(ev)))


def window(w, tee, hours=5):
    t0 = datetime.datetime.fromisoformat(tee.replace("Z", "+00:00")).replace(tzinfo=None)
    idx = {t: i for i, t in enumerate(w["time"])}
    xs, gs, rs = [], [], []
    for h in range(hours):
        k = (t0 + datetime.timedelta(hours=h)).strftime("%Y-%m-%dT%H:00")
        i = idx.get(k)
        if i is not None and w["ws"][i] is not None:
            xs.append(w["ws"][i]); gs.append(w["gust"][i] or 0); rs.append(w["rain"][i] or 0)
    return (sum(xs) / len(xs), sum(gs) / len(gs), sum(rs)) if len(xs) >= 3 else None


def test():
    R = [json.loads(l) for l in open("golf_rounds.jsonl", encoding="utf-8")]
    wind = json.load(open(WIND))
    grp = collections.defaultdict(list)
    for r in R:
        if r["event"] in wind and r.get("tee") and not wind[r["event"]]["multi"]:
            grp[(r["event"], r["round"])].append(r)
    rows = []
    for (eid, rd), rs in grp.items():
        if len(rs) < 30:
            continue
        favg = st.mean(r["strokes"] for r in rs)
        ww = []
        for r in rs:
            x = window(wind[eid], r["tee"])
            if x:
                ww.append((r, x))
        if len(ww) < 30:
            continue
        mw = st.mean(x[0] for _, x in ww); mg = st.mean(x[1] for _, x in ww)
        for r, (w_, gu, rn) in ww:
            rows.append(dict(rel=r["strokes"] - favg, dw=w_ - mw, dg=gu - mg, rain=rn, w=w_, tour=r["tour"]))
    print("rounds with tee-window wind: %d" % len(rows))
    n = len(rows); mx = st.mean(r["dw"] for r in rows); my = st.mean(r["rel"] for r in rows)
    b = sum((r["dw"] - mx) * (r["rel"] - my) for r in rows) / sum((r["dw"] - mx) ** 2 for r in rows)
    print("  slope: +%.3f strokes per +1 km/h of extra wind in his window vs the field (gusts below)" % b)
    for lo, hi in ((-99, -6), (-6, -3), (-3, -1), (-1, 1), (1, 3), (3, 6), (6, 99)):
        X = [r for r in rows if lo <= r["dw"] < hi]
        if len(X) > 200:
            print("    his wind vs field %+3d..%+3d km/h   n=%6d   score vs field %+5.2f   (over field avg %.1f%%)" % (lo, hi, len(X), st.mean(r["rel"] for r in X),
                  100 * sum(r["rel"] > 0 for r in X) / len(X)))
    for lo, hi in ((-99, -8), (-8, -4), (-4, 4), (4, 8), (8, 99)):
        X = [r for r in rows if lo <= r["dg"] < hi]
        if len(X) > 200:
            print("    gusts vs field %+3d..%+3d   n=%6d   score vs field %+5.2f" % (lo, hi, len(X), st.mean(r["rel"] for r in X)))


if __name__ == "__main__":
    {"build": build, "test": test}[sys.argv[1]]()
