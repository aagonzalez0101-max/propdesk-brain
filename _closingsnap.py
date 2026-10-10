"""Capture CLOSING consensus prices so we can measure CLV -- the only metric that
tells us in ~50 bets whether the process is real (Buchdahl).

Run it near game time (or on a loop); it stores the multi-book consensus fair
probability per team into closing_lines.jsonl. `_clv.py` then joins that to the
ledger and reports CLV by market type -- sides, totals and props separately,
because they move differently.

  python _closingsnap.py mlb          # snapshot every game starting within 90 min
  python _closingsnap.py mlb --all    # snapshot the whole slate now
"""
import sys, json, datetime, io, importlib.util
sys.path.insert(0, "betting")
import oddsapi as oa
oa.ENABLED = True
spec = importlib.util.spec_from_file_location("cons", "_consensus.py")
cons = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cons)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sport = sys.argv[1] if len(sys.argv) > 1 else "mlb"
allg = "--all" in sys.argv
now = datetime.datetime.now(datetime.timezone.utc)
rows = cons.consensus(sport)
out = 0
with open("closing_lines.jsonl", "a", encoding="utf-8") as f:
    for r in rows:
        start = datetime.datetime.fromisoformat(r["start"].replace("Z", "+00:00"))
        mins = (start - now).total_seconds() / 60
        if not allg and not (0 <= mins <= 90):
            continue
        f.write(json.dumps(dict(ts=now.isoformat(), sport=sport, game=r["game"],
                                home=r["home"], away=r["away"], fair_home=r["fair_home"],
                                fair_away=r["fair_away"], books=r["books"],
                                tightest=r["tightest"], start=r["start"],
                                mins_to_start=round(mins))) + "\n")
        out += 1
print(f"snapshotted {out} games to closing_lines.jsonl")
