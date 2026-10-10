"""Projection call on the bets we ACTUALLY made (+ saved paper), rebuilt point-in-time (2026-09-30).
For every prop leg in live_paper.jsonl: projection = mean of the player's previous 10 games (NFL: 2025 + 2026 weeks
before; WNBA: previous 15 full-minutes games; MLB: previous 15), SD = spread of those games, actual from box scores.
Then: did the call AGREE with the side taken, and how did agree vs disagree legs do?

    python _ledger_call.py
"""
import json, csv, re, math, datetime, statistics as st, urllib.request, requests

legs = json.load(open("_ledger_legs.json"))
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
UA = {"User-Agent": "Mozilla/5.0"}
g = lambda u: json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40).read())


def call(gap):
    return "OVER" if gap >= 0.25 else "UNDER" if gap <= -0.25 else "CLOSE"


def canon(stat):
    s = norm(stat)
    for a, b in (("rebounds", "rebs"), ("rebound", "rebs"), ("reb", "rebs"), ("assists", "asts"), ("assist", "asts"), ("ast", "asts"),
                 ("points", "pts"), ("point", "pts")):
        s = s.replace(a, b)
    s = s.replace("rebss", "rebs").replace("astss", "asts").replace("ptss", "pts")
    return {"pra": "ptsrebsasts"}.get(s, s)


# ---------------- NFL (nflverse weekly)
NFL = {}
for f, season in (("nfl_2025_weekly.csv", 2025), ("nfl_2026_weekly.csv", 2026)):
    for r in csv.DictReader(open(f, encoding="utf-8")):
        if r.get("season_type", "REG") not in ("REG", ""):
            continue
        NFL.setdefault(norm(r["player_display_name"]), []).append((season, int(r["week"]), r))
NFLF = {"receivingyards": ["receiving_yards"], "recyds": ["receiving_yards"], "receptions": ["receptions"],
        "rushyards": ["rushing_yards"], "rushyds": ["rushing_yards"], "passyds": ["passing_yards"], "passyards": ["passing_yards"],
        "rushattempts": ["carries"], "rushrecyds": ["rushing_yards", "receiving_yards"]}


def nfl_week(date):
    d = datetime.date.fromisoformat(date)
    return 1 if d <= datetime.date(2026, 9, 15) else 2 if d <= datetime.date(2026, 9, 22) else 3 if d <= datetime.date(2026, 9, 29) else 4


def nfl(leg):
    rows = NFL.get(norm(leg["player"]))
    f = NFLF.get(norm(leg["stat"]))
    if not rows or not f:
        return None
    wk = nfl_week(leg["date"])
    v = lambda r: sum(float(r[k] or 0) for k in f)
    act = [v(r) for s, w, r in rows if s == 2026 and w == wk]
    prev = [v(r) for s, w, r in sorted(rows, key=lambda x: (x[0], x[1])) if (s, w) < (2026, wk)][-10:]
    return (act[0] if act else None), prev


# ---------------- WNBA (ESPN gamelogs)
_ids, _logs = {}, {}


def wnba_ids():
    if not _ids:
        for t in g("https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/teams")["sports"][0]["leagues"][0]["teams"]:
            try:
                for a in g("https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/teams/%s/roster" % t["team"]["id"])["athletes"]:
                    _ids[norm(a["displayName"])] = a["id"]
            except Exception:
                pass
    return _ids


def wnba_log(pid):
    if pid not in _logs:
        out = []
        for yr in (2025, 2026):
            d = g("https://site.web.api.espn.com/apis/common/v3/sports/basketball/wnba/athletes/%s/gamelog?season=%d" % (pid, yr))
            n = [x.lower() for x in d.get("names", [])]
            for s_ in d.get("seasonTypes", []):
                for c in s_.get("categories", []):
                    for e in c.get("events", []):
                        s = e["stats"]; m = d["events"][e["eventId"]]
                        try:
                            row = {"date": m["gameDate"][:10], "min": float(s[n.index("minutes")]), "pts": float(s[n.index("points")]),
                                   "rebs": float(s[n.index("totalrebounds")]), "asts": float(s[n.index("assists")])}
                            tp = [i for i, x in enumerate(n) if x.startswith("threepointfieldgoalsmade")]
                            row["3pt"] = float(s[tp[0]].split("-")[0]) if tp else 0
                        except (ValueError, IndexError):
                            continue
                        out.append(row)
        _logs[pid] = sorted(out, key=lambda r: r["date"])
    return _logs[pid]


