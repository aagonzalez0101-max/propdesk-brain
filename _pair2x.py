"""STANDARD + GOBLIN "2x" PAIRS (2026-10-09, user: "always choose the best MISPRICED standard with data from our model, then the
best goblin you decide -- that's how we get the 2x's").
  standard leg = our model's edge: today's direction-filter picks (direction_paper.jsonl, 3+ reasons, 0 against), the CS2 high-line
                 under filter, re-checked against the LIVE PrizePicks board (PP line first, then sharps; a sharp book that disagrees
                 by 5+ pts drops the leg)
  goblin leg   = the highest sharp-priced goblin (Pinnacle/FanDuel at PP's exact number) from a DIFFERENT game and team
  value        = p_std x p_gob x payout - 1; bet only if the app's payout >= 1 / (p_std x p_gob) + ~5% cushion.
    python _pair2x.py
"""
import json, datetime, os, re, subprocess, sys, collections
import _props as P, _mismatch as M

try:                                                    # 10/10 user: everything in Texas time (Central, DST-aware)
    from zoneinfo import ZoneInfo
    CT = ZoneInfo("America/Chicago")
except Exception:
    CT = datetime.timezone(datetime.timedelta(hours=-5))
now = datetime.datetime.now(datetime.timezone.utc)
today = datetime.datetime.now(CT).date().isoformat()
LG = {"NHL": 8, "WNBA": 3, "NBA": 7, "NFL": 9, "CFB": 15, "CS2": 265, "SOCCER": 82, "NBAP": 237}

# live PP standard board
live = {}
import time as _time
_board_fail = []
for sp, lg in LG.items():
    # 10/14: the 7:45 cloud card found 2 legs vs 84 locally -- PrizePicks 429'd the NFL/NBA boards and each failure silently left that
    # league EMPTY. Retry with backoff (30s / 60s / 90s) before giving up, and say loudly which boards are missing.
    for _try in range(4):
        try:
            _bd = P.prizepicks(lg, max_age=int(os.environ.get("PP_MAX_AGE", 180)))                      # 429s at max_age=0 -> a 3-minute-old board is fine
            for l in _bd:
                if l.get("kind") == "standard" and "+" not in (l.get("player") or ""):
                    live[(sp, M.norm(l["player"]), M.norm(l["stat"]))] = l
            break
        except Exception as e:
            print(sp, "pp (try %d):" % (_try + 1), e)
            if _try < 3:
                _time.sleep(30 * (_try + 1))
            else:
                _board_fail.append(sp)
    _time.sleep(3)
print("PP boards loaded: %s%s" % (dict(collections.Counter(k[0] for k in live)), ("  MISSING: %s" % _board_fail) if _board_fail else ""))

# 10/9 user: "nobody that we've used" -> skip every player already in an OPEN bet in the ledger
USED = set()
for x in open("live_paper.jsonl", encoding="utf-8"):
    r = json.loads(x)
    if r.get("result") is None and r.get("kind") == "LIVE":
        for lg_ in r.get("legs") or []:
            if lg_.get("player"):
                USED.add(M.norm(lg_["player"]))
print("skipping players already in open bets:", len(USED))
std = []
if os.path.exists("direction_paper.jsonl"):
    for x in open("direction_paper.jsonl", encoding="utf-8"):
        r = json.loads(x)
        if r["date"] < today or r.get("result"):
            continue
        if M.norm(r["player"]) in USED:
            continue
        l = live.get((r["sport"], M.norm(r["player"]), M.norm(r["stat"])))
        if not l or l["line"] != r["line"] or datetime.datetime.fromisoformat(l["start"]).astimezone(datetime.timezone.utc) < now:
            continue                                                   # not on PP at this number right now -> not a leg
        fl = __import__("_arch").first_line(l["player"], l["stat"], l["start"][:10])
        raised = fl is not None and l["line"] > fl
        std.append(dict(sport=r["sport"], player=r["player"], team=r.get("team"), opp=r.get("opp"), stat=r["stat"], line=r["line"], side=r["side"],
                        p=r["p"], why="%d reasons: %s%s" % (r.get("agree", 3), r.get("why", ""), (" | PP RAISED %s->%s (paper: over 62%%)" % (fl, l["line"])) if raised else ""),
                        start=l["start"], img=l.get("img")))
# CS2: ONLY the measured rule (10/10 user: "I don't want off-the-books bets"). cs2_paper picks with model edge 3-9% (the band that hit
# 62% / 68.2% when the map is not a coin flip); bigger edges are the WORST legs (top-of-card 22-50%) and are never carded.
# The old "high-line under" shortcut (flat p=0.62, unmeasured) is gone -- it put 13-16% edge legs on the 10/10 card.
seen_cs = set()
# 10/11: with 874 graded band legs the CS2 band hits 52.7% -- BELOW the 55% a 3-pick needs (the 56.8% was a smaller sample).
# CS2 is PAPER: still projected, logged and graded by _cs2_live / _cs2_grade, but not carded for money unless CS2_LIVE=1.
# 10/16 user ("for CFB look for mismatches ... backtest like we did with NFL"): the NFL own-rate rule FAILS in CFB (48-50% on 1,757 lines --
# schedules swing too much). What works is the SHARP MISMATCH: on 325 graded PP CFB lines with a FanDuel/Pinnacle price, the side the sharp
# books made 55%+ hit 64.5% (n=152, halves 66/63); 58%+ hit 69.1% (n=94, halves 74/64); 65%+ 82.9% (n=35). PP closes these gaps within hours
# (10/16: Brown-Stephens 26.5 -> 31.5, Lawson 46.5 -> 56.5), so the price is taken at PP's CURRENT line. BET (backtested, user 10/15 rule).
try:
    import sqlite3 as _sq5, bisect as _bs5
    # 10/17 CORRECTED: priced at PP's exact line INSIDE the sharp ladder (no extrapolation -- a one-rung extrapolation produced fake 100% legs
    # and a fake "receiving yards 74%"): RUSH YARDS sharp 57%+ -> 85% (n=34, halves 82/88), 62%+ -> 90%; PASS YARDS 55%+ -> 75% (n=16);
    # RECEIVING YARDS 57%+ -> 56% (halves 71/41, fading); RECEPTIONS 32%. QBs excluded from rush yards (sacks count as rushing -- Stokes 10/16).
    _SMAP5 = {"Rush Yards": "rushing yards", "Pass Yards": "passing yards"}
    _SH5 = collections.defaultdict(list)
    for _bk, _pl, _st, _ln, _po, _ts in _sq5.connect("lines.db", timeout=60).execute(
            "select book, player, stat, line, p_over, ts from sharp where sport='CFB' and ts >= ?", ((datetime.datetime.now(CT) - datetime.timedelta(days=2)).isoformat()[:10],)):
        _SH5[(M.norm(_pl), _st.lower())].append((_ts, float(_ln), float(_po)))
    _QB5 = set()
    for _pl5, _js5 in _sq5.connect("sports.db").execute("select player, stats from player_games where sport='CFB' and date >= '2026-08-01'"):
        if float(json.loads(_js5).get("att") or 0) >= 8:
            _QB5.add(M.norm(_pl5))
    _cfb_is_qb = lambda pl: M.norm(pl) in _QB5
    def _cfb_fair(pl, stat, line):
        R = _SH5.get((M.norm(pl), _SMAP5.get(stat, "-")))
        if not R:
            return None
        last = max(r[0] for r in R)[:13]
        pts = sorted({(l_, p_) for t_, l_, p_ in R if t_[:13] == last})
        xs = [l_ for l_, _ in pts]
        if not xs or line < xs[0] or line > xs[-1]:
            return None
        i = _bs5.bisect_left(xs, line)
        if xs[i] == line:
            return pts[i][1]
        (l0, p0), (l1, p1) = pts[i - 1], pts[i]
        return p0 + (p1 - p0) * (line - l0) / (l1 - l0)
    _n5 = 0
    for (sp, pl, st), l in live.items():
        if sp != "CFB" or l.get("kind") != "standard" or l["stat"] not in _SMAP5:
            continue
        if l["stat"] == "Rush Yards" and (l.get("position") == "QB" or _cfb_is_qb(l["player"])):
            continue
        if datetime.datetime.fromisoformat(l["start"]).astimezone(datetime.timezone.utc) < now:
            continue
        po = _cfb_fair(l["player"], l["stat"], l["line"])
        if po is None or max(po, 1 - po) < 0.57:
            continue
        side = "over" if po >= 0.5 else "under"; ps = max(po, 1 - po)
        std.append(dict(sport="CFB", cfb_sharp=True, player=l["player"], team=l.get("team"), opp=l.get("opp"), stat=l["stat"], line=l["line"], side=side,
                        p=0.80 if ps >= 0.62 else 0.75, start=l["start"], img=l.get("img"),
                        why="CFB SHARP MISMATCH (%s): FanDuel/Pinnacle make %s %g %.0f%% (backtest rush yds 57%%+ -> 85%%, pass yds 55%%+ -> 75%%)" % (l["stat"].lower(), side, l["line"], 100 * ps)))
        _n5 += 1
    print("CFB SHARP legs: %d" % _n5)
except Exception as e:
    print("cfb sharp:", e)

# 10/16 user ("we'll only really use 1-2 lines from any esport -- choose the best of the best"): CS2 POTD. Backtest, 1,801 graded
# standard CS2 legs over 29 days: the ONE leg a day with the biggest projection gap (model mean vs line) went 19-10 (65.5%, halves 71/60);
# the 2nd leg drops it to ~55%, and the old edge 3-9% band went 43-45% as a top pick. So: one CS2 leg a day, biggest gap, PP line at
# least as good as the one priced. Esports stays PAPER (user 10/15) until CS2_LIVE=1; logged to cs2_potd.jsonl and graded nightly.
if os.path.exists("cs2_paper.jsonl"):
    _cands = {}
    for x in open("cs2_paper.jsonl", encoding="utf-8"):
        r = json.loads(x)
        if str(r.get("start", ""))[:10] < today or r.get("maps") != 2 or r.get("mult") not in (None, 1.0) or not r.get("model_mu"):
            continue
        if datetime.datetime.fromisoformat(r["start"].replace("Z", "+00:00")) < now or M.norm(r["player"]) in USED:
            continue
        stat = "MAPS 1-2 Headshots" if r.get("kind") == "hs" else "MAPS 1-2 Kills"
        l = live.get(("CS2", M.norm(r["player"]), M.norm(stat)))
        side = "over" if r.get("side") == "higher" else "under"
        if not l or l.get("kind", "standard") != "standard" or (side == "over" and l["line"] > r["line"]) or (side == "under" and l["line"] < r["line"]):
            continue                                                   # PP number must be as good as the one the model priced
        g_ = (r["model_mu"] - l["line"]) / l["line"] * (1 if side == "over" else -1)
        if g_ <= 0:
            continue
        _cands[(r["player"], stat)] = (g_, r, l, stat, side)
    for g_, r, l, stat, side in sorted(_cands.values(), key=lambda t: -t[0])[:1]:
        std.append(dict(sport="CS2", cs2_potd=True, paper=os.environ.get("CS2_LIVE") != "1", player=r["player"], team=r.get("team"), opp=r.get("opp"), stat=stat,
                        line=l["line"], side=side, p=0.65, start=l["start"], img=l.get("img"), proj=round(r["model_mu"], 1),
                        proj_why="CS2 model: map-by-map kills/HS x expected rounds", gap=round(g_, 3),
                        why="CS2 POTD: biggest projection gap on the board (%.0f%%) -- backtest top-1/day 19-10 (65.5%%)" % (100 * g_)))
        try:
            _seen_p = {json.loads(x_)["date"] for x_ in open("cs2_potd.jsonl", encoding="utf-8")} if os.path.exists("cs2_potd.jsonl") else set()
            if today not in _seen_p:                          # 10/17: ONE pick of the day -- the first one stands (7 got logged 10/16-17)
                with open("cs2_potd.jsonl", "a", encoding="utf-8") as _pf:
                    _pf.write(json.dumps(dict(date=today, player=r["player"], team=r.get("team"), opp=r.get("opp"), match_id=r.get("match_id"), kind=r.get("kind"),
                                              stat=stat, line=l["line"], side=side, proj=round(r["model_mu"], 1), gap=round(g_, 3), start=l["start"], result=None), ensure_ascii=False) + chr(10))
        except Exception as e:
            print("cs2 potd log:", e)
        print("  CS2 POTD: %s %s %g %s (proj %.1f, gap %.0f%%)" % (r["player"], side, l["line"], stat, r["model_mu"], 100 * g_))

