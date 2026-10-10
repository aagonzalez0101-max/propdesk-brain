"""MLB -- team matchup card, player profiles, and the prop screen with projection calls (2026-09-30, built for the playoffs).

    python _mlb.py card "Chicago Cubs" "San Diego Padres"     # offense + defense, both teams, ranked of 30
    python _mlb.py profile "Ha-Seong Kim"                      # hitter or pitcher scouting file
    python _mlb.py screen [YYYY-MM-DD]                         # every PP/UD MLB line -> projection -> call (logged)

Playoff adjustments are the MEASURED ones: hitter overs run ~5pp under regular-season rates (3,432 games) -> hitter means
x0.93; starters record 2.6 fewer outs (workhorses -1.9, others -2.9; 304 starts); run scoring -0.94/game (171 games).
"""
import sys, os, json, re, math, datetime, statistics as st, requests
from concurrent.futures import ThreadPoolExecutor
import _props as P

H = {"User-Agent": "Mozilla/5.0"}
S = "https://statsapi.mlb.com/api/v1"
SEASON = 2026
CT = datetime.timezone(datetime.timedelta(hours=-5))
CACHE = "_mlb_cache"
os.makedirs(CACHE, exist_ok=True)
jget = lambda path, **p: requests.get(S + path, params=p, headers=H, timeout=40).json()


def cached(key, fn, hours=12):
    f = os.path.join(CACHE, re.sub(r"[^A-Za-z0-9_.-]", "_", key) + ".json")
    if os.path.exists(f) and (datetime.datetime.now().timestamp() - os.path.getmtime(f)) < hours * 3600:
        try:
            return json.load(open(f, encoding="utf-8"))
        except ValueError:
            pass
    v = fn()
    import threading
    tmp = f + ".tmp%d_%d" % (os.getpid(), threading.get_ident())
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(v, fh)
        os.replace(tmp, f)
    except OSError:                  # another thread won the race for the same file -- its copy is identical
        try:
            os.remove(tmp)
        except OSError:
            pass
    return v


num = lambda x: float(x) if x not in (None, "", "-.--", ".---") else None


# ------------------------------------------------------------------ TEAM CARD
def team_table():
    def build():
        teams = {t["id"]: t["name"] for t in jget("/teams", sportId=1, season=SEASON)["teams"]}
        rows = {}
        for tid, name in teams.items():
            hit = {s["split"]["code"]: s["stat"] for s in jget("/teams/%d/stats" % tid, stats="statSplits", group="hitting", season=SEASON, sitCodes="vl,vr")["stats"][0]["splits"]}
            pit = {s["split"]["code"]: s["stat"] for s in jget("/teams/%d/stats" % tid, stats="statSplits", group="pitching", season=SEASON, sitCodes="sp,rp")["stats"][0]["splits"]}
            hs = jget("/teams/%d/stats" % tid, stats="season", group="hitting", season=SEASON)["stats"][0]["splits"][0]["stat"]
            ps = jget("/teams/%d/stats" % tid, stats="season", group="pitching", season=SEASON)["stats"][0]["splits"][0]["stat"]
            g = hs["gamesPlayed"]
            rows[name] = dict(id=tid, runs_pg=hs["runs"] / g, ops=num(hs["ops"]), k_pct=hs["strikeOuts"] / hs["plateAppearances"],
                              bb_pct=hs["baseOnBalls"] / hs["plateAppearances"], hr_pg=hs["homeRuns"] / g,
                              ops_vl=num((hit.get("vl") or {}).get("ops")), ops_vr=num((hit.get("vr") or {}).get("ops")),
                              ra_pg=ps["runs"] / g, era=num(ps["era"]), whip=num(ps["whip"]),
                              k_pct_p=ps["strikeOuts"] / ps["battersFaced"], sp_era=num((pit.get("sp") or {}).get("era")),
                              rp_era=num((pit.get("rp") or {}).get("era")), rp_whip=num((pit.get("rp") or {}).get("whip")),
                              ops_allowed=num(ps.get("ops")))
        # last 15 games: runs for / against
        end = datetime.date.today(); start = end - datetime.timedelta(days=30)
        d = jget("/schedule", sportId=1, startDate=start.isoformat(), endDate=end.isoformat(), gameType="R,F,D,L,W")
        games = {}
        for dt in d.get("dates", []):
            for gm in dt["games"]:
                if gm["status"]["abstractGameState"] != "Final":
                    continue
                a, h = gm["teams"]["away"], gm["teams"]["home"]
                games.setdefault(a["team"]["name"], []).append((dt["date"], a.get("score", 0), h.get("score", 0)))
                games.setdefault(h["team"]["name"], []).append((dt["date"], h.get("score", 0), a.get("score", 0)))
        for name, v in games.items():
            if name in rows:
                v = sorted(v)[-15:]
                rows[name]["l15_rf"] = st.mean(x[1] for x in v); rows[name]["l15_ra"] = st.mean(x[2] for x in v)
        return rows
    return cached("teams_%s" % datetime.date.today(), build)


