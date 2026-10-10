"""GOLF STROKES -- data + model + screen (2026-10-01). User: "complete a model for golf strokes".

    python _golf.py pull [2024 2025 2026]   # every PGA / DP World (eur) / LPGA event, round scores -> golf_rounds.jsonl (resumable)
    python _golf.py test                    # walk-forward: how well do we predict a round's strokes BEFORE it's played?
    python _golf.py screen                  # tonight's PrizePicks strokes lines vs our projection (paper)

The model (no fitting tricks, all walk-forward):
  relative score  = a player's strokes minus that round's FIELD AVERAGE at that event (removes course + weather)
  skill           = exponentially-weighted mean of his past relative scores (half-life 40 rounds), shrunk toward +0.8
                    (an unknown player is a bit worse than the field average of the events he shows up in)
  course strength = for round k of an event, the field average of rounds already played there (R1 -> R2 is the
                    signal PrizePicks may not move fully), else the event's average from previous years, else par + 1.0
  projection      = expected field average for that round + skill;   sd from the walk-forward residuals.
Source: ESPN site API (free, no key): scoreboard?dates=YYYY gives the calendar; leaderboard?event=ID the rounds.
"""
import sys, os, json, math, time, datetime, statistics as st, urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

OUT = "golf_rounds.jsonl"
TOURS = ("pga", "eur", "lpga")
H = {"User-Agent": "Mozilla/5.0"}
g = lambda u: json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=60).read())


def events(tour, year):
    d = g("https://site.api.espn.com/apis/site/v2/sports/golf/%s/scoreboard?dates=%d" % (tour, year))
    cal = (d.get("leagues") or [{}])[0].get("calendar") or []
    return [(c["id"], c.get("label"), (c.get("startDate") or "")[:10]) for c in cal]


def event_rounds(tour, eid, name, start):
    d = g("https://site.web.api.espn.com/apis/site/v2/sports/golf/leaderboard?event=%s" % eid)
    ev = (d.get("events") or [{}])[0]
    courses = [dict(id=c.get("id"), name=c.get("name"), par=c.get("shotsToPar")) for c in ev.get("courses", [])]
    par = next((c["par"] for c in courses if c.get("par")), 72)
    comp = (ev.get("competitions") or [{}])[0]
    rows = []
    for c in comp.get("competitors", []):
        a = c.get("athlete") or {}
        for ls in c.get("linescores") or []:
            v = ls.get("value")
            if v is None or not (55 <= v <= 95):
                continue
            rows.append(dict(tour=tour, event=eid, name=name, start=start, player_id=a.get("id"), player=a.get("displayName"),
                             round=ls.get("period"), strokes=v, par=par, tee=ls.get("teeTime"),
                             courses=[x["name"] for x in courses]))
    return rows


def pull(years):
    done = set()
    if os.path.exists(OUT):
        for l in open(OUT, encoding="utf-8"):
            done.add(json.loads(l)["event"])
    today = datetime.date.today().isoformat()
    todo = []
    for tour in TOURS:
        for y in years:
            try:
                for eid, name, start in events(tour, y):
                    if eid not in done and start and start < today:
                        todo.append((tour, eid, name, start))
            except Exception as e:
                print("calendar fail", tour, y, e)
    print("%d events to pull" % len(todo), flush=True)
    n = 0
    with open(OUT, "a", encoding="utf-8") as f, ThreadPoolExecutor(6) as ex:
        for rows in ex.map(lambda t: _safe(event_rounds, *t), todo):
            for r in rows or []:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
            if n % 25 == 0:
                print("  %d / %d events" % (n, len(todo)), flush=True)
    print("pull complete")


def _safe(fn, *a):
    for k in range(3):
        try:
            return fn(*a)
        except Exception:
            time.sleep(2 + 3 * k)
    return []


# ------------------------------------------------------------------ model
HALF = 40.0
PRIOR, PRIOR_W = 0.5, 3.0           # tuned 2026-10-01 (_golf_tune.py): RMSE 3.100
R1_ADJ = -0.5                        # round 1 course expectation ran 0.5 strokes high (walk-forward)


def load():
    R = [json.loads(l) for l in open(OUT, encoding="utf-8")]
    seen, out = set(), []
    for r in R:
        k = (r["event"], r["player_id"], r["round"])
        if k not in seen:
            seen.add(k); out.append(r)
    out.sort(key=lambda r: (r["start"], r["event"], r["round"]))
    return out


