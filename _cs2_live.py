"""CS2 live card + grader. Paper-trades Underdog CS2 kill/headshot lines with _cs2_model.

    python _cs2_live.py card [min_edge]   # price every upcoming Underdog CS line, log PAPER picks
    python _cs2_live.py grade             # grade logged picks whose matches finished (bo3.gg)

Picks go to cs2_paper.jsonl (NOT live_paper.jsonl) with model version, line, both app lines,
model P, break-even and the time the pick was made -- so every overnight result is honest.
Break-even per leg on Underdog pick'em: sqrt(1/(3.5*m)) where m is the option multiplier
(reference_underdog_api / feedback_nfl_prop_filters). A plain 1.0x leg needs ~53.5%.
"""
import json, sys, os, math, glob, time, datetime, difflib, re, urllib.request, collections
import _cs2_model as M
import _cs2_series as SER   # Maps 1+2 priced by SERIES STATE with the measured spread

# 2026-09-22: Maps 1+2 are now priced by _cs2_series (SERIES STATE, measured spread 2.44x,
# not the 1.10x single-map figure v7 assumed). VERSION sat at "v7" for several batches AFTER
# that rewrite went live, so rows tagged v7 with ts >= 2026-09-22T18:00Z are actually this
# model. Anything earlier is genuine v7. Bump this string whenever the pricing path changes.
VERSION = "series-v1"   # was v7 + holdout-fit adjustments: recent form, event tier, team gap, sample size, Bo3, entry rate (map-specific omitted: map unknown pre-veto); full 36k-map history, recalibrated a=-0.20 b=0.62; v5 + skip lines >25% off model mean (role change guard); v3 + KPR by (won, map length) + logistic calibration (b=0.79, holdout-validated)
UA = {"User-Agent": "Mozilla/5.0 Chrome/124", "Accept": "application/json"}
PPUA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept": "application/json"}
g = lambda u, h=UA: json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=60).read())
CT = datetime.timezone(datetime.timedelta(hours=-5))
OUT = "cs2_paper.jsonl"
MAPS12_ONLY = True      # user 2026-09-18: only Maps 1+2 props -- best market, Map 1 alone is noise
EDGE_CAP = 0.09         # picks only in the 3-9% edge band; bigger model edges have been bug signals
# Measured 2026-09-20 on 621 graded lines: the picks that actually win are the ones in the 6-9%
# edge band on a map the model thinks is LOPSIDED. 60-28 = 68.2%, z=+2.77, and p=0.0123 on a
# max-z permutation test over the whole 20-filter family I searched, so it survives the multiple
# comparisons. Mechanism: the kill model multiplies KPR by 0.925 for the map winner and 0.41 for
# the loser, so on a coin-flip map the projection is a wide two-component mixture and the mean
# means little -- those lines went 107-122 (46.7%, z=-2.02). Away from 50/50 the multiplier is
# effectively known. See [[feedback_cs2_parlays_only]].
POTD_BAND = (0.06, 0.09)    # edge band for Play of the Day
COINFLIP = (0.45, 0.55)     # map win prob range to AVOID


def potd_ok(r):
    """The measured Play-of-the-Day filter: top edge band, and not a coin-flip map."""
    return (POTD_BAND[0] <= r["edge"] < POTD_BAND[1]
            and not (COINFLIP[0] <= r["map_winp"] <= COINFLIP[1])
            and not r.get("suspect"))
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
core = lambda s: norm(re.sub(r"(?i)(esports?|gaming|team|club|academy)", "", s or "")) or norm(s)


def same(x, y):
    return bool(x and y) and (x == y or (min(len(x), len(y)) >= 3 and (x in y or y in x)))


def team_score(a, b):
    """1.0 exact core match, 0.9 containment, else string ratio."""
    ca, cb = core(a), core(b)
    if ca == cb:
        return 1.0
    if same(ca, cb):
        return 0.9
    return difflib.SequenceMatcher(None, ca, cb).ratio() * 0.7


