"""PP-RAISED lines, paper (2026-10-09). _clv_pp.py: when PrizePicks raised a standard line before the game, the OVER still hit 61.8%
at the NEW number (n=55). Every hour: any standard line whose current number is above its first posted number (lines.db) and whose game
hasn't started -> raised_paper.jsonl (one row per projection). Graded nightly by _direction.py rows (same player/stat/day)."""
import sqlite3, json, os, datetime
CT = datetime.timezone(datetime.timedelta(hours=-5))
now = datetime.datetime.now(datetime.timezone.utc)
c = sqlite3.connect("lines.db")
rows = c.execute("""SELECT proj_id, league, player, team, stat, start, MIN(rowid), MAX(rowid) FROM pp WHERE kind='standard' GROUP BY proj_id
                    HAVING COUNT(*) > 1""").fetchall()
have = set()
if os.path.exists("raised_paper.jsonl"):
    have = {json.loads(l)["proj_id"] for l in open("raised_paper.jsonl", encoding="utf-8")}
new = 0
with open("raised_paper.jsonl", "a", encoding="utf-8") as f:
    for pid, lg, pl, team, stat, start, r0, r1 in rows:
        if pid in have or not start:
            continue
        try:
            if datetime.datetime.fromisoformat(start).astimezone(datetime.timezone.utc) < now:
                continue
        except Exception:
            continue
        first = c.execute("SELECT line FROM pp WHERE rowid=?", (r0,)).fetchone()[0]
        last = c.execute("SELECT line FROM pp WHERE rowid=?", (r1,)).fetchone()[0]
        if last > first:
            f.write(json.dumps(dict(proj_id=pid, league=lg, player=pl, team=team, stat=stat, first=first, line=last, side="over", start=start,
                                    logged=datetime.datetime.now(CT).isoformat(timespec="minutes"), result=None), ensure_ascii=False) + "\n"); new += 1
print("PP raised lines logged (paper over): %d new" % new)