class Model:
    def __init__(self):
        self.skill = defaultdict(lambda: [0.0, 0.0])          # player -> [weighted sum, weight]
        self.event_hist = defaultdict(list)                   # event name -> field averages from past years
        self.decay = 0.5 ** (1 / HALF)

    def player_skill(self, pid):
        s, w = self.skill[pid]
        return (s + PRIOR * PRIOR_W) / (w + PRIOR_W)

    def field_expect(self, name, par, prior_rounds_avg):
        if prior_rounds_avg:
            return st.mean(prior_rounds_avg)
        h = self.event_hist.get(name)
        return (st.mean(h) if h else par + 1.0) + R1_ADJ

    def update(self, pid, rel):
        s, w = self.skill[pid]
        self.skill[pid] = [s * self.decay + rel, w * self.decay + 1]


def test():
    R = load()
    print("%d rounds, %d events, %s .. %s" % (len(R), len({r["event"] for r in R}), R[0]["start"], R[-1]["start"]))
    by = defaultdict(list)
    for r in R:
        by[(r["event"], r["round"])].append(r)
    M = Model()
    errs, errs_naive, z = [], [], []
    ev_rounds = defaultdict(list)          # event -> field averages of rounds played so far
    keys = sorted(by, key=lambda k: (by[k][0]["start"], k[0], k[1]))
    for k in keys:
        rows = by[k]
        if len(rows) < 20:
            continue
        ev, rd = k
        name, par = rows[0]["name"], rows[0]["par"]
        fexp = M.field_expect(name, par, ev_rounds[ev])
        favg = st.mean(r["strokes"] for r in rows)
        for r in rows:
            pred = fexp + M.player_skill(r["player_id"])
            if M.skill[r["player_id"]][1] >= 8:              # score players with some history only
                errs.append(r["strokes"] - pred)
                errs_naive.append(r["strokes"] - (par + 1.0))
        for r in rows:
            M.update(r["player_id"], r["strokes"] - favg)
        ev_rounds[ev].append(favg)
        if rd == max(x[1] for x in by if x[0] == ev):
            M.event_hist[name].append(st.mean(ev_rounds[ev]))
    rmse = lambda e: math.sqrt(sum(x * x for x in e) / len(e))
    print("rounds scored (players with 8+ prior rounds): %d" % len(errs))
    print("  our projection : RMSE %.2f strokes, bias %+.2f" % (rmse(errs), st.mean(errs)))
    print("  par + 1 (naive): RMSE %.2f strokes" % rmse(errs_naive))
    sd = st.pstdev(errs)
    # how sharp is it? share of rounds within +-2 strokes of projection
    print("  within 2 strokes: %.0f%%  | residual sd %.2f (use this for line probabilities)" % (100 * sum(abs(e) <= 2 for e in errs) / len(errs), sd))
    json.dump(dict(sd=sd, n=len(errs), built=datetime.date.today().isoformat()), open("_golf_model.json", "w"))
    return M


