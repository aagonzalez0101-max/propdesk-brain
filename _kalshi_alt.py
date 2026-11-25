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
# 11/25 user: "i want other sports in there ... we start kalshi next week monday" -- same engine, per-sport config.
# sd = spread of the full-game total / margin around Pinnacle's number (normal approx; NHL is discrete, so rougher).
SPORTS = {"NBA": dict(pin=487, game="KXNBAGAME", tot="KXNBATOTAL", spr="KXNBASPREAD", sd_tot=18.5, sd_mar=13.0),
          "NHL": dict(pin=1456, game="KXNHLGAME", tot="KXNHLTOTAL", spr="KXNHLSPREAD", sd_tot=2.2, sd_mar=2.4),
          "NFL": dict(pin=889, game="KXNFLGAME", tot="KXNFLTOTAL", spr="KXNFLSPREAD", sd_tot=13.5, sd_mar=13.5),
          "CBB": dict(pin=493, game="KXNCAAMBGAME", tot="KXNCAAMBTOTAL", spr="KXNCAAMBSPREAD", sd_tot=16.0, sd_mar=11.0)}
NHL_PROPS = {"KXNHLPTS": "nhl points", "KXNHLGOAL": "nhl goals", "KXNHLAST": "nhl assists"}
NHL_KEY = {"nhl points": "points", "nhl goals": "goals", "nhl assists": "assists"}
MAX_BETS = 100
TOP_N, TOP_COMBOS = 10, 5                                  # user: "the top 5-10 ranked legs like we do on pp, same with parlays"
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


def pin_games(league=487):
    H = {"X-API-Key": PIN_KEY}
    mus = get("%s/0.1/leagues/%d/matchups" % (PIN, league), H) or []
    mk = get("%s/0.1/leagues/%d/markets/straight" % (PIN, league), H) or []
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


def candidates(sport="NBA"):
    """-> rows (kind, market, desc, yes_fair, name, canon, start) for every priced Kalshi rung of one sport"""
    cf = SPORTS[sport]; sd_tot, sd_mar = cf["sd_tot"], cf["sd_mar"]
    out = []
    games = pin_games(cf["pin"])
    ml = kmarkets(cf["game"])
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
    for m in kmarkets(cf["tot"]):
        g = game_for(m["event_ticker"].split("-", 1)[1])
        if g and g.get("total") and m.get("floor_strike") is not None:
            T, po = g["total"]; mu = T + sd_tot * zinv(po)
            out.append(("TOTAL", m, "%s v %s over %s" % (g["away"], g["home"], m["floor_strike"]), 1 - Phi((m["floor_strike"] - mu) / sd_tot), None, None, g["start"]))
    for m in kmarkets(cf["spr"]):
        g = game_for(m["event_ticker"].split("-", 1)[1])
        if g and g.get("spread_home") and m.get("floor_strike") is not None:
            city = re.match(r"(.+?) wins by", m["title"]); city = city.group(1) if city else ""
            line, pc = g["spread_home"]
            mu_home = -line + sd_mar * zinv(pc)                 # expected home margin
            mu = mu_home if city_match(city, g["home"]) else -mu_home
            out.append(("SPREAD", m, m["title"], 1 - Phi((m["floor_strike"] - mu) / sd_mar), None, None, g["start"]))
    if sport == "NHL":                                         # NHL props: our own rates only (no sharp comparison wired)
        for ser, canon in NHL_PROPS.items():
            for m in kmarkets(ser):
                if m.get("strike_type") == "greater" and m.get("floor_strike") is not None:
                    g = game_for(m["event_ticker"].split("-", 1)[1]); name = m["title"].split(":")[0]
                    if g:
                        out.append(("PROP", m, "%s %s %s+" % (name, canon.split()[1], int(m["floor_strike"] + .5)), None, name, canon, g["start"]))
    if sport != "NBA":
        return out
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
    import _stack as S2                                       # NHL: player_games, keyed like _stack (first initial + last name)
    for p, st in c.execute("select player, stats from player_games where sport='NHL' and date>='2026-10-01' order by date"):
        j = json.loads(st)
        if j.get("gtype") == "reg":
            R.setdefault("nhl:" + S2.pkey("nhl", p), []).append({k: float(j.get(k) or 0) for k in ("points", "goals", "assists")})
    return R


def own_list(OWN, name, canon):
    """-> (values for this stat, minutes or None): NBA by full name, NHL by initial+last"""
    if canon in NHL_KEY:
        import _stack as S2
        return [x[NHL_KEY[canon]] for x in OWN.get("nhl:" + S2.pkey("nhl", name), [])], None
    g = OWN.get(name.lower(), [])
    return [sum(x[k] for k in BOX[canon].split("+")) for x in g], [x["mn"] for x in g]


def injuries():
    try:
        d = get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries")
        return {i["athlete"]["displayName"].lower(): (i.get("status") or "").lower() for t in d.get("injuries", []) for i in t.get("injuries", [])}
    except Exception:
        return {}


