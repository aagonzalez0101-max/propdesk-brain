"""LIVE LINE CHECK (10/28): type a PrizePicks LIVE line, get FanDuel's in-play number for the same player/stat and the probability.

    python _live_check.py "Castle" pra 26.5          # fuzzy player name, stat = pts|reb|ast|pra|pr|pa|ra|3pm, PP's line
    python _live_check.py "Castle" pra 26.5 "Fox" pts 15.5     # several at once

PP's live lines are in-app only (not in the free feed), so this is the manual half of the Upside "+EV Sniper": you read the PP
live line, this prices it against FanDuel live in a few seconds. 60%+ on a side = PP 2-pick break-even 57.7% cleared.
"""
import sys
import _single_check as SC, _xcheck as X

STAT = {"pts": ("Points", "points"), "reb": ("Rebounds", "rebounds"), "ast": ("Assists", "assists"), "3pm": ("Made Threes", "threes made"),
        "pra": ("Pts + Reb + Ast", "pts & rebs & asts"), "pr": ("Pts + Reb", "pts & rebs"), "pa": ("Pts + Ast", "pts & asts"),
        "ra": ("Reb + Ast", "rebs & asts")}


def main(args):
    B = SC.nba_board()
    for i in range(0, len(args) - 2, 3):
        name, st, line = args[i].lower(), args[i + 1].lower(), float(args[i + 2])
        fd, canon = STAT[st]
        hits = [(pl, q) for (pl, s), q in B.items() if s == fd and name.replace(" ", "") in pl]
        if not hits:
            print("%s %s: no FanDuel live market (game not live, or player not posted)" % (args[i], st)); continue
        for pl, q in hits:
            ln, (o, u) = min(q["ou"].items(), key=lambda kv: abs(kv[0] - line))
            po = X.p_at([(l, X.two_way(X.M_imp(a), X.M_imp(b))) for l, (a, b) in q["ou"].items() if a is not None and b is not None], line, canon)
            if po is None:
                print("%-22s %s: FanDuel live %s (o %+d / u %+d) -- too far from PP %s to price" % (pl, st, ln, o, u, line)); continue
            side, p = ("OVER", po) if po >= .5 else ("UNDER", 1 - po)
            tag = "  <-- SNIPE" if p >= .60 else ""
            print("%-22s %-4s PP %5s | FanDuel live %5s (o %+d / u %+d) | %s %.0f%%%s" % (pl, st, line, ln, o, u, side, 100 * p, tag))


if __name__ == "__main__":
    main(sys.argv[1:])
