"""THE 10 GATES, AUTOMATED (11/19, user: "add all 10 to each sport ... no matter which we do ... its gonna make sure we get good betting").

Every leg, every sport, runs the same ten gates; each prints PASS / FAIL / N/A (N/A = we have no data for that gate in that sport --
shown, never silently passed). A leg is CLEAN only with zero FAILs. Then the slip check (gate 10) runs over the legs together.
    1 LINE      live PP line, kind, our side open (allowed_wager_types), whole number = push
    2 RULE      a measured rule fires (NBA/NHL EDGE rules, badminton call, tennis model)
    3 VALUE     sharp market >= 54% our side at PP's number; no market -> model >= 57.7%
    4 FORM      season >= 60% and L10 >= 6/10 our side (badminton: both players' 2026 form agree)
    5 PROJ      rate x expected minutes (TOI) on our side of the line (badminton: similar-match median)
    6 ROLE      minutes stable (unders: not rising 10%+), injury status not Q/DTD/Out
    7 DEFENSE   opponent vs his position not 5%+ against us (NHL: team-level shots allowed factor)
    8 H2H       3+ meetings not against (<40% our side); badminton: a 3-game meeting vetoes an under
    9 CONTEXT   new teammate absence kills unders; back-to-back noted; NBA spread 10+ flags overs
   10 CARD      2-picks, distinct games, one player per card ($15 cap is on the user)
    python _check.py "nba|Gui Santos|Points|7.5|under" "nhl|Anton Frondell|Shots On Goal|2|under"
    python _check.py --scan nba        # every NBA leg with sharp 52%+ -> gates, CLEAN ones first   (also: nhl)
    python _check.py --all             # "run the board": EVERY sport on PP, all gates + add-ons, one table + the slips
"""
import sys, os, json, statistics, collections, datetime, urllib.request
import _stack as S

H = {"User-Agent": "Mozilla/5.0"}
CT = S.CT
DAY = os.environ.get("CHECK_DAY") or datetime.datetime.now(CT).date().isoformat()   # CHECK_DAY=YYYY-MM-DD for tomorrow's board
P, F, NA = "PASS", "FAIL", "N/A"
_cache = {}


def pp_line(sp, player, stat):
    lg = {"nba": 7, "nhl": 8, "bad": 285, "tennis": 5}[sp]
    if lg not in _cache:
        import _ppcache as C
        d = C.projections(lg, 600)
        pl = {i["id"]: i["attributes"] for i in d.get("included", []) if i["type"] == "new_player"}
        _cache[lg] = [(pl.get(x["relationships"]["new_player"]["data"]["id"], {}).get("name", ""), x["attributes"]) for x in d["data"]]
    return [a for n, a in _cache[lg] if S.nn(n) == S.nn(player) and a["stat_type"] == stat]


def injuries():
    if "inj" not in _cache:
        try:
            d = json.load(urllib.request.urlopen(urllib.request.Request("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries", headers=H), timeout=30))
        except Exception:
            d = {}
        st = {}; out = collections.defaultdict(list)
        for t in d.get("injuries", []):
            for i in t.get("injuries", []):
                st[i["athlete"]["displayName"]] = i.get("status") or ""
                if (i.get("status") or "").lower() == "out":
                    out[t.get("abbreviation") or t.get("displayName")].append(i["athlete"]["displayName"])
        _cache["inj"] = (st, out)
    return _cache["inj"]


def market(sp, player, stat, line):
    try:
        X = json.load(open(os.path.join("site", "xcheck.json"), encoding="utf-8"))
    except Exception:
        return None, 0
    for r in X:
        if r.get("sport", "").lower() == sp and r["player"] == player and r["stat"] == stat and r["line"] == line and r.get("basis") == "sharp":
            return (r["p"] if r["side"] == "over" else 1 - r["p"]), r.get("n_sharp") or 0
    return None, 0


