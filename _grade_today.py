"""Grade every open MLB ticket in live_paper.jsonl against the statsapi finals."""
import json, io, sys, urllib.request, datetime as dt
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace", write_through=True)

F = "live_paper.jsonl"
rows = [json.loads(l) for l in open(F, encoding="utf-8") if l.strip()]
open_rows = [r for r in rows if not r.get("result")]

days = sorted({r["date"] for r in open_rows})
finals = {}          # "Away @ Home" -> (away, home, state)
for d in days:
    u = ("https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=%s"
         "&fields=dates,games,teams,home,away,score,team,name,status,detailedState" % d)
    sched = json.load(urllib.request.urlopen(u, timeout=45))
    for day in sched["dates"]:
        for g in day["games"]:
            h, a = g["teams"]["home"], g["teams"]["away"]
            key = "%s @ %s" % (a["team"]["name"], h["team"]["name"])
            finals[(d, key)] = (a.get("score"), h.get("score"),
                                g["status"]["detailedState"])

def score(day, game):
    return finals.get((day, game))

changed = 0
for r in open_rows:
    day = r["date"]
    if r.get("market") == "PARLAY":
        # every leg must be gradeable before the ticket settles
        verdicts = []
        for leg in r["legs"]:
            s = score(day, leg["game"])
            if not s or s[2] != "Final":
                verdicts.append(None); continue
            a, h = s[0], s[1]
            if leg.get("market") == "RUNLINE":
                # the named side must win by 2+
                fav_home = leg["selection"] in leg["game"].split(" @ ")[1]
                m = (h - a) if fav_home else (a - h)
                verdicts.append(m >= 2)
                leg["actual"] = "%s-%s (margin %+d)" % (a, h, m)
            elif leg.get("market") == "TOTAL":
                verdicts.append((a + h) > leg["line"])
                leg["actual"] = a + h
            else:
                verdicts.append(None)
        if None in verdicts:
            print("  %-58s legs pending" % r["bet"][:58]); continue
        r["result"] = "W" if all(verdicts) else "L"
        changed += 1
        print("  %-58s %s  legs %s" % (r["bet"][:58], r["result"],
              ["W" if v else "L" for v in verdicts]))
        continue

    if r.get("market") != "ML":
        print("  %-58s not auto-gradeable" % str(r.get("bet"))[:58]); continue
    s = score(day, r["game"])
    if not s:
        print("  %-58s game not found" % str(r.get("bet"))[:58]); continue
    if s[2] != "Final":
        print("  %-58s %s  %s-%s" % (str(r.get("bet"))[:58], s[2], s[0], s[1])); continue
    a, h = s[0], s[1]
    home_team = r["game"].split(" @ ")[1]
    picked_home = r["selection"] in home_team
    won = (h > a) if picked_home else (a > h)
    r["result"] = "W" if won else "L"
    r["result_note"] = "%s-%s" % (a, h)
    changed += 1
    print("  %-40s %-9s %+6.0f  %s   final %s-%s"
          % (str(r.get("bet"))[:40], r.get("verdict", ""), r.get("odds", 0),
             "WON " if won else "LOST", a, h))

with open(F, "w", encoding="utf-8") as fh:
    for r in rows:
        fh.write(json.dumps(r, default=str) + "\n")
print("\ngraded %d" % changed)

def dec(o):
    return 1 + (o / 100 if o > 0 else 100 / -o)

ml = [r for r in rows if r.get("market") == "ML" and r.get("result") in ("W", "L")]
# A row with no price cannot be valued -- count it in the record but keep it out
# of the unit maths, and say how many were dropped. Silently crashing here
# blocked nightly grading (2026-09-12); see feedback-ledger-hygiene.
priced = [r for r in ml if r.get("odds") is not None]
unpriced = len(ml) - len(priced)
w = sum(1 for r in ml if r["result"] == "W")
u = sum((dec(r["odds"]) - 1) if r["result"] == "W" else -1 for r in priced)
print("MLB ML TIER: %d-%d  units %+.2f  ROI %+.1f%%  (on %d priced)"
      % (w, len(ml) - w, u, 100 * u / max(len(priced), 1), len(priced)))
if unpriced:
    print("  !! %d graded ML row(s) had NO odds and were left out of the units"
          % unpriced)
