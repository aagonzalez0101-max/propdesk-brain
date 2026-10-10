"""Venue router: every leg that PASSED the bar goes to its best home -- Courtside straight, or a
PrizePicks / Underdog pick'em pair.  Run it AFTER the legs are picked, BEFORE placing them.

    python _venue.py wnba "Kelsey Mitchell|points|over|19.5|0.62|-125" "A'ja Wilson|rebounds|over|10.5|0.60|+105"
    leg format:  player|stat|side|line|our_prob|courtside_price   (courtside price optional: "-" if none)

Why (2026-09-28): with 64% legs a PrizePicks 2-pick (3x) is ~+21% per ticket vs ~+12% for a book
2-leg parlay, but a lone leg or a plus-money leg belongs straight on Courtside. Compared on
expected LOG growth at a 5% stake -- EV alone would always pick the bigger payout.
The pick'em leg only counts if the app shows the SAME line (a point off swings 5-10%).
"""
import sys, math, itertools
from _price import underdog, prizepicks, norm

STAKE = 0.05
LEAGUE = {"mlb": 2, "wnba": 3, "nfl": 9, "nba": 7, "cfb": 15, "cs2": 265, "val": 159}
PP2 = 3.0            # PrizePicks 2-pick power
UD2 = 3.5            # Underdog 2-pick base payout -- CONFIRMED 3.5x by the user 2026-09-29 (per-option multipliers on top)
ALIAS = (("rebounds", "rebs"), ("assists", "asts"), ("points", "pts"), ("pointers", "pt"), ("3pt", "3pt"))


def cstat(x):
    """one spelling for every app: 'Rebounds + Assists' == 'Rebs+Asts' == 'rebs+asts'"""
    x = norm(x)
    for a, b in ALIAS:
        x = x.replace(a, b)
    return x


dec = lambda o: 1 + (o / 100 if o > 0 else 100 / -o)


def lg(outcomes):
    """expected log growth of the roll for [(prob, net_return_per_unit_stake)]"""
    return sum(p * math.log(1 + STAKE * r) for p, r in outcomes)


def parse(s):
    f = s.split("|")
    cs = None if len(f) < 6 or f[5].strip() in ("", "-") else float(f[5])
    return dict(player=f[0].strip(), stat=f[1].strip().lower(), side=f[2].strip().lower(),
                line=float(f[3]), p=float(f[4]), cs=cs)


def find_pp(board, leg):
    if not board:
        return None                      # call failed -- unknown, NOT absent
    for (nm, st), odds in board.items():
        if nm == norm(leg["player"]) and cstat(st) == cstat(leg["stat"]):
            std = odds.get("standard")
            if std is not None and float(std) == leg["line"]:
                return True
            if leg["side"] == "over" and odds.get("goblin") is not None and float(odds["goblin"]) == leg["line"]:
                return "goblin"          # goblins cut the multiplier -- flagged, not priced
    return False


def find_ud(board, leg):
    for (nm, st, ln), row in board.items():
        if nm == norm(leg["player"]) and cstat(st) == cstat(leg["stat"]) and ln == leg["line"]:
            side = row["sides"].get(leg["side"])
            if side:
                return float(side[1] or 1.0)
    return None


def main():
    sport, legs = sys.argv[1].lower(), [parse(a) for a in sys.argv[2:]]
    pp = prizepicks(LEAGUE.get(sport, 2))
    try:
        ud = underdog()
    except Exception as e:
        print("  (underdog unavailable: %s)" % e); ud = {}
    for L in legs:
        L["pp"], L["ud"] = find_pp(pp, L), find_ud(ud, L)
        L["g_cs"] = lg([(L["p"], dec(L["cs"]) - 1), (1 - L["p"], -1)]) if L["cs"] else None

    print("\n%-22s %-14s %6s %5s %8s %8s %6s %7s" % ("leg", "stat", "line", "prob", "courtside",
                                                   "CS edge", "PP", "UD mult"))
    for L in legs:
        edge = L["p"] * dec(L["cs"]) - 1 if L["cs"] else None
        print("%-22s %-14s %6s %4.0f%% %8s %8s %6s %7s" % (
            L["player"][:22], (L["side"][0] + " " + L["stat"])[:14], L["line"], L["p"] * 100,
            "%+d" % L["cs"] if L["cs"] else "-", "%+.1f%%" % (edge * 100) if edge is not None else "-",
            {True: "yes", False: "no", "goblin": "gob", None: "?"}[L["pp"]], "%.2fx" % L["ud"] if L["ud"] else "-"))

    # best pick'em pair per couple, vs placing both straight on Courtside
    options = []
    for a, b in itertools.combinations(range(len(legs)), 2):
        A, B = legs[a], legs[b]
        best = None
        if A["pp"] is True and B["pp"] is True:
            best = ("PrizePicks 2-pick", PP2)
        if A["ud"] and B["ud"]:
            m = UD2 * A["ud"] * B["ud"]
            if not best or m > best[1]:
                best = ("Underdog 2-pick", m)
        if not best:
            continue
        pw = A["p"] * B["p"]
        g_pair = lg([(pw, best[1] - 1), (1 - pw, -1)])
        g_split = sum(x["g_cs"] for x in (A, B) if x["g_cs"] is not None)
        options.append((g_pair - g_split, a, b, best, pw * best[1] - 1))
    options.sort(reverse=True)

    used, plan = set(), []
    for gain, a, b, (venue, mult), ev in options:
        if gain > 0 and a not in used and b not in used:
            used |= {a, b}
            plan.append("PAIR  %s + %s  -> %s %.2fx  (ticket EV %+.0f%%)" % (
                legs[a]["player"], legs[b]["player"], venue, mult, ev * 100))
    for i, L in enumerate(legs):
        if i in used:
            continue
        if L["g_cs"] is not None and L["g_cs"] > 0:
            plan.append("STRAIGHT  %s %s %s %s  -> Courtside %+d" % (L["player"], L["side"], L["line"],
                                                                     L["stat"], L["cs"]))
        else:
            plan.append("NO HOME  %s %s %s %s  (Courtside price doesn't clear, no pick'em partner)" % (
                L["player"], L["side"], L["line"], L["stat"]))
    print("\nPLAN")
    for p in plan:
        print("  " + p)
    if not pp:
        print("\n  PrizePicks call FAILED -- '?' means unknown, not absent. Re-run in a minute.")
    if any(L["pp"] == "goblin" for L in legs):
        print("\n  gob = only a goblin at that line; goblins pay less -- read the multiplier off the slip.")


if __name__ == "__main__":
    main()