def build_state():
    maps = M.load()
    S = M.State()
    hs = collections.Counter()
    kills = collections.Counter()
    for _, _, _, _, teams in maps:
        for ps in teams.values():
            for r in ps:
                if r["hs"] is None or r["kills"] is None:
                    continue
                hs[r["player"]] += r["hs"]
                kills[r["player"]] += r["kills"]
        S.update(teams)
    lg_hs = sum(hs.values()) / max(1, sum(kills.values()))
    S.hs_rate = {p: (hs[p] + 60 * lg_hs) / (kills[p] + 60) for p in kills}   # 60 pseudo-kills
    S.lg_hs = lg_hs
    # v7 trackers: last-10 KPR, first-kill rate, last event tier per player
    rec = collections.defaultdict(lambda: collections.deque(maxlen=10))
    fk = collections.Counter(); tier = {}
    for _, _, _, _, teams in maps:
        for ps in teams.values():
            for r in ps:
                rec[r["player"]].append(r["kills"] / r["rounds"])
                fk[r["player"]] += r["fk"] or 0
                tier[r["player"]] = {"s": 3, "a": 2, "b": 1}.get(r.get("tier"), 0)
    S.v7 = dict(rec=rec, fk=fk, tier=tier, coef=json.load(open("cs2_v7_coef.json")) if os.path.exists("cs2_v7_coef.json") else None)
    # clan name each player last played under (Elo is keyed by clan name)
    S.clan = {}
    for _, _, _, _, teams in maps:
        for t, ps in teams.items():
            for r in ps:
                S.clan[r["player"]] = t
    return S, len(maps)


def nick_index():
    N = json.load(open("cs2_nicks.json"))
    idx = collections.defaultdict(list)
    for pid, v in N.items():
        if v.get("nick"):
            idx[norm(v["nick"])].append((v.get("last") or "", int(pid), v))
    return {k: sorted(v, reverse=True)[0] for k, v in idx.items()}


def pinnacle_winp():
    """Pinnacle CS2 match win probs keyed by normalised team names (market beats our Elo)."""
    sys.path.insert(0, "betting")
    import freeodds as fo
    dec = lambda a: 1 + a / 100 if a > 0 else 1 + 100 / -a
    out = {}
    try:
        mu = fo._get("%s/0.1/sports/12/matchups?withSpecials=false&brandId=0" % fo.PIN) or []
        mk = fo._get("%s/0.1/sports/12/markets/straight?primaryOnly=true" % fo.PIN) or []
    except Exception:
        return out
    px = {m["matchupId"]: {p.get("designation"): p.get("price") for p in m.get("prices", [])}
          for m in mk if m.get("key") == "s;0;m" and m.get("period") == 0}
    for m in mu:
        if m.get("parentId") or "CS2" not in (m.get("league") or {}).get("name", "") or m["id"] not in px:
            continue
        p = px[m["id"]]
        if p.get("home") is None or p.get("away") is None:
            continue
        s = {q["alignment"]: q["name"] for q in m["participants"]}
        ih, ia = 1 / dec(p["home"]), 1 / dec(p["away"])
        out[(norm(s["home"]), norm(s["away"]))] = ih / (ih + ia)
    return out