def gate_line(sp, player, stat, line, side):
    rows = pp_line(sp, player, stat)
    std = [a for a in rows if a.get("odds_type") == "standard"]
    if not rows:
        return F, "not on the PP board"
    hit = [a for a in rows if float(a["line_score"]) == float(line)]
    if not hit:
        return F, "PP line moved: standard now %s" % ([a["line_score"] for a in std] or "gone")
    hit.sort(key=lambda a: a.get("odds_type") != "standard")            # the standard line first, then goblin/demon
    a = hit[0]; kind = a.get("odds_type"); sides = a.get("allowed_wager_types")
    if sides == "over" and side == "under":
        return F, "%s %g -- UNDER locked (over only)" % (kind, line)
    note = "%s %g%s" % (kind, line, ", whole number = push" if float(line) == int(float(line)) else "")
    return (P if kind == "standard" else F), note + ("" if kind == "standard" else " (not standard)")


def check_team_leg(sp, player, stat, line, side, D):
    """NBA + NHL share the _stack data model."""
    g = {}
    ST = S.stats_for(sp)
    k = S.pkey(sp, player)
    gs = [x for x in D.G.get(k, []) if x["season"] == S.CUR]
    o = side == "over"
    hit = (lambda v: v > line) if o else (lambda v: v < line)
    g[1] = gate_line(sp, player, stat, line, side)
    if stat not in ST or len(gs) < 5:
        for i in range(2, 10):
            g[i] = (NA, "no %s logs" % sp)
        return g, None
    e = ST[stat]; v = [S.val(x["s"], e) for x in gs]; m = [x["min"] or 0 for x in gs]
    team, opp = gs[-1]["team"], None
    if ("board", sp) not in _cache:
        _cache[("board", sp)] = S.board(DAY, sp)                           # parse the PP board once per sport, not once per leg
    b = [r for r in _cache[("board", sp)] if S.nn(r["player"]) == S.nn(player) and r["stat"] == stat]
    if b:
        team, opp = b[0]["team"], b[0]["opp"]
    if sp == "nhl" and opp:                                              # PP codes -> our NHL data codes
        opp = {"TB": "TBL", "LA": "LAK", "NJ": "NJD", "SJ": "SJS", "UTAH": "UTA"}.get(opp, opp)
    mk, ns = market(sp, player, stat, line)
    mk_side = None if mk is None else (mk if o else 1 - mk)
    whole = float(line) == int(float(line))
    dec = [x for x in v if x != line] if whole else v                    # whole-number line: rate over decided games (pushes excluded)
    dec10 = [x for x in v[-10:] if x != line] if whole else v[-10:]
    sea = sum(map(hit, dec)) / max(len(dec), 1); l10 = round(10 * sum(map(hit, dec10)) / max(len(dec10), 1))
    rest = (datetime.date.fromisoformat(DAY) - datetime.date.fromisoformat(gs[-1]["date"][:10])).days
    min_tr = statistics.mean(m[-3:]) / max(statistics.mean(m), 1)
    dv = D.dvp(k, e, opp) if opp else None
    fl = S.first_line(player, stat, DAY, {"nba": 7, "nhl": 8}[sp])          # opening PP line (cloud archive) -> line move feeds the
    move = None if fl is None else line - fl                                # MINUTES FALLING + PP RAISED rule (64%), was always None
    f = dict(line=line, min_tr=min_tr, move=move, rest=rest, med_rel=(statistics.median(v) - line) / max(line, 1), dvp=dv, mkt=mk_side,
             season=sea, l10=l10 / 10)
    rules = [lab.split(":")[0].split("[")[0].strip() for s_, lab, t, pct, test in S.EDGE.get(sp, []) if s_ == side and test(f)]
    g[2] = (P, "; ".join(rules)) if rules else (F, "no measured %s rule fires" % side)
    if mk_side is None:
        g[3] = (NA, "no sharp price at %g yet" % line)
    else:
        g[3] = (P if mk_side >= .54 else F, "sharp %.1f%% %s (%d books)" % (100 * mk_side, side, ns))
    g[4] = (P if sea >= .60 and l10 >= 6 else F, "season %.0f%%, L10 %d/10%s" % (100 * sea, l10, " (pushes excluded: %d of last 10)" % (10 - len(dec10)) if whole else ""))
    rate = sum(v) / max(sum(m), 1); proj = rate * statistics.mean(m[-5:])
    g[5] = (P if (proj > line if o else proj < line) else F, "proj %.2f (%.3f/min x %.1f min) vs %g" % (proj, rate, statistics.mean(m[-5:]), line))
    stt = ""
    if sp == "nba":
        stt = injuries()[0].get(player, "")
    bad_status = stt.lower() in ("out", "day-to-day", "questionable", "doubtful")
    rising = (not o) and min_tr >= 1.10
    g[6] = (F if bad_status or rising else P, "min L3/season %.2f%s%s" % (min_tr, ", rising" if rising else "", (", status " + stt) if stt else ""))
    if dv is None:
        g[7] = (NA, "no defense split")
    else:
        fs = dv if o else -dv
        g[7] = (F if fs <= -.05 else P, "opp vs his type %+.0f%% (%s)" % (100 * dv, "helps" if fs > 0 else "against" if fs <= -.05 else "neutral"))
    h = [hit(S.val(x["s"], e)) for x in D.G.get(k, []) if x.get("opp") == opp and (not whole or S.val(x["s"], e) != line)][-6:] if opp else []
    if len(h) < 3:
        g[8] = (NA, "%d meetings" % len(h))
    else:
        g[8] = (P if sum(h) / len(h) >= .4 else F, "%d/%d %s vs %s" % (sum(h), len(h), side, opp))
    notes = []; ok = True
    if sp == "nba" and not o:
        lastg = max((x["date"] for x in D.G.get(k, [])), default="")
        newabs = [n for n in injuries()[1].get(team, []) if any(x["date"] == lastg for x in D.G.get(S.pkey("nba", n), [])
                                                                  if statistics.mean([y["min"] for y in D.G[S.pkey("nba", n)][-5:]] or [0]) >= 25)]
        if newabs:
            notes.append("NEW absence " + ",".join(newabs)); ok = False
    if rest == 1:
        notes.append("back-to-back")
    if move:
        notes.append("PP moved %+g since open (%s)" % (move, "toward our side" if (move > 0) != o else "against us"))
    g[9] = (P if ok else F, ", ".join(notes) or "nothing flagged")
    return g, tuple(sorted((team or "", opp or "")))              # sorted so MIL-POR == POR-MIL (same game)


