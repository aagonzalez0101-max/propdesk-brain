"""ESPORTS + TENNIS EDGE RESEARCH (11/17, user: "keep testing like we did for nba and find an edge with any possible stat ... lets just keep
going"). Same method as _edge_research.py: every graded paper line from the cloud ledgers, ~15 single conditions + every pair, FOUND on
the first half of the days and must HOLD on the second half (both >= the PP break-even). Then each surviving rule is replayed as SLIPS:
the top 2 legs a day (one per player, one per match) as a $1 2-pick at 3x.
    python _es_research.py <dir with cs2_paper.jsonl / tennis_pp_paper.jsonl>   (default: current folder)
"""
import sys, os, json, collections, datetime, itertools

D = sys.argv[1] if len(sys.argv) > 1 else "."
BE = .577


def cs2_rows():
    R = {}
    for l in open(os.path.join(D, "cs2_paper.jsonl"), encoding="utf-8"):
        if not l.strip():
            continue
        r = json.loads(l)
        if r.get("result") in ("W", "L") and r.get("edge") is not None:
            R[(r.get("match_id"), r.get("pid") or r.get("player"), r.get("stat"), r.get("side"))] = r
    out = []
    for r in R.values():
        st = r.get("start") or r["ts"]
        day = (datetime.datetime.fromisoformat(st.replace("Z", "+00:00")) - datetime.timedelta(hours=6)).date().isoformat()
        mw = r.get("map_winp"); mk = r.get("market_winp")
        out.append(dict(day=day, who=r.get("pid") or r.get("player"), game=r.get("match_id") or r.get("match"), won=r["result"] == "W",
                        rank=r["edge"], f={
            "lower": r["side"] == "lower", "higher": r["side"] != "lower",
            "kills": "Kills" in (r.get("stat") or ""), "headshots": "Headshots" in (r.get("stat") or ""),
            "edge 6%+": r["edge"] >= .06, "edge 9%+": r["edge"] >= .09, "edge 12%+": r["edge"] >= .12,
            "model 62%+": (r.get("model_p") or 0) >= .62,
            "team underdog (map win < 45%)": mw is not None and mw < .45, "team favourite (map win > 55%)": mw is not None and mw > .55,
            "coin-flip map (45-55%)": mw is not None and .45 <= mw <= .55,
            "market & model agree on winner": mw is not None and mk is not None and (mw - .5) * (mk - .5) > 0,
            "on PP (pp_line set)": r.get("pp_line") is not None, "PP line = model line": r.get("pp_line") == r.get("line"),
            "PP line above model line": r.get("pp_line") is not None and r["pp_line"] > r["line"],
            "big line (kills 30+ / HS 15+)": (r["line"] >= 30) if "Kills" in (r.get("stat") or "") else (r["line"] >= 15),
            "deep history (300+ maps)": (r.get("n_maps_hist") or 0) >= 300, "thin history (<100 maps)": (r.get("n_maps_hist") or 0) < 100,
        }))
    return out


def tennis_rows():
    R = {}
    for l in open(os.path.join(D, "tennis_pp_paper.jsonl"), encoding="utf-8"):
        if not l.strip():
            continue
        r = json.loads(l)
        if r.get("result") in ("W", "L"):
            R[(r.get("pid"), r.get("side"))] = r
    out = []
    for r in R.values():
        fav = max(r["pin_win"], 1 - r["pin_win"]) if r.get("pin_win") is not None else None
        out.append(dict(day=r["start"][:10], who=r["player"], game=(r["player"], r["opp"]) if r["player"] < r["opp"] else (r["opp"], r["player"]),
                        won=r["result"] == "W", rank=r.get("edge") or 0, f={
            "standard": r["kind"] == "standard", "goblin": r["kind"] == "goblin", "demon": r["kind"] == "demon",
            "over": r["side"] == "over", "under": r["side"] == "under",
            "total games": r["stat"] == "Total Games", "games won": r["stat"] == "Total Games Won", "1st set games": r["stat"].startswith("1st Set"),
            "tiebreaks": "Tie Break" in r["stat"], "sets": r["stat"] == "Total Sets", "fantasy": "Fantasy" in r["stat"],
            "atp": r.get("tour") == "atp", "wta": r.get("tour") == "wta", "challenger/other": r.get("tour") not in ("atp", "wta"),
            "edge 3%+": (r.get("edge") or 0) >= .03, "edge 6%+": (r.get("edge") or 0) >= .06,
            "heavy favourite match (75%+)": fav is not None and fav >= .75, "close match (<60%)": fav is not None and fav < .60,
            "player is the favourite": r.get("pin_win") is not None and r["pin_win"] > .5,
        }))
    return out


def search(name, rows, be_of=lambda f: BE):
    days = sorted({r["day"] for r in rows}); half = days[len(days) // 2]
    A = [r for r in rows if r["day"] < half]; B = [r for r in rows if r["day"] >= half]
    keys = list(rows[0]["f"])

    def rec(X):
        w = sum(r["won"] for r in X); return w, len(X)

    def fmt(w, n):
        return "%4d-%-4d %5.1f%%" % (w, n - w, 100 * w / n) if n else "    --         "

    def slips(X):
        by = collections.defaultdict(list)
        for r in X:
            by[r["day"]].append(r)
        w = l = 0
        for d, c in by.items():
            c.sort(key=lambda r: -r["rank"]); pk = []; ws = set(); gs = set()
            for r in c:
                if r["who"] in ws or r["game"] in gs:
                    continue
                ws.add(r["who"]); gs.add(r["game"]); pk.append(r)
                if len(pk) == 2:
                    break
            if len(pk) == 2:
                if pk[0]["won"] and pk[1]["won"]:
                    w += 1
                else:
                    l += 1
        n = w + l
        return "slips %d-%d net %+d (ROI %+.0f%%)" % (w, l, 2 * w - l, 100 * (2 * w - l) / n) if n else "slips --"

    print("\n%s: %d graded lines, %s..%s (first half < %s <= second half), 2-pick break-even %.1f%%" % (name, len(rows), days[0], days[-1], half, 100 * BE))
    print("  %-62s %-16s %-16s %-16s" % ("rule", "first half", "second half", "all"))
    found = []
    conds = [(k,) for k in keys] + list(itertools.combinations(keys, 2)) + list(itertools.combinations(keys, 3))
    for c in conds:
        f = lambda r, c=c: all(r["f"][k] for k in c)
        a, b = rec([r for r in A if f(r)]), rec([r for r in B if f(r)])
        if a[1] >= 25 and b[1] >= 20 and a[0] / a[1] >= BE and b[0] / b[1] >= BE:
            found.append((min(a[0] / a[1], b[0] / b[1]), c, a, b, f))
    found.sort(key=lambda x: -x[0])
    if not found:
        print("  nothing holds both halves at %.1f%%+" % (100 * BE))
    shown = 0
    for lo, c, a, b, f in found:
        X = [r for r in rows if f(r)]
        print("  %-62s %s %s %s | %s" % (" + ".join(c)[:62], fmt(*a), fmt(*b), fmt(*rec(X)), slips(X)))
        shown += 1
        if shown >= 15:
            break
    return found


if __name__ == "__main__":
    if os.path.exists(os.path.join(D, "cs2_paper.jsonl")):
        search("CS2", cs2_rows())
    if os.path.exists(os.path.join(D, "tennis_pp_paper.jsonl")):
        T = tennis_rows()
        search("TENNIS standard lines only (goblin/demon pay differently)", [r for r in T if r["f"]["standard"]])
