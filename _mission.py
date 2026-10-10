"""THE MISSION RECORD -- real money only, from 2026-09-29 (day one of 'a living by December').
    python _mission.py            record, P&L, ROI by market, open bets, paper record
Reads live_paper.jsonl. A row counts when kind == LIVE and date >= START. Grading rule: a result is
WIN/LOSS/PUSH/VOID from box scores only; no box score = PENDING (never an estimate)."""
import json, collections
START = "2026-09-29"
L = [json.loads(l) for l in open("live_paper.jsonl", encoding="utf-8") if l.strip()]
live = [r for r in L if r.get("kind") == "LIVE" and r.get("date", "") >= START and not r.get("exclude")]   # exclude: user-removed rows (10/9 Fanatics unlogged)
paper = [r for r in L if r.get("kind") == "PAPER" and r.get("date", "") >= START]
def rec(R):
    g = [r for r in R if r.get("result") in ("WIN", "LOSS", "PUSH")]
    w = sum(r["result"] == "WIN" for r in g); l = sum(r["result"] == "LOSS" for r in g); p = len(g) - w - l
    cash = [r for r in g if r.get("funding") != "bonus" and r.get("stake")]
    st = sum(r["stake"] for r in cash); net = sum(r.get("net") or 0 for r in g)
    return w, l, p, st, net
def tag(r):
    """10/9: every bet is SYSTEM (a tested filter), PROMO, or OFF (everything else). An explicit r['system_tag'] wins."""
    if r.get("system_tag"):
        return r["system_tag"]
    m = (r.get("market") or "") + " " + (r.get("selection") or "") + " " + (r.get("note") or "")
    sp = (r.get("sport") or "")
    if any(k in m.lower() for k in ("promo", "taco", "flex friday", "boost")):
        return "PROMO"
    if "direction filter" in m.lower() or "ladder" in m.lower() or r.get("system"):
        return "SYSTEM"
    if set(re.split(r"[+/ ]", sp)) <= {"KBO", "NPB"} and r.get("book") in ("Courtside", None) and "parlay" not in m.lower()[:0] + "x":
        return "SYSTEM"
    return "OFF"
import re
for r in live:
    r["_tag"] = tag(r)
w, l, p, st, net = rec(live)
print("MISSION RECORD since %s:  %d-%d%s   staked $%.2f   net %+.2f   ROI %s" % (
    START, w, l, "-%d" % p if p else "", st, net, "%+.1f%%" % (100 * net / st) if st else "-"))
for t_ in ("SYSTEM", "PROMO", "OFF"):
    w_, l_, p_, st_, net_ = rec([r for r in live if r["_tag"] == t_])
    print("   %-7s %d-%d   staked $%.2f   net %+.2f   ROI %s" % (t_, w_, l_, st_, net_, ("%+.1f%%" % (100 * net_ / st_)) if st_ else "-"))
print()
by = collections.defaultdict(list)
for r in live: by["[%s] %s %s" % (r["_tag"], r.get("sport"), r.get("market", "").split(" (")[0])].append(r)
for k, R in sorted(by.items()):
    w, l, p, st, net = rec(R)
    if w + l + p: print("   %-40s %d-%d   net %+.2f" % (k, w, l, net))
op = [r for r in live if r.get("result") in (None, "PENDING")]
print("\nOPEN (%d):" % len(op))
for r in op: print("   %s %-10s $%-5s -> $%-6s %s" % (r["date"], r.get("book") or r.get("platform"), r.get("stake"), r.get("to_return"), r.get("selection", "")[:90]))
pw = sum(r.get("result") == "WIN" for r in paper); pl = sum(r.get("result") == "LOSS" for r in paper)
print("\nPAPER since %s: %d-%d  (%d open)" % (START, pw, pl, sum(r.get("result") in (None, "PENDING") for r in paper)))