def check_badminton(player, opp_name, line, side):
    import _badminton as B
    g = {1: gate_line("bad", player, "Total Points", line, side)}
    M = json.load(open(B.OUT, encoding="utf-8")); rows, R = B.elo_rows(M)
    A = [z.strip() for z in player.split("+")]; Bn = [z.strip() for z in opp_name.split("+")]
    opts = ("MS", "WS") if len(A) == 1 else ("MD", "WD", "XD")
    disc = next((d for d in opts if B.find(R, d, A) and B.find(R, d, Bn)), None)
    if not disc:
        for i in range(2, 10):
            g[i] = (NA, "players not rated (outside World Tour data)")
        return g, None
    N = collections.Counter()
    for r in rows:
        N[(r["disc"], r["a"])] += 1; N[(r["disc"], r["b"])] += 1
    ka = max(B.find(R, disc, A), key=lambda h: N[h[0]]); kb = max(B.find(R, disc, Bn), key=lambda h: N[h[0]])
    pa = 1 / (1 + 10 ** ((kb[1] - ka[1]) / 400)); fv = max(pa, 1 - pa)
    sim = [r for r in rows if r["disc"] == disc and abs(max(r["pa"], 1 - r["pa"]) - fv) <= .05 and r["na"] >= 5 and r["nb"] >= 5]
    o = side == "over"; ps = statistics.mean((r["tot"] > line) == o for r in sim) if sim else 0
    g[2] = (P if ps >= .577 and len(sim) >= 200 else F, "model %s %.0f%% (n=%d, fav %.0f%%)" % (side, 100 * ps, len(sim), 100 * fv))
    g[3] = (NA, "no sharp badminton market") if True else None
    fa = [(r["tot"] > line) == o for r in rows if r["ym"] >= "2026" and ka[0][1] in (r["a"], r["b"]) and r["disc"] == disc]
    fb = [(r["tot"] > line) == o for r in rows if r["ym"] >= "2026" and kb[0][1] in (r["a"], r["b"]) and r["disc"] == disc]
    ok4 = bool(fa and fb) and statistics.mean(fa) >= .5 and statistics.mean(fb) >= .5
    g[4] = (P if ok4 else F, "2026 %s: A %d/%d, B %d/%d" % (side, sum(fa), len(fa), sum(fb), len(fb)))
    med = statistics.median(r["tot"] for r in sim) if sim else None
    g[5] = (NA, "no similar matches") if med is None else (P if (med > line if o else med < line) else F, "similar-match median %.1f vs %g" % (med, line))
    g[6] = (NA, "no minutes/status feed for badminton")
    g[7] = (NA, "no defense split in badminton (opponent strength is in the model)")
    h2 = [r for r in rows if {r["a"], r["b"]} == {ka[0][1], kb[0][1]}]
    three = [r["tot"] for r in h2 if r["three"]]
    if not h2:
        g[8] = (NA, "no meetings")
    elif not o and three:
        g[8] = (F, "3-game meeting(s) %s -> veto the under" % three)
    else:
        g[8] = (P, "meetings %s" % [r["tot"] for r in h2][-4:])
    g[9] = (P if len(sim) >= 200 else F, "sample n=%d" % len(sim))
    return g, (player, opp_name)


