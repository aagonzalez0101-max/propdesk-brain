"""PICKFINDER METHOD (10/30, user: "how I made my money on pickfinder last year" -- NBA = his whole 2026 profit, 422 bets +16.9%).
His exact process, reproduced in order, no editorializing:

  STEP 1  last 5 (THIS SEASON ONLY) all same side, last 10 (THIS SEASON ONLY) all same side  -- doesn't have to be good, can be a
          trend of unders. If L5 and L10 don't agree with each other, the player is OUT, not a lean.
  STEP 2  h2h vs this opponent (all seasons -- he's played enough history to count) agrees with the L5/L10 direction.
  STEP 3  defense vs HIS shooting zone matches the direction: trend is UNDER and the defense is tough in his zones (zone_boost
          negative) -> confirms. Trend is OVER and defense is soft in his zones (zone_boost positive) -> confirms. Mismatch -> drop.
  CONTEXT (11/5, printed, not gates): opponent allows X of this stat/game + rank; his avg with vs WITHOUT each out teammate;
          how OTHER players at his position (G/F/C) did vs their own PP standard line for this stat against this opponent.
  STEP 4  (printed, not auto-graded) lineups/minutes/injuries/opponent's likely defender -- his manual override layer.

    python _pf_method.py [YYYY-MM-DD]
"""
import sys, datetime, collections
import _ppcache as C, _lineflash as F
import sqlite3

CT = __import__("zoneinfo").ZoneInfo("America/Chicago")
ESPN = {"NYK": "NY", "GSW": "GS", "SAS": "SA", "NOP": "NO", "UTA": "UTAH", "WAS": "WSH"}   # 10/30: PP's team code vs our box's (Maxey h2h vs NYK came back empty -- it's really "NY")
NON_SHOT = {"Rebounds", "Assists", "Rebs+Asts", "Blocked Shots", "Steals", "Blks+Stls"}
ZONE_CLS = {"dunk": "rim", "lob dunk": "rim", "putback": "rim", "rim": "rim", "lob layup": "rim", "hook": "paint",
            "floater": "paint", "mid": "mid", "three": "three"}
STAT = {"Points": "pts", "Rebounds": "reb", "Assists": "ast", "Pts+Rebs+Asts": "pts+reb+ast", "Pts+Rebs": "pts+reb",
        "Pts+Asts": "pts+ast", "Rebs+Asts": "reb+ast", "3-PT Made": "tpm", "3-PT Attempted": "tpa", "FG Attempted": "fga",
        "FG Made": "fgm", "Two Pointers Attempted": "fga-tpa", "Fantasy Score": "pts+1.2*reb+1.5*ast+3*stl+3*blk-tov",
        "Blocked Shots": "blk", "Steals": "stl", "Blks+Stls": "stl+blk",
        # 11/5 user: "keep going for pp stuff" -- every other standard PP stat our box score can grade
        "Turnovers": "tov", "Free Throws Made": "ftm", "Free Throws Attempted": "fta", "Two Pointers Made": "fgm-tpm",
        "Offensive Rebounds": "oreb", "Defensive Rebounds": "dreb", "Personal Fouls": "pf"}
NON_SHOT |= {"Turnovers", "Offensive Rebounds", "Defensive Rebounds", "Personal Fouls"}
LINES_DB = __import__("os").environ.get("LINES_DB", "lines.db")   # archived PP lines (the cloud's copy is the current one)


def board(day):
    d = C.projections(7, 300)
    P = {i["id"]: i["attributes"] for i in d.get("included", []) if i["type"] == "new_player"}
    out = []
    for x in d["data"]:
        a = x["attributes"]
        if a.get("odds_type") != "standard" or a.get("is_promo") or a["stat_type"] not in STAT:
            continue
        if not a["start_time"].startswith(day):
            continue
        p = P.get(x["relationships"]["new_player"]["data"]["id"], {})
        opp_raw = (a.get("description") or "").split()[0]
        out.append(dict(player=p.get("name"), team=ESPN.get(p.get("team"), p.get("team")), opp=ESPN.get(opp_raw, opp_raw),
                        stat=a["stat_type"], line=float(a["line_score"]), start=a["start_time"]))
    return out


