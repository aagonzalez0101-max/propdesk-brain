"""STANDARD + GOBLIN "2x" PAIRS (2026-10-09, user: "always choose the best MISPRICED standard with data from our model, then the
best goblin you decide -- that's how we get the 2x's").
  standard leg = our model's edge: today's direction-filter picks (direction_paper.jsonl, 3+ reasons, 0 against), the CS2 high-line
                 under filter, re-checked against the LIVE PrizePicks board (PP line first, then sharps; a sharp book that disagrees
                 by 5+ pts drops the leg)
  goblin leg   = the highest sharp-priced goblin (Pinnacle/FanDuel at PP's exact number) from a DIFFERENT game and team
  value        = p_std x p_gob x payout - 1; bet only if the app's payout >= 1 / (p_std x p_gob) + ~5% cushion.
    python _pair2x.py
"""
import json, datetime, os, subprocess, sys, collections
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
for sp, lg in LG.items():
    try:
        for l in P.prizepicks(lg, max_age=int(os.environ.get("PP_MAX_AGE", 180))):                      # 429s at max_age=0 -> a 3-minute-old board is fine
            if l.get("kind") == "standard" and "+" not in (l.get("player") or ""):
                live[(sp, M.norm(l["player"]), M.norm(l["stat"]))] = l
    except Exception as e:
        print(sp, "pp:", e)

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
if os.path.exists("cs2_paper.jsonl"):
    for x in open("cs2_paper.jsonl", encoding="utf-8"):
        r = json.loads(x)
        e = r.get("edge") or 0
        if not (0.03 <= e <= 0.09) or str(r.get("start", ""))[:10] < today or r.get("maps") != 2:
            continue
        if datetime.datetime.fromisoformat(r["start"].replace("Z", "+00:00")) < now or M.norm(r["player"]) in USED:
            continue
        stat = "MAPS 1-2 Headshots" if r.get("kind") == "hs" else "MAPS 1-2 Kills"
        l = live.get(("CS2", M.norm(r["player"]), M.norm(stat)))
        side = "over" if r.get("side") == "higher" else "under"
        if not l or (side == "over" and l["line"] > r["line"]) or (side == "under" and l["line"] < r["line"]):
            continue                                                   # PP number must be as good as the one the model priced
        k = (r["player"], stat)
        if k in seen_cs:
            continue
        seen_cs.add(k)
        coin = 0.45 <= (r.get("map_winp") or 0.5) <= 0.55
        pc = __import__("_calib_es").cal("cs2", r.get("model_p"))   # 10/10: calibrated -- CS2 calls really hit ~56%, not 62-68%
        std.append(dict(sport="CS2", paper=os.environ.get("CS2_LIVE") != "1", player=r["player"], team=r.get("team"), opp=r.get("opp"), stat=stat, line=l["line"], side=side,
                        p=round(pc or 0.56, 3), why="CS2 rule: edge %.1f%%%s, model %.0f%% -> real ~%.0f%%" % (100 * e, "" if coin else ", lopsided map", 100 * (r.get("model_p") or 0), 100 * (pc or 0.56)),
                        start=l["start"], img=l.get("img")))

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
                        p=0.61, why="NFL BETA own-rate: %d of %d games %s, avg %.1f (1 week measured: 61%%, holdout 49%%)"
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
                            line=r["line"], side=r["side"], p=0.70, start=r["start"],
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
        _pj = r.get("adj_mean") or r.get("proj")
        if not tk and (_pj is None or _pj > 0.85 * float(lv["line"])):
            continue                     # 10/13: both preseason-under misses were LEANs within 15% of the line (Wemby 2.6 vs 3, McDaniels 19.9 vs 21.5)
        std.append(dict(sport="NBAP", nba_pre_under=True, paper=not NBAP_LIVE, player=lv["player"], team=lv.get("team") or r.get("team"), opp=lv.get("opp") or r.get("opp"),
                        stat=lv["stat"], line=lv["line"], side="under", p=0.72 if tk else 0.62, start=lv["start"],
                        why="NBA preseason %s (graded unders 20-2): proj %s vs line %s" % (r["call"], r.get("adj_mean") or r.get("proj"), lv["line"])))
        _have2.add(pn)
        print("  NBA PRESEASON UNDER leg: %s %s U%s (%s, called at %s)" % (lv["player"], lv["stat"], lv["line"], r["call"], r["line"]))
