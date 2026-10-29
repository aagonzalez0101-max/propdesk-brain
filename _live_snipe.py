"""LIVE SNIPER (10/28, user saw @UpsideTools "+EV Sniper": Betr live 2-man J. Allen O17.5 P+R / A. Davis U8.5 reb, $100 -> $300).

Mechanism: in-game, the books (FanDuel) re-price player props every few seconds; the DFS app's LIVE line lags. Bet the stale side.
    PrizePicks live = lines flagged is_live/in_game in the partner feed (10/28: only LAL-LAC carried them; other games leave the
    board at tip). FanDuel live = the same public event-page tabs, markets marked inPlay.
Every pass: each PP live STANDARD line vs FanDuel's in-play line on the same player/stat, moved to PP's number (_mismatch.p_over_at);
flag at 60%+ (PP 2-pick b/e 57.7%), phone push on each new flag, every flag logged to live_snipe.jsonl for grading.

    python -u _live_snipe.py [seconds=90]       # loop until stopped
Limits: PP's free feed is cached 3 min (429s otherwise) -- we see each PP move up to ~3 min late; FanDuel is live.
"""
import sys, os, json, time, datetime
import _xcheck as X, _mismatch as M, _single_check as SC, _ppcache

CT = datetime.timezone(datetime.timedelta(hours=-5))
LOG = "live_snipe.jsonl"


def pp_live():
    d = _ppcache.projections(7, 170)
    P = {i["id"]: i["attributes"] for i in d.get("included", []) if i["type"] == "new_player"}
    for x in d["data"]:
        a = x["attributes"]
        if a.get("odds_type") != "standard" or not (a.get("is_live") or a.get("in_game")):
            continue
        c = X.PP_STAT.get(a["stat_type"].lower())
        if c:
            p = P.get(x["relationships"]["new_player"]["data"]["id"], {})
            yield dict(player=p.get("name"), team=p.get("team"), stat=a["stat_type"], canon=c, line=float(a["line_score"]),
                       updated=a.get("updated_at"), game=a.get("description"))


def fd_live():
    S = {}
    for (pl, st), q in SC.nba_board().items():
        c = X.FD_NBA.get(st)
        for ln, (o, u) in (q["ou"].items() if c else []):
            if o is not None and u is not None:
                S.setdefault((pl, c), []).append((ln, X.two_way(X.M_imp(o), X.M_imp(u)), o if True else None, u))
    return S


def one_pass(seen, push):
    legs = list(pp_live())
    if not legs:
        return 0, 0
    F = fd_live()
    flags = []
    for g in legs:
        rows = F.get((X.norm(g["player"]), g["canon"]))
        if not rows:
            continue
        po = X.p_at([(l, p) for l, p, *_ in rows], g["line"], g["canon"])
        if po is None:
            continue
        side, p = ("OVER", po) if po >= .5 else ("UNDER", 1 - po)
        fl, _, o, u = min(rows, key=lambda r: abs(r[0] - g["line"]))
        if p >= .60:
            flags.append(dict(g, side=side, p=round(p, 3), fd_line=fl, fd_over=o, fd_under=u))
    stamp = datetime.datetime.now(CT).strftime("%H:%M:%S")
    new = [f for f in flags if (f["player"], f["stat"], f["line"], f["side"]) not in seen]
    for f in new:
        seen.add((f["player"], f["stat"], f["line"], f["side"]))
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(dict(f, ts=stamp, day=datetime.datetime.now(CT).date().isoformat()), ensure_ascii=False) + "\n")
        print("%s SNIPE %-20s %-5s %5s %-16s PP %s vs FanDuel live %s (o %+d / u %+d) -> %.0f%%" % (
            stamp, f["player"], f["side"], f["line"], f["stat"], f["line"], f["fd_line"], f["fd_over"], f["fd_under"], 100 * f["p"]), flush=True)
    if push and new:
        import _push
        _push.push("LIVE SNIPE (%d)" % len(new), "\n".join("%s %s %s %s -- FanDuel live %s, %.0f%%" % (
            f["player"], f["side"], f["line"], f["stat"], f["fd_line"], 100 * f["p"]) for f in new[:6]))
    return len(legs), len(flags)


