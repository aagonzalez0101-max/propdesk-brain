"""Prediction-market pricing: consensus fair vs Kalshi book, AFTER FEES, plus a
sharp-liquidity detector.

Why (research 2026-09-15): pros on prediction markets (a) price against a blend
of sharp books, (b) always use LIMIT orders with expiry at event start, (c) shave
the price for the winner's fee, (d) tail large resting size, because a big
resting order means a syndicate wants the other side at that price.

Kalshi fee on a fill = 0.07 * C * P * (1-P) per contract, charged on the WINNING
side, so a 60c bet actually needs ~60c + 1.7c to break even.

  python _predmarket.py mlb            # every game: consensus vs Kalshi, fee-aware
  python _predmarket.py mlb --depth    # + biggest resting orders (sharp liquidity)
"""
import json, sys, urllib.request, io, datetime
sys.path.insert(0, "betting")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
H = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
KAL = "https://api.elections.kalshi.com/trade-api/v2"
g = lambda u: json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=30).read())
SERIES = {"mlb": "KXMLBGAME", "nfl": "KXNFLGAME"}


def fee(price_cents, contracts=1):
    """Kalshi trading fee, dollars: 0.07 * C * P * (1-P), rounded up to the cent."""
    p = price_cents / 100.0
    import math
    return math.ceil(0.07 * contracts * p * (1 - p) * 100) / 100


MON = {"JAN":1,"FEB":2,"MAR":3,"APR":4,"MAY":5,"JUN":6,"JUL":7,"AUG":8,"SEP":9,"OCT":10,"NOV":11,"DEC":12}


def ticker_date(t):
    """KXMLBGAME-26SEP182138MINLAA-MIN -> 2026-09-18"""
    try:
        core = t.split("-")[1]
        return "20%s-%02d-%s" % (core[:2], MON[core[2:5]], core[5:7])
    except Exception:
        return None


def kalshi_markets(sport):
    out, cur = [], ""
    for _ in range(6):
        u = f"{KAL}/markets?limit=200&status=open&series_ticker={SERIES[sport]}" + (f"&cursor={cur}" if cur else "")
        d = g(u)
        out += d.get("markets", [])
        cur = d.get("cursor") or ""
        if not cur:
            break
    return out


def book(ticker):
    ob = g(f"{KAL}/markets/{ticker}/orderbook?depth=20").get("orderbook_fp", {})
    yes = [(float(p), float(s)) for p, s in (ob.get("yes_dollars") or [])]
    no = [(float(p), float(s)) for p, s in (ob.get("no_dollars") or [])]
    best_yes = max((p for p, s in yes), default=None)          # best bid for YES
    best_no = max((p for p, s in no), default=None)            # best bid for NO
    ask_yes = (1 - best_no) if best_no is not None else None   # you buy YES here
    return dict(bid=best_yes, ask=ask_yes, yes=yes, no=no,
                depth_yes=sum(s for _, s in yes), depth_no=sum(s for _, s in no),
                big=sorted(yes + no, key=lambda x: -x[1])[:3])


if __name__ == "__main__":
    sport = sys.argv[1] if len(sys.argv) > 1 else "mlb"
    day = next((a for a in sys.argv[1:] if a.count("-") == 2), None) or         (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    want_depth = "--depth" in sys.argv
    import importlib.util
    spec = importlib.util.spec_from_file_location("cons", "_consensus.py")
    cons = importlib.util.module_from_spec(spec)
    import oddsapi as oa
    oa.ENABLED = True
    spec.loader.exec_module(cons)
    fair = {}
    for r in cons.consensus(sport):
        if not r["start"].startswith(day) and not r["start"].startswith(
                (datetime.date.fromisoformat(day) + datetime.timedelta(days=1)).isoformat() + "T0"):
            continue
        fair[r["home"]] = (r["fair_home"], r["game"], r["tightest"])
        fair[r["away"]] = (r["fair_away"], r["game"], r["tightest"])
    print(f"consensus games for {day}: {len(fair)//2}")
    print(f"{'market':44s} {'consensus':>9} {'kalshi ask':>10} {'fee':>6} {'edge':>7}  {'depth $':>9}")
    rows = []
    for m in kalshi_markets(sport):
        if ticker_date(m["ticker"]) != day:
            continue
        title = m.get("title", "")
        team = title.replace(" wins", "").strip()
        hit = next((t for t in fair if team and (team.lower() in t.lower() or t.lower().endswith(team.lower()))), None)
        if not hit:
            continue
        fp, game, tight = fair[hit]
        b = book(m["ticker"])
        if not b["ask"]:
            continue
        ask = b["ask"]
        f = fee(ask * 100)
        cost = ask + f
        edge = fp / cost - 1 if cost else 0
        rows.append((edge, hit, game, fp, ask, f, edge, b))
    for edge, hit, game, fp, ask, f, _, b in sorted(rows, key=lambda r: -r[0])[:14]:
        print(f"{(hit+' | '+game)[:44]:44s} {fp:8.1%} {ask:10.2f} {f:6.2f} {edge:+7.1%}  {b['depth_yes']+b['depth_no']:9.0f}")
        if want_depth and b["big"]:
            print("      big resting: " + ", ".join(f"${s:,.0f} @ {p:.2f}" for p, s in b["big"]))