COMBO_MIN_P, COMBO_MAX_P, COMBO_PAY, COMBO_EDGE, COMBO_MAX = .65, .85, (1.8, 4.0), .02, 8   # user: "3-5 legs at 65-85% ... anything over 1.8x"


def build_combos(pool, done, now):
    """11/24 user: "I'd take like 70 and 80% ... until they are like 2x or close to it, even a 1.6x". Legs our number has at 70%+ and
    priced at or under it; 2-3 legs from DIFFERENT games; cost = product of (ask + fee) per leg (= buying leg 1 and rolling the $1 into
    leg 2), pays $1 -> payout 1/cost. Keep 1.55x-2.3x with (our combined chance - cost) >= 2 pts; each leg used once; best 8 a run."""
    import itertools
    pool = sorted(pool, key=lambda l: -(l["p"] - l["price"] - l["fee"]))[:24]
    cand = []
    for k in (3, 4, 5):
        for c in itertools.combinations(pool, k):
            if len({l["game"] for l in c}) < k:
                continue
            cost = math.prod(l["price"] + l["fee"] for l in c); p = math.prod(l["p"] for l in c)
            if COMBO_PAY[0] <= 1 / cost <= COMBO_PAY[1] and p - cost >= COMBO_EDGE:
                cand.append((p - cost, c, cost, p))
    out, used = [], set()
    for e, c, cost, p in sorted(cand, key=lambda x: -x[0]):
        key = "+".join(sorted("%s:%s" % (l["ticker"], l["side"]) for l in c))
        if any(l["ticker"] in used for l in c) or ("COMBO:" + key) in done:
            continue
        used |= {l["ticker"] for l in c}
        out.append(dict(ts=now.isoformat(timespec="seconds"), day=now.strftime("%Y-%m-%d"), kind="COMBO", ticker="COMBO:" + key,
                        desc=" + ".join(l["desc"] for l in c), side="all", price=round(cost, 4), fee=0, p=round(p, 3), edge=round(e, 3),
                        legs=[{k2: l[k2] for k2 in ("ticker", "side", "desc", "price", "fee", "p")} for l in c], result=None))
        if len(out) == COMBO_MAX:
            break
    return out