def check_tennis(player, stat, line, side):
    g = {1: gate_line("tennis", player, stat, line, side)}
    last = None
    for l in open("tennis_pp_paper.jsonl", encoding="utf-8"):
        if player in l and stat in l:
            r = json.loads(l)
            if r["player"] == player and r["stat"] == stat and float(r["line"]) == float(line):
                last = r
    if not last:
        for i in range(2, 10):
            g[i] = (NA, "not priced (no Pinnacle match)")
        return g, None
    po = last["p"] if last["side"] == "over" else 1 - last["p"]; ps = po if side == "over" else 1 - po
    g[2] = (P if ps >= .55 else F, "model %s %.0f%%" % (side, 100 * ps))
    g[3] = (P if ps >= .577 else F, "model %.0f%% vs 57.7%% b/e (Pinnacle-fitted)" % (100 * ps))
    g[4] = (NA, "no per-player tennis logs")
    g[5] = (NA, "model is the projection")
    g[6] = (NA, "no status feed")
    pw = last.get("pin_win")
    bias = stat == "Fantasy Score" and side == "under" and pw is not None and pw >= .55   # 11/20: Medvedev (67% fav) U22.5 fantasy -> 27. A favourite who wins clears fantasy; never fade a favourite on fantasy
    wta_over = last.get("tour") == "wta" and side == "over" and stat in ("Total Games", "Total Games Won")
    g[7] = (F if bias or wta_over else P, ("fantasy under on a %.0f%% favourite (model biased)" % (100 * pw)) if bias else
            ("WTA games over (model runs high)" if wta_over else "win price %s" % ("%.0f%%" % (100 * pw) if pw is not None else "?")))
    g[8] = (NA, "no tennis h2h feed")
    g[9] = (P, "tour %s" % last.get("tour"))
    return g, (player, last.get("opp"))


CS2_STAT = {"Kills on Maps 1+2": "MAPS 1-2 Kills", "Headshots on Maps 1+2": "MAPS 1-2 Headshots"}


def check_cs2(r):
    """CS2 add-ons: top lowers by model edge at PP's own number; PP line above our model line is a plus; edge > 20% = bug check."""
    g = {}
    st = CS2_STAT.get(r.get("stat"), r.get("stat")); ln = r.get("pp_line")
    if 265 not in _cache:
        import _ppcache as C
        d = C.projections(265, 600)
        pl = {i["id"]: i["attributes"] for i in d.get("included", []) if i["type"] == "new_player"}
        _cache[265] = [(pl.get(x["relationships"]["new_player"]["data"]["id"], {}).get("name", ""), x["attributes"]) for x in d["data"]]
    rows = [a for n, a in _cache[265] if n.lower() == (r.get("player") or "").lower() and a["stat_type"] == st and a.get("odds_type") == "standard"]
    if not rows:
        g[1] = (F, "not on PP now")
    else:
        ln = float(rows[0]["line_score"])
        g[1] = (P if rows[0].get("allowed_wager_types") in (None, "under_or_over") else F, "standard %g" % ln)
    edge = r.get("edge") or 0; mp = r.get("model_p") or 0
    g[2] = (P if r.get("side") == "lower" and edge >= .06 else F, "lower, model edge %+.0f%%" % (100 * edge))
    g[3] = (P if mp >= .577 else F, "model %.0f%% vs 57.7%%" % (100 * mp))
    g[4] = (NA, "form is inside the model")
    mu = r.get("model_mu")
    g[5] = (NA, "no projection") if mu is None or ln is None else (P if mu < ln else F, "proj %.1f vs PP %g" % (mu, ln))
    g[6] = (NA, "no roster/role feed")
    mw = r.get("map_winp")
    g[7] = (NA, "no map-win price") if mw is None else (P if mw <= .55 else F, "team map-win %.0f%%" % (100 * mw))
    g[8] = (NA, "no h2h feed")
    big = edge > .20
    g[9] = (F if big else P, "edge > 20%% = bug check" if big else ("PP line above model line" if ln is not None and r.get("line") is not None and ln > r["line"] else "nothing flagged"))
    return g, (r.get("match_id"), 0)


