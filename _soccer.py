"""SOCCER PROPS -- PrizePicks STANDARD lines vs each player's own recent STARTS (built 2026-09-30).

    python _soccer.py [YYYY-MM-DD]     # screen that day's PP soccer board (default: today, CT)
    python _soccer.py grade            # settle soccer_paper.jsonl from FotMob box scores

The user's markets (2026-09-29): Passes Attempted first, then Goalie Saves, plus shots / shots on target and
the role stats. STANDARD ONLY -- he never takes soccer goblins.

Data, all free, no key: FotMob
  search   /api/data/search/suggest?term=<name>          -> player id (team name breaks ties)
  player   /api/data/playerData?id=<id>                  -> last ~32 matches, club AND country, minutes, bench
  match    /api/data/matchDetails?matchId=<id>           -> every stat per player (cached forever once finished)

Model v1: the player's last 15 STARTS (60+ minutes) -> share over/under the line, shrunk toward 50%.
Why starts: PP voids a DNP but grades a sub appearance, and a line is set for a starter's minutes -- sub cameos are
a different role (the WNBA full-minutes lesson). Rotation risk is flagged separately (starts in the last 5).
Gates: side prob >= 57.7% (PP 2-pick break-even) + 3pp cushion because there is no sharp soccer prop price;
H2H vs this opponent can only VETO (>= 3 starts and < 50%).
"""
import sys, os, json, re, math, datetime, unicodedata, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor
import _props

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
FM = "https://www.fotmob.com/api/data"
CACHE = "_fotmob"
OUT = "soccer_paper.jsonl"
CT = datetime.timezone(datetime.timedelta(hours=-5))
os.makedirs(CACHE, exist_ok=True)
BE = 1 / 3 ** 0.5                 # 57.7% -- PrizePicks 2-pick power
CUSHION = 0.03


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def get(url):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40).read())


def _num(x):
    """'400 (88%)' -> 400, '1.62' -> 1.62, 42 -> 42, None -> None"""
    if x is None:
        return None
    try:
        return float(str(x).split(" ")[0])
    except ValueError:
        return None


TEAM_KEYS = {"BallPossesion": "poss", "total_shots": "shots", "ShotsOnTarget": "sot", "accurate_passes": "passes",
             "expected_goals": "xg"}


def match(mid, need_team=False):
    f = os.path.join(CACHE, "m%s.json" % mid)
    if os.path.exists(f):
        m = json.load(open(f, encoding="utf-8"))
        if not need_team or "teamStats" in m:
            return m
    d = get("%s/matchDetails?matchId=%s" % (FM, mid))
    fin = ((d.get("general") or {}).get("finished")) or ((d.get("header") or {}).get("status") or {}).get("finished")
    ts = {}
    try:
        for grp in d["content"]["stats"]["Periods"]["All"]["stats"]:
            for s in grp.get("stats", []):
                k = TEAM_KEYS.get(s.get("key"))
                if k and k not in ts and s.get("stats") and None not in s["stats"]:
                    ts[k] = [_num(v) for v in s["stats"]]
    except (KeyError, TypeError):
        pass
    teams = [dict(id=t.get("id"), name=t.get("name"), score=t.get("score")) for t in (d.get("header") or {}).get("teams", [])]
    if teams and all(t.get("score") is not None for t in teams):
        ts["goals"] = [float(t["score"]) for t in teams]
    slim = {"finished": bool(fin), "playerStats": (d.get("content") or {}).get("playerStats") or {},
            "teams": teams, "teamStats": ts}
    if fin:
        json.dump(slim, open(f, "w", encoding="utf-8"))
    return slim


def player_data(pid):
    f = os.path.join(CACHE, "p%s.json" % pid)
    if os.path.exists(f) and (datetime.datetime.now().timestamp() - os.path.getmtime(f)) < 6 * 3600:
        d = json.load(open(f, encoding="utf-8"))
        if "nextMatch" in d:
            return d
    d = get("%s/playerData?id=%s" % (FM, pid))
    slim = {k: d.get(k) for k in ("id", "name", "primaryTeam", "positionDescription", "injuryInformation",
                                  "recentMatches", "nextMatch")}
    json.dump(slim, open(f, "w", encoding="utf-8"))
    return slim


# ------------------------------------------------------------ how teams play: last 10 matches, for and against
_profiles = {}


