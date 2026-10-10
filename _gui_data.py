"""Trim the CS2 and Valorant profiles down to what the browser page needs -> gui_data.json

    python _gui_data.py

CS2 comes straight from cs2_maps.jsonl (player ids -> nicknames via cs2_nicks.json), Valorant
from val_profiles.json. Same shape for both so the page has one renderer: kills per round,
headshots per kill, the win/loss split, per-map rates, the agent pool (Valorant only) and the
last ten maps. Rates are shrunk toward the league so a three-map player does not read as elite.
"""
import json, collections, itertools

K_PLAYER = 400.0
K_MAP = 120.0
MIN_MAPS = 5


def cs2():
    nicks = json.load(open("cs2_nicks.json", encoding="utf-8"))
    nick = lambda pid: (nicks.get(str(pid)) or {}).get("nick")
    rows = []
    for l in open("cs2_maps.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if r.get("kills") is not None and (r.get("rounds") or 0) >= 13:
            rows.append(r)
    rows.sort(key=lambda r: (r["date"], r["game_id"]))
    lg = sum(r["kills"] for r in rows) / sum(r["rounds"] for r in rows)
    by = collections.defaultdict(list)
    for r in rows:
        by[r["player"]].append(r)
    out = {}
    for pid, rs in by.items():
        if len(rs) < MIN_MAPS or not nick(pid):
            continue
        k = sum(x["kills"] for x in rs); rd = sum(x["rounds"] for x in rs)
        hs = sum(x["hs"] or 0 for x in rs)
        wins = [x for x in rs if x["win"]]; loss = [x for x in rs if not x["win"]]
        rate = lambda g: round(sum(x["kills"] for x in g) / max(1, sum(x["rounds"] for x in g)), 3) if g else None
        maps_ = {}
        for m, g in itertools.groupby(sorted(rs, key=lambda x: x["map"]), key=lambda x: x["map"]):
            g = list(g)
            gk = sum(x["kills"] for x in g); gr = sum(x["rounds"] for x in g)
            maps_[m.replace("de_", "")] = dict(n=len(g), kpr=round((gk + K_MAP * (k / rd)) / (gr + K_MAP), 3))
        out[str(pid)] = dict(
            game="cs2", name=nick(pid), team=rs[-1]["team"], last=rs[-1]["date"], maps=len(rs), rounds=rd,
            kpr=round((k + K_PLAYER * lg) / (rd + K_PLAYER), 3), raw=round(k / rd, 3),
            hspk=round(hs / max(1, k), 3), kpr_w=rate(wins), kpr_l=rate(loss),
            byMap=dict(sorted(maps_.items(), key=lambda x: -x[1]["n"])[:8]),
            recent=[dict(d=x["date"], m=x["map"].replace("de_", ""), k=x["kills"], hs=x["hs"],
                         r=x["rounds"], w=x["win"], o=x["opp"][:22]) for x in rs[-10:]])
    return out, round(lg, 3)


def valorant():
    d = json.load(open("val_profiles.json", encoding="utf-8"))
    out = {}
    for pid, p in d["players"].items():
        if p["maps"] < MIN_MAPS:
            continue
        out["v" + pid] = dict(
            game="val", name=p["name"], team=p["team"], last=p["last_seen"], maps=p["maps"],
            rounds=p["rounds"], kpr=p["kpr"], raw=p["raw_kpr"], kpr_w=p["kpr_win"], kpr_l=p["kpr_loss"],
            role=p["role"], flex=p["flex"],
            agents={a: dict(n=v["maps"], share=v["share"], kpr=v["kpr"])
                    for a, v in sorted(p["by_agent"].items(), key=lambda x: -x[1]["maps"])[:6]},
            byMap={m: dict(n=v["maps"], kpr=v["kpr"], agent=v["agent"])
                   for m, v in sorted(p["by_map"].items(), key=lambda x: -x[1]["maps"])[:8]},
            recent=[dict(d=x["date"], m=x["map"], a=x["agent"], k=x["kills"], r=x["rounds"],
                         w=x["win"], o=x["opp"][:22]) for x in p["recent"]])
    return out, d["meta"]["league_kpr"], d["meta"]["rounds_mean"]


if __name__ == "__main__":
    c, c_lg = cs2()
    v, v_lg, v_rounds = valorant()
    players = {}
    players.update(c); players.update(v)
    teams = collections.defaultdict(list)
    for pid, p in players.items():
        teams[p["game"] + "|" + (p["team"] or "?")].append(pid)
    data = dict(players=players,
                teams={t: sorted(ids, key=lambda i: -players[i]["maps"])[:10] for t, ids in teams.items()},
                meta=dict(cs2_players=len(c), val_players=len(v), cs2_kpr=c_lg, val_kpr=v_lg,
                          val_rounds=v_rounds, cs2_rounds=24.4))
    json.dump(data, open("gui_data.json", "w", encoding="utf-8"), separators=(",", ":"))
    print("gui_data.json: %d CS2 players, %d Valorant players, %d teams"
          % (len(c), len(v), len(data["teams"])))
