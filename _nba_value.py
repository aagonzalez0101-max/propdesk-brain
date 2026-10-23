"""NBA VALUE FINDER (10/23, user: "how can we find lines like Zubac 1.5 dunks or Edey -- I had to tell you, make it so you can do it").
Why the dig missed them: it kept only lines whose RAW history cleared 70%, and printed context tags after the cut. Both finds were
context the line didn't price:
    Zubac O1.5 dunks   DAL missing Lively + Aldama (measured: dunk bigs vs 20+ missing big min +0.28 dunks/g, t=3.6)
    Edey  O17.5 P+R    line cut 22.5 -> 17.5 off ONE 21-min game; 25.8 min / 24.7 P+R last season; GSW without Porzingis
Measured 10/23: a line CUT by itself is not value (cut 15%+ -> overs 48.7% vs flat 48.6%, n=6,000 archived lines) -- the finder
needs the REASON the line is wrong tonight, so every row carries its reasons.

For every PP line tonight:
  1. minutes  = this season's regular-season minutes SHRUNK to his established role (1-2 games never define a role):
                (n_reg * reg_mean + 4 * base) / (n_reg + 4), base = last season on this team (10+ games) else last season's last 20
  2. sample   = every 2025-26 / 2026-27 game (15+ min, current team when 10+ games) rescaled to tonight's minutes
  3. context  = measured lifts only: opponent missing bigs (injury report) / starting no big -> big rebounds +0.63/36, dunk bigs
                +0.28 dunks; opponent pace third (PRA/36 +0.95 fast, -0.65 slow); his OWN vs-small split x opp small share (half weight)
  4. p_raw (no context) and p_ctx (with it) vs the line; VALUE = p_ctx clears the bar AND a reason moved it there (context or minutes)

    python _nba_value.py [date]     # tonight's board -> VALUE / SOLID lists + nba_value_paper.jsonl
    python _nba_value.py grade      # grade paper rows once box scores land (nightly)
"""
import sys, json, re, sqlite3, datetime, collections, statistics as st, urllib.request
import _nba_board as B, _nba_finder as NF, _nba_dunks as DK

CT = datetime.timezone(datetime.timedelta(hours=-5))
ESPN = {"NYK": "NY", "GSW": "GS", "SAS": "SA", "NOP": "NO", "UTA": "UTAH", "WAS": "WSH"}
PAPER = "nba_value_paper.jsonl"
BAR = {"standard": .58, "demon": .50, "goblin": .85}       # std = 2-pick 3x break-even 57.7%
STATS = [s for s in NF.BOX if s != "Fantasy Score"] + ["Fantasy Score", "Dunks"]


def val(row, stat):
    """row = dict of box cols + dunks"""
    if stat == "Dunks":
        return row["dunks"]
    return eval(NF.BOX[stat], {}, row)


def bigprof(P, nm):
    """his big-man profile from the last season he qualified (Lively played 7 games in 2025-26 -> use 2024-25)"""
    for se in ("2025-26", "2024-25"):
        if DK.is_big(P.get((se, nm))):
            return P[(se, nm)]
    return None


def injuries_big_out(P, team_of):
    """tonight: team -> [(big, min)] OUT/doubtful (2025-26 bigs, 15+ min)"""
    out = collections.defaultdict(list)
    try:
        d = json.load(urllib.request.urlopen(urllib.request.Request("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries",
                                                                    headers={"User-Agent": "Mozilla/5.0"}), timeout=30))
    except Exception as e:
        print("(injuries: %s)" % e); return out
    for t in d.get("injuries", []):
        for i in t.get("injuries", []):
            nm = i["athlete"]["displayName"]; p = bigprof(P, nm)
            if p and (i.get("status") or "").lower() in ("out", "doubtful") and team_of.get(nm):
                out[team_of[nm]].append((nm, round(p["min"])))
    return out


def board(day):
    d = json.load(open("data/nba_finder/pp_nba_full.json", encoding="utf-8"))
    P = {x["id"]: x["attributes"] for x in d["included"] if x["type"] == "new_player"}
    L = []
    for p in d["data"]:
        a = p["attributes"]; pl = P.get(p["relationships"]["new_player"]["data"]["id"], {})
        if not a["start_time"].startswith(day) or a["stat_type"] not in STATS or "+" in (pl.get("name") or ""):
            continue
        L.append((pl.get("name"), ESPN.get(pl.get("team"), pl.get("team")), ESPN.get(a.get("description"), a.get("description")),
                  a["stat_type"], a["odds_type"], float(a["line_score"]), a["start_time"]))
    return L


