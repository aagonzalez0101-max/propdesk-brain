"""NBA MINUTES DIG (10/22, the user's own method -- how he found McCain points demon and LeBron FTM):
  1. tonight's minutes = his 2026 minutes (preseason + regular) -- the current role, not last season's
  2. hit rate of every PP line (standard / goblin / demon) in the games where he played THOSE minutes (+-4), on his CURRENT team
  3. head-to-head vs tonight's opponent (current team), and this season's games
  4. projection = his per-minute rate on the current team x tonight's minutes

    python _nba_dig.py [date]        # every player with PP lines tonight; prints the lines where the minutes-matched rate >= 70%
"""
import sys, json, sqlite3, datetime, statistics as st, collections
import _nba_board as B, _nba_finder as NF

CT = datetime.timezone(datetime.timedelta(hours=-5))
ESPN = {"NYK": "NY", "GSW": "GS", "SAS": "SA", "NOP": "NO", "UTA": "UTAH", "WAS": "WSH"}


def dig(day=None):
    day = day or datetime.datetime.now(CT).date().isoformat()
    d = json.load(open("data/nba_finder/pp_nba_full.json", encoding="utf-8"))
    P = {x["id"]: x["attributes"] for x in d["included"] if x["type"] == "new_player"}
    db = sqlite3.connect("sports.db", timeout=60)
    names = {B.norm(r[0]): r[0] for r in db.execute("select distinct player from nba_box where date >= '2024-10-01'")}
    lines = collections.defaultdict(list)
    for p in d["data"]:
        a = p["attributes"]
        if not a["start_time"].startswith(day) or a["stat_type"] not in NF.BOX:
            continue
        pl = P.get(p["relationships"]["new_player"]["data"]["id"], {}); nm = names.get(B.norm(pl.get("name")))
        if nm and "+" not in (pl.get("name") or ""):
            lines[(nm, ESPN.get(pl.get("team"), pl.get("team")), ESPN.get(a.get("description"), a.get("description")))].append((a["stat_type"], a["odds_type"], float(a["line_score"])))
    # 10/23 (user found Edey P+R vs a GSW team with no center): opponents whose last starting five had NO real big (reb/36 >= 9.5).
    # Measured 2 seasons: bigs vs those lineups +0.63 reb/36 (t=4.9, n=1,308); no points lift. Flag it + lift big-man rebound projections.
    import _nba_dunks as DK
    PR = DK.season_profiles(db); nobig = set()
    for t_, d_ in db.execute("select b.team, max(b.date) from nba_box b join nba_games g using(game_id) where g.season='2026-27' and g.stype='regular' group by b.team"):
        st5 = [r[0] for r in db.execute("select player from nba_box where team=? and date=? and starter=1", (t_, d_))]
        if st5 and not any(DK.is_big(PR.get(("2025-26", p_))) or DK.is_big(PR.get(("2024-25", p_))) for p_ in st5):
            nobig.add(t_)
    if nobig:
        print("OPPONENTS STARTING NO REAL BIG (bigs vs them +0.63 reb/36, measured): %s" % ", ".join(sorted(nobig)))
    out = []
    for (nm, tm, opp), L in lines.items():
        # 10/22 fix: preseason minutes are CAPPED for stars (Mitchell/Murray/SGA ~22) -> regular-season minutes first
        reg = [m[0] for m in db.execute("select b.min from nba_box b join nba_games g using(game_id) where b.player=? and b.date >= '2026-10-01' and b.min > 0 and g.stype='regular' order by b.date", (nm,))]
        pre = [m[0] for m in db.execute("select b.min from nba_box b join nba_games g using(game_id) where b.player=? and b.date >= '2026-10-01' and b.min > 0 and g.stype='pre' order by b.date", (nm,))]
        last = [m[0] for m in db.execute("select b.min from nba_box b join nba_games g using(game_id) where b.player=? and b.team=? and b.min > 0 and g.stype in ('regular','post','play-in') and b.date between '2025-10-01' and '2026-08-01' order by b.date", (nm, tm))]
        if reg:
            exp_min = st.mean(reg)
        elif last and st.mean(last[-10:]) >= 26:
            exp_min = st.mean(last[-10:])                                       # established starter: last season's role, not capped preseason
        elif pre or last:
            exp_min = max(st.mean(pre) if pre else 0, st.mean(last[-10:]) if last else 0)
        else:
            continue
        for stat, kind, ln in L:
            e = NF.re.sub(r"\b([a-z]+)\b", r"b.\1", NF.BOX[stat])
            G = db.execute("select b.date, b.team, b.opp, b.min, %s from nba_box b join nba_games g using(game_id) where b.player=? and b.min > 0 "
                           "and g.stype in ('regular','post','play-in') and b.date between '2024-10-01' and '2026-08-01' order by b.date" % e, (nm,)).fetchall()
            same = [g for g in G if g[1] == tm]                                   # current team only (new-team trap)
            band = [g for g in same if abs(g[3] - exp_min) <= 4]
            if len(band) < 8:
                continue
            v = [g[4] for g in band]
            per_min = sum(g[4] for g in same) / max(sum(g[3] for g in same), 1)
            proj = per_min * exp_min
            if opp in nobig and "Reb" in stat and DK.is_big(PR.get(("2025-26", nm)) or PR.get(("2024-25", nm))):
                proj += 0.63 * exp_min / 36                         # no-big opponent lift (rebounds only)
            this = [r[0] for r in db.execute("select %s from nba_box b where b.player=? and b.date >= '2026-10-01' and b.min > 0 order by b.date" % e, (nm,))]
            h2h = [g[4] for g in same if g[2] == opp]
            sides = ["over"] if kind in ("goblin", "demon") else ["over", "under"]
            for side in sides:
                D = [x for x in v if x != ln]
                if not D:
                    continue
                r = sum((x > ln) if side == "over" else (x < ln) for x in D) / len(D)
                rt = (sum((x > ln) if side == "over" else (x < ln) for x in this) / len(this)) if this else None
                rh = (sum((x > ln) if side == "over" else (x < ln) for x in h2h if x != ln) / max(len([x for x in h2h if x != ln]), 1)) if h2h else None
                bar = .85 if kind == "goblin" else (.55 if kind == "demon" else .70)
                if r >= bar and (rt is None or rt >= .6) and (rh is None or rh >= .5):
                    out.append((r, nm, tm, opp, stat, kind, side, ln, len(v), exp_min, proj, this[-5:], h2h[-4:], rt, rh))
    out.sort(key=lambda x: ({"standard": 0, "demon": 1, "goblin": 2}[x[5]], -x[0]))
    print("MINUTES DIG %s -- lines where his games at TONIGHT's minutes (current team) clear the bar (std 70%%, demon 55%%, goblin 85%%)" % day)
    for r, nm, tm, opp, stat, kind, side, ln, n, em, pj, th, hh, rt, rh in out:
        print("  %-8s %-22s %-4s v %-4s %-20s %-5s %5g | at ~%.0f min: %3.0f%% (n=%d) | proj %.1f | 2026 %s | h2h %s%s"
              % (kind.upper(), nm[:22], tm, opp, stat[:20], side, ln, em, 100 * r, n, pj, th, hh, "  [OPP NO BIG]" if opp in nobig else ""))
    return out


if __name__ == "__main__":
    dig(sys.argv[1] if len(sys.argv) > 1 else None)
