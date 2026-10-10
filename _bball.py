"""BASKETBALL ENGINE -- WNBA + NBA player profiles and the prop screen (2026-09-30). Same gates as NHL.

    python _bball.py profile wnba "Caitlin Clark"     # our scouting file on the player
    python _bball.py screen wnba [YYYY-MM-DD]          # tonight's props: role, H2H, opponent D, card, call, early mode
    python _bball.py screen nba  [YYYY-MM-DD]          # same code for the NBA (opens ~Oct 20)

Data (all free): ESPN athlete gamelogs (every game: date, opponent, home/away, minutes, pts/reb/ast/3PM), ESPN team box
scores for defence (`_bball_card.py fetch`), Underdog + PrizePicks lines (PP: NBA 7, WNBA 3), Pinnacle (NBA 487, WNBA 578).
Gates: role = full-minutes games (>= 85% of last-5 minutes, current season); H2H vs tonight's opponent in the CURRENT role
band; value = Pinnacle at the same line, or EARLY mode (TAKE call + 5pp cushion) when Pinnacle hasn't posted;
WNBA playoff lift applied in postseason games (measured: MIN +10.3%, PTS -2.8%, REB +3.6%, AST -8.4%).
"""
import sys, os, json, re, math, datetime, collections, statistics as st, urllib.request
from concurrent.futures import ThreadPoolExecutor
import _props as P
import _bball_card as C

UA = {"User-Agent": "Mozilla/5.0"}
g = lambda u: json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40).read())
CT = datetime.timezone(datetime.timedelta(hours=-5))
CACHE = "_bball_logs"
os.makedirs(CACHE, exist_ok=True)
SEASONS = {"wnba": (2025, 2026), "nba": (2025, 2026)}   # ESPN NBA season 2026 = 2025-26
PP_LEAGUE = {"wnba": 3, "nba": 7}
PIN = {"wnba": 578, "nba": 487}
UD_SPORT = {"wnba": "WNBA", "nba": "NBA"}
PLAYOFF_LIFT = {"pts": -0.028, "reb": 0.036, "ast": -0.084, "tpm": 0.0}
COMBO = {"points": ["pts"], "pts": ["pts"], "rebounds": ["reb"], "rebs": ["reb"], "assists": ["ast"], "asts": ["ast"],
         "3pointersmade": ["tpm"], "3ptmade": ["tpm"], "threes": ["tpm"],
         "ptsrebsasts": ["pts", "reb", "ast"], "ptsrebs": ["pts", "reb"], "ptsasts": ["pts", "ast"], "rebsasts": ["reb", "ast"]}
PIN_STAT = {"pts": "points", "reb": "rebounds", "ast": "assists", "tpm": "threes made", "ptsrebast": "pts & rebs & asts"}


def ckey(stat):
    s = P.norm(stat).replace("rebounds", "rebs").replace("assists", "asts").replace("points", "pts")
    s = s.replace("pointers", "pt").replace("3ptmade", "3ptmade")
    return {"pra": "ptsrebsasts", "3pointersmade": "3pointersmade", "3ptmade": "3ptmade"}.get(s, s)


_ids = {}


def roster(league):
    if league not in _ids:
        m = {}
        for t in g("https://site.api.espn.com/apis/site/v2/sports/basketball/%s/teams" % league)["sports"][0]["leagues"][0]["teams"]:
            try:
                for a in g("https://site.api.espn.com/apis/site/v2/sports/basketball/%s/teams/%s/roster" % (league, t["team"]["id"]))["athletes"]:
                    m[P.norm(a["displayName"])] = (a["id"], t["team"]["abbreviation"], a["displayName"])
            except Exception:
                pass
        _ids[league] = m
    return _ids[league]


