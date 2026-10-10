"""PROP DESK SITE -- data builder (2026-09-30). Pulls the chart data for tonight's slate into site/data.json.

    python _site_data.py            # build everything (each section independent; a failed section is reported, not hidden)
    python _site_data.py wnba       # one section

Sections: tonight (bet cards from legs/), wnba (ESPN shot coordinates + team defense by zone), mlb (Statcast spray +
pitch locations, Baseball Savant CSV), nfl (defense vs position from nflverse weekly, target map from nflverse pbp),
soccer (FotMob shot maps). All free, no keys.
"""
import sys, os, json, math, csv, io, gzip, datetime, statistics as st, urllib.request, glob
from concurrent.futures import ThreadPoolExecutor

UA = {"User-Agent": "Mozilla/5.0"}
DAY = datetime.date.today().isoformat()
OUT = os.path.join("site", "data.json")
CACHE = "_site_cache"
os.makedirs(CACHE, exist_ok=True)


def raw(u, cache=None, max_age=6 * 3600):
    f = os.path.join(CACHE, cache) if cache else None
    if f and os.path.exists(f) and datetime.datetime.now().timestamp() - os.path.getmtime(f) < max_age:
        return open(f, "rb").read()
    b = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read()
    if f:
        open(f, "wb").write(b)
    return b


g = lambda u, cache=None: json.loads(raw(u, cache))


# ---------------------------------------------------------------------------------------------------------- WNBA
ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba"


def zone(x, y, three):
    d = math.hypot(x - 25, y)
    if three:
        return "corner 3" if y <= 8 else "above-break 3"
    if d <= 5:
        return "rim"
    if d <= 13 and abs(x - 25) <= 8:
        return "paint"
    return "midrange"


def wnba_game_shots(eid):
    s = g("%s/summary?event=%s" % (ESPN, eid), "wnba_%s.json" % eid)
    teams = {c["team"]["id"]: c["team"]["abbreviation"] for c in s["header"]["competitions"][0]["competitors"]}
    ath = {}
    for tb in (s.get("boxscore") or {}).get("players", []):
        for grp in tb.get("statistics", []):
            for a in grp.get("athletes", []):
                ath[a["athlete"]["id"]] = a["athlete"]["displayName"]
    out = []
    for p in s.get("plays", []):
        if not p.get("shootingPlay"):
            continue
        t = (p.get("type") or {}).get("text", "")
        c = p.get("coordinate") or {}
        if "Free Throw" in t or not (0 <= c.get("x", -1) <= 50 and 0 <= c.get("y", -1) <= 47):
            continue
        pid = ((p.get("participants") or [{}])[0].get("athlete") or {}).get("id")
        three = "three point" in (p.get("text") or "").lower()
        out.append(dict(x=c["x"], y=c["y"], made=bool(p.get("scoringPlay")), three=three, zone=zone(c["x"], c["y"], three),
                        player=ath.get(pid, "?"), team=teams.get((p.get("team") or {}).get("id"), "?"), game=eid))
    date = s["header"]["competitions"][0]["date"][:10]
    return date, teams, out


def wnba():
    sb = g("%s/scoreboard?dates=%s" % (ESPN, DAY.replace("-", "")))
    games = []
    for e in sb["events"]:
        comp = e["competitions"][0]
        abbr = [c["team"]["abbreviation"] for c in comp["competitors"]]
        games.append(dict(name=e["shortName"], start=e["date"], teams=abbr, ids=[c["team"]["id"] for c in comp["competitors"]]))
    teams = {}
    for gm in games:
        for ab, tid in zip(gm["teams"], gm["ids"]):
            sch = g("%s/teams/%s/schedule?seasontype=2" % (ESPN, tid), "wnba_sch_%s_2.json" % tid)
            po = g("%s/teams/%s/schedule?seasontype=3" % (ESPN, tid), "wnba_sch_%s_3.json" % tid)
            done = [e for e in sch.get("events", []) + po.get("events", [])
                    if ((e["competitions"][0].get("status") or {}).get("type") or {}).get("completed")]
            done.sort(key=lambda e: e["date"])
            teams[ab] = [e["id"] for e in done[-10:]]
    ids = sorted({i for v in teams.values() for i in v})
    with ThreadPoolExecutor(6) as ex:
        res = dict(zip(ids, ex.map(lambda i: wnba_game_shots(i), ids)))
    shots, defense = {}, {}
    for ab, eids in teams.items():
        allowed = []
        for i in eids:
            date, tm, sh = res[i]
            for s_ in sh:
                if s_["team"] == ab:
                    shots.setdefault(s_["player"], {"team": ab, "shots": []})["shots"].append(dict(s_, date=date))
                else:
                    allowed.append(s_)
        z = {}
        for s_ in allowed:
            r = z.setdefault(s_["zone"], [0, 0]); r[0] += s_["made"]; r[1] += 1
        defense[ab] = {k: dict(fg=round(v[0] / v[1], 3), att=round(v[1] / len(eids), 1)) for k, v in z.items()}
        defense[ab]["games"] = len(eids)
    # league zone averages from every game we pulled (both sides)
    lz = {}
    for i in ids:
        for s_ in res[i][2]:
            r = lz.setdefault(s_["zone"], [0, 0]); r[0] += s_["made"]; r[1] += 1
    league = {k: round(v[0] / v[1], 3) for k, v in lz.items()}
    keep = {k: v for k, v in shots.items() if len(v["shots"]) >= 25}
    for v in keep.values():
        v["shots"] = [{k: s_[k] for k in ("x", "y", "made", "three", "zone", "date")} for s_ in v["shots"]]
    return dict(games=games, players=keep, defense=defense, league_zone=league)


