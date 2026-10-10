"""PROP DESK v2 -- player pages for every line on the boards (2026-09-30). PickFinder-style, every sport, one file.

    python _site_players.py            # all sports -> site/players.json
    python _site_players.py WNBA NHL   # some sports (others kept from the last build)

Per player: game logs (date, opponent, home, minutes, stats), tonight's app lines (UD multipliers + PP), and a READ per line:
  * MODEL read  = our screen's call + probability from legs/<day>_<sport>.json (the same numbers the slip builder uses)
  * QUICK read  = season average x opponent defense-vs-position factor (half weight), empirical hit rate. Never a BET by
                  itself -- it is labelled as unvalidated on the page.
Per sport: defense vs position (what each team ALLOWS per game to each position, season / last 15 / last 7, rank 1 =
toughest), team offense vs defense ranks, and for WNBA shot zones allowed (from the ESPN shot data in site/data.json).
"""
import sys, os, json, csv, math, sqlite3, datetime, statistics as st, re, unicodedata, urllib.request
from collections import defaultdict

DAY = datetime.date.today().isoformat()
OUT = os.path.join("site", "players.json")
norm = lambda s: re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())
UA = {"User-Agent": "Mozilla/5.0"}
getj = lambda u: json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40).read())

# --------------------------------------------------------------------------------------------- stat definitions
# key -> (label, tab, parts)   parts = the raw stat keys summed
WNBA_STATS = {"pts": ("Points", "PTS", ["pts"]), "reb": ("Rebounds", "REB", ["reb"]), "ast": ("Assists", "AST", ["ast"]),
              "tpm": ("3-Pointers Made", "3PM", ["tpm"]), "pra": ("Pts + Rebs + Asts", "PRA", ["pts", "reb", "ast"]),
              "pr": ("Points + Rebounds", "PR", ["pts", "reb"]), "pa": ("Points + Assists", "PA", ["pts", "ast"]),
              "ra": ("Rebounds + Assists", "RA", ["reb", "ast"])}
MLB_H = {"h": ("Hits", "H", ["h"]), "tb": ("Total Bases", "TB", ["tb"]), "hrr": ("Hits + Runs + RBIs", "H+R+RBI", ["h", "r", "rbi"]),
         "r": ("Runs", "R", ["r"]), "rbi": ("RBIs", "RBI", ["rbi"]), "k": ("Strikeouts", "K", ["k"]), "bb": ("Walks", "BB", ["bb"]),
         "s1": ("Singles", "1B", ["s1"])}
MLB_P = {"pk": ("Strikeouts", "K", ["pk"]), "outs": ("Pitching Outs", "OUTS", ["outs"]), "er": ("Earned Runs Allowed", "ER", ["er"]),
         "ha": ("Hits Allowed", "H ALLOWED", ["ha"]), "bba": ("Walks Allowed", "BB ALLOWED", ["bba"])}
NHL_S = {"sog": ("Shots on Goal", "SOG", ["sog"]), "pts": ("Points", "PTS", ["points"]), "g": ("Goals", "G", ["goals"]),
         "a": ("Assists", "A", ["assists"]), "hits": ("Hits", "HITS", ["hits"]), "blk": ("Blocked Shots", "BLK", ["blocks"])}
NHL_G = {"sv": ("Saves", "SAVES", ["saves"]), "ga": ("Goals Against", "GA", ["ga"])}
NFL_S = {"pyd": ("Passing Yards", "PASS YDS", ["passing_yards"]), "patt": ("Pass Attempts", "ATT", ["attempts"]),
         "cmp": ("Completions", "CMP", ["completions"]), "ptd": ("Passing TDs", "PASS TD", ["passing_tds"]),
         "int": ("Interceptions", "INT", ["passing_interceptions"]), "ryd": ("Rushing Yards", "RUSH YDS", ["rushing_yards"]),
         "car": ("Rush Attempts", "CAR", ["carries"]), "rec": ("Receptions", "REC", ["receptions"]),
         "reyd": ("Receiving Yards", "REC YDS", ["receiving_yards"]), "rry": ("Rush + Rec Yards", "RUSH+REC", ["rushing_yards", "receiving_yards"])}
SOC_S = {"pas": ("Passes", "PASSES", ["passes"]), "sh": ("Shots", "SHOTS", ["shots"]), "sot": ("Shots on Target", "SOT", ["sot"]),
         "sv": ("Goalie Saves", "SAVES", ["saves"])}

# app stat name (normalized) -> our key, per sport
ALIAS = {
    "WNBA": {"points": "pts", "rebounds": "reb", "assists": "ast", "3pointersmade": "tpm", "3ptmade": "tpm", "ptsrebsasts": "pra",
             "pointsrebounds": "pr", "ptsrebs": "pr", "pointsassists": "pa", "ptsasts": "pa", "reboundsassists": "ra", "rebsasts": "ra"},
    "MLB_H": {"hits": "h", "totalbases": "tb", "hitsrunsrbis": "hrr", "runs": "r", "rbis": "rbi", "batterstrikeouts": "k",
              "hitterstrikeouts": "k", "batterwalks": "bb", "walks": "bb", "singles": "s1"},
    "MLB_P": {"strikeouts": "pk", "pitcherstrikeouts": "pk", "pitchingouts": "outs", "pitchingoutsrecorded": "outs", "outsrecorded": "outs",
              "earnedrunsallowed": "er", "hitsallowed": "ha", "walksallowed": "bba"},
    "NHL_S": {"shotsongoal": "sog", "points": "pts", "goals": "g", "assists": "a", "hits": "hits", "blockedshots": "blk"},
    "NHL_G": {"saves": "sv", "goaliesaves": "sv", "goalsagainst": "ga", "goalsallowed": "ga"},
    "NFL": {"passingyards": "pyd", "passyards": "pyd", "passattempts": "patt", "completions": "cmp", "passcompletions": "cmp",
            "passingtds": "ptd", "passtds": "ptd", "interceptions": "int", "int": "int", "interceptionsthrown": "int",
            "rushingyards": "ryd", "rushyards": "ryd", "rushingattempts": "car", "rushattempts": "car", "receptions": "rec",
            "receivingyards": "reyd", "rushrecyards": "rry", "rushrecyds": "rry", "rushingreceivingyards": "rry"},
    "SOCCER": {"passesattempted": "pas", "passes": "pas", "shots": "sh", "shotsontarget": "sot", "goaliesaves": "sv", "saves": "sv"},
}
BE_UD, BE_PP = 1 / 3.5 ** 0.5, 1 / 3.0 ** 0.5
CAL = json.load(open("calibration.json")) if os.path.exists("calibration.json") else {}