def zone_detail(player, opp):
    """readable version of zone_boost: his own FG% in his top 1-2 shot zones + the opponent's league RANK (1=toughest,
    32=softest) defending each zone -- 'shoots 44% from three, NY ranks 9th defending the three' instead of a raw %."""
    F.zone_boost(player, opp)  # ensures _ZONES is built
    if not F._ZONES:
        return None
    D, LG, MIX = F._ZONES["D"], F._ZONES["LG"], F._ZONES["MIX"]
    mix = MIX.get(player); tot = sum(mix.values()) if mix else 0
    if tot < 200:
        return None
    teams = {o for (o, z) in D if D[(o, z)][1] >= 150}
    out = []
    for z, label in (("three", "the three"), ("mid", "midrange"), ("rim", "the rim"), ("paint", "floater/hook range")):
        share = mix.get(z, 0) / tot
        if share < 0.12:
            continue
        own_fg = D.get((player, z))  # not stored per-player makes/misses separately; compute his own zone FG% from scratch below
        ranks = sorted(teams, key=lambda o: D[(o, z)][0] / max(D[(o, z)][1], 1))  # ascending FG% allowed = toughest first
        if opp not in ranks:
            continue
        rk = ranks.index(opp) + 1
        out.append((share, z, label, rk, len(ranks)))
    out.sort(reverse=True)
    return out[:2]


def own_zone_fg(c, player, zone_cls_map):
    """player's own FG% in each zone, this season + last (from nba_pbp shots)."""
    import sqlite3
    p = sqlite3.connect("nba_pbp.db")
    made = collections.Counter(); att = collections.Counter()
    for cls, m, n in p.execute("select cls, made, count(*) from nba_shots where player=? and season in ('2025-26','2026-27') group by 1,2", (player,)):
        z = zone_cls_map.get(cls, "mid"); att[z] += n
        if m:
            made[z] += n
    return {z: (made[z] / att[z] if att[z] else None) for z in ("rim", "paint", "mid", "three")}


def teammate_already_out(c, teammate, since):
    """10/30 bug caught by user: flagged Williams/Butler/Porzingis/Moody as 'out tonight' when none of them had
    played a single game all season -- their absence was already baked into the whole L5/h2h sample, not new info.
    Returns True if this teammate has NOT played any real minutes since `since` (i.e. his absence is already priced in)."""
    rows = c.execute("select min, dnp from nba_box where player=? and date>=?", (teammate, since)).fetchall()
    return not any((m or 0) > 5 and not d for m, d in rows)


_ALLOWED = {}


def opp_allowed(c, expr, opp):
    """11/5 user: "pickfinder says 'allows 34 rebounds a game, ranked #23'". Per-game team total of this stat that
    opponents put up against `opp` this season, and its rank (1 = allows the MOST = softest)."""
    if expr not in _ALLOWED:
        per = collections.defaultdict(list)
        for o, v in c.execute(
                "select b.opp, sum(%s) from nba_box b join nba_games g on g.game_id=b.game_id where g.season='2026-27' "
                "and g.stype='regular' and (b.dnp=0 or b.dnp is null) group by b.game_id, b.team" % expr):
            if v is not None:
                per[o].append(v)
        avg = {o: sum(v) / len(v) for o, v in per.items() if v}
        order = sorted(avg, key=avg.get, reverse=True)
        _ALLOWED[expr] = (avg, {o: i + 1 for i, o in enumerate(order)}, len(order))
    avg, rk, n = _ALLOWED[expr]
    return (avg.get(opp), rk.get(opp), n) if opp in avg else None


def with_without(c, player, team, expr, teammate, line):
    """11/5 user: "they'll say add more rebounds bc so and so are out". His numbers this season + last (same team) in games
    the teammate PLAYED (5+ min) vs games he did NOT. Returns (avg_with, n_with, avg_without, n_without, over_without)."""
    rows = c.execute(
        "select b.game_id, %s from nba_box b join nba_games g on g.game_id=b.game_id where b.player=? and b.team=? "
        "and g.stype='regular' and g.season in ('2025-26','2026-27') and (b.dnp=0 or b.dnp is null) and b.min>0" % expr,
        (player, team)).fetchall()
    played = {r[0] for r in c.execute("select game_id from nba_box where player=? and team=? and min>5 and (dnp=0 or dnp is null)",
                                      (teammate, team))}
    w = [v for gid, v in rows if gid in played]; wo = [v for gid, v in rows if gid not in played]
    if not w or not wo:
        return None
    return (sum(w) / len(w), len(w), sum(wo) / len(wo), len(wo), sum(v > line for v in wo))


import os, json, unicodedata, re
_norm = lambda s: re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())
POS_F = "nba_positions.json"
POS_GROUP = {"PG": "G", "SG": "G", "G": "G", "SF": "F", "PF": "F", "F": "F", "C": "C"}


