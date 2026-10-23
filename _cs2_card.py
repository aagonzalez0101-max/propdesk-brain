"""CS2 DAILY SLIPS -- PAPER ONLY (10/3 full backtest: no CS2 rule beats Underdog's break-even; do not bet these).

FULL-DATA VERDICT (cs2_priced_all fully graded 10/3, 2,227 model-favoured sides): model sides hit 52.7% vs 53.4% needed in
BOTH halves; the 6-9% band ~57% both halves but its neighbours don't support it (noise until proven); UD-vs-PP gap 1.5+ =
61% on 9/17-20 then 41% from 9/21. Slips are still built + graded nightly as a forward record.

    python _cs2_card.py [YYYY-MM-DD] [--roll 10]   # build today's slips -> cards/<date>__cs2.json
    python _cs2_card.py grade                       # grade every cards/*__cs2.json from cs2_paper.jsonl results

THE RULE v2 (10/3, ONE change): the leg source is the UNDERDOG vs PRIZEPICKS LINE GAP, not our model.
  Why: the model predicts kills no better than the line (MAE 5.38 vs 5.33 since 9/18); kills legs since 9/18 hit 52.3% (< 53.5%
  b/e) and the old 6-9%-edge rule's +10% replay was luck. When UD and PP disagree by 1.5+ on the same player/stat, UD's side
  toward the PP line hit 70% (28-12), 2+ = 68% -- grows with the gap, mechanism = one app's line is stale. Not proven (n=40).
  * legs = kills OR headshots, |PP line - UD line| >= 1.5, take UD's side TOWARD the PP number
  * Underdog main lines only (multiplier between 0.7x and 1.5x)
  * one leg per player; the two legs of a slip come from DIFFERENT matches
  * play EVERY qualifying slip -- NO ranking by edge (ranking within the band lost, 4th market where it did)
  * 2-pick slips at 3.5x x leg multipliers; stake 5% of the app's morning roll per slip
Legs come from the CS2 paper card (_cs2_live.py card -> cs2_paper.jsonl), so run that first.
"""
import sys, os, json, glob, datetime

CT = datetime.timezone(datetime.timedelta(hours=-5))
PAPER = "cs2_paper.jsonl"


PRICED = "cs2_priced_all.jsonl"          # every priced side, with pp_line


def qualifies(r):
    m = r.get("mult")
    if r.get("pp_line") is None or r.get("line") is None or not r.get("start"):
        return False
    gap = r["pp_line"] - r["line"]
    toward = "higher" if gap > 0 else "lower"
    return (abs(gap) >= 1.5 and r.get("side") == toward and r.get("kind") in ("k", "kills", "hs")
            and isinstance(m, (int, float)) and 0.7 < m < 1.5)


def build(day, roll):
    now = datetime.datetime.now(datetime.timezone.utc)
    lo = datetime.datetime.fromisoformat(day + "T00:00:00-05:00")
    hi = lo + datetime.timedelta(hours=30)                 # the CT day plus the overnight Asia/EU morning
    legs, seen = [], set()
    for l in open(PRICED, encoding="utf-8"):
        r = json.loads(l)
        if not qualifies(r) or r.get("result") is not None:
            continue
        st = datetime.datetime.fromisoformat(r["start"].replace("Z", "+00:00"))
        if not (max(lo, now) <= st < hi) or r["player"] in seen:
            continue
        seen.add(r["player"]); legs.append(r)
    legs.sort(key=lambda r: r["start"])                    # by START TIME, never by edge
    slips = []
    while len(legs) >= 2:
        a = legs.pop(0)
        b = next((x for x in legs if x["match"] != a["match"]), None)
        if not b:
            break
        legs.remove(b)
        slips.append(dict(venue="UD", n=2, pay=round(3.5 * a["mult"] * b["mult"], 2),
                          legs=[{k: x.get(k) for k in ("player", "team", "match", "start", "stat", "kind", "maps", "line", "pp_line", "side", "mult", "edge", "model_p")}
                                for x in (a, b)]))
    stake = round(roll * 0.05, 2)
    fn = os.path.join("cards", "%s__cs2.json" % day)
    if os.path.exists(fn) and "--force" not in sys.argv:
        old = json.load(open(fn, encoding="utf-8"))
        if any(datetime.datetime.fromisoformat(g["start"].replace("Z", "+00:00")) <= now for s in old["slips"] for g in s["legs"]):
            print("CS2 card %s locked (legs started)" % fn); return
    os.makedirs("cards", exist_ok=True)
    json.dump(dict(day=day, roll=roll, stake=stake, slips=slips), open(fn, "w", encoding="utf-8"), indent=1)
    print("CS2 PAPER SLIPS (NOT A BET) %s -- rule v2: UD vs PP line gap >= 1.5, UD side toward PP, every slip, $%.2f each (5%% of $%.2f)" % (day, stake, roll))
    if not slips:
        print("  no qualifying pairs yet (legs post closer to match time -- the card reruns 09:15 and 21:00)")
    for i, s in enumerate(slips, 1):
        print("  slip %d  pays %.2fx" % (i, s["pay"]))
        for g in s["legs"]:
            t = datetime.datetime.fromisoformat(g["start"].replace("Z", "+00:00")).astimezone(CT).strftime("%a %I:%M%p")
            print("     %-14s %-6s %5s %-22s x%.2f  PP has %-5s  %s (%s)" % (g["player"], "OVER" if g["side"] == "higher" else "UNDER",
                  g["line"], g["stat"], g["mult"], g["pp_line"], g["match"], t))


