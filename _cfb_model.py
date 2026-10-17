"""CFB MODEL FOR EVERY PP LINE (10/17, user: "look at every PP CFB line and make a model for each -- I know there's fantasy lines").

The measured lesson (10/16): a CFB player's own history does NOT beat PP (48-50% on 1,757 lines -- schedules swing), but the SHARP
books do (FanDuel/Pinnacle 58%+ -> 69%). FanDuel posts receiving / rushing / passing yards, receptions and TD passes, NOT PP's combos
or fantasy -- so this model BUILDS every PP line from the sharp medians:

    direct     Receiving Yards, Rush Yards, Pass Yards, Receptions, Pass TDs     sharp median (the line FanDuel prices at 50%)
    combos     Rush+Rec Yds = rush + rec,  Pass+Rush Yds = pass + rush
    fantasy    skill: 0.1 x (rush + rec yds) + receptions + 6 x TDs/game (his season rate, TDs have no sharp price)
               QB:    0.04 x pass yds + 4 x pass TDs - INT/game + 0.1 x rush yds + 6 x rush TDs/game
    P(side)    normal around the projection, spread = that stat's measured coefficient of variation (player-game history)

    python _cfb_model.py bt            # backtest every stat on graded PP lines (sharp prices as of the day before the game)
    python _cfb_model.py board [day]   # every live PP CFB line, model side + %, best first
"""
import sys, json, re, sqlite3, bisect, collections, datetime, statistics as stat_
from statistics import NormalDist

norm = lambda s: re.sub(r"[^a-z]", "", (s or "").lower())
N = NormalDist()
SH = {"Receiving Yards": "receiving yards", "Rush Yards": "rushing yards", "Pass Yards": "passing yards", "Receptions": "receptions",
      "Pass TDs": "touchdown passes"}
BOX = {"Receiving Yards": "rec_yds", "Rush Yards": "rush_yds", "Pass Yards": "pass_yds", "Receptions": "rec", "Pass TDs": "pass_td",
       "Rush Attempts": "carries", "Pass Attempts": "att", "Pass Completions": "cmp"}
MODELED = ["Receiving Yards", "Rush Yards", "Pass Yards", "Receptions", "Pass TDs", "Rush+Rec Yds", "Pass+Rush Yds", "Fantasy Score"]

_sharp = None


def sharp_rows():
    global _sharp
    if _sharp is None:
        _sharp = collections.defaultdict(list)
        for pl, st, ln, po, ts in sqlite3.connect("lines.db", timeout=60).execute(
                "select player, stat, line, p_over, ts from sharp where sport='CFB'"):
            _sharp[(norm(pl), st.lower())].append((ts, float(ln), float(po)))
    return _sharp


def median(player, stat, before=None):
    """the line FanDuel/Pinnacle price at 50% (their median), from the latest hour of prices before `before`"""
    R = sharp_rows().get((norm(player), SH.get(stat, "-")))
    if not R:
        return None
    if before:
        R = [r for r in R if r[0][:13] <= before]
    if not R:
        return None
    last = max(r[0] for r in R)[:13]
    pts = sorted({(l, p) for t, l, p in R if t[:13] == last})
    for (l0, p0), (l1, p1) in zip(pts, pts[1:]):
        if p0 >= 0.5 >= p1 and p0 != p1:
            return l0 + (l1 - l0) * (p0 - 0.5) / (p0 - p1)
    if len(pts) == 1 and pts[0][1] == 0.5:
        return pts[0][0]
    return None                                             # 10/17: one alt rung or a ladder that never crosses 50% -> no median (it produced
                                                            # "100%" legs like proj 11.7 vs 37.5 -- an extrapolation, not a price)


_games = None


def games():
    global _games
    if _games is None:
        _games = collections.defaultdict(list)
        for pl, d, js in sqlite3.connect("sports.db").execute("select player, date, stats from player_games where sport='CFB' and date >= '2025-08-01'"):
            _games[norm(pl)].append((d, json.loads(js)))
        for k in _games:
            _games[k].sort(key=lambda t: t[0])
    return _games


def fantasy(s):
    g = lambda k: float(s.get(k) or 0)
    return (0.04 * g("pass_yds") + 4 * g("pass_td") - g("int") + 0.1 * (g("rush_yds") + g("rec_yds")) + g("rec")
            + 6 * (g("rush_td") + g("rec_td")))


def actual(stat, s):
    if stat == "Rush+Rec Yds":
        return float(s.get("rush_yds") or 0) + float(s.get("rec_yds") or 0)
    if stat == "Pass+Rush Yds":
        return float(s.get("pass_yds") or 0) + float(s.get("rush_yds") or 0)
    if stat == "Fantasy Score":
        return fantasy(s)
    k = BOX.get(stat)
    return float(s.get(k) or 0) if k else None


def project(player, stat, day, before=None):
    """projection from the sharp medians (+ season rates where no sharp market exists); None when the core piece has no sharp price"""
    prior = [s for d, s in games().get(norm(player), []) if d < day and d >= "2026-08-01"]
    rate = lambda k: (sum(float(s.get(k) or 0) for s in prior) / len(prior)) if prior else 0.0
    m = lambda st: median(player, st, before)
    if stat in SH:
        return m(stat)
    if stat == "Rush+Rec Yds":
        r, c = m("Rush Yards"), m("Receiving Yards")
        if r is None and c is None:
            return None
        return (r if r is not None else rate("rush_yds")) + (c if c is not None else rate("rec_yds"))
    if stat == "Pass+Rush Yds":
        p, r = m("Pass Yards"), m("Rush Yards")
        if p is None:
            return None
        return p + (r if r is not None else rate("rush_yds"))
    if stat == "Fantasy Score":
        p = m("Pass Yards")
        if p is not None:                                   # QB
            td = m("Pass TDs")
            return 0.04 * p + 4 * (td if td is not None else rate("pass_td")) - rate("int") + 0.1 * (m("Rush Yards") or rate("rush_yds")) + 6 * rate("rush_td")
        r, c, rc = m("Rush Yards"), m("Receiving Yards"), m("Receptions")
        if r is None and c is None:
            return None
        return (0.1 * ((r if r is not None else rate("rush_yds")) + (c if c is not None else rate("rec_yds")))
                + (rc if rc is not None else rate("rec")) + 6 * (rate("rush_td") + rate("rec_td")))
    return None


