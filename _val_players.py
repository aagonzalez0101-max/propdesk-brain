"""Valorant player tracker: who plays what, on which map, and how many kills it produces.

    python _val_players.py <player> [<player> ...]     # profile one or more players
    python _val_players.py --team <team name>          # every player on a team
    python _val_players.py --flex                      # players whose role changes by map (the risky props)

Built on val_maps.jsonl (from _val_pull.py). For each player:
  - agent pool: maps played on each agent, share, kills per round on it
  - map -> agent: what he plays on each map (the pick is usually fixed per map)
  - role share and a FLEX flag when his most-played role is under 70% of his maps
  - last 10 maps: agent, map, kills, rounds, result
Kills per round are shown raw and shrunk toward the league rate for that agent (40 pseudo-rounds),
so a 2-map sample on a new agent does not read as a real rate.
"""
import sys, json, collections, re

F = "val_maps.jsonl"
SHRINK = 40.0


def load():
    rows = [json.loads(l) for l in open(F, encoding="utf-8")]
    rows = [r for r in rows if r["rounds"] >= 13 and r["kills"] is not None]
    rows.sort(key=lambda r: (r["date"], r["match"], r["game_id"]))
    return rows


def league_agent_kpr(rows):
    k = collections.Counter(); n = collections.Counter()
    for r in rows:
        k[r["agent"]] += r["kills"]; n[r["agent"]] += r["rounds"]
    lg = sum(k.values()) / max(1, sum(n.values()))
    return {a: (k[a] + 200 * lg) / (n[a] + 200) for a in k}, lg


def profile(rows, name, LA, lg, quiet=False):
    me = [r for r in rows if r["name"].lower() == name.lower()]
    if not me:
        cand = sorted({r["name"] for r in rows if name.lower() in r["name"].lower()})
        print("no player '%s'%s" % (name, (" -- did you mean: " + ", ".join(cand[:8])) if cand else ""))
        return None
    team = me[-1]["team"]
    print("\n" + "=" * 70)
    print("%s  (%s)  %d maps, last %s" % (me[-1]["name"], team, len(me), me[-1]["date"]))
    ag = collections.defaultdict(lambda: [0, 0, 0])
    roles = collections.Counter()
    for r in me:
        a = ag[r["agent"]]; a[0] += 1; a[1] += r["kills"]; a[2] += r["rounds"]
        roles[r["role"]] += 1
    print("  agent pool:")
    for a, (n, k, rd) in sorted(ag.items(), key=lambda x: -x[1][0]):
        shr = (k + SHRINK * LA.get(a, lg)) / (rd + SHRINK)
        print("    %-10s %3d maps (%3.0f%%)  KPR %.3f raw, %.3f shrunk  | %.1f kills/map" % (
            a, n, 100 * n / len(me), k / max(1, rd), shr, k / n))
    top_role, top_n = roles.most_common(1)[0]
    flex = top_n / len(me) < 0.70
    print("  roles: " + ", ".join("%s %d%%" % (ro, round(100 * c / len(me))) for ro, c in roles.most_common())
          + ("   <-- FLEX: role changes by map, price per map" if flex else ""))
    mp = collections.defaultdict(collections.Counter)
    for r in me:
        mp[r["map"]][r["agent"]] += 1
    print("  map -> agent:  " + " | ".join("%s: %s" % (m, "/".join("%s%s" % (a, "" if c == 1 else "x%d" % c)
                                                                    for a, c in cnt.most_common(2)))
                                            for m, cnt in sorted(mp.items(), key=lambda x: -sum(x[1].values()))))
    print("  last 10 maps:")
    for r in me[-10:]:
        print("    %s %-9s %-9s %2d K in %2d rds (%.2f)  %s vs %s" % (
            r["date"], r["map"], r["agent"], r["kills"], r["rounds"], r["kills"] / r["rounds"],
            "W" if r["win"] else "L", r["opp"][:22]))
    return dict(flex=flex, team=team)


def main():
    rows = load()
    LA, lg = league_agent_kpr(rows)
    a = sys.argv[1:]
    if not a:
        print(__doc__); return
    if a[0] == "--team":
        t = " ".join(a[1:]).lower()
        names = []
        for r in reversed(rows):
            if t in r["team"].lower() and r["name"] not in names:
                names.append(r["name"])
            if len(names) >= 5:
                break
        for n in names:
            profile(rows, n, LA, lg)
    elif a[0] == "--flex":
        by = collections.defaultdict(list)
        for r in rows:
            by[r["name"]].append(r)
        out = []
        for n, rs in by.items():
            if len(rs) < 8:
                continue
            c = collections.Counter(r["role"] for r in rs)
            ro, k = c.most_common(1)[0]
            if k / len(rs) < 0.70:
                out.append((k / len(rs), n, rs[-1]["team"], dict(c)))
        out.sort()
        print("FLEX players (main role < 70% of maps) -- their kill lines swing with the map/agent:")
        for share, n, t, c in out[:40]:
            print("  %-14s %-24s main role %3.0f%%  %s" % (n, t[:24], 100 * share, c))
    else:
        for n in a:
            profile(rows, n, LA, lg)


if __name__ == "__main__":
    main()
