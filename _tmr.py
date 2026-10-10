"""Tomorrow's ML board, built on free Pinnacle prices instead of the Odds API."""
import sys, json, os
sys.path.insert(0, ".")
sys.path.insert(0, "pp")
from betting import freeodds as F

day = sys.argv[1] if len(sys.argv) > 1 else "2026-09-07"
ev = F.kalshi_mlb()
json.dump(ev, open("odds_free.json", "w"))
print("pinnacle events cached: %d" % len(ev))

import board as B          # rebinds stdout on import, so import it last
b = B.build(day, "odds_free.json", None)
os.makedirs("pp/boards", exist_ok=True)
stamp = b["built_at"].replace(":", "").replace("-", "")[9:13]
path = "pp/boards/%s_%sZ.json" % (day, stamp)
json.dump(b, open(path, "w"), indent=1)
print("\nboard -> %s" % path)

ml = [r for r in b["picks"] if r["market"] == "ML"]
ml.sort(key=lambda r: -r["ev"])
print("\n%-9s %-42s %-7s %8s %8s %8s" % ("verdict", "pick", "odds", "market", "model", "EV"))
for r in ml:
    print("%-9s %-42s %+7.0f %7.1f%% %7.1f%% %+7.1f%%"
          % (r["verdict"], r["selection"][:42], r["odds"],
             100 * r["market_prob"], 100 * r["raw"], 100 * r["ev"]))