def logs(league, aid):
    f = os.path.join(CACHE, "%s_%s_%s.json" % (league, aid, datetime.date.today().isoformat()))
    if os.path.exists(f):
        try:
            return json.load(open(f, encoding="utf-8"))
        except ValueError:
            pass                                   # half-written by another thread: refetch
    out = []
    for yr in SEASONS[league]:
        try:
            d = g("https://site.web.api.espn.com/apis/common/v3/sports/basketball/%s/athletes/%s/gamelog?season=%d" % (league, aid, yr))
        except Exception:
            continue
        n = [x.lower() for x in d.get("names", [])]
        if not n:
            continue
        tp = [i for i, x in enumerate(n) if x.startswith("threepointfieldgoalsmade")]
        for s_ in d.get("seasonTypes", []):
            post = "post" in (s_.get("displayName") or "").lower()
            for c in s_.get("categories", []):
                for e in c.get("events", []):
                    s = e["stats"]; m = d["events"][e["eventId"]]
                    try:
                        out.append(dict(date=m["gameDate"][:10], opp=m["opponent"]["abbreviation"], home=m.get("atVs") == "vs",
                                        min=float(s[n.index("minutes")]), pts=float(s[n.index("points")]),
                                        reb=float(s[n.index("totalrebounds")]), ast=float(s[n.index("assists")]),
                                        tpm=float(s[tp[0]].split("-")[0]) if tp else 0.0, post=post, season=yr))
                    except (ValueError, IndexError, KeyError):
                        continue
    out.sort(key=lambda r: r["date"])
    tmp = f + ".%d.tmp" % os.getpid()
    json.dump(out, open(tmp, "w")); os.replace(tmp, f)       # atomic: readers never see a half file
    return out


def defense(league):
    """team -> what opponents score/rebound/assist/make from three against it (last 15), and league average"""
    rows = C.team_games(league)
    by = collections.defaultdict(list)
    for r in rows:
        by[r["team"]].append(r)
    D = {}
    for t, v in by.items():
        if len(v) < 10:
            continue
        v = sorted(v, key=lambda r: r["date"])[-15:]
        D[t] = {k: st.mean(r["a"][k] or 0 for r in v) for k in ("pts", "reb", "ast", "tpm")}
    avg = {k: st.mean(x[k] for x in D.values()) for k in ("pts", "reb", "ast", "tpm")}
    return D, avg


def tier_of(D, k, team):
    s = sorted(D, key=lambda t: D[t][k])
    i = s.index(team) if team in s else None
    if i is None:
        return None
    return "low" if i < len(s) / 3 else "high" if i >= 2 * len(s) / 3 else "mid"


# ------------------------------------------------------------------ profile
def profile(league, name, quiet=False):
    r = roster(league).get(P.norm(name))
    if not r:
        hits = [v for k, v in roster(league).items() if P.norm(name.split()[-1]) in k]
        r = hits[0] if len(hits) == 1 else None
    if not r:
        print("no player", name); return None
    aid, team, full = r
    L = logs(league, aid)
    if not L:
        print("no games", full); return None
    D, avg = defense(league)
    cur = [x for x in L if x["season"] == max(x["season"] for x in L)]
    ref = st.mean(x["min"] for x in cur[-5:])
    full_g = [x for x in cur if x["min"] >= 0.85 * ref]
    out = dict(name=full, team=team, last_game=L[-1]["date"], games=len(cur), min_avg=round(st.mean(x["min"] for x in cur), 1),
               min_last5=round(ref, 1), full_min_games=len(full_g), short_nights=round(100 * (1 - len(full_g) / len(cur))))
    stats = {}
    for lbl, parts in (("PTS", ["pts"]), ("REB", ["reb"]), ("AST", ["ast"]), ("3PM", ["tpm"]), ("PRA", ["pts", "reb", "ast"]),
                       ("R+A", ["reb", "ast"]), ("P+A", ["pts", "ast"])):
        v = lambda x: sum(x[p] for p in parts)
        allv = [v(x) for x in full_g]
        if len(allv) < 5:
            continue
        k = parts[0] if len(parts) == 1 else "pts"
        tiers = {t: [v(x) for x in full_g if tier_of(D, k, x["opp"]) == t] for t in ("high", "mid", "low")}
        stats[lbl] = dict(avg=round(st.mean(allv), 1), med=st.median(allv), sd=round(st.pstdev(allv), 1),
                          last10=round(st.mean(allv[-10:]), 1), all_games_avg=round(st.mean(v(x) for x in cur), 1),
                          home=round(st.mean([v(x) for x in full_g if x["home"]] or [0]), 1),
                          away=round(st.mean([v(x) for x in full_g if not x["home"]] or [0]), 1),
                          vs_def={t: round(st.mean(x), 1) if x else None for t, x in tiers.items()},
                          playoffs=round(st.mean([v(x) for x in L if x["post"]]), 1) if any(x["post"] for x in L) else None)
    out["stats"] = stats
    out["h2h"] = collections.defaultdict(list)
    for x in L[-60:]:
        out["h2h"][x["opp"]].append((x["date"][5:], int(x["min"]), int(x["pts"]), int(x["reb"]), int(x["ast"])))
    if not quiet:
        print("\n%s (%s)  last game %s | %d games | minutes %.1f (last 5: %.1f) | short nights %d%%" % (
            full, team, out["last_game"], out["games"], out["min_avg"], out["min_last5"], out["short_nights"]))
        print("  %-5s %7s %5s %5s %7s %9s %6s %6s   %-26s %s" % ("", "full-min", "med", "sd", "last10", "all games", "home", "away", "vs defence allowing hi/mid/lo", "playoffs"))
        for k, s in stats.items():
            vd = s["vs_def"]
            print("  %-5s %7s %5s %5s %7s %9s %6s %6s   %-26s %s" % (k, s["avg"], s["med"], s["sd"], s["last10"], s["all_games_avg"], s["home"], s["away"],
                                                               "%s / %s / %s" % (vd["high"], vd["mid"], vd["low"]), s["playoffs"]))
        print("  recent H2H (date, min, pts, reb, ast):")
        for o, v in sorted(out["h2h"].items(), key=lambda kv: -len(kv[1]))[:6]:
            print("     %-4s %s" % (o, v[-5:]))
    return out


