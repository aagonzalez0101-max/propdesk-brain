"""THE PROP ENGINE -- one pipeline, one adapter per sport (built 2026-09-29, night of mission day one).

    python _props.py nhl [YYYY-MM-DD]      # screen tomorrow's/today's NHL props, log passing legs to paper
    python _props.py soccer [YYYY-MM-DD]   # PrizePicks soccer props vs our shots/goals model (paper only)
    python _props.py grade                 # settle every pending leg in props_paper.jsonl from box scores

Every leg runs the same gates (the bet-selection bar, made mechanical):
  1. VALUE     -- Pinnacle de-vig at the SAME line (NHL). Soccer has no sharp prop price anywhere free, so it
                  uses our model and stays PAPER until its record earns it.
  2. ROLE      -- current role only: skaters' games at >= 85% of their last-10 TOI; goalies' full starts.
  3. H2H       -- vs tonight's opponent, CURRENT ROLE ONLY (the Boston lesson, 2026-09-29). Fewer than 3 = no H2H.
  4. AGREE     -- all three on the same side, or it is not a leg in either direction.
Output: the PASS list, a balance line (over/under share -- cap is 60%), and paper rows in props_paper.jsonl.
"""
import sys, json, re, math, datetime, collections, urllib.request, urllib.parse
import numpy as np
from concurrent.futures import ThreadPoolExecutor

PIN_KEY = "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124", "Accept": "application/json"}
PH = dict(UA, **{"X-API-Key": PIN_KEY})
CT = datetime.timezone(datetime.timedelta(hours=-5))
OUT = "props_paper.jsonl"
norm = lambda s: re.sub(r"[^a-z0-9]", "", __import__("unicodedata").normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())   # 10/21: accents (Dončić) broke matching
dec = lambda o: 1 + (o / 100 if o > 0 else 100 / -o)
imp = lambda o: 1 / dec(o)
UD2_BE = 1 / 3.5 ** 0.5          # 53.5% per leg, Underdog 2-pick 3.5x (confirmed)
PP2_BE = 1 / 3.0 ** 0.5          # 57.7% per leg, PrizePicks 2-pick power 3x


def get(url, h=UA, timeout=40):
    import time as _t
    for k in range(4):                     # 10/2: NHL search reset connections under 8 parallel threads -> back off and retry
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout).read())
        except (ConnectionError, urllib.error.URLError, TimeoutError) as e:
            if k == 3 or getattr(e, "code", None) in (400, 401, 403, 404):
                raise
            _t.sleep(2 * (k + 1))


def archive(tag, payload):
    """Keep every raw board we pull (2026-09-30): prop backtests had to use stand-in lines because no history of
    real PP/UD lines existed. lines_archive/<date>/<tag>_<HHMMSS>.json -- the real-line backtest set, from today."""
    import os
    if tag == "ud_all":
        return                          # 10/9: Underdog closed 10/5 -- its 36 MB board x ~68/day was 2.4 GB/day of archive
    try:
        now = datetime.datetime.now(CT)
        d = os.path.join("lines_archive", now.strftime("%Y-%m-%d"))
        os.makedirs(d, exist_ok=True)
        json.dump(payload, open(os.path.join(d, "%s_%s.json" % (tag, now.strftime("%H%M%S"))), "w", encoding="utf-8"))
    except Exception:
        pass


def projection_call(mu, sd, line, goblin=None, demon=None, allow_alt=True):
    """User's read (2026-09-30): projection vs line in the player's own SDs -> plain call."""
    sd = max(sd or 0, 0.5)
    gap = (mu - line) / sd
    if gap >= 0.5:
        c = "TAKE OVER"
    elif gap <= -0.5:
        c = "TAKE UNDER"
    elif abs(gap) < 0.25:
        c = "TOO CLOSE"
    else:
        c = "LEAN OVER" if gap > 0 else "LEAN UNDER"
    if allow_alt:
        if c in ("TOO CLOSE", "LEAN OVER", "LEAN UNDER") and goblin is not None and (mu - goblin) / sd >= 0.75:
            c += " -> GOBLIN %s" % goblin
        if demon is not None and (mu - demon) / sd >= 0.25:
            c += " | DEMON %s live" % demon
    return c, round(gap, 2)


def shrink(hits, n, prior=0.5, k=10):
    return (hits + prior * k) / (n + k)


