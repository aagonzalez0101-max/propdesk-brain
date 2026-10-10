"""Do the WNBA direction reasons transfer to the NBA? (2026-10-07, before the 10/20 opener)
Two full NBA seasons from sports.db: each player-game vs that player's own trailing-20 average, split by rest (back-to-back),
opponent defense (trailing points allowed), stat family. A reason that moves NBA players off their own average is a candidate
vote for the NBA direction filter; one that doesn't is dropped before any money touches it."""
import json, sqlite3, collections, bisect, datetime, requests
c = sqlite3.connect("sports.db")
ids = {}
for t in requests.get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams", timeout=30).json()["sports"][0]["leagues"][0]["teams"]:
    ids[t["team"]["id"]] = t["team"]["abbreviation"]
FIX = {"GS": "GSW", "NY": "NYK", "SA": "SAS", "NO": "NOP", "UTAH": "UTA", "WSH": "WAS"}
tg = collections.defaultdict(list)
for d, t, o in c.execute("select date,team,opp_stats from team_games where sport='NBA'"):
    pa = json.loads(o or "{}").get("pts")
    if pa is not None:
        tg[t].append((d, float(pa)))
for t in tg:
    tg[t].sort()
abbrs = set(tg)
def norm_abbr(a):
    for x in (a, FIX.get(a), {v: k for k, v in FIX.items()}.get(a)):
        if x in abbrs:
            return x
    return None
lg = sum(x for v in tg.values() for _, x in v) / sum(len(v) for v in tg.values())
def def_allowed(t, d):
    v = tg.get(t)
    if not v:
        return None
    i = bisect.bisect_left([x[0] for x in v], d); xs = [x[1] for x in v[max(0, i - 20):i]]
    return sum(xs) / len(xs) / lg if len(xs) >= 8 else None
pg = collections.defaultdict(list)
for p, d, team, opp, mins, st in c.execute("select player,date,team,opp,minutes,stats from player_games where sport='NBA'"):
    s = json.loads(st)
    if mins and mins >= 24:
        pg[p].append((d, opp, s))
rows = []
for p, gl in pg.items():
    gl.sort()
    for i in range(10, len(gl)):
        d, opp, s = gl[i]; prev = gl[max(0, i - 20):i]
        rest = (datetime.date.fromisoformat(d) - datetime.date.fromisoformat(gl[i - 1][0])).days
        o = norm_abbr(ids.get(opp, opp)); da = def_allowed(o, d) if o else None
        for stat, f in (("pts", ("pts",)), ("reb", ("reb",)), ("ast", ("ast",)), ("pra", ("pts", "reb", "ast"))):
            mu = sum(sum(x[2].get(k, 0) for k in f) for x in prev) / len(prev)
            if mu < 3:
                continue
            a = sum(s.get(k, 0) for k in f)
            rows.append((stat, rest, da, a > mu, a / mu - 1))
print("player-games x stats:", len(rows))
def show(lab, X):
    if X:
        print("  %-34s n=%6d  over own avg %5.1f%%   mean shift %+5.1f%%" % (lab, len(X), 100 * sum(r[3] for r in X) / len(X), 100 * sum(r[4] for r in X) / len(X)))
for stat in ("pts", "reb", "ast", "pra"):
    S = [r for r in rows if r[0] == stat]
    print(stat.upper())
    show("all", S)
    show("back-to-back (rest 1)", [r for r in S if r[1] == 1])
    show("rest 2", [r for r in S if r[1] == 2])
    show("rest 3+", [r for r in S if r[1] >= 3])
    D = sorted([r for r in S if r[2] is not None], key=lambda r: r[2]); q = len(D) // 5
    show("toughest 20% D", D[:q]); show("softest 20% D", D[-q:])