# NFL BETA (10/10, user: "make NFL work, I'm not taking another week without it"). Measured on 1,067 graded PP lines (Week 4-5 2026):
# when a player's OWN 2026 games went the same way vs THIS line >= 75% of the time (2+ games), that side hit 61.3% (n=326) --
# but the Week-5 holdout was 48.9% (n=47). Unproven -> carded as NFL BETA (tagged), graded every Monday, promoted only if Week 6 holds.
try:
    import sqlite3 as _sq, statistics as _st
    _f = lambda s_, k: float(s_.get(k) or 0)
    NFL_STAT = {"Pass Yards": lambda s_: _f(s_, "passing_yards"), "Rush Yards": lambda s_: _f(s_, "rushing_yards"),
                "Receiving Yards": lambda s_: _f(s_, "receiving_yards"), "Receptions": lambda s_: _f(s_, "receptions"),
                "Rush Attempts": lambda s_: _f(s_, "carries"), "Pass Attempts": lambda s_: _f(s_, "attempts"),
                "Pass Completions": lambda s_: _f(s_, "completions"), "Rush+Rec Yds": lambda s_: _f(s_, "rushing_yards") + _f(s_, "receiving_yards"),
                "Fantasy Score": lambda s_: 0.04 * _f(s_, "passing_yards") + 4 * _f(s_, "passing_tds") - _f(s_, "interceptions")
                + 0.1 * (_f(s_, "rushing_yards") + _f(s_, "receiving_yards")) + 6 * (_f(s_, "rushing_tds") + _f(s_, "receiving_tds")) + _f(s_, "receptions")}
    _db = _sq.connect("sports.db"); _NG = {}
    for _pl, _js, _d in _db.execute("select player, stats, date from player_games where sport='NFL' and season='2026'"):
        _NG.setdefault(M.norm(_pl), []).append((int(_d[1:]), json.loads(_js)))
    # 10/13: sports.db lagged a week (Juwan Johnson read 4-of-4 over; his 16-yd week 5 was missing) -> the nflverse weekly file
    # (refreshed by _nfl_beta_grade.py every morning) wins for any week it has
    try:
        import csv as _csv
        if os.path.exists("nfl_2026_weekly.csv"):
            _have = {(k, w) for k, v in _NG.items() for w, _ in v}
            for _r in _csv.DictReader(open("nfl_2026_weekly.csv", encoding="utf-8")):
                if _r.get("season_type", "REG") != "REG":
                    continue
                _k, _w = M.norm(_r["player_display_name"]), int(_r["week"])
                _r = dict(_r, interceptions=_r.get("passing_interceptions"))
                if (_k, _w) in _have:
                    _NG[_k] = [(w, (_r if w == _w else g)) for w, g in _NG[_k]]
                else:
                    _NG.setdefault(_k, []).append((_w, _r))
    except Exception as e:
        print("nfl weekly merge:", e)
    # 10/10: Shipley U9.5 (Barkley OUT, Bigsby IR -> Shipley leads the backfield) and Coleman U18.5 (WR Douglas OUT) were role-change traps.
    # Injury context first: no NFL UNDER when a same-team, same-position teammate is Out / Doubtful / IR this week.
    _OUTPOS = set()
    try:
        import requests as _rq
        _abbr = {}
        for _t in _rq.get("https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams", timeout=30).json()["sports"][0]["leagues"][0]["teams"]:
            _abbr[_t["team"]["displayName"]] = _t["team"]["abbreviation"]
        for _t in _rq.get("https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries", timeout=30).json().get("injuries", []):
            for _i in _t.get("injuries", []):
                if (_i.get("status") or "") in ("Out", "Doubtful", "Injured Reserve"):
                    _OUTPOS.add((_abbr.get(_t.get("displayName"), ""), ((_i.get("athlete") or {}).get("position") or {}).get("abbreviation")))
    except Exception as e:
        print("NFL injuries:", e)
    _FIX = {"WSH": "WAS", "JAC": "JAX", "LA": "LAR"}
    n_nfl = 0
    for (sp, pl, st), l in live.items():
        if sp != "NFL" or l["stat"] not in NFL_STAT or pl in USED or l.get("kind") != "standard":
            continue
        if datetime.datetime.fromisoformat(l["start"]).astimezone(datetime.timezone.utc) < now:
            continue
        games = sorted(_NG.get(pl, []), key=lambda t: t[0])
        if len(games) < 3 or l["line"] < 2.5:
            continue                                                   # tiny lines (0.5 rec) make every "margin" look huge
        if (games[-1][1].get("position") or "") in ("K", "P", ""):
            continue                                                   # kickers: our stats have no field goals -> fake fantasy 0s
        vals = [NFL_STAT[l["stat"]](g_) for _, g_ in games]
        hit = sum(v > l["line"] for v in vals) / len(vals); avg = _st.mean(vals)
        # strongest measured version only: EVERY 2026 game went that way (63.5%, n=285) and the average sits 15%+ off the line
        if hit == 1.0 and avg >= l["line"] * 1.15:
            side = "over"
        elif hit == 0.0 and avg <= l["line"] * 0.85:
            side = "under"
        else:
            continue
        _pos = games[-1][1].get("position")
        if side == "under" and ((_FIX.get(l.get("team"), l.get("team")), _pos) in _OUTPOS or (l.get("team"), _pos) in _OUTPOS):
            print("  dropped (role change: a %s %s teammate is out): %s %s under %s" % (l.get("team"), _pos, l["player"], l["stat"], l["line"]))
            continue
        if l["stat"] == "Fantasy Score":                # 10/11 Hutchinson: no Pinnacle FS market -> implied FS from FanDuel catches + yards
            try:
                import _fanduel as _F2
                if "_FDP" not in globals():
                    globals()["_FDP"] = _F2.props("nfl")
                def _med(st_):
                    R_ = sorted((ln_, po_) for (a_, b_, ln_), po_ in _FDP.items() if a_ == pl and b_ == st_)
                    for (l0, p0), (l1, p1) in zip(R_, R_[1:]):
                        if p0 >= 0.5 >= p1:
                            return l0 + (l1 - l0) * (p0 - 0.5) / max(p0 - p1, 1e-9)
                    return None
                rec, ry, ru, py = _med("receptions"), _med("receiving yards"), _med("rushing yards"), _med("passing yards")
                if any(v is not None for v in (rec, ry, ru, py)):
                    impl = (rec or 0) + 0.1 * ((ry or 0) + (ru or 0)) + 0.04 * (py or 0)
                    if (side == "over" and impl < l["line"] * 0.95) or (side == "under" and impl > l["line"] * 1.05):
                        print("  dropped (FanDuel implied fantasy %.1f vs line %s): %s %s" % (impl, l["line"], l["player"], side))
                        with open("gate_drops.jsonl", "a", encoding="utf-8") as gf:      # graded nightly by _gate_grade.py (Hutchinson 10/11 would have been a winning drop)
                            gf.write(json.dumps(dict(date=today, sport="NFL", player=l["player"], stat=l["stat"], line=l["line"], model_side=side,
                                                     flip_side="under" if side == "over" else "over", reason="fanduel implied fantasy %.1f" % impl,
                                                     start=l.get("start"), result=None), ensure_ascii=False) + chr(10))
                        continue
            except Exception as e:
                print("fd fantasy:", e)
        own = hit if side == "over" else 1 - hit
        std.append(dict(sport="NFL", player=l["player"], team=l.get("team"), opp=l.get("opp"), stat=l["stat"], line=l["line"], side=side,
                        p=0.61, proj=round(avg, 1), proj_why="his 2026 average", why="NFL BETA own-rate: %d of %d games %s, avg %.1f (1 week measured: 61%%, holdout 49%%)"
                        % (round(own * len(vals)), len(vals), side, avg), start=l["start"], img=l.get("img"), beta=True))
        n_nfl += 1
    # cap: the 8 NFL legs furthest from their line (a flood of thin legs is how off-book slips get built)
    def gap(x):                                                        # margin in standard deviations of his own games
        vals_ = [NFL_STAT[x["stat"]](g_) for _, g_ in _NG.get(M.norm(x["player"]), [])]
        sd_ = max(_st.pstdev(vals_) if len(vals_) > 1 else 0, 0.25 * x["line"])
        return abs(_st.mean(vals_) - x["line"]) / sd_
    keepn = set(id(x) for x in sorted([x for x in std if x.get("beta")], key=gap, reverse=True)[:8])
    std = [x for x in std if not x.get("beta") or id(x) in keepn]
    print("NFL BETA legs: %d found, %d kept" % (n_nfl, len(keepn)))
    # paper-log every kept NFL BETA leg (graded when nflverse posts the week) -- this is how the beta earns or loses its place
    _seen = set()
    if os.path.exists("nfl_beta_paper.jsonl"):
        _seen = {(json.loads(x)["player"], json.loads(x)["stat"], json.loads(x)["start"]) for x in open("nfl_beta_paper.jsonl", encoding="utf-8")}
    with open("nfl_beta_paper.jsonl", "a", encoding="utf-8") as nf:
        for x in std:
            if x.get("beta") and (x["player"], x["stat"], x["start"]) not in _seen:
                nf.write(json.dumps(dict(logged=today, player=x["player"], team=x.get("team"), opp=x.get("opp"), stat=x["stat"], line=x["line"],
                                         side=x["side"], start=x["start"], why=x["why"], result=None), ensure_ascii=False) + chr(10))
except Exception as e:
    print("NFL beta:", e)

# 10/10 (sh1ro O31 vs MOUZ lost; MOUZ had held him under 4 of 5): the bet bar is value AND head-to-head AND form -- check them
# BEFORE carding. Drop a leg when, toward the call, the last 5 hit under 50%%, or vs this opponent (3+ games) hit under 40%%.
try:
    import _cardpost as _CP
    kept = []
    for s_ in std:
        S_ = _CP.stats_for(s_)
        if S_:
            l5 = S_["l10"][-5:]
            over_ = s_["side"] == "over"
            h5 = sum((g["v"] > s_["line"]) if over_ else (g["v"] < s_["line"]) for g in l5)
            why_drop = None
            if len(l5) >= 5 and h5 < 3:
                why_drop = "form %d of last 5" % h5
            elif S_["vs_n"] >= 3 and S_["vs_hit"] / S_["vs_n"] < 0.4:
                why_drop = "vs %s %d of %d" % (s_.get("opp"), S_["vs_hit"], S_["vs_n"])
            if why_drop:
                print("  dropped (%s): %s %s %s %s" % (why_drop, s_["player"], s_["stat"], s_["side"], s_["line"]))
                # 10/10 user: log every dropped leg BOTH ways on paper -- model side vs the flip -- to measure who is right
                _gk = "%s|%s|%s|%s|%s" % (today, s_["player"], s_["stat"], s_["line"], s_["side"])
                if "_GSEEN" not in globals():
                    globals()["_GSEEN"] = {"%s|%s|%s|%s|%s" % (d_["date"], d_["player"], d_["stat"], d_["line"], d_["model_side"])
                                           for d_ in (json.loads(x_) for x_ in open("gate_drops.jsonl", encoding="utf-8") if x_.strip())} if os.path.exists("gate_drops.jsonl") else set()
                if _gk in _GSEEN:
                    continue
                _GSEEN.add(_gk)
                with open("gate_drops.jsonl", "a", encoding="utf-8") as gf:
                    gf.write(json.dumps(dict(date=today, sport=s_["sport"], player=s_["player"], stat=s_["stat"], line=s_["line"],
                                             model_side=s_["side"], flip_side="under" if s_["side"] == "over" else "over", reason=why_drop,
                                             start=s_.get("start"), result=None), ensure_ascii=False) + chr(10))
                continue
        kept.append(s_)
    std = kept
except Exception as e:
    print("form/H2H check:", e)

# 10/11: Dota 2 legs join the ESPORTS paper pool (calibrated ~56%, paper until proven); today's/tomorrow's LEANs not started yet
try:
    import _calib_es as _CE
    if os.path.exists("dota_paper.jsonl"):
        _dseen = set()
        for x in open("dota_paper.jsonl", encoding="utf-8"):
            r = json.loads(x)
            if r.get("result") or not r.get("start") or (r["player"], r["line"]) in _dseen:
                continue
            if datetime.datetime.fromisoformat(r["start"]).astimezone(datetime.timezone.utc) < now:
                continue
            _dseen.add((r["player"], r["line"]))
            std.append(dict(sport="Dota2", paper=True, player=r["player"], team=r.get("team"), opp=r.get("opp"), stat="MAPS 1-2 Kills",
                            line=r["line"], side=r["side"], p=round(_CE.cal("dota", r.get("p")) or 0.56, 3),
                            why="Dota model %.0f%% -> real ~%.0f%% (paper)" % (100 * (r.get("p") or 0), 100 * (_CE.cal("dota", r.get("p")) or 0.56)), start=r["start"]))
except Exception as e:
    print("dota legs:", e)

# 10/11 user ("club is better than int" -- measured: club HIT 55-23, club HIT PASSES 42-15 = 73.7%): CLUB soccer HIT passes-attempted
# legs are a BET market. HIT is already club-only + under-only in _soccer.py; goalie-saves HITs (3-5) stay out. Leg p = the measured
# club-HIT rate (0.70), not the model's own number; the line must still be live on PP at the same number.
try:
    _sd = datetime.datetime.now(CT).date()
    for _day in (_sd, _sd + datetime.timedelta(days=1)):
        _bf = "_soccer_board_%s.json" % _day.isoformat()
        if not os.path.exists(_bf):
            continue
        for r in json.load(open(_bf, encoding="utf-8")):
            if r.get("verdict") != "HIT" or r.get("stat") != "Passes Attempted" or not r.get("start"):
                continue
            if datetime.datetime.fromisoformat(r["start"]).astimezone(datetime.timezone.utc) < now:
                continue
            lv = live.get(("SOCCER", M.norm(r["player"]), M.norm(r["stat"])))
            if not lv or float(lv["line"]) != float(r["line"]):
                print("  soccer HIT not live at %s: %s %s" % (r["line"], r["player"], r["stat"])); continue
            std.append(dict(sport="SOCCER", soccer_hit=True, player=r["player"], team=r.get("team"), opp=r.get("opp"), stat=r["stat"],
                            line=r["line"], side=r["side"], p=0.70, start=r["start"], proj=r.get("adj_avg") or r.get("avg"),
                            proj_why="last %d starts, adjusted for the opponent (%s; script %s)" % (r.get("n") or 15, r.get("factor_why") or "neutral", r.get("script") or "?"),
                            why="Club soccer HIT passes (measured 42-15, 73.7%%): %d of %d starts %s, avg %.1f" % (r.get("hits") or 0, r.get("n") or 0, r["side"], r.get("avg") or 0)))
            print("  SOCCER HIT leg: %s %s %s %s" % (r["player"], r["side"], r["line"], r["stat"]))
except Exception as e:
    print("soccer legs:", e)