def rank(T, team, key, high_first=True):
    vals = sorted([r[key] for r in T.values() if r.get(key) is not None], reverse=high_first)
    return vals.index(T[team][key]) + 1 if T[team].get(key) is not None else 0


def find_team(T, q):
    q = P.norm(q)
    h = [n for n in T if q in P.norm(n) or P.norm(n).endswith(q)]
    return h[0] if h else None


def card(a, b, sp_hand=None):
    T = team_table()
    A, B = find_team(T, a), find_team(T, b)
    rows = [("runs / game", "runs_pg", True), ("OPS", "ops", True), ("OPS vs LHP", "ops_vl", True), ("OPS vs RHP", "ops_vr", True),
            ("strikeout %", "k_pct", True), ("walk %", "bb_pct", True), ("HR / game", "hr_pg", True), ("runs last 15", "l15_rf", True),
            ("-- PITCHING --", None, None), ("runs allowed / game", "ra_pg", False), ("starters ERA", "sp_era", False),
            ("bullpen ERA", "rp_era", False), ("bullpen WHIP", "rp_whip", False), ("pitching K %", "k_pct_p", True),
            ("OPS allowed", "ops_allowed", False), ("runs allowed last 15", "l15_ra", False)]
    print("\nMATCHUP  %s vs %s   (%d season; rank of 30 -- #1 = best at it)" % (A, B, SEASON))
    for lbl, k, hi in rows:
        if k is None:
            print("  " + lbl); continue
        fa = lambda t: ("%.3f" % T[t][k] if T[t][k] < 1.5 else "%.2f" % T[t][k]) if T[t].get(k) is not None else "-"
        print("  %-22s %-9s (#%2d)    %-9s (#%2d)" % (lbl, fa(A), rank(T, A, k, hi), fa(B), rank(T, B, k, hi)))
    return A, B


# ------------------------------------------------------------------ PROFILES
def person(name):
    p = jget("/people/search", names=name, sportIds=1).get("people") or []
    return p[0] if p else None


def game_log(pid, group, season=SEASON):
    return cached("gl_%s_%s_%s_%s" % (pid, group, season, datetime.date.today()),
                  lambda: [dict(x["stat"], date=x["date"], opp=x["opponent"]["name"], home=x.get("isHome"))
                           for x in (jget("/people/%d/stats" % pid, stats="gameLog", group=group, season=season)["stats"] or [{}])[0].get("splits", [])])


def post_career(pid, group):
    d = jget("/people/%d/stats" % pid, stats="career", group=group, gameType="P")
    sp = [x["stat"] for s in d.get("stats", []) for x in s.get("splits", [])]
    return sp[0] if sp else None


