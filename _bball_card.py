"""BASKETBALL MATCHUP CARD -- WNBA / NBA offense AND defense with league ranks (2026-09-30).

    python _bball_card.py fetch wnba 2026-05-15 2026-10-31   # cache every team box score (resumable)
    python _bball_card.py card wnba LV IND                   # last-15 for/against + ranks, both teams

Team box scores come from ESPN (scoreboard per date -> summary). "for" = what the team does, "against" = what its
opponents do vs it (the defence). Pace proxy = FGA + 0.44*FTA - OREB + TO (possessions).
"""
import sys, os, json, datetime, urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = {"User-Agent": "Mozilla/5.0"}
g = lambda u: json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40).read())
D = "_espn_box"
os.makedirs(D, exist_ok=True)


def num(v):
    try:
        return float(str(v).split("-")[0])
    except ValueError:
        return None


def box(league, eid):
    f = os.path.join(D, "%s_%s.json" % (league, eid))
    if os.path.exists(f):
        return json.load(open(f, encoding="utf-8"))
    s = g("https://site.api.espn.com/apis/site/v2/sports/basketball/%s/summary?event=%s" % (league, eid))
    teams = []
    for t in (s.get("boxscore") or {}).get("teams", []):
        st = {x.get("name"): x.get("displayValue") for x in t.get("statistics", [])}
        teams.append(dict(team=t["team"]["abbreviation"], stats=st))
    comp = ((s.get("header") or {}).get("competitions") or [{}])[0]
    scores = {c["team"]["abbreviation"]: num(c.get("score")) for c in comp.get("competitors", [])}
    out = dict(eid=eid, date=(comp.get("date") or "")[:10], teams=teams, scores=scores,
               done=((comp.get("status") or {}).get("type") or {}).get("completed"))
    if out["done"]:
        json.dump(out, open(f, "w", encoding="utf-8"))
    return out


def fetch(league, a, b):
    d0, d1 = datetime.date.fromisoformat(a), datetime.date.fromisoformat(b)
    ids = []
    while d0 <= min(d1, datetime.date.today()):
        try:
            ev = g("https://site.api.espn.com/apis/site/v2/sports/basketball/%s/scoreboard?dates=%s" % (league, d0.strftime("%Y%m%d"))).get("events", [])
            ids += [e["id"] for e in ev if ((e.get("status") or {}).get("type") or {}).get("completed")]
        except Exception:
            pass
        d0 += datetime.timedelta(days=1)
    todo = [i for i in ids if not os.path.exists(os.path.join(D, "%s_%s.json" % (league, i)))]
    print("%d completed games, %d to fetch" % (len(ids), len(todo)), flush=True)
    with ThreadPoolExecutor(6) as ex:
        def safe(i):
            for a in range(3):
                try:
                    return box(league, i)
                except Exception:
                    import time; time.sleep(3 + 5 * a)
        list(ex.map(safe, todo))
    print("done")


KEYS = [("pts", "points"), ("reb", "rebounds"), ("ast", "assists"), ("tpm", "3PM"), ("fga", "FGA"), ("pace", "possessions")]


def team_games(league):
    rows = []
    for fn in os.listdir(D):
        if not fn.startswith(league + "_"):
            continue
        b = json.load(open(os.path.join(D, fn), encoding="utf-8"))
        if len(b["teams"]) != 2:
            continue
        vals = []
        for t in b["teams"]:
            s = t["stats"]
            fga, fta = num(s.get("fieldGoalsMade-fieldGoalsAttempted", "0-0").split("-")[-1]), num((s.get("freeThrowsMade-freeThrowsAttempted") or "0-0").split("-")[-1])
            v = dict(pts=b["scores"].get(t["team"]), reb=num(s.get("totalRebounds")), ast=num(s.get("assists")),
                     tpm=num(s.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted") or 0), fga=fga,
                     oreb=num(s.get("offensiveRebounds")), to=num(s.get("turnovers") or s.get("totalTurnovers")))
            v["pace"] = (fga or 0) + 0.44 * (fta or 0) - (v["oreb"] or 0) + (v["to"] or 0)
            vals.append((t["team"], v))
        for i in (0, 1):
            rows.append(dict(date=b["date"], team=vals[i][0], opp=vals[1 - i][0], f=vals[i][1], a=vals[1 - i][1]))
    return rows


def card(league, x, y, n=15, quiet=False):
    rows = team_games(league)
    cnt = {}
    for r in rows:
        cnt[r["team"]] = cnt.get(r["team"], 0) + 1
    teams = {t for t, c in cnt.items() if c >= 10}          # drops All-Star / exhibition teams
    table = {}
    for t in teams:
        g_ = sorted([r for r in rows if r["team"] == t], key=lambda r: r["date"])[-n:]
        table[t] = {(side, k): sum(r[side][k] or 0 for r in g_) / len(g_) for side in ("f", "a") for k, _ in KEYS}
    def rk(t, key):
        vals = sorted([v[key] for v in table.values()], reverse=True)
        return vals.index(table[t][key]) + 1
    out = {t: {"%s_%s" % (s, k): (round(table[t][(s, k)], 1), rk(t, (s, k))) for s in ("f", "a") for k, _ in KEYS} for t in (x, y)}
    if not quiet:
        print("\nMATCHUP %s vs %s  (%s, last %d games, rank of %d; #1 = most)" % (x, y, league.upper(), n, len(teams)))
        for k, lbl in KEYS:
            for s, w in (("f", "makes"), ("a", "allows")):
                a_, b_ = out[x]["%s_%s" % (s, k)], out[y]["%s_%s" % (s, k)]
                print("  %-18s %-4s %6.1f (#%2d)    %-4s %6.1f (#%2d)" % ("%s %s" % (lbl, w), x, a_[0], a_[1], y, b_[0], b_[1]))
    return out


if __name__ == "__main__":
    if sys.argv[1] == "fetch":
        fetch(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        card(sys.argv[2], sys.argv[3], sys.argv[4])