def match_to_map_winp(pm):
    """Series win prob -> single-map win prob for a Bo3 (invert p^2(3-2p))."""
    lo, hi = 0.0, 1.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if mid * mid * (3 - 2 * mid) < pm:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def print_potd(rows):
    """The picks that passed, in plain words. No ranking inside the pool -- it is not measured."""
    q = [r for r in rows if potd_ok(r)]
    # spread the legs over different matches, best line-shop first; inside the pool the picks
    # are equal so the only sensible ordering is variety, not model probability
    q.sort(key=lambda r: (r["match_id"], -r["n_maps_hist"]))
    print("\n" + "=" * 70)
    if not q:
        print("NO PLAYS TODAY. Nothing hit the good zone -- that happens, sit it out.")
        return
    print("THE GOOD ZONE  (%d picks passed)" % len(q))
    print("Out of sample (9/18 on) these went 109-83, 56.8% -- above the 53.5% UD 2-pick break-even, not yet proven. All of them are")
    print("equally good -- the model cannot tell them apart, so pick for variety.\n")
    for r in q[:8]:
        shop = ""
        if r["pp_line"] is not None and r["pp_line"] != r["line"]:
            better = "PrizePicks" if ((r["pp_line"] > r["line"]) == (r["side"] == "lower")) else "Underdog"
            shop = "  ->  better on %s (UD %.1f, PP %.1f)" % (better, r["line"], r["pp_line"])
        print("  %-13s %-5s %-5.1f %-9s  %s vs %s  %s%s" % (
            r["player"], "UNDER" if r["side"] == "lower" else "OVER", r["line"],
            "headshots" if r["kind"] == "hs" else "kills", r["team"][:14], r["opp"][:14],
            r["start_ct"], shop))
    # slips: different matches where possible, always 2+ teams
    def slip(n, mult, label):
        legs, teams, seen = [], set(), set()
        for r in q:
            if r["match_id"] in seen or any(x["player"] == r["player"] for x in legs):
                continue
            legs.append(r); teams.add(r["team"]); seen.add(r["match_id"])
            if len(legs) == n:
                break
        while len(legs) < n:                      # not enough matches, allow a second from one
            extra = next((r for r in q if r not in legs and all(x["player"] != r["player"] for x in legs)), None)
            if not extra:
                return
            legs.append(extra); teams.add(extra["team"])
        if len(teams) < 2:
            alt = next((r for r in q if r["team"] not in teams), None)
            if not alt:
                print("  %s: no slip -- every pick is on the same team" % label)
                return
            legs[-1] = alt
        print("\n  %s SLIP (pays %.1fx):  %s" % (
            label, mult, "  +  ".join("%s %s%.1f" % (r["player"], "U" if r["side"] == "lower" else "O", r["line"])
                                      for r in legs)))
    slip(2, 3.5, "2-PICK")
    slip(3, 6.5, "3-PICK")
    print("\n  Rule: skip anything the card shows with a huge edge. Those lose.")


