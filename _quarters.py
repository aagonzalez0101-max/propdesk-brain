"""QUARTERS WITH N+ POINTS (11/16, user: "do we have value for 1Q or 1H legs ... play by play tracking"). PP's only NBA quarter props are
'Quarters with 3+ Points' / '5+ Points' (demons + goblins, MORE only). nba_pbp.db gives each player's points per quarter (made shots +
ft_made events). Grades every archived line (lines.db) and prices today's board from the player's own season quarter record.
    python _quarters.py
"""
import sqlite3, json, re, unicodedata, collections, datetime, statistics
CT = __import__("zoneinfo").ZoneInfo("America/Chicago")
nn = lambda s: re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())
P = sqlite3.connect("nba_pbp.db")
Q = collections.defaultdict(lambda: collections.defaultdict(int))     # (player, game, date) -> {period: pts}
meta = {}
for g, d, per, pl, pts in P.execute("select game_id, date, period, player, pts from nba_shots where made=1 and season='2026-27' and period<=4"):
    Q[(nn(pl), g)][per] += pts; meta[(nn(pl), g)] = d
for g, d, per, pl in P.execute("select game_id, date, period, player from nba_events where kind='ft_made' and period<=4 and date>='2026-10-20'"):
    Q[(nn(pl), g)][per] += 1; meta[(nn(pl), g)] = d
G = collections.defaultdict(list)                                    # player -> [(date, pts by quarter)]
for (pl, g), q in Q.items():
    G[pl].append((meta[(pl, g)], [q.get(i, 0) for i in (1, 2, 3, 4)]))
for v in G.values():
    v.sort()
cnt = lambda qs, n: sum(x >= n for x in qs)


def prior(pl, day):
    return [qs for d, qs in G.get(pl, []) if d < day]


L = sqlite3.connect("lines.db")
close = {}
for pl, st, kind, line, start, ls in L.execute("select player, stat, kind, line, start, last_seen from pp where league=7 and stat like 'Quarters with %'"):
    day = datetime.datetime.fromisoformat(start).astimezone(CT).date().isoformat()
    k = (day, nn(pl), st, kind)
    if k not in close or (ls or "") > close[k][1]:
        close[k] = (line, ls or "")
rows = []
for (day, pl, st, kind), (line, _) in close.items():
    n = 3 if "3+" in st else 5
    game = [qs for d, qs in G.get(pl, []) if d == day]
    if not game:
        continue
    pr = prior(pl, day)
    act = cnt(game[0], n)
    p_own = sum(cnt(qs, n) > line for qs in pr) / len(pr) if len(pr) >= 5 else None
    rows.append(dict(day=day, pl=pl, st=st, kind=kind, line=line, act=act, hit=act > line, p_own=p_own, n=len(pr)))
print("GRADED %d archived lines (more side; PP only offers more on demons/goblins)" % len(rows))
for st in ("Quarters with 3+ Points", "Quarters with 5+ Points"):
    for kind in ("demon", "goblin"):
        X = [r for r in rows if r["st"] == st and r["kind"] == kind]
        if not X:
            continue
        print("\n %s  %s: %d-%d (%.1f%% hit)" % (st, kind, sum(r["hit"] for r in X), sum(not r["hit"] for r in X), 100 * sum(r["hit"] for r in X) / len(X)))
        for ln in sorted({r["line"] for r in X}):
            Y = [r for r in X if r["line"] == ln]
            print("    line %-4g %4d-%-4d %5.1f%%" % (ln, sum(r["hit"] for r in Y), len(Y) - sum(r["hit"] for r in Y), 100 * sum(r["hit"] for r in Y) / len(Y)))
        Z = [r for r in X if r["p_own"] is not None]
        for lo, hi in ((0, .3), (.3, .45), (.45, .6), (.6, 1.01)):
            Y = [r for r in Z if lo <= r["p_own"] < hi]
            if Y:
                print("    own season rate %2.0f-%3.0f%%: %4d-%-4d %5.1f%%" % (100 * lo, 100 * hi, sum(r["hit"] for r in Y), len(Y) - sum(r["hit"] for r in Y), 100 * sum(r["hit"] for r in Y) / len(Y)))
json.dump(rows, open("quarters_graded.json", "w"))
# today's board
d = json.load(open("data/ppcache/league_7.json", encoding="utf-8"))
PL = {i["id"]: i["attributes"] for i in d.get("included", []) if i["type"] == "new_player"}
today = datetime.datetime.now(CT).date().isoformat()
print("\nTODAY %s -- own season rate of MORE at PP's line (5+ games this season)" % today)
out = []
for x in d["data"]:
    a = x["attributes"]
    if not a["stat_type"].startswith("Quarters with") or datetime.datetime.fromisoformat(a["start_time"]).astimezone(CT).date().isoformat() != today:
        continue
    p = PL[x["relationships"]["new_player"]["data"]["id"]]; pl = nn(p["name"]); n = 3 if "3+" in a["stat_type"] else 5
    pr = prior(pl, today)
    if len(pr) < 5:
        continue
    ln = float(a["line_score"]); c = [cnt(qs, n) for qs in pr]
    out.append((sum(v > ln for v in c) / len(c), p["name"], p.get("team"), a["stat_type"], a.get("odds_type"), ln, len(c), " ".join(map(str, c[::-1][:10]))))
for r in sorted(out, reverse=True)[:25]:
    print("  %5.1f%%  %-22s %-4s %-24s %-6s more %-4g (n=%d)  last10: %s" % ((100 * r[0],) + r[1:]))
