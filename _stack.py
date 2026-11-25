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
         "Fantasy Score": "pts+1.2*reb+1.5*ast+3*blk+3*stl-tov",
         # 11/24 user: "add all these little picks ... large volume to choose from" -- every PP NBA stat the box score can grade
         "3-PT Attempted": "tpa", "Two Pointers Attempted": "fga-tpa", "Two Pointers Made": "fgm-tpm", "Free Throws Attempted": "fta",
         "Personal Fouls": "pf"}
COLS = ["pts", "reb", "ast", "tpm", "blk", "stl", "tov", "fgm", "fga", "ftm", "oreb", "dreb", "tpa", "fta", "pf"]
NHL_STATS = {"Shots On Goal": "sog", "Points": "points", "Assists": "assists", "Goals": "goals", "Hits": "hits", "Blocked Shots": "blocks"}
NHL_COLS = ["sog", "points", "assists", "goals", "hits", "blocks"]
stats_for = lambda sp: NHL_STATS if sp == "nhl" else STATS
CUR = "2026-27"
# 11/15 user ("why wasnt defense a part of the check" -> "add all 3"): the team-level opp check cancels out by position (POR soft vs C,
# tough vs F -> reads 0) and never fires. OPP_MODE=pos = defense vs the player's TYPE (NBA G/F/C by per-36 reb/ast, NHL shooter/non-shooter),
# what that type actually did vs this defense / their own season rate, per stat; +-8% = a vote, so a defense clearly against the side BLOCKS it.
OPP_MODE = os.environ.get("OPP_MODE", "auto")   # auto = pos for NBA, team for NHL/CBB (_opp_bt.py 11/15, see below)
# _opp_bt.py 11/15 on archived closing lines: NBA pos opp says UNDER 185-119 60.9% (team 56.9%); UNDER 4+ 151-128 54.1% vs 139-123 53.1%,
# blocked 6-7, added 18-12. NHL: pos WORSE (under 4+ 60.7 vs 61.7, its blocks hit 82.6%; points over 47.9 vs 52.2) -> NHL keeps team.
# 11/6 user: "why cant we ever just mix always" -> every measured rule, BOTH sides, one table. (side, stats or None=all, min agree, label, tier)
# tier 0 = measured on real closing PP lines 10/1-11/4 (stack_bt.py), 1 = small-n measured, 2 = probation (not measured in this sport)
RULES = {"nba": [],      # 11/16: "NBA under 4+" RETIRED -- full cloud data 145-159 47.7% (n=304, _edge_research.py); EDGE rules below
         "nhl": [],      # 11/16: NHL under 4+ 55.8% and points over 4+ 52% on full data -> retired; EDGE rules below
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


_FL = {}


def first_line(player, stat, day, league):
    """opening PP line for this player/stat/day. 11/16: one query per (league, day), cached -- the per-leg query full-scanned the
    260 MB cloud lines.db and timed the card out."""
    if (league, day) not in _FL:
        d = {}
        try:
            L = sqlite3.connect("lines.db", timeout=30)
            for pl, st, ln, fs in L.execute("select player, stat, line, first_seen from pp where league=? and kind='standard' and start like ?",
                                            (league, day + "%")):
                if (pl, st) not in d or (fs or "") < d[(pl, st)][0]:
                    d[(pl, st)] = (fs or "", ln)
        except Exception:
            pass
        _FL[(league, day)] = {k: v[1] for k, v in d.items()}
    return _FL[(league, day)].get((player, stat))


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

    def dvp(self, key, expr, opp):
        """position-aware defense factor (actual / expected - 1) for this player's type vs `opp`, current season, as-of `before`."""
        if getattr(self, "_A", None) is None:
            cols = NHL_COLS if self.sp == "nhl" else COLS
            mmin = 8 if self.sp == "nhl" else 10
            self._A = collections.defaultdict(lambda: [0.0, 0.0]); self._arch = {}; self._ng = collections.defaultdict(set)
            for p, gs in self.G.items():
                gs = [g for g in gs if g["season"] == CUR and g["min"] >= mmin]
                if len(gs) < 3:
                    continue
                M = sum(g["min"] for g in gs); r = {c: sum(g["s"].get(c, 0) for g in gs) / M for c in cols}
                if self.sp == "nhl":
                    a_ = "S" if sum(g["s"].get("sog", 0) for g in gs) / len(gs) >= 2.0 else "N"
                else:
                    a_ = "C" if r["reb"] * 36 >= 9.5 else ("G" if r["ast"] * 36 >= 5 else "F")
                self._arch[p] = a_
                for g in gs:
                    self._ng[g["opp"]].add(g["date"])
                    for c in cols:
                        x = self._A[(g["opp"], a_, c)]; x[0] += g["s"].get(c, 0); x[1] += r[c] * g["min"]
        a_ = self._arch.get(key)
        if not a_ or len(self._ng.get(opp, ())) < 4:
            return None
        cs = [t for t in re.findall(r"[a-z_]+", expr) if t in (NHL_COLS if self.sp == "nhl" else COLS)]
        act = sum(self._A[(opp, a_, c)][0] for c in cs); exp = sum(self._A[(opp, a_, c)][1] for c in cs)
        if exp <= 0:
            return None
        n = len(self._ng[opp])
        return (act / exp - 1) * n / (n + 3)

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
    mode = OPP_MODE if OPP_MODE != "auto" else ("pos" if leg["sport"] == "nba" else "team")
    of_pos = D.dvp(pkey(leg["sport"], leg["player"]), e, leg["opp"]) if mode == "pos" else None
    if mode == "pos":
        v["opp"] = 0 if of_pos is None else (1 if of_pos > .08 else -1 if of_pos < -.08 else 0)
    else:
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
                l5=seq[-5:], mins=exp_min, of=of, of_pos=of_pos)


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


