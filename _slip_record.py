"""SLIP RECORD (11/17, user: "can you do records of slips now? instead of legs"). Every settled LIVE slip in live_paper.jsonl, by
format, by system tag, by sport and by week -- W-L, money in, money back, net, ROI. Pending slips listed at the bottom.
    python _slip_record.py [since=2026-11-10]
"""
import json, sys, collections

since = sys.argv[1] if len(sys.argv) > 1 else "2026-11-10"
R = [json.loads(l) for l in open("live_paper.jsonl", encoding="utf-8") if l.strip()]
R = [r for r in R if r.get("kind") == "LIVE" and (r.get("date") or "") >= since]
done = [r for r in R if r.get("result") not in (None, "PENDING") and r.get("net") is not None]
pend = [r for r in R if r.get("result") in (None, "PENDING")]


def fmt_group(r):
    m = (r.get("market") or "").lower()
    if "flex" in m:
        return "flex"
    for n in ("2-pick", "3-pick", "4-pick", "5-pick", "6-pick"):
        if n in m:
            return n + (" + promo" if any(w in m for w in ("taco", "goblin", "flash", "promo")) else "")
    return m[:20] or "?"


def tag_group(r):
    t = (r.get("system_tag") or "").upper()
    for k in ("EDGE", "PROMO", "FLEX", "NATIONAL", "MEASURED", "CURATED", "MARKET", "STATS", "PROBATION", "SYSTEM"):
        if k in t:
            return k
    return "OTHER"


def line(lab, X):
    w = sum(r["result"] == "WIN" for r in X); l = sum(r["result"] == "LOSS" for r in X); o = len(X) - w - l
    stake = sum(float(r.get("stake") or 0) for r in X); net = sum(float(r.get("net") or 0) for r in X)
    return "  %-22s %3d-%-3d%s  staked $%6.2f  net %+7.2f  ROI %+5.0f%%" % (lab, w, l, (" (+%d other)" % o) if o else "           ", stake, net,
                                                                            100 * net / stake if stake else 0)


print("SLIP RECORD since %s -- %d settled, %d pending" % (since, len(done), len(pend)))
print(line("ALL SLIPS", done))
for title, key in (("BY FORMAT", fmt_group), ("BY SYSTEM", tag_group), ("BY SPORT", lambda r: r.get("sport") or "?"),
                   ("BY DAY", lambda r: r.get("date"))):
    print("\n" + title)
    g = collections.defaultdict(list)
    for r in done:
        g[key(r)].append(r)
    for k in sorted(g, key=lambda k: (title != "BY DAY" and -len(g[k]), k)):
        print(line(str(k), g[k]))
if pend:
    print("\nPENDING")
    for r in pend:
        legs = " / ".join("%s %s%s" % (x.get("player"), (x.get("side") or "?")[0].upper(), x.get("line")) for x in (r.get("legs") or []))
        print("  %s %-18s $%.2f -> $%.2f  %s" % (r.get("date"), r.get("market", "")[:18], float(r.get("stake") or 0), float(r.get("to_return") or 0), legs))
