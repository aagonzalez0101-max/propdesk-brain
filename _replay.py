"""Replay September day by day: what the NEW model would have bet vs the OLD one.

    python _replay.py [start] [end]

The rule is the one we actually played, not a backtest fantasy:

  * On each day we really bet, the replay places the SAME NUMBER of ordinary bets we placed,
    $10 each, taking that model's best moneyline value on the board that day.
  * The ladder is kept separate, exactly as it was: only on days we really laddered, one bet,
    inside the -120 to -200 band, 60% of the pot (never all-in -- all-in busts, measured).
  * Both models see the identical board and the identical games. The ONLY difference is the
    probability each one puts on a side, so every difference in the table is caused by the
    calibration staircase and nothing else.

Ordinary bets are meant to lose sometimes; the ladder is the compounding one. Keeping them
apart is the point -- mixing them hid which rule was actually working.
"""
import json, glob, sys, urllib.request, collections

be = lambda o: abs(o) / (abs(o) + 100) if o < 0 else 100 / (o + 100)
dec = lambda o: 1 + (o / 100 if o > 0 else 100 / abs(o))
FLAT = 10.0
LADDER_BAND = (-200, -120)
LADDER_BAR = 0.05
LADDER_FRAC = 0.60
LADDER_START = 25.0


def real_bets(path="live_paper.jsonl"):
    """How many ordinary MLB bets and how many ladder bets we really placed each day."""
    out = collections.defaultdict(lambda: {"flat": 0, "ladder": 0})
    for l in open(path, encoding="utf-8"):
        r = json.loads(l)
        d = r.get("date") or ""
        if not d.startswith("2026-09") or r.get("kind") != "LIVE":
            continue
        if r.get("sport") not in (None, "MLB"):
            continue
        if r.get("ladder") or "ladder" in (r.get("note") or "").lower():
            out[d]["ladder"] += 1
        else:
            out[d]["flat"] += 1
    return out


def boards():
    games = {}
    for f in sorted(glob.glob("pp/boards/2026-09-*.json")):
        try:
            b = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for p in b.get("picks", []):
            if p.get("market") == "ML" and p.get("raw") is not None:
                games.setdefault((b["day"], p["game"], p["selection"]), p)
    return games


def finals(days):
    fin = {}
    for day in days:
        try:
            d = json.loads(urllib.request.urlopen(
                "https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=%s" % day, timeout=30).read())
        except Exception:
            continue
        for dt in d.get("dates", []):
            for g in dt["games"]:
                if g["status"]["detailedState"] != "Final":
                    continue
                a, h = g["teams"]["away"], g["teams"]["home"]
                fin[(day, "%s @ %s" % (a["team"]["name"], h["team"]["name"]))] = (
                    a["team"]["name"] if a["score"] > h["score"] else h["team"]["name"],
                    "%d-%d" % (a["score"], h["score"]))
    return fin


def day_picks(games, fin, day, key, n, band=None, bar=None):
    c = []
    for (d2, game, sel), p in games.items():
        if d2 != day or (day, game) not in fin:
            continue
        if band and not (band[0] <= p["odds"] <= band[1]):
            continue
        v = p[key] / be(p["odds"]) - 1
        if bar is not None and v < bar:
            continue
        c.append((v, p, game))
    c.sort(key=lambda x: -x[0])
    return c[:n]


def main(start="2026-09-01", end="2026-09-30"):
    games = boards()
    real = real_bets()
    days = sorted({k[0] for k in games if start <= k[0] <= end})
    fin = finals(days)
    pot = {"new": LADDER_START, "old": LADDER_START}
    tot = {"new": [0, 0, 0.0], "old": [0, 0, 0.0]}
    lad = {"new": [0, 0], "old": [0, 0]}
    print("REPLAY -- same number of bets we really placed, $%d each, ladder kept separate\n" % FLAT)
    for day in days:
        r = real.get(day)
        if not r or (r["flat"] == 0 and r["ladder"] == 0):
            continue
        print("=" * 78)
        print("%s   we placed %d ordinary bet(s)%s" %
              (day, r["flat"], " + %d ladder" % r["ladder"] if r["ladder"] else ""))
        picks = {k: day_picks(games, fin, day, key, r["flat"])
                 for k, key in (("new", "raw"), ("old", "calibrated"))}
        if r["flat"]:
            print("  %-5s %-24s %6s %7s %7s  %-14s %s" %
                  ("", "pick", "odds", "model", "value", "result", "$"))
        for k, label in (("new", "NEW"), ("old", "OLD")):
            for v, p, game in picks[k]:
                won = fin[(day, game)][0] == p["selection"]
                pnl = FLAT * (dec(p["odds"]) - 1) if won else -FLAT
                tot[k][0 if won else 1] += 1
                tot[k][2] += pnl
                print("  %-5s %-24s %+6d %6.1f%% %+6.1f%%  %-14s %+6.2f" %
                      (label, p["selection"][:24], p["odds"],
                       100 * p["raw" if k == "new" else "calibrated"], 100 * v,
                       ("WON " if won else "lost") + " " + fin[(day, game)][1], pnl))
            if picks[k]:
                same = {x[1]["selection"] for x in picks["new"]} & {x[1]["selection"] for x in picks["old"]}
                if k == "old":
                    diff_new = [x[1]["selection"] for x in picks["new"] if x[1]["selection"] not in same]
                    diff_old = [x[1]["selection"] for x in picks["old"] if x[1]["selection"] not in same]
                    if diff_new or diff_old:
                        print("        -> they differ: NEW took %s, OLD took %s"
                              % (", ".join(diff_new) or "nothing extra", ", ".join(diff_old) or "nothing extra"))
                    else:
                        print("        -> same picks, no difference today")
        if r["ladder"]:
            for k, key in (("new", "raw"), ("old", "calibrated")):
                c = day_picks(games, fin, day, key, 1, LADDER_BAND, LADDER_BAR)
                if not c:
                    print("  %-5s LADDER: nothing qualified, pot stays $%.2f" % (k.upper(), pot[k]))
                    continue
                v, p, game = c[0]
                won = fin[(day, game)][0] == p["selection"]
                stake = pot[k] * LADDER_FRAC
                pot[k] += stake * (dec(p["odds"]) - 1) if won else -stake
                lad[k][0 if won else 1] += 1
                print("  %-5s LADDER %-20s %+6d  stake %6.2f  %-10s pot -> %.2f" %
                      (k.upper(), p["selection"][:20], p["odds"], stake,
                       "WON" if won else "lost", pot[k]))
    print("\n" + "=" * 78)
    print("ORDINARY BETS at $%d" % FLAT)
    for k, lab in (("new", "NEW (raw model)"), ("old", "OLD (nudged)")):
        w, l, net = tot[k]
        print("  %-18s %d-%d   net %+.2f" % (lab, w, l, net))
    print("LADDER from $%.0f, %d%% of pot" % (LADDER_START, 100 * LADDER_FRAC))
    for k, lab in (("new", "NEW (raw model)"), ("old", "OLD (nudged)")):
        print("  %-18s %d-%d   pot $%.2f" % (lab, lad[k][0], lad[k][1], pot[k]))
    print("TOTAL")
    for k, lab in (("new", "NEW (raw model)"), ("old", "OLD (nudged)")):
        print("  %-18s %+.2f" % (lab, tot[k][2] + pot[k] - LADDER_START))


if __name__ == "__main__":
    main(*(sys.argv[1:3] or ["2026-09-01", "2026-09-30"]))
