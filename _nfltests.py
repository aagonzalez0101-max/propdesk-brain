"""NFL rule suite -- every rule we bet, re-tested on the FULL history in one run.

    python _nfltests.py            # all games with lines (1999-2026)
    python _nfltests.py 2015       # only seasons >= 2015

Data: nflverse nfldata/games.csv (spread_line, total_line, wind, temp, roof,
div_game, result). Prints record, hit rate and ROI at -110 for each rule so a
decaying rule is visible before it costs money.
"""
import csv, io, sys, urllib.request, math, collections

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"


def load(min_season=1999):
    raw = urllib.request.urlopen(urllib.request.Request(
        URL, headers={"User-Agent": "M/5"}), timeout=180).read().decode()
    out = []
    for r in csv.DictReader(io.StringIO(raw)):
        if r["game_type"] != "REG" or not r["home_score"]:
            continue
        try:
            s = int(r["season"])
        except ValueError:
            continue
        if s < min_season:
            continue
        def f(k):
            v = r.get(k)
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        out.append(dict(season=s, week=r.get("week"), home=r["home_team"], away=r["away_team"],
                        hs=int(r["home_score"]), as_=int(r["away_score"]),
                        spread=f("spread_line"), total=f("total_line"),
                        wind=f("wind"), temp=f("temp"), roof=(r.get("roof") or ""),
                        div=(r.get("div_game") or "0") == "1"))
    return out


def rep(label, wins, n, price=-110):
    if n < 25:
        print(f"  {label:46s} n={n:5d}  (too few)")
        return
    p = wins / n
    ret = 100 / -price if price < 0 else price / 100
    roi = (wins * ret - (n - wins)) / n
    se = math.sqrt(p * (1 - p) / n)
    z = (p - 1 / (1 + ret)) / se
    print(f"  {label:46s} n={n:5d}  {p:6.1%}  ROI {roi:+6.1%}  z={z:+5.2f}")


def totals(G):
    print("\nTOTALS -- unders")
    out = [g for g in G if g["total"] and "closed" not in g["roof"] and g["roof"] != "dome"]
    def under(sub):
        s = [g for g in sub if g["hs"] + g["as_"] != g["total"]]
        return sum(1 for g in s if g["hs"] + g["as_"] < g["total"]), len(s)
    w, n = under(out)
    rep("all outdoor games: UNDER", w, n)
    for lo in (8, 10, 12, 15, 20):
        sub = [g for g in out if g["wind"] is not None and g["wind"] >= lo]
        w, n = under(sub)
        rep(f"wind >= {lo} mph: UNDER", w, n)
    cold = [g for g in out if g["temp"] is not None and g["temp"] <= 35]
    w, n = under(cold)
    rep("temp <= 35F: UNDER", w, n)
    windcold = [g for g in out if g["wind"] and g["wind"] >= 12 and g["temp"] is not None and g["temp"] <= 45]
    w, n = under(windcold)
    rep("wind >= 12 AND temp <= 45: UNDER", w, n)
    dom = [g for g in G if g["total"] and ("closed" in g["roof"] or g["roof"] == "dome")]
    s = [g for g in dom if g["hs"] + g["as_"] != g["total"]]
    rep("DOME games: UNDER (control)", sum(1 for g in s if g["hs"] + g["as_"] < g["total"]), len(s))
    d = [g for g in G if g["total"] and g["div"]]
    s = [g for g in d if g["hs"] + g["as_"] != g["total"]]
    rep("divisional games: UNDER", sum(1 for g in s if g["hs"] + g["as_"] < g["total"]), len(s))


def teasers(G, teas=6):
    print("\nTEASERS -- 6-point legs (2-team at -110 needs 72.4% per leg)")
    def legs(lo, hi, fav):
        w = n = 0
        for g in G:
            if g["spread"] is None:
                continue
            marg = g["hs"] - g["as_"]
            for line, m in ((g["spread"], marg), (-g["spread"], -marg)):
                if fav and lo <= line <= hi:
                    n += 1
                    w += (m + teas - line) > 0
                if not fav and lo <= -line <= hi:
                    n += 1
                    w += (m + (-line) + teas) > 0
        return w, n
    for lab, lo, hi, fav in (("favourite -7.5..-8.5 -> -1.5..-2.5", 7.5, 8.5, True),
                             ("favourite -7..-9", 7.0, 9.0, True),
                             ("underdog +1.5..+2.5 -> +7.5..+8.5", 1.5, 2.5, False),
                             ("underdog +1..+3", 1.0, 3.0, False),
                             ("underdog +2.5..+3 (crosses 3 only)", 2.5, 3.0, False)):
        w, n = legs(lo, hi, fav)
        rep(lab, w, n, price=-110)


def sides(G):
    print("\nSIDES -- common claims")
    def cover(sub, home):
        w = n = 0
        for g in sub:
            if g["spread"] is None:
                continue
            # nfldata: spread_line POSITIVE = home favoured by that many.
            # home covers when margin > spread_line (verified vs the 47.6% base rate)
            marg = (g["hs"] - g["as_"]) if home else (g["as_"] - g["hs"])
            line = g["spread"] if home else -g["spread"]
            if marg - line == 0:
                continue
            n += 1
            w += (marg - line) > 0
        return w, n
    w, n = cover(G, True)
    rep("home teams ATS", w, n)
    dogs = [g for g in G if g["spread"] is not None and g["spread"] < 0]   # home is the dog
    w, n = cover(dogs, True)
    rep("home UNDERDOGS ATS", w, n)
    big = [g for g in G if g["spread"] is not None and abs(g["spread"]) >= 10]
    w, n = cover(big, True)
    rep("home side in blowout spreads (>=10)", w, n)
    d = [g for g in G if g["div"]]
    w, n = cover(d, True)
    rep("home side, divisional games", w, n)


def keynums(G):
    print("\nKEY NUMBERS -- margin distribution, by era")
    eras = [(1999, 2011), (2012, 2019), (2020, 2030)]
    dist = {e: collections.Counter() for e in eras}
    tot = {e: 0 for e in eras}
    for g in G:
        e = next((x for x in eras if x[0] <= g["season"] <= x[1]), None)
        if not e:
            continue
        dist[e][abs(g["hs"] - g["as_"])] += 1
        tot[e] += 1
    print(f"  {'margin':>6} " + " ".join(f"{a}-{b}".rjust(11) for a, b in eras))
    for m in (1, 2, 3, 4, 5, 6, 7, 10, 14):
        print(f"  {m:6d} " + " ".join(f"{100*dist[e][m]/tot[e]:10.1f}%" for e in eras))


if __name__ == "__main__":
    ms = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 1999
    G = load(ms)
    print(f"NFL RULE SUITE -- {len(G)} regular-season games, {ms}+")
    print(f"  with spreads: {sum(1 for g in G if g['spread'] is not None)}"
          f" | with totals: {sum(1 for g in G if g['total'] is not None)}"
          f" | with wind: {sum(1 for g in G if g['wind'] is not None)}")
    totals(G)
    teasers(G)
    sides(G)
    keynums(G)
