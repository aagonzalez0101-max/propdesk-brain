"""CROSS-CHECK BOARD (10/28, user: "mispriced stuff ... all over twitter ... more cross checks on other free sites so we can see if we
are getting good value, kinda how Upside had it").

Every PrizePicks STANDARD line (NBA / NFL / NHL / CFB) priced by every free source on one row:
    apps   Underdog (v1 over_under_lines, per-side payout multipliers)   Sleeper (lines/available, per-side multipliers)
           Dabble (api.dabble.com, decimal price per side)
    books  Pinnacle (guest API, de-vigged)   FanDuel (public JSON: NBA tabs + ladders, NFL/CFB via _fanduel)
Each source's probability is moved to PP's number with _mismatch.p_over_at (Poisson for small counts, normal spread otherwise; a
different line further than 0.75 sd is dropped, not guessed). Consensus (11/15) = SHARP books only, weighted Pinnacle 3 / FanDuel 2 / BetRivers 2 / Bovada 1 / Kalshi 1; DFS apps are a separate
discrepancy check (a different number than PP, or a side priced 55%+). FLAG = 2+ sources and the consensus
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
CT = __import__("zoneinfo").ZoneInfo("America/Chicago")
LOG = "xcheck_log.jsonl"
norm = M.norm
PP_LEAGUE = {"NBA": 7, "NFL": 9, "NHL": 8, "CFB": 15, "CBB": 20}   # 11/6: + CBB (sources: Underdog + Sleeper only)
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


# ---- 11/15: more SHARP sources (user: "add them all"). Each price is stored under (player, stat, game date) when the source gives a date,
# so a back-to-back team never gets tonight's price on tomorrow's PP line.
SHARP_W = {"Pinnacle": 3, "FanDuel": 2, "BetRivers": 2, "Bovada": 1, "Kalshi": 1}     # market % = these only
DFS = ("Underdog", "Sleeper", "Dabble")                                               # discrepancy check only, not the market %


def _add(S, pl, canon, src, ln, p, date=None):
    S.setdefault((pl, canon) if date is None else (pl, canon, date), {}).setdefault(src, []).append((ln, p))


KALSHI = {"NBA": {"KXNBAPTS": "points", "KXNBAREB": "rebounds", "KXNBAAST": "assists", "KXNBAPRA": "pts & rebs & asts", "KXNBA3PT": "threes made"},
          "NHL": {"KXNHLPTS": "points", "KXNHLGOAL": "goals", "KXNHLSOG": "shots on goal"},
          "NFL": {"KXNFLRECYDS": "receiving yards", "KXNFLPASSYDS": "passing yards", "KXNFLRSHYDS": "rushing yards", "KXNFLREC": "receptions"}}
MON = {m: i + 1 for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


def src_kalshi(sp, S):
    """Kalshi ladders: 'Name: 25+ ...' = P(X >= 25) = P(over floor_strike 24.5). Mid of bid/ask, only when both sides are quoted
    and the spread is <= 15c (wider = no real price)."""
    for ser, canon in KALSHI.get(sp, {}).items():
        try:
            ms = get("https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=%s&status=open&limit=1000" % ser, 30).get("markets", [])
        except Exception:
            continue
        for m in ms:
            b, a = float(m.get("yes_bid_dollars") or 0), float(m.get("yes_ask_dollars") or 0)
            if m.get("strike_type") != "greater" or not (0 < b < a < 1) or a - b > .15 or m.get("floor_strike") is None:
                continue
            g = re.match(r".*-(\d\d)([A-Z]{3})(\d\d)", m["event_ticker"])
            date = "20%s-%02d-%s" % (g.group(1), MON[g.group(2)], g.group(3)) if g else None
            _add(S, norm(m["title"].split(":")[0]), canon, "Kalshi", float(m["floor_strike"]), (a + b) / 2, date)


KAMBI_PATH = {"NBA": "basketball/nba", "NHL": "ice_hockey/nhl", "NFL": "american_football/nfl", "CFB": "american_football/ncaaf"}
KAMBI_STAT = [("points, rebounds & assists", "pts & rebs & asts"), ("points & rebounds", "pts & rebs"), ("points & assists", "pts & asts"),
              ("rebounds & assists", "rebs & asts"), ("3-point", "threes made"), ("points scored", "points"), ("rebounds", "rebounds"),
              ("assists", "assists"), ("shots on goal", "shots on goal"), ("saves", "saves"), ("passing yards", "passing yards"),
              ("rushing yards", "rushing yards"), ("receiving yards", "receiving yards"), ("receptions", "receptions"),
              ("pass attempts", "pass attempts"), ("pass completions", "pass completions"), ("rushing attempts", "rush attempts")]


def src_betrivers(sp, S):
    """BetRivers = Kambi public offering JSON (rsiusil). Player O/U offers: criterion '... by the player', outcomes OT_OVER/OT_UNDER,
    line and decimal odds in 1/1000."""
    if sp not in KAMBI_PATH:
        return
    B = "https://eu-offering-api.kambicdn.com/offering/v2018/rsiusil"
    now = datetime.datetime.now(datetime.timezone.utc)
    for e in get("%s/listView/%s/all/all/matches.json?lang=en_US&market=US" % (B, KAMBI_PATH[sp]), 30).get("events", []):
        e = e["event"]; t = datetime.datetime.fromisoformat(e["start"].replace("Z", "+00:00"))
        if not (now < t < now + datetime.timedelta(hours=40)):
            continue
        date = t.astimezone(CT).date().isoformat()
        try:
            offers = get("%s/betoffer/event/%s.json?lang=en_US&market=US&includeParticipants=true" % (B, e["id"]), 30).get("betOffers", [])
        except Exception:
            continue
        for o in offers:
            lab = o["criterion"]["label"].lower()
            if "player" not in lab or any(w in lab for w in ("next", "quarter", "half", "period", "1st", "first")):
                continue
            canon = next((c for k, c in KAMBI_STAT if k in lab), None)
            side = {}
            for oc in o.get("outcomes", []):
                if oc.get("type") in ("OT_OVER", "OT_UNDER") and oc.get("odds") and oc.get("line") is not None:
                    nm = oc.get("participant") or ""
                    nm = " ".join(reversed(nm.split(", "))) if ", " in nm else nm
                    side.setdefault((nm, oc["line"] / 1000), {})[oc["type"]] = oc["odds"] / 1000
            for (nm, ln), q in side.items():
                if canon and nm and len(q) == 2:
                    _add(S, norm(nm), canon, "BetRivers", ln, two_way(1 / q["OT_OVER"], 1 / q["OT_UNDER"]), date)


BOV_PATH = {"NBA": "basketball/nba", "NHL": "hockey/nhl", "NFL": "football/nfl", "CFB": "football/college-football"}
BOV_STAT = {"points": "points", "rebounds": "rebounds", "assists": "assists", "points, rebounds and assists": "pts & rebs & asts",
            "points, rebounds & assists": "pts & rebs & asts", "points and rebounds": "pts & rebs", "points and assists": "pts & asts",
            "rebounds and assists": "rebs & asts", "made threes": "threes made", "three pointers made": "threes made",
            "3-point field goals made": "threes made", "shots on goal": "shots on goal", "saves": "saves",
            "passing yards": "passing yards", "rushing yards": "rushing yards", "receiving yards": "receiving yards",
            "receptions": "receptions", "pass attempts": "pass attempts", "pass completions": "pass completions", "rushing attempts": "rush attempts"}


def src_bovada(sp, S):
    """Bovada public coupon JSON. Prop market 'Total Points - Rudy Gobert (MIN)', outcomes Over/Under with handicap + american price."""
    if sp not in BOV_PATH:
        return
    B = "https://www.bovada.lv/services/sports/event/coupon/events/A/description"
    lst = get("%s/%s?marketFilterId=def&preMatchOnly=true&lang=en" % (B, BOV_PATH[sp]), 30)
    now = datetime.datetime.now(datetime.timezone.utc)
    for ev in (lst[0]["events"] if lst else []):
        t = datetime.datetime.fromtimestamp(ev["startTime"] / 1000, datetime.timezone.utc)
        if not (now < t < now + datetime.timedelta(hours=40)):
            continue
        date = t.astimezone(CT).date().isoformat()
        try:
            d = get(B + ev["link"] + "?lang=en", 30)
        except Exception:
            continue
        for e2 in (d[0]["events"] if d else []):
            for dg in e2.get("displayGroups", []):
                for mk in dg.get("markets", []):
                    g = re.match(r"^(?:Total )?(.+?) - (.+?)(?: \(([A-Z]{2,4})\))?$", mk.get("description", ""))
                    if not g or (mk.get("period") or {}).get("abbreviation", "G") not in ("G", "M", "FG"):
                        continue
                    canon = BOV_STAT.get(g.group(1).lower())
                    q = {o["description"].lower(): o for o in mk.get("outcomes", [])}
                    if not canon or "over" not in q or "under" not in q:
                        continue
                    try:
                        ln = float(q["over"]["price"]["handicap"])
                        am = lambda x: int(str(x).replace("EVEN", "100").replace("+", ""))
                        po = two_way(M_imp(am(q["over"]["price"]["american"])), M_imp(am(q["under"]["price"]["american"])))
                    except Exception:
                        continue
                    _add(S, norm(g.group(2)), canon, "Bovada", ln, po, date)


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
                   start=t.astimezone(CT).strftime("%a %I:%M%p"), date=t.astimezone(CT).date().isoformat())


def p_at(rows, line, canon):
    return M.p_over_at(rows, line, "points" if canon in COMBO_SD else canon)


def board(sports):
    out = []
    for sp in sports:
        S = {}
        for f in (src_pinnacle, src_fanduel, src_betrivers, src_bovada, src_kalshi, src_underdog, src_sleeper, src_dabble):
            try:
                f(sp, S)
            except Exception as e:
                print("  %s %s: %s" % (sp, f.__name__[4:], str(e)[:80]))
        cnt = {}
        for k, v in S.items():
            for name in v:
                cnt[name] = cnt.get(name, 0) + 1
        print("  %s sources (player-stats priced): %s" % (sp, ", ".join("%s %d" % kv for kv in sorted(cnt.items(), key=lambda x: -x[1])) or "none"))
        n = 0
        for g in pp_lines(sp):
            q = {}
            for key in ((norm(g["player"]), g["canon"]), (norm(g["player"]), g["canon"], g["date"])):
                for name, rows in S.get(key, {}).items():
                    q.setdefault(name, []).extend(rows)
            src = {}
            for name, rows in q.items():
                p = p_at(rows, g["line"], g["canon"])
                if p is not None:
                    src[name] = (round(p, 3), min(rows, key=lambda r: abs(r[0] - g["line"]))[0])
            n += 1
            sharp = {k: v for k, v in src.items() if k in SHARP_W}
            dfs = {k: v for k, v in src.items() if k in DFS}
            if not sharp and len(dfs) < 2:
                continue
            if sharp:
                po = sum(sharp[k][0] * SHARP_W[k] for k in sharp) / sum(SHARP_W[k] for k in sharp)
            else:
                po = sum(v[0] for v in dfs.values()) / len(dfs)
            side, p = ("over", po) if po >= .5 else ("under", 1 - po)
            pd = sum(v[0] for v in dfs.values()) / len(dfs) if dfs else None
            gaps = {k: v[1] for k, v in dfs.items() if v[1] != g["line"]}            # a DFS site posting a different number than PP
            out.append(dict(g, side=side, p=round(p, 3), n=len(src), n_sharp=len(sharp), basis="sharp" if sharp else "dfs",
                            p_dfs=round(pd, 3) if pd is not None else None, dfs_gaps=gaps, src=src, lines={k: v[1] for k, v in src.items()}))
        mine = [r for r in out if r["sport"] == sp]
        print("%s: %d PP standard lines, %d priced (%d by 1+ sharp book, %d by 2+)" % (sp, n, len(mine),
              sum(1 for r in mine if r["n_sharp"]), sum(1 for r in mine if r["n_sharp"] >= 2)))
    return out


def main(sports, push=False):
    rows = board(sports)
    flags = sorted([r for r in rows if r["p"] >= .60], key=lambda r: -r["p"])
    os.makedirs("site", exist_ok=True)
    json.dump(rows, open(os.path.join("site", "xcheck.json"), "w", encoding="utf-8"), indent=0)
    day = datetime.datetime.now(CT).date().isoformat()
    # 11/14: every run's FULL snapshot is archived (the site file is overwritten per run, and lines.db stopped 10/31) -> grade bands later
    ts = datetime.datetime.now(CT).isoformat(timespec="minutes")
    with open("xcheck_snap.jsonl", "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(dict(r, day=day, ts=ts), ensure_ascii=False) + "\n")
    seen = set()
    if os.path.exists(LOG):
        seen = {json.loads(l)["key"] for l in open(LOG, encoding="utf-8") if l.strip()}
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
    top = sorted([r for r in rows if r["basis"] == "sharp" and r["p"] >= .52], key=lambda r: (-min(r["n_sharp"], 3), -r["p"]))
    print("\nTOP BY SHARP CONSENSUS (market 52%%+, sharp books only; DFS lines after |) -- %d lines" % len(top))
    for r in top[:25]:
        sh = "  ".join("%s %s@%.0f%%" % (k[:3], r["lines"][k], 100 * (v[0] if r["side"] == "over" else 1 - v[0])) for k, v in r["src"].items() if k in SHARP_W)
        df = "  ".join("%s %s" % (k[:3], r["lines"][k]) for k in r["src"] if k in DFS)
        print("  %-4s %-22s %-17s %-5s %5s  %3.0f%%  (%d sharp)  %s  | %s | %s" % (r["sport"], r["player"][:22], r["stat"][:17], r["side"].upper(),
              r["line"], 100 * r["p"], r["n_sharp"], r["start"], sh, df or "-"))
    disc = [r for r in rows if r["dfs_gaps"] or (r["p_dfs"] is not None and abs(r["p_dfs"] - .5) >= .05)]
    print("\nDFS DISCREPANCIES (a DFS site posts a different number than PP, or prices a side 55%%+) -- %d lines" % len(disc))
    for r in sorted(disc, key=lambda r: -max([abs(v - r["line"]) for v in r["dfs_gaps"].values()] + [0]))[:20]:
        d = "  ".join("%s %s" % (k[:3], v) for k, v in r["dfs_gaps"].items())
        print("  %-4s %-22s %-17s PP %-5s | DFS lines: %s | DFS over %s | market %s %.0f%% (%s)" % (r["sport"], r["player"][:22], r["stat"][:17],
              r["line"], d or "same", "%.0f%%" % (100 * r["p_dfs"]) if r["p_dfs"] is not None else "-", r["side"], 100 * r["p"], r["basis"]))
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
