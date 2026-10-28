"""CROSS-CHECK BOARD (10/28, user: "mispriced stuff ... all over twitter ... more cross checks on other free sites so we can see if we
are getting good value, kinda how Upside had it").

Every PrizePicks STANDARD line (NBA / NFL / NHL / CFB) priced by every free source on one row:
    apps   Underdog (v1 over_under_lines, per-side payout multipliers)   Sleeper (lines/available, per-side multipliers)
           Dabble (api.dabble.com, decimal price per side)
    books  Pinnacle (guest API, de-vigged)   FanDuel (public JSON: NBA tabs + ladders, NFL/CFB via _fanduel)
Each source's probability is moved to PP's number with _mismatch.p_over_at (Poisson for small counts, normal spread otherwise; a
different line further than 0.75 sd is dropped, not guessed). Consensus = books x2 + apps x1. FLAG = 2+ sources and the consensus
side at 60%+ (PP 2-pick break-even 57.7%) -- the same thing a Twitter "mispriced" post is, measured instead of eyeballed.

    python _xcheck.py [NBA NFL NHL CFB]     # board -> console + site/xcheck.json; flags appended to xcheck_log.jsonl (graded later)
    python _xcheck.py loop 600 NBA NHL      # rerun every 10 min, phone alert (ntfy) on each NEW flag -- the edge is speed (PP lags news)
First run 10/28: 789 NBA/NHL lines cross-checked (3-5 sources each), 0 flags -- top was 57%. PP's main lines sit inside 2-7 pts of
the market almost always; the flags are the minutes after news when PP hasn't moved yet.
"""
import sys, os, re, json, datetime, statistics, unicodedata
import requests
import _mismatch as M

H = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
CT = datetime.timezone(datetime.timedelta(hours=-5))
LOG = "xcheck_log.jsonl"
norm = M.norm
PP_LEAGUE = {"NBA": 7, "NFL": 9, "NHL": 8, "CFB": 15}
COMBO_SD = {"pts & rebs", "pts & asts", "rebs & asts"}                 # spread like points (sd_for has no combo rows)

# every source's stat name -> one vocabulary (Pinnacle's)
PP_STAT = {"points": "points", "rebounds": "rebounds", "assists": "assists", "3-pt made": "threes made", "pts+rebs+asts": "pts & rebs & asts",
           "pts+rebs": "pts & rebs", "pts+asts": "pts & asts", "rebs+asts": "rebs & asts", "shots on goal": "shots on goal",
           "goalie saves": "saves", "goals": "goals", "pass yards": "passing yards", "rush yards": "rushing yards",
           "receiving yards": "receiving yards", "receptions": "receptions", "pass attempts": "pass attempts",
           "pass completions": "pass completions", "rush attempts": "rush attempts"}
SLEEPER_STAT = {"points": "points", "rebounds": "rebounds", "assists": "assists", "threes_made": "threes made", "pts_reb_ast": "pts & rebs & asts",
                "points_and_rebounds": "pts & rebs", "points_and_assists": "pts & asts", "rebounds_and_assists": "rebs & asts",
                "shots": "shots on goal", "shots_on_goal": "shots on goal", "saves": "saves", "goals": "goals",
                "passing_yards": "passing yards", "rushing_yards": "rushing yards", "receiving_yards": "receiving yards",
                "receptions": "receptions", "passing_attempts": "pass attempts", "passing_completions": "pass completions",
                "rushing_attempts": "rush attempts"}
UD_STAT = {"points": "points", "rebounds": "rebounds", "assists": "assists", "3pointersmade": "threes made", "ptsrebsasts": "pts & rebs & asts",
           "pointsrebounds": "pts & rebs", "pointsassists": "pts & asts", "reboundsassists": "rebs & asts", "ptsrebs": "pts & rebs",
           "ptsasts": "pts & asts", "rebsasts": "rebs & asts", "shotsongoal": "shots on goal", "shots": "shots on goal", "saves": "saves",
           "goaliesaves": "saves", "goals": "goals", "passingyards": "passing yards", "rushingyards": "rushing yards",
           "receivingyards": "receiving yards", "receptions": "receptions", "passingattempts": "pass attempts",
           "passingcompletions": "pass completions", "rushingattempts": "rush attempts", "passyards": "passing yards",
           "rushyards": "rushing yards", "recyards": "receiving yards"}
