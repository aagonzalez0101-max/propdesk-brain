"""Consensus fair price from many books -- the input our model was missing.

Why: our board priced edges off ONE book (Kalshi, sometimes Pinnacle). Every
serious modeller (OddsJam/Alex Monahan tutorial, 2026-09-15) builds fair value
as a WEIGHTED AVERAGE of de-vigged prices across sharp books + exchanges, then
bets only when the price in hand beats that consensus.

  python _consensus.py mlb                 # today's board, consensus fair both sides
  python _consensus.py mlb "Angels" -125   # is my price better than consensus?

Weights: sharp books and liquid exchanges carry the market; retail books are
noise but still data. Props are the exception -- for player props US retail
(DK/FanDuel) is SHARPER than Pinnacle because that is where the volume is.
Market WIDTH (the two-way spread) is the confidence signal: tight = trust it.
"""
import sys, json, datetime, io
sys.path.insert(0, "betting")
import oddsapi as oa

W = {"pinnacle": 1.00, "betonlineag": 0.55, "lowvig": 0.45, "novig": 0.50,
     "prophetx": 0.50, "kalshi": 0.40, "polymarket": 0.30, "betopenly": 0.25,
     "circasports": 0.90}
RETAIL_W = 0.12
imp = lambda a: 100 / (a + 100) if a > 0 else -a / (-a + 100)
amer = lambda p: round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def consensus(sport="mlb"):
    ev = oa.get_odds(oa.SPORT_KEYS.get(sport, sport), markets="h2h", regions="us,us2,eu")
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    out = []
    for g in ev:
        if g["commence_time"] <= now:      # in-play prices are not a fair-value signal
            continue
        home, away = g["home_team"], g["away_team"]
        num = {home: 0.0, away: 0.0}
        den = 0.0
        widths = []
        books = 0
        for b in g.get("bookmakers", []):
            m = next((x for x in b.get("markets", []) if x["key"] == "h2h"), None)
            if not m:
                continue
            px = {o["name"]: o["price"] for o in m["outcomes"] if o["name"] in (home, away)}
            if len(px) != 2:
                continue
            ih, ia = imp(px[home]), imp(px[away])
            s = ih + ia
            if not 1.0 <= s < 1.30:
                continue
            w = W.get(b["key"], RETAIL_W)
            num[home] += w * ih / s
            num[away] += w * ia / s
            den += w
            widths.append(s - 1)
            books += 1
        if den == 0:
            continue
        fh, fa = num[home] / den, num[away] / den
        tight = min(widths) if widths else None
        out.append(dict(game=f"{away} @ {home}", home=home, away=away, fair_home=fh, fair_away=fa,
                        books=books, tightest=tight, start=g["commence_time"]))
    return out


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sport = sys.argv[1] if len(sys.argv) > 1 else "mlb"
    rows = consensus(sport)
    team = sys.argv[2] if len(sys.argv) > 2 else None
    price = float(sys.argv[3]) if len(sys.argv) > 3 else None
    print(f"{'game':46s} {'fair away':>10} {'fair home':>10} {'books':>5} {'tightest mkt':>13}")
    for r in sorted(rows, key=lambda r: r["start"]):
        if team and team.lower() not in r["game"].lower():
            continue
        print(f'{r["game"][:46]:46s} {r["fair_away"]:9.1%} ({amer(r["fair_away"]):+5d}) '
              f'{r["fair_home"]:9.1%} ({amer(r["fair_home"]):+5d}) {r["books"]:5d} {100*r["tightest"]:11.1f}%')
        if team and price is not None:
            side = r["away"] if team.lower() in r["away"].lower() else r["home"]
            fp = r["fair_away"] if side == r["away"] else r["fair_home"]
            mine = imp(price)
            edge = fp / mine - 1
            print(f'   -> {side}: consensus {fp:.1%} ({amer(fp):+d}), your price {price:+.0f} '
                  f'= {mine:.1%}  EDGE {edge:+.1%}  {"BET" if edge >= 0.03 else "PASS"}')
    print(f"\n{oa.budget_report()}")