def team_profile(tid, n=10):
    """Averages of what this team DOES (for_) and what opponents do AGAINST it (against), over its last n finished
    matches. Possession, shots, shots on target, accurate passes, xG, goals."""
    if tid in _profiles:
        return _profiles[tid]
    f = os.path.join(CACHE, "t%s_%s.json" % (tid, datetime.date.today().isoformat()))
    if os.path.exists(f):
        _profiles[tid] = json.load(open(f, encoding="utf-8")); return _profiles[tid]
    try:
        t = get("%s/teams?id=%s" % (FM, tid))
        fx = ((t.get("fixtures") or {}).get("allFixtures") or {}).get("fixtures") or []
    except Exception:
        return None
    done = [x for x in fx if (x.get("status") or {}).get("finished") and not (x.get("status") or {}).get("cancelled")][-n:]
    rows = []
    for x in done:
        try:
            m = match(x["id"], need_team=True)
        except Exception:
            continue
        ids = [tm.get("id") for tm in m.get("teams", [])]
        if tid not in ids or not m.get("teamStats"):
            continue
        i = ids.index(tid); j = 1 - i
        rows.append({"for": {k: v[i] for k, v in m["teamStats"].items()}, "against": {k: v[j] for k, v in m["teamStats"].items()}})
    if not rows:
        return None
    prof = {"n": len(rows)}
    for side in ("for", "against"):
        prof[side] = {}
        for k in ("poss", "shots", "sot", "passes", "xg", "goals"):
            vals = [r[side].get(k) for r in rows if r[side].get(k) is not None]
            prof[side][k] = sum(vals) / len(vals) if vals else None
    json.dump(prof, open(f, "w", encoding="utf-8"))
    _profiles[tid] = prof
    return prof


# ------------------------------------------------------------ the market's read of the match (Pinnacle 1X2 + total)
_pin = None


def pinnacle_soccer():
    global _pin
    if _pin is None:
        H = dict(UA, **{"X-API-Key": "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R"})
        M = json.loads(urllib.request.urlopen(urllib.request.Request(
            "https://guest.api.arcadia.pinnacle.com/0.1/sports/29/matchups", headers=H), timeout=60).read())
        K = json.loads(urllib.request.urlopen(urllib.request.Request(
            "https://guest.api.arcadia.pinnacle.com/0.1/sports/29/markets/straight", headers=H), timeout=60).read())
        mk = {}
        for k in K:
            if k.get("period") == 0 and not k.get("isAlternate"):
                mk.setdefault(k["matchupId"], {})[k["type"]] = k
        _pin = [(m, mk.get(m["id"], {})) for m in M if m.get("type") == "matchup" and not m.get("parent")
                and not re.search(r"U\d\d|Women|Reserves", m["league"]["name"])]
    return _pin


def pin_match(home, away, utc):
    imp = lambda o: (-o / (-o + 100)) if o < 0 else 100 / (o + 100)
    for m, mk in pinnacle_soccer():
        names = {p["alignment"]: p["name"] for p in m.get("participants", [])}
        if abs((datetime.datetime.fromisoformat(m["startTime"].replace("Z", "+00:00")) -
                datetime.datetime.fromisoformat(utc.replace("Z", "+00:00"))).total_seconds()) > 6 * 3600:
            continue
        h, a = norm(names.get("home")), norm(names.get("away"))
        if not (h[:5] and a[:5] and (h[:5] in norm(home) or norm(home)[:5] in h) and (a[:5] in norm(away) or norm(away)[:5] in a)):
            continue
        ml = mk.get("moneyline")
        if not ml:
            return None
        pr = {p["designation"]: imp(p["price"]) for p in ml["prices"]}
        tot = sum(pr.values())
        out = {k: v / tot for k, v in pr.items()}
        t = mk.get("total")
        if t:
            out["total"] = t["prices"][0].get("points")
        return out
    return None


def find_player(name, team):
    try:
        s = get("%s/search/suggest?term=%s&lang=en" % (FM, urllib.parse.quote(name)))
    except Exception:
        return None
    cands = [x for blk in s for x in blk.get("suggestions", []) if x.get("type") == "player"]
    if not cands:
        return None
    exact = [c for c in cands if norm(c["name"]) == norm(name)] or cands
    for c in exact:
        if team and (norm(team) in norm(c.get("teamName")) or norm(c.get("teamName")) in norm(team)):
            return c["id"]
    return exact[0]["id"]


_teams = {}