# ------------------------------------------------------------------ shared: pick'em boards
def underdog(sport):
    d = get("https://api.underdogfantasy.com/v1/over_under_lines")
    archive("ud_all", d)
    G = {x["id"]: x for x in d.get("games", [])}
    A = {a["id"]: a for a in d["appearances"]}
    P = {p["id"]: p for p in d["players"]}
    out = []
    for l in d["over_under_lines"]:
        ap = (l.get("over_under") or {}).get("appearance_stat") or {}
        a = A.get(ap.get("appearance_id")) or {}
        gm = G.get(a.get("match_id")) or {}
        if gm.get("sport_id") != sport:
            continue
        pl = P.get(a.get("player_id")) or {}
        sides = {}
        for o in l.get("options", []):
            sides["under" if o.get("choice") == "lower" else "over"] = float(o.get("payout_multiplier") or 1)
        out.append(dict(player=("%s %s" % (pl.get("first_name") or "", pl.get("last_name") or "")).strip(),
                        stat=ap.get("display_stat"), line=float(l["stat_value"]), mult=sides,
                        game=gm.get("title"), start=gm.get("scheduled_at"), venue="UD"))
    return out


def prizepicks(league_id, max_age=600):
    # cached for 10 min: repeated screens were tripping PrizePicks' 429 rate limit (2026-09-29)
    import os, time
    cf = "_pp_cache_%d.json" % league_id
    if os.path.exists(cf) and time.time() - os.path.getmtime(cf) < max_age:
        d = json.load(open(cf, encoding="utf-8"))
    else:
        d = get("https://partner-api.prizepicks.com/projections?per_page=1000&league_id=%d" % league_id)
        json.dump(d, open(cf, "w", encoding="utf-8"))
        archive("pp_%d" % league_id, d)
    inc = {(x["type"], x["id"]): x for x in d.get("included", [])}
    out = []
    for x in d["data"]:
        a = x["attributes"]
        pl = inc.get(("new_player", x["relationships"]["new_player"]["data"]["id"]), {}).get("attributes", {})
        if a.get("odds_type") not in ("standard", "goblin", "demon"):
            continue
        out.append(dict(player=pl.get("name"), team=pl.get("team"), stat=a.get("stat_type"), line=float(a["line_score"]),
                        kind=a.get("odds_type"), opp=a.get("description"), start=a.get("start_time"), venue="PP",
                        league=pl.get("league"), img=pl.get("image_url")))
    return out


# ------------------------------------------------------------------ shared: Pinnacle player specials
def pinnacle_props(league):
    M = get("https://guest.api.arcadia.pinnacle.com/0.1/leagues/%d/matchups" % league, PH)
    K = get("https://guest.api.arcadia.pinnacle.com/0.1/leagues/%d/markets/straight" % league, PH)
    sp = {m["id"]: m for m in M if m.get("type") == "special" and (m.get("special") or {}).get("category") == "Player Props"}
    out = {}
    for k in K:
        m = sp.get(k["matchupId"])
        if not m or k.get("type") != "total":
            continue
        names = {p["id"]: p["name"] for p in m["participants"]}
        pr = {names.get(p.get("participantId")): (p.get("points"), p["price"]) for p in k["prices"]}
        if "Over" not in pr or "Under" not in pr:
            continue
        desc = m["special"]["description"]
        mm = re.match(r"(.+?) Total (.+)$", desc)
        if not mm:
            continue
        o, u = imp(pr["Over"][1]), imp(pr["Under"][1])
        out[(norm(mm.group(1)), mm.group(2).lower(), float(pr["Over"][0]))] = o / (o + u)
    return out


# ------------------------------------------------------------------ NHL adapter
NHL_STAT = {  # pick'em / Pinnacle stat name -> (log field, pinnacle stat name)
    "shots on goal": ("shots", "shots on goal"), "shots": ("shots", "shots on goal"),
    "points": ("points", "points"), "goals": ("goals", "goals"), "assists": ("assists", "assists"),
    "saves": ("saves", "saves"), "goalie saves": ("saves", "saves"), "goaltender saves": ("saves", "saves"),
}


def toi_min(s):
    try:
        m, sec = s.split(":")
        return int(m) + int(sec) / 60
    except Exception:
        return 0.0


_nhl_ids = {}


_NHL_IDS_F = "_nhl_ids.json"
try:
    _nhl_ids.update(json.load(open(_NHL_IDS_F, encoding="utf-8")))
except Exception:
    pass


