"""Screen the whole Underdog NFL board against real history + matchup. Free data only.

    python _nflprops.py            # Sunday's board, best sides first
    python _nflprops.py 0.60       # lower the hit-rate floor

For every Underdog line: how often that player actually beat that exact number in 2025 + 2026,
the size of the gap between his average and the line, whether Week 1 agreed, and how the opposing
defense ranks against his position (from _nflmatch). Rows are dropped when:
  - fewer than 8 games of history, or he changed teams (old rate belongs to an old role)
  - Week 1 went the other way by a wide margin (role change we cannot see)
  - the line sits within 8% of his average (a fair line, no edge either way)
Break-even on Underdog Standard: 2-pick 3.5x = 53.5%, 3-pick 6.5x = 53.6%.
"""
import sys, csv, io, json, math, datetime, collections, urllib.request

REAL_ONLY = True   # drop 0.5-yard novelty lines and never-used backups
import _nflmatch as NM

H = {"User-Agent": "Mozilla/5.0"}
STAT = {"Receiving Yards": "receiving_yards", "Rush Yards": "rushing_yards",
        "Pass Yards": "passing_yards", "Receptions": "receptions", "Rush Attempts": "carries",
        "Targets": "targets", "Completions": "completions", "Pass Attempts": "attempts",
        "Rush + Rec Yards": "rush_rec"}
POS_KEY = {"RB": {"rushing_yards": "d_rush_rb", "receiving_yards": "d_rec_rb", "rush_rec": "d_rush_rb"},
           "WR": {"receiving_yards": "d_rec_wr"}, "TE": {"receiving_yards": "d_rec_te"},
           "QB": {"passing_yards": "d_pass", "rushing_yards": "d_rush_qb"}}
ALIAS = {"WAS": "WAS", "WSH": "WAS", "LA": "LA", "LAR": "LA"}


def load(year):
    raw = urllib.request.urlopen(urllib.request.Request(
        "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_%d.csv" % year,
        headers=H), timeout=240).read().decode()
    return [r for r in csv.DictReader(io.StringIO(raw)) if r["season_type"] == "REG"]


def hist():
    G = collections.defaultdict(list)
    teams = collections.defaultdict(set)
    pos = {}
    for yr in (2025, 2026):
        for r in load(yr):
            n = r["player_display_name"]
            teams[n].add(r["team"])
            pos[n] = r["position"]
            d = {k: float(r[k] or 0) for k in
                 ("receiving_yards", "rushing_yards", "passing_yards", "receptions", "carries",
                  "targets", "completions", "attempts")}
            d["rush_rec"] = d["rushing_yards"] + d["receiving_yards"]
            G[n].append((yr, int(r["week"]), d))
    for n in G:
        G[n].sort()
    return G, teams, pos


def underdog_nfl():
    d = json.loads(urllib.request.urlopen(urllib.request.Request(
        "https://api.underdogfantasy.com/v1/over_under_lines", headers=H), timeout=120).read())
    P = {p["id"]: p for p in d["players"]}
    A = {a["id"]: a for a in d["appearances"]}
    Gm = {g["id"]: g for g in d.get("games", []) if g.get("sport_id") == "NFL"}
    out = []
    for l in d["over_under_lines"]:
        ap = l["over_under"].get("appearance_stat", {})
        a = A.get(ap.get("appearance_id"))
        if not a or a.get("match_id") not in Gm:
            continue
        col = STAT.get(ap.get("display_stat"))
        if not col:
            continue
        p = P[a["player_id"]]
        gm = Gm[a["match_id"]]
        out.append(dict(name=(p.get("first_name", "") + " " + p.get("last_name", "")).strip(),
                        stat=ap["display_stat"], col=col, line=float(l["stat_value"]),
                        match=gm["full_team_names_title"], title=gm.get("abbreviated_title", ""),
                        start=gm["scheduled_at"],
                        mult={o["choice"]: float(o.get("payout_multiplier") or 1) for o in l.get("options", [])}))
    return out


def main(floor=0.65):
    G, teams, pos = hist()
    D, O, gw = NM.build()
    prof = NM.per_game(D, O, gw)
    keys = ["d_rush_rb", "d_rec_wr", "d_rec_te", "d_rec_rb", "d_rush_qb", "d_pass"]
    R = {k: NM.ranks(prof, k) for k in keys}
    rows = []
    for L in underdog_nfl():
        g = G.get(L["name"])
        if not g or len(g) < 8 or len(teams[L["name"]]) > 1:
            continue
        vals = [d[L["col"]] for _, _, d in g]
        over = sum(v > L["line"] for v in vals) / len(vals)
        side, rate = ("higher", over) if over >= .5 else ("lower", 1 - over)
        avg = sum(vals) / len(vals)
        if L["line"] and abs(avg - L["line"]) / max(1.0, L["line"]) < 0.08:
            continue                                   # line sits on his average
        wk1 = [d[L["col"]] for yr, wk, d in g if yr == 2026]
        w1 = wk1[0] if wk1 else None
        if w1 is not None and L["line"]:
            agreed = (w1 > L["line"]) == (side == "higher")
            if not agreed and abs(w1 - L["line"]) / max(1.0, L["line"]) > 0.5:
                continue                               # week 1 blew the other way: role change
        else:
            agreed = None
        if rate < floor:
            continue
        # keep real production props only: the line has to be in the neighbourhood of what he does
        if REAL_ONLY:
            if L["stat"] not in ("Receiving Yards", "Rush Yards", "Rush + Rec Yards", "Pass Yards"):
                continue
            if L["line"] < 15 or not (0.45 <= avg / max(1.0, L["line"]) <= 2.2):
                continue
        # matchup: which defense he faces
        me = list(teams[L["name"]])[0]
        t1, t2 = [x.strip() for x in L["title"].split(" @ ")] if " @ " in L["title"] else (None, None)
        opp = None
        if t1:
            other = t2 if ALIAS.get(t1, t1) == ALIAS.get(me, me) else t1
            opp = ALIAS.get(other, other)
        k = POS_KEY.get(pos.get(L["name"], ""), {}).get(L["col"])
        rank = R[k].get(opp) if (k and opp in prof) else None
        rows.append((rate, L, side, avg, w1, agreed, rank, opp, pos.get(L["name"]), len(vals)))
    rows.sort(key=lambda r: -r[0])
    print("%-22s %-4s %-17s %6s %-6s %5s %7s %6s  %-9s %s" % (
        "player", "pos", "stat", "line", "side", "hit", "avg", "wk1", "def rank", "game"))
    for rate, L, side, avg, w1, agreed, rank, opp, ps, n in rows[:40]:
        rk = "-" if rank is None else ("#%d %s" % (rank, "soft" if rank <= 10 else "tough" if rank >= 23 else ""))
        print("%-22s %-4s %-17s %6.1f %-6s %4.0f%% %7.1f %6s  %-9s %s" % (
            L["name"][:22], ps or "?", L["stat"][:17], L["line"],
            "OVER" if side == "higher" else "UNDER", 100 * rate, avg,
            "-" if w1 is None else int(w1), rk, L["title"]))
    print("\n%d lines pass the floor (%.0f%%). Break-even: 53.5%% per leg." % (len(rows), 100 * floor))


def cli():
    global REAL_ONLY
    if "--all" in sys.argv:
        REAL_ONLY = False
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    main(float(a[0]) if a else 0.65)


if __name__ == "__main__":
    cli()