# 10/11 user ("these were paper but you'd still say 0"): the NHL screen's UNDERS are a BET market -- graded 9/30-10/10 at standard
# payouts: TAKE UNDER 29-11 (72.5%), LEAN UNDER 58-34 (63%); its OVERS are 52% (no edge) and stay out. The screen prices Underdog
# lines, so a call counts only if PrizePicks has the same player+stat at the SAME or HIGHER line (equal or better for an under).
# Leg p = the measured tier rate, shaded down (TAKE 0.70, LEAN 0.62), not the model's own number.
try:
    _have = {M.norm(s_["player"]) for s_ in std}
    _days = {today, (datetime.date.fromisoformat(today) + datetime.timedelta(days=1)).isoformat()}
    _nu = {}
    for x in open("calls_log.jsonl", encoding="utf-8"):
        r = json.loads(x)
        if r.get("sport") != "NHL" or r.get("date") not in _days or r.get("call") not in ("TAKE UNDER", "LEAN UNDER") or not r.get("start"):
            continue
        if r.get("kind") not in (None, "standard"):
            continue
        _m = r.get("mult")
        if isinstance(_m, dict):
            _m = _m.get("under")
        if r.get("venue") == "UD" and _m is not None and not (0.85 <= _m <= 1.15):
            continue                                                   # shifted UD lines weren't in the measured record
        k = (M.norm(r["player"]), M.norm(r["stat"]))
        if k not in _nu or r["call"] == "TAKE UNDER":
            _nu[k] = r
    for (pn, sn), r in _nu.items():
        if pn in _have or datetime.datetime.fromisoformat(r["start"].replace("Z", "+00:00")).astimezone(datetime.timezone.utc) < now:
            continue
        lv = live.get(("NHL", pn, sn)) or (live.get(("NHL", pn, "goaliesaves")) if "save" in sn else None)
        if not lv or float(lv["line"]) < float(r["line"]):
            continue
        tk = r["call"] == "TAKE UNDER"
        std.append(dict(sport="NHL", nhl_under=True, player=lv["player"], team=lv.get("team") or r.get("team"), opp=lv.get("opp") or r.get("opp"),
                        stat=lv["stat"], line=lv["line"], side="under", p=0.70 if tk else 0.62, start=lv["start"],
                        proj=r.get("adj_mean") or r.get("avg"), proj_why="matchup-adjusted average (opponent + his role)",
                        why="NHL screen %s (measured %s): avg %s, h2h %s" % (r["call"], "29-11, 72.5%" if tk else "58-34, 63%", r.get("adj_mean") or r.get("avg"), r.get("h2h"))))
        _have.add(pn)
        print("  NHL UNDER leg: %s %s U%s (%s, called at %s)" % (lv["player"], lv["stat"], lv["line"], r["call"], r["line"]))
except Exception as e:
    print("nhl unders:", e)

# 10/13 user ("yes on the nba preseason"): NBA PRESEASON UNDERS. Graded model calls: TAKE UNDER 16-0, LEAN UNDER 4-2 (overs 101-151) --
# starters sit the 2nd half. A preseason UNDER call counts only when PrizePicks' preseason board (league 237) has the same player+stat at
# the same or HIGHER line. PAPER until the forward record (calls from 10/13 on) has 2+ graded days, 10+ legs, 65%+ -> then BET by itself.
def _nbap_live_switch():
    try:
        W_ = collections.defaultdict(lambda: [0, 0])
        for x in open("calls_log.jsonl", encoding="utf-8"):
            r = json.loads(x)
            if r.get("sport") == "NBA" and r.get("date", "") >= "2026-10-13" and r.get("call") in ("TAKE UNDER", "LEAN UNDER") and r.get("result") in ("W", "L"):
                W_[r["date"]][0] += r["result"] == "W"; W_[r["date"]][1] += 1
        w, n = sum(v[0] for v in W_.values()), sum(v[1] for v in W_.values())
        ok = len(W_) >= 2 and n >= 10 and w / n >= 0.65
        print("NBA preseason unders forward: %d-%d over %d days -> %s" % (w, n - w, len(W_), "BET" if ok else "PAPER"))
        return ok
    except Exception as e:
        print("nbap switch:", e); return False
NBAP_LIVE = _nbap_live_switch()
try:
    _have2 = {M.norm(s_["player"]) for s_ in std}
    _dd = {today, (datetime.date.fromisoformat(today) + datetime.timedelta(days=1)).isoformat()}
    _nb = {}
    for x in open("calls_log.jsonl", encoding="utf-8"):
        r = json.loads(x)
        if r.get("sport") != "NBA" or r.get("date") not in _dd or r.get("call") not in ("TAKE UNDER", "LEAN UNDER") or not r.get("start"):
            continue
        k_ = (M.norm(r["player"]), M.norm(r["stat"]))
        if k_ not in _nb or r["call"] == "TAKE UNDER":
            _nb[k_] = r
    for (pn, sn), r in _nb.items():
        lv = live.get(("NBAP", pn, sn))
        if pn in _have2 or not lv or float(lv["line"]) < float(r["line"]):
            continue
        if datetime.datetime.fromisoformat(lv["start"]).astimezone(datetime.timezone.utc) < now:
            continue
        tk = r["call"] == "TAKE UNDER"
        # 10/13 user: "the last preseason is fucked" -- starters stretch out in a team's last 2 preseason games (Curry 2025: 27 + 30 min after
        # 13-16 all preseason). Block the under for a STARTER (25+ min/g last season) there; bench players lose minutes in a dress rehearsal.
        try:
            import _nba_presched as _PS, _bball as _BBq
            _day0 = datetime.datetime.fromisoformat(lv["start"]).astimezone(CT).date().isoformat()
            if _PS.late_preseason(lv.get("team") or r.get("team"), _day0):
                _a0 = _BBq.roster("nba").get(M.norm(lv["player"]))
                _all0 = [g_ for g_ in (_BBq.logs("nba", _a0[0]) if _a0 else []) if not g_.get("pre")]
                _reg = [g_ for g_ in _all0 if g_.get("season") == 2026] or [g_ for g_ in _all0 if g_.get("season") == max((x["season"] for x in _all0), default=0)]   # Haliburton missed 2025-26
                # 10/15 audit: Lopez (bench, 11 mpg) 9 pts in 8 min, Dybantsa/Boozer rookies at 23.7/17 mpg slipped the 25-mpg cut ->
                # in a team's last 2 preseason games rotations are unpredictable for EVERYONE: no preseason unders there at all
                print("  preseason under blocked (late preseason, any role): %s %s" % (lv["player"], lv["stat"])); continue
        except Exception as e:
            print("presched:", e)
        _pj = r.get("adj_mean") or r.get("proj")
        if not tk and (_pj is None or _pj > 0.85 * float(lv["line"])):
            continue                     # 10/13: both preseason-under misses were LEANs within 15% of the line (Wemby 2.6 vs 3, McDaniels 19.9 vs 21.5)
        std.append(dict(sport="NBAP", nba_pre_under=True, paper=not NBAP_LIVE, player=lv["player"], team=lv.get("team") or r.get("team"), opp=lv.get("opp") or r.get("opp"),
                        stat=lv["stat"], line=lv["line"], side="under", p=0.72 if tk else 0.62, start=lv["start"], proj=_pj, proj_why="preseason rate x projected minutes",
                        why="NBA preseason %s (graded unders 20-2): proj %s vs line %s" % (r["call"], r.get("adj_mean") or r.get("proj"), lv["line"])))
        _have2.add(pn)
        print("  NBA PRESEASON UNDER leg: %s %s U%s (%s, called at %s)" % (lv["player"], lv["stat"], lv["line"], r["call"], r["line"]))
except Exception as e:
    print("nba preseason unders:", e)

# 10/14 user ("it was during the day bc i pushed you"): the PRESEASON BOX-SCORE scan that found Bronny / Horford / Curry, automated.
# Every NBA preseason PP line vs THIS preseason's games: under in every game (2+), minutes-x-rate projection <= 85% of the line;
# starters (25+ mpg last season played) blocked in a team's last 2 preseason games (dress rehearsal); bench players allowed.
try:
    import _bball as _BBx, _nba_presched as _PSx
    _ids_x = _BBx.roster("nba"); _haveX = {M.norm(s_["player"]) for s_ in std}; _nx = 0
    for (sp, pl, st), l in list(live.items()):
        if sp != "NBAP" or l.get("kind") != "standard" or pl in _haveX or l["line"] < 2.5:
            continue
        _stx = datetime.datetime.fromisoformat(l["start"])
        if _stx.astimezone(datetime.timezone.utc) < now:
            continue
        _pp = _BBx.COMBO.get(M.norm(l["stat"])); _ax = _ids_x.get(pl)
        if not _pp or not _ax:
            continue
        _LX = _BBx.logs("nba", _ax[0])
        _G = [g_ for g_ in _LX if g_.get("pre") and g_["date"] >= "2026-09-01" and g_["min"] > 0]
        if len(_G) < 2:
            continue
        _vals = [sum(g_[p_] for p_ in _pp) for g_ in _G]; _mins = [g_["min"] for g_ in _G]
        if not all(v_ < l["line"] for v_ in _vals):
            continue
        _w = [0.5, 0.3, 0.2][:len(_mins)]
        _proj = sum(_vals) / sum(_mins) * sum(wi * m_ for wi, m_ in zip(_w, _mins[::-1])) / sum(_w)
        if _proj > 0.85 * l["line"]:
            continue
        _reg = [g_ for g_ in _LX if not g_.get("pre")]
        _last = max((g_["season"] for g_ in _reg), default=0); _regl = [g_ for g_ in _reg if g_["season"] == _last]
        _mpg = sum(g_["min"] for g_ in _regl) / len(_regl) if _regl else 0
        _mpg = max(_mpg, sum(_mins) / len(_mins) * (25 / 24))     # 10/14: rookies (Caleb Wilson 29-32 min) have no last season -> preseason 24+ min = starter
        _dayx = _stx.astimezone(CT).date().isoformat()
        if _PSx.late_preseason(l.get("team"), _dayx):            # 10/15 audit: any role (see above)
            print("  preseason box under blocked (late preseason, any role): %s %s" % (l["player"], l["stat"])); continue
        std.append(dict(sport="NBAP", nba_pre_under=True, paper=not NBAP_LIVE, player=l["player"], team=l.get("team"), opp=l.get("opp"), stat=l["stat"],
                        line=l["line"], side="under", p=0.68, start=l["start"], proj=round(_proj, 1), proj_why="preseason per-minute rate x recent minutes",
                        why="Preseason box scan: %s in %s min this preseason (all under %s), proj %.1f; last-season %.0f mpg%s" % (
                            "/".join("%d" % v_ for v_ in _vals), "/".join("%d" % m_ for m_ in _mins), l["line"], _proj, _mpg,
                            " (bench, late preseason helps)" if _PSx.late_preseason(l.get("team"), _dayx) else "")))
        _haveX.add(pl); _nx += 1
    print("NBA preseason box-scan legs: %d" % _nx)
except Exception as e:
    print("preseason box scan:", e)

# 10/13 user ("add that now to the model"): NHL ROLE GUARD. Podkolzin U2.5 SOG was carded off last season (15.4 min, 1.7 SOG) while
# 2026-27 he plays 19.2 min with 3.4 SOG. Every NHL leg: this season's TOI vs last season's -- minutes UP 15%+ blocks an UNDER, minutes
# DOWN 15%+ blocks an OVER; and with 3+ games this season, a leg whose side lost in 60%+ of them is blocked. Drops -> gate_drops.jsonl.
_NHL_ROLE = {}
def _nhl_role(player):
    if player in _NHL_ROLE:
        return _NHL_ROLE[player]
    out = None
    try:
        import requests as _rq3
        _s = _rq3.get("https://search.d3.nhle.com/api/v1/search/player", params=dict(culture="en-us", limit=5, q=player), timeout=20).json()
        _s = next((x for x in _s if M.norm(x.get("name")) == M.norm(player)), _s[0] if _s else None)
        if _s:
            _logs = {}
            for _sea in ("20262027", "20252026"):
                _logs[_sea] = _rq3.get("https://api-web.nhle.com/v1/player/%s/game-log/%s/2" % (_s["playerId"], _sea), timeout=20).json().get("gameLog", [])
            _t = lambda L: sum(int(r["toi"].split(":")[0]) + int(r["toi"].split(":")[1]) / 60 for r in L) / len(L) if L else None
            out = dict(cur=_logs["20262027"], toi_now=_t(_logs["20262027"]), toi_last=_t(_logs["20252026"]))
    except Exception as e:
        print("nhl role lookup:", player, e)
    _NHL_ROLE[player] = out
    return out
_NHLK = {"shotsongoal": "shots", "points": "points", "assists": "assists", "goals": "goals", "hits": "hits", "blockedshots": "blockedShots"}
_kept_nr = []
for s_ in std:
    if s_["sport"] != "NHL" or s_.get("promo"):
        _kept_nr.append(s_); continue
    R_ = _nhl_role(s_["player"])
    why_ = None
    if R_ and R_["toi_now"] and R_["toi_last"]:
        ratio = R_["toi_now"] / R_["toi_last"]
        if s_["side"] == "under" and ratio >= 1.15:
            why_ = "role up: TOI %.1f -> %.1f" % (R_["toi_last"], R_["toi_now"])
        elif s_["side"] == "over" and ratio <= 0.85:
            why_ = "role down: TOI %.1f -> %.1f" % (R_["toi_last"], R_["toi_now"])
    k_ = _NHLK.get(M.norm(s_["stat"]))
    if not why_ and R_ and k_ and len(R_["cur"]) >= 3:
        v_ = [r.get(k_) or 0 for r in R_["cur"]]
        lost = sum((x > s_["line"]) if s_["side"] == "under" else (x < s_["line"]) for x in v_)
        if lost / len(v_) >= 0.60:
            why_ = "this season %d of %d games went the other way" % (lost, len(v_))
    if why_:
        print("  dropped (NHL role guard, %s): %s %s %s %s" % (why_, s_["player"], s_["stat"], s_["side"], s_["line"]))
        try:
            with open("gate_drops.jsonl", "a", encoding="utf-8") as gf:
                gf.write(json.dumps(dict(date=today, sport="NHL", player=s_["player"], stat=s_["stat"], line=s_["line"], model_side=s_["side"],
                                         flip_side="over" if s_["side"] == "under" else "under", reason="role guard: " + why_, start=s_.get("start"), result=None), ensure_ascii=False) + chr(10))
        except Exception:
            pass
        continue
    _kept_nr.append(s_)
