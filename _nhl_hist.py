"""NHL history for the prop backtest (2026-09-30): every regular-season box score of 2024-25 and 2025-26 (+ the new
season so far) into _nhl/<gameId>.json, then one row per player-game.

    python _nhl_hist.py fetch     # resumable
    python _nhl_hist.py build     # -> _nhl_hist_rows.json
"""
import sys, os, json, time
from concurrent.futures import ThreadPoolExecutor
import _props as P

D = "_nhl"
os.makedirs(D, exist_ok=True)
SEASONS = {"2024": 1312, "2025": 1312, "2026": 1312}
PRESEASON = {"2026": 140}      # 2026-27 preseason (game type 01) -- roles, goalie usage and lineups before opening night


def box(gid):
    f = os.path.join(D, "%d.json" % gid)
    if os.path.exists(f):
        return json.load(open(f, encoding="utf-8"))
    b = P.get("https://api-web.nhle.com/v1/gamecenter/%d/boxscore" % gid)
    if b.get("gameState") in ("OFF", "FINAL"):
        slim = {k: b.get(k) for k in ("id", "gameDate", "awayTeam", "homeTeam", "playerByGameStats", "gameState")}
        json.dump(slim, open(f, "w", encoding="utf-8"))
        return slim
    return None


def fetch():
    todo = [int("%s02%04d" % (s, i)) for s, n in SEASONS.items() for i in range(1, n + 1)]
    todo += [int("%s01%04d" % (s, i)) for s, n in PRESEASON.items() for i in range(1, n + 1)]
    todo = [g for g in todo if not os.path.exists(os.path.join(D, "%d.json" % g))]
    print("%d games to fetch" % len(todo), flush=True)
    done = [0]; miss = [0]

    def one(g):
        for a in range(3):
            try:
                if box(g) is None:
                    miss[0] += 1
                break
            except Exception:
                time.sleep(2 + 3 * a)
        done[0] += 1
        if done[0] % 250 == 0:
            print("  %d / %d  (not played yet: %d)" % (done[0], len(todo), miss[0]), flush=True)

    with ThreadPoolExecutor(6) as ex:
        list(ex.map(one, todo))
    print("fetch complete", flush=True)


def toi(s):
    try:
        m, x = s.split(":"); return int(m) + int(x) / 60
    except Exception:
        return 0.0


def build():
    out = []
    for fn in os.listdir(D):
        b = json.load(open(os.path.join(D, fn), encoding="utf-8"))
        season = str(b["id"])[:4]
        teams = {"awayTeam": b["awayTeam"], "homeTeam": b["homeTeam"]}
        for side, other in (("awayTeam", "homeTeam"), ("homeTeam", "awayTeam")):
            st = b["playerByGameStats"][side]
            base = dict(gid=b["id"], season=season, gtype="pre" if str(b["id"])[4:6] == "01" else "reg", date=b["gameDate"], team=teams[side]["abbrev"],
                        opp=teams[other]["abbrev"], home=(side == "homeTeam"),
                        team_sog=teams[side].get("sog"), opp_sog=teams[other].get("sog"),
                        team_goals=teams[side].get("score"), opp_goals=teams[other].get("score"))
            for grp in ("forwards", "defense"):
                for p in st.get(grp, []):
                    out.append(dict(base, pid=p["playerId"], name=p["name"]["default"], pos=grp[0].upper(), toi=toi(p.get("toi")),
                                    sog=p.get("sog"), goals=p.get("goals"), assists=p.get("assists"), points=p.get("points"),
                                    hits=p.get("hits"), blocks=p.get("blockedShots"), pp_goals=p.get("powerPlayGoals")))
            for g in st.get("goalies", []):
                out.append(dict(base, pid=g["playerId"], name=g["name"]["default"], pos="G", toi=toi(g.get("toi")),
                                starter=bool(g.get("starter")), saves=g.get("saves"), shots_against=g.get("shotsAgainst")))
    json.dump(out, open("_nhl_hist_rows.json", "w"))
    print("%d player-game rows from %d games" % (len(out), len({r['gid'] for r in out})))


if __name__ == "__main__":
    {"fetch": fetch, "build": build}[sys.argv[1]]()