FD_NBA = {"Points": "points", "Rebounds": "rebounds", "Assists": "assists", "Made Threes": "threes made", "Pts + Reb + Ast": "pts & rebs & asts",
          "Pts + Reb": "pts & rebs", "Pts + Ast": "pts & asts", "Reb + Ast": "rebs & asts"}
DABBLE_COMP = {"NFL": "NFL", "NBA": "NBA", "NHL": "US NHL"}


def two_way(po, pu):
    """two prices for the same line (any convention where bigger = less likely) -> P(over)"""
    return po / (po + pu)


def get(u, t=60):
    return requests.get(u, headers=H, timeout=t).json()


def src_pinnacle(sp, S):
    import _props as P
    for (pl, st, ln), p in P.pinnacle_props(M.PIN_LEAGUE[sp]).items():
        S.setdefault((pl, st), {}).setdefault("Pinnacle", []).append((ln, p))


def src_fanduel(sp, S):
    if sp == "NBA":
        import _single_check as SC
        for (pl, st), q in SC.nba_board().items():
            c = FD_NBA.get(st)
            for ln, (o, u) in (q["ou"].items() if c else []):
                if o is not None and u is not None:
                    S.setdefault((pl, c), {}).setdefault("FanDuel", []).append((ln, two_way(M_imp(o), M_imp(u))))
    elif sp in ("NFL", "CFB"):
        import _fanduel
        for (pl, st, ln), p in _fanduel.props(sp.lower()).items():
            S.setdefault((pl, st), {}).setdefault("FanDuel", []).append((ln, p))


def M_imp(a):
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def src_sleeper(sp, S):
    if sp == "CFB":
        return
    names = {k: v.get("full_name") for k, v in get("https://api.sleeper.app/v1/players/" + sp.lower(), 120).items()}
    for r in get("https://api.sleeper.app/lines/available?dynamic=true&include_preseason=true&eg=15.control"):
        if r.get("sport") != sp.lower() or r.get("status") != "active":
            continue
        c = SLEEPER_STAT.get(r.get("wager_type")); o = {x["outcome"]: x for x in r.get("options", [])}
        if not c or "over" not in o or "under" not in o:
            continue
        mo, mu = float(o["over"]["payout_multiplier"]), float(o["under"]["payout_multiplier"])
        S.setdefault((norm(names.get(r["subject_id"])), c), {}).setdefault("Sleeper", []).append((float(o["over"]["outcome_value"]), two_way(1 / mo, 1 / mu)))


_UD = None
def src_underdog(sp, S):
    global _UD
    _UD = _UD or get("https://api.underdogfantasy.com/v1/over_under_lines", 120)
    d = _UD
    P = {p["id"]: p for p in d["players"]}; A = {a["id"]: a for a in d["appearances"]}
    for l in d["over_under_lines"]:
        if l.get("status") != "active":
            continue
        ap = l["over_under"].get("appearance_stat", {}); a = A.get(ap.get("appearance_id")); p = P.get(a and a.get("player_id"))
        if not p or p.get("sport_id") != sp:
            continue
        c = UD_STAT.get(norm(ap.get("display_stat")))
        o = {x.get("choice"): x for x in l.get("options", [])}
        if not c or "higher" not in o or "lower" not in o:
            continue
        mo, mu = float(o["higher"].get("payout_multiplier") or 0), float(o["lower"].get("payout_multiplier") or 0)
        if mo and mu:
            S.setdefault((norm("%s %s" % (p["first_name"], p["last_name"])), c), {}).setdefault("Underdog", []).append(
                (float(l["stat_value"]), two_way(1 / mo, 1 / mu)))


def src_dabble(sp, S):
    if sp not in DABBLE_COMP:
        return
    import _dabble as D
    for f in D.fixtures(DABBLE_COMP[sp], hours=36):
        side = {}
        for p in D.props(f["id"]):
            c = D.STAT.get(p["stat"])
            if c and p["price"]:
                side.setdefault((norm(p["player"]), c, p["line"]), {})[(p["side"] or "").lower()] = p["price"]
        for (pl, c, ln), q in side.items():
            if "over" in q and "under" in q:
                S.setdefault((pl, c), {}).setdefault("Dabble", []).append((ln, two_way(1 / q["over"], 1 / q["under"])))