def profile(name, vs_pitcher=None, quiet=False):
    p = person(name)
    if not p:
        print("no player", name); return None
    pitcher = p.get("primaryPosition", {}).get("abbreviation") == "P"
    if pitcher:
        G = [g for g in game_log(p["id"], "pitching") if g.get("gamesStarted")]
        if not G:
            print("no starts"); return None
        outs = [g["outs"] for g in G]; ks = [g["strikeOuts"] for g in G]; er = [g["earnedRuns"] for g in G]
        pc = [g.get("numberOfPitches") or 0 for g in G]
        out = dict(name=p["fullName"], role="SP", throws=p.get("pitchHand", {}).get("code"), starts=len(G), last=G[-1]["date"],
                   outs=(round(st.mean(outs), 1), round(st.mean(outs[-5:]), 1)), k=(round(st.mean(ks), 1), round(st.mean(ks[-5:]), 1)),
                   er=(round(st.mean(er), 2), round(st.mean(er[-5:]), 2)), pitches=round(st.mean(pc[-5:])),
                   short_rate=round(100 * sum(o < 15 for o in outs) / len(outs)),
                   home=round(st.mean([g["outs"] for g in G if g["home"]] or [0]), 1), away=round(st.mean([g["outs"] for g in G if not g["home"]] or [0]), 1),
                   post=post_career(p["id"], "pitching"))
        if not quiet:
            print("\n%s (SP, throws %s) | %d starts, last %s | pitches last 5: %d | starts under 15 outs: %d%%" % (
                out["name"], out["throws"], out["starts"], out["last"], out["pitches"], out["short_rate"]))
            print("  outs  season %.1f / last 5 %.1f | K  %.1f / %.1f | ER  %.2f / %.2f | outs home %.1f away %.1f" % (
                out["outs"][0], out["outs"][1], out["k"][0], out["k"][1], out["er"][0], out["er"][1], out["home"], out["away"]))
            if out["post"]:
                s = out["post"]; print("  POSTSEASON career: %s GS, %s IP, ERA %s, %s K" % (s.get("gamesStarted"), s.get("inningsPitched"), s.get("era"), s.get("strikeOuts")))
            last = {}
            for g in G:
                last.setdefault(g["opp"], []).append("%s:%do/%dK/%dER" % (g["date"][5:], g["outs"], g["strikeOuts"], g["earnedRuns"]))
            print("  vs teams this season: " + " | ".join("%s %s" % (k.split()[-1], " ".join(v[-3:])) for k, v in list(last.items())[-8:]))
        return out
    G = [g for g in game_log(p["id"], "hitting") if (g.get("plateAppearances") or 0) >= 3]
    if not G:
        print("no games"); return None
    hrr = lambda g: g["hits"] + g["runs"] + g["rbi"]
    spl = {s["split"]["code"]: s["stat"] for s in (jget("/people/%d/stats" % p["id"], stats="statSplits", group="hitting", season=SEASON, sitCodes="vl,vr")["stats"] or [{}])[0].get("splits", [])}
    out = dict(name=p["fullName"], role="H", bats=p.get("batSide", {}).get("code"), games=len(G), last=G[-1]["date"],
               hit_rate=round(100 * sum(g["hits"] > 0 for g in G) / len(G)), hit_rate_l15=round(100 * sum(g["hits"] > 0 for g in G[-15:]) / min(15, len(G))),
               hrr=round(st.mean(hrr(g) for g in G), 2), tb=round(st.mean(g["totalBases"] for g in G), 2), k=round(st.mean(g["strikeOuts"] for g in G), 2),
               vs_l=(spl.get("vl") or {}).get("ops"), vs_r=(spl.get("vr") or {}).get("ops"),
               home_hit=round(100 * st.mean([g["hits"] > 0 for g in G if g["home"]] or [0])), away_hit=round(100 * st.mean([g["hits"] > 0 for g in G if not g["home"]] or [0])),
               post=post_career(p["id"], "hitting"))
    if vs_pitcher:
        q = person(vs_pitcher)
        if q:
            v = jget("/people/%d/stats" % p["id"], stats="vsPlayer", opposingPlayerId=q["id"], group="hitting")
            tot = [x["stat"] for b in v.get("stats", []) if (b.get("type") or {}).get("displayName") == "vsPlayerTotal" for x in b.get("splits", [])]
            out["vs_sp"] = "%s-for-%s" % (tot[0].get("hits"), tot[0].get("atBats")) if tot else "never faced"
    if not quiet:
        print("\n%s (bats %s) | %d games (3+ PA), last %s" % (out["name"], out["bats"], out["games"], out["last"]))
        print("  games with a hit: season %d%% / last 15 %d%% | home %d%% away %d%%" % (out["hit_rate"], out["hit_rate_l15"], out["home_hit"], out["away_hit"]))
        print("  per game: H+R+RBI %.2f | total bases %.2f | strikeouts %.2f | OPS vs LHP %s, vs RHP %s" % (out["hrr"], out["tb"], out["k"], out["vs_l"], out["vs_r"]))
        if out.get("vs_sp"):
            print("  vs today's starter (career): %s" % out["vs_sp"])
        if out["post"]:
            s = out["post"]; print("  POSTSEASON career: %s PA, AVG %s, OPS %s, %s HR" % (s.get("plateAppearances"), s.get("avg"), s.get("ops"), s.get("homeRuns")))
    return out