def find_team(name):
    if name in _teams:
        return _teams[name]
    try:
        s = get("%s/search/suggest?term=%s&lang=en" % (FM, urllib.parse.quote(name)))
    except Exception:
        return None
    c = [x for blk in s for x in blk.get("suggestions", []) if x.get("type") == "team"]
    exact = [x for x in c if norm(x.get("name")) == norm(name)] or c
    _teams[name] = int(exact[0]["id"]) if exact else None
    return _teams[name]


def fval(stats, key, part="value"):
    for b in stats:
        v = (b.get("stats") or {}).get(key)
        if v and v.get("stat"):
            return v["stat"].get(part)
    return None


# PP stat -> how to read it from a FotMob player box
STAT = {
    "passes attempted": lambda s: fval(s, "Accurate passes", "total"),
    "goalie saves": lambda s: fval(s, "Saves"),
    "shots": lambda s: fval(s, "Total shots"),
    "shots on target": lambda s: fval(s, "Shots on target"),
    "clearances": lambda s: fval(s, "Clearances"),
    "crosses": lambda s: fval(s, "Accurate crosses", "total"),
    "attempted dribbles": lambda s: fval(s, "Successful dribbles", "total"),
    "shots assisted": lambda s: fval(s, "Chances created"),
    "goals allowed": lambda s: fval(s, "Goals conceded"),
    "tackles": lambda s: fval(s, "Tackles"),
}
ZERO_OK = {"shots", "shots on target", "clearances", "crosses", "attempted dribbles", "shots assisted", "goals allowed",
           "tackles", "goalie saves"}   # FotMob omits a zero count; a started player with no entry had 0


def history(pid, stat, n_starts=15):
    pd = player_data(pid)
    rm = pd.get("recentMatches") or []
    if isinstance(rm, dict):
        rm = [m for v in rm.values() for m in (v if isinstance(v, list) else [])]
    rm = sorted(rm, key=lambda m: (m.get("matchDate") or {}).get("utcTime", ""), reverse=True)
    last5 = [m for m in rm[:5]]
    started5 = sum(1 for m in last5 if (m.get("minutesPlayed") or 0) >= 60)
    rows = []
    for m in rm:
        if (m.get("minutesPlayed") or 0) < 60:
            continue
        try:
            ps = match(m["id"]).get("playerStats", {})
        except Exception:
            continue
        box = ps.get(str(pid))
        if not box:
            continue
        v = STAT[stat](box.get("stats") or [])
        if v is None:
            if stat in ZERO_OK:
                v = 0
            else:
                continue
        rows.append(dict(date=(m.get("matchDate") or {}).get("utcTime", "")[:10], opp=m.get("opponentTeamName"),
                         league=m.get("leagueName"), mins=m.get("minutesPlayed"), v=float(v)))
        if len(rows) >= n_starts:
            break
    inj = pd.get("injuryInformation")
    return rows, started5, inj, (pd.get("primaryTeam") or {}).get("teamName"), pd.get("positionDescription")


# which opponent tendency moves each stat: (for = what the opponent does, against = what teams do vs it), metric
OPP_METRIC = {
    "passes attempted": ("against", "passes"), "goalie saves": ("for", "sot"), "goals allowed": ("for", "goals"),
    "shots": ("against", "shots"), "shots on target": ("against", "sot"), "shots assisted": ("against", "shots"),
    "crosses": ("against", "poss"), "attempted dribbles": ("against", "poss"), "clearances": ("for", "shots"),
    "tackles": ("for", "poss"),
}


def shrink(h, n, k=6):
    return (h + 0.5 * k) / (n + k)


