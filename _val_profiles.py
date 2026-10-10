"""Valorant PLAYER PROFILES -- the file the kill model prices off. Rebuilt from val_maps.jsonl.

    python _val_profiles.py build            # rebuild val_profiles.json from every map we have
    python _val_profiles.py show <player>    # print one player's profile
    python _val_profiles.py team <team>      # the current five for a team
    python _val_profiles.py stale            # players whose profile is thin (few maps)

One profile per player, keyed by vlr player id:

  kpr            kills per round, shrunk toward the league rate (400 pseudo-rounds)
  by_agent       same, per agent -- this is the whole point, a Jett game is not a Killjoy game
  by_map         kills per round on each map, and which agent he plays there
  win / loss     kills per round when his team wins the map vs loses it
  role, flex     main role and whether it changes by map (under 70% = flex, price per map)
  recent         last 10 maps, newest last
  team           the team he last played for, and how many maps ago that was

Shrinkage: every rate is pulled toward the level above it -- an agent rate toward the player's
own overall rate, a player's rate toward the league rate -- by a fixed number of pseudo-rounds.
A two-map sample on a new agent therefore reads close to his normal number, not as a real rate.
Same idea as the CS2 model's K_ROUNDS, which is what stopped small samples posting fake edges.
"""
import json, sys, os, collections, itertools, datetime

F = "val_maps.jsonl"
OUT = "val_profiles.json"
K_PLAYER = 400.0    # pseudo-rounds pulling a player toward the league
K_AGENT = 150.0     # pseudo-rounds pulling an agent rate toward the player's own rate
K_MAP = 120.0
MIN_ROUNDS = 13     # ignore half-finished maps


def load():
    rows = []
    for l in open(F, encoding="utf-8"):
        r = json.loads(l)
        if r.get("pid") and r.get("kills") is not None and (r.get("rounds") or 0) >= MIN_ROUNDS:
            rows.append(r)
    rows.sort(key=lambda r: (r["date"], r["match"], r["game_id"]))
    return rows


def build():
    rows = load()
    lg_k = sum(r["kills"] for r in rows)
    lg_r = sum(r["rounds"] for r in rows)
    lg = lg_k / lg_r
    # league rate per agent, so a new Chamber player is shrunk toward CHAMBER, not toward all agents
    ak = collections.Counter(); ar = collections.Counter()
    for r in rows:
        ak[r["agent"]] += r["kills"]; ar[r["agent"]] += r["rounds"]
    lg_agent = {a: (ak[a] + 400 * lg) / (ar[a] + 400) for a in ak}

    by_pid = collections.defaultdict(list)
    for r in rows:
        by_pid[r["pid"]].append(r)

    prof = {}
    today = datetime.date.today()
    for pid, rs in by_pid.items():
        k = sum(x["kills"] for x in rs); rd = sum(x["rounds"] for x in rs)
        kpr = (k + K_PLAYER * lg) / (rd + K_PLAYER)
        agents = {}
        for a, g in itertools.groupby(sorted(rs, key=lambda x: x["agent"]), key=lambda x: x["agent"]):
            g = list(g)
            gk = sum(x["kills"] for x in g); gr = sum(x["rounds"] for x in g)
            # shrink toward this player's own rate, adjusted for how the agent plays league-wide
            anchor = kpr * (lg_agent.get(a, lg) / lg)
            agents[a] = dict(maps=len(g), rounds=gr, kpr=round((gk + K_AGENT * anchor) / (gr + K_AGENT), 4),
                             raw=round(gk / gr, 4), share=round(len(g) / len(rs), 3))
        maps_ = {}
        for m, g in itertools.groupby(sorted(rs, key=lambda x: x["map"]), key=lambda x: x["map"]):
            g = list(g)
            gk = sum(x["kills"] for x in g); gr = sum(x["rounds"] for x in g)
            pick = collections.Counter(x["agent"] for x in g).most_common(1)[0]
            maps_[m] = dict(maps=len(g), kpr=round((gk + K_MAP * kpr) / (gr + K_MAP), 4),
                            agent=pick[0], agent_share=round(pick[1] / len(g), 2))
        wins = [x for x in rs if x["win"]]; losses = [x for x in rs if not x["win"]]
        wr = lambda g: round(sum(x["kills"] for x in g) / max(1, sum(x["rounds"] for x in g)), 4) if g else None
        roles = collections.Counter(x["role"] for x in rs)
        top_role, top_n = roles.most_common(1)[0]
        last = rs[-1]
        prof[str(pid)] = dict(
            name=last["name"], team=last["team"], tag=last.get("tag"), last_seen=last["date"],
            maps=len(rs), rounds=rd, kpr=round(kpr, 4), raw_kpr=round(k / rd, 4),
            kpr_win=wr(wins), kpr_loss=wr(losses), win_maps=len(wins),
            role=top_role, role_share=round(top_n / len(rs), 3), flex=top_n / len(rs) < 0.70,
            by_agent=agents, by_map=maps_,
            recent=[dict(date=x["date"], map=x["map"], agent=x["agent"], kills=x["kills"],
                         rounds=x["rounds"], win=x["win"], opp=x["opp"]) for x in rs[-10:]])
    meta = dict(built=today.isoformat(), maps=len({r["game_id"] for r in rows}), players=len(prof),
                league_kpr=round(lg, 4), league_by_agent={a: round(v, 4) for a, v in sorted(lg_agent.items())},
                rounds_mean=round(sum(r["rounds"] for r in rows) / len(rows), 2))
    json.dump(dict(meta=meta, players=prof), open(OUT, "w", encoding="utf-8"))
    print("built %s: %d players, %d maps, league %.3f kills per round"
          % (OUT, len(prof), meta["maps"], lg))
    thin = sum(1 for p in prof.values() if p["maps"] < 10)
    print("  %d players have fewer than 10 maps -- they price off the league rate, not their own"
          % thin)