def positions():
    """player (normalized name) -> G / F / C, from ESPN team rosters, cached 3 days."""
    if os.path.exists(POS_F) and (datetime.datetime.now().timestamp() - os.path.getmtime(POS_F)) < 3 * 86400:
        return json.load(open(POS_F, encoding="utf-8"))
    import requests
    H = {"User-Agent": "Mozilla/5.0"}; out = {}
    teams = requests.get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams", headers=H, timeout=20).json()
    for t in teams["sports"][0]["leagues"][0]["teams"]:
        try:
            r = requests.get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/%s/roster" % t["team"]["id"], headers=H, timeout=20).json()
        except Exception:
            continue
        for a in r.get("athletes", []):
            g = POS_GROUP.get((a.get("position") or {}).get("abbreviation"))
            if g:
                out[_norm(a.get("displayName"))] = g
    json.dump(out, open(POS_F, "w", encoding="utf-8"))
    return out


_PVL = {}


def pos_vs_line(c, opp, stat, pos, me, before):
    """11/5 user (PickFinder feature): how every OTHER player at his position did vs his PP STANDARD line for this stat when
    facing `opp` this season. Closing line per player-game from the archive, graded off our box score. Not a gate."""
    if not os.path.exists(LINES_DB) or stat not in STAT:
        return None
    key = (stat,)
    if key not in _PVL:
        L = sqlite3.connect(LINES_DB)
        close = {}
        for pl, st, line, start, seen in L.execute(
                "select player, stat, line, start, last_seen from pp where league=7 and kind='standard' and stat=? and start>='2026-10-20'", (stat,)):
            d = datetime.datetime.fromisoformat(start).astimezone(CT).date().isoformat()
            k = (_norm(pl), d)
            if k not in close or (seen or "") > close[k][1]:
                close[k] = (line, seen or "")
        box = {}
        for d, pl, o, v in c.execute("select b.date, b.player, b.opp, %s from nba_box b join nba_games g on g.game_id=b.game_id where "
                                     "g.season='2026-27' and g.stype='regular' and (b.dnp=0 or b.dnp is null) and b.min>0" % STAT[stat]):
            box[(_norm(pl), d)] = (o, v, pl)
        rows = []
        for k, (line, _) in close.items():
            if k in box and box[k][1] is not None and box[k][1] != line:
                o, v, pl = box[k]
                rows.append(dict(opp=o, player=pl, n=k[0], date=k[1], line=line, v=v, over=v > line))
        _PVL[key] = rows
    P = positions()
    X = [r for r in _PVL[key] if r["opp"] == opp and r["date"] < before and r["n"] != _norm(me) and P.get(r["n"]) == pos]
    return X