# ------------------------------------------------------------------------------------------------------------------------------
# HALFTIME 2H SNIPE (10/28): PP's feed has no true in-game lines (is_live is only on demons), but it posts 2H lines (league 80) that
# trade through halftime. FanDuel's in-play FULL-GAME line minus the player's 1H = the book's implied 2H number. Same flag rule.
ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
H2 = {"points": lambda s: s["pts"], "pts+rebs+asts": lambda s: s["pts"] + s["reb"] + s["ast"]}
H2_CANON = {"points": "points", "pts+rebs+asts": "pts & rebs & asts"}


def espn_halftime():
    """{normalized player: {pts, reb, ast, team}} for every game at HALFTIME right now"""
    import requests
    out = {}
    sb = requests.get(ESPN + "/scoreboard", headers=X.H, timeout=20).json()
    for e in sb.get("events", []):
        st = e["status"]["type"]
        if not (st.get("shortDetail") == "Halftime" or (e["status"].get("period") == 2 and st.get("name") == "STATUS_END_PERIOD")):
            continue
        s = requests.get(ESPN + "/summary?event=" + e["id"], headers=X.H, timeout=20).json()
        for t in s.get("boxscore", {}).get("players", []):
            for blk in t["statistics"]:
                for a in blk["athletes"]:
                    if a.get("stats"):
                        d = dict(zip(blk["keys"], a["stats"]))
                        out[X.norm(a["athlete"]["displayName"])] = dict(pts=int(d.get("points", 0)), reb=int(d.get("rebounds", 0)),
                                                                        ast=int(d.get("assists", 0)), team=t["team"]["abbreviation"])
    return out


def halftime_pass(seen, push):
    HT = espn_halftime()
    if not HT:
        return 0, 0
    d = _ppcache.projections(80, 170)
    P = {i["id"]: i["attributes"] for i in d.get("included", []) if i["type"] == "new_player"}
    F = fd_live(); flags = []; n = 0
    for x in d["data"]:
        a = x["attributes"]; k = a["stat_type"].lower()
        if a.get("odds_type") != "standard" or k not in H2:
            continue
        p = P.get(x["relationships"]["new_player"]["data"]["id"], {}); nm = X.norm(p.get("name"))
        h1 = HT.get(nm); rows = F.get((nm, H2_CANON[k]))
        if not h1 or not rows:
            continue
        n += 1
        L2 = float(a["line_score"]); done = H2[k](h1)
        po = X.p_at([(l, q) for l, q, *_ in rows], L2 + done, H2_CANON[k])     # 2H over L2  ==  final over L2 + 1H
        if po is None:
            continue
        side, pr = ("OVER", po) if po >= .5 else ("UNDER", 1 - po)
        fl, _, o, u = min(rows, key=lambda r: abs(r[0] - (L2 + done)))
        if pr >= .60:
            flags.append(dict(player=p.get("name"), stat="2H " + a["stat_type"], line=L2, side=side, p=round(pr, 3), h1=done,
                              fd_line=fl, fd_over=o, fd_under=u, implied_2h=round(fl - done, 1)))
    stamp = datetime.datetime.now(CT).strftime("%H:%M:%S")
    new = [f for f in flags if (f["player"], f["stat"], f["line"], f["side"]) not in seen]
    for f in new:
        seen.add((f["player"], f["stat"], f["line"], f["side"]))
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(dict(f, ts=stamp, day=datetime.datetime.now(CT).date().isoformat(), kind="2H"), ensure_ascii=False) + "\n")
        print("%s 2H SNIPE %-20s %-5s %5s %-18s 1H %s | FanDuel live full game %s -> implied 2H %s -> %.0f%%" % (
            stamp, f["player"], f["side"], f["line"], f["stat"], f["h1"], f["fd_line"], f["implied_2h"], 100 * f["p"]), flush=True)
    if push and new:
        import _push
        _push.push("2H SNIPE (%d)" % len(new), "\n".join("%s %s %s %s -- book implies %s, %.0f%%" % (
            f["player"], f["side"], f["line"], f["stat"], f["implied_2h"], 100 * f["p"]) for f in new[:6]))
    return n, len(flags)


if __name__ == "__main__":
    every = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    seen = set()
    while True:
        for f, lab in ((one_pass, "PP live"), (halftime_pass, "2H at halftime")):
            try:
                n, k = f(seen, push=True)
                if n:
                    print("%s %s: %d lines checked, %d at 60%%+" % (datetime.datetime.now(CT).strftime("%H:%M:%S"), lab, n, k), flush=True)
            except Exception as e:
                print("live_snipe %s error: %s" % (lab, str(e)[:150]), flush=True)
        time.sleep(every)
