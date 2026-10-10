"""LoL OPPONENT-vs-ROLE check (2026-10-04, user: "do we run the same precautions on esports -- opponent ranks, how they fare vs that position").

    python _lol_matchup.py TEAM ROLE      # kills the OPPONENT team allows per game to that role vs league average (from graded games)

Built from _lol_games_cache.json (every game _lol_grade.py has pulled: per-player kills + role). TOUGH (< 90% of league) supports
an under, SOFT (> 110%) is against it. Small samples (< 6 games) are reported, not trusted.
"""
import sys, json, collections, statistics as st


def table():
    c = json.load(open("_lol_games_cache.json"))
    allowed = collections.defaultdict(lambda: collections.defaultdict(list)); lg = collections.defaultdict(list)
    for g in c.values():
        teams = collections.defaultdict(dict)
        for nm, v in g.items():
            teams[nm.split(" ", 1)[0] if " " in nm else "?"][v["role"]] = v["kills"]
        if len(teams) != 2:
            continue
        a, b = list(teams)
        for t, o in ((a, b), (b, a)):
            for role, k in teams[o].items():
                allowed[t][role].append(k); lg[role].append(k)
    return allowed, {r: st.mean(v) for r, v in lg.items()}


def check(team, role):
    allowed, avg = table()
    v = allowed.get(team, {}).get(role, [])
    if not v:
        return None, "no games for %s" % team
    m = st.mean(v); r = m / avg[role]
    tag = "TOUGH (supports UNDER)" if r < 0.9 else ("SOFT (against UNDER)" if r > 1.1 else "average")
    return r, "%s allows %.2f/game to %s over %d games (league %.2f) -> %s%s" % (team, m, role, len(v), avg[role], tag, "  [small sample]" if len(v) < 6 else "")


if __name__ == "__main__":
    print(check(sys.argv[1].upper(), sys.argv[2].lower())[1])