def run(day):
    c = sqlite3.connect("sports.db")
    F.load_outs(c)
    legs = board(day)
    print("PICKFINDER METHOD %s -- %d standard lines on the board\n" % (day, len(legs)))
    passed = []
    for g in legs:
        e = STAT[g["stat"]]
        rows = c.execute(
            "select b.date,b.opp,round(b.min),%s,g.stype from nba_box b join nba_games g on g.game_id=b.game_id "
            "where b.player=? and (b.dnp=0 or b.dnp is null) and b.date>='2024-10-01' order by b.date" % e,
            (g["player"],)).fetchall()
        if not rows:
            continue
        cur = [r for r in rows if r[0] >= "2026-10-20" and r[4] == "regular"]
        if len(cur) < 5:
            continue
        # 10/30: season is young -- use L5 and L9/L10 (whatever's available up to 10, not a hard "must have 10" gate)
        l5 = cur[-5:]; l10 = cur[-10:]
        ln = g["line"]
        over5 = sum(r[3] > ln for r in l5); under5 = 5 - over5
        over10 = sum(r[3] > ln for r in l10); under10 = len(l10) - over10
        # STEP 1: L5 trend (4+/5) and L9/L10 trend (whatever games exist, strict majority) must agree
        side = None
        if over5 >= 4:
            side = "over"
        elif under5 >= 4:
            side = "under"
        else:
            continue
        l10_side = "over" if over10 > len(l10) / 2 else "under" if under10 > len(l10) / 2 else None
        if l10_side != side:
            continue
        # STEP 2: h2h (all seasons) agrees
        hh = [r[3] for r in rows if r[1] == g["opp"]]
        if len(hh) < 2:
            continue
        hok = (lambda v: v > ln) if side == "over" else (lambda v: v < ln)
        h2h_rate = sum(map(hok, hh)) / len(hh)
        if h2h_rate < 0.5:
            continue
        # STEP 3: zone defense agrees with direction
        # 11/5: shooting zones say nothing about rebounds/assists/steals/blocks -- Wendell Carter O8.5 REB vs PHX (#30 D, #28 oreb
        # allowed) was dropped for a neutral zone score. Non-shooting props skip the zone gate (shown as "zone: n/a").
        zb = None if g["stat"] in NON_SHOT else F.zone_boost(g["player"], g["opp"])
        if zb is None:
            zone_ok = None  # no data, don't block, just flag unknown
        elif side == "over":
            zone_ok = zb > 0.003
        else:
            zone_ok = zb < -0.003
        if zone_ok is False:
            continue
        zd = zone_detail(g["player"], g["opp"])
        own_fg = own_zone_fg(c, g["player"], ZONE_CLS) if zd else {}
        outs = F.OUTS.get(g["team"], [])
        new_outs = [t for t in outs if not teammate_already_out(c, t, "2026-10-20")]
        g.update(side=side, l5=[r[3] for r in l5], l10=[r[3] for r in l10], n_season=len(cur),
                 h2h=hh[-6:], h2h_rate=h2h_rate, zone=zb, zone_detail=zd, own_fg=own_fg,
                 status=F.STATUS.get(g["player"], "active"), teammates_out=outs, new_outs=new_outs)
        passed.append(g)
    print("%d players cleared steps 1-3 (L5+L10 same side, h2h agrees, zone not against)\n" % len(passed))
    for g in sorted(passed, key=lambda g: -g["h2h_rate"]):
        t = datetime.datetime.fromisoformat(g["start"]).astimezone(CT).strftime("%a %I:%M%p")
        flag = ""
        if g["status"] not in ("active", None):
            flag += "  [%s]" % g["status"]
        print("%-22s %s%-5s %-16s (%s v %s %s)%s" % (g["player"], g["side"][0].upper(), g["line"], g["stat"], g["team"], g["opp"], t, flag))
        teammate_note = "none"
        if g["teammates_out"]:
            already = [t for t in g["teammates_out"] if t not in g["new_outs"]]
            parts = []
            if g["new_outs"]:
                parts.append("NEW tonight: %s (check usage impact)" % ", ".join(g["new_outs"]))
            if already:
                parts.append("already out all season (priced into the sample, not new): %s" % ", ".join(already))
            teammate_note = "; ".join(parts)
        print("   L5 %s | L%d(season) %s | h2h vs %s %s (%.0f%%) | teammates OUT: %s" % (
            g["l5"], g["n_season"], g["l10"], g["opp"], g["h2h"], 100 * g["h2h_rate"], teammate_note))
        e = STAT[g["stat"]]
        oa = opp_allowed(c, e, g["opp"])
        if oa and oa[0] is not None:
            soft = oa[1] <= oa[2] / 3; tough = oa[1] > 2 * oa[2] / 3
            agree = (soft and g["side"] == "over") or (tough and g["side"] == "under")
            against = (tough and g["side"] == "over") or (soft and g["side"] == "under")
            print("   %s allows %.1f %s/game to opponents, #%d of %d (1 = allows the most)%s" % (
                g["opp"], oa[0], g["stat"].lower(), oa[1], oa[2], "  -> AGREES" if agree else "  -> AGAINST" if against else ""))
        pos = positions().get(_norm(g["player"]))
        X = pos_vs_line(c, g["opp"], g["stat"], pos, g["player"], day) if pos else None
        if X:
            ov = sum(r["over"] for r in X)
            lean = ov / len(X)
            tag = ("  -> AGREES" if (lean >= 0.6 and g["side"] == "over") or (lean <= 0.4 and g["side"] == "under") else
                   "  -> AGAINST" if (lean >= 0.6 and g["side"] == "under") or (lean <= 0.4 and g["side"] == "over") else "")
            ex = ", ".join("%s %s v %s" % ([w for w in r["player"].split() if w.rstrip(".") not in ("Jr", "Sr", "II", "III", "IV")][-1], ("%g" % r["v"]), r["line"]) for r in sorted(X, key=lambda r: r["date"])[-4:])
            print("   other %ss vs %s on PP %s lines: %d over / %d under%s   (%s)" % (
                {"G": "guard", "F": "forward", "C": "center"}[pos], g["opp"], g["stat"].lower(), ov, len(X) - ov, tag, ex))
        for tm in g["teammates_out"] or []:
            ww = with_without(c, g["player"], g["team"], e, tm, g["line"])
            if ww:
                print("   with %s: %.1f (%d g) | WITHOUT: %.1f (%d g), over %s in %d/%d" % (
                    tm, ww[0], ww[1], ww[2], ww[3], g["line"], ww[4], ww[3]))
        if g["zone_detail"]:
            for share, z, label, rk, n in g["zone_detail"]:
                fg = g["own_fg"].get(z)
                print("   shoots %s%% from %s (%.0f%% of his shots), %s ranks %d/%d defending %s" % (
                    ("%.0f" % (100 * fg)) if fg is not None else "?", label, 100 * share, g["opp"], rk, n, label))
        else:
            print("   zone: no data (low shot volume)")
        print()


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else datetime.datetime.now(CT).date().isoformat())