def screen(day):
    B = _props.prizepicks(82, max_age=900)
    legs = [b for b in B if b.get("kind") == "standard" and (b["stat"] or "").lower() in STAT and b.get("start")
            and datetime.datetime.fromisoformat(b["start"]).astimezone(CT).strftime("%Y-%m-%d") == day
            and "+" not in (b["player"] or "")]
    print("SOCCER %s: %d PrizePicks STANDARD lines on modelled stats" % (day, len(legs)))
    # opponent = the OTHER team posted at the same kickoff (PP's description field is an abbreviation FotMob never uses)
    teams_at = {}
    for b in B:
        if b.get("team") and "/" not in b["team"]:
            teams_at.setdefault(b["start"], set()).add(b["team"])
    for b in legs:
        others = teams_at.get(b["start"], set()) - {b.get("team")}
        b["opp_team"] = sorted(others)[0] if len(others) == 1 else None

    def gather(b):
        pid = find_player(b["player"], b.get("team"))
        if not pid:
            return None
        stat = b["stat"].lower()
        rows, s5, inj, team, pos = history(pid, stat)
        if len(rows) < 6:
            return None
        nm = player_data(pid).get("nextMatch") or {}
        prof = pin = None
        own_id = None
        mine_home = None
        if nm and abs((datetime.datetime.fromisoformat(nm["matchDate"].replace("Z", "+00:00")) -
                       datetime.datetime.fromisoformat(b["start"])).total_seconds()) < 18 * 3600:
            tn = norm(b.get("team"))[:5]
            mine_home = tn and tn in norm(nm.get("homeName")) if tn else None
            if mine_home is None or (not mine_home and not (tn in norm(nm.get("awayName")))):
                mine_home = (nm.get("homeId") == ((player_data(pid).get("primaryTeam") or {}).get("teamId")))
            opp_id = nm["awayId"] if mine_home else nm["homeId"]
            own_id = nm["homeId"] if mine_home else nm["awayId"]
            prof = team_profile(opp_id)
            try:
                pm = pin_match(nm.get("homeName"), nm.get("awayName"), nm["matchDate"])
            except Exception:
                pm = None
            if pm:
                pin = dict(win=pm.get("home") if mine_home else pm.get("away"),
                           lose=pm.get("away") if mine_home else pm.get("home"), draw=pm.get("draw"), total=pm.get("total"))
        opp_name = (nm.get("awayName") if mine_home else nm.get("homeName")) if mine_home is not None else None
        intl = False
        if prof is None and (b.get("opp_team") or b.get("opp")):
            intl = True
            # national-team window: FotMob's nextMatch is the CLUB's next game, so find tonight's opponent by name.
            # Several internationals share a kickoff, so the same-kickoff pairing can fail -- PP's own opponent field backs it up.
            opp_name = b.get("opp_team") or b.get("opp")
            tid = find_team(opp_name)
            prof = team_profile(tid) if tid else None
            for h, a, mine in ((b.get("team"), opp_name, True), (opp_name, b.get("team"), False)):
                try:
                    pm = pin_match(h, a, b["start"])
                except Exception:
                    pm = None
                if pm:
                    pin = dict(win=pm.get("home") if mine else pm.get("away"), lose=pm.get("away") if mine else pm.get("home"),
                               draw=pm.get("draw"), total=pm.get("total"))
                    break
        # OUR side of the matchup card too (user 2026-09-30: both teams' offense and defense, every leg)
        try:
            own = team_profile(own_id) if own_id else team_profile(find_team(b.get("team")))
        except Exception:
            own = None
        return dict(b=b, pid=pid, stat=stat, rows=rows, s5=s5, inj=inj, pos=pos, prof=prof, pin=pin, opp_name=opp_name, own=own, intl=intl)

    with ThreadPoolExecutor(6) as ex:
        G = [g for g in ex.map(gather, legs) if g]
    # reference = the average team in today's pool of opponent profiles (both what they do and what they allow)
    pool = {}
    for g in G:
        if g["prof"]:
            pool[id(g["prof"])] = g["prof"]
    REF = {}
    for side in ("for", "against"):
        for k in ("poss", "shots", "sot", "passes", "xg", "goals"):
            v = [p[side][k] for p in pool.values() if p[side].get(k) is not None] + \
                [p[{"for": "against", "against": "for"}[side]][k] for p in pool.values()
                 if p[{"for": "against", "against": "for"}[side]].get(k) is not None]
            REF[(side, k)] = sum(v) / len(v) if v else None

    def work(g):
        b, stat, rows, s5, inj, pos, pid = g["b"], g["stat"], g["rows"], g["s5"], g["inj"], g["pos"], g["pid"]
        L = b["line"]
        n = len(rows); vals = [r["v"] for r in rows]; avg = sum(vals) / n
        # 1. OPPONENT STYLE: how much of this stat the opponent gives up (or creates), vs the average team today
        f, why = 1.0, ""
        side_k = OPP_METRIC.get(stat)
        prof = g["prof"]
        if side_k and prof and prof[side_k[0]].get(side_k[1]) and REF.get(side_k):
            raw = prof[side_k[0]][side_k[1]] / REF[side_k]
            w = prof["n"] / (prof["n"] + 8.0)            # 10 matches of opponent data -> ~55% weight
            f = 1 + (raw - 1) * w
            why = "opp %s %s %.1f vs avg %.1f" % ("allows" if side_k[0] == "against" else "makes",
                                                 side_k[1], prof[side_k[0]][side_k[1]], REF[side_k])
        adj = [v * f for v in vals]
        mu = avg * f
        def p_side(over):
            emp = sum((v > L) if over else (v < L) for v in adj) / n
            if avg < 8:                                   # small counts: blend in a Poisson at the adjusted mean
                cdf = sum(math.exp(-mu) * mu ** k / math.factorial(k) for k in range(int(math.floor(L)) + 1))
                pk = math.exp(-mu) * mu ** int(L) / math.factorial(int(L)) if float(L).is_integer() else 0
                pois = (1 - cdf) if over else (cdf - pk)
                emp = 0.5 * emp + 0.5 * pois
            return (emp * n + 0.5 * 6) / (n + 6)
        po, pu = p_side(True), p_side(False)
        side, p = ("over", po) if po >= pu else ("under", pu)
        over = sum(r["v"] > L for r in rows); under = sum(r["v"] < L for r in rows)
        opp = g.get("opp_name") or b.get("opp_team") or (b.get("opp") or "")
        key = norm(opp)[:6]
        h = [r for r in rows if key and norm(r["opp"])[:6] == key]
        hh = sum((r["v"] > L) if side == "over" else (r["v"] < L) for r in h)
        veto = len(h) >= 3 and hh / len(h) < 0.5
        flags = []
        if s5 < 4:
            flags.append("ROTATION %d/5 starts" % s5)
        if inj:
            flags.append("INJURY NOTE")
        # 2. GAME SCRIPT from Pinnacle: a big favourite keeps the ball, shoots more and faces fewer shots; a big
        #    underdog the reverse. If the pick runs against the script it is downgraded -- direction only, no fitted size.
        pin = g["pin"]; script = ""
        conflict = False
        if pin and pin.get("win") is not None:
            fav = pin["win"] >= 0.60; dog = pin["win"] <= 0.22
            script = "FAV %d%%" % round(100 * pin["win"]) if fav else "DOG %d%%" % round(100 * pin["win"]) if dog else \
                     "EVEN %d%%" % round(100 * pin["win"])
            up_when_fav = {"passes attempted": True, "goalie saves": False, "goals allowed": False, "shots": True,
                           "shots on target": True, "shots assisted": True, "clearances": False, "crosses": True,
                           "attempted dribbles": True, "tackles": False}.get(stat)
            if up_when_fav is not None and (fav or dog):
                wants_up = (side == "over")
                script_up = fav if up_when_fav else dog
                conflict = wants_up != script_up
            if conflict:
                flags.append("AGAINST GAME SCRIPT (%s)" % script)
        # overs capped at LEAN: graded soccer overs ran 4-11 then 14-14 while unders ran 8-1 / 18-9 (2026-10-02).
        # national-team games: our numbers are mostly CLUB matches and roles don't transfer (Højlund 27 passes vs POR, 10/1)
        intl = bool(g.get("intl"))
        if intl:
            flags.append("NATIONAL TEAM (club-based numbers: check country-only + possession script)")
        verdict = "HIT" if (p >= BE + CUSHION and not veto and s5 >= 4 and not inj and not conflict and side == "under" and not intl) else \
                  "LEAN" if p >= BE and not veto else "AVOID"
        def _card(pf):
            if not pf:
                return None
            return {"%s_%s" % (sd[0], k): (round(pf[sd][k], 1) if pf[sd].get(k) is not None else None)
                    for sd in ("for", "against") for k in ("poss", "passes", "shots", "sot", "xg", "goals")}
        card = {"team": _card(g.get("own")), "opp": _card(g.get("prof"))}
        import statistics as _st
        _sd = _st.pstdev(adj) if len(adj) > 1 else 1.0
        call, gap = _props.projection_call(mu, _sd, L, allow_alt=False)     # soccer: never goblins (user rule)
        return dict(call=call, gap=gap, card=card, date=day, player=b["player"], team=b.get("team"), opp=opp, start=b["start"], stat=b["stat"],
                    line=L, side=side, p=round(p, 3), n=n, hits=over if side == "over" else under,
                    avg=round(avg, 1), adj_avg=round(mu, 1), factor=round(f, 3), factor_why=why, script=script,
                    pin=pin, last5=[int(x) for x in vals[:5]], h2h="%d/%d" % (hh, len(h)),
                    starts_last5=s5, flags=flags, verdict=verdict, fotmob_id=pid, position=pos)

    R = [r for r in map(work, G) if r]
    R.sort(key=lambda r: ({"HIT": 0, "LEAN": 1, "AVOID": 2}[r["verdict"]], -r["p"]))
    json.dump(R, open("_soccer_board_%s.json" % day, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print("\n%-6s %-22s %-14s %-18s %-5s %5s %5s %7s %6s %-18s %-5s %s" % (
        "", "player", "team", "stat", "side", "line", "prob", "record", "avg", "last 5 starts", "h2h", "flags"))
    for r in R:
        print("%-6s %-22s %-14s %-18s %-5s %5s %4.0f%% %3d/%-3d %6s %-18s %-5s %s" % (
            r["verdict"], r["player"][:22], (r["team"] or "")[:14], r["stat"][:18], r["side"], r["line"], 100 * r["p"],
            r["hits"], r["n"], r["avg"], str(r["last5"])[:18], r["h2h"], ", ".join(r["flags"])))
    hit = [r for r in R if r["verdict"] == "HIT"]
    if hit:
        ov = sum(r["side"] == "over" for r in hit) / len(hit)
        print("\n%d HIT / %d LEAN / %d AVOID.  HIT balance: %.0f%% overs%s" % (
            len(hit), sum(r["verdict"] == "LEAN" for r in R), sum(r["verdict"] == "AVOID" for r in R), 100 * ov,
            "  <-- over the 60% cap" if max(ov, 1 - ov) > .6 else ""))
    try:
        import _calls
        _calls.log([dict(r, sport="SOCCER", proj=r.get("adj_avg")) for r in R])
        _calls.legs_dump("SOCCER", day, [dict(r, sport="SOCCER", side=sd, p=(r["p"] if sd == r["side"] else 1 - r["p"]), venue="PP",
                                              kind="standard", mult=1.0) for r in R for sd in ("over", "under")])
    except Exception as e:
        print("  call log failed:", e)
    have = set()
    if os.path.exists(OUT):
        have = {(x["date"], x["player"], x["stat"], x["line"]) for x in map(json.loads, open(OUT, encoding="utf-8"))}
    # 10/22 user: "keep doing passes for paper on all soccer instead of just goalies" -> every modelled line is papered (verdict kept on the row)
    new = [r for r in R if (r["date"], r["player"], r["stat"], r["line"]) not in have]
    with open(OUT, "a", encoding="utf-8") as f:
        for r in new:
            f.write(json.dumps(dict(r, result=None), ensure_ascii=False) + "\n")
    print("logged %d new PAPER legs -> %s" % (len(new), OUT))
    return R


def grade():
    if not os.path.exists(OUT):
        print("nothing logged yet"); return
    rows = [json.loads(l) for l in open(OUT, encoding="utf-8")]
    n = 0
    for r in rows:
        if r.get("result"):
            continue
        try:
            os.path.exists(os.path.join(CACHE, "p%s.json" % r["fotmob_id"])) and os.remove(os.path.join(CACHE, "p%s.json" % r["fotmob_id"]))
            pd = player_data(r["fotmob_id"])
        except Exception:
            continue
        rm = pd.get("recentMatches") or []
        m = next((m for m in rm if (m.get("matchDate") or {}).get("utcTime", "")[:10] in
                  (r["date"], (datetime.date.fromisoformat(r["date"]) + datetime.timedelta(days=1)).isoformat())), None)
        if not m:
            continue
        if not m.get("playedInMatch"):
            r["result"] = "VOID"; n += 1; continue
        box = match(m["id"]).get("playerStats", {}).get(str(r["fotmob_id"]))
        if not box:
            continue
        v = STAT[r["stat"].lower()](box.get("stats") or [])
        v = 0 if v is None and r["stat"].lower() in ZERO_OK else v
        if v is None:
            continue
        r["actual"] = v
        r["result"] = "PUSH" if v == r["line"] else ("W" if ((v > r["line"]) if r["side"] == "over" else (v < r["line"])) else "L")
        n += 1
    with open(OUT, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    for v in ("HIT", "LEAN"):
        g = [r for r in rows if r["verdict"] == v and r.get("result") in ("W", "L")]
        if g:
            w = sum(r["result"] == "W" for r in g); print("%-5s %d-%d (%.0f%%)" % (v, w, len(g) - w, 100 * w / len(g)))
    print("settled %d" % n)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "grade":
        grade()
    else:
        screen(a[0] if a else datetime.datetime.now(CT).strftime("%Y-%m-%d"))