# ------------------------------------------------------------------ SCREEN
MAP = {"hits": ("H", "hits"), "hitsrunsrbis": ("H", "hrr"), "hitsrunsrbi": ("H", "hrr"), "totalbases": ("H", "totalBases"),
       "hitterstrikeouts": ("H", "strikeOuts"), "batterstrikeouts": ("H", "strikeOuts"),
       "pitcherstrikeouts": ("P", "strikeOuts"), "strikeouts": ("P", "strikeOuts"), "pitchingouts": ("P", "outs"),
       "pitchingoutsrecorded": ("P", "outs"), "pitcherearnedrunsallowed": ("P", "earnedRuns"), "earnedrunsallowed": ("P", "earnedRuns")}


def screen(day):
    T = team_table()
    lg_ops = st.mean(r["ops"] for r in T.values()); lg_k = st.mean(r["k_pct"] for r in T.values())
    sch = jget("/schedule", sportId=1, date=day, hydrate="probablePitcher,team")
    games = {}
    for dt in sch.get("dates", []):
        for gm in dt["games"]:
            post = gm.get("gameType") in ("F", "D", "L", "W")
            a, h = gm["teams"]["away"], gm["teams"]["home"]
            for me, op in ((a, h), (h, a)):
                games[me["team"]["name"]] = dict(opp=op["team"]["name"], sp=(op.get("probablePitcher") or {}).get("fullName"),
                                                 my_sp=(me.get("probablePitcher") or {}).get("fullName"), post=post, start=gm["gameDate"], home=me is h)
    print("MLB %s: %d games%s" % (day, len(games) // 2, " (POSTSEASON)" if any(g["post"] for g in games.values()) else ""))
    legs = []
    try:
        legs += P.underdog("MLB")
    except Exception as e:
        print("  underdog failed (unknown, not absent):", e)
    try:
        legs += [l for l in P.prizepicks(2) if l.get("kind") == "standard"]
    except Exception as e:
        print("  prizepicks failed (unknown, not absent):", e)
    legs = [l for l in legs if P.norm(l["stat"]) in MAP]
    print("  %d MLB lines" % len(legs))
    people = {}
    import _news as N
    _lu = {}

    def lineup(team):                                             # posted lineup, cached per team (user 2026-09-30: news on every lookup)
        if team not in _lu:
            try:
                _lu[team] = N.mlb_lineup(team, day)
            except Exception:
                _lu[team] = (False, {})
        return _lu[team]

    def work(l):
        kind, field = MAP[P.norm(l["stat"])]
        pp = people.get(l["player"]) or person(l["player"])
        people[l["player"]] = pp
        if not pp:
            return None
        team = (pp.get("currentTeam") or {}).get("name") or ""
        if not team:
            pp2 = jget("/people/%d" % pp["id"], hydrate="currentTeam")["people"][0]; team = (pp2.get("currentTeam") or {}).get("name", "")
        gm = games.get(team)
        if not gm:
            return None
        news, spot = N.flags("mlb", team, pp["fullName"], day), None
        if any(x.startswith("OUT") for x in news):
            return None
        if kind == "H":
            posted, L = lineup(team)
            if posted:
                spot = L.get(pp["fullName"])
                if spot is None:
                    return None                                   # lineup is out and he isn't in it -> no bet
            news = news + (["LINEUP #%d" % spot] if spot else ["lineup not posted"])
        if kind == "H":
            # every game he batted 2+ times: dropping the short nights (3+ PA only) faked an over lean (2026-09-30)
            G = [g for g in game_log(pp["id"], "hitting") if (g.get("plateAppearances") or 0) >= 2]
            if len(G) < 20:
                return None
            val = (lambda g: g["hits"] + g["runs"] + g["rbi"]) if field == "hrr" else (lambda g: g[field])
            vals = [val(g) for g in G][-60:]
            mu = st.mean(vals)
            opp = T.get(gm["opp"]) or {}
            if field == "strikeOuts":
                f = 1 + ((opp.get("k_pct_p") or lg_k) / lg_k - 1) * 0.5
            else:
                f = 1 + ((opp.get("ops_allowed") or lg_ops) / lg_ops - 1) * 0.5
                if gm["post"]:
                    f *= 0.93                                     # measured playoff haircut on hitter overs
            mu *= f
        else:
            G = [g for g in game_log(pp["id"], "pitching") if g.get("gamesStarted")]
            if len(G) < 5 or pp["fullName"] != gm.get("my_sp"):
                return None
            vals = [g[field] for g in G][-15:]
            mu = st.mean(vals)
            opp = T.get(gm["opp"]) or {}
            if field == "outs" and gm["post"]:
                mu -= 1.9 if st.mean(g["outs"] for g in G) >= 18 else 2.9
            elif field == "strikeOuts":
                mu *= 1 + ((opp.get("k_pct") or lg_k) / lg_k - 1) * 0.5
                if gm["post"]:
                    mu *= 1 - (2.6 / max(10, st.mean(g["outs"] for g in G)))   # fewer outs -> fewer K
            elif field == "earnedRuns":
                mu *= 1 + ((opp.get("ops") or lg_ops) / lg_ops - 1) * 0.5
        sd = max(st.pstdev(vals), 0.5)
        if kind == "H" or field in ("strikeOuts", "earnedRuns"):
            # small counts: the call is on the PROBABILITY of clearing the line (Poisson at the adjusted mean blended with
            # the adjusted empirical rate), expressed as a z so TAKE >= 69%, LEAN >= 60%, TOO CLOSE 40-60%
            lam = max(mu, 0.02); k = int(math.floor(l["line"]))
            pois = 1 - sum(math.exp(-lam) * lam ** j / math.factorial(j) for j in range(k + 1))
            base = st.mean(vals) if st.mean(vals) > 0 else 1e-9
            emp = sum(v * (mu / base) > l["line"] for v in vals) / len(vals)
            p_over = min(0.97, max(0.03, P.shrink((0.5 * pois + 0.5 * emp) * len(vals), len(vals))))
            gap = round(st.NormalDist().inv_cdf(p_over), 2)
            call = "TAKE OVER" if gap >= 0.5 else "TAKE UNDER" if gap <= -0.5 else "TOO CLOSE" if abs(gap) < 0.25 else                    ("LEAN OVER" if gap > 0 else "LEAN UNDER")
        else:
            call, gap = P.projection_call(mu, sd, l["line"], allow_alt=False)
            p_over = 0.5 * math.erfc(((l["line"] - mu) / sd) / math.sqrt(2))
        return dict(sport="MLB", date=day, player=pp["fullName"], team=team, opp=gm["opp"], vs_sp=gm["sp"] if kind == "H" else None,
                    stat=l["stat"], field=field, line=l["line"], venue=l["venue"], kind=l.get("kind"), mult=l.get("mult"),
                    proj=round(mu, 2), sd=round(sd, 2), p_over=round(p_over, 3), call=call, gap=gap, post=gm["post"], start=gm["start"], spot=spot, flags=news)

    with ThreadPoolExecutor(6) as ex:
        R = [r for r in ex.map(work, legs) if r]
    try:
        import _calls
        seen = {}
        for r in R:
            seen.setdefault((r["player"], r["stat"], r["line"]), r)
        _calls.log(list(seen.values()))
        sides = []
        for r in R:
            for sd, pr in (("over", r["p_over"]), ("under", 1 - r["p_over"])):
                m = (r.get("mult") or {}).get(sd) if r["venue"] == "UD" else 1.0
                if r["venue"] == "UD" and m is None:
                    continue                                   # side not offered
                sides.append(dict(r, side=sd, p=pr, mult=m))
        _calls.legs_dump("MLB", day, sides)
    except Exception as e:
        print("  call log failed:", e)
    R.sort(key=lambda r: -abs(r["gap"]))
    print("\n%-22s %-16s %-16s %5s %-3s %6s %6s  %s" % ("player", "vs", "stat", "line", "app", "proj", "gap", "call"))
    for r in R:
        if r["call"].startswith(("TAKE", "LEAN")):
            print("%-22s %-16s %-16s %5s %-3s %6s %+6.2f  %s" % (r["player"][:22], (r["vs_sp"] or r["opp"] or "")[:16], r["stat"][:16], r["line"],
                                                              r["venue"], r["proj"], r["gap"], r["call"]) + ("  | " + ", ".join(r["flags"]) if r.get("flags") else ""))
    print("\n%d lines screened: %s" % (len(R), dict(__import__("collections").Counter(r["call"].split(" ")[0] + " " + (r["call"].split(" ")[1] if " " in r["call"] else "") for r in R))))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "card":
        card(a[1], a[2])
    elif a[0] == "profile":
        profile(" ".join(a[1:]).split(" --vs ")[0], vs_pitcher=(" ".join(a[1:]).split(" --vs ")[1] if " --vs " in " ".join(a[1:]) else None))
    else:
        screen(a[1] if len(a) > 1 else datetime.datetime.now(CT).strftime("%Y-%m-%d"))
