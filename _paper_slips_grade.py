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
# 10/14: CS2 legs graded 0-14 because the generic box-score helper summed the wrong maps (deStiny 13 HS / trindade 21 K vs the real 19 / 31).
# CS2 legs now take the actual from cs2_paper.jsonl (the dedicated CS2 grader: same player, same line, same day +-1); CS2 legs graded the old
# way are reset once so they regrade.
import re as _re
_n = lambda x: _re.sub(r"[^a-z0-9]", "", (x or "").lower())
_CS = collections.defaultdict(list)
if os.path.exists("cs2_paper.jsonl"):
    for _l in open("cs2_paper.jsonl", encoding="utf-8"):
        _r = json.loads(_l)
        if _r.get("actual") is not None:
            _CS[(_n(_r.get("player")), "hs" if _r.get("kind") == "hs" else "k")].append(((_r.get("start") or _r.get("ts") or "")[:10], float(_r.get("pp_line") or _r.get("line") or 0), float(_r.get("line") or 0), _r["actual"]))
def _cs2_actual(g):
    k = (_n(g["player"]), "hs" if "Head" in g["stat"] else "k"); d0 = datetime.date.fromisoformat(g["start"][:10])
    c = [a for d, pl, ln, a in _CS.get(k, []) if d and abs((datetime.date.fromisoformat(d) - d0).days) <= 1 and float(g["line"]) in (pl, ln)]
    c = c or [a for d, pl, ln, a in _CS.get(k, []) if d and abs((datetime.date.fromisoformat(d) - d0).days) <= 1]
    return c[-1] if c else None
for r in rows:
    if r.get("cs2_regraded"):
        continue
    if any(g.get("sport") == "CS2" for g in r.get("legs", [])):
        for g in r["legs"]:
            if g.get("sport") == "CS2":
                g.pop("result", None); g.pop("actual", None)
        r["result"] = None
    r["cs2_regraded"] = True
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
            if g["sport"] == "CS2":
                a = _cs2_actual(g)
            else:
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