# ---------------------------------------------------------------------------------------------------------- run

def wnba_all():
    """shot zones for EVERY team (last 10 games each): zone defense ranks + each player's makes by zone."""
    teams = g("%s/teams" % ESPN)["sports"][0]["leagues"][0]["teams"]
    ids = set()
    tabbr = {}
    for t in teams:
        t = t["team"]; tabbr[t["id"]] = t["abbreviation"]
        evs = []
        for stype in (2, 3):
            try:
                sch = g("%s/teams/%s/schedule?seasontype=%d" % (ESPN, t["id"], stype), "wnba_sch_%s_%d.json" % (t["id"], stype))
                evs += [e for e in sch.get("events", []) if ((e["competitions"][0].get("status") or {}).get("type") or {}).get("completed")]
            except Exception:
                pass
        evs.sort(key=lambda e: e["date"])
        ids |= {e["id"] for e in evs[-10:]}
    with ThreadPoolExecutor(6) as ex:
        res = dict(zip(sorted(ids), ex.map(wnba_game_shots, sorted(ids))))
    real = set(tabbr.values())
    D, Pz, games = {}, {}, {}
    for eid, (date, tm, sh) in res.items():
        side = list(tm.values())
        if not all(x in real for x in side):
            continue
        for s_ in sh:
            opp = [x for x in side if x != s_["team"]]
            if not opp:
                continue
            d = D.setdefault(opp[0], {}).setdefault(s_["zone"], [0, 0]); d[0] += s_["made"]; d[1] += 1
            p = Pz.setdefault(s_["player"], {"team": s_["team"], "z": {}})["z"].setdefault(s_["zone"], [0, 0]); p[0] += s_["made"]; p[1] += 1
        for x in side:
            games.setdefault(x, set()).add(eid)
    zones = ["rim", "paint", "midrange", "corner 3", "above-break 3"]
    out = {}
    for t, z in D.items():
        out[t] = {k: dict(fg=round(z[k][0] / z[k][1], 3), att=round(z[k][1] / len(games[t]), 1)) for k in zones if k in z and z[k][1]}
    for k in zones:                                             # rank 1 = lowest FG% allowed = toughest
        order = sorted([t for t in out if k in out[t]], key=lambda t: out[t][k]["fg"])
        for i, t in enumerate(order):
            out[t][k]["rk"] = i + 1
    return dict(defense=out, players=Pz, nteams=len(out))


SECTIONS = {"wnba": wnba, "wnba_all": wnba_all}


def _more(name):
    import _site_more
    return getattr(_site_more, name)()


for _k in ("tonight", "mlb", "nfl", "soccer"):
    SECTIONS[_k] = (lambda k: (lambda: _more(k)))(_k)

if __name__ == "__main__":
    want = sys.argv[1:] or list(SECTIONS)
    data = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    data["built"] = datetime.datetime.now().isoformat(timespec="minutes")
    for k in want:
        try:
            data[k] = SECTIONS[k]()
            print("%-7s ok" % k)
        except Exception as e:
            import traceback; traceback.print_exc()
            print("%-7s FAILED: %s" % (k, e))
    json.dump(data, open(OUT, "w", encoding="utf-8"))
    print("wrote %s (%.0f KB)" % (OUT, os.path.getsize(OUT) / 1e3))
