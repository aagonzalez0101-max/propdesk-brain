"""Game-level LoL context from Leaguepedia -> lol_games.jsonl

    python _lol_games.py

`ScoreboardPlayers` (already collected, 26k rows) gives kills/deaths/assists per player but
NOT the three things that decide a kill line: how long the game ran, who won, and who the
opponent was. Those live in `ScoreboardGames`, keyed by the same GameId.

Duration matters here for the same reason it killed the first Dota model: a 22-minute stomp
and a 40-minute grind are different games, and multiplying a per-game average by nothing at
all quietly assumes every game is average length.
"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from betting import lol as L

OUT = "lol_games.jsonl"
F = ("GameId=gid,Gamelength=len,Gamelength_Number=lenmin,Winner=winner,"
     "Team1=t1,Team2=t2,Team1Kills=k1,Team2Kills=k2,DateTime_UTC=dt,Tournament=tour")


def done():
    s = set()
    if os.path.exists(OUT):
        for l in open(OUT, encoding="utf-8"):
            try:
                s.add(json.loads(l)["gid"])
            except Exception:
                pass
    return s


def pull(start="2026-01-01"):
    have = done()
    print("have %d games already" % len(have), flush=True)
    f = open(OUT, "a", encoding="utf-8")
    cur, new, empty = start + " 00:00:00", 0, 0
    while True:
        try:
            rows = L._cargo("ScoreboardGames", F,
                            where='ScoreboardGames.DateTime_UTC >= "%s"' % cur,
                            order="ScoreboardGames.DateTime_UTC ASC", limit=500)
        except L.RateLimited as e:
            print("  throttled (%s), waiting 90s" % e, flush=True)
            time.sleep(90)
            continue
        if not rows:
            empty += 1
            if empty >= 2:
                break
            time.sleep(5)
            continue
        empty = 0
        added = 0
        for r in rows:
            if r.get("gid") and r["gid"] not in have:
                have.add(r["gid"]); f.write(json.dumps(r) + "\n"); added += 1
        new += added
        f.flush()
        last = rows[-1].get("dt")
        print("  ..%s  %d games (+%d)" % (last, len(have), added), flush=True)
        if last == cur and added == 0:
            # a single timestamp can hold more rows than one page returns; step past it
            t = time.strptime(last, "%Y-%m-%d %H:%M:%S")
            cur = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.mktime(t) + 60))
        else:
            cur = last
    f.close()
    print("done: %d new -> %s (%d total)" % (new, OUT, len(have)))


if __name__ == "__main__":
    pull(sys.argv[1] if len(sys.argv) > 1 else "2026-01-01")
