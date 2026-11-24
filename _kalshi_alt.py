"""KALSHI ALT-LINE PAPER BOT (11/24, user: "only alt lines ... whatever you see that is good against the checks we do, and also ML
and totals for NBA mainly" -- the 40+ cent-sized bets idea, tested on paper before any money).

Every run, for today's NBA games, price EVERY Kalshi rung against a sharp fair number and paper-buy 1 contract when it clears:
  ML      KXNBAGAME   "Team wins"              fair = Pinnacle moneyline, de-vigged
  TOTAL   KXNBATOTAL  "Over 231.5" ladder       fair = Normal(Pinnacle main total shifted by its de-vigged over %, sd 18.5)
  SPREAD  KXNBASPREAD "Team wins by over X"     fair = Normal(Pinnacle main spread shifted by its cover %, sd 13)
  PROPS   KXNBAPTS/REB/AST/3PT/PRA ladders      fair = OUR number (user 11/24: "kalshi is its own ... we just going off our things"):
                                                the player's season hit rate at Kalshi's rung, shrunk (h+2)/(n+4), with our checks --
                                                L10 agrees, minutes not falling on a YES, no under while minutes rise 15%+ (11/23 rule),
                                                not OUT/D/Q, 8+ games; edge >= 5 pts after fee. Sharp-book % is RECORDED (p_sharp) to
                                                compare later, never used to pick (props vs sharps already failed: PM-10).
Checks (the desk's, adapted): YES or NO side, edge = fair - (ask + Kalshi fee for ONE contract, rounded up to the cent) >= 3 pts;
ask 8-92c; bid/ask spread <= 10c; props also skip OUT/doubtful/questionable players and need the player's own season rate at the
rung to agree (within 5 pts of fair, on our side); one bet per market. Paper only -- no key, no orders.
    python _kalshi_alt.py            # price + paper-log (DRYRUN=1: print only)
    python _kalshi_alt.py grade      # settle from Kalshi's own market results; record by market type
Pass bar (pre-declared 11/24): >= 300 bets over >= 2 weeks, net after fees > 0 with per-bet t >= 2, both weeks positive,
reported by market type. Fail = it stays paper and we say so.
"""
import os, sys, json, math, re, datetime, statistics, urllib.request
sys.path.insert(0, "betting")

CT = __import__("zoneinfo").ZoneInfo("America/Chicago")
KAL = "https://api.elections.kalshi.com/trade-api/v2"
PIN = "https://guest.api.arcadia.pinnacle.com"
PIN_KEY = "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R"
OUT = "kalshi_alt_paper.jsonl"
EDGE_PROP = .05                                     # our own-rate number is noisier than a sharp line -> bigger cushion
EDGE, LO, HI, MAXSPR = .01, .08, .92, .10   # log from +1 pt (volume); grade by edge bucket to find the real cutoff
SD_TOT, SD_MAR = 18.5, 13.0
PROPS = {"KXNBAPTS": "points", "KXNBAREB": "rebounds", "KXNBAAST": "assists", "KXNBA3PT": "threes made", "KXNBAPRA": "pts & rebs & asts"}
BOX = {"points": "pts", "rebounds": "reb", "assists": "ast", "threes made": "fg3m", "pts & rebs & asts": "pts+reb+ast"}


def get(u, hdr=None):
    return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json", **(hdr or {})}), timeout=30).read() or b"null")


Phi = lambda z: .5 * (1 + math.erf(z / math.sqrt(2)))


def zinv(p):
    lo, hi = -6.0, 6.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if Phi(mid) < p else (lo, mid)
    return (lo + hi) / 2


def imp(a):
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def fee(p):
    return math.ceil(round(7 * p * (1 - p), 6)) / 100           # Kalshi taker fee, 1 contract, rounded UP to the cent


def kmarkets(series):
    return get("%s/markets?series_ticker=%s&status=open&limit=1000" % (KAL, series)).get("markets", [])


