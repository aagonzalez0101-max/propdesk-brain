"""ESPORTS DAILY BACKTEST (10/23, user: "backtest every day, pick the 2 best that clear our mark, would we have made money so far on
one 2-leg or one 3-leg every day"). Replays every day in cs2_paper.jsonl: the legs that clear the mark, ranked by edge, one leg per
player, different matches -> one 2-pick (3x) and one 3-pick (6x) at $1 each. Days with too few clearing legs are skipped (no forcing).

Marks tested side by side:
    v3   LOWER + edge >= 6% + Maps 1+2 + player's team < 40% to win the map   (rule v3, 79-37 on all legs)
    lo69 LOWER + edge 6-9%                                                     (the older band, 59%)

    python _es_daily_bt.py           # full replay + running P&L; nightly in the esports grade
"""
import json, collections, datetime

CT = datetime.timezone(datetime.timedelta(hours=-5))


def edge(r):
    x = float(r.get("edge") or 0)
    return x * 100 if abs(x) < 1 else x


MARKS = {
    "v3": lambda r: r.get("side") == "lower" and edge(r) >= 6 and "1+2" in (r.get("stat") or "") and r.get("map_winp") is not None and float(r["map_winp"]) < 0.40,
    "lo69": lambda r: r.get("side") == "lower" and 6 <= edge(r) < 9,
}


def day_of(r):
    s = r.get("start") or r.get("ts") or ""
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(CT).date().isoformat()
    except Exception:
        return s[:10]


def pick(legs, k):
    out, players, matches = [], set(), set()
    for r in sorted(legs, key=lambda r: -edge(r)):
        if r["player"] in players or r.get("match") in matches:
            continue
        out.append(r); players.add(r["player"]); matches.add(r.get("match"))
        if len(out) == k:
            return out
    return None


def run():
    R = [json.loads(l) for l in open("cs2_paper.jsonl", encoding="utf-8")]
    G = [r for r in R if r.get("result") in ("W", "L")]
    for name, mark in MARKS.items():
        by = collections.defaultdict(list)
        for r in G:
            if mark(r):
                by[day_of(r)].append(r)
        tot = {2: [0, 0, 0.0], 3: [0, 0, 0.0]}; rows = []
        for d in sorted(by):
            line = [d, len(by[d])]
            for k, mult in ((2, 3.0), (3, 6.0)):
                p = pick(by[d], k)
                if not p:
                    line.append("  -  "); continue
                win = all(x["result"] == "W" for x in p)
                tot[k][0] += win; tot[k][1] += 1; tot[k][2] += (mult - 1) if win else -1
                line.append("%s %+.0f" % ("W" if win else "L", (mult - 1) if win else -1))
            rows.append(line)
        print("\n=== MARK %s -- %d days with clearing legs" % (name, len(rows)))
        for d, n, a, b in rows[-21:]:
            print("  %s  legs %2d | 2-pick %-6s | 3-pick %s" % (d, n, a, b))
        for k in (2, 3):
            w, n, net = tot[k]
            print("  %d-pick every day: %d-%d (%.0f%%)  at $5/slip net %+.2f (staked $%d)  ROI %+.0f%%" % (k, w, n - w, 100 * w / max(n, 1), 5 * net, 5 * n, 100 * net / max(n, 1)))   # user 10/23: $5 per slip


if __name__ == "__main__":
    run()
