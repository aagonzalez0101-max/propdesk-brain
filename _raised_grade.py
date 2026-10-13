"""Grade PP-RAISED lines (raised_paper.jsonl) -- 10/13: 1,359 rows had never been graded (the docstring in _raised.py said _direction.py
did it; it didn't). NFL from nflverse weekly stats (nfl_2026_weekly.csv), CFB from sports.db box scores. Other leagues stay open.
    python _raised_grade.py
The question it answers: when PrizePicks RAISES a line before the game, does the OVER still hit at the new number? (10/9: 61.8%, n=55)
"""
import json, csv, re, sqlite3, datetime, collections, os

norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
f = lambda r, k: float(r.get(k) or 0)
NFL = {"Pass Yards": lambda r: f(r, "passing_yards"), "Rush Yards": lambda r: f(r, "rushing_yards"), "Receiving Yards": lambda r: f(r, "receiving_yards"),
       "Receptions": lambda r: f(r, "receptions"), "Rush Attempts": lambda r: f(r, "carries"), "Pass Attempts": lambda r: f(r, "attempts"),
       "Pass Completions": lambda r: f(r, "completions"), "Rush+Rec Yds": lambda r: f(r, "rushing_yards") + f(r, "receiving_yards"),
       "Pass+Rush Yds": lambda r: f(r, "passing_yards") + f(r, "rushing_yards"), "Rec Targets": lambda r: f(r, "targets"),
       "Fantasy Score": lambda r: 0.04 * f(r, "passing_yards") + 4 * f(r, "passing_tds") - f(r, "passing_interceptions")
       + 0.1 * (f(r, "rushing_yards") + f(r, "receiving_yards")) + 6 * (f(r, "rushing_tds") + f(r, "receiving_tds")) + f(r, "receptions")}
CFB = {"Pass Yards": ["pass_yds"], "Rush Yards": ["rush_yds"], "Receiving Yards": ["rec_yds"], "Receptions": ["rec"], "Rush Attempts": ["carries"],
       "Pass Attempts": ["att"], "Pass Completions": ["cmp"], "Rush+Rec Yds": ["rush_yds", "rec_yds"], "Pass+Rush Yds": ["pass_yds", "rush_yds"]}
W = {}
if os.path.exists("nfl_2026_weekly.csv"):
    for r in csv.DictReader(open("nfl_2026_weekly.csv", encoding="utf-8")):
        W[(norm(r["player_display_name"]), int(r["week"]))] = r
db = sqlite3.connect("sports.db")
CB = collections.defaultdict(dict)
for pl, d, js in db.execute("select player, date, stats from player_games where sport='CFB' and season='2026'"):
    CB[norm(pl)][d] = json.loads(js)
R = [json.loads(l) for l in open("raised_paper.jsonl", encoding="utf-8") if l.strip()]
n = 0
for r in R:
    if r.get("result") is not None or not r.get("start"):
        continue
    day = datetime.datetime.fromisoformat(r["start"]).astimezone(datetime.timezone(datetime.timedelta(hours=-5))).date()
    if day >= datetime.date.today():
        continue
    a = None
    if r["league"] == 9 and r["stat"] in NFL:
        b = W.get((norm(r["player"]), 1 + (day - datetime.date(2026, 9, 8)).days // 7))
        a = NFL[r["stat"]](b) if b else None
    elif r["league"] == 15 and r["stat"] in CFB:
        for dd in (day, day + datetime.timedelta(days=1)):
            b = CB.get(norm(r["player"]), {}).get(dd.isoformat())
            if b:
                a = sum(float(b.get(k) or 0) for k in CFB[r["stat"]]); break
    if a is None:
        continue
    r["actual"] = a
    r["result"] = "PUSH" if a == r["line"] else ("W" if (a > r["line"]) == (r.get("side", "over") == "over") else "L")
    n += 1
open("raised_paper.jsonl", "w", encoding="utf-8").write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in R))
T = collections.Counter((r["league"], r["result"]) for r in R if r.get("result") in ("W", "L"))
print("raised lines graded %d new | OVER at the raised number: NFL %d-%d, CFB %d-%d" % (n, T[(9, "W")], T[(9, "L")], T[(15, "W")], T[(15, "L")]))
