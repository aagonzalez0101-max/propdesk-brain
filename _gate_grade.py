"""Grade the legs the form/H2H gate DROPPED (gate_drops.jsonl) -- is the gate saving us or costing us?
  python _gate_grade.py
'model L' = the model's side lost = the gate was RIGHT to drop it. 10/11 first read: CS2 model side 24-36 (gate right 60%), NHL 10-10.
Results come from what the nightly graders already settled: calls_log.jsonl (NHL/WNBA/NBA/soccer), cs2_paper.jsonl (CS2, +-1 day).
"""
import json, re, collections, datetime

norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
F = "gate_drops.jsonl"
D = [json.loads(x) for x in open(F, encoding="utf-8") if x.strip()]
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
for d in D:
    if d.get("result") is not None:
        continue
    if d["sport"] == "CS2":
        st = (d.get("start") or d["date"])[:10]
        m = [a for dt, a in C.get((norm(d["player"]), float(d["line"])), [])
             if abs((datetime.date.fromisoformat(dt) - datetime.date.fromisoformat(st)).days) <= 1]
        a = m[-1] if m else None
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
