"""Chart-data sections for the prop desk site (tonight, MLB, NFL, soccer). Imported by _site_data.py."""
import os, json, csv, io, gzip, statistics as st
from concurrent.futures import ThreadPoolExecutor
from _site_data import raw, g, DAY


# ---------------------------------------------------------------------------------------------------------- TONIGHT
def recent(sport, player, stat, n=10):
    """last n values of a stat for a player from sports.db, oldest first: [(date, value)]"""
    import sqlite3
    c = sqlite3.connect("sports.db")
    parts = player.split()
    rows = c.execute("SELECT date, stats FROM player_games WHERE sport=? AND (player=? OR player=?) ORDER BY date",
                     (sport, player, parts[0][0] + ". " + " ".join(parts[1:]))).fetchall()
    k = "".join(ch for ch in stat.lower() if ch.isalnum())
    out = []
    for d, js in rows:
        x = json.loads(js)
        try:
            if sport == "MLB":
                pitch = any(w in k for w in ("pitchingouts", "earnedruns", "allowed")) or k == "strikeouts"
                if (x.get("group") == "pitching") != pitch:
                    continue
                if pitch and not x.get("gamesStarted"):
                    continue
                if not pitch and (x.get("plateAppearances") or 0) < 2:
                    continue
                if "runs" in k and "hits" in k:
                    v = x["hits"] + x["runs"] + x["rbi"]
                elif "totalbases" in k:
                    v = x["totalBases"]
                elif "strikeout" in k:
                    v = x["strikeOuts"]
                elif "outs" in k:
                    v = x.get("outs")
                elif k == "hits":
                    v = x["hits"]
                else:
                    v = None
            elif sport == "NHL":
                if x.get("pos") != "G" or not x.get("starter"):
                    continue
                v = x.get("saves")
            elif sport == "WNBA":
                v = 0
                if "point" in k or "pts" in k:
                    v += x["pts"]
                if "reb" in k:
                    v += x["reb"]
                if "ast" in k or "assist" in k:
                    v += x["ast"]
                if "3pt" in k or "three" in k:
                    v += x["tpm"]
            elif sport == "SOCCER":
                v = (x.get("saves") if "save" in k else x.get("sot") if ("target" in k or "sot" in k)
                     else x.get("shots") if "shot" in k else x.get("passes"))
            else:
                v = None
        except (KeyError, TypeError):
            v = None
        if v is not None:
            out.append((d, v))
    return out[-n:]