# ---- 11/16 EDGE RULES (user: "yes do that but i want the overs to work too so we have more bets"). _edge_research.py, walk-forward on
# REALISTIC legs (NBA pts/reb/ast/combos/3PM 20+ min, NHL SOG/pts/ast 14+ min, 5+ games), full cloud lines.db 10/29-11/14: found on the
# first half of the days, held on the second half. Tier 0 = n>=100 and both halves >= 59%; tier 1 = held but thinner. None is proven at
# p<.05 vs the 57.7% break-even yet -- re-run _edge_research.py every 2 weeks. Each rule: (side, label, tier, measured %, test on features f).
REAL = {"nba": {"Points", "Rebounds", "Assists", "Pts+Rebs+Asts", "Pts+Rebs", "Pts+Asts", "Rebs+Asts", "3-PT Made"},
        "nhl": {"Shots On Goal", "Points", "Assists"}}
EDGE = {"nba": [
    ("over", "SOFT D + BIG LINE: defense 8%+ soft vs his type, line 20.5+  [NBA 102-65 61.1%, halves 63.1/59.0]", 0, 61,
     lambda f: f["dvp"] is not None and f["dvp"] >= .08 and f["line"] >= 20.5),
    ("over", "MARKET 55%+ OVER (sharp books)  [NBA 54-34 61.4%, halves 67.6/56.9]", 1, 61,
     lambda f: f["mkt"] is not None and f["mkt"] >= .55),
    ("over", "HOT + MINUTES FALLING: season 70%+ & L10 70%+ over, last-3 min <= 90% of season  [NBA 59-40 59.6%, halves 60.7/59.2]", 1, 60,
     lambda f: f["season"] >= .7 and f["l10"] >= .7 and f["min_tr"] <= .9),
    ("under", "MINUTES FALLING + PP RAISED THE LINE  [NBA 95-53 64.2%, halves 63.0/64.5]", 0, 64,
     lambda f: f["min_tr"] <= .9 and f["move"] is not None and f["move"] > 0),
    ("under", "TOUGH D + BACK-TO-BACK: defense 8%+ tough vs his type, played yesterday  [NBA 79-47 62.7%, halves 66.7/59.4]", 0, 63,
     lambda f: f["dvp"] is not None and f["dvp"] <= -.08 and f["rest"] == 1),
    ("under", "MARKET 55%+ UNDER (sharp books)  [NBA 110-79 58.2%, halves 60.2/56.4]", 1, 58,
     lambda f: f["mkt"] is not None and f["mkt"] >= .55)],
    "nhl": [
    ("under", "MARKET 55%+ & MEDIAN 15%+ BELOW THE LINE  [NHL 127-78 62.0%, halves 64.4/59.6]", 0, 62,
     lambda f: f["mkt"] is not None and f["mkt"] >= .55 and f["med_rel"] <= -.15),
    ("under", "BACK-TO-BACK & MARKET 52%+ UNDER  [NHL 63-39 61.8%, halves 65.0/59.7]", 0, 62,
     lambda f: f["mkt"] is not None and f["mkt"] >= .52 and f["rest"] == 1),
    ("under", "SEASON 60%+ UNDER & MARKET 55%+  [NHL 108-68 61.4%, halves 63.3/59.3]", 0, 61,
     lambda f: f["mkt"] is not None and f["mkt"] >= .55 and f["season"] >= .6)]}


