"""POST-MORTEM v2 -- every graded lean, every sport/esport, bet or not, with the STATS behind each result and what to fix
(2026-10-09, user: "more in-depth reasoning with stats backing it up and what can be fixed").

    python _postmortem.py [YYYY-MM-DD]      # default: yesterday (CT)

For each graded leg: call (HIGHER/LOWER), our projection, the actual, and the DRIVERS vs the player's own normal:
  NHL skater  ice time, power-play time, shot ATTEMPTS (on goal + missed + blocked, from play-by-play) vs his last-10, team shots,
              final margin  -> was it opportunity (TOI/PP), volume (attempts), or finishing (attempts fine, few on goal)?
  NHL goalie  shots faced vs what our saves projection implied, the opponent's shot rate this season, goals allowed, pulled?
  WNBA/NBA    minutes and shot attempts vs his last-10, final margin (blowout benching)
  SOCCER      minutes played (sub/started), per-90 rate vs line, final score
  CS2/VAL     rounds played vs a normal series (2 maps ~ 43 rounds; 30+ on a map = overtime), kills per round vs what the model implied
  DOTA/GOLF   projection error only
Every MISS gets a cause + a concrete fix; the summary ranks fixes by how many misses they would have addressed.
Lines: venue split -- PP lines graded separately from Underdog (UD 0.5 'lopsided' lines inflate hit rates). Duplicate stat names merged.
"""
import sys, os, json, re, sqlite3, datetime, collections, requests, statistics as st

CT = datetime.timezone(datetime.timedelta(hours=-5))
DAY = sys.argv[1] if len(sys.argv) > 1 else (datetime.datetime.now(CT).date() - datetime.timedelta(days=1)).isoformat()
NHL = "https://api-web.nhle.com/v1"
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
SAME = {"goaliesaves": "saves", "shotsongoal": "sog", "shotsongoals": "sog", "ptsrebsasts": "pra", "pointsreboundsassists": "pra",
        "ptsrebs": "pr", "pointsrebounds": "pr", "ptsasts": "pa", "pointsassists": "pa", "rebsasts": "ra", "reboundsassists": "ra",
        "3pointersmade": "3pm", "3ptmade": "3pm"}
canon = lambda s: SAME.get(norm(s), norm(s))
def nkey(name):
    p = (name or "").replace(".", ". ").split()
    return norm(p[0][:1] + "".join(p[1:])) if len(p) > 1 else norm(name)
def mins(s):
    try:
        m, sec = (s or "0:00").split(":"); return int(m) + int(sec) / 60
    except Exception:
        return 0.0

# ---------------------------------------------------------------- legs (deduped: same player + canonical stat + line + venue group)
legs, seen = [], set()
def add(sport, src, venue, player, stat, line, side, proj, actual, why="", team=None, extra=None):
    try:
        actual, line = float(actual), float(line)
    except (TypeError, ValueError):
        return
    if actual == line or side not in ("over", "under"):
        return
    k = (sport, norm(player), canon(stat), line, "UD" if venue == "UD" else "PP")
    if k in seen:
        return
    seen.add(k)
    legs.append(dict(sport=sport, src=src, venue="UD" if venue == "UD" else "PP", player=player, stat=stat, line=line, side=side,
                     proj=(float(proj) if proj not in (None, "") else None), actual=actual, hit=(actual > line) if side == "over" else (actual < line),
                     why=why, team=team, extra=extra or {}))
for l in open("calls_log.jsonl", encoding="utf-8"):
    r = json.loads(l)
    if r.get("date") != DAY or r.get("kind") in ("goblin", "demon") or r.get("actual") is None:
        continue
    c = str(r.get("call", ""))
    if not (c.startswith("TAKE") or c.startswith("LEAN")):
        continue
    side = "over" if "OVER" in c else "under" if "UNDER" in c else None
    m = r.get("mult")
    if isinstance(m, dict):
        m = m.get("higher" if side == "over" else "lower")
    try:
        if r.get("venue") == "UD" and m is not None and (float(m) >= 1.5 or float(m) <= 0.7):
            continue                                           # UD lopsided = goblin-like (user rule 10/3)
    except (TypeError, ValueError):
        pass
    add(r["sport"], "screen", r.get("venue"), r["player"], r["stat"], r["line"], side, r.get("proj") or r.get("adj_mean"), r["actual"],
        "; ".join(r.get("flags") or []), r.get("team"))
