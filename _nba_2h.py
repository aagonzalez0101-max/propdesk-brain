"""NBA SECOND-HALF MODEL (10/24, user: "can we make a model for 2H lines? usually points, PRA or fantasy"). PrizePicks posts NBA2H lines
(league 80) AT HALFTIME, so the model uses what the first half already showed.

Per player-game (2024-25 on, regular season), from data we already keep:
    nba_qtr   points / rebounds / assists by quarter (1H = Q1-2, 2H = Q3, Q4 and OT)
    nba_stints  seconds on the floor by half (lineup rebuild)          nba_pbp.db events  first-half personal fouls
    nba_box   steals / blocks / turnovers (full game; split by the share of minutes played in the 2H, for fantasy)
Features at halftime:
    base   his own average 2H output over his previous 20 games (no peeking)
    h1     what he did in this game's first half;  m1  1H minutes vs his usual 1H minutes
    margin halftime score margin (his team's lead, absolute and signed);  fouls  1H personal fouls
Model: least squares per stat, trained on 2024-25, tested out-of-sample on 2025-26 (+ 2026-27 so far).

    python _nba_2h.py test            # walk-forward accuracy vs "just his average" + how each feature moves the 2H
    python _nba_2h.py live            # every NBA2H line on PrizePicks right now -> projection, P(over), HIGHER/LOWER
"""
import sys, os, json, sqlite3, collections, statistics as st, math, datetime, urllib.request
import numpy as np

DB, PBP = "sports.db", "nba_pbp.db"
PAPER = "nba_2h_paper.jsonl"
CT = datetime.timezone(datetime.timedelta(hours=-5))
STATS = {"Points": lambda h: h["pts"], "Pts+Rebs+Asts": lambda h: h["pts"] + h["reb"] + h["ast"],
         "Fantasy Score": lambda h: h["pts"] + 1.2 * h["reb"] + 1.5 * h["ast"] + h["def"]}
FEATS = ["base", "h1", "m1d", "lead", "absm", "fouls", "base_x_absm", "h1_vs_his_1h"]   # 10/24: +1H vs his own normal 1H (60%+ calls +1 pt)


def table():
    """one row per player-game with 1H and 2H stats, minutes by half, halftime margin, 1H fouls"""
    c = sqlite3.connect(DB, timeout=60)
    box = {}
    for gid, pid, pl, tm, date, season, mn, stl, blk, tov, starter in c.execute(
            "select b.game_id, b.player_id, b.player, b.team, b.date, g.season, b.min, b.stl, b.blk, b.tov, b.starter from nba_box b join nba_games g using(game_id) "
            "where g.stype='regular' and g.season in ('2024-25','2025-26','2026-27') and b.min > 0"):
        box[(gid, pid)] = dict(player=pl, team=tm, date=date, season=season, min=mn, stl=stl or 0, blk=blk or 0, tov=tov or 0, starter=starter)
    half = collections.defaultdict(lambda: [dict(pts=0, reb=0, ast=0), dict(pts=0, reb=0, ast=0)])
    for gid, pid, per, pts, reb, ast in c.execute("select game_id, player_id, period, pts, reb, ast from nba_qtr"):
        if (gid, pid) in box:
            h = half[(gid, pid)][0 if per <= 2 else 1]
            h["pts"] += pts or 0; h["reb"] += reb or 0; h["ast"] += ast or 0
    secs = collections.defaultdict(lambda: [0.0, 0.0])
    for gid, per, t0, t1, unit in c.execute("select game_id, period, t0, t1, unit from nba_stints"):
        for nm in unit.split("|"):
            secs[(gid, nm)][0 if per <= 2 else 1] += t1 - t0
    team1h = collections.defaultdict(float)
    for (gid, pid), h in half.items():
        team1h[(gid, box[(gid, pid)]["team"])] += h[0]["pts"]
    teams = collections.defaultdict(set)
    for (gid, pid), b in box.items():
        teams[gid].add(b["team"])
    fouls = collections.Counter()
    if os.path.exists(PBP):
        for gid, pl in sqlite3.connect(PBP).execute("select game_id, player from nba_events where kind in ('foul','shooting_foul') and period <= 2"):
            fouls[(gid, pl)] += 1
    rows = []
    for (gid, pid), (h1, h2) in half.items():
        b = box[(gid, pid)]; s1, s2 = secs.get((gid, b["player"]), (0.0, 0.0))
        if s1 + s2 < 60:
            continue
        opp = [t for t in teams[gid] if t != b["team"]]
        if not opp:
            continue
        share2 = s2 / (s1 + s2)
        d = 3 * b["stl"] + 3 * b["blk"] - b["tov"]
        h1["def"] = d * (1 - share2); h2["def"] = d * share2
        rows.append(dict(gid=gid, date=b["date"], season=b["season"], player=b["player"], team=b["team"], starter=b["starter"], h1=dict(h1), h2=dict(h2),
                         m1=s1 / 60, m2=s2 / 60, lead=team1h[(gid, b["team"])] - team1h[(gid, opp[0])], fouls=fouls[(gid, b["player"])]))
    rows.sort(key=lambda r: r["date"])
    return rows


