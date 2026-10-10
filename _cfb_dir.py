"""CFB direction backtest (2026-10-09, user: "do those 3" -- the CFB part). Every archived PrizePicks CFB STANDARD line (lines.db, league 15),
graded from sports.db box scores, with as-of features: the player's own games vs the line (season mean/median, hit rate, last 3),
opponent's yards ALLOWED for that stat (summed from the box scores, trailing, relative to the league), and the line's move.
    python _cfb_dir.py          # scans: which reasons point over/under; then a leave-one-date-out check of a vote filter
"""
import json, sqlite3, re, datetime, collections, statistics as st

CT = datetime.timezone(datetime.timedelta(hours=-5))
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
FIELDS = {"Rush Yards": ("rush_yds",), "Receiving Yards": ("rec_yds",), "Pass Yards": ("pass_yds",), "Receptions": ("rec",),
          "Rush Attempts": ("carries",), "Pass Attempts": ("att",), "Pass Completions": ("cmp",), "Rush+Rec Yds": ("rush_yds", "rec_yds"),
          "Pass+Rush Yds": ("pass_yds", "rush_yds")}
DEF = {"rush_yds": "rush_yds", "rec_yds": "pass_yds", "pass_yds": "pass_yds", "rec": "cmp", "carries": "carries", "att": "att", "cmp": "cmp"}

c = sqlite3.connect("sports.db")
pg = collections.defaultdict(list); team_game = collections.defaultdict(lambda: collections.Counter())
for d, gid, pl, team, opp, s in c.execute("SELECT date, game_id, player, team, opp, stats FROM player_games WHERE sport='CFB'"):
    s = json.loads(s)
    if pl.strip() == "Team":
        continue
    pg[norm(pl)].append((d, team, opp, s))
    for k in ("rush_yds", "pass_yds", "cmp", "carries", "att"):
        team_game[(team, d)][k] += s.get(k) or 0
for k in pg:
    pg[k].sort(key=lambda x: x[0])
allowed = collections.defaultdict(list)                  # defense team -> [(date, offense totals vs them)]
for (team, d), tot in team_game.items():
    allowed[team]  # ensure key
games_by_team_date = {}
for k, v in pg.items():
    for d, team, opp, s in v:
        games_by_team_date[(team, d)] = opp
for (team, d), tot in team_game.items():
    opp = games_by_team_date.get((team, d))
    if opp:
        allowed[opp].append((d, tot))
for t in allowed:
    allowed[t].sort(key=lambda x: x[0])
lg_avg = {k: st.mean(t[k] for tg in allowed.values() for d, t in tg) for k in ("rush_yds", "pass_yds", "cmp", "carries", "att")}

L = sqlite3.connect("lines.db")
lines = {}
for pid, pl, team, stat, line, start, fs in L.execute("SELECT proj_id, player, team, stat, line, start, first_seen FROM pp WHERE league=15 AND kind='standard' ORDER BY rowid"):
    if stat in FIELDS and pl and "+" not in pl:
        first = lines.get(pid, {}).get("first", line)
        lines[pid] = dict(player=pl, team=team, stat=stat, line=line, start=start, first=first)
rows = []
for pid, l in lines.items():
    games = pg.get(norm(l["player"]))
    if not games or not l["start"]:
        continue
    day = datetime.datetime.fromisoformat(l["start"]).astimezone(CT).date()
    g = next((x for x in games if abs((datetime.date.fromisoformat(x[0]) - day).days) <= 1), None)
    if not g:
        continue
    f = FIELDS[l["stat"]]
    actual = sum(g[3].get(k) or 0 for k in f)
    if actual == l["line"]:
        continue
    prior = [sum(x[3].get(k) or 0 for k in f) for x in games if x[0] < g[0] and x[0] >= "2025-08-01"]
    cur = [sum(x[3].get(k) or 0 for k in f) for x in games if x[0] < g[0] and x[0] >= "2026-08-01"]
    if len(cur) < 2:
        continue
    dk = DEF[f[0]]
    al = [t[dk] for d, t in allowed.get(g[2], []) if d < g[0] and d >= "2026-08-01"]
    rows.append(dict(date=g[0], player=l["player"], stat=l["stat"], line=l["line"], first=l["first"], actual=actual, over=int(actual > l["line"]),
                     cur_mean=st.mean(cur) / l["line"] if l["line"] else 1, cur_med=st.median(cur) / l["line"] if l["line"] else 1,
                     prev_mean=(st.mean(prior) / l["line"]) if prior and l["line"] else 1, n_cur=len(cur),
                     hit_cur=sum(v > l["line"] for v in cur) / len(cur), last3=st.mean(cur[-3:]) / l["line"] if l["line"] else 1,
                     d_opp=(st.mean(al) / lg_avg[dk]) if len(al) >= 2 else None, moved=l["line"] - l["first"]))
print("CFB graded standard lines: %d  dates %s  over rate %.1f%%" % (len(rows), sorted(collections.Counter(r["date"] for r in rows).items()),
      100 * sum(r["over"] for r in rows) / max(len(rows), 1)))
def q(name, key):
    X = sorted([r for r in rows if r.get(key) is not None], key=lambda r: r[key]); n = len(X) // 5
    if n < 30:
        return
    qs = [X[i * n:(i + 1) * n] if i < 4 else X[4 * n:] for i in range(5)]
    print("  %-10s over%% by quintile: %s   cuts %s" % (name, "  ".join("%3.0f" % (100 * sum(r["over"] for r in b) / len(b)) for b in qs),
          [round(b[0][key], 2) for b in qs]))
for k in ("cur_mean", "cur_med", "prev_mean", "hit_cur", "last3", "d_opp", "moved", "n_cur"):
    q(k, k)
for s_ in sorted({r["stat"] for r in rows}):
    X = [r for r in rows if r["stat"] == s_]
    if len(X) >= 40:
        print("  %-18s n=%4d over %.1f%%" % (s_, len(X), 100 * sum(r["over"] for r in X) / len(X)))
json.dump(rows, open("_cfb_dir_rows.json", "w"))