for fn, src in (("direction_paper.jsonl", "direction"),):
    if os.path.exists(fn):
        for l in open(fn, encoding="utf-8"):
            r = json.loads(l)
            if r["date"] == DAY and r.get("actual") is not None:
                add(r["sport"], src, "PP", r["player"], r["stat"], r["line"], r["side"], None, r["actual"], r.get("why", ""), r.get("team"))
for fn, sport in (("cs2_paper.jsonl", "CS2"), ("val_paper.jsonl", "VAL")):
    if os.path.exists(fn):
        for l in open(fn, encoding="utf-8"):
            r = json.loads(l)
            try:
                d = datetime.datetime.fromisoformat(str(r.get("start", "")).replace("Z", "+00:00")).astimezone(CT).date().isoformat()
            except Exception:
                continue
            if d == DAY and r.get("actual") is not None:
                add(sport, "paper", "PP", r["player"], r["stat"], r["line"], "over" if r.get("side") == "higher" else "under", r.get("model_mu"),
                    r["actual"], "edge %+.0f%%" % (100 * (r.get("edge") or 0)), r.get("team"),
                    dict(rounds=r.get("rounds"), maps_rounds=r.get("maps_rounds"), maps=r.get("maps") or 2, kind=r.get("kind")))
if os.path.exists("dota_paper.jsonl"):
    for l in open("dota_paper.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if r["date"] == DAY and r.get("actual") is not None:
            add("DOTA", "paper", "PP", r["player"], r["stat"], r["line"], r["side"], r.get("proj"), r["actual"], "model %.0f%%" % (100 * (r.get("p") or 0)))

# ---------------------------------------------------------------- NHL context: boxscore + play-by-play shot attempts + game logs
nhl = {}
if any(g["sport"] == "NHL" for g in legs):
    try:
        for gm in requests.get("%s/score/%s" % (NHL, DAY), timeout=30).json().get("games", []):
            gid = gm["id"]; b = requests.get("%s/gamecenter/%s/boxscore" % (NHL, gid), timeout=30).json()
            att = collections.Counter()
            try:
                pbp = requests.get("%s/gamecenter/%s/play-by-play" % (NHL, gid), timeout=30).json()
                for p in pbp.get("plays", []):
                    if p.get("typeDescKey") in ("shot-on-goal", "missed-shot", "blocked-shot", "goal"):
                        sid = (p.get("details") or {}).get("shootingPlayerId") or (p.get("details") or {}).get("scoringPlayerId")
                        if sid:
                            att[sid] += 1
            except Exception:
                pass
            hs, as_ = gm["homeTeam"].get("score") or 0, gm["awayTeam"].get("score") or 0
            tsog = {"homeTeam": gm["homeTeam"].get("sog"), "awayTeam": gm["awayTeam"].get("sog")}
            for side, oside, my, th in (("homeTeam", "awayTeam", hs, as_), ("awayTeam", "homeTeam", as_, hs)):
                for grp in ("forwards", "defense", "goalies"):
                    for p in (b.get("playerByGameStats") or {}).get(side, {}).get(grp, []):
                        nhl[nkey(p["name"]["default"])] = dict(pid=p["playerId"], toi=mins(p.get("toi")), pp=mins(p.get("powerPlayToi")), sog=p.get("sog"),
                            att=att.get(p["playerId"], 0), margin=my - th, team=b[side]["abbrev"], opp=b[oside]["abbrev"], team_sog=tsog[side],
                            opp_sog=tsog[oside], goalie=grp == "goalies", sa=p.get("shotsAgainst"), ga=p.get("goalsAgainst"), starter=p.get("starter"))
    except Exception as e:
        print("nhl context:", e)
_gl = {}
def nhl_normal(pid):
    if pid in _gl:
        return _gl[pid]
    rows = []
    for season in ("20262027", "20252026"):
        try:
            rows += [g for g in requests.get("%s/player/%s/game-log/%s/2" % (NHL, pid, season), timeout=30).json().get("gameLog", []) if g.get("gameDate", "") < DAY]
        except Exception:
            pass
        if len(rows) >= 10:
            break
    rows = rows[:10]
    f = lambda k: (st.mean([float(g[k]) if not isinstance(g[k], str) else mins(g[k]) for g in rows if g.get(k) is not None]) if any(g.get(k) is not None for g in rows) else None)
    _gl[pid] = dict(toi=f("toi"), pp=f("powerPlayToi"), sog=f("shots"), sa=f("shotsAgainst"), n=len(rows))
    return _gl[pid]
_ts = {}
def team_sf(team):
    if not _ts:
        try:
            teams = {t["id"]: t["triCode"] for t in requests.get("https://api.nhle.com/stats/rest/en/team", timeout=30).json()["data"]}
            for r in requests.get("https://api.nhle.com/stats/rest/en/team/summary?cayenneExp=seasonId=20262027%20and%20gameTypeId=2", timeout=30).json()["data"]:
                _ts[teams.get(r["teamId"])] = (r.get("shotsForPerGame"), r.get("gamesPlayed"))
        except Exception:
            pass
    return _ts.get(team, (None, None))

db = sqlite3.connect("sports.db")
def bball(sport, player):
    rows = db.execute("SELECT date, minutes, stats, team FROM player_games WHERE sport=? AND player=? AND date<=? ORDER BY date DESC LIMIT 11",
                      (sport, player, (datetime.date.fromisoformat(DAY) + datetime.timedelta(days=1)).isoformat())).fetchall()
    if not rows:
        return None
    s0 = json.loads(rows[0][2]); prev = [(r[1], json.loads(r[2])) for r in rows[1:] if r[1]]
    t = db.execute("SELECT stats, opp_stats FROM team_games WHERE sport=? AND date=? AND team=?", (sport, rows[0][0], rows[0][3])).fetchone()
    return dict(mins=rows[0][1], n_mins=st.mean(m for m, _ in prev) if prev else None, fga=s0.get("fga"),
                n_fga=st.mean(x.get("fga") or 0 for _, x in prev) if prev else None,
                margin=((json.loads(t[0]).get("pts") or 0) - (json.loads(t[1]).get("pts") or 0)) if t else None)

_sday = {}
def soccer_ctx(g):
    """FotMob: the match with this player's team on DAY -> his minutes + the score (PP voids DNPs; subs are graded)."""
    try:
        import _soccer as S
        import unicodedata
        nn = lambda s_: re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", s_ or "").encode("ascii", "ignore").decode().lower())
        if DAY not in _sday:
            L = []
            for lg in (S.get("%s/matches?date=%s" % (S.FM, DAY.replace("-", ""))).get("leagues") or []):
                for m in lg.get("matches") or []:
                    if (m.get("status") or {}).get("finished"):
                        L.append(m)
            _sday[DAY] = L
        for m in _sday[DAY]:
            box = S.match(m["id"]).get("playerStats", {})
            p = next((v for v in box.values() if nn(v.get("name")) == nn(g["player"])), None)
            if p:
                mn = S.fval(p.get("stats") or [], "Minutes played")
                per = (g["actual"] * 90.0 / mn) if mn else None
                return dict(min=mn, per90=per, score="%s %s-%s %s" % (m["home"]["name"], m["home"].get("score"), m["away"].get("score"), m["away"]["name"]))
    except Exception:
        return None
    return None

# ---------------------------------------------------------------- diagnose each leg
def diagnose(g):
    d, cause, fix = [], None, None
    if g["sport"] == "NHL":
        c = nhl.get(nkey(g["player"]))
        if c and not c["goalie"]:
            n = nhl_normal(c["pid"])
            d.append("TOI %.1f (normal %.1f)" % (c["toi"], n["toi"] or 0))
            d.append("attempts %d, on goal %s (normal SOG %.1f)" % (c["att"], c["sog"], n["sog"] or 0))
            d.append("%s %s by %d, team shots %s" % (c["team"], "won" if c["margin"] > 0 else "lost" if c["margin"] < 0 else "tied", abs(c["margin"]), c["team_sog"]))
            if not g["hit"]:
                low_toi = n["toi"] and c["toi"] < 0.85 * n["toi"]
                low_pp = False                                  # NHL public data has no PP ice time (10/9)
                if g["side"] == "over":
                    if low_toi:
                        cause, fix = "ROLE: ice time cut %.0f%%" % (100 * (1 - c["toi"] / n["toi"])), "pre-lock line-combination check (Daily Faceoff); skip players moved down"
                    elif low_pp:
                        cause, fix = "ROLE: power-play time cut", "check PP units before locking"
                    elif c["margin"] >= 3:
                        cause, fix = "GAME SCRIPT: team up by %d, coasted" % c["margin"], "flag star overs on heavy favorites (blowout risk) -- count repeats"
                    elif c["att"] >= (n["sog"] or 0) * 1.6:
                        cause, fix = "FINISHING: %d attempts but only %s on goal (volume was there)" % (c["att"], c["sog"]), "variance -- no fix"
                    else:
                        cause, fix = "VOLUME: only %d attempts vs normal ~%.0f with full ice time" % (c["att"], 1.7 * (n["sog"] or 0)), "check opponent shot suppression weight in model"
                else:
                    if c["margin"] <= -3:
                        cause, fix = "GAME SCRIPT: team down %d, chased (more shots)" % -c["margin"], "flag unders on big underdogs' shooters"
                    elif n["toi"] and c["toi"] > 1.15 * n["toi"]:
                        cause, fix = "ROLE: ice time UP %.0f%%" % (100 * (c["toi"] / n["toi"] - 1)), "pre-lock line check (promotions / injuries ahead of him)"
                    else:
                        cause, fix = "VOLUME: %d attempts, %s on goal above his ~%.1f" % (c["att"], c["sog"], n["sog"] or 0), "model under-projected his usage"
        elif c and c["goalie"]:
            n = nhl_normal(c["pid"]); sf, gp = team_sf(c["opp"])
            exp_sa = (g["proj"] / 0.905) if g["proj"] else None
            d.append("faced %s shots (proj implied %s), allowed %s" % (c["sa"], "%.0f" % exp_sa if exp_sa else "?", c["ga"]))
            d.append("%s shoots %.1f/game this season (%s GP)" % (c["opp"], sf or 0, gp))
            d.append("TOI %.0f, margin %+d" % (c["toi"], c["margin"]))
            if not g["hit"]:
                if c["toi"] < 50 and c.get("starter"):
                    cause, fix = "PULLED after %.0f min" % c["toi"], "variance on overs; no fix"
                elif g["side"] == "under":
                    cause, fix = "SHOT VOLUME: %s shots vs ~%s projected (opp avg %.1f)" % (c["sa"], "%.0f" % exp_sa if exp_sa else "?", sf or 0), \
                                 "early-season opponent shot rates (<10 GP) -> weight last season more"
                else:
                    cause, fix = "SHOT VOLUME: only %s shots faced" % c["sa"], "check opponent's shot rate trend"
    elif g["sport"] in ("WNBA", "NBA"):
        c = bball(g["sport"], g["player"])
        if c:
            d.append("min %.0f (normal %.0f)" % (c["mins"] or 0, c["n_mins"] or 0))
            if c["fga"] is not None:
                d.append("FGA %s (normal %.1f)" % (c["fga"], c["n_fga"] or 0))
            if c["margin"] is not None:
                d.append("margin %+d" % c["margin"])
            if not g["hit"]:
                if c["n_mins"] and (c["mins"] or 0) < 0.85 * c["n_mins"]:
                    cause = "MINUTES: %.0f vs %.0f normal" % (c["mins"] or 0, c["n_mins"])
                    fix = "blowout/foul/injury minutes risk -> full-minutes screen + injury report pre-lock" if c["margin"] is None or abs(c["margin"]) < 20 else "blowout bench -> flag big spreads"
                elif c["n_fga"] and c["fga"] is not None and g["side"] == "over" and c["fga"] < 0.8 * c["n_fga"]:
                    cause, fix = "USAGE: %s shots vs %.1f normal with full minutes" % (c["fga"], c["n_fga"]), "check role/usage changes (teammate returns)"
                elif c["n_fga"] and c["fga"] is not None and g["side"] == "under" and c["fga"] > 1.2 * c["n_fga"]:
                    cause, fix = "USAGE UP: %s shots vs %.1f normal" % (c["fga"], c["n_fga"]), "teammate out? check injury report pre-lock"
                else:
                    cause, fix = "EFFICIENCY/VARIANCE: normal minutes and usage", "no fix"
    elif g["sport"] == "SOCCER":
        c = soccer_ctx(g)
        if c:
            d.append("minutes %s%s, final %s" % (c["min"], " (sub/benched)" if c["min"] is not None and c["min"] < 60 else "", c["score"]))
            if c.get("per90") is not None:
                d.append("per 90: %.1f vs line %.1f" % (c["per90"], g["line"]))
            if not g["hit"]:
                if c["min"] is not None and c["min"] < 60 and g["side"] == "over":
                    cause, fix = "MINUTES: only %s min" % c["min"], "starts-only screen: skip players with <4 of last 5 starts / rotation risk"
                elif c["min"] is not None and g["side"] == "under" and c["min"] >= 85 and c.get("per90") and c["per90"] > g["line"] * 1.2:
                    cause, fix = "RATE: full 90 at %.1f per 90 (line %.1f)" % (c["per90"], g["line"]), "game-script/possession input (team chasing or dominating)"
    elif g["sport"] in ("CS2", "VAL"):
        e = g["extra"]; rounds = e.get("rounds"); maps = e.get("maps") or 2; normal = 21.5 * maps
        if g["proj"]:
            kpr_model = g["proj"] / normal
            d.append("proj %.1f over ~%.0f rounds (%.3f/round)" % (g["proj"], normal, kpr_model))
        if rounds:
            d.append("played %d rounds %s (%.3f/round)" % (rounds, e.get("maps_rounds"), g["actual"] / rounds))
            if not g["hit"]:
                ot = any(r_ > 30 for r_ in (e.get("maps_rounds") or []))
                if g["side"] == "under" and rounds >= normal + 5:
                    cause, fix = "LONG SERIES: %d rounds vs ~%.0f normal%s" % (rounds, normal, " (overtime)" if ot else ""), \
                                 "add a round-count spread to the kill model; avoid unders on close (coin-flip) matchups"
                elif g["side"] == "over" and rounds <= normal - 5:
                    cause, fix = "SHORT SERIES: %d rounds (stomp)" % rounds, "avoid overs on lopsided matchups (map win prob <35% or >65%)"
                elif g["proj"] and abs(g["actual"] / rounds - kpr_model) > 0.12:
                    cause, fix = "PER-ROUND: %.3f kills/round vs %.3f modeled" % (g["actual"] / rounds, kpr_model), "role/agent/opponent-skill input in kill model"
                else:
                    cause, fix = "VARIANCE: normal rounds and rate", "no fix"
        elif not g["hit"]:
            cause, fix = "UNKNOWN (no round data)", "regrade with rounds"
    if not g["hit"] and cause is None:
        err = abs(g["actual"] - g["proj"]) if g["proj"] is not None else abs(g["actual"] - g["line"])
        cause, fix = ("VARIANCE (miss %.1f)" % err, "no fix") if err <= 0.6 * {"SOCCER": 2.5, "GOLF": 3.1, "DOTA": 4.0}.get(g["sport"], 3.0) else \
                     ("MODEL (off by %.1f)" % err, "review this player's inputs")
    return cause or "HIT", fix, "; ".join(d)

out = []
for g in legs:
    cause, fix, detail = diagnose(g)
    out.append(dict(g, day=DAY, call="HIGHER" if g["side"] == "over" else "LOWER", cause=cause, fix=fix, detail=detail))
with open("postmortem.jsonl", "a", encoding="utf-8") as f:
    for r in out:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

print("POST-MORTEM %s -- every graded lean, every sport/esport (bet or not)" % DAY)
for sp in sorted({r["sport"] for r in out}):
    for ven in ("PP", "UD"):
        S = [r for r in out if r["sport"] == sp and r["venue"] == ven]
        if not S:
            continue
        w = sum(r["hit"] for r in S)
        print("\n%s (%s lines): model right %d of %d (%.0f%%)" % (sp, ven, w, len(S), 100 * w / len(S)))
        if ven == "UD":
            continue                                             # UD = reference only (account closed)
        fixes = collections.Counter(r["fix"] for r in S if not r["hit"] and r["fix"] and r["fix"] != "no fix")
        for fx, n in fixes.most_common(4):
            print("   FIX (%d misses): %s" % (n, fx))
        for r in sorted([r for r in S if not r["hit"]], key=lambda r: -abs(r["actual"] - r["line"]))[:6]:
            print("   ❌ %-20s %-14s %s %-5g -> %-5g | %s" % (r["player"][:20], r["stat"][:14], r["call"], r["line"], r["actual"], r["cause"]))
            if r["detail"]:
                print("        %s" % r["detail"])
if not out:
    print("no graded leans for %s yet" % DAY)
