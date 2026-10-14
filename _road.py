"""ROAD TO $500 (user 10/9: 'tmr is the first day since adding $45 ... road to 500'). Real money only, from road.json start_date.
    python _road.py        balance, % to goal, day-by-day P&L, record by SYSTEM/PROMO/OFF, today's 5% stake
Balance = start_roll + net of every graded LIVE row since start_date (pending rows are listed, never counted).
Same tagging as _mission.py. The future Discord #results header reads this."""
import json, collections, datetime
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):          # _mission prints its full report on import
    from _mission import tag, L
R = json.load(open("road.json", encoding="utf-8"))
S, G = R["start_date"], R["goal"]
live = [r for r in L if r.get("kind") == "LIVE" and r.get("date", "") >= S and not r.get("exclude")]
done = [r for r in live if r.get("result") in ("WIN", "LOSS", "PUSH", "VOID")]
DEP = sum(d["amount"] for d in R.get("deposits", []) if d["date"] <= datetime.date.today().isoformat())
bal = R["start_roll"] + DEP + sum(r.get("net") or 0 for r in done)
day = (datetime.date.today() - datetime.date.fromisoformat(S)).days + 1
pct = 100 * (bal - R["start_roll"]) / (G - R["start_roll"])
print("ROAD TO $%d  --  day %d   start $%.2f%s -> now $%.2f   (betting profit %+.2f)   %.0f%% of the way" % (G, max(day, 0), R["start_roll"],
      (" + $%.2f deposited" % DEP) if DEP else "", bal, bal - R["start_roll"] - DEP, max(pct, 0)))
bar = int(max(0, min(1, (bal - R["start_roll"]) / (G - R["start_roll"]))) * 30)
_morning = R["start_roll"] + DEP + sum(x.get("net") or 0 for x in done if x["date"] < datetime.date.today().isoformat())   # stake fixed on the morning roll
print("[" + "#" * bar + "-" * (30 - bar) + "]   today's stake (5%% of the morning roll $%.2f): $%.2f" % (_morning, R["stake_pct"] * _morning))
by = collections.defaultdict(list)
for r in done: by[r["date"]].append(r)
run = R["start_roll"]
for d in sorted(by):
    n = sum(r.get("net") or 0 for r in by[d]); run += n
    w = sum(r["result"] == "WIN" for r in by[d]); l = sum(r["result"] == "LOSS" for r in by[d])
    print("   %s   %d-%d   %+7.2f   roll $%.2f" % (d, w, l, n, run))
for t in ("SYSTEM", "PROMO", "OFF"):
    g = [r for r in done if tag(r) == t]
    if g:
        st = sum(r.get("stake") or 0 for r in g if r.get("funding") != "bonus"); n = sum(r.get("net") or 0 for r in g)
        print("   %-7s %d-%d   net %+.2f   ROI %s" % (t, sum(r["result"] == "WIN" for r in g), sum(r["result"] == "LOSS" for r in g), n, "%+.0f%%" % (100 * n / st) if st else "-"))
op = [r for r in live if r.get("result") in (None, "PENDING")]
if op:
    cash = sum(r.get("stake") or 0 for r in op if r.get("funding") != "bonus"); bonus = sum(r.get("stake") or 0 for r in op if r.get("funding") == "bonus")
    print("   open: %d bet(s), $%.2f cash at risk%s -> cash on hand $%.2f" % (len(op), cash, (" + $%.2f bonus" % bonus) if bonus else "", bal - cash))
