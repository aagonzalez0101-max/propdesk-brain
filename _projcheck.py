"""PROJECTION vs ACTUAL (2026-10-10, user: "what Dota has -- compare what you projected vs the real result, as a small check").
For every leg we bet or carded on a day: line, OUR projection, actual result, how far the projection missed, and whether the call was right.
    python _projcheck.py [YYYY-MM-DD] [--post]     # default: yesterday; --post sends the table to Discord #card
Projection source per market: CS2 = model mean (cs2_paper / cs2_priced_all), Dota = model proj (dota_paper), NFL = his 2026 average,
NHL/WNBA = his pre-game last-10 average (the direction model outputs a side, not a number). Actual = box score for that date.
"""
import sys, json, datetime, re, os
import _cardpost as C

norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())


def legs_for(day):
    out, seen = [], set()
    for l in open("live_paper.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if r.get("kind") != "LIVE" or r.get("date") != day or r.get("exclude"):
            continue
        sport = r.get("sport", "")
        for g in r.get("legs") or []:
            sp = "CS2" if "Kills" in g.get("stat", "") or "Headshots" in g.get("stat", "") else \
                 "NHL" if "Shots On Goal" in g.get("stat", "") else "CFB" if "Pass Yards" in g.get("stat", "") and "CFB" in sport else \
                 "NFL" if "NFL" in sport else sport.split("+")[0]
            k = (g["player"], g["stat"], g["line"])
            if k not in seen:
                seen.add(k); out.append(dict(sport=sp, player=g["player"], stat=g["stat"], line=g["line"], side=g["side"], bet=True))
    if os.path.exists("dota_paper.jsonl"):
        for l in open("dota_paper.jsonl", encoding="utf-8"):
            r = json.loads(l)
            if str(r.get("start", ""))[:10] == day or r.get("date") == day:
                k = (r["player"], r["stat"], r["line"])
                if k not in seen:
                    seen.add(k); out.append(dict(sport="Dota2", player=r["player"], stat="MAPS 1-2 Kills", line=r["line"], side=r["side"],
                                                 proj=r.get("proj"), actual=r.get("actual"), bet=False))
    return out


def cs2_proj(player, stat, line):
    best = None
    for f in ("cs2_paper.jsonl", "cs2_priced_all.jsonl"):
        if not os.path.exists(f):
            continue
        for l in open(f, encoding="utf-8"):
            r = json.loads(l)
            if norm(r.get("player")) == norm(player) and r.get("maps") == 2 and (("hs" if "Head" in stat else "k") == r.get("kind")) and r.get("model_mu"):
                best = r["model_mu"]
    return best


def fill(leg, day):
    """projection + actual for one leg"""
    sp = leg["sport"]
    q = dict(sport="Dota2" if sp.startswith("Dota") else sp, player=leg["player"], team="", opp="", stat=leg["stat"], line=leg["line"],
             side=leg["side"], p=0.5, why="")
    G = None
    try:
        G = C.esports_games(q) if q["sport"] in ("CS2", "Dota2", "VAL") else (C.nfl_games(q) if sp == "NFL" else None)
        if G is None and sp in ("NHL", "WNBA", "NBA"):
            S = C.stats_for(q)
            G = S["l10"] if S else None
    except Exception:
        G = None
    if sp == "CFB":                                   # college: box scores live in sports.db (sport CFB, stats pass_yds/rush_yds/rec_yds)
        import sqlite3
        k = {"Pass Yards": "pass_yds", "Rush Yards": "rush_yds", "Receiving Yards": "rec_yds"}.get(leg["stat"])
        if k:
            R = sqlite3.connect("sports.db").execute("select date, stats from player_games where sport='CFB' and player like ? order by date",
                                                     ("%" + leg["player"] + "%",)).fetchall()
            vals = [(d, json.loads(js).get(k) or 0) for d, js in R]
            same = [v for d, v in vals if d in (day, (datetime.date.fromisoformat(day) + datetime.timedelta(days=1)).isoformat())]
            if same and leg.get("actual") is None:
                leg["actual"] = same[-1]
            pre = [v for d, v in vals if d < day][-10:]
            if pre and leg.get("proj") is None:
                leg["proj"] = sum(pre) / len(pre)
    if leg.get("actual") is None and G:
        same = [g for g in G if g["date"] in (day, (datetime.date.fromisoformat(day) + datetime.timedelta(days=1)).isoformat())]
        if same:
            leg["actual"] = same[-1]["v"]
    if leg.get("proj") is None:
        if q["sport"] == "CS2":
            leg["proj"] = cs2_proj(leg["player"], leg["stat"], leg["line"])
        if leg.get("proj") is None and G:
            pre = [g for g in G if g["date"] < day][-10:]
            if pre:
                leg["proj"] = sum(g["v"] for g in pre) / len(pre)
    return leg


def table(day):
    L = [fill(l, day) for l in legs_for(day)]
    lines, right, n, err = [], 0, 0, []
    for l in L:
        a, p = l.get("actual"), l.get("proj")
        if a is None:
            lines.append("⏳ **%s** %s %s %g · proj %s · not graded yet" % (l["player"], "O" if l["side"] == "over" else "U", l["stat"].replace("MAPS 1-2 ", ""), l["line"],
                         ("%.1f" % p) if p is not None else "-"))
            continue
        hit = (a > l["line"]) if l["side"] == "over" else (a < l["line"])
        right += hit; n += 1
        miss = "" if p is None else " · off by **%+.1f**" % (a - p)
        if p is not None:
            err.append(abs(a - p) / max(l["line"], 1))
        lines.append("%s **%s** %s %g %s · proj **%s** → actual **%g**%s%s" % (
            "✅" if hit else "❌", l["player"], "O" if l["side"] == "over" else "U", l["line"], l["stat"].replace("MAPS 1-2 ", "").replace("Shots On Goal", "SOG"),
            ("%.1f" % p) if p is not None else "-", a, miss, "" if l["bet"] else " _(paper)_"))
    head = "Calls right **%d of %d**" % (right, n) + (" · average projection miss **%.0f%%** of the line" % (100 * sum(err) / len(err)) if err else "")
    return head, lines


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    day = a[0] if a else (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    head, lines = table(day)
    print("PROJ vs ACTUAL", day, "--", head.replace("**", ""))
    for x in lines:
        print("  " + x.replace("**", ""))
    if "--post" in sys.argv:
        C.post_embed("📏 PROJECTION vs ACTUAL · %s" % day, head + chr(10) + chr(10) + chr(10).join(lines), 0x539DF5)