def featurize(rows, stat):
    f = STATS[stat]
    hist = collections.defaultdict(list)            # player -> [(2H value, 1H minutes)] of PRIOR games
    X, y, meta = [], [], []
    for r in rows:
        H = hist[r["player"]]
        if len(H) >= 8:
            base = st.mean(v for v, _, _ in H[-20:]); m1n = st.mean(m for _, m, _ in H[-20:]); b1 = st.mean(u for _, _, u in H[-20:])
            absm = abs(r["lead"])
            X.append([base, f(r["h1"]), r["m1"] - m1n, r["lead"], absm, r["fouls"], base * absm / 10, f(r["h1"]) - b1])
            y.append(f(r["h2"])); meta.append(r)
        H.append((f(r["h2"]), r["m1"], f(r["h1"])))
    return np.array(X), np.array(y), meta


def fit(X, y):
    A = np.column_stack([np.ones(len(X)), X])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    return coef


def predict(coef, X):
    return np.column_stack([np.ones(len(X)), X]) @ coef


def test():
    rows = table()
    print("player-games with halves: %d (%s)" % (len(rows), dict(collections.Counter(r["season"] for r in rows))))
    out = {}
    for stat in STATS:
        X, y, meta = featurize(rows, stat)
        tr = np.array([m["season"] == "2024-25" for m in meta]); te = ~tr
        coef = fit(X[tr], y[tr]); p = predict(coef, X[te])
        base = X[te][:, 0]
        mae, mae_b = np.mean(np.abs(p - y[te])), np.mean(np.abs(base - y[te]))
        res = y[te] - p
        # direction test: line at his own 2H average (where PP roughly sets it) -> how often does the model's side win?
        line = np.round(base * 2) / 2 + 0.25 * np.sign(np.round(base * 2) / 2 - base + 1e-9) * 0 + 0.0
        line = np.floor(base) + 0.5
        side_over = p > line; hit = np.where(side_over, y[te] > line, y[te] < line)
        big = np.abs(p - line) >= 0.12 * np.maximum(line, 1)
        print("\n== %s  (test n=%d, 2025-26 + 2026-27)" % (stat, te.sum()))
        print("   avg error: model %.2f vs 'his 2H average' %.2f  (%.0f%% better)" % (mae, mae_b, 100 * (1 - mae / mae_b)))
        print("   at a line = his 2H average: model side wins %.1f%% of all lines, %.1f%% when the model is 12%%+ off the line (n=%d)"
              % (100 * hit.mean(), 100 * hit[big].mean(), big.sum()))
        print("   2H moves per unit:  1H %+.2f | 1H min vs usual %+.2f/min | lead %+.2f/pt | |margin| %+.2f/pt | 1H fouls %+.2f | base x margin %+.2f | 1H vs his normal %+.2f"
              % tuple(coef[2:9]))
        out[stat] = dict(coef=coef.tolist(), sd=float(np.std(res)), q=np.quantile(res, np.linspace(0.01, 0.99, 99)).tolist())
    json.dump(out, open("nba_2h_model.json", "w"))
    # refit on everything for live use
    for stat in STATS:
        X, y, _ = featurize(rows, stat)
        out[stat]["coef_all"] = fit(X, y).tolist()
    json.dump(out, open("nba_2h_model.json", "w"))
    print("\nsaved nba_2h_model.json (live uses the all-seasons fit + test-set residuals)")


def p_over(stat, proj, line, M):
    q = np.array(M[stat]["q"])                     # empirical residual quantiles from the out-of-sample test
    return float(np.mean(proj + q > line))


