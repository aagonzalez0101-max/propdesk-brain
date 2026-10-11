"""SIDES fair-price board (10/11, user: "fix ml and totals and other lines that arent props so we get more value").
Measured: our own ML/totals models do NOT beat Pinnacle (MLB ML -1.2% on 141, totals negative skill, NFL Elo t=+0.05).
The value in sides is PRICE: Pinnacle is the sharp number, Fanatics is a soft book. Beat the fair price = +EV, no model needed.

  python _sides.py nfl|cfb|nhl|nba            # every game in the next 36h: fair ML / spread / total, de-vigged, + the price you need
  python _sides.py nfl "Bengals" -150         # moneyline check: is my Fanatics price above fair?
  python _sides.py nfl "Bengals -6.5" -110    # spread check (same points only)
  python _sides.py nfl "over 47.5" -110       # total check (first game with that total; add a team name to pick: "Bengals over 47.5")
Free: Pinnacle guest API only. Fair = proportional de-vig of the two-way price.
"""
import sys, datetime, re
sys.path.insert(0, ".")
from betting import freeodds as F

LEAGUE = {"nfl": 889, "cfb": 880, "nhl": 1456, "nba": 487}
CT = datetime.timezone(datetime.timedelta(hours=-5))


def dec(a):
    a = float(a)
    return 1 + (a / 100 if a > 0 else 100 / -a)


def amer(p):
    if p <= 0 or p >= 1:
        return "--"
    return "%+d" % round(-100 * p / (1 - p) if p >= 0.5 else 100 * (1 - p) / p)


def devig(a, b):
    ia, ib = 1 / dec(a), 1 / dec(b)
    return ia / (ia + ib), ib / (ia + ib)


def board(lg):
    mus = F._get("%s/0.1/leagues/%s/matchups?brandId=0" % (F.PIN, LEAGUE[lg])) or []
    mks = F._get("%s/0.1/leagues/%s/markets/straight" % (F.PIN, LEAGUE[lg])) or []
    now = datetime.datetime.now(datetime.timezone.utc)
    G = {}
    for mu in mus:
        if mu.get("parentId") or mu.get("type") != "matchup":
            continue
        side = {p["alignment"]: p["name"] for p in mu.get("participants", [])}
        if not side.get("home") or not side.get("away") or "(" in side["home"] + side["away"]:
            continue                                            # specials like "Away Runs (15 Games)"
        t = datetime.datetime.fromisoformat(mu["startTime"].replace("Z", "+00:00"))
        if not (now < t < now + datetime.timedelta(hours=36)):
            continue
        G[mu["id"]] = dict(home=side["home"], away=side["away"], t=t)
    for m in mks:
        g = G.get(m.get("matchupId"))
        if not g or m.get("period") != 0 or m.get("isAlternate"):
            continue
        px = {p.get("designation"): p for p in m.get("prices", [])}
        if m["type"] == "moneyline" and "home" in px and "away" in px:
            g["ml"] = (px["home"]["price"], px["away"]["price"])
        elif m["type"] == "spread" and "home" in px and "away" in px:
            g["sp"] = (px["home"]["points"], px["home"]["price"], px["away"]["price"])
        elif m["type"] == "total" and "over" in px and "under" in px:
            g["tot"] = (px["over"]["points"], px["over"]["price"], px["under"]["price"])
    return sorted(G.values(), key=lambda g: g["t"])


def show(lg):
    B = board(lg)
    print("%s -- %d games, Pinnacle de-vigged. 'fair' = the break-even: a Fanatics price BETTER than fair is +EV." % (lg.upper(), len(B)))
    print("%-16s %-24s %-24s %-22s %-22s" % ("time (TX)", "game", "moneyline fair", "spread fair", "total fair"))
    for g in B:
        ml = sp = tt = "--"
        if "ml" in g:
            ph, pa = devig(*g["ml"]); ml = "%s %s / %s %s" % (_ab(g["away"]), amer(pa), _ab(g["home"]), amer(ph))
        if "sp" in g:
            pts, h, a = g["sp"]; ph, pa = devig(h, a); sp = "%s %+g %s / %s" % (_ab(g["home"]), pts, amer(ph), amer(pa))
        if "tot" in g:
            pts, o, u = g["tot"]; po, pu = devig(o, u); tt = "o%g %s / u %s" % (pts, amer(po), amer(pu))
        print("%-16s %-24s %-24s %-22s %-22s" % (g["t"].astimezone(CT).strftime("%a %I:%M%p"), (_ab(g["away"]) + " @ " + _ab(g["home"]))[:24], ml, sp, tt))


def _ab(n):
    return n.split()[-1][:10]


def check(lg, what, price):
    B = board(lg); w = what.lower(); price = float(price)
    m = re.search(r"(over|under|o|u)\s*(\d+(\.\d+)?)", w)
    pt = re.search(r"([+-]\d+(\.\d+)?)\s*$", what.strip())
    for g in B:
        names = {"home": g["home"].lower(), "away": g["away"].lower()}
        hit = [k for k, n in names.items() if any(tok in n for tok in re.findall(r"[a-z]{3,}", w) if tok not in ("over", "under"))]
        if m and "tot" in g and float(m.group(2)) == g["tot"][0] and (hit or not re.findall(r"[a-z]{3,}", re.sub(r"over|under", "", w))):
            po, pu = devig(g["tot"][1], g["tot"][2]); p = po if m.group(1).startswith("o") else pu; lab = "%s %s @ %s %s" % (m.group(1), m.group(2), _ab(g["away"]), _ab(g["home"]))
        elif hit and pt and not m and "sp" in g:
            k = hit[0]; pts = g["sp"][0] if k == "home" else -g["sp"][0]
            if float(pt.group(1)) != pts:
                print("Pinnacle has %s at %+g, not %s -- different number, no clean check (each half point near 3/7 is worth real %%)." % (g[k], pts, pt.group(1))); return
            ph, pa = devig(g["sp"][1], g["sp"][2]); p = ph if k == "home" else pa; lab = "%s %+g" % (g[k], pts)
        elif hit and not m and not pt and "ml" in g:
            k = hit[0]; ph, pa = devig(*g["ml"]); p = ph if k == "home" else pa; lab = "%s ML" % g[k]
        else:
            continue
        be = 1 / dec(price); ev = p * dec(price) - 1
        print("%s  |  your price %+d needs %.1f%%  |  fair %.1f%% (%s)  |  EV %+.1f%%  ->  %s" % (lab, price, 100 * be, 100 * p, amer(p), 100 * ev,
              "CHECK THE PRICE -- 25%+ edge has been a typo/wrong game every time" if ev > 0.25 else
              "BET (beats the sharp number)" if ev >= 0.02 else "thin -- under 2%" if ev > 0 else "NO (worse than fair)"))
        return
    print("no matching game/market for %r in the next 36h" % what)


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) >= 3:
        check(a[0].lower(), a[1], a[2])
    else:
        for lg in ([a[0].lower()] if a else ["nfl", "cfb", "nhl", "nba"]):
            show(lg); print()