# ---------------------------------------------------------------------------------------------------------------------------------
# RULE v3 "UNDERDOG UNDER" (10/23, user: "tweak esports"). 3,128 graded cs2_paper legs: LOWER + model edge >= 6% + Maps 1+2
# (kills or headshots) + the player's team < 40% to win the map = 79-37 (68%), Sep 58-25 / Oct 21-12. Mechanism: a team that
# loses the map plays fewer rounds -> fewer kills/HS (rounds drive kills, project_cs2_rounds_not_state). Cut alongside it:
# Map-1 kills lower (46%), overs at 12%+ edge (48%), 46+ projected rounds (42%). PAPER until it holds forward (esports = paper).
def dog_under(r):
    e = float(r.get("edge") or 0); e = e * 100 if abs(e) < 1 else e
    wp = r.get("map_winp"); ln = r.get("pp_line")
    return (r.get("side") == "lower" and e >= 6 and "1+2" in (r.get("stat") or "") and wp is not None and float(wp) < 0.40
            and (ln is None or float(ln) >= float(r.get("line") or 0)))       # 10/23: UD closed -> 'line' IS the PP line now (pp_line empty)


def build_dog(day):
    now = datetime.datetime.now(datetime.timezone.utc)
    lo = datetime.datetime.fromisoformat(day + "T00:00:00-05:00"); hi = lo + datetime.timedelta(hours=30)
    legs, seen = [], set()
    for l in open(PAPER, encoding="utf-8"):
        r = json.loads(l)
        if r.get("result") is not None or not r.get("start") or not dog_under(r):
            continue
        st = datetime.datetime.fromisoformat(r["start"].replace("Z", "+00:00"))
        if not (max(lo, now) <= st < hi) or r["player"] in seen:
            continue
        seen.add(r["player"]); legs.append(r)
    legs.sort(key=lambda r: r["start"])
    slips = []
    while len(legs) >= 2:
        a = legs.pop(0); b = next((x for x in legs if x["match"] != a["match"]), None)
        if not b:
            break
        legs.remove(b)
        slips.append(dict(venue="PP", n=2, pay=3.0, rule="v3 underdog under",
                          legs=[{k: x.get(k) for k in ("player", "team", "match", "start", "stat", "kind", "maps", "line", "pp_line", "side", "edge", "map_winp", "model_p")}
                                for x in (a, b)]))
    fn = os.path.join("cards", "%s__cs2u.json" % day)
    os.makedirs("cards", exist_ok=True)
    json.dump(dict(day=day, rule="v3 underdog under", slips=slips), open(fn, "w", encoding="utf-8"), indent=1)
    print("CS2 v3 UNDERDOG UNDER (PAPER) %s: %d slips (rule backtest 79-37, 68%%)" % (day, len(slips)))
    for i, s in enumerate(slips, 1):
        for g in s["legs"]:
            t = datetime.datetime.fromisoformat(g["start"].replace("Z", "+00:00")).astimezone(CT).strftime("%a %I:%M%p")
            print("   slip %d  %-14s UNDER %5s %-22s team map-win %.0f%%  edge %s  %s (%s)" % (i, g["player"], g["pp_line"] or g["line"], g["stat"], 100 * float(g["map_winp"]), g["edge"], g["match"], t))


def grade():
    res = {}
    for l in list(open(PAPER, encoding="utf-8")) + list(open(PRICED, encoding="utf-8")):
        r = json.loads(l)
        if r.get("result") in ("W", "L", "VOID"):
            res[(r["player"], r["match"], r.get("start"), r.get("stat"), r.get("line"))] = r["result"]
    tot_s = tot_w = 0; net = 0.0
    for fn in sorted(glob.glob(os.path.join("cards", "*__cs2*.json"))):
        c = json.load(open(fn, encoding="utf-8"))
        for s in c["slips"]:
            rs = [res.get((g["player"], g["match"], g["start"], g["stat"], g["line"])) for g in s["legs"]]
            if None in rs:
                s["result"] = "PENDING"; continue
            if "VOID" in rs:
                s["result"] = "VOID"; continue                     # UD drops the leg; treat the slip as a push
            s["result"] = "W" if all(x == "W" for x in rs) else "L"
            tot_s += 1; tot_w += s["result"] == "W"; net += (s["pay"] - 1) if s["result"] == "W" else -1
        json.dump(c, open(fn, "w", encoding="utf-8"), indent=1)
        print("  %s: %s" % (os.path.basename(fn), " ".join(s.get("result", "?") for s in c["slips"]) or "no slips"))
    print("CS2 RULE live record: %d-%d slips, flat $1/slip %+.2f" % (tot_w, tot_s - tot_w, net))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "grade":
        grade()
    else:
        day = next((x for x in a if len(x) == 10 and x[4] == "-"), datetime.datetime.now(CT).date().isoformat())
        roll = float(a[a.index("--roll") + 1]) if "--roll" in a else 10.0
        build(day, roll)
        build_dog(day)
