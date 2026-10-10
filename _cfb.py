"""CFB -- college football brought up to the level of the other sports (2026-10-02).

    python _cfb.py pull [2025 2026]   # every FBS game's player box score (ESPN) -> sports.db sport='CFB' (resumable via cache)
    python _cfb.py board [YYYY-MM-DD] # integer-spread games (buy the half point) for the day, from ESPN odds

Box scores: ESPN summary?event=ID, categories passing/rushing/receiving. Positions come from the category a player shows up in
(QB = passing attempts, RB = carries without targets, WR/TE = receiving). Player pages, reads and defense-vs-position run through
_site_players.py (cfb adapter), same rules as NFL: no read until 4 games THIS season.
"""
import sys, os, json, datetime, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

H = {"User-Agent": "Mozilla/5.0"}
ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"
CACHE = "_cfb"
os.makedirs(CACHE, exist_ok=True)
g = lambda u: json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=40).read())


def week_events(year, week):
    try:
        d = g("%s/scoreboard?dates=%d&seasontype=2&week=%d&groups=80&limit=200" % (ESPN, year, week))
    except Exception:
        return []
    return [(e["id"], e["date"][:10]) for e in d.get("events", []) if e["status"]["type"].get("completed")]


def box(eid):
    f = os.path.join(CACHE, "%s.json" % eid)
    if os.path.exists(f):
        return json.load(open(f, encoding="utf-8"))
    for k in range(3):
        try:
            s = g("%s/summary?event=%s" % (ESPN, eid))
            break
        except Exception:
            time.sleep(2 + 3 * k)
    else:
        return None
    teams = [(t["team"]["id"], t["team"]["displayName"]) for t in (s.get("boxscore") or {}).get("players", [])]
    rows = []
    for ti, tb in enumerate((s.get("boxscore") or {}).get("players", [])):
        team = tb["team"]["displayName"]; opp = teams[1 - ti][1] if len(teams) == 2 else None
        per = {}
        for grp in tb.get("statistics", []):
            keys = grp.get("keys") or []
            for a in grp.get("athletes", []):
                pid = a["athlete"]["id"]
                r = per.setdefault(pid, dict(player=a["athlete"]["displayName"], pid=pid, team=team, opp=opp))
                vals = dict(zip(keys, a.get("stats") or []))
                if grp["name"] == "passing":
                    ca = str(vals.get("completions/passingAttempts", "0/0")).split("/")
                    r.update(cmp=float(ca[0] or 0), att=float(ca[1] or 0) if len(ca) > 1 else 0, pass_yds=_n(vals.get("passingYards")),
                             pass_td=_n(vals.get("passingTouchdowns")), int=_n(vals.get("interceptions")))
                elif grp["name"] == "rushing":
                    r.update(carries=_n(vals.get("rushingAttempts")), rush_yds=_n(vals.get("rushingYards")), rush_td=_n(vals.get("rushingTouchdowns")))
                elif grp["name"] == "receiving":
                    r.update(rec=_n(vals.get("receptions")), rec_yds=_n(vals.get("receivingYards")), rec_td=_n(vals.get("receivingTouchdowns")))
        for r in per.values():
            r["pos"] = "QB" if r.get("att", 0) >= 5 else "RB" if r.get("carries", 0) >= 3 and r.get("rec", 0) <= 3 else \
                       "WR" if r.get("rec", 0) or r.get("rec_yds", 0) else "RB" if r.get("carries") else None
            if r["pos"]:
                rows.append(r)
    out = dict(eid=eid, date=(s.get("header", {}).get("competitions") or [{}])[0].get("date", "")[:10], rows=rows)
    json.dump(out, open(os.path.join(CACHE, "%s.json" % eid), "w", encoding="utf-8"))
    return out


def _n(v):
    try:
        return float(str(v).replace("--", "0"))
    except (TypeError, ValueError):
        return 0.0


def pull(years):
    import _db
    c = _db.con()
    for y in years:
        evs = []
        for w in range(1, 17):
            evs += week_events(y, w)
        print("%d: %d completed FBS games" % (y, len(evs)), flush=True)
        n = 0
        with ThreadPoolExecutor(8) as ex:
            for b in ex.map(lambda e: box(e[0]), evs):
                if not b:
                    continue
                rows = []
                for r in b["rows"]:
                    st = {k: r.get(k, 0.0) for k in ("cmp", "att", "pass_yds", "pass_td", "int", "carries", "rush_yds", "rush_td", "rec", "rec_yds", "rec_td")}
                    st["pos"] = r["pos"]
                    rows.append(("CFB", "CFB", str(y), b["date"], str(b["eid"]), str(r["pid"]), r["player"], r["team"], r["opp"], None, None, json.dumps(st)))
                _db.put_pg(c, rows); n += 1
        print("  %d: %d box scores loaded" % (y, n), flush=True)


def board(day):
    d = g("%s/scoreboard?dates=%s&groups=80&limit=200" % (ESPN, day.replace("-", "")))
    n = 0
    for e in d.get("events", []):
        od = (e["competitions"][0].get("odds") or [{}])[0]
        det = od.get("details", "")
        try:
            num = abs(float(det.split()[-1]))
        except (ValueError, IndexError):
            continue
        if num and num == int(num) and num in (3, 7, 10, 14, 4, 6):
            print("  %-34s %-14s integer line on a key number -> buy the half point (worth ~4pp net)" % (e["name"][:34], det)); n += 1
    print("%d key-number spreads on %s" % (n, day))


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] == "pull":
        pull([int(x) for x in a[1:]] or [2025, 2026])
    elif a[0] == "board":
        board(a[1] if len(a) > 1 else datetime.date.today().isoformat())
