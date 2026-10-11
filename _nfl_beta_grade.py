"""Grade NFL BETA paper legs (nfl_beta_paper.jsonl) once nflverse posts the week (10/10: the beta earns real money only if Week 6 holds).
    python _nfl_beta_grade.py      # fetches the 2026 weekly stats, grades every leg whose game has stats, prints the running record
"""
import json, csv, io, re, urllib.request, datetime
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
f = lambda r, k: float(r.get(k) or 0)
STAT = {"Pass Yards": lambda r: f(r, "passing_yards"), "Rush Yards": lambda r: f(r, "rushing_yards"), "Receiving Yards": lambda r: f(r, "receiving_yards"),
        "Receptions": lambda r: f(r, "receptions"), "Rush Attempts": lambda r: f(r, "carries"), "Pass Attempts": lambda r: f(r, "attempts"),
        "Pass Completions": lambda r: f(r, "completions"), "Rush+Rec Yds": lambda r: f(r, "rushing_yards") + f(r, "receiving_yards"),
        "Fantasy Score": lambda r: 0.04 * f(r, "passing_yards") + 4 * f(r, "passing_tds") - f(r, "passing_interceptions")
        + 0.1 * (f(r, "rushing_yards") + f(r, "receiving_yards")) + 6 * (f(r, "rushing_tds") + f(r, "receiving_tds")) + f(r, "receptions")}
week = lambda d: (datetime.date.fromisoformat(d[:10]) - datetime.date(2026, 9, 9)).days // 7 + 1
raw = urllib.request.urlopen(urllib.request.Request("https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2026.csv",
                                                    headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read().decode()
open("nfl_2026_weekly.csv", "w", encoding="utf-8").write(raw)
B = {(norm(r["player_display_name"]), int(r["week"])): r for r in csv.DictReader(io.StringIO(raw))}
rows = [json.loads(l) for l in open("nfl_beta_paper.jsonl", encoding="utf-8")]
for r in rows:
    if r.get("result") or r["stat"] not in STAT:
        continue
    b = B.get((norm(r["player"]), week(r["start"])))
    if b:
        a = STAT[r["stat"]](b); r["actual"] = a
        r["result"] = "PUSH" if a == r["line"] else ("W" if (a > r["line"]) == (r["side"] == "over") else "L")
open("nfl_beta_paper.jsonl", "w", encoding="utf-8").write("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
w = sum(r.get("result") == "W" for r in rows); l = sum(r.get("result") == "L" for r in rows)
print("NFL BETA paper: %d-%d%s  (%d still waiting on stats)" % (w, l, " = %.0f%%" % (100 * w / (w + l)) if w + l else "", sum(not r.get("result") for r in rows)))