def nhl_player(name):
    if name in _nhl_ids:
        return _nhl_ids[name]
    q = urllib.parse.quote(name)
    r = get("https://search.d3.nhle.com/api/v1/search/player?culture=en-us&limit=5&q=%s&active=true" % q)
    hit = next((p for p in r if norm(p["name"]) == norm(name)), r[0] if r else None)
    _nhl_ids[name] = hit
    try:
        json.dump(_nhl_ids, open(_NHL_IDS_F, "w", encoding="utf-8"))   # disk cache: one search per player, ever
    except Exception:
        pass
    return hit


def nhl_logs(pid, goalie):
    rows = []
    for season in ("20252026", "20262027"):
        try:
            gl = get("https://api-web.nhle.com/v1/player/%s/game-log/%s/2" % (pid, season)).get("gameLog", [])
        except Exception:
            gl = []
        for g in gl:
            r = dict(date=g["gameDate"], opp=g.get("opponentAbbrev"), toi=toi_min(g.get("toi", "0:00")))
            if goalie:
                r["saves"] = (g.get("shotsAgainst") or 0) - (g.get("goalsAgainst") or 0)
            else:
                for f in ("shots", "points", "goals", "assists"):
                    r[f] = g.get(f) or 0
            rows.append(r)
    return sorted(rows, key=lambda r: r["date"])


def nhl_opponents(day):
    """team abbrev -> (opponent abbrev, start UTC) for games on `day` (CT date)."""
    s = get("https://api-web.nhle.com/v1/schedule/%s" % day)
    opp = {}
    for d in s.get("gameWeek", []):
        for g in d["games"]:
            st = datetime.datetime.fromisoformat(g["startTimeUTC"].replace("Z", "+00:00"))
            if st.astimezone(CT).strftime("%Y-%m-%d") != day:
                continue
            a, h = g["awayTeam"]["abbrev"], g["homeTeam"]["abbrev"]
            opp[a] = (h, g["startTimeUTC"]); opp[h] = (a, g["startTimeUTC"])
    return opp


def nhl_team_rates():
    """abbrev -> per-game shots for/against, goals for/against. The new season is blended in as games accrue:
    current weight = gp/(gp+10), the rest is last season (one call each to the free stats API)."""
    teams = {t["id"]: t["triCode"] for t in get("https://api.nhle.com/stats/rest/en/team")["data"]}
    def season(sid):
        d = get("https://api.nhle.com/stats/rest/en/team/summary?cayenneExp=seasonId=%s%%20and%%20gameTypeId=2" % sid)["data"]
        return {teams.get(r["teamId"]): r for r in d}
    last, cur = season("20252026"), season("20262027")
    out = {}
    for ab, r in last.items():
        c = cur.get(ab) or {}
        w = (c.get("gamesPlayed") or 0) / ((c.get("gamesPlayed") or 0) + 10.0)
        out[ab] = {k: (1 - w) * r[k] + w * (c.get(k) or r[k])
                   for k in ("shotsForPerGame", "shotsAgainstPerGame", "goalsForPerGame", "goalsAgainstPerGame",
                             "powerPlayPct", "penaltyKillPct")}
    avg = {k: sum(v[k] for v in out.values()) / len(out) for k in next(iter(out.values()))}
    return out, avg