std = _kept_nr

# 10/13 user ("do what you said ... RB, WR, TE, QB"): NFL AGREEMENT rule. Backtest weeks 4-5, 825 archived PP lines: the raw average alone
# 54%, the ROLE+VOLUME model (+ half-shrunk defense) alone 54%, but when BOTH agree and both are 10%+ off the line: 183-127 (59%),
# 15%+: 60%, 20%+: 62%. PAPER until 40 forward legs at 58%+, then BET by itself (nfl_agree_paper.jsonl, graded nightly).
def _agree_switch():
    try:
        g = [json.loads(x) for x in open("nfl_agree_paper.jsonl", encoding="utf-8") if x.strip()] if os.path.exists("nfl_agree_paper.jsonl") else []
        g = [r for r in g if r.get("result") in ("W", "L")]
        w = sum(r["result"] == "W" for r in g)
        ok = len(g) >= 40 and w / len(g) >= 0.58
        print("NFL AGREE forward: %d-%d -> %s" % (w, len(g) - w, "BET" if ok else "PAPER")); return ok
    except Exception as e:
        print("agree switch:", e); return False
NFL_AGREE_LIVE = _agree_switch()
try:
    import _nfl_role as _NR
    _inj = set()
    try:
        import requests as _rq2
        for _t in _rq2.get("https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries", timeout=30).json().get("injuries", []):
            for _i in _t.get("injuries", []):
                if (_i.get("status") or "") in ("Out", "Doubtful", "Injured Reserve"):
                    _inj.add((_i.get("athlete") or {}).get("displayName"))
    except Exception as e:
        print("agree injuries:", e)
    _have3 = {M.norm(s_["player"]) for s_ in std}
    _ag_seen = set()
    if os.path.exists("nfl_agree_paper.jsonl"):
        _ag_seen = {(json.loads(x)["player"], json.loads(x)["stat"], json.loads(x)["line"]) for x in open("nfl_agree_paper.jsonl", encoding="utf-8") if x.strip()}
    _FX = {"WSH": "WAS", "JAC": "JAX", "LAR": "LA"}
    _n_ag = 0
    for (sp, pl, st), l in live.items():
        if sp != "NFL" or l.get("kind") != "standard" or l["stat"] not in _NR.STATS or l["line"] < 2.5 or pl in _have3:
            continue
        if datetime.datetime.fromisoformat(l["start"]).astimezone(datetime.timezone.utc) < now:
            continue
        _wk = 1 + (datetime.datetime.fromisoformat(l["start"]).astimezone(CT).date() - datetime.date(2026, 9, 8)).days // 7
        _opp = _FX.get(l.get("opp"), l.get("opp"))
        _rw = _NR.raw_avg(l["player"], l["stat"], _wk)
        _rd = _NR.project(l["player"], l["stat"], _wk, absent=_inj, opp=_opp, use_d=True)
        if _rw is None or not _rd:
            continue
        g0, g1 = (_rw - l["line"]) / l["line"], (_rd["proj"] - l["line"]) / l["line"]
        if g0 * g1 <= 0 or min(abs(g0), abs(g1)) < 0.15:
            continue
        side = "over" if g0 > 0 else "under"
        # 10/14 Brian Thomas Jr. O17.5: season avg 34.1 (two 40-yd September games) but his last 3 were 8 / 17 / 0 on 1-3 targets and the line
        # fell to 16.5. Recent-role guard: if his LAST 3 games all went against the side, the leg is out, whatever the average says.
        try:
            _vk, _gp, _ek = _NR.STATS[l["stat"]]
            _last3 = [_NR.f(r_, _ek or _vk) for r_ in sorted([r_ for r_ in _NR.W26 if _NR.norm(r_["player_display_name"]) == _NR.norm(l["player"]) and int(r_["week"]) < _wk],
                                                             key=lambda r_: int(r_["week"]))[-3:]]
            if len(_last3) == 3 and all((x_ < l["line"]) if side == "over" else (x_ > l["line"]) for x_ in _last3):
                print("  NFL AGREE blocked (last 3 all against the %s: %s): %s %s %s" % (side, _last3, l["player"], l["stat"], l["line"])); continue
        except Exception as e:
            print("agree recent-role:", e)
        _p = 0.62 if min(abs(g0), abs(g1)) >= 0.20 else 0.60
        std.append(dict(sport="NFL", nfl_agree=True, gap=round(min(abs(g0), abs(g1)), 3), paper=not NFL_AGREE_LIVE, player=l["player"], team=l.get("team"), opp=l.get("opp"), stat=l["stat"],
                        line=l["line"], side=side, p=_p, start=l["start"], proj=round(_rd["proj"], 1),
                        proj_why="team volume x his %.0f%% share, vs %s defense (own avg %.1f)" % (100 * _rd["share"], _opp, _rw),
                        why="NFL AGREE: own avg %.1f + role model %.1f (share %.0f%% of team volume) both %s %s (backtest 60%%)" % (_rw, _rd["proj"], 100 * _rd["share"], side, l["line"])))
        _have3.add(pl); _n_ag += 1
        if (l["player"], l["stat"], l["line"]) not in _ag_seen:
            with open("nfl_agree_paper.jsonl", "a", encoding="utf-8") as _af:
                _af.write(json.dumps(dict(logged=today, week=_wk, player=l["player"], team=l.get("team"), opp=l.get("opp"), stat=l["stat"], line=l["line"], side=side,
                                          raw=round(_rw, 1), role=round(_rd["proj"], 1), share=round(_rd["share"], 3), start=l["start"], result=None), ensure_ascii=False) + chr(10))
            _ag_seen.add((l["player"], l["stat"], l["line"]))
    print("NFL AGREE legs: %d" % _n_ag)
except Exception as e:
    print("nfl agree:", e)

# 10/15 user ("Jalen Hurts officially ruled out ... push crazy PHI legs, people are gonna be slow to switch, especially PP"): QB-OUT rule.
# Measured on 2025 nflverse, every game a team's starting QB sat: TE receiving yards ran 0.58x their average (under 95%-of-avg 70%,
# n=97), WR receiving yards 0.80x (59%, n=183); RB carries did NOT rise (0.90x) -> no RB overs. So: when the team's starting QB
# (most 2026 pass attempts) is Out/Doubtful/IR on ESPN, its TE receiving-yards UNDER is a CRAZY leg if PP still has the line at 80%+ of
# his average (PP hasn't priced the backup in); its WR receiving-yards UNDER qualifies (59%) at 90%+ and is CRAZY only if PP didn't cut it at all.
try:
    import requests as _rq3, collections as _co3
    _qbout = {}
    for _t in _rq3.get("https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries", timeout=30).json().get("injuries", []):
        for _i in _t.get("injuries", []):
            _a = _i.get("athlete") or {}
            if (_a.get("position") or {}).get("abbreviation") == "QB" and (_i.get("status") or "") in ("Out", "Doubtful", "Injured Reserve"):
                _qbout[_a.get("displayName")] = 1
    _att = _co3.defaultdict(float)
    for _r in _NR.W26:
        if _r.get("position") == "QB":
            _att[(_r.get("recent_team") or _r.get("team"), _r["player_display_name"])] += float(_r.get("attempts") or 0)
    _starter = {}
    for (_tm, _pl), _a in _att.items():
        if _a > _starter.get(_tm, ("", 0))[1]:
            _starter[_tm] = (_pl, _a)
    _QBOUT_TEAMS = {_tm for _tm, (_pl, _a) in _starter.items() if _pl in _qbout}
    _QBOUT_TEAMS |= {{"JAX": "JAC", "LA": "LAR", "WAS": "WSH"}.get(t_, t_) for t_ in _QBOUT_TEAMS}
    print("QB OUT teams:", sorted(_QBOUT_TEAMS), {t_: _starter[t_][0] for t_ in _starter if t_ in _QBOUT_TEAMS})
    _pos = {}
    for _r in _NR.W26:
        _pos[_r["player_display_name"]] = _r.get("position")
    _n_qb = 0
    for (sp, pl), l in [((k_[0], k_[1]), v_) for k_, v_ in live.items()]:
        if sp != "NFL" or l.get("kind") != "standard" or l["stat"] != "Receiving Yards" or l.get("team") not in _QBOUT_TEAMS:
            continue
        if datetime.datetime.fromisoformat(l["start"]).astimezone(datetime.timezone.utc) < now:
            continue
        _ps = _pos.get(l["player"])
        if _ps not in ("TE", "WR"):
            continue
        _wk = 1 + (datetime.datetime.fromisoformat(l["start"]).astimezone(CT).date() - datetime.date(2026, 9, 8)).days // 7
        _avg = _NR.raw_avg(l["player"], l["stat"], _wk)
        if not _avg or _avg < 15:
            continue
        _ratio = l["line"] / _avg
        if _ps == "TE" and _ratio >= 0.80:
            _p, _crazy = 0.70, True
        elif _ps == "WR" and _ratio >= 0.90:
            _p, _crazy = 0.59, _ratio >= 1.0
        else:
            continue
        std.append(dict(sport="NFL", qb_out=True, qb_out_crazy=_crazy, player=l["player"], team=l.get("team"), opp=l.get("opp"), stat=l["stat"],
                        line=l["line"], side="under", p=_p, start=l["start"], gap=round(_ratio - 1, 3), proj=round(_avg * (0.58 if _ps == "TE" else 0.80), 1),
                        proj_why="his avg %.1f x backup-QB factor %s" % (_avg, "0.58" if _ps == "TE" else "0.80"),
                        why="QB OUT (%s): backup-QB games 2025 -- %s receiving yards ran %s of average (%s under). His avg %.1f vs line %g (PP at %.0f%% of his avg)"
                            % (_starter.get(l.get("team"), _starter.get({"JAC": "JAX", "LAR": "LA", "WSH": "WAS"}.get(l.get("team"), ""), ("?",)))[0], _ps,
                               "0.58x" if _ps == "TE" else "0.80x", "70%" if _ps == "TE" else "59%", _avg, l["line"], 100 * _ratio)))
        _n_qb += 1
    print("QB OUT legs: %d" % _n_qb)
    # the same data says a backup QB cuts every pass-catcher -> drop that team's receiving OVERS already on the card (Egbuka/Godwin O
    # with Mayfield doubtful, 10/15)
    # 10/16 (Bateman O20.5, Lamar out): PP cut him 34.5 -> 20.5 (-41%) when backup-QB WRs run 0.80x -- the over was the value. So a
    # receiving over stays blocked only while PP's line is still above 80% of his average (PP hasn't priced the backup in).
    def _still_priced_for_starter(x):
        try:
            _wk_ = 1 + (datetime.datetime.fromisoformat(x["start"]).astimezone(CT).date() - datetime.date(2026, 9, 8)).days // 7
            _a = _NR.raw_avg(x["player"], x["stat"], _wk_)
            return not _a or x["line"] > 0.80 * _a
        except Exception:
            return True
    _drop = [x for x in std if x.get("sport") == "NFL" and x.get("team") in _QBOUT_TEAMS and x.get("side") == "over"
             and x.get("stat") in ("Receiving Yards", "Receptions", "Rush+Rec Yds", "Fantasy Score") and _still_priced_for_starter(x)]
    for x in _drop:
        print("  QB OUT blocks: %s O%g %s (%s)" % (x["player"], x["line"], x["stat"], x.get("team")))
    std[:] = [x for x in std if not any(x is d_ for d_ in _drop)]
except Exception as e:
    print("qb out:", e)

# 10/13 user ("do NBA then"): NBA ROLE UNDERS. Basketball backtest: own average AND minutes model agreeing was 44-50% overall, but
# agreeing on the UNDER (both 10%+ under the line) went WNBA 27-11 (71%), NBA preseason 3-0 -- our basketball numbers run hot on
# overs. Regular-season NBA (league 7) only. PAPER until 30 forward legs at 60%+, then BET by itself (nba_role_paper.jsonl).
def _nbarole_switch():
    try:
        g = [json.loads(x) for x in open("nba_role_paper.jsonl", encoding="utf-8") if x.strip()] if os.path.exists("nba_role_paper.jsonl") else []
        out = {}
        for sd in ("under", "over"):                          # 10/13 user: "nba overs ab to hit after preseason" -> overs get their own record + switch
            gg = [r for r in g if r.get("result") in ("W", "L") and r.get("side", "under") == sd]
            w = sum(r["result"] == "W" for r in gg); out[sd] = len(gg) >= 30 and w / len(gg) >= 0.60
            print("NBA ROLE %sS forward: %d-%d -> %s" % (sd.upper(), w, len(gg) - w, "BET" if out[sd] else "PAPER"))
        return out
    except Exception as e:
        print("nba role switch:", e); return {"under": False, "over": False}
