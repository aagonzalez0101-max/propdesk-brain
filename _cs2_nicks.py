"""Backfill steam_profile_id -> nickname (+ bo3 team) for players in cs2_maps*.jsonl -> cs2_nicks.json.
Re-run any time; only fetches games that contain unknown players (newest first)."""
import json, os, time, urllib.request, collections
UA = {"User-Agent": "Mozilla/5.0 Chrome/124", "Accept": "application/json"}
g = lambda u: json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40).read())
N = json.load(open("cs2_nicks.json")) if os.path.exists("cs2_nicks.json") else {}
games = collections.defaultdict(set); date = {}
for fn in ("cs2_maps.jsonl", "cs2_maps_old.jsonl"):
    if os.path.exists(fn):
        for l in open(fn, encoding="utf-8"):
            r = json.loads(l); games[r["game_id"]].add(str(r["player"])); date[r["game_id"]] = r["date"]
calls = 0
for gid in sorted(games, key=lambda x: date[x], reverse=True):
    if all(p in N for p in games[gid]):
        continue
    try:
        st = g("https://api.bo3.gg/api/v1/games/%d/players_stats" % gid); calls += 1
    except Exception as e:
        print(gid, e); time.sleep(3); continue
    for p in st:
        sp = p.get("steam_profile") or {}
        tm = ((p.get("team_clan") or {}).get("team") or {})
        N[str(p["steam_profile_id"])] = dict(nick=(sp.get("player") or {}).get("nickname") or sp.get("nickname"),
                                             team=tm.get("name"), clan=p.get("clan_name"), last=date[gid])
    time.sleep(0.12)
    if calls % 50 == 0:
        json.dump(N, open("cs2_nicks.json", "w")); print(calls, "calls", len(N), "players", flush=True)
json.dump(N, open("cs2_nicks.json", "w")); print("done", calls, "calls", len(N), "players")
