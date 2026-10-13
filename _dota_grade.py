"""Grade Dota 2 paper legs (dota_paper.jsonl) from OpenDota maps already pulled into dota_matches.jsonl (10/13: nothing graded Dota
automatically -- the 10/11 Spirit vs PARIVISION legs sat open).
    python _dota_grade.py
MAPS 1-2 kills = the player's kills in the first two maps (lowest match ids) of that series: same day +-1, opponent name matched loosely
(PP "TSpirit" ~ "Team Spirit", "Vision" ~ "PARIVISION"). Combos sum every named player. No map data yet -> stays open.
"""
import json, re, collections, datetime

norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
M = collections.defaultdict(list)                     # player name -> [(date, match_id, opp, kills)]
for l in open("dota_matches.jsonl", encoding="utf-8"):
    if l.strip():
        r = json.loads(l)
        M[norm(r.get("name"))].append((r["date"], r["match_id"], norm(r.get("opp")), r.get("kills") or 0))


def kills(name, day, opp):
    d0 = datetime.date.fromisoformat(day)
    o = norm(opp)[-5:]
    rows = sorted({(mid, k) for d, mid, op, k in M.get(norm(name), [])
                   if abs((datetime.date.fromisoformat(d) - d0).days) <= 1 and (o in op or op[-5:] in norm(opp))})
    return sum(k for _, k in rows[:2]) if len(rows) >= 2 else None


R = [json.loads(l) for l in open("dota_paper.jsonl", encoding="utf-8") if l.strip()]
n = 0
for r in R:
    if r.get("result") is not None:
        continue
    day = (r.get("start") or r.get("date"))[:10]
    vals = [kills(p.strip(), day, r.get("opp")) for p in r["player"].split("+")]
    if not vals or any(v is None for v in vals):
        continue
    a = sum(vals); r["actual"] = a
    r["result"] = "PUSH" if a == r["line"] else ("W" if (a > r["line"]) == (r["side"] == "over") else "L")
    n += 1
open("dota_paper.jsonl", "w", encoding="utf-8").write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in R))
c = collections.Counter(r.get("result") for r in R)
print("Dota paper: graded %d new | record %d-%d (%d open)" % (n, c["W"], c["L"], c[None]))
