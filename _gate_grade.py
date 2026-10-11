"""Grade the legs the form/H2H gate DROPPED (gate_drops.jsonl) -- is the gate saving us or costing us?
  python _gate_grade.py
'model L' = the model's side lost = the gate was RIGHT to drop it. 10/11 first read: CS2 model side 24-36 (gate right 60%), NHL 10-10.
Results come from what the nightly graders already settled: calls_log.jsonl (NHL/WNBA/NBA/soccer), cs2_paper.jsonl (CS2, +-1 day).
"""
import json, re, collections, datetime

norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
F = "gate_drops.jsonl"
D, _seen = [], set()
for x in open(F, encoding="utf-8"):                         # 10/11: the card runs every 15 min and re-logged each drop -> one row per leg
    if x.strip():
        d = json.loads(x); k = (d["date"], d["sport"], d["player"], d["stat"], d["line"], d["model_side"])
        if k not in _seen:
            _seen.add(k); D.append(d)
A = {}
for x in open("calls_log.jsonl", encoding="utf-8"):
    r = json.loads(x)
    if r.get("actual") is not None:
        A[(r.get("date"), norm(r["player"]), norm(r["stat"]))] = r["actual"]
C = collections.defaultdict(list)
for x in open("cs2_paper.jsonl", encoding="utf-8"):
    r = json.loads(x)
    if r.get("actual") is not None:
        C[(norm(r.get("player")), float(r.get("line") or 0))].append(((r.get("start") or r.get("ts"))[:10], r["actual"]))
# NFL: nflverse weekly box scores. Week = 1 + (game date - Tue 2026-09-08) // 7 (Thu 10/8 + Sun 10/11 = week 5).
# PP Fantasy Score ~ PPR fantasy points.
import csv, os
_NFLW = {}
if os.path.exists("nfl_2026_weekly.csv"):
    for r in csv.DictReader(open("nfl_2026_weekly.csv", encoding="utf-8")):
        _NFLW[(norm(r["player_display_name"]), int(r["week"]))] = r


def _nfl_actual(d):
    import _nfl_matchup as NM
    wk = 1 + (datetime.date.fromisoformat((d.get("start") or d["date"])[:10]) - datetime.date(2026, 9, 8)).days // 7
    r = _NFLW.get((norm(d["player"]), wk))
    if r is None:
        return None
    if d["stat"] == "Fantasy Score":
        return float(r.get("fantasy_points_ppr") or 0)
    f = NM.SK.get(d["stat"])
    return f(r) if f else None


for d in D:
    if d.get("result") is not None:
        continue
    if d["sport"] == "CS2":
        st = (d.get("start") or d["date"])[:10]
        m = [a for dt, a in C.get((norm(d["player"]), float(d["line"])), [])
             if abs((datetime.date.fromisoformat(dt) - datetime.date.fromisoformat(st)).days) <= 1]
        a = m[-1] if m else None
    elif d["sport"] == "NFL":
        a = _nfl_actual(d)
    else:
        a = A.get((d["date"], norm(d["player"]), norm(d["stat"])))
    if a is None:
        continue
    d["actual"] = a
    d["result"] = "push" if a == d["line"] else ("model W" if (a > d["line"]) == (d["model_side"] in ("over", "higher")) else "model L")
open(F, "w", encoding="utf-8").write("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in D))
T = collections.Counter((d["sport"], d["result"]) for d in D if d.get("result") in ("model W", "model L"))
print("GATE DROPS graded (model L = gate was right):")
for sp in sorted({k[0] for k in T}):
    w, l = T[(sp, "model W")], T[(sp, "model L")]
    print("  %-5s gate right %d of %d (%.0f%%)" % (sp, l, w + l, 100 * l / max(w + l, 1)))