_cv = {}


def cv(stat):
    """spread of a player's games around his own mean, per stat (measured once from 2025-26 box scores)"""
    if stat not in _cv:
        r = []
        for k, G in games().items():
            v = [actual(stat, s) for _, s in G]
            v = [x for x in v if x is not None]
            if len(v) >= 6 and stat_.mean(v) > 3:
                r.append(stat_.pstdev(v) / stat_.mean(v))
        _cv[stat] = stat_.median(r) if r else 0.6
    return _cv[stat]


def prob_over(proj, line, stat):
    sd = max(cv(stat) * max(proj, 1.0), 0.8)
    return 1 - N.cdf((line + 0.5 * (1 if stat in ("Receptions", "Pass TDs") else 0) - proj) / sd) if stat in ("Receptions", "Pass TDs") else 1 - N.cdf((line - proj) / sd)


def backtest():
    L = sqlite3.connect("lines.db", timeout=60)
    rows = collections.defaultdict(list)
    for pl, st, line, start, fs in L.execute("select player, stat, line, start, last_seen from pp where league=15 and kind='standard'"):
        if st not in MODELED or not start:
            continue
        day = datetime.datetime.fromisoformat(start).astimezone(datetime.timezone(datetime.timedelta(hours=-5))).date().isoformat()
        rows[(pl, st, day)].append((fs, float(line)))
    res = collections.defaultdict(list)
    for (pl, st, day), v in rows.items():
        v.sort(); fs, line = v[-1]                                  # the line still up last before the game (what he'd actually bet)
        G = [s for d, s in games().get(norm(pl), []) if d in (day, (datetime.date.fromisoformat(day) + datetime.timedelta(days=1)).isoformat())]
        if not G:
            continue
        act = actual(st, G[0])
        if act is None or act == line:
            continue
        before = fs[:10] + "T" + fs[11:13] if "T" in fs else None    # sharp prices up to that same moment -- no peeking past it
        pj = project(pl, st, day, before=before)
        if pj is None:
            continue
        po = prob_over(pj, line, st)
        side = "over" if po >= 0.5 else "under"
        res[st].append((day, max(po, 1 - po), (act > line) == (side == "over")))
    print("CFB model backtest -- the last PP line before kickoff, sharp prices up to that moment")
    print("%-16s %6s | %-22s %-22s %-22s" % ("stat", "n", "model 58%+", "model 62%+", "model 66%+"))
    for st in MODELED:
        g = sorted(res.get(st, []))
        cells = []
        for lo in (0.58, 0.62, 0.66):
            s = [x for x in g if x[1] >= lo]
            if len(s) >= 15:
                h = len(s) // 2; w = lambda X: 100 * sum(x[2] for x in X) / len(X)
                cells.append("%3d %4.0f%% (%2.0f/%2.0f)" % (len(s), w(s), w(s[:h]), w(s[h:])))
            else:
                cells.append("%3d  --" % len(s))
        print("%-16s %6d | %-22s %-22s %-22s" % (st, len(g), *cells))


def board(day=None):
    import urllib.request, time
    day = day or (datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-5))).date() + datetime.timedelta(days=0)).isoformat()
    d = None
    for w in (0, 20, 40):
        time.sleep(w)
        try:
            d = json.load(urllib.request.urlopen(urllib.request.Request("https://partner-api.prizepicks.com/projections?league_id=15&per_page=1000",
                                                                        headers={"User-Agent": "Mozilla/5.0"}), timeout=40)); break
        except Exception as e:
            print("retry", e)
    P = {x["id"]: x["attributes"] for x in d.get("included", []) if x["type"] == "new_player"}
    out = []
    for p in d["data"]:
        a = p["attributes"]
        if a.get("odds_type") != "standard" or a["stat_type"] not in MODELED:
            continue
        st_day = datetime.datetime.fromisoformat(a["start_time"]).astimezone(datetime.timezone(datetime.timedelta(hours=-5))).date().isoformat()
        if st_day != day:
            continue
        pl = P.get(p["relationships"]["new_player"]["data"]["id"], {})
        ln = float(a["line_score"]); pj = project(pl.get("name"), a["stat_type"], day)
        if pj is None:
            continue
        po = prob_over(pj, ln, a["stat_type"])
        out.append((max(po, 1 - po), "MORE" if po >= 0.5 else "LESS", pl.get("name"), pl.get("team"), pl.get("position"), a["stat_type"], ln, pj,
                    a.get("description"), a["start_time"][11:16]))
    print("CFB %s -- %d PP lines modeled" % (day, len(out)))
    for r in sorted(out, reverse=True)[:25]:
        print("  %3.0f%% %-4s %-24s %-5s %-3s %-15s %6g  proj %6.1f  vs %-5s %s ET" % (100 * r[0], *r[1:]))
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["bt"]:
        backtest()
    else:
        board(a[1] if len(a) > 1 else None)
