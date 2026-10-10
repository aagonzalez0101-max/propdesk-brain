"""Closing Line Value report -- did we beat the closing consensus?

Buchdahl: beating the closing no-vig price is the signal that an edge is real,
and it shows up in as few as ~50 bets, far faster than profit does. Split by
market type; sides, totals and props move differently.

  python _clv.py            # every logged bet that has a closing snapshot
"""
import json, io, sys, collections, math
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

imp = lambda a: 100 / (a + 100) if a > 0 else -a / (-a + 100)
close = [json.loads(x) for x in open("closing_lines.jsonl", encoding="utf-8")] if __import__("os").path.exists("closing_lines.jsonl") else []
by = {}
for c in close:                                   # keep the LAST snapshot per game
    by[(c["game"], c["start"][:10])] = c
bets = [json.loads(x) for x in open("live_paper.jsonl", encoding="utf-8") if x.strip()]
rows = []
for b in bets:
    if b.get("kind") != "LIVE" or not b.get("odds") or not b.get("game"):
        continue
    # closing_lines.jsonl currently stores the MONEYLINE consensus only, so a
    # run line or total cannot be compared to it (that produced a bogus -15pp on
    # 2026-09-15). Snapshot spreads/totals before grading those.
    if b.get("market") not in ("ML", "MONEYLINE"):
        continue
    key = next((k for k in by if b["game"] in k[0] or k[0] in b["game"]), None)
    if not key:
        continue
    c = by[key]
    side = b.get("selection", "")
    fair = c["fair_home"] if side and side in c["home"] else (c["fair_away"] if side and side in c["away"] else None)
    if fair is None:
        continue
    mine = imp(float(b["odds"]))
    rows.append((b.get("market", "?"), fair - mine, b.get("result")))
if not rows:
    print("no bets yet have a closing snapshot -- run _closingsnap.py near game time")
else:
    g = collections.defaultdict(list)
    for m, clv, res in rows:
        g[m].append(clv)
        g["ALL"].append(clv)
    print(f"{'market':12s} {'n':>4} {'avg CLV':>9}  (positive = we beat the close)")
    for m, v in sorted(g.items(), key=lambda kv: -len(kv[1])):
        print(f"{m:12s} {len(v):4d} {100*sum(v)/len(v):+8.2f}pp")
    print("\nBar: +2pp CLV sustained over a few hundred bets is professional. "
          "~50 bets is enough to see whether it is real.")