# --------------------------------------------------------------------------------------------- shared helpers
def dvp(games, pos_of, keys, season_filter=None, min_games=2):
    """games: list of rows dict(date, gid, team, opp, player, s={key: v}); returns (ALLOWED, OFFENSE, league)
    ALLOWED[pos][key][team] = dict(season, l15, l7 averages + ranks) -- what `team` allows per game to players at `pos`."""
    per = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))      # (defense, gid, date) -> pos -> key -> total
    off = defaultdict(lambda: defaultdict(float))                             # (team, gid, date) -> key -> total
    for r in games:
        p = pos_of(r)
        if p is None:
            continue
        k = (r["opp"], r["gid"], r["date"])
        for key in keys:
            v = r["s"].get(key)
            if v is not None:
                per[k][p][key] += v
                off[(r["team"], r["gid"], r["date"])][key] += v
                per[k]["ALL"][key] += v
    by_def = defaultdict(list)
    for (d, gid, date), v in per.items():
        by_def[d].append((date, v))
    A = {}
    positions = sorted({p for v in per.values() for p in v})
    for p in positions:
        A[p] = {}
        for key in keys:
            rows = {}
            for d, lst in by_def.items():
                lst = sorted(lst, key=lambda x: x[0])
                vals = [v.get(p, {}).get(key, 0.0) for _, v in lst]
                if len(vals) < min_games:
                    continue
                rows[d] = dict(season=round(st.mean(vals), 2), l15=round(st.mean(vals[-15:]), 2), l7=round(st.mean(vals[-7:]), 2))
            for w in ("season", "l15", "l7"):
                order = sorted(rows, key=lambda t: rows[t][w])                # rank 1 = allows the LEAST = toughest
                for i, t in enumerate(order):
                    rows[t][w + "_rk"] = i + 1
            A[p][key] = rows
    O = defaultdict(dict)
    by_team = defaultdict(list)
    for (t, gid, date), v in off.items():
        by_team[t].append(v)
    for key in keys:
        vals = {t: st.mean(v.get(key, 0) for v in lst) for t, lst in by_team.items() if len(lst) >= 3}
        for i, t in enumerate(sorted(vals, key=lambda t: -vals[t])):         # offense rank 1 = produces the MOST
            O[t][key] = dict(v=round(vals[t], 2), rk=i + 1)
    return A, dict(O), len(by_def)


def read_for(games, parts, line, opp_factor):
    """QUICK read: season mean x opponent factor (half weight); probability = empirical season hit rate shifted to the
    adjusted mean. Returned as p_over."""
    vals = [sum(g["s"].get(p, 0) or 0 for p in parts) for g in games]
    if len(vals) < 5:
        return None
    mu = st.mean(vals)
    adj = mu * (1 + (opp_factor - 1) * 0.5)
    shift = adj - mu
    p_over = sum(v + shift > line for v in vals) / len(vals)
    p_over = (p_over * len(vals) + 0.5 * 4) / (len(vals) + 4)                  # shrink toward 50% (4 pseudo-games)
    return dict(proj=round(adj, 2), p_over=round(p_over, 3), n=len(vals), kind="quick")


