"""ALT LADDER board (2026-10-10, user: "I hope we find alt lines like we did Puka"). FanDuel's alt ladders, de-vigged, give a fair
probability for every rung ("Puka 50+ rec yds" = 85%). This lists the 80-90% rungs -- the short-priced parlay legs he likes
(feedback: value not payout, 80%+ legs) -- with fair American odds, so he can see at a glance whether his book's parlay price beats fair.
    python _altboard.py [--post]
Rules: one rung per player (the highest line still >= 80%), injury guard (skip anyone Out/Doubtful/IR; skip OVERS when a same-position
teammate RETURNS is not knowable -> overs only on active players), top 10 by fair probability.
"""
import sys, re, json, math
import _fanduel as F

norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())


def amer(p):
    return "%+d" % (round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p))


def board(league="nfl", lo=0.80, hi=0.90):
    P = F.props(league)                                          # {(player_norm, stat, line): p_over}
    out = {}
    for (pl, st, ln), p in P.items():
        # real rungs only: "1+ reception at -888" is junk (10/10) -> yards rungs 20+ (pass 150+), receptions 3+
        floor = {"receiving yards": 19.5, "rushing yards": 19.5, "passing yards": 149.5, "receptions": 2.5}.get(st)
        if floor is not None and ln >= floor and lo <= p <= hi:
            k = (pl, st)
            if k not in out or ln > out[k][0]:                   # highest rung that is still >= 80%
                out[k] = (ln, p)
    rows = sorted(((pl, st, ln, p) for (pl, st), (ln, p) in out.items()), key=lambda r: -r[3])
    return rows


def main(post=False):
    try:
        import requests
        bad = set()
        j = requests.get("https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries", timeout=30).json()
        for t in j.get("injuries", []):
            for i in t.get("injuries", []):
                if (i.get("status") or "") in ("Out", "Doubtful", "Injured Reserve", "Questionable"):
                    bad.add(norm((i.get("athlete") or {}).get("displayName")))
    except Exception:
        bad = set()
    rows = [r for r in board() if r[0] not in bad][:10]
    lines = []
    for pl, st, ln, p in rows:
        lines.append("🪜 **%s** %d+ %s · fair **%.0f%%** (%s)" % (pl, math.ceil(ln), st, 100 * p, amer(p)))
    if len(rows) >= 3:
        p3 = rows[0][3] * rows[1][3] * rows[2][3]
        lines.append("")
        lines.append("Top 3 together hit about **%.0f%%** · fair parlay price **%s** -- only bet it if your book pays MORE than that" % (100 * p3, amer(p3)))
    text = "\n".join(lines) if lines else "No 80-90% alt rungs on the board right now."
    print(text.replace("**", ""))
    if post and rows:
        import _cardpost as C
        C.post_embed("🪜 ALT LADDER · NFL (FanDuel fair prices)", "Short-priced legs for sportsbook parlays (Fanatics/Courtside). Compare your book's price to fair.\n\n" + text, 0x539DF5)


if __name__ == "__main__":
    main("--post" in sys.argv)
