"""CS2 per-map player stats from bo3.gg (free, no key) -> cs2_maps.jsonl

    python _cs2_pull.py 60 [start] # 60 pages x 50 tier S/A/B matches, newest first, from page start
    python _cs2_pull.py snap      # save today's Underdog esports lines -> esports_lines/<date>.json

One row per player per map: match, map, rounds, team, opponent, kills, deaths,
assists, headshots, first_kills, adr, win. Resumable: skips game ids already saved.
The snapshot mode exists because old prop lines cannot be recovered later.
"""
import json, os, sys, time, datetime, urllib.request

UA = {"User-Agent": "Mozilla/5.0 Chrome/124", "Accept": "application/json"}
OUT = os.environ.get("CS2_OUT", "cs2_maps.jsonl")   # second puller writes its own file
g = lambda u: json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40).read())


def pull(pages, start=0):
    done = set()
    if os.path.exists(OUT):
        for l in open(OUT, encoding="utf-8"):
            done.add(json.loads(l)["game_id"])
    f = open(OUT, "a", encoding="utf-8")
    n = 0
    for pg in range(start, start + pages):
        try:
            d = g("https://api.bo3.gg/api/v1/matches?page[offset]=%d&page[limit]=50&sort=-start_date"
                  "&filter[matches.status][in]=finished&filter[matches.discipline_id][eq]=1"
                  "&filter[matches.tier][in]=s,a,b&with=games" % (pg * 50))
        except Exception as e:
            print("page", pg, e)
            time.sleep(5)
            continue
        for m in d["results"]:
            for gm in m.get("games") or []:
                if gm["id"] in done or gm.get("status") != "finished":
                    continue
                try:
                    st = g("https://api.bo3.gg/api/v1/games/%d/players_stats" % gm["id"])
                except Exception:
                    continue
                if len(st) != 10:
                    continue
                for p in st:
                    f.write(json.dumps(dict(
                        game_id=gm["id"], match=m["slug"], date=m["start_date"][:10], tier=m["tier"],
                        bo=m["bo_type"], map_no=gm["number"], map=gm["map_name"], rounds=gm.get("rounds_count"),
                        player=p["steam_profile_id"], team=p["clan_name"], opp=p.get("enemy_clan_name"),
                        win=p.get("win"), kills=p["kills"], deaths=p["death"], assists=p["assists"],
                        hs=p["headshots"], fk=p["first_kills"], adr=p["adr"])) + "\n")
                done.add(gm["id"])
                n += 1
                time.sleep(0.15)
        f.flush()
        print("page %d: %d maps saved this run" % (pg, n), flush=True)
    print("done:", n, "new maps")


def snap():
    d = g("https://api.underdogfantasy.com/v1/over_under_lines")
    os.makedirs("esports_lines", exist_ok=True)
    P = {p["id"]: p for p in d["players"]}
    A = {a["id"]: a for a in d["appearances"]}
    rows = []
    for l in d["over_under_lines"]:
        ap = l["over_under"].get("appearance_stat", {})
        a = A.get(ap.get("appearance_id"))
        if not a:
            continue
        p = P[a["player_id"]]
        if p.get("sport_id") not in ("CS", "LOL", "VAL", "DOTA"):
            continue
        rows.append(dict(sport=p["sport_id"], player=p["last_name"] or p["first_name"], first=p["first_name"],
                         team_id=a.get("team_id"), match_id=a.get("match_id"), stat=ap.get("display_stat"),
                         line=l["stat_value"], options={o["choice"]: o.get("payout_multiplier") for o in l["options"]}))
    day = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-5))).strftime("%Y-%m-%d_%H%M")
    json.dump(dict(games=d.get("games"), lines=rows), open("esports_lines/%s.json" % day, "w", encoding="utf-8"))
    print("saved", len(rows), "esports lines")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "snap":
        snap()
    else:
        pull(int(sys.argv[1]) if len(sys.argv) > 1 else 60, int(sys.argv[2]) if len(sys.argv) > 2 else 0)