def model_reads(sport):
    """our screens' reads for today: (player_norm, stat_norm, line) -> dict(p_over, call, proj, flags, money)"""
    f = os.path.join("legs", "%s_%s.json" % (DAY, sport))
    if not os.path.exists(f):
        return {}
    import _slips
    proj = {}
    for l in open("calls_log.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if r.get("date") == DAY:
            proj[(norm(r["player"]), norm(r["stat"]), r["line"])] = r.get("proj")
    out = {}
    for l in json.load(open(f, encoding="utf-8")):
        k = (norm(l["player"]), norm(l["stat"]), l["line"])
        p = l.get("p_pin") if l.get("p_pin") is not None else l.get("p")
        if p is None:
            continue
        p_over = p if l["side"] == "over" else 1 - p
        if l.get("p_pin") is None and CAL and json.load(open("rules.json")).get("calibration"):   # only when the live rules say so
            import _calibrate as _C
            mk = _C.market(sport, l["stat"])
            po = p_over + CAL.get(mk + "|over", {}).get("adj", 0.0)
            pu = (1 - p_over) + CAL.get(mk + "|under", {}).get("adj", 0.0)
            p_over = max(0.03, min(0.97, po / max(1e-6, po + pu)))
        d = out.setdefault(k, dict(p_over=round(p_over, 3), call=l.get("call"), flags=l.get("flags") or [], money=_slips.money(l),
                                   src="pinnacle" if l.get("p_pin") is not None else "model", proj=proj.get(k), kind="model",
                                   off_pin="MODEL OFF PINNACLE" in (l.get("flags") or [])))
    return out


def board(sport_ud, pp_league):
    import _props as P
    L = []
    try:
        L += P.underdog(sport_ud)
    except Exception as e:
        print("  UD %s failed: %s" % (sport_ud, e))
    if pp_league:
        try:
            L += [l for l in P.prizepicks(pp_league, max_age=6 * 3600) if l.get("kind") in ("standard", None)]
        except Exception as e:
            print("  PP %s failed: %s" % (pp_league, e))
    return L


def game_sides(l):
    g = l.get("game") or ""
    if " @ " in g:
        a, h = g.split(" @ ")
        return a.strip(), h.strip()
    if " vs " in g.lower():
        a, h = re.split(r"(?i) vs\.? ", g)
        return a.strip(), h.strip()
    return None, None


def attach_lines(players, lines, alias_map, key_of_player, sport_key_pick, conv=lambda x: x):
    """lines -> players[pid]['lines'][statkey] = {line, ud:{over,under}, pp:line}; returns players with any line"""
    for l in lines:
        pid = key_of_player(l)
        if pid is None or pid not in players:
            continue
        P = players[pid]
        if P.get("opp") is None and l.get("team") and l.get("opp"):      # PrizePicks names both sides explicitly
            P["team"], P["opp"] = conv(l["team"]), conv(l["opp"])
            P["team_name"], P["opp_name"] = l["team"], l["opp"]
            P["moved"] = True
        amap = sport_key_pick(P)
        sk = ALIAS[amap].get(norm(l["stat"]))
        if not sk:
            continue
        slot = P["lines"].setdefault(sk, {})
        if l["venue"] == "UD":
            if "ud" not in slot or abs(l["line"] - slot["ud"]["line"]) < 1e-9 or True:
                slot.setdefault("ud", dict(line=l["line"], over=(l.get("mult") or {}).get("over"), under=(l.get("mult") or {}).get("under")))
        else:
            slot.setdefault("pp", dict(line=l["line"]))
        if l.get("start") and not P.get("start"):
            P["start"] = l["start"]
        if not P.get("game") and l.get("game"):
            P["game"] = l["game"]


def finalize(players, stats_of, dvp_A, pos_key, reads, league_avg, cur_min=None):
    """add a READ per line and trim logs"""
    for pid, P in list(players.items()):
        if not P["lines"]:
            del players[pid]
            continue
        S = stats_of(P)
        cur = [g for g in P["games"] if g.get("cur")]
        for sk, slot in P["lines"].items():
            line = (slot.get("ud") or slot.get("pp"))["line"]
            parts = S[sk][2]
            r = None
            for key in ((norm(P["name"]), norm(S[sk][0]), line),):
                pass
            # model read: any stat name that maps to this key at this line
            for (pn, sn, ln), v in reads.items():
                if pn == norm(P["name"]) and ln == line and ALIAS[pos_key(P)].get(sn) == sk:
                    r = dict(v)
                    break
            if r is None or r.get("off_pin"):
                f = 1.0
                d = (dvp_A.get(P["pos"]) or {})
                if P.get("opp") and all(d.get(p) and d[p].get(P["opp"]) for p in parts):
                    num = sum(d[p][P["opp"]]["season"] for p in parts)
                    den = sum(league_avg.get((P["pos"], p), 0) for p in parts)
                    f = num / den if den and num else 1.0
                    f = min(1.25, max(0.8, f))          # a 3-game defense sample made Stroud a 35-yard rusher (2026-09-30)
                if cur_min and len(cur) < cur_min:
                    slot["read_note"] = ("Only %d games this season. Roles change from year to year, so we don't read these lines off "
                                         "last season. The chart and matchup ranks still apply." % len(cur))
                    q = None
                else:
                    q = read_for(cur if len(cur) >= 8 else P["games"], parts, line, f)
                if q:
                    q["opp_factor"] = round(f, 3)
                    if r and r.get("off_pin"):
                        q["note"] = "our model disagreed with Pinnacle by 15%+ -- showing the quick read instead"
                    r = q
            slot["read"] = r
        P["games"] = [g for g in P["games"] if str(g.get("y", "2024")) >= "2024"]     # 2024 onward: two prior seasons + this one


def league_avgs(A):
    out = {}
    for p, d in A.items():
        for key, rows in d.items():
            if rows:
                out[(p, key)] = st.mean(r["season"] for r in rows.values())
    return out


# --------------------------------------------------------------------------------------------- WNBA
def wnba():
    c = sqlite3.connect("sports.db", timeout=300)
    ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba"
    teams = getj(ESPN + "/teams")["sports"][0]["leagues"][0]["teams"]
    pos, tname = {}, {}
    for t in teams:
        t = t["team"]
        tname[t["abbreviation"]] = t["displayName"]
        try:
            ro = getj("%s/teams/%s/roster" % (ESPN, t["id"]))
            for a in ro.get("athletes", []):
                pa = ((a.get("position") or {}).get("abbreviation") or "G")[0]
                pos[str(a["id"])] = {"G": "G", "F": "F", "C": "C"}.get(pa, "G")
        except Exception:
            pass
    rows = []
    for pid, name, team, opp, home, mins, date, season, js in c.execute(
            "SELECT player_id, player, team, opp, home, minutes, date, season, stats FROM player_games WHERE sport='WNBA' ORDER BY date"):
        s = json.loads(js)
        if not mins:
            continue
        rows.append(dict(pid=pid, player=name, team=team, opp=opp, home=home, m=mins, date=date, season=season,
                         gid="%s_%s" % (date, "".join(sorted([team or "", opp or ""]))), post=s.get("post"),
                         s={k: s.get(k) for k in ("pts", "reb", "ast", "tpm")}))
    cur = [r for r in rows if r["season"] == "2026" and r["team"] in tname and r["opp"] in tname]     # no exhibitions / All-Star
    A, O, nteams = dvp(cur, lambda r: pos.get(str(r["pid"])), ["pts", "reb", "ast", "tpm"])
    LA = league_avgs(A)
    byname = defaultdict(list)
    for r in rows:
        byname[norm(r["player"])].append(r)
    players = {}
    lines = board("WNBA", 3)
    alias_team = {"LVA": "LV", "GSV": "GS", "WAS": "WSH", "NYL": "NY", "LAS": "LA", "PHO": "PHX", "CONN": "CON", "TOR": "TOR", "POR": "POR"}
    for l in lines:
        k = norm(l["player"])
        if k in players or k not in byname:
            continue
        R = byname[k]
        last = R[-1]
        a, h = game_sides(l)
        a, h = alias_team.get(a, a), alias_team.get(h, h)
        team = last["team"]
        opp = h if a == team else a if h == team else None
        players[k] = dict(id=k, pid=str(last["pid"]), name=last["player"], team=team, team_name=tname.get(team, team), pos=pos.get(str(last["pid"]), "G"),
                          opp=opp, opp_name=tname.get(opp, opp), home=(h == team) if opp else None, lines={},
                          last_game=last["date"],
                          games=[dict(d=r["date"], o=r["opp"], h=r["home"], m=round(r["m"]), cur=r["season"] == "2026", post=bool(r["post"]), y=r["season"],
                                      s=r["s"]) for r in R])
    attach_lines(players, lines, ALIAS, lambda l: norm(l["player"]), lambda P: "WNBA", lambda x: alias_team.get(x, x))
    finalize(players, lambda P: WNBA_STATS, A, lambda P: "WNBA", model_reads("WNBA"), LA)
    # shot zones allowed, from the site's ESPN shot data (all teams we have)
    zones = {}
    try:
        W = json.load(open(os.path.join("site", "data.json"), encoding="utf-8")).get("wnba_all") or {}
        zones = dict(defense=W.get("defense", {}), nteams=W.get("nteams"))
        for P in players.values():
            z = (W.get("players") or {}).get(P["name"])
            if z:
                P["zones"] = z["z"]
    except Exception:
        pass
    return dict(label="WNBA", stats={k: v[:2] for k, v in WNBA_STATS.items()}, groups={"G": WNBA_STATS, "F": WNBA_STATS, "C": WNBA_STATS},
                players=players, dvp=A, offense=O, teams=tname, nteams=nteams, zones=zones, dvp_note="per game allowed to each position, 2026")


# --------------------------------------------------------------------------------------------- MLB
def mlb():
    c = sqlite3.connect("sports.db", timeout=300)
    import _mlb
    abbr = {}
    for t in _mlb.jget("/teams", sportId=1, season=2026)["teams"]:
        abbr[t["abbreviation"]] = t["name"]
    rows = []
    for pid, name, team, opp, home, date, gid, js, season in c.execute(
            "SELECT player_id, player, team, opp, home, date, game_id, stats, season FROM player_games WHERE sport='MLB' ORDER BY date"):
        x = json.loads(js)
        if x.get("group") == "pitching":
            if not x.get("gamesStarted"):
                continue
            ip = str(x.get("inningsPitched") or "0").split(".")
            outs = x.get("outs") if x.get("outs") is not None else int(ip[0]) * 3 + (int(ip[1]) if len(ip) > 1 else 0)
            s = dict(pk=x.get("strikeOuts"), outs=outs, er=x.get("earnedRuns"), ha=x.get("hits"), bba=x.get("baseOnBalls"))
            grp = "SP"
        else:
            if (x.get("plateAppearances") or 0) < 2:
                continue
            h = x.get("hits") or 0
            s = dict(h=h, tb=x.get("totalBases"), r=x.get("runs"), rbi=x.get("rbi"), k=x.get("strikeOuts"), bb=x.get("baseOnBalls"),
                     s1=h - (x.get("doubles") or 0) - (x.get("triples") or 0) - (x.get("homeRuns") or 0))
            grp = "H"
        rows.append(dict(pid=pid, player=name, team=team, opp=opp, home=home, date=date, gid=gid, grp=grp, s=s, season=season,
                         post=date >= {"2024": "2024-10-01", "2025": "2025-09-30"}.get(season, "2026-09-29")))
    A, O, nteams = dvp([r for r in rows if r["season"] == "2026"], lambda r: r["grp"], ["h", "tb", "r", "rbi", "k", "bb", "s1", "pk", "outs", "er", "ha", "bba"])
    LA = league_avgs(A)
    byname = defaultdict(list)
    for r in rows:
        byname[norm(r["player"])].append(r)
    players = {}
    lines = board("MLB", 2)
    full = lambda ab: abbr.get(ab, ab)
    for l in lines:
        k = norm(l["player"])
        if k in players:
            continue
        cand = byname.get(k) or next((v for kk, v in byname.items() if kk.startswith(k) or k.startswith(kk)), None)
        if not cand:
            continue
        # a two-way player could have both groups; use the group the stat belongs to
        grp = "SP" if ALIAS["MLB_P"].get(norm(l["stat"])) and not ALIAS["MLB_H"].get(norm(l["stat"])) else "H"
        R = [r for r in cand if r["grp"] == grp] or cand
        grp = R[-1]["grp"]
        last = R[-1]
        a, h = game_sides(l)
        a, h = full(a), full(h)
        team = last["team"]
        opp = h if a == team else a if h == team else None
        players[k] = dict(id=k, pid=str(last["pid"]), name=last["player"], team=team, team_name=team, pos=grp, opp=opp, opp_name=opp,
                          home=(h == team) if opp else None, lines={}, last_game=last["date"],
                          games=[dict(d=r["date"], o=r["opp"], h=r["home"], cur=r["season"] == "2026", post=r["post"], y=r["season"], s=r["s"]) for r in R])
    attach_lines(players, lines, ALIAS, lambda l: norm(l["player"]), lambda P: "MLB_P" if P["pos"] == "SP" else "MLB_H", full)
    finalize(players, lambda P: MLB_P if P["pos"] == "SP" else MLB_H, A, lambda P: "MLB_P" if P["pos"] == "SP" else "MLB_H",
             model_reads("MLB"), LA)
    # matchup context for the write-ups: opposing starter's arsenal, hitter Statcast, lineup spot (site/data.json mlb section)
    try:
        M = json.load(open(os.path.join("site", "data.json"), encoding="utf-8")).get("mlb") or {}
    except Exception:
        M = {}
    sp_of, spot = {}, {}
    for gm in M.get("games", []):
        for sd, od in (("away", "home"), ("home", "away")):
            sp_of[gm[sd]["team"]] = gm[od].get("sp")
            for i, x in enumerate(gm[sd].get("lineup") or []):
                spot[norm(x["name"])] = i + 1
    for P in players.values():
        ctx = {}
        if P["pos"] == "H":
            o = sp_of.get(P["team"])
            if o and o in (M.get("pitchers") or {}):
                pt = M["pitchers"][o]
                ctx["sp"] = dict(name=o, throws=pt.get("throws"), mix=pt.get("mix", [])[:4])
            hx = (M.get("hitters") or {}).get(P["name"])
            if hx:
                ls = [b["ls"] for b in hx.get("bip", []) if b.get("ls")]
                ctx["bat"] = dict(stand=hx.get("stand"), hard=round(sum(1 for v in ls if v >= 95) / len(ls), 3) if ls else None,
                                  ev=round(sum(ls) / len(ls), 1) if ls else None, pa=hx.get("pa"), hits=hx.get("hits"), hr=hx.get("hr"), k=hx.get("k"))
            if norm(P["name"]) in spot:
                ctx["spot"] = spot[norm(P["name"])]
        else:
            pt = (M.get("pitchers") or {}).get(P["name"])
            if pt:
                ctx["mix"] = pt.get("mix", [])[:4]
                ctx["throws"] = pt.get("throws")
        if ctx:
            P["ctx"] = ctx
    return dict(label="MLB", groups={"H": MLB_H, "SP": MLB_P}, players=players, dvp=A, offense=O, teams={v: v for v in abbr.values()},
                nteams=nteams, dvp_note="per game allowed to hitters (whole lineup) / to the starting pitcher, 2026")


# --------------------------------------------------------------------------------------------- NHL
NHL_AL = {"LA": "LAK", "NJ": "NJD", "SJ": "SJS", "TB": "TBL", "VEG": "VGK", "WAS": "WSH", "CLS": "CBJ", "MON": "MTL",
          "NAS": "NSH", "CAL": "CGY", "UTAH": "UTA", "ARI": "UTA", "LV": "VGK"}

def nhl():
    c = sqlite3.connect("sports.db", timeout=300)
    rows = []
    for pid, name, team, opp, home, mins, date, gid, season, js in c.execute(
            "SELECT player_id, player, team, opp, home, minutes, date, game_id, season, stats FROM player_games WHERE sport='NHL' "
            "AND season IN ('2024','2025','2026') ORDER BY date"):
        x = json.loads(js)
        p = x.get("pos")
        if p == "G":
            if not x.get("starter"):
                continue
            s = dict(saves=x.get("saves"), ga=(x.get("shots_against") or 0) - (x.get("saves") or 0))
        else:
            s = {k: x.get(k) for k in ("sog", "goals", "assists", "points", "hits", "blocks")}
        rows.append(dict(pid=pid, player=name, team=team, opp=opp, home=home, m=mins, date=date, gid=gid, season=season, pos=p, s=s,
                         gtype=x.get("gtype") or "reg"))
    # 2026-27 opened 9/29 (game type 2) -- defense ranks use last season + this season's regular-season games (fixed 10/2)
    reg = [r for r in rows if r["gtype"] != "pre" and r["season"] in ("2025", "2026")]
    A, O, nteams = dvp(reg, lambda r: r["pos"], ["sog", "goals", "assists", "points", "hits", "blocks", "saves", "ga"])
    LA = league_avgs(A)
    byname = defaultdict(list)
    for r in rows:
        byname[norm(r["player"])].append(r)          # stored as "A. Matthews"
    players = {}
    lines = board("NHL", 8)
    for l in lines:
        parts = l["player"].split()
        if len(parts) < 2:
            continue
        k = norm(parts[0][0] + ". " + " ".join(parts[1:]))
        if k in players or k not in byname:
            continue
        a, h = game_sides(l)
        a, h = NHL_AL.get(a, a), NHL_AL.get(h, h)
        bypid = defaultdict(list)
        for r in byname[k]:
            bypid[r["pid"]].append(r)
        cands = sorted(bypid.values(), key=lambda R: R[-1]["date"])
        R = next((R for R in cands if R[-1]["team"] in (a, h)), cands[-1])        # "A. Lee" = Andre or Anders
        last = R[-1]
        team = last["team"]
        opp = h if a == team else a if h == team else None
        players[k] = dict(id=k, pid=str(last["pid"]), name=l["player"], team=team, team_name=team, pos="G" if last["pos"] == "G" else last["pos"] or "F",
                          opp=opp, opp_name=opp, home=(h == team) if opp else None, lines={}, last_game=last["date"],
                          games=[dict(d=r["date"], o=r["opp"], h=r["home"], cur=r["gtype"] != "pre" and r["season"] in ("2025", "2026"), pre=r["gtype"] == "pre", y=r["season"],
                                      s={("saves" if kk == "saves" else kk): v for kk, v in r["s"].items()}) for r in R])
    def keyp(l):
        parts = l["player"].split()
        return norm(parts[0][0] + ". " + " ".join(parts[1:])) if len(parts) >= 2 else None
    attach_lines(players, lines, ALIAS, keyp, lambda P: "NHL_G" if P["pos"] == "G" else "NHL_S", lambda x: NHL_AL.get(x, x))
    G = {"sv": ("Saves", "SAVES", ["saves"]), "ga": ("Goals Against", "GA", ["ga"])}
    finalize(players, lambda P: G if P["pos"] == "G" else NHL_S, A, lambda P: "NHL_G" if P["pos"] == "G" else "NHL_S", model_reads("NHL"), LA)
    return dict(label="NHL", groups={"F": NHL_S, "D": NHL_S, "G": G}, players=players, dvp=A, offense=O, teams={}, nteams=nteams,
                dvp_note="per game allowed to each position, 2025-26 + 2026-27 regular season")


# --------------------------------------------------------------------------------------------- NFL
def nfl():
    rows = []
    fnum = lambda v: float(v) if v not in ("", "NA", None) else 0.0
    keys = ["passing_yards", "attempts", "completions", "passing_tds", "passing_interceptions", "rushing_yards", "carries",
            "receptions", "receiving_yards"]
    for f, season in (("nfl_2024_weekly.csv", "2024"), ("nfl_2025_weekly.csv", "2025"), ("nfl_2026_weekly.csv", "2026")):
        if not os.path.exists(f):
            continue
        for r in csv.DictReader(open(f, encoding="utf-8")):
            if r.get("season_type", "REG") != "REG" or not r.get("opponent_team"):
                continue
            rows.append(dict(pid=r["player_id"], player=r["player_display_name"], team=r.get("team") or r.get("recent_team"),
                             opp=r["opponent_team"], pos=r["position"], date="%s-W%02d" % (season, int(r["week"])), season=season,
                             gid="%s_%s_%s" % (season, r["week"], "".join(sorted([r.get("team") or "", r["opponent_team"]]))),
                             home=None, hs=r.get("headshot_url"), s={k: fnum(r.get(k)) for k in keys}))
    rows.sort(key=lambda r: r["date"])
    A, O, nteams = dvp([r for r in rows if r["season"] == "2026"], lambda r: r["pos"] if r["pos"] in ("QB", "RB", "WR", "TE") else None, keys)
    A25, _, _ = dvp([r for r in rows if r["season"] == "2025"], lambda r: r["pos"] if r["pos"] in ("QB", "RB", "WR", "TE") else None, keys)
    # NFL windows: 2026 season so far + all of 2025 (L15/L7 don't exist yet in week 4)
    for p, d in A.items():
        for key, tr in d.items():
            for t, v in tr.items():
                o = ((A25.get(p) or {}).get(key) or {}).get(t) or {}
                v["l15"], v["l15_rk"] = o.get("season"), o.get("season_rk")
                v["l7"], v["l7_rk"] = None, None
    LA = league_avgs(A)
    byname = defaultdict(list)
    for r in rows:
        byname[norm(r["player"])].append(r)
    alias = {"LAR": "LA", "JAC": "JAX", "WSH": "WAS", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU", "SL": "LA"}
    players = {}
    lines = board("NFL", 9)
    for l in lines:
        k = norm(l["player"])
        if k in players or k not in byname:
            continue
        R = byname[k]
        last = R[-1]
        if last["pos"] not in ("QB", "RB", "WR", "TE"):
            continue
        a, h = game_sides(l)
        a, h = alias.get(a, a), alias.get(h, h)
        team = last["team"]
        opp = h if a == team else a if h == team else None
        players[k] = dict(id=k, pid=str(last["pid"]), img=last.get("hs"), name=last["player"], team=team, team_name=team, pos=last["pos"], opp=opp, opp_name=opp,
                          home=(h == team) if opp else None, lines={}, last_game=last["date"],
                          games=[dict(d=r["date"], o=r["opp"], h=None, cur=r["season"] == "2026", y=r["season"], s=r["s"]) for r in R])
    attach_lines(players, lines, ALIAS, lambda l: norm(l["player"]), lambda P: "NFL", lambda x: alias.get(x, x))
    finalize(players, lambda P: NFL_S, A, lambda P: "NFL", {}, LA, cur_min=4)
    return dict(label="NFL", groups={p: NFL_S for p in ("QB", "RB", "WR", "TE")}, players=players, dvp=A, offense=O, teams={},
                nteams=nteams, dvp_note="per game allowed to each position; SEASON = 2026 so far, the middle column = all of 2025",
                windows=["2026", "2025", ""])


# --------------------------------------------------------------------------------------------- SOCCER
def soccer():
    import _soccer as S
    c = sqlite3.connect("sports.db", timeout=300)
    lines = board("SOCCER", 82)
    if not lines:
        return None
    names = {}
    teams_needed = set()
    for l in lines:
        for nm in game_sides(l):
            if nm:
                teams_needed.add(nm)
    for l in lines:
        if l.get("team"):
            teams_needed.add(l["team"])
    tid_of = {}
    for nm in teams_needed:
        try:
            t = S.find_team(nm)
            if t:
                tid_of[nm] = str(t)
                names[str(t)] = nm
        except Exception:
            pass
    lg_rows = c.execute("SELECT DISTINCT league FROM player_games WHERE sport='SOCCER' AND team IN (%s)" %
                        ",".join("?" * len(tid_of)), list(tid_of.values())).fetchall() if tid_of else []
    lgs = [r[0] for r in lg_rows]
    rows = []
    if lgs:
        for pid, name, team, opp, home, mins, date, gid, season, lg, js in c.execute(
                "SELECT player_id, player, team, opp, home, minutes, date, game_id, season, league, stats FROM player_games "
                "WHERE sport='SOCCER' AND league IN (%s) ORDER BY date" % ",".join("?" * len(lgs)), lgs):
            x = json.loads(js)
            if not mins or mins < 30:
                continue
            rows.append(dict(pid=pid, player=name, team=team, opp=opp, home=home, m=mins, date=date, gid=gid, season=season, lg=lg,
                             pos="GK" if x.get("gk") else "OUT", s={k: x.get(k) for k in ("passes", "shots", "sot", "saves")}))
    latest = {}
    for r in rows:
        latest[r["lg"]] = max(latest.get(r["lg"], ""), r["season"])
    cur = [r for r in rows if r["season"] == latest[r["lg"]]]
    A, O, nteams = dvp(cur, lambda r: r["pos"], ["passes", "shots", "sot", "saves"])
    LA = league_avgs(A)
    byname = defaultdict(list)
    for r in rows:
        byname[norm(r["player"])].append(r)
    players = {}
    for l in lines:
        k = norm(l["player"])
        if k in players or k not in byname:
            continue
        R = byname[k]
        last = R[-1]
        a, h = game_sides(l)
        ta, th = tid_of.get(a), tid_of.get(h)
        team = last["team"]
        opp = th if ta == team else ta if th == team else None
        players[k] = dict(id=k, pid=str(last["pid"]), name=last["player"], team=team, team_name=names.get(team, team), pos=last["pos"], opp=opp,
                          opp_name=names.get(opp, opp), home=(th == team) if opp else None, lines={}, last_game=last["date"],
                          games=[dict(d=r["date"], o=r["opp"], h=r["home"], m=round(r["m"]), cur=r["season"] == latest[r["lg"]], y=r["season"][:4], s=r["s"]) for r in R])
    attach_lines(players, lines, ALIAS, lambda l: norm(l["player"]), lambda P: "SOCCER", lambda x: tid_of.get(x, x))
    finalize(players, lambda P: SOC_S, A, lambda P: "SOCCER", model_reads("SOCCER"), LA)
    return dict(label="Soccer", groups={"GK": SOC_S, "OUT": SOC_S}, players=players, dvp=A, offense=O, teams=names, nteams=nteams,
                dvp_note="per match allowed to outfield players / goalkeepers, current league season")


# --------------------------------------------------------------------------------------------- ESPORTS (CS2 / Valorant)
ES_STATS = {"k12": ("Kills on Maps 1+2", "KILLS M1-2", ["k12"]), "hs12": ("Headshots on Maps 1+2", "HS M1-2", ["hs12"])}
ALIAS["ESPORTS"] = {"killsonmaps12": "k12", "maps12kills": "k12", "headshotsonmaps12": "hs12", "maps12headshots": "hs12"}


def _series(rows, pkey, name_of):
    """map rows -> one series row per player: maps 1+2 kills / headshots, opponent, date, year (series with 2+ maps only)"""
    bym = defaultdict(lambda: defaultdict(list))
    seen = set()
    for r in rows:
        k = (r["game_id"], r[pkey])
        if k in seen:
            continue
        seen.add(k)
        bym[r["match"]][r[pkey]].append(r)
    out = defaultdict(list)
    for mid, players in bym.items():
        for pid, maps in players.items():
            maps.sort(key=lambda r: (r.get("map_no") or 0, str(r["game_id"]).zfill(12)))
            if len(maps) < 2:
                continue
            m2 = maps[:2]
            out[pid].append(dict(date=m2[0]["date"], team=m2[0]["team"], opp=m2[0]["opp"], match=mid, role=m2[0].get("role"),
                                 name=name_of(m2[0]), s=dict(k12=sum(x["kills"] or 0 for x in m2),
                                 hs12=sum(x.get("hs") or 0 for x in m2) if all(x.get("hs") is not None for x in m2) else None,
                                 r12=sum(x.get("rounds") or 0 for x in m2))))
    for v in out.values():
        v.sort(key=lambda r: r["date"])
    return out


def _es_profile(game, rows, pid):
    """career card: overall per-map numbers + the pool (Valorant agents / CS2 maps), this season and all seasons"""
    key = "player" if game == "CS" else "pid"
    mine = {}
    for r in rows:
        if str(r.get(key)) == str(pid):
            mine[(r["game_id"])] = r
    M = sorted(mine.values(), key=lambda r: r["date"])
    if not M:
        return None
    def agg(ms):
        rd = sum(m.get("rounds") or 0 for m in ms) or 1
        k = sum(m["kills"] or 0 for m in ms); d = sum(m["deaths"] or 0 for m in ms) or 1
        out = dict(maps=len(ms), win=round(sum(1 for m in ms if m.get("win")) / len(ms), 3), kpr=round(k / rd, 3), kd=round(k / d, 2),
                   kpm=round(k / len(ms), 1))
        if game == "CS":
            hs = [m for m in ms if m.get("hs") is not None]
            out["hs"] = round(sum(m["hs"] for m in hs) / max(1, sum(m["kills"] or 0 for m in hs)), 3) if hs else None
            adr = [m["adr"] for m in ms if m.get("adr")]
            out["adr"] = round(sum(adr) / len(adr), 1) if adr else None
            out["fkr"] = round(sum(m.get("fk") or 0 for m in ms) / rd, 3)
        else:
            acs = [m["acs"] for m in ms if m.get("acs")]
            out["acs"] = round(sum(acs) / len(acs)) if acs else None
            fb = [m for m in ms if m.get("fb") is not None]
            if fb:
                out["fbr"] = round(sum(m["fb"] for m in fb) / max(1, sum(m.get("rounds") or 0 for m in fb)), 3)
            hsp = [m["hsp"] for m in ms if m.get("hsp") is not None]
            out["hs"] = round(sum(hsp) / len(hsp) / (100 if sum(hsp) / len(hsp) > 1 else 1), 3) if hsp else None
            adr = [m["adr"] for m in ms if m.get("adr")]
            out["adr"] = round(sum(adr) / len(adr), 1) if adr else None
        return out
    cur = [m for m in M if m["date"][:4] == "2026"] or M[-60:]
    pool_key = "map" if game == "CS" else "agent"
    pool = defaultdict(list)
    for m in cur:
        pool[(m.get(pool_key) or "?").replace("de_", "")].append(m)
    pool_all = defaultdict(list)
    for m in M:
        pool_all[(m.get(pool_key) or "?").replace("de_", "")].append(m)
    P = [dict(name=k, share=round(len(v) / len(cur), 3), **agg(v), role=(v[0].get("role") if game == "VAL" else None),
              all_maps=len(pool_all.get(k, []))) for k, v in pool.items()]
    P.sort(key=lambda x: -x["maps"])
    years = {}
    for y in sorted({m["date"][:4] for m in M}):
        years[y] = agg([m for m in M if m["date"][:4] == y])
    return dict(season=agg(cur), years=years, pool=P[:10], pool_kind=pool_key, recent_team=M[-1]["team"])


def esports(game):
    if game == "CS":
        nicks = json.load(open("cs2_nicks.json", encoding="utf-8"))
        rows = []
        for f in ("cs2_maps_old.jsonl", "cs2_maps.jsonl"):
            rows += [json.loads(l) for l in open(f, encoding="utf-8")]
        rows = [r for r in rows if r.get("date", "") >= "2024-01-01"]
        S = _series(rows, "player", lambda r: (nicks.get(str(r["player"])) or {}).get("nick") or str(r["player"]))
        pp_league, label = 265, "CS2"
    else:
        rows = []
        for f in ("val_maps.jsonl", "val_maps2.jsonl"):
            if os.path.exists(f):
                rows += [json.loads(l) for l in open(f, encoding="utf-8")]
        rows = [r for r in rows if r.get("date", "") >= "2024-01-01"]
        S = _series(rows, "pid", lambda r: r.get("name"))
        pp_league, label = 159, "Valorant"
    # 'defense': kills each team allows per opposing player per series (maps 1+2), by role for Valorant
    flat = []
    for pid, L in S.items():
        for r in L:
            flat.append(dict(gid=r["match"], date=r["date"], team=r["team"], opp=r["opp"], player=pid,
                             pos=(r.get("role") or "ALL") if game == "VAL" else "ALL", season=r["date"][:4],
                             s={"k12": r["s"]["k12"] / 5.0 if False else r["s"]["k12"], "hs12": r["s"]["hs12"]}))
    cur = [r for r in flat if r["season"] == "2026"]
    A, O, nteams = dvp(cur, lambda r: r["pos"], ["k12", "hs12"], min_games=5)
    # per-player averages are what matter: divide team totals by players at that position per series
    cnt = defaultdict(lambda: defaultdict(int))
    for r in cur:
        cnt[(r["opp"], r["gid"])][r["pos"]] += 1
    LA = league_avgs(A)
    byname = defaultdict(list)
    for pid, L in S.items():
        byname[norm(L[-1]["name"])].append((pid, L))
    lines = board(game, pp_league)
    players = {}
    for l in lines:
        k = norm(l["player"].split()[-1]) if game == "CS" else norm(l["player"])
        cands = byname.get(k) or byname.get(norm(l["player"]))
        if not cands:
            continue
        a, h = game_sides(l)
        sides = [norm(x) for x in (a, h) if x]
        def on_side(L):
            t = norm(L[-1]["team"])
            return any(t and (t.startswith(sd[:5]) or sd.startswith(t[:5])) for sd in sides)
        pick = [c for c in cands if on_side(c[1])] or sorted(cands, key=lambda c: c[1][-1]["date"])[-1:]
        pid, L = pick[0]
        key = "%s_%s" % (k, pid)
        if key in players:
            continue
        team = L[-1]["team"]
        opp = None
        for x in (a, h):
            if x and not (norm(team).startswith(norm(x)[:5]) or norm(x).startswith(norm(team)[:5])):
                opp = x
        # map the line's opponent name to the data's spelling
        if opp:
            known = {norm(r["opp"]): r["opp"] for r in flat if r["opp"]}
            opp = known.get(norm(opp)) or next((v for kk, v in known.items() if kk.startswith(norm(opp)[:5])), opp)
        role = L[-1].get("role") if game == "VAL" else None
        players[key] = dict(id=key, pid=str(pid), name=L[-1]["name"], team=team, team_name=team, pos=(role or "ALL"), opp=opp, opp_name=opp, profile=_es_profile(game, rows, pid),
                            home=None, lines={}, last_game=L[-1]["date"], role=role,
                            games=[dict(d=r["date"], o=r["opp"], h=None, cur=r["date"][:4] == "2026", y=r["date"][:4],
                                        s={kk: v for kk, v in r["s"].items() if v is not None}) for r in L])
    def keyp(l):
        k = norm(l["player"].split()[-1]) if game == "CS" else norm(l["player"])
        for key in players:
            if key.split("_")[0] == k:
                return key
        return None
    attach_lines(players, lines, ALIAS, keyp, lambda P: "ESPORTS")
    finalize(players, lambda P: ES_STATS, A, lambda P: "ESPORTS", {}, LA)
    groups = {p: ES_STATS for p in (["ALL"] + (["duelist", "initiator", "controller", "sentinel"] if game == "VAL" else []))}
    return dict(label=label, groups=groups, players=players, dvp=A, offense=O, teams={}, nteams=nteams, paper=True,
                dvp_note="kills each team allows per series (maps 1+2) to %s, 2026 matches" % ("each role" if game == "VAL" else "the opposing five"))


# --------------------------------------------------------------------------------------------- CFB
CFB_S = {"pyd": ("Passing Yards", "PASS YDS", ["pass_yds"]), "patt": ("Pass Attempts", "ATT", ["att"]), "cmp": ("Completions", "CMP", ["cmp"]),
         "ptd": ("Passing TDs", "PASS TD", ["pass_td"]), "ryd": ("Rushing Yards", "RUSH YDS", ["rush_yds"]), "car": ("Rush Attempts", "CAR", ["carries"]),
         "rec": ("Receptions", "REC", ["rec"]), "reyd": ("Receiving Yards", "REC YDS", ["rec_yds"]),
         "rry": ("Rush + Rec Yards", "RUSH+REC", ["rush_yds", "rec_yds"])}


def cfb():
    c = sqlite3.connect("sports.db", timeout=300)
    rows = []
    for pid, name, team, opp, date, gid, season, js in c.execute(
            "SELECT player_id, player, team, opp, date, game_id, season, stats FROM player_games WHERE sport='CFB' ORDER BY date"):
        x = json.loads(js)
        rows.append(dict(pid=pid, player=name, team=team, opp=opp, date=date, gid=gid, season=season, pos=x.get("pos"),
                         s={k: x.get(k, 0.0) for k in ("cmp", "att", "pass_yds", "pass_td", "carries", "rush_yds", "rec", "rec_yds")}))
    keys = ["cmp", "att", "pass_yds", "pass_td", "carries", "rush_yds", "rec", "rec_yds"]
    A, O, nteams = dvp([r for r in rows if r["season"] == "2026"], lambda r: r["pos"] if r["pos"] in ("QB", "RB", "WR") else None, keys, min_games=2)
    LA = league_avgs(A)
    byname = defaultdict(list)
    for r in rows:
        byname[norm(r["player"])].append(r)
    lines = board("CFB", 15)
    teamkey = {}
    for r in rows:
        teamkey[norm(r["team"])] = r["team"]

    abbr = {}
    try:                                              # app lines use ESPN-style abbreviations ("VT", "PITT") -> full names
        tj = getj("https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams?limit=1000&groups=80")
        for t in tj["sports"][0]["leagues"][0]["teams"]:
            t = t["team"]
            abbr[norm(t.get("abbreviation"))] = t.get("displayName")
    except Exception as e:
        print("  CFB team list failed:", e)

    def find_team(x):
        k = norm(x)
        if k in abbr:
            return abbr[k]
        if k in teamkey:
            return teamkey[k]
        return next((v for kk, v in teamkey.items() if kk.startswith(k) or k.startswith(kk[:max(4, len(k))])), x)
    players = {}
    for l in lines:
        k = norm(l["player"])
        if k in players or k not in byname:
            continue
        R = byname[k]; last = R[-1]
        a, h = game_sides(l)
        opp = None
        for x in (a, h):
            if x and norm(find_team(x)) != norm(last["team"]):
                opp = find_team(x)
        if l.get("opp"):
            opp = find_team(l["opp"])
        players[k] = dict(id=k, pid=str(last["pid"]), name=last["player"], team=last["team"], team_name=last["team"], pos=last["pos"] or "WR",
                          opp=opp, opp_name=opp, home=None, lines={}, last_game=last["date"],
                          games=[dict(d=r["date"], o=r["opp"], h=None, cur=r["season"] == "2026", y=r["season"], s=r["s"]) for r in R])
    attach_lines(players, lines, ALIAS, lambda l: norm(l["player"]), lambda P: "NFL", find_team)
    for P in players.values():                       # NFL alias covers stats CFB box scores don't have (INTs) -> drop those lines
        P["lines"] = {k: v for k, v in P["lines"].items() if k in CFB_S}
    finalize(players, lambda P: CFB_S, A, lambda P: "NFL", {}, LA, cur_min=4)
    return dict(label="CFB", groups={p: CFB_S for p in ("QB", "RB", "WR")}, players=players, dvp=A, offense=O, teams={}, nteams=nteams,
                dvp_note="per game allowed to each position, 2026 FBS games (positions from box-score role)")


SPORTS = {"WNBA": wnba, "MLB": mlb, "NHL": nhl, "NFL": nfl, "CFB": cfb, "SOCCER": soccer, "CS2": lambda: esports("CS"), "VAL": lambda: esports("VAL")}

if __name__ == "__main__":
    want = [a.upper() for a in sys.argv[1:]] or list(SPORTS)
    data = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    for sp in want:
        try:
            d = SPORTS[sp]()
            if d:
                # JSON keys: stat groups as {key: [label, tab, parts]}
                d["groups"] = {g: {k: list(v) for k, v in grp.items()} for g, grp in d["groups"].items()}
                d.pop("stats", None)
                keys = sorted({k for P in d["players"].values() for g in P["games"] for k in g["s"]})
                for P in d["players"].values():
                    for g in P["games"]:
                        g["s"] = [None if g["s"].get(k) is None else (round(g["s"][k], 1) if isinstance(g["s"][k], float) else g["s"][k]) for k in keys]
                        for f_ in ("cur", "post", "pre"):
                            if not g.get(f_):
                                g.pop(f_, None)
                d["skeys"] = keys
                data[sp] = d
                print("%-7s %4d players with lines" % (sp, len(d["players"])))
            else:
                print("%-7s no lines" % sp)
        except Exception as e:
            import traceback; traceback.print_exc()
            print("%-7s FAILED: %s" % (sp, e))
    data["built"] = datetime.datetime.now().isoformat(timespec="minutes")
    json.dump(data, open(OUT, "w", encoding="utf-8"), separators=(",", ":"))
    print("wrote %s (%.0f KB)" % (OUT, os.path.getsize(OUT) / 1e3))
