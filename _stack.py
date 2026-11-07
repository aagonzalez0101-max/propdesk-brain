"""STACKED-CHECKS PROP SCREEN, NBA + CBB (11/5, user: "we gotta make one for cbb now" + "4 picks a day in 2 leg parlays").
PP standard lines -> the same 7 STACKED CHECKS that were
measured on real NBA/NHL/NFL/soccer lines 11/5 (project_unified_model_1105.md):

    proj    blended per-minute rate (this season + last, last season weight 8 games) x expected minutes (last 5) x opponent allowed
    season  this-season average vs line (last season if <3 games this year)
    L5      4 of last 5 over / under the line          L10   7 of last 10
    h2h     2+ meetings vs this opponent, 2/3 one side opp   opponent allows +-5% of league avg of the stat (shrunk)
    move    PP moved the line since first posted (lines.db)

RULE (from the other sports, NOT yet backtested in CBB -- no CBB line archive before 11/5): UNDER with 4+ checks agreeing and
0 against = PROBATION leg. OVERS never cleared break-even in any sport at any stack -> listed only as "fade/skip" info.
CBB-specific flags: TRANSFER (his games last season were for another team) and EARLY (fewer than 3 games this season).

    python _stack.py cbb|nba [YYYY-MM-DD]        # default today CT
    python _stack.py card cbb|nba|all [YYYY-MM-DD]   # top 4 qualifiers -> POTD + two 2-pick slips

Measured 11/5 (real closing PP lines): UNDER 4+ agree NBA 58.8% (n=250), NHL 62.3% (77), NFL 57.4% (61); overs 41-49% everywhere.
"""
import sys, os, re, json, math, sqlite3, datetime, unicodedata, statistics, collections
import _ppcache as C

CT = __import__("zoneinfo").ZoneInfo("America/Chicago")
nn = lambda s: re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())
STATS = {"Points": "pts", "Rebounds": "reb", "Assists": "ast", "Pts+Rebs+Asts": "pts+reb+ast", "Pts+Rebs": "pts+reb", "Pts+Asts": "pts+ast",
         "Rebs+Asts": "reb+ast", "3-PT Made": "tpm", "Blocked Shots": "blk", "Steals": "stl", "Blks+Stls": "blk+stl", "Turnovers": "tov",
         "FG Made": "fgm", "FG Attempted": "fga", "Free Throws Made": "ftm", "Offensive Rebounds": "oreb", "Defensive Rebounds": "dreb",
         "Fantasy Score": "pts+1.2*reb+1.5*ast+3*blk+3*stl-tov"}
COLS = ["pts", "reb", "ast", "tpm", "blk", "stl", "tov", "fgm", "fga", "ftm", "oreb", "dreb"]
NHL_STATS = {"Shots On Goal": "sog", "Points": "points", "Assists": "assists", "Goals": "goals", "Hits": "hits", "Blocked Shots": "blocks"}
NHL_COLS = ["sog", "points", "assists", "goals", "hits", "blocks"]
stats_for = lambda sp: NHL_STATS if sp == "nhl" else STATS
CUR = "2026-27"
# 11/6 user: "why cant we ever just mix always" -> every measured rule, BOTH sides, one table. (side, stats or None=all, min agree, label, tier)
# tier 0 = measured on real closing PP lines 10/1-11/4 (stack_bt.py), 1 = small-n measured, 2 = probation (not measured in this sport)
RULES = {"nba": [("under", None, 4, "NBA under 4+ 58.8% n=250", 0)],
         "nhl": [("under", None, 4, "NHL under 4+ 62.3% n=77 (SOG U 69.6% n=46)", 0),
                 ("over", {"Points"}, 4, "NHL POINTS OVER 4+ 63.6% n=33", 1)],
         "cbb": [("under", None, 4, "CBB PROBATION (stack 4-16 on 11/5 -- early season, last-season data)", 2)]}
CFG = {"cbb": dict(league=20, box="cbb_box", games="cbb_games", where="", team={}),
       "nhl": dict(league=8, box=None, games=None, where="", team={}),
       "nba": dict(league=7, box="nba_box", games="nba_games", where=" and g.stype='regular'",
                   team={"NYK": "NY", "GSW": "GS", "SAS": "SA", "NOP": "NO", "UTA": "UTAH", "WAS": "WSH"})}
val = lambda row, e: eval(e, {}, row)