def live():
    import _ppcache, _nba_board as B
    M = json.load(open("nba_2h_model.json"))
    d = _ppcache.projections(80, 120)
    PL = {x["id"]: x["attributes"] for x in d["included"] if x["type"] == "new_player"}
    rows = table()
    hist = collections.defaultdict(list)
    for r in rows:
        hist[r["player"]].append(r)
    names = {B.norm(p): p for p in hist}
    sb = json.load(urllib.request.urlopen("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard", timeout=30))
    livebox = {}
    for e in sb["events"]:
        det = e["status"]["type"]["detail"]
        if "Halftime" not in det and not ("End of 2nd" in det):
            if e["status"]["type"].get("state") == "in":
                print("  waiting for halftime: %s (%s)" % (e["shortName"], det))
            continue                                                  # 10/24: a 1Q box read as a "1H" made every line a fake 90% LOWER
        comp = e["competitions"][0]; score = {c["team"]["abbreviation"]: float(c.get("score") or 0) for c in comp["competitors"]}
        s = json.load(urllib.request.urlopen("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=" + e["id"], timeout=30))
        for t in s["boxscore"].get("players", []):
            ab = t["team"]["abbreviation"]; opp = [k for k in score if k != ab]
            stt = t["statistics"][0]
            for a in stt["athletes"]:
                x = dict(zip(stt["labels"], a["stats"]))
                if not x.get("MIN") or x["MIN"] in ("--", "0"):
                    continue
                g = lambda k: float(x.get(k)) if str(x.get(k) or "").replace(".", "", 1).isdigit() else 0.0   # ESPN shows '-' for none
                livebox[B.norm(a["athlete"]["displayName"])] = dict(h1=dict(pts=g("PTS"), reb=g("REB"), ast=g("AST"), def_=3 * g("STL") + 3 * g("BLK") - g("TO")),
                                                                    m1=g("MIN"), fouls=g("PF"), lead=score[ab] - score[opp[0]] if opp else 0, status=e["status"]["type"]["detail"])
    print("NBA 2H LINES on PrizePicks: %d | live boxes: %d players" % (len(d["data"]), len(livebox)))
    out = []
    for p in d["data"]:
        a = p["attributes"]; stat = a["stat_type"]
        if stat not in STATS or a.get("odds_type") != "standard":
            continue
        pl = PL.get(p["relationships"]["new_player"]["data"]["id"], {}); nm = names.get(B.norm(pl.get("name")))
        lb = livebox.get(B.norm(pl.get("name")))
        if not nm or not lb or len(hist[nm]) < 8:
            continue
        f = STATS[stat]; H = hist[nm][-20:]
        base = st.mean(f(r["h2"]) for r in H); m1n = st.mean(r["m1"] for r in H); b1 = st.mean(f(r["h1"]) for r in H)
        h1 = dict(lb["h1"]); h1["def"] = h1.pop("def_") * 0.5
        absm = abs(lb["lead"])
        xv = np.array([[base, f(h1), lb["m1"] - m1n, lb["lead"], absm, lb["fouls"], base * absm / 10, f(h1) - b1]])
        proj = float(predict(np.array(M[stat]["coef_all"]), xv)[0]); ln = float(a["line_score"])
        po = p_over(stat, proj, ln, M)
        proj = proj + M[stat]["q"][49]                                # 10/24: show his TYPICAL (median) 2H, which always agrees with the call
        out.append((max(po, 1 - po), pl.get("name"), pl.get("team"), stat, ln, proj, po, base, f(h1), lb["m1"], lb["lead"], lb["fouls"], lb["status"]))
    out.sort(reverse=True)
    day = datetime.datetime.now(CT).date().isoformat()                 # 10/24: archive every 2H line seen -> graded nightly (the real edge test)
    seen = set()
    if os.path.exists(PAPER):
        seen = {(r["day"], r["player"], r["stat"], r["line"]) for r in map(json.loads, open(PAPER, encoding="utf-8"))}
    with open(PAPER, "a", encoding="utf-8") as fo:
        for conf, nm, tm, stat, ln, proj, po, base, h1v, m1, lead, fl, status in out:
            if (day, nm, stat, ln) not in seen:
                fo.write(json.dumps(dict(day=day, player=nm, team=tm, stat=stat, line=ln, proj=round(proj, 2), p_over=round(po, 3), base=round(base, 2),
                                         h1=h1v, m1=m1, lead=lead, fouls=fl, result=None)) + chr(10))
    for conf, nm, tm, stat, ln, proj, po, base, h1v, m1, lead, fl, status in out:
        side = "HIGHER" if po >= 0.5 else "LOWER"
        print("  %-22s %-4s %-14s %5g -> proj %5.1f  %s %3.0f%% | 2H avg %.1f, 1H %.0f in %.0f min, lead %+.0f, %d PF | %s"
              % (nm[:22], tm, stat[:14], ln, proj, side, 100 * conf, base, h1v, m1, lead, fl, status))
    return out