def wnba(leg):
    pid = wnba_ids().get(norm(leg["player"]))
    if not pid:
        return None
    k = canon(leg["stat"])
    parts = {"pts": ["pts"], "rebs": ["rebs"], "asts": ["asts"], "rebsasts": ["rebs", "asts"], "ptsrebsasts": ["pts", "rebs", "asts"],
             "ptsasts": ["pts", "asts"], "ptsrebs": ["pts", "rebs"], "3pointers": ["3pt"]}.get(k)
    if not parts:
        return None
    L = wnba_log(pid)
    v = lambda r: sum(r[p] for p in parts)
    act = [v(r) for r in L if r["date"] in (leg["date"], (datetime.date.fromisoformat(leg["date"]) + datetime.timedelta(days=1)).isoformat())]
    prior = [r for r in L if r["date"] < leg["date"]]
    ref = sum(r["min"] for r in prior[-5:]) / max(1, len(prior[-5:]))
    prev = [v(r) for r in prior if r["min"] >= 0.85 * ref][-15:]
    return (act[0] if act else None), prev


# ---------------- MLB (statsapi)
def mlb(leg):
    s = norm(leg["stat"])
    grp = "pitching" if s in ("k", "pitchingouts") else "hitting"
    p = requests.get("https://statsapi.mlb.com/api/v1/people/search", params={"names": leg["player"], "sportIds": 1}, headers=UA, timeout=20).json().get("people")
    if not p:
        return None
    d = requests.get("https://statsapi.mlb.com/api/v1/people/%d/stats" % p[0]["id"], params=dict(stats="gameLog", group=grp, season=2026), headers=UA, timeout=20).json()
    sp = d["stats"][0]["splits"] if d.get("stats") else []
    val = {"hrr": lambda x: x["hits"] + x["runs"] + x["rbi"], "hits": lambda x: x["hits"], "k": lambda x: x["strikeOuts"],
           "pitchingouts": lambda x: x["outs"]}.get(s)
    if not val:
        return None
    act = [val(x["stat"]) for x in sp if x["date"] == leg["date"]]
    prev = [val(x["stat"]) for x in sp if x["date"] < leg["date"]][-15:]
    return (act[0] if act else None), prev


rows = []
for leg in legs:
    sp = leg["sport"] or ""
    try:
        r = nfl(leg) if sp == "NFL" else wnba(leg) if "WNBA" in sp and "KBO" not in leg.get("stat", "") else mlb(leg) if sp == "MLB" else None
    except Exception as e:
        r = None
    if not r or r[0] is None or len(r[1]) < 4:
        continue
    act, prev = r
    mu, sd = st.mean(prev), max(st.pstdev(prev), 0.5)
    c = call((mu - float(leg["line"])) / sd)
    side = "OVER" if leg["side"] in ("over", "more", "higher", "o") else "UNDER"
    won = (act > leg["line"]) if side == "OVER" else (act < leg["line"])
    agree = "AGREE" if c == side else "CLOSE" if c == "CLOSE" else "AGAINST"
    rows.append(dict(leg, proj=round(mu, 1), sd=round(sd, 1), call=c, took=side, agree=agree, actual=act, leg_won=won))

json.dump(rows, open("_ledger_call.json", "w"), indent=1)
print("%-5s %-6s %-20s %-16s %-5s %5s  proj %-5s -> call %-5s | actual %-5s %s" % ("", "", "player", "stat", "took", "line", "", "", "", ""))
for r in rows:
    print("%-5s %-6s %-20s %-16s %-5s %5s  proj %-5s -> %-6s %-7s | actual %-5s %s" % (
        r["kind"], r["sport"][:6], r["player"][:20], r["stat"][:16], r["took"], r["line"], r["proj"], r["call"], r["agree"],
        r["actual"], "WIN" if r["leg_won"] else "loss"))
for a in ("AGREE", "CLOSE", "AGAINST"):
    x = [r for r in rows if r["agree"] == a]
    if x:
        w = sum(r["leg_won"] for r in x); print("\n%-8s the call: %d-%d  (%.0f%%)" % (a, w, len(x) - w, 100 * w / len(x)), end="")
        lv = [r for r in x if r["kind"] == "LIVE"]
        if lv:
            print("   real-money legs %d-%d" % (sum(r["leg_won"] for r in lv), len(lv) - sum(r["leg_won"] for r in lv)), end="")
print("\n%d of %d legs rebuilt" % (len(rows), len(legs)))