def _market(day, sp):
    """sharp-book P(over) at PP's exact line from today's _xcheck.py run (site/xcheck.json); stale or missing file -> no market rules."""
    try:
        X = json.load(open(os.path.join("site", "xcheck.json"), encoding="utf-8"))
    except Exception:
        return {}
    return {(r["player"], r["stat"], r["line"]): (r["p"] if r["side"] == "over" else 1 - r["p"]) for r in X
            if r.get("sport", "").lower() == sp and r.get("basis") == "sharp" and r.get("date", day) == day}


def edge_rules(day, sp, D, rows):
    MK = _market(day, sp)
    mmin = 14 if sp == "nhl" else 20
    out, seen = [], {}
    for r in rows:
        if r["stat"] not in REAL.get(sp, ()):
            continue
        key = pkey(sp, r["player"])
        gs = [g for g in D.G.get(key, []) if g["season"] == CUR]
        if len(gs) < 5:
            continue
        m = [g["min"] for g in gs]
        if statistics.mean(m[-5:]) < mmin:
            continue
        e = stats_for(sp)[r["stat"]]; ln = r["line"]; v = [val(g["s"], e) for g in gs]
        fl = first_line(r["player"], r["stat"], r["start"][:10], CFG[sp]["league"])
        dv = r.get("of_pos")
        if dv is None and sp == "nba":
            dv = D.dvp(key, e, r["opp"])
        po = MK.get((r["player"], r["stat"], ln))
        base = dict(line=ln, min_tr=statistics.mean(m[-3:]) / statistics.mean(m), move=None if fl is None else ln - fl,
                    rest=(datetime.date.fromisoformat(day) - datetime.date.fromisoformat(gs[-1]["date"][:10])).days,
                    med_rel=(statistics.median(v) - ln) / max(ln, 1))
        for side, label, tier, pct, test in EDGE.get(sp, []):
            o = side == "over"
            f = dict(base, dvp=dv, mkt=None if po is None else (po if o else 1 - po),
                     season=sum((x > ln) if o else (x < ln) for x in v) / len(v),
                     l10=sum((x > ln) if o else (x < ln) for x in v[-10:]) / len(v[-10:]))
            if test(f) and not (f["mkt"] is not None and f["mkt"] < .48):   # 11/16: market against the side blocks (36-48% at every stats level)
                k = (r["player"], r["stat"])
                if k in seen and seen[k]["side"] != side:
                    seen[k]["conflict"] = True; continue
                if k in seen:
                    continue
                seen[k] = dict(r, side=side, k=pct, rule=label, tier=tier, f=f, conflict=False)
    for h in seen.values():
        if not h["conflict"]:
            out.append(h)
    for side, label, tier, pct, test in EDGE.get(sp, []):
        hit = sorted([h for h in out if h["rule"] == label], key=lambda h: -(h["f"]["mkt"] or 0))
        print("\nEDGE %s (tier %d) -- %s" % (side.upper(), tier, label))
        for h in hit:
            f = h["f"]
            print("  %-22s %-5s vs %-5s %s%-5g %-14s | season %.0f%% L10 %.0f%% | def %s | min L3/season %.2f | rest %d | PP move %s | mkt %s | L5 %s" % (
                h["player"][:22], h["team"], h["opp"], side[0].upper(), h["line"], h["stat"], 100 * f["season"], 100 * f["l10"],
                "%+.0f%%" % (100 * f["dvp"]) if f["dvp"] is not None else "-", f["min_tr"], f["rest"],
                "%+g" % f["move"] if f["move"] is not None else "-", "%.1f%%" % (100 * f["mkt"]) if f["mkt"] is not None else "-",
                "/".join("%g" % x for x in h["l5"])))
        if not hit:
            print("  none")
    if not MK:
        print("\n  (no same-day site/xcheck.json -- run `python _xcheck.py %s` first or the MARKET rules cannot fire)" % sp.upper())
    return out