def card(min_edge=0.03, max_hours=None):
    S, nmaps = build_state()
    # Maps 1+2 are priced by the series-state model. The old path assumes kills vary 1.10x
    # Poisson, which was measured on a SINGLE map; over two maps the real spread is 2.44x
    # because the maps are tied together by the series result. Using 1.10 made every
    # probability too confident -- a "70%" pick was really about 62%.
    SER_S = SER.State(SER.series_rows(SER.load()))
    NI = nick_index()
    PIN = pinnacle_winp()
    d = g("https://api.underdogfantasy.com/v1/over_under_lines")
    P = {p["id"]: p for p in d["players"]}
    A = {a["id"]: a for a in d["appearances"]}
    G = {gm["id"]: gm for gm in d.get("games", []) if gm.get("sport_id") == "CS"}
    try:
        pp = g("https://partner-api.prizepicks.com/projections?per_page=1000&league_id=265", PPUA)
        pinc = {(x["type"], x["id"]): x for x in pp.get("included", [])}
        PPL = {}
        for x in pp["data"]:
            a = x["attributes"]
            if a.get("odds_type") != "standard":
                continue
            pl = pinc.get(("new_player", x["relationships"]["new_player"]["data"]["id"]), {}).get("attributes", {})
            PPL[(norm(pl.get("name")), a["stat_type"].upper().replace("MAPS 1-2", "M12").replace("MAP 1", "M1"))] = a["line_score"]
    except Exception as e:
        print("prizepicks unavailable:", e)
        PPL = {}
    done = set()
    if os.path.exists(OUT):
        for l in open(OUT, encoding="utf-8"):
            r = json.loads(l)
            # rows added by hand (a one-off read) carry no match_id/stat; they are not card rows
            if not r.get("match_id") or not r.get("stat"):
                continue
            done.add((r["match_id"], r["player"], r["stat"], r.get("version")))
    now = datetime.datetime.now(datetime.timezone.utc)
    rows, miss = [], collections.Counter()
    for l in d["over_under_lines"]:
        ap = l["over_under"].get("appearance_stat", {})
        a = A.get(ap.get("appearance_id"))
        if not a or a.get("match_id") not in G:
            continue
        gm = G[a["match_id"]]
        start = datetime.datetime.fromisoformat(gm["scheduled_at"].replace("Z", "+00:00"))
        if start <= now or (max_hours and start > now + datetime.timedelta(hours=max_hours)):
            continue
        stat = ap.get("display_stat", "")
        kind = "hs" if "Headshot" in stat else "k" if "Kills" in stat else None
        nm = 2 if "1+2" in stat else 1 if "Map 1" in stat else None
        if not kind or not nm:
            continue
        if MAPS12_ONLY and nm != 2:
            continue                                   # user 2026-09-18: Maps 1+2 only
        p = P[a["player_id"]]
        nick = (p.get("last_name") or p.get("first_name") or "").strip()
        hit = NI.get(norm(nick))
        if not hit:
            miss["no history"] += 1
            continue
        _, pid, info = hit
        if S.pmaps[pid] < 8:
            miss["<8 maps"] += 1
            continue
        home, away = gm["full_team_names_title"].split(" vs ")
        clan = S.clan.get(pid)
        if not clan:
            miss["no clan"] += 1
            continue
        # which side is the player on? decide from HIS clan history, not Underdog's team ids
        if team_score(clan, home) >= team_score(clan, away):
            team_name, opp_name = home, away
        else:
            team_name, opp_name = away, home
        if max(team_score(clan, home), team_score(clan, away)) < 0.6:
            miss["clan/team mismatch (roster move?)"] += 1
            continue
        cands = sorted(((team_score(c, opp_name), c) for c in S.elo), reverse=True)
        opp_clan = cands[0][1] if cands and cands[0][0] >= 0.75 else None
        if opp_clan is None:
            miss["opponent unknown"] += 1
            continue
        pw = None
        tn, on = core(team_name), core(opp_name)
        for (h, aw), v in PIN.items():
            if same(h, tn) and same(aw, on):
                pw = v
            elif same(aw, tn) and same(h, on):
                pw = 1 - v
        line = float(l["stat_value"])
        opts = {o["choice"]: float(o.get("payout_multiplier") or 1) for o in l.get("options", [])}
        # price
        saved_elo = None
        if pw is not None:                       # override Elo with the market's map win prob
            mp = match_to_map_winp(pw)
            saved_elo = (S.elo[clan], S.elo[opp_clan])
            S.elo[clan] = M.ELO_BASE + 200 * math.log10(mp / (1 - mp))
            S.elo[opp_clan] = M.ELO_BASE - 200 * math.log10(mp / (1 - mp))
        v7m = 1.0
        if S.v7["coef"]:
            c = S.v7["coef"]
            season = S.pk[pid] / max(1, S.pr[pid])
            rf = (sum(S.v7["rec"][pid]) / len(S.v7["rec"][pid]) / max(.3, season)) if S.v7["rec"][pid] else 1.0
            gap = (S.elo[clan] - S.elo[opp_clan]) / 100
            v7m = 1 + (c["const"] + c["recent_form"] * (rf - 1) + c["tier"] * S.v7["tier"].get(pid, 0) + c["elo_gap/100"] * gap
                       + c["n_maps/100"] * min(200, S.pmaps[pid]) / 100 + c["bo3"] * (1 if nm == 2 else 0)
                       + c["fk_rate*10"] * 10 * S.v7["fk"][pid] / max(1, S.pr[pid]))
            v7m = max(0.85, min(1.15, v7m))
        _orig_kpr_v7 = S.kpr
        S.kpr = lambda q, o=None, _o=_orig_kpr_v7, _m=v7m: _o(q, o) * _m
        base_kpr = S.kpr(pid)
        if kind == "hs":
            S.pk[pid], S.pr[pid] = S.pk[pid], S.pr[pid]
            scale = S.hs_rate.get(pid, S.lg_hs)
            orig = S.kpr
            S.kpr = lambda q, o=None, _o=orig, _s=scale: _o(q, o) * _s
            po, mu = S.p_over(pid, clan, opp_clan, line, nm)
            S.kpr = orig
        else:
            po, mu = S.p_over(pid, clan, opp_clan, line, nm)
        winp = S.winp(clan, opp_clan)
        S.kpr = _orig_kpr_v7
        if saved_elo:
            S.elo[clan], S.elo[opp_clan] = saved_elo
        if po is None:
            continue
        raw_po = po
        if nm == 2:
            skind = "hs" if kind == "hs" else "kills"
            smu, h2h_n = SER_S.mean(pid, S.winp(clan, opp_clan), skind, opp_clan)
            if smu and smu > 0:
                po = SER.over(smu, line, SER.PHI[skind])
                mu = smu
                raw_po = po
        elif os.path.exists("cs2_calib.json"):
            c = json.load(open("cs2_calib.json"))
            z = c["a"] + c["b"] * math.log(max(1e-6, po) / max(1e-6, 1 - po))
            po = 1 / (1 + math.exp(-z))
        ppkey = (norm(nick), ("HEADSHOTS" if kind == "hs" else "KILLS"))
        ppline = PPL.get((norm(nick), ("M12 " if nm == 2 else "M1 ") + ("HEADSHOTS" if kind == "hs" else "KILLS")))
        for side, prob in (("higher", po), ("lower", 1 - po)):
            if side not in opts:
                continue
            be = math.sqrt(1 / (3.5 * opts[side]))
            rows.append(dict(ts=now.isoformat(), version=VERSION, match_id=a["match_id"], match=gm["full_team_names_title"],
                             start_ct=start.astimezone(CT).strftime("%a %H:%M"), start=gm["scheduled_at"],
                             player=nick, pid=pid, team=team_name, opp=opp_name, stat=stat, kind=kind, maps=nm,
                             line=line, pp_line=ppline, side=side, mult=opts[side], model_p=round(prob, 4),
                             model_mu=round(mu, 2), breakeven=round(be, 4), edge=round(prob - be, 4),
                             map_winp=round(winp, 3), market_winp=pw, n_maps_hist=S.pmaps[pid],
                             opp_clan=opp_clan, clan=clan, opp_D=round(S.D(opp_clan), 3), v7_mult=round(v7m, 3), raw_p=round(raw_po if side == "higher" else 1 - raw_po, 4)))
    rows.sort(key=lambda r: -r["edge"])
    print("history maps %d | priced sides %d | skipped %s | pinnacle CS2 matches %d" % (nmaps, len(rows), dict(miss), len(PIN)))
    print("%-6s %-5s %-14s %-24s %5s %5s %6s %6s %6s %5s  %s" % ("edge", "side", "player", "stat", "line", "PP", "P", "BE", "mu", "winp", "match (CT)"))
    for r in rows:
        ratio = r["model_mu"] / r["line"] if r["line"] else 1
        r["suspect"] = "line %.0f%% off model mean: role change / news the model can't see" % (100 * (ratio - 1)) if (ratio < 0.8 or ratio > 1.25) else None
    picks = [r for r in rows if min_edge <= r["edge"] < EDGE_CAP and not r["suspect"]]
    for r in rows[:40]:
        print("%+5.1f%% %-5s %-14s %-24s %5.1f %5s %5.1f%% %5.1f%% %6.1f %5.2f  %s %s%s" % (
            100 * r["edge"], r["side"][:5], r["player"][:14], r["stat"][:24], r["line"], r["pp_line"] if r["pp_line"] is not None else "-",
            100 * r["model_p"], 100 * r["breakeven"], r["model_mu"], r["map_winp"], r["match"][:30], r["start_ct"],
            "  <<" if potd_ok(r) else ""))
    print_potd(rows)
    new = 0
    with open(OUT, "a", encoding="utf-8") as f:
        for r in picks:
            k = (r["match_id"], r["player"], r["stat"], r["version"])
            if k in done:
                continue
            done.add(k)
            f.write(json.dumps(r) + "\n")
            new += 1
    # also keep EVERY priced side for calibration grading
    with open("cs2_priced_all.jsonl", "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print("\nlogged %d new PAPER picks (edge >= %.0f%%) -> %s" % (new, 100 * min_edge, OUT))


def actual_for(match_title, start_iso, pid, maps, nick=None):
    """Kills/HS for pid on maps 1..maps of the bo3.gg match matching this title/date."""
    day = start_iso[:10]
    # bo3 IGNORES `sort=` (and `page=`/`offset=`/`limit=`); the feed is OLDEST-FIRST, so
    # offsets 0/50/100 were scanning matches from years ago and this never matched anything.
    # The newest rows sit at the END, so walk back from the total count.
    total = g("https://api.bo3.gg/api/v1/matches?page[limit]=1")["total"]["count"]
    for off in (total - 100, total - 200, total - 300, total - 400):
        if off < 0:
            continue
        d = g("https://api.bo3.gg/api/v1/matches?page[offset]=%d&page[limit]=100"
              "&filter[matches.status][in]=finished,current&filter[matches.discipline_id][eq]=1&with=teams,games" % off)
        for m in d["results"]:
            if not m.get("team1") or not m.get("team2"):
                continue
            t1, t2 = m["team1"]["name"], m["team2"]["name"]
            A_, B_ = match_title.split(" vs ")
            if max(team_score(A_, t1) + team_score(B_, t2), team_score(A_, t2) + team_score(B_, t1)) < 1.7:
                continue
            if abs((datetime.date.fromisoformat(m["start_date"][:10]) - datetime.date.fromisoformat(day)).days) > 1:
                continue
            games = sorted(m.get("games") or [], key=lambda x: x["number"])
            if len(games) < maps:
                if m["status"] == "finished":
                    return None, "series ended before map %d (void)" % maps
                return None, "map %d not started" % maps
            k = h = 0
            for gm in games[:maps]:
                if gm.get("status") != "finished":
                    return None, "map %d not finished" % gm["number"]
                st = g("https://api.bo3.gg/api/v1/games/%d/players_stats" % gm["id"])
                if len(st) < 10:
                    return None, "stats not posted yet for map %d" % gm["number"]
                me = [p for p in st if p["steam_profile_id"] == pid or (nick and norm((p.get("steam_profile") or {}).get("nickname")) == norm(nick))
                      or (nick and norm(((p.get("steam_profile") or {}).get("player") or {}).get("nickname")) == norm(nick))]
                if not me:
                    return None, "player not in map %d (void)" % gm["number"]
                k += me[0]["kills"]
                h += me[0]["headshots"]
            return (k, h), "ok"
    return None, "not finished / not found"


def grade():
    for fn in (OUT, "cs2_priced_all.jsonl"):
        if not os.path.exists(fn):
            continue
        rows = [json.loads(l) for l in open(fn, encoding="utf-8")]
        cache = {}
        now = datetime.datetime.now(datetime.timezone.utc)
        changed = 0
        for r in rows:
            if r.get("result") in ("W", "L") or (r.get("result") == "VOID" and "series ended" in r.get("why", "")):
                continue
            # rows added by hand (a user-requested read, not a card run) can lack the ISO
            # start/pid the grader keys on -- skip them rather than killing the whole pass
            if not r.get("start") or not r.get("pid"):
                continue
            start = datetime.datetime.fromisoformat(r["start"].replace("Z", "+00:00"))
            if now < start + datetime.timedelta(hours=1, minutes=30 * r["maps"]):
                continue
            key = (r["match"], r["start"][:10], r["pid"], r["maps"])
            if key not in cache:
                try:
                    cache[key] = actual_for(r["match"], r["start"], r["pid"], r["maps"], r["player"])
                except Exception as e:
                    cache[key] = (None, "error %s" % e)
            val, why = cache[key]
            if val is None:
                if "void" in why:
                    r["result"], r["why"] = "VOID", why
                    changed += 1
                continue
            act = val[1] if r["kind"] == "hs" else val[0]
            r["actual"] = act
            over = act > r["line"]
            r["result"] = "W" if (over and r["side"] == "higher") or (not over and act < r["line"] and r["side"] == "lower") else "L"
            changed += 1
        with open(fn, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        g_ = [r for r in rows if r.get("result") in ("W", "L")]
        if fn == OUT:
            w = sum(r["result"] == "W" for r in g_)
            print("%s: graded now %d | record %d-%d (%.1f%%) | avg break-even %.1f%%" % (
                fn, changed, w, len(g_) - w, 100 * w / max(1, len(g_)),
                100 * sum(r.get("breakeven") or 0 for r in g_) / max(1, len(g_))))
        else:
            print("%s: graded now %d | calibration rows %d" % (fn, changed, len(g_)))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "card"
    if cmd == "card":
        card(float(sys.argv[2]) if len(sys.argv) > 2 else 0.03, float(sys.argv[3]) if len(sys.argv) > 3 else None)
    elif cmd == "grade":
        grade()
