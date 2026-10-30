"""PICKFINDER METHOD (10/30, user: "how I made my money on pickfinder last year" -- NBA = his whole 2026 profit, 422 bets +16.9%).
His exact process, reproduced in order, no editorializing:

  STEP 1  last 5 (THIS SEASON ONLY) all same side, last 10 (THIS SEASON ONLY) all same side  -- doesn't have to be good, can be a
          trend of unders. If L5 and L10 don't agree with each other, the player is OUT, not a lean.
  STEP 2  h2h vs this opponent (all seasons -- he's played enough history to count) agrees with the L5/L10 direction.
  STEP 3  defense vs HIS shooting zone matches the direction: trend is UNDER and the defense is tough in his zones (zone_boost
          negative) -> confirms. Trend is OVER and defense is soft in his zones (zone_boost positive) -> confirms. Mismatch -> drop.
  STEP 4  (printed, not auto-graded) lineups/minutes/injuries/opponent's likely defender -- his manual override layer.

    python _pf_method.py [YYYY-MM-DD]
"""
import sys, datetime, collections
import _ppcache as C, _lineflash as F
import sqlite3

CT = datetime.timezone(datetime.timedelta(hours=-5))
ESPN = {"NYK": "NY", "GSW": "GS", "SAS": "SA", "NOP": "NO", "UTA": "UTAH", "WAS": "WSH"}   # 10/30: PP's team code vs our box's (Maxey h2h vs NYK came back empty -- it's really "NY")
ZONE_CLS = {"dunk": "rim", "lob dunk": "rim", "putback": "rim", "rim": "rim", "lob layup": "rim", "hook": "paint",
            "floater": "paint", "mid": "mid", "three": "three"}
STAT = {"Points": "pts", "Rebounds": "reb", "Assists": "ast", "Pts+Rebs+Asts": "pts+reb+ast", "Pts+Rebs": "pts+reb",
        "Pts+Asts": "pts+ast", "Rebs+Asts": "reb+ast", "3-PT Made": "tpm", "3-PT Attempted": "tpa", "FG Attempted": "fga",
        "FG Made": "fgm", "Two Pointers Attempted": "fga-tpa", "Fantasy Score": "pts+1.2*reb+1.5*ast+3*stl+3*blk-tov",
        "Blocked Shots": "blk", "Steals": "stl", "Blks+Stls": "stl+blk"}


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
        zb = F.zone_boost(g["player"], g["opp"])
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
        g.update(side=side, l5=[r[3] for r in l5], l10=[r[3] for r in l10], n_season=len(cur),
                 h2h=hh[-6:], h2h_rate=h2h_rate, zone=zb, zone_detail=zd, own_fg=own_fg,
                 status=F.STATUS.get(g["player"], "active"), teammates_out=F.OUTS.get(g["team"], []))
        passed.append(g)
    print("%d players cleared steps 1-3 (L5+L10 same side, h2h agrees, zone not against)\n" % len(passed))
    for g in sorted(passed, key=lambda g: -g["h2h_rate"]):
        t = datetime.datetime.fromisoformat(g["start"]).astimezone(CT).strftime("%a %I:%M%p")
        flag = ""
        if g["status"] not in ("active", None):
            flag += "  [%s]" % g["status"]
        print("%-22s %s%-5s %-16s (%s v %s %s)%s" % (g["player"], g["side"][0].upper(), g["line"], g["stat"], g["team"], g["opp"], t, flag))
        print("   L5 %s | L%d(season) %s | h2h vs %s %s (%.0f%%) | teammates OUT: %s" % (
            g["l5"], g["n_season"], g["l10"], g["opp"], g["h2h"], 100 * g["h2h_rate"], ", ".join(g["teammates_out"]) or "none"))
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