def screen():
    """PrizePicks strokes lines for the next round vs projection = field average so far at this event + skill. PAPER."""
    import _props as P, re
    norm = lambda x: re.sub(r"[^a-z0-9]", "", (x or "").lower())
    R = load()
    M = Model()
    by = defaultdict(list)
    for r in R:
        by[(r["event"], r["round"])].append(r)
    for k in sorted(by, key=lambda k: (by[k][0]["start"], k[0], k[1])):
        rows = by[k]
        if len(rows) < 20:
            continue
        favg = st.mean(r["strokes"] for r in rows)
        for r in rows:
            M.update(r["player_id"], r["strokes"] - favg)
        M.event_hist[rows[0]["name"]].append(favg)
    sd = json.load(open("_golf_model.json"))["sd"] if os.path.exists("_golf_model.json") else 3.1
    names = {}
    for r in R:
        names[norm(r["player"])] = r["player_id"]
    # live events: rounds already played this week give the course's scoring level and update skill
    cur = {}
    for tour, lid in (("pga", 1), ("eur", 131), ("lpga", 256)):
        try:
            sb = g("https://site.api.espn.com/apis/site/v2/sports/golf/%s/scoreboard" % tour)
            ev = sb["events"][0]
            lb = g("https://site.web.api.espn.com/apis/site/v2/sports/golf/leaderboard?event=%s" % ev["id"])["events"][0]
            done = defaultdict(list)
            for c in lb["competitions"][0]["competitors"]:
                for ls in c.get("linescores") or []:
                    if ls.get("value") and 55 <= ls["value"] <= 95:
                        done[ls["period"]].append((c["athlete"].get("id"), ls["value"]))
            favgs = [st.mean(v for _, v in rows) for rd, rows in sorted(done.items()) if len(rows) >= 20]
            for rd, rows in done.items():
                if len(rows) >= 20:
                    fa = st.mean(v for _, v in rows)
                    for pid, v in rows:
                        M.update(pid, v - fa)
            par = next((c.get("shotsToPar") for c in lb.get("courses", []) if c.get("shotsToPar")), 72)
            # 10/8: next-round tee times + Open-Meteo FORECAST wind in each player's 5-hour window vs the field's average.
            # _golf_wind.py (99,591 rounds): +0.041 strokes per +1 km/h of extra wind vs the field (+6 km/h -> +0.31).
            tees = {}
            for c in lb["competitions"][0]["competitors"]:
                t = (c.get("status") or {}).get("teeTime")
                if t:
                    tees[c["athlete"].get("id")] = t
            wave = {}
            try:
                import _golf_wind as GW
                cname = (lb.get("courses") or [{}])[0].get("name")
                geo = json.load(open(GW.GEO)) if os.path.exists(GW.GEO) else {}
                loc = geo.get(cname) or GW.geocode(cname)
                if loc and tees:
                    fc = g("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s&hourly=wind_speed_10m,wind_gusts_10m,precipitation&forecast_days=4&timezone=UTC"
                           % (loc["lat"], loc["lon"]))["hourly"]
                    w = dict(time=fc["time"], ws=fc["wind_speed_10m"], gust=fc["wind_gusts_10m"], rain=fc["precipitation"])
                    win = {pid: GW.window(w, t) for pid, t in tees.items()}
                    win = {k: v for k, v in win.items() if v}
                    if len(win) >= 20:
                        mw = st.mean(v[0] for v in win.values())
                        wave = {k: v[0] - mw for k, v in win.items()}
            except Exception as e:
                print("wind", tour, "fail:", e)
            cur[lid] = dict(event=ev["name"], event_id=ev["id"], tour=tour, fexp=st.mean(favgs) if favgs else M.field_expect(ev["name"], par, []),
                            multi_course=len(lb.get("courses", [])) > 1, rounds_done=len(favgs), wave=wave)
        except Exception as e:
            print("live", tour, "fail:", e)
    rows_out = []
    for lid, info in cur.items():
        try:
            L = [l for l in P.prizepicks(lid, max_age=1800) if l.get("kind") == "standard" and norm(l["stat"]) == "strokes"]
        except Exception as e:
            print("PP", lid, e); continue
        time.sleep(26)
        for l in L:
            pid = names.get(norm(l["player"]))
            if not pid or M.skill[pid][1] < 8:
                continue
            dw = info.get("wave", {}).get(pid)
            proj = info["fexp"] + M.player_skill(pid) + (0.041 * dw if dw is not None else 0.0)
            p_over = 0.5 * math.erfc(((l["line"] - proj) / sd) / math.sqrt(2))
            gap = (proj - l["line"]) / sd
            call = "TAKE OVER" if gap >= 0.5 else "TAKE UNDER" if gap <= -0.5 else "LEAN OVER" if gap >= 0.25 else "LEAN UNDER" if gap <= -0.25 else "TOO CLOSE"
            if info["multi_course"]:
                call = "SKIP (multi-course)"           # 10/8: Dunhill Links went 38% -- course per player unknown
            elif dw is not None and abs(dw) >= 4 and call == "TOO CLOSE":
                call = "WAVE " + ("OVER" if dw > 0 else "UNDER")   # bad/good wind draw is the only reason -> paper tier
            rows_out.append(dict(sport="GOLF", date=datetime.date.today().isoformat(), player=l["player"], stat="Strokes", line=l["line"],
                                 proj=round(proj, 2), sd=round(sd, 2), p_over=round(p_over, 3), gap=round(gap, 2), call=call, venue="PP",
                                 event=info["event"], event_id=info["event_id"], tour=info["tour"], round=info["rounds_done"] + 1,
                                 start=l.get("start"),
                                 wave_kmh=None if dw is None else round(dw, 1),
                                 flags=(["MULTI-COURSE (course per player unknown)"] if info["multi_course"] else [])
                                       + (["WIND DRAW %+.0f km/h vs field" % dw] if dw is not None and abs(dw) >= 3 else [])))
    rows_out.sort(key=lambda r: -abs(r["gap"]))
    for r in rows_out:
        print("%-22s %-28s line %-5s proj %-6s P(over) %3.0f%%  %-11s %s" % (r["player"][:22], r["event"][:28], r["line"], r["proj"],
                                                                         100 * r["p_over"], r["call"], ",".join(r["flags"])))
    try:
        import _calls
        _calls.log(rows_out)
    except Exception as e:
        print("log fail", e)
    print("%d golf lines screened, logged as paper" % len(rows_out))


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] == "pull":
        pull([int(x) for x in a[1:]] or [2024, 2025, 2026])
    elif a[0] == "test":
        test()
    elif a[0] == "screen":
        screen()