def nhl_starters():
    """Daily Faceoff starting goalies: team abbrev-ish name -> (goalie, 'Confirmed'|'Likely'|'Unconfirmed'|None)."""
    h = urllib.request.urlopen(urllib.request.Request("https://www.dailyfaceoff.com/starting-goalies/", headers=UA),
                               timeout=30).read().decode("utf-8", "ignore")
    nd = json.loads(re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', h).group(1))
    out = {}
    for g in nd["props"]["pageProps"].get("data", []):
        for side in ("home", "away"):
            out[norm(g.get(side + "TeamName"))] = (g.get(side + "GoalieName"), g.get(side + "NewsStrengthName"))
    return out


def nhl_played_yesterday(day):
    y = (datetime.date.fromisoformat(day) - datetime.timedelta(days=1)).isoformat()
    s = get("https://api-web.nhle.com/v1/schedule/%s" % y)
    teams = set()
    for d in s.get("gameWeek", []):
        for g in d["games"]:
            st = datetime.datetime.fromisoformat(g["startTimeUTC"].replace("Z", "+00:00")).astimezone(CT).strftime("%Y-%m-%d")
            if st == y:
                teams |= {g["awayTeam"]["abbrev"], g["homeTeam"]["abbrev"]}
    return teams


def nhl_implied_goals():
    """Pinnacle NHL moneyline + total -> each team's implied goals (Poisson-free split: total x win-prob share,
    pulled halfway to an even split). Used for direction only."""
    M = get("https://guest.api.arcadia.pinnacle.com/0.1/leagues/1456/matchups", PH)
    K = get("https://guest.api.arcadia.pinnacle.com/0.1/leagues/1456/markets/straight", PH)
    mk = {}
    for k in K:
        if k.get("period") == 0 and not k.get("isAlternate"):
            mk.setdefault(k["matchupId"], {})[k["type"]] = k
    out = {}
    for m in M:
        if m.get("type") != "matchup" or m.get("parent"):
            continue
        x = mk.get(m["id"], {})
        if "moneyline" not in x or "total" not in x:
            continue
        pr = {p["designation"]: imp(p["price"]) for p in x["moneyline"]["prices"]}
        s = sum(pr.values()); tot = x["total"]["prices"][0].get("points")
        names = {p["alignment"]: p["name"] for p in m["participants"]}
        for side in ("home", "away"):
            share = 0.5 + (pr[side] / s - 0.5) * 0.5
            out[norm(names[side])] = round(tot * share, 2)
    return out


def team_key(ab, full_names):
    """abbrev -> normalized full team name via the NHL stats team list (for Daily Faceoff / Pinnacle lookups)."""
    return full_names.get(ab, "")


def screen_nhl(day):
    opp = nhl_opponents(day)
    try:
        RATES, AVG = nhl_team_rates()
    except Exception as e:
        print("  team rates failed: %s -- no opponent adjustment" % e); RATES, AVG = {}, {}
    try:
        FULL = {t["triCode"]: norm(t["fullName"]) for t in get("https://api.nhle.com/stats/rest/en/team")["data"]}
    except Exception:
        FULL = {}
    try:
        START = nhl_starters()
    except Exception as e:
        print("  daily faceoff failed: %s -- goalie legs will be skipped" % e); START = None
    try:
        B2B = nhl_played_yesterday(day)
    except Exception:
        B2B = set()
    try:
        IMPL = nhl_implied_goals()
    except Exception:
        IMPL = {}
    print("NHL %s: %d games (%s)" % (day, len(opp) // 2, ", ".join(sorted({"%s-%s" % tuple(sorted((k, v[0]))) for k, v in opp.items()}))))
    if not opp:
        return []
    legs = []
    try:
        legs += [l for l in underdog("NHL")]
    except Exception as e:
        print("  underdog failed: %s (unknown, NOT absent)" % e)
    try:
        legs += [l for l in prizepicks(8)]
    except Exception as e:
        print("  prizepicks failed: %s (unknown, NOT absent)" % e)
    try:
        pin = pinnacle_props(1456)
    except Exception as e:
        print("  pinnacle failed: %s" % e); pin = {}
    print("  %d pick'em lines, %d Pinnacle player lines" % (len(legs), len(pin)))
    ALT = {}
    for l in legs:
        if l["venue"] == "PP" and l.get("kind") in ("goblin", "demon"):
            ALT.setdefault((norm(l["player"]), (l["stat"] or "").lower()), {})[l["kind"]] = l["line"]
    legs = [l for l in legs if (l["stat"] or "").lower() in NHL_STAT and l.get("kind") != "demon"]

    def work(l):
        p = nhl_player(l["player"])
        if not p or p.get("teamAbbrev") not in opp:
            return None
        goalie = p.get("positionCode") == "G"
        field, pstat = NHL_STAT[l["stat"].lower()]
        if (field == "saves") != goalie:
            return None
        L = nhl_logs(p["playerId"], goalie)
        if len(L) < 15:
            return None
        if goalie:
            role = [r for r in L if r["toi"] >= 50]
        else:
            ref = sum(r["toi"] for r in L[-10:]) / min(10, len(L))
            role = [r for r in L if r["toi"] >= 0.85 * ref]
        if len(role) < 12:
            return None
        o_ab, start = opp[p["teamAbbrev"]]
        lo, hi = (0.85 * ref, 1.25 * ref) if not goalie else (50, 99)
        h2h = [r for r in role if r["opp"] == o_ab and lo <= r["toi"] <= hi]
        flags = []
        # GOALIE GATE: a saves prop is only real if he is tonight's starter
        if goalie:
            st = (START or {}).get(FULL.get(p["teamAbbrev"], ""))
            if START is None or not st or norm(st[0]) != norm(l["player"]):
                return None
            if st[1] != "Confirmed":
                flags.append("STARTER %s" % (st[1] or "UNCONFIRMED").upper())
        if p["teamAbbrev"] in B2B:
            flags.append("BACK-TO-BACK")
        # OPPONENT: scale the player's role games by what tonight's opponent allows (or generates, for saves)
        key = {"shots": "shotsAgainstPerGame", "points": "goalsAgainstPerGame", "goals": "goalsAgainstPerGame",
               "assists": "goalsAgainstPerGame", "saves": "shotsForPerGame"}[field]
        f = 1.0
        if RATES.get(o_ab) and AVG.get(key):
            f = 1 + (RATES[o_ab][key] / AVG[key] - 1) * 0.5      # half weight: team rates regress
        mu = sum(r[field] for r in role) / len(role) * f
        if goalie and RATES.get(o_ab) and RATES.get(p["teamAbbrev"]):
            # BACKTESTED saves model (_nhl_bt.py, fit 2024-25, held on 2025-26 under 3 line proxies):
            # log(saves+1) - log(base+1) = 0.4286 ln(opp shots-for/avg) - 0.1072 ln(own shots-against/avg) - 0.0504
            base = sum(r["saves"] for r in role[-20:]) / len(role[-20:])
            mu = math.exp(math.log(base + 1) + 0.4286 * math.log(RATES[o_ab]["shotsForPerGame"] / AVG["shotsForPerGame"])
                          - 0.1072 * math.log(RATES[p["teamAbbrev"]]["shotsAgainstPerGame"] / AVG["shotsAgainstPerGame"]) - 0.0504) - 1
        # MATCHUP CARD (user 2026-09-30): both teams' offense AND defense with league ranks, on every leg
        def _rk(team, k):
            vals = sorted([v[k] for v in RATES.values()], reverse=True)
            return vals.index(RATES[team][k]) + 1 if team in RATES else 0
        card = ""
        if RATES.get(p["teamAbbrev"]) and RATES.get(o_ab):
            t, o = p["teamAbbrev"], o_ab
            card = "%s SF#%d SA#%d PP#%d | %s SF#%d SA#%d PK#%d" % (
                t, _rk(t, "shotsForPerGame"), _rk(t, "shotsAgainstPerGame"), _rk(t, "powerPlayPct"),
                o, _rk(o, "shotsForPerGame"), _rk(o, "shotsAgainstPerGame"), _rk(o, "penaltyKillPct"))
        # GAME SCRIPT: Pinnacle's implied goals for his team (skater scoring props only, direction only)
        ig = IMPL.get(FULL.get(p["teamAbbrev"], ""))
        res = []
        for side in ("over", "under"):
            if l["venue"] == "PP" and l.get("kind") in ("goblin", "demon"):
                continue                      # main lines only (user 10/2): goblins inflated the record
            if l["venue"] == "UD" and side not in l["mult"]:
                continue                      # UD posts some lines one-sided (NHL goals 0.5 = over only) -- unbettable
            hit = (lambda v: v > l["line"]) if side == "over" else (lambda v: v < l["line"])
            if goalie:                          # saves: normal, sd = sqrt(1.4 mu), as in the backtest
                pn = 0.5 * math.erfc((l["line"] - mu) / (math.sqrt(1.4 * max(mu, 1)) * math.sqrt(2)))
                pn = pn if side == "over" else 1 - pn
            emp = sum(hit(r[field] * f) for r in role) / len(role)
            # counts are small: blend a Poisson at the opponent-adjusted mean with the scaled empirical rate
            Lf = l["line"]
            cdf = sum(math.exp(-mu) * mu ** k / math.factorial(k) for k in range(int(math.floor(Lf)) + 1))
            pk = math.exp(-mu) * mu ** int(Lf) / math.factorial(int(Lf)) if float(Lf).is_integer() else 0
            pois = (1 - cdf) if side == "over" else (cdf - pk)
            rr = pn if goalie else shrink((0.5 * emp + 0.5 * pois) * len(role), len(role))
            sflags = list(flags)
            if ig is not None and field in ("points", "goals", "assists"):
                if side == "over" and ig <= 2.5:
                    sflags.append("TEAM IMPLIED %.1f GOALS" % ig)
                if side == "under" and ig >= 3.5:
                    sflags.append("TEAM IMPLIED %.1f GOALS" % ig)
            hh = (sum(hit(r[field]) for r in h2h), len(h2h))
            pf = pin.get((norm(l["player"]), pstat, l["line"]))
            pf = None if pf is None else (pf if side == "over" else 1 - pf)
            mult = l["mult"][side] if l["venue"] == "UD" else 1.0
            be = UD2_BE if l["venue"] == "UD" else PP2_BE
            if l["venue"] == "PP" and l.get("kind") == "goblin":
                be = 0.70                     # goblin 2-pick pays far less -- demand a much higher hit rate
            value = (pf if pf is not None else rr) * mult
            ok_value = pf is not None and value >= be
            # EARLY MODE (user 2026-09-30: "do it ourselves before the sharp books get the intel"): with no Pinnacle
            # price yet, our own model is the price -- saves (backtested, 65-66% top bucket OOS) with a 3pp cushion;
            # other props only on a TAKE call with a 5pp cushion, tagged EARLY and tracked apart until validated.
            early = False
            if pf is None:
                _c, _g = projection_call(mu, float(np.std([r[field] for r in role])) if len(role) > 1 else 1.0, l["line"], allow_alt=False)
                _dir_ok = (_c == "TAKE OVER" and side == "over") or (_c == "TAKE UNDER" and side == "under")
                if goalie and rr * mult >= be + 0.03:
                    early = ok_value = True
                elif not goalie and _dir_ok and rr * mult >= be + 0.05:
                    early = ok_value = True
            ok_role = rr * mult >= be
            ok_h2h = hh[1] >= 3 and hh[0] / hh[1] >= 0.5
            res.append(dict(sport="NHL", date=day, player=l["player"], team=p["teamAbbrev"], opp=o_ab, start=start,
                            stat=l["stat"], field=field, line=l["line"], side=side, venue=l["venue"], kind=l.get("kind"),
                            mult=mult, p_pin=pf, p_role=round(rr, 3), role_n=len(role), h2h="%d/%d" % hh,
                            breakeven=round(be, 3), value=round(value, 3), opp_factor=round(f, 3), adj_mean=round(mu, 2),
                            implied_goals=ig, flags=sflags + (["EARLY (no sharp price yet)"] if early else []), card=card, early=early,
                            call=projection_call(mu, float(np.std([r[field] for r in role])) if len(role) > 1 else 1.0,
                                                 l["line"], (ALT.get((norm(l["player"]), l["stat"].lower())) or {}).get("goblin"),
                                                 (ALT.get((norm(l["player"]), l["stat"].lower())) or {}).get("demon"))[0],
                            passed=bool(ok_value and ok_role and ok_h2h and not any(x.startswith("TEAM IMPLIED") for x in sflags)),
                            why=("" if ok_value else "no sharp price at this line" if pf is None else "price") +
                                ("" if ok_role else " role") + ("" if ok_h2h else " h2h") +
                                (" script" if any(x.startswith("TEAM IMPLIED") for x in sflags) else "")))
        return res

    with ThreadPoolExecutor(8) as ex:
        R = [x for r in ex.map(work, legs) if r for x in r]
    return R


# ------------------------------------------------------------------ SOCCER adapter (model only, no sharp price)
SOC_STAT = {"shots": "totalShots", "shots on target": "shotsOnTarget", "goals": "totalGoals",
            "assists": "goalAssists", "goal + assist": "ga", "fouls": "foulsCommitted"}
ESPN_LEAGUES = ("uefa.champions", "eng.1", "esp.1", "ita.1", "ger.1", "fra.1", "usa.1", "uefa.europa")


def espn_soccer_id(name):
    q = urllib.parse.quote(name)
    try:
        r = get("https://site.web.api.espn.com/apis/search/v2?query=%s&limit=5&type=player" % q)
    except Exception:
        return None
    for blk in r.get("results", []):
        for c in blk.get("contents", []):
            if (c.get("sport") or "") == "soccer" or "soccer" in (c.get("link", {}).get("web") or ""):
                uid = c.get("uid", "")
                m = re.search(r"a:(\d+)", uid)
                if m and norm(c.get("displayName")) == norm(name):
                    return m.group(1)
    return None


def espn_soccer_logs(aid):
    rows = {}
    for season in ("2025", "2026"):
        try:
            d = get("https://site.web.api.espn.com/apis/common/v3/sports/soccer/all/athletes/%s/gamelog?season=%s" % (aid, season))
        except Exception:
            continue
        names = d.get("names") or []
        for st in d.get("seasonTypes", []):
            for cat in st.get("categories", []):
                for e in cat.get("events", []):
                    ev = (d.get("events") or {}).get(e["eventId"], {})
                    try:
                        v = {n: float(x) for n, x in zip(names, e["stats"])}
                    except ValueError:
                        continue
                    v["ga"] = v.get("totalGoals", 0) + v.get("goalAssists", 0)
                    v["date"] = (ev.get("gameDate") or "")[:10]
                    v["opp"] = ((ev.get("opponent") or {}).get("displayName") or "")
                    rows[e["eventId"]] = v
    return sorted(rows.values(), key=lambda r: r["date"])


def screen_soccer(day):
    try:
        B = prizepicks(82)
    except Exception as e:
        print("  prizepicks soccer failed: %s (unknown, NOT absent)" % e); return []
    B = [b for b in B if b.get("kind") == "standard"]   # user 2026-09-29: never soccer goblins
    B = [b for b in B if (b["stat"] or "").lower() in SOC_STAT and b.get("start") and
         datetime.datetime.fromisoformat(b["start"]).astimezone(CT).strftime("%Y-%m-%d") == day]
    print("SOCCER %s: %d PrizePicks standard/goblin lines on the model's stats" % (day, len(B)))

    def work(b):
        aid = espn_soccer_id(b["player"])
        if not aid:
            return None
        L = espn_soccer_logs(aid)
        if len(L) < 10:
            return None
        field = SOC_STAT[b["stat"].lower()]
        recent = L[-20:]                   # current role proxy: ESPN has no minutes, so last 20 appearances
        res = []
        for side in ("over", "under"):
            if b.get("kind") == "goblin" and side == "under":
                continue
            hit = (lambda v: v > b["line"]) if side == "over" else (lambda v: v < b["line"])
            rr = shrink(sum(hit(r.get(field, 0)) for r in recent), len(recent))
            h2h = [r for r in L if norm(r["opp"]) and norm(r["opp"]) in norm(b.get("opp") or "")]
            hh = (sum(hit(r.get(field, 0)) for r in h2h), len(h2h))
            be = 0.70 if b.get("kind") == "goblin" else PP2_BE
            ok_role = rr >= be + 0.03          # no sharp price: demand a cushion over break-even
            ok_h2h = hh[1] < 3 or hh[0] / hh[1] >= 0.5   # soccer H2H is rare; only a real sample can veto
            res.append(dict(sport="SOCCER", date=day, player=b["player"], team=b.get("team"), opp=b.get("opp"),
                            start=b["start"], stat=b["stat"], field=field, line=b["line"], side=side, venue="PP",
                            kind=b.get("kind"), mult=1.0, p_pin=None, p_role=round(rr, 3), role_n=len(recent),
                            h2h="%d/%d" % hh, breakeven=round(be, 3), value=round(rr, 3), espn_id=aid,
                            passed=bool(ok_role and ok_h2h),
                            why=("" if ok_role else "role") + ("" if ok_h2h else " h2h") + " MODEL-ONLY"))
        return res

    with ThreadPoolExecutor(6) as ex:
        R = [x for r in ex.map(work, B) if r for x in r]
    return R


# ------------------------------------------------------------------ report + paper log
def report(R):
    try:
        import _calls
        seen = {}
        for r in R:                      # one call per player/stat/line (the call does not depend on side)
            seen.setdefault((r["player"], r["stat"], r["line"]), r)
        _calls.log([dict(r, proj=r.get("adj_mean")) for r in seen.values() if r.get("call")])
        if R and R[0].get("sport") == "NHL":
            _calls.legs_dump("NHL", R[0]["date"], [dict(r, p=(r["p_pin"] if r.get("p_pin") is not None else r["p_role"])) for r in R])
    except Exception as e:
        print("  call log failed:", e)
    P = sorted([r for r in R if r["passed"]], key=lambda r: -(r["value"] - r["breakeven"]))
    print("\n%-22s %-4s %-16s %-5s %5s %-3s %6s %6s %6s %-6s %s" % ("player", "tm", "stat", "side", "line", "app",
                                                                   "pin", "role", "value", "h2h", "start CT"))
    for r in P[:25]:
        st = datetime.datetime.fromisoformat(r["start"].replace("Z", "+00:00")).astimezone(CT).strftime("%a %H:%M")
        print("%-22s %-4s %-16s %-5s %5s %-3s %6s %5.0f%% %5.0f%% %-6s %s" % (
            r["player"][:22], (r["team"] or "")[:4], r["stat"][:16], r["side"], r["line"], r["venue"],
            "%.0f%%" % (100 * r["p_pin"]) if r["p_pin"] is not None else "-", 100 * r["p_role"], 100 * r["value"], r["h2h"], st))
        if r.get("call"):
            print("      projected %s vs line %s -> %s   %s" % (r.get("adj_mean"), r["line"], r["call"], r.get("card", "")))
    W = sorted([r for r in R if not r["passed"] and r["why"].strip() == "no sharp price at this line"
                and not any(x.startswith("TEAM IMPLIED") for x in (r.get("flags") or []))],
               key=lambda r: -(r["p_role"] * r["mult"] - r["breakeven"]))
    if W:
        print("\nWATCHLIST -- %d legs pass ROLE + H2H, waiting on a Pinnacle price (it posts props on game day; rerun then):" % len(W))
        for r in W[:12]:
            print("   %-22s %-4s v %-4s %-14s %-5s %5s %-3s role %3.0f%% x%.2f = %3.0f%% (b/e %.0f%%) h2h %-4s adj mean %s %s" % (
                r["player"][:22], r["team"], r.get("opp", ""), r["stat"][:14], r["side"], r["line"], r["venue"], 100 * r["p_role"],
                r["mult"], 100 * r["p_role"] * r["mult"], 100 * r["breakeven"], r["h2h"], r.get("adj_mean"),
                ", ".join(r.get("flags") or [])))
            if r.get("card"):
                print("        card: %s   (#1 = most; SA#1 = allows the most shots)" % r["card"])
            print("        projected %s vs line %s -> %s" % (r.get("adj_mean"), r["line"], r.get("call")))
    if P:
        ov = sum(r["side"] == "over" for r in P) / len(P)
        print("\n%d PASS of %d legs screened.  Balance: %.0f%% overs / %.0f%% unders%s" % (
            len(P), len(R), 100 * ov, 100 * (1 - ov), "   <-- OVER THE 60% CAP, pick from the other side too" if max(ov, 1 - ov) > .6 else ""))
    else:
        print("\nNo legs passed all gates. Sit it out.")
    have = set()
    try:
        for l in open(OUT, encoding="utf-8"):
            x = json.loads(l); have.add((x["date"], x["player"], x["stat"], x["line"], x["side"], x["venue"]))
    except FileNotFoundError:
        pass
    new = [r for r in P if (r["date"], r["player"], r["stat"], r["line"], r["side"], r["venue"]) not in have]
    with open(OUT, "a", encoding="utf-8") as f:
        for r in new:
            f.write(json.dumps(dict(r, logged=datetime.datetime.now(CT).isoformat(), result=None), ensure_ascii=False) + "\n")
    print("logged %d new PAPER legs -> %s" % (len(new), OUT))


def grade():
    rows = [json.loads(l) for l in open(OUT, encoding="utf-8")]
    n = 0
    for r in rows:
        if r.get("result"):
            continue
        try:
            if r["sport"] == "NHL":
                p = nhl_player(r["player"])
                L = [x for x in nhl_logs(p["playerId"], r["field"] == "saves") if x["date"] == r["date"] or
                     x["date"] == (datetime.date.fromisoformat(r["date"]) + datetime.timedelta(days=1)).isoformat()]
            else:
                L = [x for x in espn_soccer_logs(r["espn_id"]) if x["date"] in (r["date"], (datetime.date.fromisoformat(r["date"]) + datetime.timedelta(days=1)).isoformat())]
        except Exception:
            continue
        if not L:
            continue
        v = L[0].get(r["field"], 0)
        r["actual"] = v
        r["result"] = "PUSH" if v == r["line"] else ("W" if ((v > r["line"]) if r["side"] == "over" else (v < r["line"])) else "L")
        n += 1
    with open(OUT, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    g = [r for r in rows if r.get("result") in ("W", "L")]
    for sp in sorted({r["sport"] for r in g}):
        x = [r for r in g if r["sport"] == sp]; w = sum(r["result"] == "W" for r in x)
        print("%-7s %d-%d  (%.1f%%)" % (sp, w, len(x) - w, 100 * w / len(x)))
    print("settled %d new" % n)


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print(__doc__); sys.exit()
    if a[0] == "grade":
        grade(); sys.exit()
    day = a[1] if len(a) > 1 else datetime.datetime.now(CT).strftime("%Y-%m-%d")
    R = screen_nhl(day) if a[0] == "nhl" else screen_soccer(day) if a[0] == "soccer" else []
    report(R)