def line_moves():
    """open -> now for every PP line, from the cloud's hourly archive (lines.db pp: first_seen/last_seen per line value)."""
    import sqlite3
    mv = {}
    try:
        L = sqlite3.connect("lines.db")
        first = {}
        for pl, st, ln, fs, kind in L.execute("select player, stat, line, first_seen, kind from pp where kind='standard' and start >= ?", (DAY,)):
            k = (S.nn(pl), st)
            if k not in first or (fs or "~") < first[k][1]:
                first[k] = (ln, fs or "~")
        mv = {k: v[0] for k, v in first.items()}
    except Exception:
        pass
    return mv


def all_board():
    """'run the board': every PP leg we can price, every sport, all gates -> one table. One sport at a time (PP rate limit)."""
    out = []
    now = datetime.datetime.now(CT)
    for sp in ("nba", "nhl"):
        try:
            D = S.Data(DAY, sp)
        except Exception as e:
            print(sp, "data error", e); continue
        MK = {}
        try:
            for r in json.load(open(os.path.join("site", "xcheck.json"), encoding="utf-8")):
                if r.get("sport", "").lower() == sp and r.get("basis") == "sharp" and r.get("date") == DAY:
                    MK[(r["player"], r["stat"], r["line"])] = r["p"] if r["side"] == "over" else 1 - r["p"]
        except Exception:
            pass
        ST = S.stats_for(sp)
        if ("board", sp) not in _cache:
            _cache[("board", sp)] = S.board(DAY, sp)
        for b in _cache[("board", sp)]:
            if b["stat"] not in ST:
                continue
            po = MK.get((b["player"], b["stat"], b["line"]))
            if po is None:
                k = S.pkey(sp, b["player"]); gs = [x for x in D.G.get(k, []) if x["season"] == S.CUR]
                if len(gs) < 5:
                    continue
                v = [S.val(x["s"], ST[b["stat"]]) for x in gs]
                po = sum(x > b["line"] for x in v) / len(v)
            side = "over" if po >= .5 else "under"
            g, gm = check_team_leg(sp, b["player"], b["stat"], b["line"], side, D)
            out.append((sp, "%s %s %s%g" % (b["player"], b["stat"], side[0].upper(), b["line"]), g, gm, b["player"]))
    try:
        import _badminton as B
        for disc, A, Bn, L, t in B.pp_board():
            g, gm = check_badminton(" + ".join(A), " + ".join(Bn), L, "under")
            out.append(("bad", "%s v %s U%g" % (" + ".join(A), " + ".join(Bn), L), g, gm, " + ".join(A)))
    except Exception as e:
        print("badminton:", e)
    seen = set()
    for l in open("tennis_pp_paper.jsonl", encoding="utf-8"):
        if not l.strip():
            continue
        r = json.loads(l)
        if r["kind"] != "standard":
            continue
        try:
            st = datetime.datetime.fromisoformat(r["start"]).astimezone(CT)
        except Exception:
            continue
        if not (now < st < now + datetime.timedelta(hours=30)) or (r["player"], r["stat"], r["line"]) in seen:
            continue
        seen.add((r["player"], r["stat"], r["line"]))
        try:
            g, gm = check_tennis(r["player"], r["stat"], r["line"], r["side"])
        except RuntimeError as e:                                         # PP cooldown on the tennis league: skip tennis, keep the board
            print("tennis skipped:", e); break
        out.append(("tennis", "%s %s %s%g" % (r["player"], r["stat"], r["side"][0].upper(), r["line"]), g, gm, r["player"]))
    seen = set()
    for l in open("cs2_paper.jsonl", encoding="utf-8"):
        if '"lower"' not in l or '"pp_line": null' in l:
            continue
        r = json.loads(l)
        try:
            st = datetime.datetime.fromisoformat((r.get("start") or "").replace("Z", "+00:00")).astimezone(CT)
        except Exception:
            continue
        k = (r.get("player"), r.get("stat"), r.get("match_id"))
        if not (now < st < now + datetime.timedelta(hours=30)) or k in seen:
            continue
        seen.add(k)
        try:
            g, gm = check_cs2(r)
        except RuntimeError as e:                                         # PP cooldown on CS2: skip CS2, keep the board
            print("cs2 skipped:", e); break
        out.append(("cs2", "%s U%s %s" % (r.get("player"), r.get("pp_line"), (r.get("stat") or "").replace(" on Maps 1+2", "")), g, gm, r.get("player")))
    return out