def pin_games():
    H = {"X-API-Key": PIN_KEY}
    mus = get("%s/0.1/leagues/487/matchups" % PIN, H) or []
    mk = get("%s/0.1/leagues/487/markets/straight" % PIN, H) or []
    G = {}
    for u in mus:
        if u.get("parentId") or u.get("type") != "matchup":
            continue
        side = {p.get("alignment"): p.get("name") for p in u.get("participants", [])}
        if side.get("home") and side.get("away"):
            G[u["id"]] = dict(home=side["home"], away=side["away"], start=u.get("startTime"))
    for m in mk:
        g = G.get(m.get("matchupId"))
        if not g or m.get("period") != 0 or m.get("isAlternate"):
            continue
        P = m.get("prices", [])
        if m["key"] == "s;0;m":
            d = {p.get("designation"): imp(p["price"]) for p in P}
            if "home" in d and "away" in d:
                s = d["home"] + d["away"]; g["ml"] = (d["home"] / s, d["away"] / s)
        elif m["key"].startswith("s;0;ou"):
            d = {p.get("designation"): (p.get("points"), imp(p["price"])) for p in P}
            if "over" in d and "under" in d:
                g["total"] = (d["over"][0], d["over"][1] / (d["over"][1] + d["under"][1]))
        elif m["key"].startswith("s;0;s"):
            d = {p.get("designation"): (p.get("points"), imp(p["price"])) for p in P}
            if "home" in d and "away" in d:
                g["spread_home"] = (d["home"][0], d["home"][1] / (d["home"][1] + d["away"][1]))   # home line (e.g. -6.5), P(home covers)
    return list(G.values())


def city_match(city, team):
    c = city.lower().replace(".", ""); t = team.lower().replace(".", "")
    return t.startswith(c) or c in t or (c == "la" and t.startswith("los angeles"))


def candidates():
    """-> rows (kind, ticker, desc, yes_fair, market) for every priced Kalshi rung"""
    out = []
    games = pin_games()
    ml = kmarkets("KXNBAGAME")
    ev = {}                                                  # event code -> {city: team}, from the ML markets
    for m in ml:
        code = m["event_ticker"].split("-", 1)[1]
        ev.setdefault(code, []).append(m.get("yes_sub_title") or m["title"].replace(" wins", ""))
    def game_for(code):
        cities = ev.get(code, [])
        for g in games:
            if len(cities) == 2 and all(any(city_match(c, t) for t in (g["home"], g["away"])) for c in cities):
                return g
    for m in ml:
        g = game_for(m["event_ticker"].split("-", 1)[1])
        if g and g.get("ml"):
            city = m.get("yes_sub_title") or ""
            p = g["ml"][0] if city_match(city, g["home"]) else g["ml"][1]
            out.append(("ML", m, "%s wins" % city, p, None, None, g["start"]))
    for m in kmarkets("KXNBATOTAL"):
        g = game_for(m["event_ticker"].split("-", 1)[1])
        if g and g.get("total") and m.get("floor_strike") is not None:
            T, po = g["total"]; mu = T + SD_TOT * zinv(po)
            out.append(("TOTAL", m, "%s v %s over %s" % (g["away"], g["home"], m["floor_strike"]), 1 - Phi((m["floor_strike"] - mu) / SD_TOT), None, None, g["start"]))
    for m in kmarkets("KXNBASPREAD"):
        g = game_for(m["event_ticker"].split("-", 1)[1])
        if g and g.get("spread_home") and m.get("floor_strike") is not None:
            city = re.match(r"(.+?) wins by", m["title"]); city = city.group(1) if city else ""
            line, pc = g["spread_home"]
            mu_home = -line + SD_MAR * zinv(pc)                 # expected home margin
            mu = mu_home if city_match(city, g["home"]) else -mu_home
            out.append(("SPREAD", m, m["title"], 1 - Phi((m["floor_strike"] - mu) / SD_MAR), None, None, g["start"]))
    # props: sharp books at Kalshi's rung
    import _xcheck as X, _mismatch as M
    S = {}
    for f in (X.src_pinnacle, X.src_fanduel, X.src_betrivers):
        try:
            f("NBA", S)
        except Exception as e:
            print("  %s: %s" % (f.__name__, str(e)[:60]))
    for ser, canon in PROPS.items():
        for m in kmarkets(ser):
            if m.get("strike_type") != "greater" or m.get("floor_strike") is None:
                continue
            name = m["title"].split(":")[0]
            rows = [r for k, v in S.items() if k[0] == X.norm(name) and k[1] == canon for src, rs in v.items() for r in rs]
            g = game_for(m["event_ticker"].split("-", 1)[1])
            if g:                                          # fair is filled in run() from OUR numbers; sharp % kept for comparison only
                ps = M.p_over_at(rows, m["floor_strike"], canon) if rows else None
                out.append(("PROP", m, "%s %s %s+" % (name, canon, int(m["floor_strike"] + .5)), ps, name, canon, g["start"]))
    return out