def run():
    now = datetime.datetime.now(CT)
    done = set()
    if os.path.exists(OUT):
        done = {(json.loads(l)["ticker"]) for l in open(OUT, encoding="utf-8") if l.strip()}
    C = []
    for sp in SPORTS:
        try:
            C += [(sp,) + tuple(c) for c in candidates(sp)]
        except Exception as e:
            print("  %s: %s" % (sp, str(e)[:80]))
    OWN = own_rates(); INJ = injuries()
    bets, seen, pool = [], 0, []
    for c in C:
        sport, c = c[0], c[1:]
        kind, m, desc, pf = c[:4]
        p_sharp = pf if kind == "PROP" else None
        if kind == "PROP":                                    # OUR fair: shrunk season hit rate at the rung (+ checks below)
            v, _ = own_list(OWN, c[4], c[5])
            if len(v) < 8:
                continue
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
            if e < 0:
                continue
            why = ""
            if kind == "PROP":
                name, canon = c[4], c[5]
                if INJ.get(name.lower()) in ("out", "doubtful", "questionable"):
                    continue
                v, mins = own_list(OWN, name, canon)
                l10 = [x > m["floor_strike"] for x in v[-10:]]
                l10s = sum(l10) / len(l10) if side == "yes" else 1 - sum(l10) / len(l10)
                if l10s < .5:                                     # last 10 must agree with the side
                    continue
                tr = (sum(mins[-3:]) / 3) / (sum(mins) / len(mins)) if mins else 1.0
                if side == "yes" and tr < .90:                    # YES needs his minutes holding
                    continue
                if side == "no" and tr >= 1.15:                   # 11/23 rule: no unders while minutes are rising
                    continue
                why = "season %d/%d, L10 %d/10, min %.0f%%%s" % (sum(x > m["floor_strike"] for x in v) if side == "yes" else sum(x <= m["floor_strike"] for x in v),
                      len(v), round(10 * l10s) if len(l10) == 10 else round(len(l10) * l10s), 100 * tr,
                      ", sharp %.0f%%" % (100 * (p_sharp if side == "yes" else 1 - p_sharp)) if p_sharp is not None else "")
            leg = dict(ts=now.isoformat(timespec="seconds"), day=now.strftime("%Y-%m-%d"), sport=sport, kind=kind, ticker=m["ticker"], desc=desc,
                       side=side, price=ask, fee=fee(ask), p=round(p, 3), edge=round(e, 3), close=m["close_time"], why=why, result=None,
                       p_sharp=(round(p_sharp if side == "yes" else 1 - p_sharp, 3) if p_sharp is not None else None),
                       game=m["event_ticker"].split("-", 1)[1][:13])
            if COMBO_MIN_P <= p <= COMBO_MAX_P and ask <= .92:
                pool.append(leg)                                  # 11/24 user: 70-80% legs stacked to ~1.6-2x
            if e >= (EDGE_PROP if kind == "PROP" else EDGE):
                bets.append(leg)
            break
    # 11/25: 4 sports -> 600+ rungs clear; a ladder of rungs on one player/game is one bet repeated. Keep the best rung per
    # player-stat (props) / per game and market (totals, spreads), then the top MAX_BETS by edge (user: "same number of bets").
    best = {}
    for b in bets:
        g = (b["sport"], b["kind"], b["game"], b["desc"].rsplit(" ", 1)[0] if b["kind"] == "PROP" else b["kind"])
        if g not in best or b["edge"] > best[g]["edge"]:
            best[g] = b
    props = sorted([b for b in best.values() if b["kind"] == "PROP"], key=lambda b: -b["edge"])
    gm = sorted([b for b in best.values() if b["kind"] != "PROP"], key=lambda b: -b["edge"])
    bets = props[:MAX_BETS - min(len(gm), MAX_BETS * 2 // 5)] + gm[:MAX_BETS * 2 // 5]   # 60 props + 40 game-market bets
    combos = build_combos(pool, done, now)
    for i, b in enumerate(sorted(bets, key=lambda b: -b["edge"])[:TOP_N], 1):
        b["rank"] = i                                            # the ranked shortlist, graded on its own (TOP10)
    for i, c in enumerate(combos[:TOP_COMBOS], 1):
        c["rank"] = i
    print("KALSHI ALT PAPER %s: %d rungs priced, %d bets (edge >= %.0f pts after fee), %d combos" % (now.strftime("%m-%d %H:%M"), seen, len(bets), 100 * EDGE, len(combos)))
    for c in combos:
        print("  COMBO %.2fx  cost %.0fc  ours %.0f%%  edge +%.1f  | %s" % (1 / c["price"], 100 * c["price"], 100 * c["p"], 100 * c["edge"],
              " + ".join("%s %s@%.0f" % (l["desc"][:30], l["side"].upper(), 100 * l["price"]) for l in c["legs"])))
    import collections
    print("  mix: " + ", ".join("%s %s %d" % (k[0], k[1], v) for k, v in sorted(collections.Counter((b["sport"], b["kind"]) for b in bets).items())))
    print("  TOP %d LEGS (ranked by edge):" % TOP_N)
    for b in sorted([b for b in bets if b.get("rank")], key=lambda b: b["rank"]):
        print("   #%-2d %s %-6s %-44s %s @ %.2f  ours %.0f%%  edge +%.1f" % (b["rank"], b["sport"], b["kind"], b["desc"][:44], b["side"].upper(), b["price"], 100 * b["p"], 100 * b["edge"]))
    for b in sorted(bets, key=lambda b: -b["edge"])[:40]:
        print("  %-6s %-46s %-3s @ %.2f (+%.2f fee)  fair %.0f%%  edge +%.1f  %s" % (b["kind"], b["desc"][:46], b["side"].upper(), b["price"], b["fee"], 100 * b["p"], 100 * b["edge"], b["why"]))
    if os.environ.get("DRYRUN"):
        print("(dry run: not logged)"); return
    with open(OUT, "a", encoding="utf-8") as f:
        f.write("".join(json.dumps(b) + "\n" for b in bets + combos))      # 11/25 fix: combos were printed but never saved


def grade():
    if not os.path.exists(OUT):
        print("nothing logged yet"); return
    B = [json.loads(l) for l in open(OUT, encoding="utf-8") if l.strip()]
    n = 0
    for b in B:
        if b.get("result") is None and b["kind"] == "COMBO":
            rs = []
            for l in b["legs"]:
                try:
                    rs.append(get("%s/markets/%s" % (KAL, l["ticker"])).get("market", {}).get("result"))
                except Exception:
                    rs.append(None)
            if all(r in ("yes", "no") for r in rs):
                win = all(r == l["side"] for r, l in zip(rs, b["legs"]))
                b["result"] = "W" if win else "L"; b["net"] = round((1 - b["price"]) if win else -b["price"], 4); n += 1
            continue
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
          "PROP": lambda b: b["kind"] == "PROP", "COMBO": lambda b: b["kind"] == "COMBO", "edge1-2": lambda b: b["edge"] < .02, "edge2-3": lambda b: .02 <= b["edge"] < .03,
          "edge3+": lambda b: b["edge"] >= .03 and b["kind"] != "COMBO",
          "TOP10 legs": lambda b: b["kind"] != "COMBO" and (b.get("rank") or 99) <= 10,
          "TOP5 combos": lambda b: b["kind"] == "COMBO" and (b.get("rank") or 99) <= 5,
          "NBA": lambda b: b.get("sport", "NBA") == "NBA" and b["kind"] != "COMBO", "NHL": lambda b: b.get("sport") == "NHL" and b["kind"] != "COMBO",
          "NFL": lambda b: b.get("sport") == "NFL" and b["kind"] != "COMBO", "CBB": lambda b: b.get("sport") == "CBB" and b["kind"] != "COMBO",
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