def pkey(sp, name):
    """NHL rows store "S. Colangelo"; PP sends "Sam Colangelo" -> first initial + last name. Other sports: full name."""
    if sp != "nhl" or not name:
        return nn(name)
    if ". " in name:
        a, b = name.split(". ", 1)
    else:
        w = name.split(); a, b = w[0], " ".join(w[1:])
    return a[:1].lower() + nn(b)


def board(day, sp):
    cf = CFG[sp]; T = lambda x: cf["team"].get(x, x)
    d = C.projections(cf["league"], 300)
    P = {i["id"]: i["attributes"] for i in d.get("included", []) if i["type"] == "new_player"}
    out = []
    for x in d["data"]:
        a = x["attributes"]
        if a.get("odds_type") != "standard" or a.get("is_promo") or a["stat_type"] not in stats_for(sp):
            continue
        if datetime.datetime.fromisoformat(a["start_time"]).astimezone(CT).date().isoformat() != day:
            continue
        p = P.get(x["relationships"]["new_player"]["data"]["id"], {})
        out.append(dict(sport=sp, player=p.get("name"), team=T(p.get("team")), opp=T((a.get("description") or "").split()[0]) if a.get("description") else None,
                        stat=a["stat_type"], line=float(a["line_score"]), start=a["start_time"]))
    return out


def first_line(player, stat, day, league):
    try:
        L = sqlite3.connect("lines.db", timeout=30)
        r = L.execute("select line from pp where league=? and kind='standard' and player=? and stat=? and substr(start,1,10)=? order by first_seen limit 1",
                      (league, player, stat, day)).fetchone()
        return r[0] if r else None
    except Exception:
        return None


class Data:
    def __init__(self, before, sp):
        cf = CFG[sp]; self.sp = sp
        c = sqlite3.connect("sports.db", timeout=60)
        self.G = collections.defaultdict(list)
        tot = collections.defaultdict(lambda: collections.defaultdict(float))
        if sp == "nhl":
            for gid, d, tm, opp, pl, mn, st in c.execute("select game_id,date,team,opp,player,minutes,stats from player_games where sport='NHL' and date>='2025-10-01' and date<? order by date", (before,)):
                j = json.loads(st)
                if j.get("gtype") != "reg" or not mn:
                    continue
                season = CUR if d >= "2026-09-01" else "2025-26"
                s = {k: float(j.get(k) or 0) for k in NHL_COLS}
                self.G[pkey(sp, pl)].append(dict(date=d, team=tm, opp=opp, min=mn, season=season, s=s))
                for k, v in s.items():
                    tot[(gid, opp, season)][k] += v
            self.OPP = collections.defaultdict(list)
            for (gid, opp, season), t in tot.items():
                self.OPP[(opp, season)].append(t)
            return
        for r in c.execute("select b.game_id,b.date,b.team,b.opp,b.player,b.min,g.season," + ",".join("b." + k for k in COLS) +
                           " from %s b join %s g on g.game_id=b.game_id where (b.dnp is null or b.dnp='' or b.dnp='0') and b.min>0 and b.date<?%s order by b.date" % (cf["box"], cf["games"], cf["where"]), (before,)):
            gid, d, tm, opp, pl, mn, season = r[:7]; s = dict(zip(COLS, [x or 0 for x in r[7:]]))
            self.G[nn(pl)].append(dict(date=d, team=tm, opp=opp, min=mn, season=season, s=s))
            for k, v in s.items():
                tot[(gid, opp, season)][k] += v
        self.OPP = collections.defaultdict(list)
        for (gid, opp, season), t in tot.items():
            self.OPP[(opp, season)].append(t)

    def opp_factor(self, expr, opp):
        for season, k in ((CUR, 4.0), ("2025-26", 12.0)):        # this season if it has games, else last season (rosters change: half weight)
            me = [val(t, expr) for t in self.OPP.get((opp, season), [])]
            lg = [val(t, expr) for (o, s), x in self.OPP.items() if s == season for t in x]
            if len(me) >= 2 and lg and statistics.mean(lg) > 0:
                w = len(me) / (len(me) + k) * (1.0 if season == CUR else 0.5)
                return w * (statistics.mean(me) / statistics.mean(lg) - 1)
        return 0.0