def _val(g):
    """rank: a sharp-market % counts in full; a model-only % is discounted 8 pts (our models are less proven than the books)"""
    t = g[3][1] if g[3][0] == P else g[2][1]
    try:
        v = float(t.split("%")[0].split()[-1].lstrip("+"))
    except Exception:
        return 0.0
    return v - 8 if "model" in t else v


def run_all():
    rows = all_board()
    locked = set(); card_used = 0
    try:
        for l in open("live_paper.jsonl", encoding="utf-8"):
            r = json.loads(l) if l.strip() else {}
            if r.get("date") == DAY and r.get("kind") == "LIVE":
                if "EXTRA" not in (r.get("system_tag") or "") and "OFF" not in (r.get("system_tag") or ""):
                    card_used += 1
                for x in r.get("legs") or []:
                    locked.add(S.nn(x.get("player")))
    except Exception:
        pass
    must = lambda g: g[2][0] == P and (g[3][0] == P or g[4][0] == P)    # no data is not a pass: rule + (value or form) must actually pass
    clean = [r for r in rows if not any(v[0] == F for v in r[2].values()) and must(r[2])]
    near = [r for r in rows if sum(v[0] == F for v in r[2].values()) == 1]
    print("THE BOARD %s: %d legs checked (%s) -> %d CLEAN, %d one gate short" % (DAY, len(rows),
          ", ".join("%s %d" % (k, v) for k, v in collections.Counter(r[0] for r in rows).items()), len(clean), len(near)))
    print("gates: 1 line 2 rule 3 value 4 form 5 proj 6 role 7 defense 8 h2h 9 context   (ok / X fail / - no data)")
    print("\n%-6s %-48s %s  value" % ("sport", "CLEAN leg", "1  2  3  4  5  6  7  8  9 "))
    for sp, lab, g, gm, pl in sorted(clean, key=lambda r: -_val(r[2])):
        mark = "  [already on a slip]" if S.nn(pl) in locked else ""
        print("%-6s %-48s %s  %s%s" % (sp, lab[:48], " ".join("%-2s" % {P: "ok", F: "X", NA: "-"}[g[i][0]] for i in range(1, 10)),
                                       g[3][1] if g[3][0] == P else g[2][1], mark))
    print("\nONE GATE SHORT (watch list):")
    for sp, lab, g, gm, pl in sorted(near, key=lambda r: -_val(r[2]))[:15]:
        bad = [i for i in g if g[i][0] == F][0]
        print("  %-6s %-48s fails %d: %s" % (sp, lab[:48], bad, g[bad][1]))
    pool = [r for r in sorted(clean, key=lambda r: -_val(r[2])) if S.nn(r[4]) not in locked]
    slips = []; used = set()
    room = max(0, 4 - card_used)
    while len(pool) >= 2:                                                # user 11/19: no 4-slip cap when there's value -- every clean pair
        a = pool.pop(0)
        if S.nn(a[4]) in used:
            continue
        b = next((x for x in pool if S.nn(x[4]) != S.nn(a[4]) and S.nn(x[4]) not in used and (x[3] is None or a[3] is None or x[3] != a[3])), None)
        if not b:
            break
        pool.remove(b); used |= {S.nn(a[4]), S.nn(b[4])}; slips.append((a, b))
    print("\nSLIPS from CLEAN legs (2-picks, distinct games/players, skips anyone already on today's slips; $15 each)")
    print("slips already placed today: %d (no cap on CLEAN slips -- user 11/19; $15 each)" % card_used)
    for i, (a, b) in enumerate(slips, 1):
        print("  %d. [%s] %s  +  [%s] %s" % (i, a[0], a[1], b[0], b[1]))
    if not slips:
        print("  none -- not enough clean legs right now")
    if "--post" in sys.argv:                                             # cloud: AM/PM board to Discord (CARD = allowed by the quiet rule)
        lines = ["**THE BOARD %s** -- %d legs checked, %d clean" % (DAY, len(rows), len(clean))]
        for sp, lab, g, gm, pl in sorted(clean, key=lambda r: -_val(r[2]))[:20]:
            lines.append("- [%s] %s%s" % (sp.upper(), lab, "  (on a slip)" if S.nn(pl) in locked else ""))
        lines.append("")
        lines.append("**Slips ($15, 2-picks):**" if slips else "No new clean pairs.")
        for i, (a, b) in enumerate(slips, 1):
            lines.append("%d. %s  +  %s" % (i, a[1], b[1]))
        try:
            import _notify
            _notify.send("CARD", chr(10).join(lines))
        except Exception as e:
            print("post failed:", e)