NBA_ROLE_LIVE = _nbarole_switch()
try:
    _nba_live = [l for (sp, pl, st), l in live.items() if sp == "NBA" and l.get("kind") == "standard"]
    if _nba_live:
        import _bb_role as _BR
        _ids_nba = _BR.BB.roster("nba")
        _seen_nr = set()
        if os.path.exists("nba_role_paper.jsonl"):
            _seen_nr = {(json.loads(x)["player"], json.loads(x)["stat"], json.loads(x)["day"]) for x in open("nba_role_paper.jsonl", encoding="utf-8") if x.strip()}
        _have4 = {M.norm(s_["player"]) for s_ in std}; _n_nr = 0
        for l in _nba_live:
            if not _BR.parts(l["stat"]) or l["line"] < 2.5 or M.norm(l["player"]) in _have4:
                continue
            _st = datetime.datetime.fromisoformat(l["start"])
            if _st.astimezone(datetime.timezone.utc) < now:
                continue
            _day = _st.astimezone(CT).date().isoformat()
            m_ = _BR.models("nba", l["player"], l["stat"], _day, _ids_nba)
            if not m_:
                continue
            raw_, role_, pmin_ = m_
            if raw_ <= 0.90 * l["line"] and role_ <= 0.90 * l["line"]:
                _sd = "under"
            elif raw_ >= 1.10 * l["line"] and role_ >= 1.10 * l["line"]:
                _sd = "over"                                  # paper-tracked; WNBA backtest overs 37% -> earns money only on its own forward record
            else:
                continue
            std.append(dict(sport="NBA", nba_role_under=(_sd == "under"), nba_role_over=(_sd == "over"), paper=not NBA_ROLE_LIVE[_sd], player=l["player"], team=l.get("team"),
                            opp=l.get("opp"), stat=l["stat"], line=l["line"], side=_sd, p=0.65 if _sd == "under" else 0.55, start=l["start"],
                            proj=round(role_, 1), proj_why="%.0f projected minutes x per-minute rate (own avg %.1f)" % (pmin_, raw_),
                            why="NBA ROLE %s: own avg %.1f + minutes model %.1f (%.0f min) both 10%%+ %s %s" % (_sd.upper(), raw_, role_, pmin_, _sd, l["line"])))
            _have4.add(M.norm(l["player"])); _n_nr += 1
            if (l["player"], l["stat"], _day) not in _seen_nr:
                with open("nba_role_paper.jsonl", "a", encoding="utf-8") as _nf:
                    _nf.write(json.dumps(dict(logged=today, day=_day, side=_sd, player=l["player"], team=l.get("team"), opp=l.get("opp"), stat=l["stat"], line=l["line"],
                                              raw=round(raw_, 1), role=round(role_, 1), pmin=round(pmin_, 1), start=l["start"], result=None), ensure_ascii=False) + chr(10))
                _seen_nr.add((l["player"], l["stat"], _day))
        print("NBA ROLE legs (unders + overs): %d" % _n_nr)
except Exception as e:
    print("nba role unders:", e)

# sharp check on the STANDARD leg: a Pinnacle/FanDuel price that disagrees with our side by 5+ pts drops it (Gauthier 10/9: 51%)
PINS = {}
for sp in ("NHL", "WNBA", "NBA", "NFL", "CFB"):
    try:
        for (pl, st, ln), pr in P.pinnacle_props(M.PIN_LEAGUE[sp]).items():
            PINS.setdefault((sp, pl, st), []).append((ln, pr))
    except Exception:
        pass
# ⚡ SOFT LINE detector (10/10, user: "like Puka over 6 targets -- it was literally removed"). PP posts a mispriced number, then pulls it.
# Every scan: every live PP standard line vs the sharp fair price AT PP'S NUMBER (Pinnacle props + FanDuel ladders, interpolated between
# rungs). One side >= 62% (2-pick b/e 57.7%) -> post it NOW, once. Market EV: no model needed, the sharp books are the reference.
try:
    import _fanduel as _FD, bisect
    _SOFT_F = "_soft_seen.json"
    _seen_soft = set(json.load(open(_SOFT_F))) if os.path.exists(_SOFT_F) else set()
    _fd = {}
    for _lg in ("nfl", "cfb"):
        try:
            for (_pl, _st, _ln), _po in _FD.props(_lg).items():
                _fd.setdefault((_lg.upper(), _pl, _st), []).append((_ln, _po))
        except Exception as e:
            print("fanduel", _lg, e)

    def _fd_at(sp, pl, st, line):
        R = sorted(_fd.get((sp, pl, st), []))
        if len(R) < 2 or not (R[0][0] <= line <= R[-1][0]):
            return next((po for ln, po in R if ln == line), None)
        i = bisect.bisect_left([r[0] for r in R], line)
        if R[i][0] == line:
            return R[i][1]
        (l0, p0), (l1, p1) = R[i - 1], R[i]
        return p0 + (p1 - p0) * (line - l0) / (l1 - l0)

    soft = []
    for (sp, pl, st), l in live.items():
        if l.get("kind") != "standard" or datetime.datetime.fromisoformat(l["start"]).astimezone(datetime.timezone.utc) < now:
            continue
        stk = M.STAT.get(M.norm(l["stat"]))
        if not stk:
            continue
        R = PINS.get((sp, pl, stk))
        p_pin = M.p_over_at(R, l["line"], stk) if R else None
        p_fd = _fd_at(sp, pl, stk, l["line"]) if sp in ("NFL", "CFB") else None
        have = [x for x in (p_pin, p_fd) if x is not None]
        if not have:
            continue
        if len(have) == 2 and abs(p_pin - p_fd) > 0.08:
            continue                                   # 10/10 Bourne: Pinnacle-extrapolated 28% vs FanDuel 47% -> books disagree = bug, not edge
        po = min(have, key=lambda x: abs(x - 0.5))      # the LESS extreme of the two books
        side, pp = ("over", po) if po >= 0.5 else ("under", 1 - po)
        if side == "under" and sp == "NFL":             # 10/10 Bourne: WR1 Harrison OUT -> his role grows; same guard as NFL BETA
            _ps = (sorted(_NG.get(pl, []), key=lambda t: t[0])[-1][1].get("position") if _NG.get(pl) else None) if "_NG" in globals() else None
            if _ps and (((_FIX.get(l.get("team"), l.get("team")), _ps) in _OUTPOS) or ((l.get("team"), _ps) in _OUTPOS)):
                continue
        key = "%s|%s|%s|%s" % (l["player"], l["stat"], l["line"], side)
        if pp >= 0.62 and key not in _seen_soft:
            soft.append((pp, l, side)); _seen_soft.add(key)
    if soft:
        import _cardpost as _C
        soft.sort(key=lambda t: -t[0])
        NL = chr(10)
        body = ("Sharp books make one side **62%+** at PrizePicks' exact number (2-pick needs 57.7%). These get pulled fast -- "
                "check your screen and lock early." + NL + NL +
                NL.join("⚡ **%s** %s %s %g · sharp **%.0f%%** · %s" % (l["player"], "HIGHER" if sd == "over" else "LOWER", l["stat"], l["line"], 100 * pp,
                        datetime.datetime.fromisoformat(l["start"]).astimezone(CT).strftime("%a %I:%M %p TX")) for pp, l, sd in soft[:12]))
        _C.post_embed("⚡ SOFT LINES · PrizePicks vs the sharp books", body, 0xFFA42B)
        print("SOFT LINES posted:", len(soft))
        for pp, l, sd in soft:
            print("  SOFT: %s %s %s %g sharp %.1f%% start %s" % (l["player"], sd.upper(), l["stat"], l["line"], 100 * pp, l["start"]))
    json.dump(sorted(_seen_soft)[-5000:], open(_SOFT_F, "w"))
except Exception as e:
    print("soft lines:", e)

keep = []
for s_ in std:
    st = M.STAT.get(M.norm(s_["stat"])); R = PINS.get((s_["sport"], M.norm(s_["player"]), st)) if st else None
    po = M.p_over_at(R, s_["line"], st) if R else None
    if po is None and s_["sport"] == "NHL" and M.norm(s_["stat"]) == "points" and float(s_["line"]) == 0.5:
        # 10/13 Kent Johnson U0.5 pts carded at 62%: Pinnacle posts no NHL points, but goals + assists imply it -> P(0 pts) ~ (1-pG)(1-pA)
        _pl = M.norm(s_["player"])
        _gR, _aR = PINS.get(("NHL", _pl, "goals")), PINS.get(("NHL", _pl, "assists"))
        _pg = next((pr for ln, pr in (_gR or []) if ln == 0.5), None); _pa = next((pr for ln, pr in (_aR or []) if ln == 0.5), None)
        if _pg is not None and _pa is not None:
            po = 1 - (1 - _pg) * (1 - _pa)
    if po is not None:
        sharp = po if s_["side"] == "over" else 1 - po
        s_["sharp"] = sharp
        if sharp < s_["p"] - 0.05 and sharp < 0.55:
            print("  dropped (sharp disagrees %.0f%%): %s %s %s" % (100 * sharp, s_["player"], s_["side"], s_["line"])); continue
    keep.append(s_)