def db():
    if not os.path.exists(OUT):
        sys.exit("no %s yet -- run: python _val_profiles.py build" % OUT)
    return json.load(open(OUT, encoding="utf-8"))


def find(name):
    d = db()
    hits = [(pid, p) for pid, p in d["players"].items() if p["name"].lower() == name.lower()]
    if not hits:
        hits = [(pid, p) for pid, p in d["players"].items() if name.lower() in p["name"].lower()]
    return sorted(hits, key=lambda x: -x[1]["maps"])


def show(name):
    hits = find(name)
    if not hits:
        print("no player called '%s' in the profiles" % name); return
    for pid, p in hits[:2]:
        print("\n" + "=" * 72)
        print("%s  (%s)   %d maps, %d rounds, last played %s"
              % (p["name"], p["team"], p["maps"], p["rounds"], p["last_seen"]))
        print("  kills per round: %.3f   when his team wins the map: %.3f   when it loses: %.3f"
              % (p["kpr"], p["kpr_win"] or 0, p["kpr_loss"] or 0))
        print("  role: %s (%d%% of maps)%s" % (p["role"], round(100 * p["role_share"]),
                                               "   FLEX -- price him per map" if p["flex"] else ""))
        print("\n  agent           maps  share   kills/round")
        for a, v in sorted(p["by_agent"].items(), key=lambda x: -x[1]["maps"])[:8]:
            print("    %-12s %4d   %3d%%   %.3f" % (a, v["maps"], round(100 * v["share"]), v["kpr"]))
        print("\n  map          usual agent   maps   kills/round")
        for m, v in sorted(p["by_map"].items(), key=lambda x: -x[1]["maps"])[:8]:
            print("    %-10s %-12s %4d   %.3f" % (m, v["agent"], v["maps"], v["kpr"]))
        print("\n  last 10 maps:")
        for x in p["recent"]:
            print("    %s %-9s %-10s %2d kills in %2d rounds   %s vs %s"
                  % (x["date"], x["map"], x["agent"], x["kills"], x["rounds"],
                     "W" if x["win"] else "L", x["opp"][:22]))


def team(name):
    d = db()
    ps = [p for p in d["players"].values() if name.lower() in (p["team"] or "").lower()]
    ps.sort(key=lambda p: (p["last_seen"], p["maps"]), reverse=True)
    print("%s -- most recent players" % name)
    print("  %-14s %-10s %5s %7s %6s  %s" % ("player", "role", "maps", "k/round", "flex", "main agents"))
    for p in ps[:8]:
        ags = ", ".join("%s %d%%" % (a, round(100 * v["share"]))
                        for a, v in sorted(p["by_agent"].items(), key=lambda x: -x[1]["maps"])[:3])
        print("  %-14s %-10s %5d %7.3f %6s  %s"
              % (p["name"], p["role"], p["maps"], p["kpr"], "yes" if p["flex"] else "", ags))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd == "build":
        build()
    elif cmd == "show":
        show(" ".join(sys.argv[2:]))
    elif cmd == "team":
        team(" ".join(sys.argv[2:]))
    else:
        print(__doc__)