def check(D, leg, day):
    games = D.G.get(pkey(leg["sport"], leg["player"]))
    if not games:
        return None
    e = stats_for(leg["sport"])[leg["stat"]]; ln = leg["line"]
    mmin = 8 if leg["sport"] == "nhl" else 10
    cur = [g for g in games if g["season"] == CUR]; prev = [g for g in games if g["season"] == "2025-26" and g["min"] >= mmin]
    early = len(cur) < 3
    base_g = cur if not early else (prev + cur)
    if len(base_g) < 3:
        return None
    rate = lambda gs: sum(val(g["s"], e) for g in gs) / max(1e-9, sum(g["min"] for g in gs))
    r = rate(cur) if cur and not prev else rate(prev) if not cur else (len(cur) * rate(cur) + 8 * rate(prev)) / (len(cur) + 8)
    exp_min = statistics.mean(g["min"] for g in base_g[-5:])
    of = D.opp_factor(e, leg["opp"])
    mu = r * exp_min * (1 + of)
    vals = [val(g["s"], e) for g in (prev[-15:] + cur)[-20:]]
    sd = max(statistics.pstdev(vals) if len(vals) > 1 else 0, math.sqrt(max(mu, .25)) * .8)
    seq = [val(g["s"], e) for g in base_g]
    v = {}
    z = (mu - ln) / sd; zc = (statistics.mean(seq) - ln) / sd
    v["proj"] = 1 if z > .3 else -1 if z < -.3 else 0
    v["season"] = 1 if zc > .3 else -1 if zc < -.3 else 0
    l5, l10 = seq[-5:], seq[-10:]
    v["L5"] = (1 if sum(x > ln for x in l5) >= 4 else -1 if sum(x < ln for x in l5) >= 4 else 0) if len(l5) >= 5 else 0
    v["L10"] = (1 if sum(x > ln for x in l10) >= .7 * len(l10) else -1 if sum(x < ln for x in l10) >= .7 * len(l10) else 0) if len(l10) >= 7 else 0
    hh = [val(g["s"], e) for g in games if g["opp"] == leg["opp"]]
    v["h2h"] = (1 if sum(x > ln for x in hh) >= 2 / 3 * len(hh) else -1 if sum(x < ln for x in hh) >= 2 / 3 * len(hh) else 0) if len(hh) >= 2 else 0
    v["opp"] = 1 if of > .05 else -1 if of < -.05 else 0
    fl = first_line(leg["player"], leg["stat"], leg["start"][:10], CFG[leg["sport"]]["league"])
    v["move"] = 0 if fl is None or fl == ln else (1 if ln > fl else -1)
    po = list(v.values()).count(1); pu = list(v.values()).count(-1)
    # 11/7: RISING MINUTES (Burries 16->26 min, then 38 min / 27 P+A on 11/6): last 2 games 20%+ and 4+ min above his season average
    rising = False
    if len(cur) >= 4:
        smin = statistics.mean(g["min"] for g in cur[:-2]); l2 = statistics.mean(g["min"] for g in cur[-2:])
        rising = l2 >= 1.2 * smin and l2 - smin >= 4
    transfer = bool(prev and cur and prev[-1]["team"] != cur[-1]["team"]) or bool(prev and not cur and leg["team"] and prev[-1]["team"] != leg["team"])
    return dict(leg, mu=mu, z=z, v=v, po=po, pu=pu, n_cur=len(cur), early=early, transfer=transfer, rising=rising,
                l5=seq[-5:], mins=exp_min, of=of)


def nba_totals(day):
    """11/7: pregame game total per team (ESPN scoreboard odds). NBA under 4+: total <=222.5 63.3% vs >=226.5 54.2% (n=250) -> FLAG."""
    try:
        import urllib.request
        d = json.load(urllib.request.urlopen(urllib.request.Request(
            "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=" + day.replace("-", ""), headers={"User-Agent": "Mozilla/5.0"}), timeout=30))
        out = {}
        for e in d.get("events", []):
            c = e["competitions"][0]; o = (c.get("odds") or [{}])[0]
            for t in c["competitors"]:
                out[t["team"]["abbreviation"]] = o.get("overUnder")
        return out
    except Exception:
        return {}