def run(day=None):
    day = day or datetime.datetime.now(CT).date().isoformat()
    db = sqlite3.connect("sports.db", timeout=60)
    lines = board(day)
    names = {B.norm(r[0]): r[0] for r in db.execute("select distinct player from nba_box where date >= '2024-10-01'")}
    want = {names.get(B.norm(x[0])) for x in lines} - {None}
    # one pass over the DB for every player on the board (was one query per line)
    G = collections.defaultdict(list)
    dk = {(g, p): v for g, p, v in db.execute("select game_id, player_id, sum(dunks) from nba_qtr where game_id in "
                                             "(select game_id from nba_games where season in ('2025-26','2026-27')) group by 1, 2")}
    cols = ["game_id", "date", "team", "opp", "player_id", "player", "min", "fgm", "fga", "tpm", "tpa", "ftm", "fta", "oreb", "dreb", "reb",
            "ast", "stl", "blk", "tov", "pf", "pts"]
    for r in db.execute("select %s, g.stype, g.season from nba_box b join nba_games g using(game_id) where b.min > 0 and b.date < ? "
                        "and g.season in ('2024-25','2025-26','2026-27') and g.stype in ('regular','post','play-in')" % ",".join("b." + c for c in cols), (day,)):
        if r[5] in want:
            x = dict(zip(cols + ["stype", "season"], r)); x["dunks"] = dk.get((x["game_id"], x["player_id"]), 0) or 0
            G[x["player"]].append(x)
    PR = DK.season_profiles(db)
    team_of = {}
    for pl, tm in db.execute("select player, team from nba_box where date >= '2025-10-01' order by date"):
        team_of[pl] = tm
    big_out = injuries_big_out(PR, team_of)
    nobig = set()                                               # last starting five had no real big
    for t_, d_ in db.execute("select b.team, max(b.date) from nba_box b join nba_games g using(game_id) where g.season='2026-27' and g.stype='regular' group by b.team"):
        st5 = [r[0] for r in db.execute("select player from nba_box where team=? and date=? and starter=1", (t_, d_))]
        if st5 and not any(DK.is_big(PR.get(("2025-26", p_))) or DK.is_big(PR.get(("2024-25", p_))) for p_ in st5):
            nobig.add(t_)
    pc = collections.defaultdict(list)
    for se_, h_, a_, ps_ in db.execute("select season, home, away, poss from nba_games where stype='regular' and poss is not null and season in ('2025-26','2026-27')"):
        pc[(se_, h_)].append(ps_); pc[(se_, a_)].append(ps_)
    pace = {}
    for (se_, t_), v_ in sorted(pc.items()):
        if se_ == "2025-26" or len(v_) >= 10:
            pace[t_] = st.mean(v_)
    pv = sorted(pace.values()); lo_p, hi_p = pv[len(pv) // 3], pv[2 * len(pv) // 3]
    small_share = {t_: (sm_ / tot_ if tot_ else 0) for t_, sm_, tot_ in db.execute(
        "select team, sum(case when small=1 then t1-t0 else 0 end), sum(t1-t0) from nba_stints where season in ('2025-26','2026-27') group by team")}
    vs_small = {}
    for pl, o_, s_, rb, pt in db.execute("select player, opp_small, sum(secs), sum(reb), sum(pts) from nba_stint_stats group by 1, 2"):
        vs_small.setdefault(pl, {})[o_] = (s_, rb, pt)
    # previous game's standard line per player/stat (shows the cut / raise; NOT a signal by itself -- measured)
    prev = {}
    try:
        for pl, stt, ln in sqlite3.connect("lines.db", timeout=60).execute(
                "select player, stat, line from pp where league=7 and kind='standard' and start < ? order by start, last_seen", (day,)):
            prev[(pl, stt)] = ln
    except Exception:
        pass

    out = []
    for nm_pp, tm, opp, stat, kind, ln, start in lines:
        nm = names.get(B.norm(nm_pp))
        if not nm or not G.get(nm):
            continue
        g = sorted(G[nm], key=lambda x: x["date"])
        reg = [x["min"] for x in g if x["season"] == "2026-27" and x["stype"] == "regular"]
        lastT = [x["min"] for x in g if x["season"] == "2025-26" and x["team"] == tm]
        lastA = [x["min"] for x in g if x["season"] == "2025-26"]
        base = st.mean(lastT[-20:]) if len(lastT) >= 10 else (st.mean(lastA[-20:]) if lastA else None)
        if base is None and not reg:
            continue
        exp_min = (len(reg) * st.mean(reg) + 4 * base) / (len(reg) + 4) if base is not None and reg else (base if base is not None else st.mean(reg))
        if reg:
            exp_min = min(exp_min, st.mean(reg[-3:]))          # 10/23: never project MORE minutes than he is getting now (Edey is 21 every game)
        S = [x for x in g if x["season"] in ("2025-26", "2026-27") and x["min"] >= 15]
        same = [x for x in S if x["team"] == tm]
        S = same if len(same) >= 10 else S
        if len(S) < 10:
            continue
        v = [val(x, stat) * exp_min / x["min"] for x in S]
        # context deltas (per game at tonight's minutes)
        why, delta = [], 0.0
        prof = bigprof(PR, nm)
        big = prof is not None
        out_min = sum(m for _, m in big_out.get(opp, []))
        if big and (out_min >= 20 or opp in nobig):
            why.append("OPP NO BIG (%s)" % (", ".join(n for n, _ in big_out.get(opp, [])) or "starts small"))
            if "Reb" in stat or stat == "Fantasy Score":
                delta += 0.63 * exp_min / 36 * (1.2 if stat == "Fantasy Score" else 1)
            if stat == "Dunks" and out_min >= 20 and prof and prof["dk"] >= .8:
                delta += 0.28
        tier = "FAST" if pace.get(opp, 0) >= hi_p else ("SLOW" if pace.get(opp, 1e9) <= lo_p else None)
        if tier and stat in ("Points", "Rebounds", "Assists", "Pts+Rebs+Asts", "Pts+Rebs", "Pts+Asts", "Rebs+Asts", "Fantasy Score"):
            pra = st.mean(x["pts"] + x["reb"] + x["ast"] for x in S) or 1
            share = st.mean(val(x, stat) for x in S) / pra
            delta += (0.95 if tier == "FAST" else -0.65) * exp_min / 36 * share
            why.append("OPP %s pace" % tier)
        vsm = vs_small.get(nm, {})
        if small_share.get(opp, 0) >= .5 and vsm.get(1) and vsm.get(0) and vsm[1][0] >= 6000:
            d_reb = 2160 * (vsm[1][1] / vsm[1][0] - vsm[0][1] / vsm[0][0]); d_pts = 2160 * (vsm[1][2] / vsm[1][0] - vsm[0][2] / vsm[0][0])
            k = 0.5 * small_share[opp] * exp_min / 36
            add = k * ((d_reb if "Reb" in stat else 0) + (d_pts if ("Pts" in stat or stat == "Points") else 0))
            if abs(add) >= .3:
                delta += add; why.append("OPP SMALL %.0f%% (his reb/36 %+.1f pts/36 %+.1f)" % (100 * small_share[opp], d_reb, d_pts))
        l3 = [x["min"] for x in g if x["season"] == "2026-27"][-3:]
        if reg and exp_min - st.mean(reg) >= 3:
            why.append("note: %.0f min now vs %.0f last season (projected at %.0f)" % (st.mean(reg), base, exp_min))
        pl_prev = prev.get((nm_pp, stat))
        sides = ["over"] if kind in ("goblin", "demon") else ["over", "under"]
        for side in sides:
            D = [(x, x + delta) for x in v if round(x, 6) != ln]
            if not D:
                continue
            hit = (lambda y: y > ln) if side == "over" else (lambda y: y < ln)
            p_raw = sum(hit(a) for a, _ in D) / len(D); p_ctx = sum(hit(b) for _, b in D) / len(D)
            proj = st.median(v) + delta
            reasons = why
            tagged = (side == "over" and delta > 0 or side == "under" and delta < 0) and p_ctx - p_raw >= .08   # a MEASURED context moved it 8+ pts (Zubac +12, Edey +27; pace alone rarely does)
            if p_ctx >= BAR[kind]:
                out.append(dict(day=day, player=nm, team=tm, opp=opp, stat=stat, kind=kind, side=side, line=ln, p_raw=round(p_raw, 3),
                                p_ctx=round(p_ctx, 3), proj=round(proj, 1), exp_min=round(exp_min, 1), n=len(D), why=reasons,
                                tier="VALUE" if tagged else "SOLID", prev_line=pl_prev, start=start))
    out.sort(key=lambda r: (r["tier"] != "VALUE", {"standard": 0, "demon": 1, "goblin": 2}[r["kind"]], -(r["p_ctx"] - BAR[r["kind"]])))
    print("NBA VALUE FINDER %s -- %d lines clear the bar (std %.0f%% / demon %.0f%% / goblin %.0f%%, rescaled to tonight's minutes)"
          % (day, len(out), 100 * BAR["standard"], 100 * BAR["demon"], 100 * BAR["goblin"]))
    print("bigs OUT tonight: %s" % "; ".join("%s %s" % (t, ", ".join(n for n, _ in L)) for t, L in big_out.items()))
    for tier in ("VALUE", "SOLID"):
        R = [r for r in out if r["tier"] == tier]
        print("\n== %s (%d)%s" % (tier, len(R), " -- a measured context moved it 8+ pts over the bar" if tier == "VALUE" else " -- clears on his own numbers, no new reason"))
        for r in R[:80 if tier == "VALUE" else 20]:
            print("  %-8s %-22s %-4s v %-4s %-20s %-5s %5g%s | %3.0f%% (raw %3.0f%%) proj %5.1f @%2.0f min n=%d | %s"
                  % (r["kind"].upper(), r["player"][:22], r["team"], r["opp"], r["stat"][:20], r["side"], r["line"],
                     " (was %g)" % r["prev_line"] if r["prev_line"] and r["prev_line"] != r["line"] and r["kind"] == "standard" else "",
                     100 * r["p_ctx"], 100 * r["p_raw"], r["proj"], r["exp_min"], r["n"], "; ".join(r["why"])))
    seen = set()
    try:
        seen = {(x["day"], x["player"], x["stat"], x["kind"], x["side"], x["line"]) for x in map(json.loads, open(PAPER, encoding="utf-8"))}
    except FileNotFoundError:
        pass
    with open(PAPER, "a", encoding="utf-8") as f:
        for r in out:
            k = (r["day"], r["player"], r["stat"], r["kind"], r["side"], r["line"])
            if k not in seen:
                f.write(json.dumps(r) + "\n"); seen.add(k)
    return out


def grade():
    db = sqlite3.connect("sports.db", timeout=60)
    R = [json.loads(l) for l in open(PAPER, encoding="utf-8")]
    cols = ["min", "fgm", "fga", "tpm", "tpa", "ftm", "fta", "oreb", "dreb", "reb", "ast", "stl", "blk", "tov", "pf", "pts"]
    n = 0
    for r in R:
        if r.get("result"):
            continue
        x = db.execute("select %s, (select sum(dunks) from nba_qtr q where q.game_id=b.game_id and q.player_id=b.player_id) from nba_box b "
                       "where player=? and date=?" % ",".join("b." + c for c in cols), (r["player"], r["day"])).fetchone()
        if not x:
            continue
        if not x[0]:
            r["result"] = "DNP"; continue
        row = dict(zip(cols, x)); row["dunks"] = x[-1] or 0
        a = val(row, r["stat"]); r["actual"] = a
        r["result"] = "P" if a == r["line"] else ("W" if (a > r["line"]) == (r["side"] == "over") else "L"); n += 1
    with open(PAPER, "w", encoding="utf-8") as f:
        for r in R:
            f.write(json.dumps(r) + "\n")
    agg = collections.defaultdict(lambda: [0, 0])
    for r in R:
        if r.get("result") in ("W", "L"):
            for k in (r["tier"], "%s %s" % (r["tier"], r["kind"]), "%s %s" % (r["tier"], r["side"])):
                agg[k][0] += r["result"] == "W"; agg[k][1] += 1
    print("VALUE FINDER paper: graded %d new" % n)
    for k in sorted(agg):
        w, t = agg[k]; print("  %-18s %d-%d (%.0f%%)" % (k, w, t - w, 100 * w / t))


if __name__ == "__main__":
    a = sys.argv[1:]
    grade() if a[:1] == ["grade"] else run(a[0] if a else None)