except Exception as e:
    print("nba preseason unders:", e)

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
        _p = 0.62 if min(abs(g0), abs(g1)) >= 0.20 else 0.60
        std.append(dict(sport="NFL", nfl_agree=True, paper=not NFL_AGREE_LIVE, player=l["player"], team=l.get("team"), opp=l.get("opp"), stat=l["stat"],
                        line=l["line"], side=side, p=_p, start=l["start"],
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

# 10/13 user ("do NBA then"): NBA ROLE UNDERS. Basketball backtest: own average AND minutes model agreeing was 44-50% overall, but
# agreeing on the UNDER (both 10%+ under the line) went WNBA 27-11 (71%), NBA preseason 3-0 -- our basketball numbers run hot on
# overs. Regular-season NBA (league 7) only. PAPER until 30 forward legs at 60%+, then BET by itself (nba_role_paper.jsonl).
def _nbarole_switch():
    try:
        g = [json.loads(x) for x in open("nba_role_paper.jsonl", encoding="utf-8") if x.strip()] if os.path.exists("nba_role_paper.jsonl") else []
        g = [r for r in g if r.get("result") in ("W", "L")]
        w = sum(r["result"] == "W" for r in g); ok = len(g) >= 30 and w / len(g) >= 0.60
        print("NBA ROLE UNDERS forward: %d-%d -> %s" % (w, len(g) - w, "BET" if ok else "PAPER")); return ok
    except Exception as e:
        print("nba role switch:", e); return False
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
            if raw_ > 0.90 * l["line"] or role_ > 0.90 * l["line"]:
                continue
            std.append(dict(sport="NBA", nba_role_under=True, paper=not NBA_ROLE_LIVE, player=l["player"], team=l.get("team"), opp=l.get("opp"), stat=l["stat"],
                            line=l["line"], side="under", p=0.65, start=l["start"],
                            why="NBA ROLE UNDER: own avg %.1f + minutes model %.1f (%.0f min) both 10%%+ under %s (WNBA backtest 71%%)" % (raw_, role_, pmin_, l["line"])))
            _have4.add(M.norm(l["player"])); _n_nr += 1
            if (l["player"], l["stat"], _day) not in _seen_nr:
                with open("nba_role_paper.jsonl", "a", encoding="utf-8") as _nf:
                    _nf.write(json.dumps(dict(logged=today, day=_day, player=l["player"], team=l.get("team"), opp=l.get("opp"), stat=l["stat"], line=l["line"],
                                              raw=round(raw_, 1), role=round(role_, 1), pmin=round(pmin_, 1), start=l["start"], result=None), ensure_ascii=False) + chr(10))
                _seen_nr.add((l["player"], l["stat"], _day))
        print("NBA ROLE UNDER legs: %d" % _n_nr)
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
for s in sorted(std, key=lambda s: -s["p"]):
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
money_ok = lambda s: bool(s.get("promo")) or (bool(s.get("beta")) and NFL_BETA_LIVE) or bool(s.get("soccer_hit")) or bool(s.get("nhl_under")) or (bool(s.get("nba_pre_under")) and NBAP_LIVE) or (bool(s.get("nfl_agree")) and NFL_AGREE_LIVE) or (bool(s.get("nba_role_under")) and NBA_ROLE_LIVE) or (s["sport"] in ("NHL", "WNBA") and not s.get("paper"))
CRAZY = lambda s: bool(s.get("promo")) or s["p"] >= 0.66
by_fam = collections.defaultdict(list)
for s in sorted(std, key=lambda s: -s["p"]):
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
_promos_wild = [s for s in sorted(std, key=lambda s: -s["p"]) if s.get("promo")]
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
left = [s for s in sorted(std, key=lambda s: -s["p"]) if id(s) not in used_leg and CRAZY(s)]
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
        cut = (datetime.datetime.now(CT) - datetime.timedelta(days=2)).isoformat()
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
    room = max(0, 5 - max(_bets, _cards))
    fresh = sorted(fresh, key=lambda t: -t[2])[:room]
    if room == 0:
        print("daily cap reached (5 bets/slips today) -- nothing new posted")
    print("slips: %d qualify, %d new" % (len(slips), len(fresh)))
    if os.environ.get("NEW_ONLY") and not fresh:
        raise SystemExit(0)                                            # scanner: nothing new -> no Discord noise
    slips = fresh
    _h = datetime.datetime.now(CT).hour
    C.post_embed((("🌙 OVERNIGHT EDGE · %s" if (_h >= 23 or _h < 7) else "🆕 NEW LINES · %s") if os.environ.get("NEW_ONLY") else ("🧾 TOMORROW'S CARD · %s" if datetime.datetime.now(CT).hour >= 18 else "🧾 TODAY'S CARD · %s")) % datetime.datetime.now(CT).strftime("%a %m/%d %I:%M %p"),
                 "**%d slip%s** below%s.\n\n**🔺 OVERS that qualify (%d)**\n%s\n\n**🔻 UNDERS that qualify (%d)**\n%s"
                 % (len(slips), "" if len(slips) == 1 else "s", (" · roll $%.2f · stake $%.2f each" % (rl, 0.05 * rl)) if rl else "",
                    len(_ov), side(_ov), len(_un), side(_un)))
    for k_, grp_, ph_, mult_, tag_, fam_ in slips:
        C.post_slip(k_, grp_, ph_, stake=0.05 * rl if rl else None, mult=mult_, be=0.55 if mult_ == 6.0 else 0.577)
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