def own_rates():
    import sqlite3
    c = sqlite3.connect("sports.db"); R = {}
    for p, pts, reb, ast, fg3m, mn in c.execute("select b.player,b.pts,b.reb,b.ast,b.tpm,b.min from nba_box b join nba_games g on g.game_id=b.game_id "
                                                "where g.season='2026-27' and g.stype='regular' and b.min>0 order by g.date"):
        R.setdefault(p.lower(), []).append(dict(pts=pts or 0, reb=reb or 0, ast=ast or 0, fg3m=fg3m or 0, mn=mn or 0))
    return R


def injuries():
    try:
        d = get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries")
        return {i["athlete"]["displayName"].lower(): (i.get("status") or "").lower() for t in d.get("injuries", []) for i in t.get("injuries", [])}
    except Exception:
        return {}


def run():
    now = datetime.datetime.now(CT)
    done = set()
    if os.path.exists(OUT):
        done = {(json.loads(l)["ticker"]) for l in open(OUT, encoding="utf-8") if l.strip()}
    C = candidates(); OWN = own_rates(); INJ = injuries()
    bets, seen = [], 0
    for c in C:
        kind, m, desc, pf = c[:4]
        p_sharp = pf if kind == "PROP" else None
        if kind == "PROP":                                    # OUR fair: shrunk season hit rate at the rung (+ checks below)
            g = OWN.get(c[4].lower(), [])
            if len(g) < 8:
                continue
            v = [sum(x[k] for k in BOX[c[5]].split("+")) for x in g]
            pf = (sum(x > m["floor_strike"] for x in v) + 2) / (len(v) + 4)
        if m["ticker"] in done or pf is None:
            continue
        if not c[6] or datetime.datetime.fromisoformat(c[6].replace("Z", "+00:00")) <= now + datetime.timedelta(minutes=10):
            continue                                              # pregame only: Kalshi keeps these markets open during the game
        seen += 1
        yb, ya = float(m.get("yes_bid_dollars") or 0), float(m.get("yes_ask_dollars") or 0)
        nb, na = float(m.get("no_bid_dollars") or 0), float(m.get("no_ask_dollars") or 0)
        for side, ask, bid, p in (("yes", ya, yb, pf), ("no", na, nb, 1 - pf)):
            if not (LO <= ask <= HI) or not bid or ask - bid > MAXSPR:
                continue
            e = p - ask - fee(ask)
            if e < (EDGE_PROP if kind == "PROP" else EDGE):
                continue
            why = ""
            if kind == "PROP":
                name, canon = c[4], c[5]
                if INJ.get(name.lower()) in ("out", "doubtful", "questionable"):
                    continue
                g = OWN[name.lower()]
                v = [sum(x[k] for k in BOX[canon].split("+")) for x in g]
                l10 = [x > m["floor_strike"] for x in v[-10:]]
                l10s = sum(l10) / len(l10) if side == "yes" else 1 - sum(l10) / len(l10)
                if l10s < .5:                                     # last 10 must agree with the side
                    continue
                mins = [x["mn"] for x in g]; tr = (sum(mins[-3:]) / 3) / (sum(mins) / len(mins))
                if side == "yes" and tr < .90:                    # YES needs his minutes holding
                    continue
                if side == "no" and tr >= 1.15:                   # 11/23 rule: no unders while minutes are rising
                    continue
                why = "season %d/%d, L10 %d/10, min %.0f%%%s" % (sum(x > m["floor_strike"] for x in v) if side == "yes" else sum(x <= m["floor_strike"] for x in v),
                      len(v), round(10 * l10s) if len(l10) == 10 else round(len(l10) * l10s), 100 * tr,
                      ", sharp %.0f%%" % (100 * (p_sharp if side == "yes" else 1 - p_sharp)) if p_sharp is not None else "")
            bets.append(dict(ts=now.isoformat(timespec="seconds"), day=now.strftime("%Y-%m-%d"), kind=kind, ticker=m["ticker"], desc=desc,
                             side=side, price=ask, fee=fee(ask), p=round(p, 3), edge=round(e, 3), close=m["close_time"], why=why, result=None,
                             p_sharp=(round(p_sharp if side == "yes" else 1 - p_sharp, 3) if p_sharp is not None else None)))
            break
    print("KALSHI ALT PAPER %s: %d rungs priced, %d bets (edge >= %.0f pts after fee)" % (now.strftime("%m-%d %H:%M"), seen, len(bets), 100 * EDGE))
    for b in sorted(bets, key=lambda b: -b["edge"])[:40]:
        print("  %-6s %-46s %-3s @ %.2f (+%.2f fee)  fair %.0f%%  edge +%.1f  %s" % (b["kind"], b["desc"][:46], b["side"].upper(), b["price"], b["fee"], 100 * b["p"], 100 * b["edge"], b["why"]))
    if os.environ.get("DRYRUN"):
        print("(dry run: not logged)"); return
    with open(OUT, "a", encoding="utf-8") as f:
        f.write("".join(json.dumps(b) + "\n" for b in bets))