def pp_lines(sp):
    import _ppcache
    d = _ppcache.projections(PP_LEAGUE[sp], 600)
    P = {i["id"]: i["attributes"] for i in d.get("included", []) if i["type"] == "new_player"}
    now = datetime.datetime.now(datetime.timezone.utc)
    for x in d["data"]:
        a = x["attributes"]
        if a.get("odds_type") != "standard" or a.get("is_promo"):
            continue
        c = PP_STAT.get(a["stat_type"].lower())
        t = datetime.datetime.fromisoformat(a["start_time"])
        if not c or not (now < t < now + datetime.timedelta(hours=36)):
            continue
        p = P.get(x["relationships"]["new_player"]["data"]["id"], {})
        yield dict(sport=sp, player=p.get("name"), team=p.get("team"), stat=a["stat_type"], canon=c, line=float(a["line_score"]),
                   start=t.astimezone(CT).strftime("%a %I:%M%p"))


def p_at(rows, line, canon):
    return M.p_over_at(rows, line, "points" if canon in COMBO_SD else canon)


def board(sports):
    out = []
    for sp in sports:
        S = {}
        for f in (src_pinnacle, src_fanduel, src_underdog, src_sleeper, src_dabble):
            try:
                f(sp, S)
            except Exception as e:
                print("  %s %s: %s" % (sp, f.__name__[4:], str(e)[:80]))
        n = 0
        for g in pp_lines(sp):
            q = S.get((norm(g["player"]), g["canon"]), {})
            src = {}
            for name, rows in q.items():
                p = p_at(rows, g["line"], g["canon"])
                if p is not None:
                    src[name] = (round(p, 3), min(rows, key=lambda r: abs(r[0] - g["line"]))[0])
            n += 1
            if len(src) < 2:
                continue
            w = {k: (2 if k in ("Pinnacle", "FanDuel") else 1) for k in src}
            po = sum(src[k][0] * w[k] for k in src) / sum(w.values())
            side, p = ("over", po) if po >= .5 else ("under", 1 - po)
            out.append(dict(g, side=side, p=round(p, 3), n=len(src), src=src,
                            lines={k: v[1] for k, v in src.items()}))
        print("%s: %d PP standard lines, %d with 2+ sources" % (sp, n, sum(1 for r in out if r["sport"] == sp)))
    return out


def main(sports, push=False):
    rows = board(sports)
    flags = sorted([r for r in rows if r["p"] >= .60], key=lambda r: -r["p"])
    os.makedirs("site", exist_ok=True)
    json.dump(rows, open(os.path.join("site", "xcheck.json"), "w", encoding="utf-8"), indent=0)
    day = datetime.datetime.now(CT).date().isoformat()
    seen = set()
    if os.path.exists(LOG):
        seen = {json.loads(l)["key"] for l in open(LOG, encoding="utf-8")}
    new = []
    with open(LOG, "a", encoding="utf-8") as f:
        for r in flags:
            k = "%s|%s|%s|%s" % (day, r["player"], r["stat"], r["line"])
            if k not in seen:
                f.write(json.dumps(dict(r, day=day, key=k), ensure_ascii=False) + "\n"); new.append(r)
    if push and new:
        import _push
        _push.push("MISPRICED on PrizePicks (%d)" % len(new), "\n".join(
            "%s %s %s %s -- market %.0f%% (%d sources)" % (r["player"], r["side"].upper(), r["line"], r["stat"], 100 * r["p"], r["n"]) for r in new[:8]))
    print("\nMISPRICED vs the market (consensus 60%%+, PP 2-pick b/e 57.7%%) -- %d of %d cross-checked lines" % (len(flags), len(rows)))
    for r in flags[:30]:
        s = "  ".join("%s %s@%.0f%%" % (k[:3], r["lines"][k], 100 * (v[0] if r["side"] == "over" else 1 - v[0])) for k, v in r["src"].items())
        print("  %-4s %-22s %-17s %-5s %5s  %3.0f%%  (%d src)  %s  | %s" % (r["sport"], r["player"][:22], r["stat"][:17], r["side"].upper(),
              r["line"], 100 * r["p"], r["n"], r["start"], s))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["loop"]:                      # python _xcheck.py loop 600 [NBA NHL ...] -- phone alert on each NEW 60%+ line
        import time
        every = int(a[1]) if len(a) > 1 and a[1].isdigit() else 600
        sp = [x.upper() for x in a[2:]] or ["NBA", "NHL", "NFL", "CFB"]
        while True:
            try:
                main(sp, push=True)
            except Exception as e:
                print("xcheck error:", e)
            time.sleep(every)
    else:
        main([x.upper() for x in a] or ["NBA", "NHL", "NFL", "CFB"])
