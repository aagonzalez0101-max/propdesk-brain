"""POLYMARKET vs PINNACLE (11/2, user: "ML work ... wanna do polymarket"). Free public Gamma API, no key/auth needed.
Polymarket prices game-winner markets as 0-1 "yes" share prices -- that IS the implied probability directly (no vig to
remove the way a sportsbook has, though the bid/ask spread on thin markets eats into real edge). Compares to Pinnacle's
de-vigged fair line (same source _sides.py uses) to find real mispricings.

    python _polymarket.py nba|nfl|nhl|mlb|cfb    # every game in the next 48h with both a Polymarket and Pinnacle price
"""
import sys, requests
import _sides as S

H = {"User-Agent": "Mozilla/5.0"}
TEAM_ALIAS = {  # Polymarket's short team name -> Pinnacle's name fragment, only where they'd otherwise mismatch
    "76ers": "philadelphia", "Timberwolv": "minnesota", "Trail Blazers": "portland",
}


def poly_games(hours=48):
    r = requests.get("https://gamma-api.polymarket.com/events?closed=false&limit=500&order=volume24hr&ascending=false", headers=H, timeout=20)
    out = []
    for e in r.json():
        t = e.get("title", "")
        if " vs. " not in t or any(x in t for x in ("FC", ":", "More Markets")):
            continue
        main = next((m for m in e.get("markets", []) if m.get("question") == t), None)
        if not main or not main.get("outcomePrices"):
            continue
        away, home = [x.strip() for x in t.split(" vs. ")]
        try:
            prices = [float(x) for x in eval(main["outcomePrices"])] if isinstance(main["outcomePrices"], str) else main["outcomePrices"]
            outcomes = eval(main["outcomes"]) if isinstance(main["outcomes"], str) else main["outcomes"]
        except Exception:
            continue
        p = dict(zip(outcomes, [float(x) for x in prices]))
        out.append(dict(title=t, away=away, home=home, p_away=p.get(away), p_home=p.get(home), vol=main.get("volume")))
    return out


def dec(a):
    a = float(a)
    return 1 + a / 100 if a > 0 else 1 - 100 / a


def main(sport):
    games = poly_games()
    pin = S.board(sport, hours=72)
    print("POLYMARKET vs PINNACLE -- %s, %d Polymarket games / %d Pinnacle games\n" % (sport.upper(), len(games), len(pin)))
    for g in games:
        match = next((r for r in pin if "ml" in r and (g["home"].lower() in r["home"].lower() or g["away"].lower() in r["away"].lower())), None)
        if not match:
            continue
        fair_home, fair_away = S.devig(*match["ml"])
        edge_home = g["p_home"] - fair_home if g["p_home"] else None   # positive = Polymarket UNDERPRICES home (buy)
        edge_away = g["p_away"] - fair_away if g["p_away"] else None
        print("%-30s  vol $%-8.0f  Pinnacle fair: %s %.0f%% / %s %.0f%%  |  Polymarket: %s %.0f%% (edge %+.1fpp) / %s %.0f%% (edge %+.1fpp)" % (
            g["title"], float(g["vol"] or 0), g["away"], 100 * fair_away, g["home"], 100 * fair_home,
            g["away"], 100 * g["p_away"], -100 * edge_away if edge_away else 0,
            g["home"], 100 * g["p_home"], -100 * edge_home if edge_home else 0))
    print("\n(edge = how much CHEAPER Polymarket's price is than Pinnacle's fair number -- positive = real value buying that side)")


if __name__ == "__main__":
    main(sys.argv[1].lower() if len(sys.argv) > 1 else "nba")