def tonight():
    import _slips
    legs = _slips.prepare(_slips.load(DAY))
    proj = {}
    for l in open("calls_log.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if r.get("date") == DAY:
            proj[(r["player"], r["stat"], r["line"])] = r.get("proj")
    rows, seen = [], set()
    for l in sorted(legs, key=lambda l: -(l["value"] - _slips.BE[l["venue"]])):
        key = (l["player"], l["side"])
        if key in seen:
            continue
        seen.add(key)
        fl = [f for f in (l.get("flags") or []) if not (l["sport"] == "MLB" and f.startswith("NEW TEAMMATE OUT"))]
        rows.append(dict(sport=l["sport"], player=l["player"], team=l.get("team"), opp=l.get("opp"), stat=l["stat"], line=l["line"],
                         side=l["side"], venue=l["venue"], mult=l["m"], p=l["p_used"], src=l["src"],
                         be=round(_slips.BE[l["venue"]] / l["m"], 3), call=l.get("call"),
                         proj=proj.get((l["player"], l["stat"], l["line"])), money=_slips.money(l), flags=fl[:4],
                         start=l.get("start"), recent=recent(l["sport"], l["player"], l["stat"])))
    slip = [r for r in rows if (r["player"], r["side"]) in {("Darcy Kuemper", "under"), ("Alex Bregman", "over")}]
    return dict(board=rows[:40], slip=slip, counts={s: sum(r["sport"] == s for r in rows) for s in {r["sport"] for r in rows}})


# ---------------------------------------------------------------------------------------------------------- MLB
SAV = ("https://baseballsavant.mlb.com/statcast_search/csv?all=true&type=details&player_type=%s&%s%%5B%%5D=%d"
       "&hfSea=2026%%7C&hfGT=R%%7CF%%7CD%%7CL%%7CW%%7C")
HIT_EV = {"single", "double", "triple", "home_run"}


def savant(pid, kind):
    b = raw(SAV % (kind, "batters_lookup" if kind == "batter" else "pitchers_lookup", pid), "sav_%s_%d.csv" % (kind, pid), 12 * 3600)
    return list(csv.DictReader(io.StringIO(b.decode("utf-8-sig"))))


def mlb():
    import _mlb
    T = _mlb.team_table()

    def rank(k, high_is_1):
        order = sorted(T, key=lambda t: (T[t].get(k) or 0), reverse=high_is_1)
        return {t: i + 1 for i, t in enumerate(order)}
    R = {k: rank(k, hi) for k, hi in (("ops", True), ("k_pct", False), ("runs_pg", True), ("era", False), ("ops_allowed", False),
                                       ("rp_era", False), ("k_pct_p", True))}
    sch = _mlb.jget("/schedule", sportId=1, date=DAY, hydrate="probablePitcher,team,lineups")
    games = []
    for dt in sch.get("dates", []):
        for gm in dt["games"]:
            if (gm.get("status") or {}).get("abstractGameState") == "Final":
                continue
            side = {}
            for sd in ("away", "home"):
                t = gm["teams"][sd]
                nm = t["team"]["name"]
                pp = t.get("probablePitcher") or {}
                L = (gm.get("lineups") or {}).get(sd + "Players") or []
                side[sd] = dict(team=nm, abbr=t["team"].get("abbreviation"), sp=pp.get("fullName"), sp_id=pp.get("id"),
                                lineup=[dict(name=p["fullName"], id=p["id"]) for p in L],
                                stats={k: T.get(nm, {}).get(k) for k in ("ops", "k_pct", "runs_pg", "era", "ops_allowed", "rp_era", "l15_rf", "l15_ra")},
                                ranks={k: R[k].get(nm) for k in R})
            games.append(dict(start=gm["gameDate"], state=gm["status"]["detailedState"], series=gm.get("seriesDescription"), **side))
    todo_h = [(p["id"], p["name"], gm[sd]["team"]) for gm in games for sd in ("away", "home") for p in gm[sd]["lineup"]]
    todo_p = [(gm[sd]["sp_id"], gm[sd]["sp"], gm[sd]["team"]) for gm in games for sd in ("away", "home") if gm[sd]["sp_id"]]

    def hit(x):
        pid, name, team = x
        rows = savant(pid, "batter")
        bip = [r for r in rows if r["hc_x"] and r["hc_y"]]
        pa = [r for r in rows if r["events"]]
        return name, dict(team=team, stand=rows[0]["stand"] if rows else "",
                          bip=[dict(x=round(float(r["hc_x"]), 1), y=round(float(r["hc_y"]), 1), ev=r["events"],
                                    ls=round(float(r["launch_speed"])) if r["launch_speed"] else None, vs=r["p_throws"], d=r["game_date"])
                               for r in bip],
                          pa=len(pa), hits=sum(r["events"] in HIT_EV for r in pa), k=sum(r["events"] == "strikeout" for r in pa),
                          hr=sum(r["events"] == "home_run" for r in pa))

    def pit(x):
        pid, name, team = x
        rows = savant(pid, "pitcher")
        mix = {}
        for r in rows:
            m = mix.setdefault(r["pitch_type"] or "?", dict(n=0, sw=0, wh=0, velo=[], name=r["pitch_name"]))
            m["n"] += 1
            d = r["description"]
            if "swing" in d or "foul" in d or "hit_into_play" in d:
                m["sw"] += 1
            if d in ("swinging_strike", "swinging_strike_blocked"):
                m["wh"] += 1
            if r["release_speed"]:
                m["velo"].append(float(r["release_speed"]))
        n = sum(m["n"] for m in mix.values()) or 1
        mix = [dict(code=k, name=m["name"], pct=round(m["n"] / n, 3), whiff=round(m["wh"] / max(1, m["sw"]), 3),
                    velo=round(st.mean(m["velo"]), 1) if m["velo"] else None) for k, m in mix.items() if m["n"] / n >= 0.02]
        mix.sort(key=lambda m: -m["pct"])
        locs = [dict(x=round(float(r["plate_x"]), 2), z=round(float(r["plate_z"]), 2), t=r["pitch_type"], s=r["stand"],
                     w=int(r["description"] in ("swinging_strike", "swinging_strike_blocked")))
                for r in rows[:1600] if r["plate_x"] and r["plate_z"]]
        return name, dict(team=team, mix=mix, locs=locs, pitches=len(rows), throws=rows[0]["p_throws"] if rows else "")

    with ThreadPoolExecutor(4) as ex:
        hitters = dict(ex.map(hit, todo_h))
        pitchers = dict(ex.map(pit, todo_p))
    return dict(games=games, hitters=hitters, pitchers=pitchers)


# ---------------------------------------------------------------------------------------------------------- NFL
def nfl():
    rows = list(csv.DictReader(open("nfl_2026_weekly.csv", encoding="utf-8")))
    rows = [r for r in rows if r.get("season_type", "REG") == "REG" and r.get("opponent_team")]
    weeks = sorted({int(r["week"]) for r in rows})
    f = lambda v: float(v) if v not in ("", "NA", None) else 0.0
    allow, games = {}, {}
    for r in rows:
        d, pos = r["opponent_team"], r["position"]
        if pos not in ("QB", "RB", "WR", "TE"):
            continue
        games.setdefault(d, set()).add(r["week"])
        a = allow.setdefault(d, {}).setdefault(pos, dict(pass_yds=0, rush_yds=0, rec_yds=0, rec=0, tgt=0, tds=0))
        a["pass_yds"] += f(r["passing_yards"]); a["rush_yds"] += f(r["rushing_yards"]); a["rec_yds"] += f(r["receiving_yards"])
        a["rec"] += f(r["receptions"]); a["tgt"] += f(r["targets"])
        a["tds"] += f(r["passing_tds"]) + f(r["rushing_tds"]) + f(r["receiving_tds"])
    D = {}
    for t, v in allow.items():
        gp = len(games[t])
        D[t] = dict(gp=gp, **{pos: {k: round(x / gp, 1) for k, x in a.items()} for pos, a in v.items()})
    b = raw("https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_2026.csv.gz", "pbp_2026.csv.gz", 12 * 3600)
    tg = {}
    for r in csv.DictReader(io.StringIO(gzip.decompress(b).decode("utf-8"))):
        if r.get("pass_attempt") != "1" or not r.get("receiver_player_name") or r.get("air_yards") in ("", "NA", None):
            continue
        t = tg.setdefault(r["receiver_player_name"], dict(team=r["posteam"], t=[]))
        yg = r.get("yards_gained")
        t["t"].append(dict(loc=r.get("pass_location") or "?", ay=round(float(r["air_yards"])), c=int(r.get("complete_pass") == "1"),
                           yds=int(float(yg)) if yg not in ("", "NA", None) else 0, td=int(r.get("touchdown") == "1"),
                           wk=int(r["week"]), opp=r["defteam"]))
    top = dict(sorted(tg.items(), key=lambda kv: -len(kv[1]["t"]))[:60])
    return dict(weeks=weeks, defense=D, targets=top)


# ---------------------------------------------------------------------------------------------------------- SOCCER
def soccer():
    import _soccer as S
    L = json.load(open(os.path.join("legs", "%s_SOCCER.json" % DAY), encoding="utf-8"))
    bf = "_soccer_board_%s.json" % DAY
    board = json.load(open(bf, encoding="utf-8")) if os.path.exists(bf) else []
    teams = {}
    for nm in sorted({l["team"] for l in L} | {l["opp"] for l in L}):
        tid = S.find_team(nm)
        if not tid or tid in teams:
            continue
        d = S.get("%s/teams?id=%s" % (S.FM, tid))
        fx = [x for x in d["fixtures"]["allFixtures"]["fixtures"] if (x.get("status") or {}).get("finished")][-6:]
        sf, sa, matches = [], [], []
        for x in fx:
            m = g("%s/matchDetails?matchId=%s" % (S.FM, x["id"]), "fm_%s.json" % x["id"])
            sh = ((m.get("content") or {}).get("shotmap") or {}).get("shots") or []
            gen = m["general"]
            opp = gen["awayTeam"]["name"] if gen["homeTeam"]["id"] == tid else gen["homeTeam"]["name"]
            matches.append(dict(opp=opp, date=(gen.get("matchTimeUTCDate") or "")[:10],
                                score=((m.get("header") or {}).get("status") or {}).get("scoreStr")))
            for s_ in sh:
                row = dict(x=round(s_["x"], 1), y=round(s_["y"], 1), xg=round(s_.get("expectedGoals") or 0, 3), ev=s_["eventType"],
                           on=bool(s_.get("isOnTarget")), p=s_.get("playerName"), opp=opp, sit=s_.get("situation"))
                (sf if s_["teamId"] == tid else sa).append(row)
        teams[str(tid)] = dict(name=d["details"]["name"], matches=matches, shots_for=sf, shots_against=sa, profile=S.team_profile(tid))
    keep = ("player", "team", "opp", "stat", "line", "side", "call", "gap", "proj", "avg", "adj_avg", "factor_why", "last5", "h2h",
            "flags", "position")
    return dict(teams=teams, board=[{k: b_.get(k) for k in keep} for b_ in board])
