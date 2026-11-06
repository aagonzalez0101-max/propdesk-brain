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
CUR = "2026-27"
CFG = {"cbb": dict(league=20, box="cbb_box", games="cbb_games", where="", team={}),
       "nba": dict(league=7, box="nba_box", games="nba_games", where=" and g.stype='regular'",
                   team={"NYK": "NY", "GSW": "GS", "SAS": "SA", "NOP": "NO", "UTA": "UTAH", "WAS": "WSH"})}
val = lambda row, e: eval(e, {}, row)


def board(day, sp):
    cf = CFG[sp]; T = lambda x: cf["team"].get(x, x)
    d = C.projections(cf["league"], 300)
    P = {i["id"]: i["attributes"] for i in d.get("included", []) if i["type"] == "new_player"}
    out = []
    for x in d["data"]:
        a = x["attributes"]
        if a.get("odds_type") != "standard" or a.get("is_promo") or a["stat_type"] not in STATS:
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
        cf = CFG[sp]
        c = sqlite3.connect("sports.db", timeout=60)
        self.G = collections.defaultdict(list)
        tot = collections.defaultdict(lambda: collections.defaultdict(float))
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
    games = D.G.get(nn(leg["player"]))
    if not games:
        return None
    e = STATS[leg["stat"]]; ln = leg["line"]
    cur = [g for g in games if g["season"] == CUR]; prev = [g for g in games if g["season"] == "2025-26" and g["min"] >= 10]
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
    transfer = bool(prev and cur and prev[-1]["team"] != cur[-1]["team"]) or bool(prev and not cur and leg["team"] and prev[-1]["team"] != leg["team"])
    return dict(leg, mu=mu, z=z, v=v, po=po, pu=pu, n_cur=len(cur), early=early, transfer=transfer,
                l5=seq[-5:], mins=exp_min, of=of)


def screen(day, sp):
    legs = board(day, sp)
    D = Data(day, sp)
    rows = [r for r in (check(D, l, day) for l in legs) if r]
    print("%s %s: %d PP standard lines, %d with logs" % (sp.upper(), day, len(legs), len(rows)))
    q = [r for r in rows if r["pu"] >= 4 and r["po"] == 0]
    q.sort(key=lambda r: (-r["pu"], r["z"]))
    print("\nQUALIFIERS -- UNDER, 4+ checks agree, 0 against  (%s)" % ("NBA 58.8% n=250" if sp == "nba" else "PROBATION: measured in NBA/NHL/NFL, not yet in CBB"))
    for r in q:
        print("  %-22s %-5s vs %-5s U%-5g %-14s proj %5.1f | %d agree [%s] | L5 %s | min %.0f%s%s" % (
            r["player"][:22], r["team"], r["opp"], r["line"], r["stat"], r["mu"], r["pu"], ",".join(k for k, x in r["v"].items() if x == -1),
            "/".join("%g" % x for x in r["l5"]), r["mins"], " EARLY(%d gm)" % r["n_cur"] if r["early"] else "", " TRANSFER" if r["transfer"] else ""))
    fade = [r for r in rows if r["po"] >= 4 and r["pu"] == 0]
    if fade:
        print("\nALL-CHECKS-SAY-OVER (overs lose at every stack in every sport -- skip; NHL/NFL these were fades):")
        for r in sorted(fade, key=lambda r: -r["po"])[:8]:
            print("  %-22s O%-5g %-14s proj %5.1f | %d agree" % (r["player"][:22], r["line"], r["stat"], r["mu"], r["po"]))
    return q


def card(day, sports):
    q = []
    for sp in sports:
        q += screen(day, sp)
        print()
    q.sort(key=lambda r: (r["sport"] == "cbb" or r["early"], -r["pu"], r["z"]))   # 11/6: measured NBA legs first; CBB/early = probation, fill only
    used, pick = set(), []
    for r in q:
        if nn(r["player"]) in used or r["transfer"]:
            continue
        used.add(nn(r["player"])); pick.append(r)
        if len(pick) == 4:
            break
    print("\nCARD (top 4, one per player, no transfers):")
    if pick:
        print("  POTD: [%s] %s U%g %s" % (pick[0]["sport"].upper(), pick[0]["player"], pick[0]["line"], pick[0]["stat"]))
    for i in (0, 2):
        sl = pick[i:i + 2]
        if len(sl) == 2:
            print("  Slip %d: %s" % (i // 2 + 1, "  +  ".join("[%s] %s U%g %s" % (r["sport"].upper(), r["player"], r["line"], r["stat"]) for r in sl)))


if __name__ == "__main__":
    a = sys.argv[1:]
    day = next((x for x in a if re.match(r"\d{4}-\d\d-\d\d", x)), datetime.datetime.now(CT).date().isoformat())
    sp = next((x for x in a if x in ("cbb", "nba", "all")), "cbb")
    if a[:1] == ["card"]:
        card(day, ["nba", "cbb"] if sp == "all" else [sp])
    else:
        screen(day, sp)