def screen(day, sp):
    legs = board(day, sp)
    D = Data(day, sp)
    rows = [r for r in (check(D, l, day) for l in legs) if r]
    print("%s %s: %d PP standard lines, %d with logs" % (sp.upper(), day, len(legs), len(rows)))
    TOT = nba_totals(day) if sp == "nba" else {}
    for r in rows:
        r["total"] = TOT.get(r["team"])
    q = []
    for side, stats, k, label, tier in RULES[sp]:
        hit = [dict(r, side=side, k=r["pu"] if side == "under" else r["po"], rule=label, tier=tier + (1 if r["early"] and tier < 2 else 0))
               for r in rows if (stats is None or r["stat"] in stats) and
               ((side == "under" and r["pu"] >= k and r["po"] == 0) or (side == "over" and r["po"] >= k and r["pu"] == 0))]
        hit.sort(key=lambda r: (-r["k"], r["z"] if side == "under" else -r["z"]))
        print("\n%s -- %s %d+ checks agree, 0 against  [%s]" % ("QUALIFIERS" if tier < 2 else "PROBATION", side.upper(), k, label))
        for r in hit:
            print("  %-22s %-5s vs %-5s %s%-5g %-14s proj %5.1f | %d agree [%s] | L5 %s | min %.0f%s%s" % (
                r["player"][:22], r["team"], r["opp"], side[0].upper(), r["line"], r["stat"], r["mu"], r["k"],
                ",".join(c_ for c_, x in r["v"].items() if x == (-1 if side == "under" else 1)),
                "/".join("%g" % x for x in r["l5"]), r["mins"], " EARLY(%d gm)" % r["n_cur"] if r["early"] else "", " TRANSFER" if r["transfer"] else "")
                + (" | total %g%s" % (r["total"], " HIGH" if r["total"] >= 226.5 else " low" if r["total"] <= 222.5 else "") if r.get("total") else "")
                + (" | RISING MIN -> bench" if r["rising"] else ""))
        if not hit:
            print("  none")
        q += hit
    ruled = {(r["player"], r["stat"]) for r in q}
    fade = [r for r in rows if r["po"] >= 4 and r["pu"] == 0 and (r["player"], r["stat"]) not in ruled]
    if fade:
        print("\nALL-CHECKS-SAY-OVER with no measured over rule (overs 41-49 pct at every stack) -- skip%s:" % (
            "; NHL SOG overs 4+ went 14-27 = FADE" if sp == "nhl" else ""))
        for r in sorted(fade, key=lambda r: -r["po"])[:8]:
            print("  %-22s O%-5g %-14s proj %5.1f | %d agree" % (r["player"][:22], r["line"], r["stat"], r["mu"], r["po"]))
    return q


def card(day, sports, n_slips=2):
    """11/6 MIXED card: every sport's measured rules, both sides, ranked by tier then agreement. At most 2 legs per sport unless no
    other sport has a qualifier; one leg per player; a slip never pairs two legs from the same game."""
    q = []
    for sp in sports:
        try:
            q += screen(day, sp)
        except Exception as e:
            print("%s screen failed: %s" % (sp.upper(), e))
        print()
    bench = [r for r in q if r["rising"]]
    if bench:
        print("BENCHED (rising minutes): " + ", ".join("%s %s%g %s" % (r["player"], r["side"][0].upper(), r["line"], r["stat"]) for r in bench))
    q = [r for r in q if not r["transfer"] and not r["rising"]]
    q.sort(key=lambda r: (r["tier"], -r["k"], -abs(r["z"])))
    need = 2 * n_slips
    used, per, pick = set(), collections.Counter(), []
    for cap in (2, need):
        for r in q:
            if len(pick) == need:
                break
            if pkey(r["sport"], r["player"]) in used or per[r["sport"]] >= cap:
                continue
            used.add(pkey(r["sport"], r["player"])); per[r["sport"]] += 1; pick.append(r)
    slips, rest = [], pick[:]
    while len(rest) >= 2:
        a = rest.pop(0)
        b = next((x for x in rest if {x["team"], x["opp"]} != {a["team"], a["opp"]}), rest[0])
        rest.remove(b); slips.append((a, b))
    fmt = lambda r: "[%s] %s %s%g %s (tier %d%s)" % (r["sport"].upper(), r["player"], r["side"][0].upper(), r["line"], r["stat"], r["tier"],
                                                   ", total %g" % r["total"] if r.get("total") else "")
    print("\nMIXED CARD (tier 0 = measured, 1 = small-n / early, 2 = probation; max 2 legs per sport when others qualify):")
    if pick:
        print("  POTD: " + fmt(pick[0]))
    for i, (a, b) in enumerate(slips):
        print("  Slip %d: %s  +  %s" % (i + 1, fmt(a), fmt(b)))
    return pick