def grade():
    """settle logged 2H lines from nba_qtr (Q3 + Q4 + OT); fantasy adds 2H share of steals/blocks/turnovers by minutes"""
    if not os.path.exists(PAPER):
        return
    c = sqlite3.connect(DB, timeout=60)
    R = [json.loads(l) for l in open(PAPER, encoding="utf-8")]
    for r in R:
        if r.get("result"):
            continue
        q = c.execute("""select sum(case when q.period>=3 then q.pts else 0 end), sum(case when q.period>=3 then q.reb else 0 end),
                                sum(case when q.period>=3 then q.ast else 0 end), b.stl, b.blk, b.tov, b.min
                         from nba_box b join nba_qtr q on q.game_id=b.game_id and q.player_id=b.player_id where b.player=? and b.date between ? and date(?, '+1 day')""",
                      (r["player"], r["day"], r["day"])).fetchone()
        if not q or q[0] is None:
            continue
        pts, reb, ast, stl, blk, tov, mn = q
        share2 = max(0.0, min(1.0, ((mn or 0) - r.get("m1", 0)) / max(mn or 1, 1)))
        v = {"Points": pts, "Pts+Rebs+Asts": pts + reb + ast, "Fantasy Score": pts + 1.2 * reb + 1.5 * ast + share2 * (3 * (stl or 0) + 3 * (blk or 0) - (tov or 0))}[r["stat"]]
        r["actual"] = round(v, 1)
        r["result"] = "P" if v == r["line"] else ("W" if (v > r["line"]) == (r["p_over"] >= 0.5) else "L")
    open(PAPER, "w", encoding="utf-8").write("".join(json.dumps(r) + chr(10) for r in R))
    g = [r for r in R if r.get("result") in ("W", "L")]
    for lab, sub in (("all", g), ("60%+", [r for r in g if max(r["p_over"], 1 - r["p_over"]) >= .60]), ("unders", [r for r in g if r["p_over"] < .5]),
                     ("overs", [r for r in g if r["p_over"] >= .5])):
        if sub:
            print("2H paper %-7s %d-%d (%.0f%%)" % (lab, sum(r["result"] == "W" for r in sub), sum(r["result"] == "L" for r in sub), 100 * st.mean(r["result"] == "W" for r in sub)))


def check(player, day, stat, line):
    """10/24: replay a past 2H line -- the halftime picture from our data, the model's call, and what actually happened"""
    import _nba_board as B
    M = json.load(open("nba_2h_model.json")); rows = table(); f = STATS[stat]
    names = {B.norm(r["player"]): r["player"] for r in rows}
    nm = names.get(B.norm(player))
    H = [r for r in rows if r["player"] == nm]
    g = [r for r in H if r["date"][:10] in (day, (datetime.date.fromisoformat(day) + datetime.timedelta(days=1)).isoformat())]
    if not g:
        print("  %s: no game on %s in the DB" % (player, day)); return None
    r = g[0]; prior = [x for x in H if x["date"] < r["date"]][-20:]
    base = st.mean(f(x["h2"]) for x in prior); m1n = st.mean(x["m1"] for x in prior); b1 = st.mean(f(x["h1"]) for x in prior); absm = abs(r["lead"])
    xv = np.array([[base, f(r["h1"]), r["m1"] - m1n, r["lead"], absm, r["fouls"], base * absm / 10, f(r["h1"]) - b1]])
    proj = float(predict(np.array(M[stat]["coef_all"]), xv)[0]); po = p_over(stat, proj, line, M); act = f(r["h2"])
    proj += M[stat]["q"][49]                                          # typical (median) 2H
    call = "HIGHER" if po >= .5 else "LOWER"; res = "PUSH" if act == line else ("W" if (act > line) == (po >= .5) else "L")
    print("  %-20s %-14s %5g | 1H %.1f in %.0f min (usual 1H min %.0f), lead %+.0f, %d PF | 2H avg %.1f -> proj %.1f %s %.0f%% | actual 2H %.1f -> %s"
          % (nm, stat, line, f(r["h1"]), r["m1"], m1n, r["lead"], r["fouls"], base, proj, call, 100 * max(po, 1 - po), act, res))
    return res


if __name__ == "__main__":
    if sys.argv[1:2] == ["check"]:            # python _nba_2h.py check "Player" 2026-10-23 "Pts+Rebs+Asts" 14.5
        check(sys.argv[2], sys.argv[3], sys.argv[4], float(sys.argv[5])); sys.exit()
    if sys.argv[1:2] == ["grade"]:
        grade(); sys.exit()
    a = sys.argv[1:]
    test() if a[:1] == ["test"] else live() if a[:1] == ["live"] else print(__doc__)
