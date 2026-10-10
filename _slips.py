"""SLIP BUILDER -- the best 2- and 3-pick slips across every sport we screened today (2026-09-30).

    python _slips.py                          # today's slips from legs/<today>_*.json
    python _slips.py --promo "Kevin Lankinen|Goalie Saves|21.5|over|0.92|PP"    # best partners for a promo leg
    python _slips.py 2026-10-01               # another day

Rules built in (all measured or user-set):
  * value = probability x payout; a leg must clear its venue break-even (UD 2-pick 53.5% at 1.0x; PP 2-pick 57.7%)
  * our probability is BLENDED 60/40 with the app's own implied probability -- our hitter/bench numbers ran hot vs the
    20+ book consensus (9/29), so the market gets a real vote. Pinnacle-backed legs use Pinnacle instead.
  * TOO CLOSE calls never go on a slip; soccer never uses goblins; PP goblins/demons only as a promo leg
  * one player per slip, different teams (UD rule), at most ONE leg per game (no stacking a single game script)
  * PP and UD legs never mix; slip EV = product of probabilities x payout
"""
import sys, os, json, glob, itertools, datetime

CT = datetime.timezone(datetime.timedelta(hours=-5))
BE = {"UD": 1 / 3.5 ** 0.5, "PP": 1 / 3.0 ** 0.5}
PAY2 = {"UD": 3.5, "PP": 3.0}
PAY3 = {"UD": 6.5, "PP": 5.0}           # PP 3-pick power 5x, UD 3-pick 6.5x


# MONEY markets = validated on real lines / by backtest; everything else builds PAPER slips (tracked, not bet)
MONEY_STATS = {("MLB", "hits"), ("MLB", "hitsrunsrbis"), ("MLB", "totalbases"), ("NHL", "saves"), ("NHL", "goaliesaves")}
norm = lambda s: "".join(ch for ch in (s or "").lower() if ch.isalnum())


def money(l):
    return l.get("p_pin") is not None or (l["sport"], norm(l["stat"])) in MONEY_STATS


def load(day):
    legs = []
    for f in glob.glob(os.path.join("legs", "%s_*.json" % day)):
        legs += json.load(open(f, encoding="utf-8"))
    return legs


def prepare(legs):
    out = []
    for l in legs:
        call = l.get("call") or ""
        if not call.startswith(("TAKE", "LEAN")):
            continue
        want = "over" if "OVER" in call else "under"
        if l["side"] != want:
            continue
        if l.get("kind") in ("goblin", "demon"):
            continue
        if "MODEL OFF PINNACLE" in (l.get("flags") or []):
            continue                                   # projection >15% off Pinnacle's median = our error (2026-09-30)
        m = float(l.get("mult") or 1.0)
        venue = l.get("venue") or "PP"
        implied = min(0.95, BE[venue] / m) if venue == "UD" else 0.5
        if l.get("p_pin") is not None:
            p = l["p_pin"] if l["side"] == "over" else 1 - l["p_pin"]
            src = "pinnacle"
        else:
            p = 0.6 * float(l["p"]) + 0.4 * implied
            src = "blend"
        value = p * m
        if value < BE[venue]:
            continue
        game = "|".join(sorted([str(l.get("team")), str(l.get("opp"))]))
        out.append(dict(l, p_used=round(p, 3), value=round(value, 3), src=src, game=game, venue=venue, m=m))
    return out


def ok(combo):
    players = {c["player"] for c in combo}
    teams = {c["team"] for c in combo}
    games = [c["game"] for c in combo]
    return len(players) == len(combo) and len(teams) == len(combo) and len(set(games)) == len(games)


def best(legs, n=2, top=6):
    res = []
    for venue in ("UD", "PP"):
        pool = sorted([l for l in legs if l["venue"] == venue], key=lambda l: -l["value"])[:40]
        for combo in itertools.combinations(pool, n):
            if not ok(combo):
                continue
            prob = 1.0; pay = (PAY2 if n == 2 else PAY3)[venue]
            for c in combo:
                prob *= c["p_used"]; pay *= c["m"] if venue == "UD" else 1.0
            res.append((prob * pay - 1, prob, pay, venue, combo))
    res.sort(key=lambda x: -x[0])
    return res[:top]


def show(title, rows):
    print("\n" + title)
    if not rows:
        print("   none clear the bar")
    for ev, prob, pay, venue, combo in rows:
        overs = sum(c["side"] == "over" for c in combo)
        print("   %s %.2fx | hits %.0f%% | EV %+.0f%% | %d over / %d under" % (venue, pay, 100 * prob, 100 * ev, overs, len(combo) - overs))
        for c in combo:
            print("      %-8s %-22s %-5s %5s %-18s p %.0f%% (%s) x%.2f  %s" % (c["sport"], c["player"][:22], c["side"].upper(), c["line"],
                                                                     str(c["stat"])[:18], 100 * c["p_used"], c["src"], c["m"],
                                                                     ", ".join(c.get("flags") or [])))


def main():
    a = sys.argv[1:]
    day = next((x for x in a if len(x) == 10 and x[4] == "-"), datetime.datetime.now(CT).strftime("%Y-%m-%d"))
    legs = prepare(load(day))
    # one player per day: skip anyone already on a live ticket today
    taken = set()
    try:
        for l in open("live_paper.jsonl", encoding="utf-8"):
            r = json.loads(l)
            if r.get("kind") == "LIVE" and r.get("date") == day:
                for g in r.get("legs") or []:
                    if isinstance(g, dict) and g.get("player"):
                        taken.add(norm(g["player"]))
    except FileNotFoundError:
        pass
    if taken:
        legs = [l for l in legs if norm(l["player"]) not in taken]
        print("  skipping players already bet today: %d" % len(taken))
    print("SLIPS %s: %d legs clear their break-even after the market blend (%s)" % (
        day, len(legs), ", ".join("%s %d" % (s, sum(l["sport"] == s for l in legs)) for s in sorted({l["sport"] for l in legs}))))
    if "--promo" in a:
        f = a[a.index("--promo") + 1].split("|")
        promo = dict(sport="PROMO", player=f[0], stat=f[1], line=float(f[2]), side=f[3], p_used=float(f[4]), venue=f[5],
                     m=1.0, team="PROMO", game="PROMO", src="you", flags=["promo leg"])
        partners = sorted([l for l in legs if l["venue"] == promo["venue"] and l["player"] != promo["player"] and
                           (money(l) or "--paper" in a)], key=lambda l: -l["value"])[:8]     # money markets only
        show("BEST PARTNERS for the promo leg (%s %s %s %s):" % (promo["player"], promo["side"], promo["line"], promo["stat"]),
             [(promo["p_used"] * p["p_used"] * PAY2[promo["venue"]] - 1, promo["p_used"] * p["p_used"], PAY2[promo["venue"]], promo["venue"], (promo, p)) for p in partners])
        return
    M = [l for l in legs if money(l)]
    Pp = [l for l in legs if not money(l)]
    print("  money legs (validated markets / Pinnacle-backed): %d   paper legs: %d" % (len(M), len(Pp)))
    show("MONEY -- TOP 2-PICK SLIPS", best(M, 2))
    show("MONEY -- TOP 3-PICK SLIPS", best(M, 3, top=3))
    if "--paper" in a:
        show("PAPER (not validated -- track only) -- TOP 2-PICK", best(Pp, 2, top=4))


if __name__ == "__main__":
    main()