def screen(day, sp):
    legs = board(day, sp)
    D = Data(day, sp)
    rows = [r for r in (check(D, l, day) for l in legs) if r]
    print("%s %s: %d PP standard lines, %d with logs" % (sp.upper(), day, len(legs), len(rows)))
    # 11/12: the NBA box table was 1-2 games behind (Risacher's 2-reb game missing) and NHL 6 days behind -> every L5 was stale.
    thru = max((g["date"] for gs in D.G.values() for g in gs), default="")
    behind = (datetime.date.fromisoformat(day) - datetime.date.fromisoformat(thru[:10])).days if thru else 99
    print("DATA THROUGH %s (%d days before %s)%s" % (thru[:10], behind, day,
          "  *** STALE -- run `python _laptop_nightly.py` (NBA) / `python _db.py update` (NHL) before using any L5 ***" if behind > 2 else ""))
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
    q += edge_rules(day, sp, D, rows)
    # 11/9 (user: "add it to yours"): two MATCHUP rules, measured on cloud closing lines (scratchpad over_top.py / margin.py), tier 1 = lead.
    #  CORE OVER: last 5 ALL over + season over + h2h over + defense NOT tough, ranked by L5 margin; take top 2.
    #    NBA CORE 57.0% (149), tough defense 5-7; not tough 58.4% (137), not early 73.5% (34); top-1/day by margin 10-2, #2 7-3 (12 days).
    #  BIG-MISS UNDER: L5 avg 50%+ BELOW the line + h2h under + season under. NBA 71.4% (49, z+1.95); L5 50%+ below alone 60.2% (176).
    ruled = {(r["player"], r["stat"]) for r in q}
    for r in rows:
        if len(r["l5"]) == 5 and r["line"] >= 1:        # backtest used lines >= 1 (0.5 lines with L5 all zeros are not this spot)
            r["margin"] = sum(r["l5"]) / 5 / r["line"] - 1
    core = [r for r in rows if r.get("margin") is not None and all(x > r["line"] for x in r["l5"]) and r["v"]["season"] == 1
            and r["v"]["h2h"] == 1 and r["v"]["opp"] != -1 and (r["player"], r["stat"]) not in ruled]
    core.sort(key=lambda r: -r["margin"]); seen_p = set(); core_pick = []
    for r in core:
        if r["player"] not in seen_p and len(core_pick) < 2:
            seen_p.add(r["player"]); core_pick.append(dict(r, side="over", k=r["po"], rule="CORE OVER", tier=2))   # 11/16: untested on full data -> lead only
    miss = [dict(r, side="under", k=r["pu"], rule="BIG-MISS UNDER", tier=2) for r in rows
            if r.get("margin") is not None and r["margin"] <= -.5 and r["v"]["h2h"] == -1 and r["v"]["season"] == -1 and (r["player"], r["stat"]) not in ruled]
    for lab, L, sd in (("CORE OVER -- last 5 all over + season + h2h over, defense not tough, top 2 by margin  [NBA top-1 10-2, top-2 7-3; lead]", core_pick, "O"),
                       ("BIG-MISS UNDER -- L5 avg 50%+ below line + h2h + season under  [NBA 71.4% n=49; lead]", miss, "U")):
        print("\nMATCHUP -- " + lab)
        for r in L:
            print("  %-22s %-5s vs %-5s %s%-5g %-14s proj %5.1f | L5 %s (avg %+.0f%%) | def %+d | %d-%d checks | min %.0f%s" % (
                r["player"][:22], r["team"], r["opp"], sd, r["line"], r["stat"], r["mu"], "/".join("%g" % x for x in r["l5"]), 100 * r["margin"],
                r["v"]["opp"], r["po"], r["pu"], r["mins"], " EARLY" if r["early"] else ""))
        if not L:
            print("  none")
    q += core_pick + miss
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
    mk = lambda r: ((r.get("f") or {}).get("mkt") or .5)
    q.sort(key=lambda r: (r["tier"], -mk(r), -r["k"], -abs(r["z"])))   # 11/16: market on the side breaks ties inside a tier
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
    stake_plan(q, fmt)
    return pick


