"""MATCHUP CARD -- both teams' offense AND defense, ranked within their league (2026-09-30, user: "each other's
tendencies, offense and defense, rankings -- that needs to be part of everything we check in every sport").

    python _matchup.py soccer "St. Louis" "New York"      # last 10 matches, ranks among the league's teams
    python _matchup.py nhl TOR NYI                          # season rates + ranks (NHL stats API)

Soccer uses the FotMob match cache (_fotmob/, filled by _soccer_hist.py) -- current season of the league the two
teams play in. Rank 1 = most of that stat.
"""
import sys, os, json, collections
import _soccer as S

STATS = [("poss", "possession %"), ("passes", "accurate passes"), ("shots", "shots"), ("sot", "shots on target"),
         ("xg", "xG"), ("goals", "goals")]


def soccer_table(league, season):
    idx = json.load(open("_soccer_hist_index.json"))
    games = collections.defaultdict(list)        # team id -> [(date, for{}, against{})]
    names = {}
    for mid, lg, s, date, hid, aid in idx:
        if lg != league or s != season:
            continue
        f = os.path.join(S.CACHE, "m%s.json" % mid)
        if not os.path.exists(f):
            continue
        m = json.load(open(f, encoding="utf-8"))
        ts = m.get("teamStats") or {}
        t = m.get("teams") or []
        if len(t) != 2 or not ts:
            continue
        for i in (0, 1):
            names[t[i]["id"]] = t[i]["name"]
            games[t[i]["id"]].append((date, {k: v[i] for k, v in ts.items()}, {k: v[1 - i] for k, v in ts.items()}))
    table = {}
    for tid, g in games.items():
        g = sorted(g)[-10:]
        row = {}
        for side, j in (("for", 1), ("against", 2)):
            for k, _ in STATS:
                v = [x[j].get(k) for x in g if x[j].get(k) is not None]
                row[(side, k)] = sum(v) / len(v) if v else None
        table[tid] = row
    return table, names


def rank(table, key, tid, high_is_1=True):
    vals = sorted([r[key] for r in table.values() if r.get(key) is not None], reverse=high_is_1)
    v = table[tid].get(key)
    return (vals.index(v) + 1 if v in vals else None), len(vals), v


def find(names, q):
    q = S.norm(q)
    hits = [tid for tid, n in names.items() if q in S.norm(n) or S.norm(n) in q]
    return hits[0] if hits else None


def soccer(a, b, league="MLS", season="2026"):
    table, names = soccer_table(league, season)
    ta, tb = find(names, a), find(names, b)
    if not ta or not tb:
        print("team not found in %s %s cache: %s / %s" % (league, season, a, b)); return
    print("\nMATCHUP  %s  vs  %s   (%s %s, last 10 matches, rank of %d teams)" % (names[ta], names[tb], league, season, len(table)))
    print("%-18s | %-24s | %-24s" % ("", names[ta][:24], names[tb][:24]))
    for k, lbl in STATS:
        for side, word in (("for", "makes"), ("against", "allows")):
            ra = rank(table, (side, k), ta); rb = rank(table, (side, k), tb)
            print("%-18s | %6.1f  (#%2d)            | %6.1f  (#%2d)" % ("%s %s" % (lbl[:12], word), ra[2] or 0, ra[0] or 0, rb[2] or 0, rb[0] or 0))
    print("  read: '#1 makes' = most in the league; '#1 allows' = gives up the most (weakest defence at it)")


def nhl(a, b):
    import _props as P
    teams = {t["id"]: t["triCode"] for t in P.get("https://api.nhle.com/stats/rest/en/team")["data"]}
    rows = {}
    for sid in ("20252026", "20262027"):
        d = P.get("https://api.nhle.com/stats/rest/en/team/summary?cayenneExp=seasonId=%s%%20and%%20gameTypeId=2" % sid)["data"]
        for r in d:
            if sid == "20252026" or (r.get("gamesPlayed") or 0) >= 10:
                rows[teams.get(r["teamId"])] = r
    keys = [("shotsForPerGame", "shots for/gm", True), ("shotsAgainstPerGame", "shots against/gm", True),
            ("goalsForPerGame", "goals for/gm", True), ("goalsAgainstPerGame", "goals against/gm", True),
            ("powerPlayPct", "power play %", True), ("penaltyKillPct", "penalty kill %", True)]
    print("\nMATCHUP  %s vs %s  (NHL, rank of %d; #1 = most)" % (a, b, len(rows)))
    for k, lbl, hi in keys:
        vals = sorted([r[k] for r in rows.values()], reverse=hi)
        f = lambda t: "%6.2f (#%2d)" % (rows[t][k] * (100 if "Pct" in k else 1), vals.index(rows[t][k]) + 1)
        print("  %-18s %-4s %s   %-4s %s" % (lbl, a, f(a), b, f(b)))


if __name__ == "__main__":
    sp = sys.argv[1]
    if sp == "soccer":
        soccer(sys.argv[2], sys.argv[3], *(sys.argv[4:6]))
    elif sp == "nhl":
        nhl(sys.argv[2], sys.argv[3])
