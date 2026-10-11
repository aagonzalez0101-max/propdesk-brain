"""Grade every logged slip in paper_slips.jsonl (10/11, user: "keep doing paper, I want everything to pass even if we don't bet").
Each leg is graded from the box score of its game date (same sources as _projcheck: NHL/WNBA/NBA sports.db, NFL nflverse, CS2/VAL/Dota
map files); a slip is W only if every leg hit, PENDING while any leg has no result. Prints the record per league and BET vs PAPER.
    python _paper_slips_grade.py
"""
import json, datetime, collections, os
import _projcheck as PC

F = "paper_slips.jsonl"
if not os.path.exists(F):
    raise SystemExit("no paper slips yet")
rows = [json.loads(l) for l in open(F, encoding="utf-8") if l.strip()]
now = datetime.datetime.now(datetime.timezone.utc)
for r in rows:
    if r.get("result"):
        continue
    res = []
    for g in r["legs"]:
        if g.get("result") is None:
            st = g.get("start")
            if not st or datetime.datetime.fromisoformat(st.replace("Z", "+00:00")) > now - datetime.timedelta(hours=4):
                res.append(None); continue
            day = st[:10]
            leg = PC.fill(dict(sport=g["sport"], player=g["player"], stat=g["stat"], line=g["line"], side=g["side"], bet=False), day)
            a = leg.get("actual")
            if a is not None:
                g["actual"] = a
                g["result"] = "PUSH" if a == g["line"] else ("W" if (a > g["line"]) == (g["side"] == "over") else "L")
        res.append(g.get("result"))
    if any(x == "L" for x in res):
        r["result"] = "L"
    elif res and all(x in ("W", "PUSH") for x in res):
        r["result"] = "W"
open(F, "w", encoding="utf-8").write("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
rec = collections.defaultdict(lambda: [0, 0, 0])
for r in rows:
    k = (r["tag"], r["league"])
    rec[k][2] += 1
    if r.get("result") == "W": rec[k][0] += 1
    if r.get("result") == "L": rec[k][1] += 1
print("SLIP RECORD (all logged slips, bet or paper):")
for (tag, lg), (w, l, n) in sorted(rec.items()):
    print("  %-5s %-22s %d-%d  (%d pending)" % (tag, lg, w, l, n - w - l))
legs = collections.defaultdict(lambda: [0, 0])
for r in rows:
    for g in r["legs"]:
        if g.get("result") in ("W", "L"):
            legs[g["sport"]][0 if g["result"] == "W" else 1] += 1
print("LEGS by sport: " + "  ".join("%s %d-%d" % (s, w, l) for s, (w, l) in sorted(legs.items())))