def show(label, g):
    fails = [i for i in g if g[i][0] == F]
    print("\n%s  ->  %s" % (label, "CLEAN" if not fails else "FAILS gate " + ",".join(map(str, fails))))
    names = {1: "LINE", 2: "RULE", 3: "VALUE", 4: "FORM", 5: "PROJ", 6: "ROLE", 7: "DEFENSE", 8: "H2H", 9: "CONTEXT"}
    for i in range(1, 10):
        s, note = g.get(i, (NA, ""))
        print("   %d %-8s %-4s  %s" % (i, names[i], s, note))
    return not fails


def main(args):
    if args[:1] == ["--all"]:
        return run_all()
    legs, games, players = [], [], []
    D = {}
    if args[:1] == ["--scan"]:
        sp = args[1]
        X = [r for r in json.load(open(os.path.join("site", "xcheck.json"), encoding="utf-8"))
             if r.get("sport", "").lower() == sp and r.get("basis") == "sharp" and r.get("date") == DAY and r["p"] >= .52]
        args = ["%s|%s|%s|%s|%s" % (sp, r["player"], r["stat"], r["line"], r["side"]) for r in X]
        print("scanning %d %s legs with sharp 52%%+" % (len(args), sp.upper()))
    clean = []
    for a in args:
        sp, player, stat, line, side = a.split("|")
        line = float(line)
        if sp in ("nba", "nhl"):
            D.setdefault(sp, S.Data(DAY, sp))
            g, gm = check_team_leg(sp, player, stat, line, side, D[sp])
        elif sp == "bad":
            g, gm = check_badminton(player, stat, line, side)       # bad|<side A>|<side B>|line|side
        elif sp == "tennis":
            g, gm = check_tennis(player, stat, line, side)
        else:
            print("\n%s: no adapter (cs2/golf/soccer use their own tools)" % a); continue
        ok = show("%s %s %s %g %s" % (sp.upper(), player, stat if sp != "bad" else "v " + stat, line, side.upper()), g)
        if ok:
            clean.append(a)
        legs.append(a); games.append(tuple(sorted(gm)) if gm and None not in gm else None); players.append(player)
    if len(legs) >= 2 and not args[:1] == ["--scan"]:
        dup_p = len(set(players)) < len(players)
        dup_g = len([x for x in games if x]) != len(set(x for x in games if x))
        print("\n10 CARD     %s  (distinct players: %s, distinct games: %s)" % (F if dup_p or dup_g else P, not dup_p, not dup_g))
    if args and clean:
        print("\nCLEAN legs (%d): %s" % (len(clean), " | ".join(clean)))


if __name__ == "__main__":
    main(sys.argv[1:])