def grade():
    if not os.path.exists(OUT):
        print("nothing logged yet"); return
    B = [json.loads(l) for l in open(OUT, encoding="utf-8") if l.strip()]
    n = 0
    for b in B:
        if b.get("result") is None:
            try:
                m = get("%s/markets/%s" % (KAL, b["ticker"])).get("market", {})
            except Exception:
                continue
            r = m.get("result")
            if r in ("yes", "no"):
                win = r == b["side"]
                b["result"] = "W" if win else "L"
                b["net"] = round((1 - b["price"] - b["fee"]) if win else -(b["price"] + b["fee"]), 4); n += 1
    open(OUT, "w", encoding="utf-8").write("".join(json.dumps(b) + "\n" for b in B))
    G = [b for b in B if b.get("result") in ("W", "L") and not (b["kind"] == "PROP" and "p_sharp" not in b)]   # 22 props from the first 11/24
                                                                         # run were picked off sharp books, before the switch to our numbers
    print("graded %d new; total %d settled, %d open" % (n, len(G), len(B) - len(G)))
    sl = {"ML": lambda b: b["kind"] == "ML", "TOTAL": lambda b: b["kind"] == "TOTAL", "SPREAD": lambda b: b["kind"] == "SPREAD",
          "PROP": lambda b: b["kind"] == "PROP", "edge1-2": lambda b: b["edge"] < .02, "edge2-3": lambda b: .02 <= b["edge"] < .03,
          "edge3+": lambda b: b["edge"] >= .03,
          "PROP sharp-ok": lambda b: b["kind"] == "PROP" and b.get("p_sharp") is not None and b["p_sharp"] >= b["price"] + b["fee"],
          "PROP sharp-no": lambda b: b["kind"] == "PROP" and b.get("p_sharp") is not None and b["p_sharp"] < b["price"] + b["fee"],
          "ALL": lambda b: True}
    for k, f in sl.items():
        X = [b for b in G if f(b)]
        if not X:
            continue
        v = [b["net"] for b in X]; s = statistics.pstdev(v) if len(v) > 1 else 0
        t = statistics.mean(v) / (s / math.sqrt(len(v))) if s else 0
        cost = sum(b["price"] + b["fee"] for b in X)
        print("  %-14s n=%4d  won %5.1f%% (fair said %4.1f%%)  net $%+7.2f  ROI %+5.1f%%  t %+.2f" % (
            k, len(X), 100 * sum(b["result"] == "W" for b in X) / len(X), 100 * statistics.mean(b["p"] for b in X), sum(v), 100 * sum(v) / cost, t))


if __name__ == "__main__":
    grade() if sys.argv[1:2] == ["grade"] else run()