std = keep
# goblins (fresh scan). 10/9 user: the goblin must be the tier ONE BELOW the standard line (the shallowest goblin) -- the deep tiers
# pay 1.2-1.3x and kill the 2x. Questionable/Doubtful NFL players are out.
if not os.environ.get("SKIP_GOBLINS"):                                  # goblins are promo-only now; skip the 10-25 min scan when in a hurry
    subprocess.run([sys.executable, "_goblins.py"], capture_output=True, timeout=1500, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
G = json.load(open("_goblins_today.json"))
top = {}
for g in G:
    k = (g["sport"], g["player"], g["stat"])
    if k not in top or g["line"] > top[k]["line"]:
        top[k] = g
try:
    import _nflscreen as N
    inj, _ = N.injuries()
except Exception:
    inj = {}
gob = [g for g in top.values() if M.norm(g["player"]) not in USED and g["p"] >= 0.72 and inj.get(g["player"]) not in ("Questionable", "Doubtful", "Out", "Injured Reserve")]
gob.sort(key=lambda g: -g["p"])

# 10/9 user rule: "our plays are OVERS and UNDERS" -- show both sides of the qualifying standard pool, never only one by default
_ov = sorted([x for x in std if x["side"] == "over"], key=lambda x: -x["p"]); _un = sorted([x for x in std if x["side"] == "under"], key=lambda x: -x["p"])
print("BOTH SIDES -- qualifying standard legs: %d OVER, %d UNDER" % (len(_ov), len(_un)))
for lab, X in (("OVERS", _ov), ("UNDERS", _un)):
    print("  %s:" % lab)
    for x in X[:8]:
        print("    PP: %-22s %-5s %-18s %-5s %-5s %.0f%%  (%s)" % (x["player"], x["team"] or "", x["stat"][:18], x["side"].upper(), x["line"], 100 * x["p"], x["why"][:55]))
    if not X:
        print("    none qualified today")
# sharp-priced standard OVERS (Pinnacle/FanDuel >= 58% at PP's number) -- the over hunt beyond our filter
try:
    _sb = json.load(open("_standard_today.json")) if os.path.exists("_standard_today.json") else []
    _so = sorted([r for r in _sb if min(r["src"].values()) >= .58], key=lambda r: -min(r["src"].values()))
    print("  sharp-priced standard OVERS >= 58%%: %d" % len(_so))
    for r in _so[:6]:
        print("    PP: %-22s %-5s %-18s OVER  %-5s sharp %.0f%%" % (r["player"], r["team"] or "", r["stat"][:18], r["line"], 100 * min(r["src"].values())))
except Exception as e:
    print("  sharp overs:", e)
print()
print("STANDARD (our model) + GOBLIN (sharp-priced) pairs -- the payout must clear the 'needs' column on your screen")
used = set(); n = 0; teams_used = set()
for s in sorted(std, key=lambda s: (-s["p"], -s.get("gap", 0))):
    if s["team"] in teams_used:
        continue                                # 10/8 lesson: 3 Carolina legs across 3 slips died in one 7-2 blowout -> 1 leg per team, all slips
    teams_used.add(s["team"])
    g = next((g for g in gob if g["player"] not in used and g["team"] not in (s["team"], s["opp"])
              and (g.get("opp") or "")[:3] not in ((s["team"] or "")[:3], (s["opp"] or "")[:3])), None)
    if not g:
        continue
    used.add(g["player"]); n += 1
    both = s["p"] * g["p"]
    ts = lambda x: datetime.datetime.fromisoformat(x.replace("Z", "+00:00")).astimezone(CT).strftime("%a %I:%M%p")
    print("\n  PAIR %d   both hit ~%.0f%%   needs >= %.2fx   value at 2.0x %+.0f%% / 2.2x %+.0f%%" % (n, 100 * both, 1.05 / both, 100 * (both * 2 - 1), 100 * (both * 2.2 - 1)))
    print("    STANDARD  PP: %-22s %-5s %-18s %-5s %-5s  model %.0f%%  (%s)  %s" % (s["player"], s["team"] or "", s["stat"][:18], s["side"].upper(),
          s["line"], 100 * s["p"], s["why"][:60], ts(s["start"])))
    print("    GOBLIN    PP: %-22s %-5s %-18s MORE  %-5s  sharp %.0f%%  (tier right below standard)  %s" % (g["player"], g["team"] or "", g["stat"][:18], g["line"], 100 * g["p"], ts(g["start"])))
    if float(s["line"]).is_integer():
        print("    !! standard line %s is a whole number in the feed -- your app may show %s; confirm" % (s["line"], s["line"] - 0.5))
if not n:
    print("  no standard leg from our filters is live on PP right now")

# 🟢 GOBLIN PAIRS, sharp-gated (10/10 user: "double goblins right under the standard, 1.5-1.7x, free"). Measured: shallow goblins hit
# NHL 67.9% / WNBA 70.4% -- a 1.5x pair needs 81.6% each, so blind pairs lose ~26%. Only post pairs where BOTH goblins are sharp-priced
# high enough that p1*p2*1.5 >= 1.03 (his conservative payout; set GOB_MULT if his app shows more), different teams, one tier under std.
try:
    _GM = float(os.environ.get("GOB_MULT", 1.5))
    _gp = sorted([g for g in gob if g["p"] >= (1.03 / _GM) ** 0.5 - 0.02], key=lambda g: -g["p"])
    _pairs, _usedg = [], set()
    for i, a_ in enumerate(_gp):
        if a_["player"] in _usedg:
            continue
        b_ = next((x for x in _gp[i + 1:] if x["player"] not in _usedg and x["team"] != a_["team"]), None)
        if b_ and a_["p"] * b_["p"] * _GM >= 1.03:
            _pairs.append((a_, b_)); _usedg |= {a_["player"], b_["player"]}
    _GF = "_gob_pairs_seen.json"
    _gs = set(json.load(open(_GF))) if os.path.exists(_GF) else set()
    _new = [(a_, b_) for a_, b_ in _pairs if "%s|%s" % (a_["player"], b_["player"]) not in _gs]
    if _new:
        import _cardpost as _C
        NL = chr(10)
        _C.post_embed("🟢 GOBLIN PAIRS · sharp-priced high enough to beat %.1fx" % _GM,
                      "Both goblins priced by the sharp books above what a %.1fx pair needs (%.0f%% each). Check the payout on your screen -- if it shows LESS than %.1fx, skip it." % (_GM, 100 * (1 / _GM) ** 0.5, _GM)
                      + NL + NL + NL.join("🟢 **%s** MORE %g %s (sharp %.0f%%)  +  **%s** MORE %g %s (sharp %.0f%%) · both hit **%.0f%%** · worth **%+.0f%%**"
                                          % (a_["player"], a_["line"], a_["stat"], 100 * a_["p"], b_["player"], b_["line"], b_["stat"], 100 * b_["p"],
                                             100 * a_["p"] * b_["p"], 100 * (a_["p"] * b_["p"] * _GM - 1)) for a_, b_ in _new[:5]), 0x1ED760)
        _gs |= {"%s|%s" % (a_["player"], b_["player"]) for a_, b_ in _new}
        json.dump(sorted(_gs)[-2000:], open(_GF, "w"))
    print("goblin pairs: %d qualify (%d new)" % (len(_pairs), len(_new)))
except Exception as e:
    print("goblin pairs:", e)

# 10/10 smartest-path ordering (user OK'd): PROMO-anchored 3-picks first (promo ~0.9 + 2 model legs = the best bet we have), then
# direction legs, NFL BETA, and CS2 last (thin ~56%) with at most ONE CS2 leg per slip. 1 leg per team across all slips.
try:
    import _promos as _PR
    for pm in _PR.promos():
        if pm.get("promo_line") is None or M.norm(pm.get("player")) in USED:
            continue
        _ps = datetime.datetime.fromisoformat(pm["start"]).astimezone(datetime.timezone.utc)
        if _ps < now or _ps > now + datetime.timedelta(hours=36):
            continue                                                   # promo must play soon (Edwards' 10/21 free square would lock a slip 11 days)
        std.append(dict(sport=pm["league"], player=pm["player"], team=pm.get("team"), opp=pm.get("opp"), stat=pm["stat"],
                        line=pm["promo_line"], side="over", p=0.90, why="PROMO: %s -> %s (%s)" % (pm["line"], pm["promo_line"], pm.get("kind")),
                        start=pm["start"], promo=True))
except Exception as e:
    print("promo legs:", e)
# 10/11 user: LEAGUE-BASED slips -- one slip per league (NHL, WNBA, NBA, NFL, CFB, ESPORTS = any esports mixed, MLB when back), built only
# from that league's legs; leagues mix ONLY for crazy value (a promo leg, or calibrated p >= 0.66 = projection way past the line).
# A slip is a 💰 BET only if every leg comes from a proven market (promo, NHL/WNBA direction filter, NFL BETA); otherwise 📝 PAPER --
# paper slips are logged + graded every day so every league keeps building a record ("I want everything to pass even if we don't bet").
FAM = lambda s: "ESPORTS" if s["sport"] in ("CS2", "VAL", "Dota2", "LoL") else s["sport"]
# 10/12 user ("do it now"): NFL BETA legs are BET only once a full NFL week has graded at 60%+ (8+ legs); they switch back to PAPER on
# their own if the running record falls under the 57.7% 2-pick break-even. Week 5 (10/11) was 9-2 on ESPN box scores, pending nflverse.
def _beta_live():
    try:
        if os.path.exists("nfl_beta_status.json") and json.load(open("nfl_beta_status.json")).get("force"):
            print("NFL BETA money switch: ON (user override, nfl_beta_status.json)"); return True
        R = [json.loads(x) for x in open("nfl_beta_paper.jsonl", encoding="utf-8") if x.strip()]
        wk = lambda d: (datetime.date.fromisoformat(d[:10]) - datetime.date(2026, 9, 9)).days // 7 + 1
        W = collections.defaultdict(list)
        for r in R:
            if r.get("start"):
                W[wk(r["start"])].append(r)
        done = [w for w, rs in W.items() if all(r.get("result") for r in rs) and len([r for r in rs if r["result"] in ("W", "L")]) >= 8]
        if not done:
            return False
        last = [r for r in W[max(done)] if r["result"] in ("W", "L")]
        allg = [r for r in R if r.get("result") in ("W", "L")]
        ok = sum(r["result"] == "W" for r in last) / len(last) >= 0.60 and sum(r["result"] == "W" for r in allg) / len(allg) >= 0.577
        print("NFL BETA money switch: week %d %d/%d, running %d/%d -> %s" % (max(done), sum(r["result"] == "W" for r in last), len(last),
              sum(r["result"] == "W" for r in allg), len(allg), "BET" if ok else "PAPER"))
        return ok
    except Exception as e:
        print("beta switch:", e); return False
NFL_BETA_LIVE = _beta_live()
# 10/15 user ("would you have made those picks? ... we need shi with the research qualities as Claude"): RESEARCH GATE = the checks run by
# hand on every leg before naming it. Audit of the 19 cloud slips 10/10-10/15: legs these checks reject went 0-3 (Podkolzin, Kent Johnson,
# Lopez), legs they keep went 8-2. Applied last, to every leg, BET or paper:
#   1. tiny lines are noise, not edge: NFL receiving/rush yards <= 5.5, receptions/targets/rush attempts <= 1.5 (Hampton O3.5, Arroyo O3.5)
#   2. club keeper passes: his OWN starts must go our way at least half the time (Rossi U26.5: 6 of 15)
_INJ_POS, _INJ_Q = {}, set()   # 10/16: (team, pos) -> Out/Doubtful/IR names ; questionable players
try:
    import requests as _rq4
    _TMAP = {}
    for _t in _rq4.get("https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries", timeout=30).json().get("injuries", []):
        for _i in _t.get("injuries", []):
            _a = _i.get("athlete") or {}; _ps = (_a.get("position") or {}).get("abbreviation"); _stt = _i.get("status") or ""
            _tm = ((_a.get("team") or {}).get("abbreviation")) or _t.get("abbreviation") or _t.get("displayName")
            if _stt in ("Out", "Doubtful", "Injured Reserve"):
                _INJ_POS.setdefault(_ps, set()).add((_t.get("displayName"), _a.get("displayName")))
            elif _stt == "Questionable":
                _INJ_Q.add(_a.get("displayName"))
except Exception as e:
    print("research gate injuries:", e)


def _teammate_out(x):
    """same-team, same-position teammate Out/Doubtful/IR this week (team matched through the 2026 weekly rows)"""
    try:
        pos_ = {r_["player_display_name"]: (r_.get("position"), r_.get("recent_team") or r_.get("team")) for r_ in _NR.W26}
        mine = pos_.get(x["player"])
        if not mine:
            return None
        for _tdisp, nm_ in _INJ_POS.get(mine[0], ()):
            o_ = pos_.get(nm_)
            if o_ and o_[1] == mine[1] and nm_ != x["player"]:
                return nm_
    except Exception:
        return None
    return None


def _research_ok(x):
    if x.get("promo"):
        return True, ""
    #   7. (10/16: Lloyd U42.5 with Jacobs OUT, Daniels U37.5 rush with Mayfield OUT, Theo Johnson questionable) -- an UNDER on a
    #      player whose role just grew is built on his old, smaller role; and a questionable player can sit or be limited.
    if x.get("sport") == "NFL":
        if x["player"] in _INJ_Q:
            return False, "he is questionable"
        if x["side"] == "under":
            _to = _teammate_out(x)
            if _to:
                return False, "under with teammate %s out (role grows)" % _to
            if "Rush" in x["stat"]:
                try:
                    _me = next((r_ for r_ in _NR.W26 if r_["player_display_name"] == x["player"]), None)
                    if _me and _me.get("position") == "QB" and _teammate_out(dict(x, player=x["player"])) is None:
                        _tq = _me.get("recent_team") or _me.get("team")
                        if any(o_ for _t2, o_ in _INJ_POS.get("QB", ()) if next((r_ for r_ in _NR.W26 if r_["player_display_name"] == o_ and (r_.get("recent_team") or r_.get("team")) == _tq), None)):
                            return False, "backup QB starting -- his rush history is from mop-up snaps"
                except Exception:
                    pass
    if x.get("sport") == "NFL":
        if x["stat"] in ("Receiving Yards", "Rush Yards") and x["line"] <= 5.5:
            return False, "tiny line %g" % x["line"]
        if x["stat"] in ("Receptions", "Rec Targets", "Rush Attempts") and x["line"] <= 1.5:
            return False, "tiny line %g" % x["line"]
    #   3. NFL: a player who missed 2+ straight games is out (Dowdle last played 9/20 and was on a forced pair 10/15); bye = 1 week
    if x.get("sport") == "NFL" and x.get("start"):
        try:
            _wk_ = 1 + (datetime.datetime.fromisoformat(x["start"]).astimezone(CT).date() - datetime.date(2026, 9, 8)).days // 7
            _pw = [int(r_["week"]) for r_ in _NR.W26 if _NR.norm(r_["player_display_name"]) == _NR.norm(x["player"]) and int(r_["week"]) < _wk_]
            if _pw and _wk_ - max(_pw) >= 4:
                return False, "last played week %d (now week %d)" % (max(_pw), _wk_)
            # 10/16 audit of the Raridon / Mason Taylor / Jonnu Smith slips -- the average said over, the games didn't:
            #  4. GAME BY GAME: his 2026 games must clear THIS line on our side at least 60% of the time (3+ games) --
            #     Raridon averaged 25 vs 12.5 off one 57-yard game, but went over in 2 of 4
            _G6 = sorted([r_ for r_ in _NR.W26 if _NR.norm(r_["player_display_name"]) == _NR.norm(x["player"]) and int(r_["week"]) < _wk_],
                         key=lambda r_: int(r_["week"]))
            if x["stat"] in _NR.STATS and len(_G6) >= 3:
                _vk, _gp, _ek = _NR.STATS[x["stat"]]
                _vals = [_NR.f(r_, _ek or _vk) for r_ in _G6]
                _ok = sum((v_ > x["line"]) if x["side"] == "over" else (v_ < x["line"]) for v_ in _vals)
                if _ok / len(_vals) < 0.60:
                    return False, "his 2026 games clear %g only %d of %d" % (x["line"], _ok, len(_vals))
            #  5. back from an absence: missed 2+ of the last 3 weeks (Mason Taylor: weeks 2-4 out, back week 5) -- role not settled
            _recent = {w_ for w_ in _pw if w_ >= _wk_ - 3}
            if _pw and len(_recent) <= 1 and _wk_ - 1 in _pw and len(_pw) >= 1 and _wk_ >= 4:
                return False, "back from missing %d of the last 3 weeks" % (3 - len(_recent))
            #  6. changed teams: his 2026 games were for another team than the one PP lists now (Jonnu Smith) -- the history is a different role
            _tms = [(r_.get("recent_team") or r_.get("team")) for r_ in _G6]
            _FXT = {"JAX": "JAC", "LA": "LAR", "WAS": "WSH"}
            if _tms and x.get("team") and _FXT.get(_tms[-1], _tms[-1]) != _FXT.get(x["team"], x["team"]) and _tms[-1] != x["team"]:
                return False, "his 2026 games were for %s, PP lists %s" % (_tms[-1], x["team"])
        except Exception:
            pass
    if x.get("soccer_hit"):
        m_ = re.search(r"(\d+) of (\d+) starts", x.get("why", ""))
        if m_ and int(m_.group(2)) >= 6 and int(m_.group(1)) / int(m_.group(2)) < 0.5:
            return False, "own starts %s of %s" % (m_.group(1), m_.group(2))
    return True, ""
_kept_rg = []
for x in std:
    ok_, why_ = _research_ok(x)
    if ok_:
        _kept_rg.append(x)
    else:
        print("  RESEARCH GATE drops %s %s %g %s -- %s" % (x["player"], x["side"], x["line"], x["stat"], why_))
std = _kept_rg

# 10/15 user ("projected 25 based on offense/defense/team, then the line shows 23 so it's an over, or 28 so it's an under" + market prior):
# every leg shows PROJ (what the model says, before the line) vs LINE -> HIGHER/LOWER, and its win chance is nudged by its MARKET's
# history (_history.py: every archived PP opening line graded -- e.g. NFL rush yards under 62% of 108, NFL receiving yards over 54% of 227).
# p_final = p_model + 0.5 x (market side rate - 50%), markets with 30+ graded lines only. Ranks overs and unders on equal footing.
_MKT = {}
try:
    _HS = {"NBAP": "NBA"}
    for _x in (json.loads(x_) for x_ in open("pp_history.jsonl", encoding="utf-8") if x_.strip()):
        if _x["res_open"] != "push":
            _m = _MKT.setdefault((_x["sport"], _x["stat"]), [0, 0]); _m[0] += _x["res_open"] == "over"; _m[1] += 1
except Exception as e:
    print("market prior:", e)
for x in std:
    _m = _MKT.get(({"NBAP": "NBA"}.get(x["sport"], x["sport"]), x["stat"]))
    if _m and _m[1] >= 30 and not x.get("promo"):
        _rate = _m[0] / _m[1] if x["side"] == "over" else 1 - _m[0] / _m[1]
        x["p_model"] = x["p"]
        x["p"] = round(min(0.80, max(0.40, x["p"] + 0.3 * (_rate - 0.5))), 3)   # 10/15 out-of-sample: 61% markets ran 53.5% the next week -> ~30% survives
        x["market"] = "%s %s: %s %.0f%% of %d" % (x["sport"], x["stat"], x["side"], 100 * _rate, _m[1])
        x["mkt_rate"] = _rate
    if x.get("proj") is not None:
        _pr = float(x["proj"])
        _call = "HIGHER" if _pr > x["line"] else "LOWER"
        x["why"] = "PROJ %.1f (%s) vs LINE %g -> %s%s%s | %s" % (_pr, x.get("proj_why", "model"), x["line"], _call,
                   "" if (_call == "HIGHER") == (x["side"] == "over") else " [PROJ DISAGREES WITH SIDE]",
                   (" | market: " + x["market"]) if x.get("market") else "", x.get("why", ""))
    elif x.get("market"):
        x["why"] = "market: %s | %s" % (x["market"], x.get("why", ""))
print("market prior applied to %d of %d legs" % (sum(1 for x in std if x.get("market")), len(std)))

# 10/14 user ("make shit bettable asap and fix as we go"): PROBATION tier -- a rule with a positive backtest but no forward proof yet bets at
# HALF stake (2.5% of the roll) from day one: NFL AGREE (60% backtest), NBA preseason unders (TAKE 21-2), NBA ROLE UNDERS (WNBA 71%).
# Full stake once its own switch flips; a probation rule under break-even after 20 graded legs goes back to paper (_probation_ok).
def _probation_ok(tag):
    try:
        F = {"nfl_agree": "nfl_agree_paper.jsonl", "nba_role_under": "nba_role_paper.jsonl"}.get(tag)
        if not F or not os.path.exists(F):
            return True
        g = [json.loads(x) for x in open(F, encoding="utf-8") if x.strip()]
        g = [r for r in g if r.get("result") in ("W", "L") and r.get("side", "under") in ("under", "over") and (tag != "nba_role_under" or r.get("side", "under") == "under")]
        return len(g) < 20 or sum(r["result"] == "W" for r in g) / len(g) >= 0.577
    except Exception:
        return True
_PROB = {t: _probation_ok(t) for t in ("nfl_agree", "nba_role_under", "nba_pre_under")}
print("probation rules live: %s" % {k: ("HALF-STAKE BET" if v else "back to PAPER") for k, v in _PROB.items()})
# 10/15 user: "fuck the paper testing unless it's esports" -> backtested rules bet FULL stake from day 1; the auto-demote (under 57.7% after
# 20 graded legs -> back to paper) stays, because that is a measured loss, not a test.
_FULL = lambda s: any(s.get(t) and _PROB[t] for t in _PROB)
probation = lambda s: False and (
    (s.get("nfl_agree") and NFL_AGREE_LIVE) or (s.get("nba_role_under") and NBA_ROLE_LIVE["under"]) or (s.get("nba_pre_under") and NBAP_LIVE))
money_ok = lambda s: bool(s.get("cfb_sharp")) or bool(s.get("qb_out")) or _FULL(s) or probation(s) or bool(s.get("promo")) or (bool(s.get("beta")) and NFL_BETA_LIVE) or bool(s.get("soccer_hit")) or bool(s.get("nhl_under")) or (bool(s.get("nba_pre_under")) and NBAP_LIVE) or (bool(s.get("nfl_agree")) and NFL_AGREE_LIVE) or (bool(s.get("nba_role_under")) and NBA_ROLE_LIVE["under"]) or (bool(s.get("nba_role_over")) and NBA_ROLE_LIVE["over"]) or (s["sport"] in ("NHL", "WNBA") and not s.get("paper"))
# 10/15 user: "6.5% first 3 if it's crazy good, if not we keep it going -- don't hold a slot because later will be good too, just lower the
# stake after that" (two6zero: lower the stake later on). Tiered by the slip's place in the day (game-day count):
#   slips 1-3: 6.5% if the slip is STRONG (joint p >= 0.44 = two ~66% legs), else 5%;  slips 4-6: 2.5%;  hard stop at 6
# 10/15 user, refined: "it only stays at 6.5% if it passes at a very high or very low projection and is backed from history". A STRONG
# leg = (1) its projection sits 20%+ past the line on its side, and (2) history backs it: a measured rule put it there (money_ok) AND its
# market's graded record doesn't run against that side (< 50%). A slip is strong only when EVERY leg is.
MAX_SLIPS, STAKE, STRONG_GAP = 6, 0.065, 0.20
def _strong_leg(g):
    if g.get("proj") is None or not g.get("line"):
        return False
    gap = (float(g["proj"]) - g["line"]) / g["line"] * (1 if g["side"] == "over" else -1)
    return gap >= STRONG_GAP and money_ok(g) and g.get("mkt_rate", 0.5) >= 0.5
def _stake_for(pos, grp):
    if pos < 3:
        return STAKE if all(_strong_leg(g) for g in grp) else 0.05
    return 0.025
CRAZY = lambda s: bool(s.get("promo")) or s.get("p_model", s["p"]) >= 0.66 or bool(s.get("qb_out_crazy"))   # 10/15: the model's own p, not the market-nudged one
by_fam = collections.defaultdict(list)
for s in sorted(std, key=lambda s: (-s["p"], -s.get("gap", 0))):
    by_fam[FAM(s)].append(s)
used_team, used_leg = set(), set()


def _build(cands, n):
    grp = []
    for x in cands:
        if id(x) in used_leg or x["team"] in used_team or any(x["team"] == g["team"] for g in grp):
            continue
        if x.get("promo") and any(g.get("promo") for g in grp):
            continue                                                   # one promo per slip
        if any({x["team"], x.get("opp")} == {g["team"], g.get("opp")} for g in grp):
            continue                                                   # legs from different games
        grp.append(x)
        if len(grp) == n:
            break
    return grp if len(grp) == n else None


k = 0; slips_txt = []; slips = []
print("\nLEAGUE SLIPS (one per league; 3-pick 6x needs 55%/leg, 2-pick 3x needs 57.7%):")
_promos_wild = [s for s in sorted(std, key=lambda s: (-s["p"], -s.get("gap", 0))) if s.get("promo")]
for fam in sorted(by_fam, key=lambda f: -max(s["p"] for s in by_fam[f])):
    # a promo is crazy value by definition (~90%) -> it may anchor ANY league's slip (promo + that league's 2 best legs = the best bet we have)
    _free = [p_ for p_ in _promos_wild if id(p_) not in used_leg and FAM(p_) != fam]
    grp = _build(([_free[0]] if _free else []) + [x for x in by_fam[fam] if not x.get("promo")], 3) if _free else None
    if grp is None or not any(g.get("promo") for g in grp):
        grp = _build(by_fam[fam], 3)
    mult = 6.0
    if grp is None:
        g2 = _build(by_fam[fam], 2)
        if g2 and min(g["p"] for g in g2) >= 0.60:                      # a 2-pick only when both legs clear 60% (2-pick b/e 57.7%)
            grp, mult = g2, 3.0
        elif g2:                                                         # 10/13: under the bar -> still a PAPER 2-pick so it gets graded
            for g in g2:
                used_leg.add(id(g)); used_team.add(g["team"])
            k += 1; slips.append((k, g2, g2[0]["p"] * g2[1]["p"], 3.0, "PAPER", fam + " (under the 60% bar)"))
            continue
    if not grp:
        continue
    # 10/11 real record: PP 2-leg 7-9 (+$22.10) vs 3-leg 0-11 (-$17.90) -> BET slips are 2-picks (best two legs, promo first);
    # the 3-pick version is still logged as PAPER-3 so 3s can earn their way back
    if len(grp) == 3 and all(money_ok(g) for g in grp):
        p3 = grp[0]["p"] * grp[1]["p"] * grp[2]["p"]
        k += 1; slips.append((k, list(grp), p3, 6.0, "PAPER", fam + " (3-pick version)"))
        grp, mult = sorted(grp, key=lambda g: (not g.get("promo"), -g["p"]))[:2], 3.0
    for g in grp:
        used_leg.add(id(g)); used_team.add(g["team"])
    ph = 1.0
    for g in grp:
        ph *= g["p"]
    k += 1
    tag = "BET" if all(money_ok(g) for g in grp) else "PAPER"
    slips.append((k, grp, ph, mult, tag, fam))
# crazy-value mixer: leftover legs from different leagues, only promos / projections way past the line
left = [s for s in sorted(std, key=lambda s: (-s["p"], -s.get("gap", 0))) if id(s) not in used_leg and CRAZY(s)]
grp = _build(left, 3)
if grp and len({FAM(g) for g in grp}) > 1:
    for g in grp:
        used_leg.add(id(g)); used_team.add(g["team"])
    ph = grp[0]["p"] * grp[1]["p"] * grp[2]["p"]
    k += 1
    slips.append((k, grp, ph, 6.0, "BET" if all(money_ok(g) for g in grp) else "PAPER", "MIXED (crazy value)"))
# 10/13 user ("0 paper bets to track yesterday was crazy"): paper is the record-builder, so EVERY day logs paper slips. After the BET/crazy
# slips: a wider PAPER pool (today's/tomorrow's NHL screen calls on live PP standard lines, soccer HIT/LEAN legs on live PP lines) plus every
# leftover card leg -> the best 2-pick per league, tagged PAPER, never money. Leg p = the model's number shrunk halfway to 50% (it runs hot).
_pp_pool = []
try:
    _dset = {today, (datetime.date.fromisoformat(today) + datetime.timedelta(days=1)).isoformat()}
    _seenp = {(M.norm(s["player"]), M.norm(s["stat"])) for s in std}
    for x in open("calls_log.jsonl", encoding="utf-8"):
        r = json.loads(x)
        if r.get("sport") != "NHL" or r.get("date") not in _dset or r.get("call") not in ("TAKE OVER", "TAKE UNDER", "LEAN OVER", "LEAN UNDER") or not r.get("start"):
            continue
        k_ = (M.norm(r["player"]), M.norm(r["stat"])); lv = live.get(("NHL",) + k_)
        if k_ in _seenp or not lv or float(lv["line"]) != float(r["line"]):
            continue
        if datetime.datetime.fromisoformat(r["start"].replace("Z", "+00:00")).astimezone(datetime.timezone.utc) < now:
            continue
        up = r["call"].endswith("OVER"); pm = r.get("p_role") if r.get("p_role") is not None else 0.55
        pm = pm if up else 1 - pm
        _seenp.add(k_)
        _pp_pool.append(dict(sport="NHL", paper=True, player=lv["player"], team=lv.get("team"), opp=lv.get("opp"), stat=lv["stat"], line=lv["line"],
                             side="over" if up else "under", p=round(0.5 + (pm - 0.5) / 2, 3), start=lv["start"], why="NHL screen %s (paper pool)" % r["call"]))
    for _day in _dset:
        _bf = "_soccer_board_%s.json" % _day
        if not os.path.exists(_bf):
            continue
        for r in json.load(open(_bf, encoding="utf-8")):
            if r.get("verdict") not in ("HIT", "LEAN") or not r.get("start"):
                continue
            k_ = (M.norm(r["player"]), M.norm(r["stat"])); lv = live.get(("SOCCER",) + k_)
            if k_ in _seenp or not lv or float(lv["line"]) != float(r["line"]):
                continue
            if datetime.datetime.fromisoformat(r["start"]).astimezone(datetime.timezone.utc) < now:
                continue
            _seenp.add(k_)
            _pp_pool.append(dict(sport="SOCCER", paper=True, player=r["player"], team=r.get("team"), opp=r.get("opp"), stat=r["stat"], line=r["line"],
                                 side=r["side"], p=round(0.5 + ((r.get("p") or 0.55) - 0.5) / 2, 3), start=r["start"], why="Soccer %s (paper pool)" % r["verdict"]))
except Exception as e:
    print("paper pool:", e)
_pfam = collections.defaultdict(list)
for s in sorted([s for s in std if id(s) not in used_leg] + _pp_pool, key=lambda s: -s["p"]):
    _pfam[FAM(s)].append(s)
for fam in sorted(_pfam):
    g2 = _build(_pfam[fam], 2)
    if not g2:
        continue
    for g in g2:
        used_leg.add(id(g)); used_team.add(g["team"])
    k += 1
    slips.append((k, g2, g2[0]["p"] * g2[1]["p"], 3.0, "PAPER", fam + " (paper pool)"))
print("paper pool: %d extra legs -> %d paper slips" % (len(_pp_pool), sum(1 for s_ in slips if s_[5].endswith("(paper pool)"))))
for k_, grp_, ph_, mult_, tag_, fam_ in slips:
    print("  %s SLIP %d %-20s %d-pick %gx  all hit ~%.0f%%  value %+.0f%%" % ("💰" if tag_ == "BET" else "📝", k_, fam_, len(grp_), mult_, 100 * ph_, 100 * (ph_ * mult_ - 1)))
    for g in grp_:
        print("    PP: %-22s %-5s %-18s %-5s %-5s  %.0f%%  (%s)" % (g["player"], g["team"] or "", g["stat"][:18], g["side"].upper(), g["line"], 100 * g["p"], g["why"][:50]))
    slips_txt.append("**%s SLIP %d** · %s · %d-pick %gx · all ~%.0f%%" % (tag_, k_, fam_, len(grp_), mult_, 100 * ph_) + chr(10) + chr(10).join(
        "%s **%s** %s %s · %.0f%%" % ("🔺 HIGHER" if g["side"] == "over" else "🔻 LOWER", g["player"], g["stat"], g["line"], 100 * g["p"]) for g in grp_))
# every PAPER slip (and every BET slip) is logged for grading -- dedupe by legs
try:
    _ps_seen = set()
    if os.path.exists("paper_slips.jsonl"):
        for x in open("paper_slips.jsonl", encoding="utf-8"):
            if x.strip():
                _ps_seen.add(json.loads(x)["sig"])
    with open("paper_slips.jsonl", "a", encoding="utf-8") as pf:
        for k_, grp_, ph_, mult_, tag_, fam_ in slips:
            sg = "|".join(sorted("%s/%s/%s/%s" % (g["player"], g["stat"], g["line"], g["side"]) for g in grp_))
            if sg in _ps_seen:
                continue
            pf.write(json.dumps(dict(logged=datetime.datetime.now(CT).isoformat(timespec="minutes"), tag=tag_, league=fam_, mult=mult_, p=round(ph_, 4), sig=sg,
                                     legs=[{kk: g.get(kk) for kk in ("sport", "player", "team", "opp", "stat", "line", "side", "p", "start")} for g in grp_],
                                     result=None), ensure_ascii=False) + chr(10))
except Exception as e:
    print("paper log:", e)


try:
    # 10/9: the card goes to Discord #card as rich cards (_cardpost.py): a header, then one message per slip with a card per leg
    import _cardpost as C
    feed = " || ".join(x.replace("\n", " | ") for x in slips_txt) or "no slip"
    with open(os.path.join("daily_log", "feed.txt"), "a", encoding="utf-8") as f_:
        f_.write("%s CARD: %s\n" % (datetime.datetime.now(CT).strftime("%m-%d %I:%M %p"), feed))
    side = lambda X: "\n".join("%s **%s** %s %g · %.0f%%" % ("🔺" if x["side"] == "over" else "🔻", x["player"], x["stat"], x["line"], 100 * x["p"])
                               for x in X[:6]) or "none qualified"
    rl = C.roll()
    # 10/10 cloud line-release scanner: never post the same slip twice; NEW_ONLY runs (every 30 min) stay silent unless a NEW slip qualifies
    sig = lambda grp_: "|".join(sorted("%s/%s/%s/%s" % (g["player"], g["stat"], g["line"], g["side"]) for g in grp_))
    posted, posted_players = set(), set()
    if os.path.exists("_slips_posted.jsonl"):
        cut = (datetime.datetime.now(CT) - datetime.timedelta(days=7)).isoformat()   # 10/16: 2 days let Raridon (posted Wed for Sun) get re-posted Fri -- NFL slips post days early
        for x in open("_slips_posted.jsonl", encoding="utf-8"):
            if x.strip():
                rr = json.loads(x)
                if rr.get("posted", "") >= cut:
                    posted.add(sig(rr["legs"]))
                    # 10/13: Pionk landed on 3 posted slips in one morning (each scan reshuffled his partner) -> one posted slip per
                    # player per game: a player already on a posted slip for that game is never posted again in a new combo
                    posted_players |= {(g["player"], (g.get("start") or "")[:10]) for g in rr["legs"]}
    paper_slips = [t for t in slips if t[4] == "PAPER"]
    slips = [t for t in slips if t[4] == "BET"]
    fresh = [t for t in slips if sig(t[1]) not in posted and not any((g["player"], (g.get("start") or "")[:10]) in posted_players for g in t[1])]
    # 10/10 user: "5 bets max" a day -- count today's real bets + slips already posted today; post only what fits, best value first
    _today = datetime.datetime.now(CT).date().isoformat()
    # 10/13 user: an early-locked slip (NFL 3-pick placed Tue for Sunday) counts on its GAME day (game_date), not the day it was placed
    _bets = sum(1 for x in open("live_paper.jsonl", encoding="utf-8") if x.strip() and json.loads(x).get("kind") == "LIVE"
                and (json.loads(x).get("game_date") or json.loads(x).get("date")) == _today)
    _cards = sum(1 for x in open("_slips_posted.jsonl", encoding="utf-8") if x.strip() and json.loads(x).get("posted", "")[:10] == _today)         if os.path.exists("_slips_posted.jsonl") else 0
    # 10/15 user ("of the 300+ lines we only bet a few -- choose the best ones and bet them with confidence"): BEST 3 slips a day at a
    # bigger stake. Backtest (107 graded legs, 1,000 tie orders): top-ranked legs hit 77%, legs 5-10 56% (below the 57.7% b/e);
    # best 3 x 6.5-7.5% beat 5 x 5% (median $102 vs $87 from $40, same downside). Ranked by joint p (model + market prior).
    room = max(0, MAX_SLIPS - max(_bets, _cards))
    fresh = sorted(fresh, key=lambda t: -t[2])[:room]
    _pos0 = max(_bets, _cards)                                         # slips already placed/posted today -> where these land in the tiers
    if room == 0:
        print("daily cap reached (%d best slips today) -- nothing new posted" % MAX_SLIPS)
    print("slips: %d qualify, %d new" % (len(slips), len(fresh)))
    # 10/14 user ("how tf did we not flag Allgeier 4.5 rush atts"): Allgeier O4.5 rush att passed NFL AGREE (avg 7.6, role 5.7) but the NFL
    # slip was already posted (BTJ/Raridon), so he had no fresh partner and never surfaced; PP moved it to 6.5 within minutes. A BET-eligible
    # leg that lands on no slip now posts ONCE as a solo-leg alert -- pair it with anything on the card or play it on a promo.
    try:
        _inslip = {(g["player"], (g.get("start") or "")[:10]) for t in fresh for g in t[1]} | posted_players
        _SF = "_solo_alerted.json"
        _sa = set(json.load(open(_SF, encoding="utf-8"))) if os.path.exists(_SF) else set()
        # "crazy" = PP just moved the line our way: the last different standard line for this player+stat (lines.db, 3 days) was 15%+
        # tougher (Allgeier rush att 6.5 -> 4.5 on an over). A big % gap alone is NOT crazy -- tiny lines (O3.5 rec yds) make it trivial.
        import sqlite3 as _sq
        _ldb = _sq.connect("lines.db", timeout=60) if os.path.exists("lines.db") else None
        def _moved_our_way(x):
            if not _ldb:
                return None
            cut_ = (datetime.datetime.now(CT) - datetime.timedelta(days=3)).strftime("%Y-%m-%dT%H%M%S")
            r_ = _ldb.execute("select line from pp where player=? and stat=? and kind='standard' and line!=? and last_seen>=? order by last_seen desc limit 1",
                              (x["player"], x["stat"], x["line"], cut_)).fetchone()
            if not r_:
                return None
            mv = (r_[0] - x["line"]) / max(r_[0], 0.5) * (1 if x["side"] == "over" else -1)
            need = 5.0 if "Yds" in x["stat"] or "Yards" in x["stat"] else 1.0   # 1-yard moves on O5.5 rec yds are noise, not a pull
            return r_[0] if mv >= 0.15 and abs(r_[0] - x["line"]) >= need else None
        _solo = []
        for x in sorted(std, key=lambda s: (-s["p"], -s.get("gap", 0))):
            if money_ok(x) and x.get("kind", "standard") == "standard" and (x["player"], (x.get("start") or "")[:10]) not in _inslip                     and "%s|%s|%s|%s" % (x["player"], x["stat"], x["line"], x["side"]) not in _sa:
                _was = _moved_our_way(x)
                if _was is not None or CRAZY(x):
                    x["was_line"] = _was
                    _solo.append(x)
        _solo = _solo[:3]
        # 10/14 user: "if theres a crazy pull like that, you force a pair". A CRAZY solo leg (promo, p >= 66%, or an edge of 25%+ off the
        # line) gets the best partner we have: a fresh BET-eligible leg first, else a BET-eligible leg already on a posted slip, else any
        # 60%+ leg -- different team and game. Posted as a real 2-pick (half stake if either leg is probation), outside the 5-a-day cap.
        _forced = []
        # 10/14 user: "just put both crazy legs together" -- crazy legs pair with EACH OTHER first (different teams; same game allowed,
        # e.g. Hill BAL + Watson CLE -- opposing-side legs measured independent); only a leftover crazy leg gets a regular partner.
        _left = sorted(_solo, key=lambda y: y.get("was_line") is None)        # line-pull legs pair with each other before p-only crazies
        while len(_left) >= 2:
            a_ = _left.pop(0)
            b_ = next((y for y in _left if y["team"] != a_["team"]), None)
            if not b_:
                break
            _left.remove(b_); _forced.append([a_, b_])
        for x in _left:
            _ok = lambda y: y is not x and y["team"] != x["team"] and {y["team"], y.get("opp")} != {x["team"], x.get("opp")} and y.get("kind", "standard") == "standard"                 and all(y is not g for t in _forced for g in t)
            _pool = sorted([y for y in std if _ok(y)], key=lambda y: (-y["p"], -y.get("gap", 0)))
            _mate = next((y for y in _pool if money_ok(y) and (y["player"], (y.get("start") or "")[:10]) not in _inslip), None)                 or next((y for y in _pool if money_ok(y)), None) or next((y for y in _pool if y["p"] >= 0.60), None)
            if _mate:
                _forced.append([x, _mate])
        for grp_ in _forced:
            for g in grp_:
                g["probation"] = bool(probation(g))
            _half = not all(money_ok(g) for g in grp_)
            C.post_embed("🚨 FORCED PAIR · crazy line, %s %s %g%s -- locked in with our best partner" % (grp_[0]["player"], grp_[0]["stat"], grp_[0]["line"],
                         " (was %g)" % grp_[0]["was_line"] if grp_[0].get("was_line") is not None else ""),
                         "Partner: **%s** %s %g %s (%.0f%%)%s" % (grp_[1]["player"], "HIGHER" if grp_[1]["side"] == "over" else "LOWER", grp_[1]["line"], grp_[1]["stat"],
                                                                   100 * grp_[1]["p"], "" if money_ok(grp_[1]) else " -- paper-tier partner, half stake"), 0xFF3B3B)
            C.post_slip(99, grp_, grp_[0]["p"] * grp_[1]["p"], stake=(0.025 if _half else (STAKE if all(_strong_leg(g) for g in grp_) else 0.05)) * rl if rl else None, mult=3.0, be=0.577)
            print("FORCED PAIR posted:", " / ".join(g["player"] for g in grp_))
        _solo = [x for x in _solo if not any(x is g for t in _forced for g in t)]
        if _forced:
            _sa |= {"%s|%s|%s|%s" % (g["player"], g["stat"], g["line"], g["side"]) for t in _forced for g in t if g.get("was_line") is not None or CRAZY(g)}
            json.dump(sorted(_sa), open(_SF, "w", encoding="utf-8"))
        if _solo:
            C.post_embed("⚡ SOLO LEG · qualifies, no fresh partner -- pair it or play it now", chr(10).join(
                "%s **%s** %s %g %s · %.0f%%%s · %s" % ("🔺" if x["side"] == "over" else "🔻", x["player"], "HIGHER" if x["side"] == "over" else "LOWER", x["line"], x["stat"],
                                                      100 * x["p"], " · 🟡 half stake" if probation(x) else "", x.get("why", "")[:160]) for x in _solo), 0xFFD400)
            _sa |= {"%s|%s|%s|%s" % (x["player"], x["stat"], x["line"], x["side"]) for x in _solo}
            json.dump(sorted(_sa), open(_SF, "w", encoding="utf-8"))
            print("SOLO legs posted:", len(_solo))
    except Exception as e:
        print("solo legs:", e)
    if os.environ.get("NEW_ONLY") and not fresh:
        raise SystemExit(0)                                            # scanner: nothing new -> no Discord noise
    slips = fresh
    _h = datetime.datetime.now(CT).hour
    C.post_embed((("🌙 OVERNIGHT EDGE · %s" if (_h >= 23 or _h < 7) else "🆕 NEW LINES · %s") if os.environ.get("NEW_ONLY") else ("🧾 TOMORROW'S CARD · %s" if datetime.datetime.now(CT).hour >= 18 else "🧾 TODAY'S CARD · %s")) % datetime.datetime.now(CT).strftime("%a %m/%d %I:%M %p"),
                 "**%d slip%s** below%s.\n\n**🔺 OVERS that qualify (%d)**\n%s\n\n**🔻 UNDERS that qualify (%d)**\n%s"
                 % (len(slips), "" if len(slips) == 1 else "s", (" · roll $%.2f · stakes: first 3 $%.2f if STRONG (proj 20%%+ past the line + history backs it) / $%.2f, then $%.2f" % (rl, STAKE * rl, 0.05 * rl, 0.025 * rl)) if rl else "",
                    len(_ov), side(_ov), len(_un), side(_un)))
    for _i, (k_, grp_, ph_, mult_, tag_, fam_) in enumerate(slips):
        for g in grp_:
            g["probation"] = bool(probation(g))
        _sk = _stake_for(_pos0 + _i, grp_)
        print("  slip %d of the day: %s -> stake %.1f%%" % (_pos0 + _i + 1, "STRONG (every leg 20%+ past the line + history backs it)" if all(_strong_leg(g) for g in grp_) else "regular", 100 * _sk))
        C.post_slip(k_, grp_, ph_, stake=_sk * rl if rl else None, mult=mult_, be=0.55 if mult_ == 6.0 else 0.577)
    _pp = [t for t in paper_slips if sig(t[1]) not in posted]
    if _pp and not os.environ.get("NEW_ONLY"):
        C.post_embed("📝 PAPER SLIPS · not bets -- tracked to build each league's record", chr(10).join(
            "📝 **%s** · %d-pick %gx · all ~%.0f%% · %s" % (fam_, len(grp_), mult_, 100 * ph_, " / ".join("%s %s%g %s" % (g["player"], "O" if g["side"] == "over" else "U", g["line"], g["stat"].replace("MAPS 1-2 ", "")) for g in grp_))
            for k_, grp_, ph_, mult_, tag_, fam_ in _pp), 0x7C7C7C)
    if not slips and not os.environ.get("NEW_ONLY"):
        C.post_embed("🧾 No new slip", "No 2 legs from different teams pass a proven filter on the live board yet -- more lines post overnight and the 15-min scanner posts anything that qualifies. Never force a slip.")
except Exception as e:
    print("card post:", e)


# 10/10: refresh the cloud alert watch list (open bets + card legs) after every card build
try:
    subprocess.run([sys.executable, "_watchlist.py"], timeout=120)
except Exception as e:
    print("watchlist:", e)