def grade(days, sp, lines_db=None):
    """11/6 user: "move the nba stat process into cbb right away so we know". Every archived CLOSING PP standard line on each day ->
    the 7 checks AS-OF that day -> graded vs the box. Appends to stack_grades.jsonl (one row per line, re-runs dedupe) and prints the
    record by stack. Needs a CURRENT lines.db (laptop copy is stale: extract the cloud bundle's and pass LINES_DB=<path>)."""
    lines_db = lines_db or os.environ.get("LINES_DB", "lines.db")
    L = sqlite3.connect(lines_db, timeout=30); c = sqlite3.connect("sports.db", timeout=60); cf = CFG[sp]
    done = set()
    if os.path.exists("stack_grades.jsonl"):
        for l in open("stack_grades.jsonl", encoding="utf-8"):
            r = json.loads(l); done.add((r["sport"], r["date"], nn(r["player"]), r["stat"]))
    new = []
    for day in days:
        close = {}
        for pl, team, st, line, start, seen in L.execute("select player, team, stat, line, start, last_seen from pp where league=? and kind='standard'", (cf["league"],)):
            if st not in STATS or not pl or datetime.datetime.fromisoformat(start).astimezone(CT).date().isoformat() != day:
                continue
            k = (nn(pl), st)
            if k not in close or (seen or "") > close[k][1]:
                close[k] = (line, seen or "", pl, team, start)
        box = {}
        for row in c.execute("select b.player, b.team, b.opp, " + ",".join("b." + k for k in COLS) + " from %s b where b.date=? and b.min>0" % cf["box"], (day,)):
            box[nn(row[0])] = (row[1], row[2], dict(zip(COLS, [x or 0 for x in row[3:]])))
        D = Data(day, sp)
        global first_line
        _fl = first_line
        first_line = lambda player, stat, d, league: (lambda r: r[0] if r else None)(L.execute(
            "select line from pp where league=? and kind='standard' and player=? and stat=? and substr(start,1,10)=? order by first_seen limit 1",
            (league, player, stat, d)).fetchone())
        for (k, st), (line, _, pl, team, start) in close.items():
            if k not in box or (sp, day, k, st) in done:
                continue
            tm, opp, s = box[k]; act = val(s, STATS[st])
            if act == line:
                continue
            r = check(D, dict(sport=sp, player=pl, team=cf["team"].get(team, team), opp=opp, stat=st, line=line, start=start), day)
            if not r:
                continue
            new.append(dict(sport=sp, date=day, player=pl, stat=st, line=line, act=act, over=int(act > line), po=r["po"], pu=r["pu"],
                            v=r["v"], z=round(r["z"], 3), early=r["early"], transfer=r["transfer"], n_cur=r["n_cur"]))
        first_line = _fl
    with open("stack_grades.jsonl", "a", encoding="utf-8") as f:
        for r in new:
            f.write(json.dumps(r) + "\n")
    allr = [json.loads(l) for l in open("stack_grades.jsonl", encoding="utf-8")]
    allr = [r for r in allr if r["sport"] == sp]
    print("%s graded lines: %d new, %d total (%s)" % (sp.upper(), len(new), len(allr), ", ".join(sorted(set(r["date"] for r in allr)))))
    def rep(lab, X):
        if X:
            w = sum(X); n = len(X); print("  %-38s %4d-%-4d %5.1f%%" % (lab, w, n - w, 100 * w / n))
        else:
            print("  %-38s   --" % lab)
    rep("ALL UNDERS (base)", [1 - r["over"] for r in allr])
    for k_ in (3, 4, 5):
        rep("UNDER %d+ agree, 0 against" % k_, [1 - r["over"] for r in allr if r["pu"] >= k_ and r["po"] == 0])
        rep("OVER  %d+ agree, 0 against" % k_, [r["over"] for r in allr if r["po"] >= k_ and r["pu"] == 0])
    rep("UNDER 4+ & NOT early (3+ games this yr)", [1 - r["over"] for r in allr if r["pu"] >= 4 and r["po"] == 0 and not r["early"]])
    print("  each check alone:")
    for ck in ("proj", "season", "L5", "L10", "h2h", "opp", "move"):
        rep("    %-7s says UNDER" % ck, [1 - r["over"] for r in allr if r["v"][ck] == -1])
        rep("    %-7s says OVER" % ck, [r["over"] for r in allr if r["v"][ck] == 1])


if __name__ == "__main__":
    a = sys.argv[1:]
    day = next((x for x in a if re.match(r"\d{4}-\d\d-\d\d", x)), datetime.datetime.now(CT).date().isoformat())
    sp = next((x for x in a if x in ("cbb", "nba", "nhl", "all")), "cbb")
    if a[:1] == ["grade"]:                    # python _stack.py grade cbb 2026-11-05 [2026-11-06 ...]   (LINES_DB=<current lines.db>)
        grade([x for x in a if re.match(r"\d{4}-\d\d-\d\d", x)] or [day], sp)
    elif a[:1] == ["card"]:
        card(day, ["nba", "nhl", "cbb"] if sp == "all" else [sp])
    else:
        screen(day, sp)