PAYX = {2: 3.0, 3: 6.0, 4: 10.0}


def kelly_f(ps, combos):
    """Exact growth-optimal fraction of roll for a set of PP power slips (independent legs, every win/loss outcome enumerated)."""
    import itertools
    D = []
    for hits in itertools.product((0, 1), repeat=len(ps)):
        pr = math.prod(p if h else 1 - p for p, h in zip(ps, hits))
        D.append((pr, sum(PAYX[len(c)] for c in combos if all(hits[i] for i in c)) / len(combos)))
    g, f = max((sum(p * math.log(1 + fr * (r - 1)) for p, r in D), fr) for fr in [i / 200 for i in range(1, 100)])
    return (f if g > 0 else 0.0), g


def stake_plan(q, fmt):
    """11/9 NEW STAKE PLAN (user reset: $15 roll, scratchpad combo_math.py). Picks the format by how many legs qualify:
    4 legs (distinct games, tier <= 1) -> 4-man by 3s | 3 legs -> 3-man by 2s + the 3-pick | 2 legs -> one 2-pick.
    Stake = HALF Kelly at the assumed leg hit rate (HIT env, default .62 = between the model's ~61% and his logged 66%), $1 PP minimum per slip.
    ROLL env = this morning's PP roll (default 15)."""
    import itertools
    roll = float(os.environ.get("ROLL", 15)); p = float(os.environ.get("HIT", .62))
    legs, games, players = [], set(), set()
    for r in q:
        g = frozenset((r["team"], r["opp"]))
        if r["tier"] > 1 or g in games or pkey(r["sport"], r["player"]) in players:
            continue
        legs.append(r); games.add(g); players.add(pkey(r["sport"], r["player"]))
        if len(legs) == 4:
            break
    n = len(legs)
    if n < 2:
        print("\nSTAKE PLAN: %d leg(s) pass (tier <= 1, distinct games) -> NO SLIPS today" % n); return
    C = lambda m, k: list(itertools.combinations(range(m), k))
    cand = [("two 2-picks", [(0, 1), (2, 3)], 4), ("one 2-pick", C(2, 2), 2)]   # 11/16: 2-picks ONLY (3-picks 0-12 since the 11/10 reset)
    best = None
    for name, combos, m in cand:
        if m > n:
            continue
        ps = [p] * min(m, 3) + [p - .05] * max(0, m - 3)
        f, _ = kelly_f(ps, combos)
        fr = max(.05 * len(combos), len(combos) / roll)     # 11/16: 5% of the roll per slip (user's stake rule), $1 PP minimum
        D = [(math.prod(q_ if h else 1 - q_ for q_, h in zip(ps, hits)), sum(PAYX[len(c)] for c in combos if all(hits[i] for i in c)) / len(combos))
             for hits in itertools.product((0, 1), repeat=m)]
        g = sum(pr * math.log(max(1e-9, 1 + fr * (r - 1))) for pr, r in D)
        if best is None or g > best[0]:
            best = (g, name, combos, m, f, fr)
    g, name, combos, m, f, fr = best
    legs = legs[:m]
    per = roll * fr / len(combos)
    flag = "  ($1 PP minimum binds)" if fr > .05 * len(combos) + 1e-9 else "  (5% of roll per slip)"
    print("\nSTAKE PLAN -- roll $%.2f, assumed leg hit %.0f%% (HIT=), %d legs pass -> %s  (best growth at a stake you can place: %+.2f%%/day)" % (
        roll, 100 * p, n, name, 100 * (math.exp(g) - 1)))
    print("  full Kelly %.0f%%, half %.1f%%, staking %.1f%% -> $%.2f per slip x %d slips = $%.2f%s" % (100 * f, 50 * f, 100 * fr, per, len(combos), per * len(combos), flag))
    for i, r in enumerate(legs):
        print("  leg %d: %s" % (i + 1, fmt(r)))
    for c in combos:
        print("  slip: %s  ($%.2f, pays %gx)" % (" + ".join("leg %d" % (i + 1) for i in c), per, PAYX[len(c)]))


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
