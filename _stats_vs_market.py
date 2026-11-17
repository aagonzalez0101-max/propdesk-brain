"""STATS vs MARKET (11/15, user: "with all backtesting there's no way to beat the market by our stats alone? ... run that test").
Every graded PP closing line (pp_history.jsonl, 9/30-10/31) joined to the sharp price at that SAME line (lines.db sharp: Pinnacle +
FanDuel de-vigged p_over, latest snapshot on game day) and the player's L10 hit rate at that line from games BEFORE that day (sports.db).
Question: when our stats say 8/10+ but the market says coin flip, which one does the result follow?
    python _stats_vs_market.py
"""
import json, sqlite3, collections, datetime, re
import _history as H

SH = {"Receiving Yards": "receiving yards", "Rush Yards": "rushing yards", "Receptions": "receptions", "Pass Yards": "passing yards",
      "Rush Attempts": "rush attempts", "Pass Completions": "pass completions", "Pass Attempts": "pass attempts",
      "Shots On Goal": "shots on goal", "Points": "points", "Assists": "assists", "Goals": "goals", "Goalie Saves": "saves",
      "Rebounds": "rebounds", "3-PT Made": "threes made", "Pts+Rebs+Asts": "pts & rebs & asts", "Total Bases": "bases",
      "Pitcher Strikeouts": "strikeouts"}
norm = lambda s: re.sub(r"[^a-z]", "", (s or "").lower())


def main():
    L = sqlite3.connect("lines.db"); S = sqlite3.connect("sports.db")
    mk = collections.defaultdict(dict)    # (sport, player, stat, line, day) -> {book: (ts, p)}
    for book, sp, pl, st, ln, p, ts in L.execute("select book, sport, player, stat, line, p_over, ts from sharp"):
        k = (sp, pl, st, ln, ts[:10]); b = mk[k].get(book)
        if not b or ts > b[0]:
            mk[k][book] = (ts, p)
    G = collections.defaultdict(list)
    for sp in ("NFL", "CFB", "NHL", "NBA", "WNBA", "MLB"):
        for pl, d, gid, st in S.execute("select player, date, game_id, stats from player_games where sport=?", (sp,)):
            if sp == "NFL" and not str(gid).startswith("2026_"):
                continue
            s = json.loads(st)
            for k in {H.norm(pl), H.short(pl)}:
                G[(sp, k)].append((d, s))
    for v in G.values():
        v.sort(key=lambda x: x[0], reverse=True)
    out = []
    for l in open("pp_history.jsonl", encoding="utf-8"):
        r = json.loads(l)
        sp, st, ln = r["sport"], r["stat"], r["close"]
        if st not in SH or r["res_close"] == "push" or sp not in ("NFL", "CFB", "NHL", "NBA", "WNBA", "MLB"):
            continue
        day = r["day"]; prev = (datetime.date.fromisoformat(day) - datetime.timedelta(days=1)).isoformat()
        books = mk.get((sp, norm(r["player"]), SH[st], ln, day)) or mk.get((sp, norm(r["player"]), SH[st], ln, prev))
        if not books:
            continue
        p_over = sum(p for _, p in books.values()) / len(books)
        cut = H.nfl_week(day) if sp == "NFL" else day
        gl = G.get((sp, H.norm(r["player"]))) or G.get((sp, H.short(r["player"]))) or []
        prior = [s for d, s in gl if d < cut][:10]
        vals = []
        for s in prior:
            x = [s.get(k) for k in H.STAT[sp][st]]
            if all(y is not None for y in x):
                vals.append(sum(float(y) for y in x))
        if len(vals) < 6:
            continue
        for side in ("over", "under"):
            hit = sum((v > ln) if side == "over" else (v < ln) for v in vals) / len(vals)
            out.append(dict(day=day, player=r["player"], line=ln, margin=sum(vals)/len(vals)-ln, sp=sp, stat=st, side=side, stats=hit, n=len(vals), mkt=p_over if side == "over" else 1 - p_over,
                            won=r["res_close"] == side, books=len(books)))
    return out


def band_s(h):
    return "8/10+" if h >= .8 else ("6-7/10" if h >= .6 else "<6/10")


def band_m(p):
    return "<48%" if p < .48 else ("48-52%" if p < .52 else ("52-55%" if p < .55 else "55%+"))


if __name__ == "__main__":
    R = main()
    print("joined %d (line, side) pairs = %d graded lines with a sharp price at the same number and 6+ prior games\n" % (len(R), len(R) // 2))
    for lab, flt in (("ALL SIDES", lambda r: True), ("OVERS", lambda r: r["side"] == "over"), ("UNDERS", lambda r: r["side"] == "under")):
        c = collections.defaultdict(lambda: [0, 0])
        for r in R:
            if flt(r):
                x = c[(band_s(r["stats"]), band_m(r["mkt"]))]; x[0] += r["won"]; x[1] += 1
        print(lab)
        print("  %-8s" % "stats|mkt" + "".join("%16s" % m for m in ("<48%", "48-52%", "52-55%", "55%+")))
        for s in ("8/10+", "6-7/10", "<6/10"):
            print("  %-8s" % s + "".join("%16s" % ("%d/%d %.0f%%" % (c[(s, m)][0], c[(s, m)][1], 100 * c[(s, m)][0] / c[(s, m)][1]) if c[(s, m)][1] else "-")
                                         for m in ("<48%", "48-52%", "52-55%", "55%+")))
        print()
    # per sport: 8/10+ stats with a flat market (48-52)
    print("8/10+ STATS, MARKET 48-52% -- by sport and side")
    c = collections.defaultdict(lambda: [0, 0])
    for r in R:
        if r["stats"] >= .8 and .48 <= r["mkt"] < .52:
            x = c[(r["sp"], r["side"])]; x[0] += r["won"]; x[1] += 1
    for k, (w, n) in sorted(c.items(), key=lambda x: -x[1][1]):
        print("  %-5s %-6s %d/%d %.1f%%" % (k[0], k[1], w, n, 100 * w / n))
    json.dump(R, open("stats_vs_market.json", "w"))