# ------------------------------------------------------------------ screen
def games_on(league, day):
    sb = g("https://site.api.espn.com/apis/site/v2/sports/basketball/%s/scoreboard?dates=%s" % (league, day.replace("-", "")))
    opp = {}
    for e in sb.get("events", []):
        c = e["competitions"][0]["competitors"]
        post = (e.get("season") or {}).get("type") == 3
        a = [x for x in c if x["homeAway"] == "away"][0]["team"]["abbreviation"]; h = [x for x in c if x["homeAway"] == "home"][0]["team"]["abbreviation"]
        opp[a] = (h, e["date"], post, False); opp[h] = (a, e["date"], post, True)
    return opp


def screen(league, day):
    opp = games_on(league, day)
    print("%s %s: %s" % (league.upper(), day, ", ".join(sorted({" @ ".join(sorted((k, v[0]))) for k, v in opp.items()})) or "no games"))
    if not opp:
        return
    legs = []
    try:
        legs += P.underdog(UD_SPORT[league])
    except Exception as e:
        print("  underdog failed (unknown, not absent):", e)
    try:
        legs += [l for l in P.prizepicks(PP_LEAGUE[league]) if l.get("kind") != "demon"]
    except Exception as e:
        print("  prizepicks failed (unknown, not absent):", e)
    try:
        pin = P.pinnacle_props(PIN[league])
    except Exception:
        pin = {}
    D, avg = defense(league)
    R_ = roster(league)
    B2B_teams = {t for t, v in games_on(league, (datetime.date.fromisoformat(day) - datetime.timedelta(days=1)).isoformat()).items()} \
        if True else set()
    legs = [l for l in legs if ckey(l["stat"] or "") in COMBO and R_.get(P.norm(l["player"]), (0, ""))[1] in opp]
    print("  %d lines on tonight's players, %d Pinnacle props" % (len(legs), len(pin)))

    aids = sorted({R_[P.norm(l["player"])][0] for l in legs})
    with ThreadPoolExecutor(6) as ex:
        LOGS = dict(zip(aids, ex.map(lambda a: logs(league, a), aids)))   # one fetch per player

    def work(l):
        aid, team, full = R_[P.norm(l["player"])]
        L = LOGS.get(aid) or []
        cur = [x for x in L if x["season"] == max(x["season"] for x in L)] if L else []
        if len(cur) < 10:
            return None
        parts = COMBO[ckey(l["stat"])]
        v = lambda x: sum(x[p] for p in parts)
        ref = st.mean(x["min"] for x in cur[-5:])
        role = [x for x in cur if x["min"] >= 0.85 * ref]
        if len(role) < 8:
            return None
        o, start, post, home = opp[team]
        h2h = [x for x in L if x["opp"] == o and 0.85 * ref <= x["min"] <= 1.3 * ref]
        # RATE x EXPECTED MINUTES (2026-09-30): full-minutes averages overstate bench players whose playoff minutes shrink
        # -> per-minute rate from role games, times minutes over the last 5 games (short nights included).
        min_proj = st.mean(x["min"] for x in cur[-5:])
        po = [x for x in cur if x["post"]]
        if post and po:                           # playoff rotations tighten -- but phase them in: ONE blowout Game 1 set
            w = min(1.0, len(po) / 3.0)           # Bueckers to 25 min / 17.9 P+A vs 23-37 in her last 5 (2026-09-30)
            min_proj = w * st.mean(x["min"] for x in po[-3:]) + (1 - w) * min_proj
        vals = [v(x) / x["min"] * min_proj for x in role if x["min"] > 0]
        mu = st.mean(vals)
        # opponent defence: what it allows for each part, half weight (team rates regress)
        f = 1.0
        if o in D:
            num = sum(D[o][p] for p in parts); den = sum(avg[p] for p in parts)
            f = 1 + (num / den - 1) * 0.5
        mu *= f
        if post and league == "wnba":
            mu *= 1 + sum(PLAYOFF_LIFT[p] * (st.mean(x[p] for x in role) / max(1e-9, st.mean(vals))) for p in parts)
        sd = max(st.pstdev(vals), 1.0)
        flags = []
        try:
            import _news
            flags += _news.flags(league, team, full, day)            # injuries / new teammate absences (user 2026-09-30)
        except Exception:
            pass
        if team in B2B_teams:
            flags.append("BACK-TO-BACK")
        if L[-1]["date"] < (datetime.date.fromisoformat(day) - datetime.timedelta(days=10)).isoformat():
            flags.append("LAST GAME %s" % L[-1]["date"])
        tier = tier_of(D, parts[0] if len(parts) == 1 else "pts", o)
        res = []
        for side in ("over", "under"):
            if l["venue"] == "PP" and l.get("kind") in ("goblin", "demon"):
                continue                      # main lines only (user 10/2)
            if l["venue"] == "UD" and side not in l["mult"]:
                continue
            p_ = 0.5 * math.erfc(((l["line"] - mu) / sd) / math.sqrt(2)); p_ = p_ if side == "over" else 1 - p_
            emp = sum((x > l["line"]) if side == "over" else (x < l["line"]) for x in [q * f for q in vals]) / len(vals)
            rr = P.shrink((0.5 * p_ + 0.5 * emp) * len(vals), len(vals))
            hh = (sum((v(x) > l["line"]) if side == "over" else (v(x) < l["line"]) for x in h2h), len(h2h))
            pstat = "pts & rebs & asts" if parts == ["pts", "reb", "ast"] else PIN_STAT.get(parts[0]) if len(parts) == 1 else None
            pf = pin.get((P.norm(l["player"]), pstat, l["line"])) if pstat else None
            pf = None if pf is None else (pf if side == "over" else 1 - pf)
            # SANITY vs PINNACLE (2026-09-30): Pinnacle's line at ANY number is its median. Sum the single-stat medians for
            # combos; if our projection sits >15% off it, the model is what's wrong (Bueckers 23.4 vs Pinnacle PRA 28.5).
            pk = P.norm(l["player"])
            pmed = {}
            for (pp_, ps_, pl_), po_ in pin.items():
                if pp_ == pk:
                    pmed.setdefault(ps_, []).append(pl_ + (po_ - 0.5) * 2 * max(1.0, 0.25 * pl_ ** 0.5))
            if parts == ["pts", "reb", "ast"] and "pts & rebs & asts" in pmed:
                pin_mu = st.mean(pmed["pts & rebs & asts"])
            elif all(PIN_STAT.get(q) in pmed for q in parts):
                pin_mu = sum(st.mean(pmed[PIN_STAT[q]]) for q in parts)
            else:
                pin_mu = None
            off_pin = pin_mu is not None and pin_mu > 3 and abs(mu - pin_mu) / pin_mu > 0.15
            mult = l["mult"][side] if l["venue"] == "UD" else 1.0
            be = P.UD2_BE if l["venue"] == "UD" else (0.70 if l.get("kind") == "goblin" else P.PP2_BE)
            call, gap = P.projection_call(mu, sd, l["line"], allow_alt=False)
            dir_ok = (call == "TAKE OVER" and side == "over") or (call == "TAKE UNDER" and side == "under")
            ok_value = (pf is not None and pf * mult >= be) or (pf is None and dir_ok and rr * mult >= be + 0.05)
            ok_h2h = hh[1] < 2 or hh[0] / hh[1] >= 0.5
            res.append(dict(sport=league.upper(), date=day, player=full, team=team, opp=o, start=start, stat=l["stat"], line=l["line"],
                            side=side, venue=l["venue"], kind=l.get("kind"), mult=mult, p_pin=pf, p_role=round(rr, 3), role_n=len(vals),
                            h2h="%d/%d" % hh, breakeven=round(be, 3), value=round((pf if pf is not None else rr) * mult, 3),
                            adj_mean=round(mu, 1), call=call, gap=gap, opp_def_tier=tier, flags=flags + ([] if pf is not None else ["EARLY"]) + (["PINNACLE ~%.1f" % pin_mu] if pin_mu else []) + (["MODEL OFF PINNACLE"] if off_pin else []),
                            pin_mu=None if pin_mu is None else round(pin_mu, 1),
                            passed=bool(ok_value and ok_h2h and not off_pin and not any(x.startswith(("LAST GAME", "OUT:")) for x in flags)),
                            why=("" if ok_value else "value") + ("" if ok_h2h else " h2h")))
        return res

    with ThreadPoolExecutor(6) as ex:
        R = [x for r in ex.map(work, legs) if r for x in r]
    try:
        import _calls
        seen = {}
        for r in R:
            seen.setdefault((r["player"], r["stat"], r["line"]), r)
        _calls.log([dict(r, proj=r["adj_mean"]) for r in seen.values()])
        _calls.legs_dump(league.upper(), day, [dict(r, p=(r["p_pin"] if r.get("p_pin") is not None else r["p_role"])) for r in R])
    except Exception as e:
        print("  call log failed:", e)
    Pz = sorted([r for r in R if r["passed"]], key=lambda r: -(r["value"] - r["breakeven"]))
    print("\n%-22s %-4s %-4s %-16s %-5s %5s %-3s %6s %6s %-5s  %s" % ("player", "tm", "opp", "stat", "side", "line", "app", "proj", "value", "h2h", "call / flags"))
    for r in Pz[:25]:
        print("%-22s %-4s %-4s %-16s %-5s %5s %-3s %6s %5.0f%% %-5s  %s | opp D allows %s | %s" % (
            r["player"][:22], r["team"], r["opp"], r["stat"][:16], r["side"], r["line"], r["venue"] + ("g" if r.get("kind") == "goblin" else ""), r["adj_mean"], 100 * r["value"],
            r["h2h"], r["call"], r["opp_def_tier"], ", ".join(r["flags"])))
    if Pz:
        ov = sum(r["side"] == "over" for r in Pz) / len(Pz)
        print("\n%d pass. Balance %.0f%% overs%s" % (len(Pz), 100 * ov, "  <-- over the 60%% cap" if max(ov, 1 - ov) > .6 else ""))
    else:
        print("\nnothing passed")
    with open("props_paper.jsonl", "a", encoding="utf-8") as fh:
        for r in Pz:
            fh.write(json.dumps(dict(r, logged=datetime.datetime.now(CT).isoformat(), result=None), ensure_ascii=False) + "\n")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "profile":
        profile(a[1], " ".join(a[2:]))
    else:
        screen(a[1], a[2] if len(a) > 2 else datetime.datetime.now(CT).strftime("%Y-%m-%d"))
