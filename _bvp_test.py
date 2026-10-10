"""Does batter-vs-pitcher history add anything to the moneyline model? -> answer, not a guess.

    python _bvp_test.py

For every graded board game: take each side's actual starting nine and the opposing starter,
add up how those batters have done against THAT pitcher in plate appearances that happened
BEFORE this game, and compare it to how those same batters hit in general. The difference is
the "this lineup owns him" number.

Then two questions:
  1. Does that number move the game at all? (correlation with the actual run margin)
  2. Does it move it beyond what the model already says? (does it explain the model's misses)

A feature only earns a place if the answer to 2 is yes. BvP is famous for tiny samples -- a
hitter sees a given starter 10-20 times in a career -- so the null result is the likely one and
is just as useful: it closes the question.
"""
import json, glob, os, math, time, collections, urllib.request

API = "https://statsapi.mlb.com/api/v1"
UA = {"User-Agent": "Mozilla/5.0"}
g = lambda u: json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=45).read())
CACHE = "bvp_games.json"


def load_bvp():
    """(batter, pitcher) -> list of (date, ab, h, tb, k), and each batter's own totals."""
    pair = collections.defaultdict(list)
    bat = collections.defaultdict(lambda: [0, 0, 0, 0])      # ab, h, tb, k
    for l in open("bvp.jsonl", encoding="utf-8"):
        r = json.loads(l)
        pair[(r["b"], r["p"])].append((r["d"], r["ab"], r["h"], r["tb"], r["k"]))
        s = bat[r["b"]]
        s[0] += r["ab"]; s[1] += r["h"]; s[2] += r["tb"]; s[3] += r["k"]
    return pair, bat


def board_games():
    out = {}
    for f in sorted(glob.glob("pp/boards/2026-09-*.json")):
        try:
            b = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for p in b.get("picks", []):
            if p.get("market") == "ML" and p.get("raw") is not None:
                out.setdefault((b["day"], p["game"]), {})[p["selection"]] = p
    return out


def lineups(days):
    """day -> {game name: (home_ids, away_ids, home_sp, away_sp, home_runs, away_runs)}"""
    if os.path.exists(CACHE):
        return json.load(open(CACHE, encoding="utf-8"))
    out = {}
    for day in days:
        try:
            sched = g("%s/schedule?sportId=1&date=%s" % (API, day))
        except Exception:
            continue
        for dt in sched.get("dates", []):
            for gm in dt["games"]:
                if gm["status"]["detailedState"] != "Final":
                    continue
                try:
                    box = g("%s/game/%d/boxscore" % (API, gm["gamePk"]))
                except Exception:
                    continue
                rec = {}
                for side in ("home", "away"):
                    t = box["teams"][side]
                    order = [int(x) for x in (t.get("battingOrder") or [])][:9]
                    sp = t.get("pitchers") or []
                    rec[side] = dict(order=order, sp=sp[0] if sp else None,
                                     runs=t["teamStats"]["batting"].get("runs", 0))
                name = "%s @ %s" % (gm["teams"]["away"]["team"]["name"], gm["teams"]["home"]["team"]["name"])
                out.setdefault(day, {})[name] = rec
                time.sleep(0.05)
        print("  lineups", day, flush=True)
    json.dump(out, open(CACHE, "w", encoding="utf-8"))
    return out


def lineup_edge(order, sp, day, pair, bat):
    """How much better than usual this lineup has hit this pitcher, per plate appearance."""
    tb = ab = 0
    exp = 0.0
    for b in order:
        for (d, a, h, t, k) in pair.get((b, sp), []):
            if d >= day:
                continue                       # leak guard: only what had already happened
            ab += a; tb += t
            own = bat[b]
            exp += (own[2] / own[0]) * a if own[0] else 0.0
    if ab < 15:
        return None, ab                        # too little history to say anything
    return (tb - exp) / ab, ab


def main():
    pair, bat = load_bvp()
    games = board_games()
    days = sorted({k[0] for k in games})
    L = lineups(days)
    rows = []
    for (day, name), picks in games.items():
        rec = (L.get(day) or {}).get(name)
        if not rec:
            continue
        hm, aw = rec["home"], rec["away"]
        if not (hm["order"] and aw["order"] and hm["sp"] and aw["sp"]):
            continue
        h_edge, h_n = lineup_edge(hm["order"], aw["sp"], day, pair, bat)
        a_edge, a_n = lineup_edge(aw["order"], hm["sp"], day, pair, bat)
        if h_edge is None or a_edge is None:
            continue
        margin = hm["runs"] - aw["runs"]
        home_name = name.split(" @ ")[1]
        p = picks.get(home_name)
        model_home = p["raw"] if p else None
        if model_home is None:
            other = [v for k, v in picks.items() if k != home_name]
            model_home = 1 - other[0]["raw"] if other else None
        if model_home is None:
            continue
        rows.append(dict(day=day, game=name, bvp=h_edge - a_edge, n=h_n + a_n,
                         margin=margin, model=model_home, home_won=margin > 0))
    print("\n%d games with enough matchup history on both sides" % len(rows))
    if len(rows) < 30:
        print("not enough to test"); return

    def corr(xs, ys):
        n = len(xs); mx = sum(xs) / n; my = sum(ys) / n
        sx = math.sqrt(sum((x - mx) ** 2 for x in xs) / n) or 1e-9
        sy = math.sqrt(sum((y - my) ** 2 for y in ys) / n) or 1e-9
        return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (n * sx * sy)

    bv = [r["bvp"] for r in rows]
    mg = [float(r["margin"]) for r in rows]
    resid = [r["margin"] - (r["model"] - 0.5) * 6.0 for r in rows]   # model's implied lean, in runs
    c1, c2 = corr(bv, mg), corr(bv, resid)
    t = lambda c, n: c * math.sqrt((n - 2) / max(1e-9, 1 - c * c))
    print("  matchup edge vs actual run margin:     correlation %+.3f  (t %+.2f)" % (c1, t(c1, len(rows))))
    print("  matchup edge vs what the model MISSED: correlation %+.3f  (t %+.2f)" % (c2, t(c2, len(rows))))
    hi = [r for r in rows if r["bvp"] > 0.05]
    lo = [r for r in rows if r["bvp"] < -0.05]
    for nm, s in (("home lineup owns the pitcher", hi), ("home lineup struggles vs him", lo)):
        if len(s) >= 15:
            w = sum(1 for r in s if r["home_won"])
            print("  %-32s %3d games, home won %3d (%.0f%%), model said %.0f%%"
                  % (nm, len(s), w, 100 * w / len(s), 100 * sum(r["model"] for r in s) / len(s)))
    print("\n  median plate appearances of history per game: %d"
          % sorted(r["n"] for r in rows)[len(rows) // 2])


if __name__ == "__main__":
    main()
