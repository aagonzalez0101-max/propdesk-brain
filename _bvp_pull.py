"""Batter-vs-pitcher history from play-by-play, built LEAK-FREE -> bvp.jsonl

    python _bvp_pull.py 2025-03-01 2026-09-21

One row per plate appearance: date, batter id, pitcher id, and the outcome. We build the
matchup history ourselves instead of asking the API for career splits, because the career
split it returns TODAY includes the games we are trying to predict. That is exactly the
as-of leak that faked earlier backtests ([[feedback_asof_leak]]): when the test asks
"how does this lineup hit this starter", the answer must only contain plate appearances
that had already happened.

Resumable: skips game ids already saved.
"""
import json, os, sys, time, urllib.request

OUT = "bvp.jsonl"
API = "https://statsapi.mlb.com/api/v1"
UA = {"User-Agent": "Mozilla/5.0"}
g = lambda u: json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=45).read())

# what counts as a "good" outcome for the batter, in total bases; None = not an at-bat
TB = {"single": 1, "double": 2, "triple": 3, "home_run": 4}
NOT_AB = {"walk", "intent_walk", "hit_by_pitch", "sac_fly", "sac_bunt", "catcher_interf",
          "sac_fly_double_play", "sac_bunt_double_play"}


def done_games():
    seen = set()
    if os.path.exists(OUT):
        for l in open(OUT, encoding="utf-8"):
            try:
                seen.add(json.loads(l)["g"])
            except Exception:
                pass
    return seen


def schedule(start, end):
    d = g("%s/schedule?sportId=1&startDate=%s&endDate=%s" % (API, start, end))
    out = []
    for dt in d.get("dates", []):
        for gm in dt["games"]:
            if gm["status"]["detailedState"] == "Final":
                out.append((gm["officialDate"], gm["gamePk"]))
    return out


def pull(start, end):
    seen = done_games()
    games = [x for x in schedule(start, end) if x[1] not in seen]
    print("%d finished games in range, %d already saved, %d to pull" % (
        len(games) + len(seen & {x[1] for x in schedule(start, end)}), len(seen), len(games)))
    f = open(OUT, "a", encoding="utf-8")
    n = 0
    for date, pk in games:
        try:
            pbp = g("%s/game/%d/playByPlay" % (API, pk))
        except Exception as e:
            print(" game", pk, e); time.sleep(3); continue
        for play in pbp.get("allPlays", []):
            m = play.get("matchup") or {}
            res = play.get("result") or {}
            ev = (res.get("eventType") or "")
            b = (m.get("batter") or {}).get("id"); p = (m.get("pitcher") or {}).get("id")
            if not b or not p or not ev:
                continue
            ab = 0 if ev in NOT_AB else 1
            f.write(json.dumps(dict(g=pk, d=date, b=b, p=p, e=ev, ab=ab,
                                    tb=TB.get(ev, 0), h=1 if ev in TB else 0,
                                    k=1 if ev in ("strikeout", "strikeout_double_play") else 0,
                                    bb=1 if ev in ("walk", "intent_walk") else 0)) + "\n")
        n += 1
        if n % 50 == 0:
            f.flush(); print("  %d games saved" % n, flush=True)
        time.sleep(0.12)
    f.close()
    print("done, %d games added" % n)


if __name__ == "__main__":
    pull(sys.argv[1] if len(sys.argv) > 1 else "2025-03-01",
         sys.argv[2] if len(sys.argv) > 2 else "2026-09-21")
