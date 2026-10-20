"""NBA PICKFINDER (10/20, user: "are we starting the pickfinder data -- everything we need"). His 2026 NBA profit came off PickFinder's
stack; this is that stack plus the step cappers skip: the PRICE.

    python _nba_finder.py "Stephon Castle" "Pts+Asts" 22.5 over
    python _nba_finder.py "Tyrese Maxey" "Pts+Rebs+Asts" 29.5 over --opp NYK

One card per leg:
    hit rates      this season (ESPN, incl. preseason flagged), last season, last 20/10/5, home/away, as starter, by minutes
    head-to-head   vs this opponent, two seasons
    defense        what the opponent allows to his POSITION (G/F/C), rank of 30 over last season / its last 10 / its last 5
    game           DK spread + total (blowout risk), both teams' injury report
    line           PrizePicks line history (lines.db archive)
    PRICE          DraftKings fair % at the PP line (Odds API, cached 6h) vs the 57.7% two-pick break-even -> BET / LEAN / PASS
Measured lessons baked in: last season misleads when the role changed (10/19 opener: 67-81% own rates, DK 49-56%), defense-vs-position
is context (~52% in NFL), the price decides.
"""
import sys, os, json, re, math, sqlite3, datetime, collections, statistics as st
import urllib.request
from statistics import NormalDist

N = NormalDist()
CT = datetime.timezone(datetime.timedelta(hours=-5))
CACHE = os.path.join("data", "nba_finder")
os.makedirs(CACHE, exist_ok=True)
norm = lambda s: re.sub(r"[^a-z]", "", (s or "").lower())
KEYS = {"Points": ("pts",), "Rebounds": ("reb",), "Assists": ("ast",), "3-PT Made": ("tpm",), "Pts+Rebs+Asts": ("pts", "reb", "ast"),
        "Pts+Rebs": ("pts", "reb"), "Pts+Asts": ("pts", "ast"), "Rebs+Asts": ("reb", "ast"), "Blocked Shots": ("blk",), "Steals": ("stl",),
        "Blks+Stls": ("blk", "stl"), "Turnovers": ("to",)}
ESPN_KEYS = {"pts": "PTS", "reb": "REB", "ast": "AST", "tpm": "3PT", "blk": "BLK", "stl": "STL", "to": "TO"}
DK_ALT = {"player_points_alternate": "Points", "player_rebounds_alternate": "Rebounds", "player_assists_alternate": "Assists",
          "player_points_rebounds_assists_alternate": "Pts+Rebs+Asts", "player_threes_alternate": "3-PT Made",
          "player_blocks_alternate": "Blocked Shots", "player_steals_alternate": "Steals"}
DK_MAIN = {"player_points_rebounds": "Pts+Rebs", "player_points_assists": "Pts+Asts", "player_rebounds_assists": "Rebs+Asts",
           "player_blocks_steals": "Blks+Stls", "player_turnovers": "Turnovers"}


def get(url, cache=None, hours=6):
    if cache:
        f = os.path.join(CACHE, cache)
        if os.path.exists(f) and (datetime.datetime.now().timestamp() - os.path.getmtime(f)) < hours * 3600:
            return json.load(open(f, encoding="utf-8"))
    d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=40))
    if cache:
        json.dump(d, open(os.path.join(CACHE, cache), "w", encoding="utf-8"))
    return d


def odds_key():
    return next(l.split("=", 1)[1].strip().strip('"') for l in open(".env") if l.startswith("ODDS_API_KEY"))


def teams():
    t = get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams", "teams.json", 240)
    return {x["team"]["abbreviation"]: (x["team"]["id"], x["team"]["displayName"]) for x in t["sports"][0]["leagues"][0]["teams"]}


def positions():
    """current rosters -> {norm(name): 'G'|'F'|'C'}"""
    pos = {}
    for ab, (tid, _) in teams().items():
        r = get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/%s/roster" % tid, "roster_%s.json" % tid, 24)
        for a in r.get("athletes", []):
            pos[norm(a["displayName"])] = (a.get("position") or {}).get("abbreviation", "?")[:1]
    return pos


def pp_line(player, stat):
    d = get("https://partner-api.prizepicks.com/projections?league_id=7&per_page=1000", "pp_nba.json", 0.25)
    P = {x["id"]: x["attributes"] for x in d.get("included", []) if x["type"] == "new_player"}
    for p in d["data"]:
        a = p["attributes"]; pl = P.get(p["relationships"]["new_player"]["data"]["id"], {})
        if norm(pl.get("name")) == norm(player) and a["stat_type"] == stat and a.get("odds_type") == "standard":
            return dict(line=float(a["line_score"]), team=pl.get("team"), opp=a.get("description"), start=a["start_time"])
    return None


def season_logs(player, keys):
    """this season from ESPN (preseason flagged) -- sports.db has no 2026-27 yet"""
    s = get("https://site.web.api.espn.com/apis/common/v3/search?query=%s&limit=5&type=player" % player.replace(" ", "%20"))
    it = [i for i in s.get("items", []) if "nba" in json.dumps(i).lower()]
    if not it:
        return []
    gl = get("https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/%s/gamelog?season=2027" % it[0]["id"], "gl_%s.json" % it[0]["id"], 3)
    lab = gl.get("labels", []); ev = gl.get("events", {}); rows = []
    for stt in gl.get("seasonTypes", []):
        pre = "Pre" in stt.get("displayName", "")
        for cat in stt.get("categories", []):
            for e in cat.get("events", []):
                d = dict(zip(lab, e["stats"])); m = ev.get(e["eventId"], {})
                v = 0.0
                for k in keys:
                    x = d.get(ESPN_KEYS[k], "0")
                    v += float(str(x).split("-")[0] or 0)
                rows.append(dict(date=m.get("gameDate", "")[:10], opp=(m.get("opponent") or {}).get("abbreviation"), min=float(d.get("MIN") or 0), v=v, pre=pre))
    return sorted(rows, key=lambda r: r["date"])


def dk_fair(team_full, opp_full, player, stat, line, sd):
    key = odds_key()
    E = get("https://api.the-odds-api.com/v4/sports/basketball_nba/events?apiKey=%s" % key, "dk_events.json", 3)
    ev = next((e for e in E if {e["home_team"], e["away_team"]} == {team_full, opp_full}), None)
    if not ev:
        return None, None, None
    mk = ",".join(list(DK_ALT) + list(DK_MAIN))
    d = get("https://api.the-odds-api.com/v4/sports/basketball_nba/events/%s/odds?apiKey=%s&regions=us&bookmakers=draftkings&markets=%s&oddsFormat=american"
            % (ev["id"], key, mk), "dk_%s.json" % ev["id"], 6)
    gm = get("https://api.the-odds-api.com/v4/sports/basketball_nba/odds?apiKey=%s&regions=us&bookmakers=draftkings&markets=spreads,totals&oddsFormat=american" % key, "dk_lines.json", 6)
    game = next((g for g in gm if g["id"] == ev["id"]), None)
    imp = lambda a: 100 / (a + 100) if a > 0 else -a / (-a + 100)
    alt, main = {}, None
    for b in d.get("bookmakers", []):
        for m in b["markets"]:
            if m["key"] in DK_ALT and DK_ALT[m["key"]] == stat:
                for o in m["outcomes"]:
                    if o["name"] == "Over" and norm(o["description"]) == norm(player):
                        alt[o["point"]] = imp(o["price"]) * 0.955
            if m["key"] in DK_MAIN and DK_MAIN[m["key"]] == stat:
                ou = {o["name"]: (o["point"], imp(o["price"])) for o in m["outcomes"] if norm(o["description"]) == norm(player)}
                if "Over" in ou and "Under" in ou:
                    main = (ou["Over"][0], ou["Over"][1] / (ou["Over"][1] + ou["Under"][1]))
    po = None
    if alt:
        if line == int(line) and line + 0.5 in alt and line - 0.5 in alt:
            po = alt[line + 0.5] / (alt[line + 0.5] + 1 - alt[line - 0.5])     # push removed
        elif line in alt:
            po = alt[line]
        src = "DK alt ladder"
    if po is None and main:
        pt, p0 = main; mu = pt + sd * N.inv_cdf(min(.98, max(.02, p0)))
        po = 1 - N.cdf((line - mu) / sd); src = "DK main %g, moved by his spread" % pt
    gl = None
    if game:
        for b in game["bookmakers"]:
            sp = {m["key"]: m["outcomes"] for m in b["markets"]}
            fav = min(sp.get("spreads", []), key=lambda o: o["point"], default=None)
            tot = (sp.get("totals") or [{}])[0].get("point")
            gl = "%s %+g, total %s" % (fav["name"].split()[-1], fav["point"], tot) if fav else None
    return po, (src if po is not None else "no DK line"), gl


def card(player, stat, line=None, side="over", opp=None):
    keys = KEYS[stat]
    T = teams(); ab = {v[0]: k for k, v in T.items()}
    pp = pp_line(player, stat)
    if line is None and pp:
        line = pp["line"]
    ALIAS = {"SAS": "SA", "NYK": "NY", "GSW": "GS", "NOP": "NO", "UTA": "UTAH", "WAS": "WSH"}   # PrizePicks -> ESPN abbreviations
    team = ALIAS.get(pp["team"], pp["team"]) if pp else None
    opp = ALIAS.get(opp or (pp or {}).get("opp"), opp or (pp or {}).get("opp"))
    print("\n%s %s %s %g vs %s%s" % (player, side.upper(), stat, line, opp, ("  (%s)" % datetime.datetime.fromisoformat(pp["start"]).astimezone(CT).strftime("%a %I:%M%p CT")) if pp else ""))
    hit = lambda X: (sum((x > line) if side == "over" else (x < line) for x in X), len(X))
    fmt = lambda h: "%d/%d (%.0f%%)" % (h[0], h[1], 100 * h[0] / h[1]) if h[1] else "--"
    db = sqlite3.connect("sports.db"); f = lambda s, k: float(s.get(k) or 0)
    R = [(d, o, m or 0, json.loads(s), h) for d, o, m, s, h in db.execute(
        "select date, opp, minutes, stats, home from player_games where sport='NBA' and player=? and season in ('2024-25','2025-26') order by date", (player,))]
    last = [(d, ab.get(o, o), m, sum(f(s, k) for k in keys), s.get("starter"), h) for d, o, m, s, h in R if d >= "2025-10-01" and m >= 15]
    cur = season_logs(player, keys)
    reg = [r for r in cur if not r["pre"]]; pre = [r for r in cur if r["pre"]]
    vals = [x[3] for x in last]
    print("  THIS SEASON   regular %s | preseason %s %s" % (fmt(hit([r["v"] for r in reg])), fmt(hit([r["v"] for r in pre])),
          [(int(r["v"]), int(r["min"])) for r in pre][-6:]))
    if vals:
        sd = st.pstdev(vals) or 1
        print("  LAST SEASON   %s avg %.1f | last 20 %s | last 10 %s | last 5 %s" % (fmt(hit(vals)), st.mean(vals), fmt(hit(vals[-20:])), fmt(hit(vals[-10:])), fmt(hit(vals[-5:]))))
        print("  SPLITS        starter %s | bench %s | 30+ min %s | under 30 min %s" % (fmt(hit([x[3] for x in last if x[4]])), fmt(hit([x[3] for x in last if not x[4]])),
              fmt(hit([x[3] for x in last if x[2] >= 30])), fmt(hit([x[3] for x in last if x[2] < 30]))))
        h2h = [x for x in [(d, ab.get(o, o), m, sum(f(s, k) for k in keys)) for d, o, m, s, h in R if m >= 15] if x[1] == opp]
        print("  HEAD-TO-HEAD  vs %s (2 seasons) %s %s" % (opp, fmt(hit([x[3] for x in h2h])), [int(x[3]) for x in h2h][-6:]))
    else:
        sd = max(1.0, 0.25 * line); print("  LAST SEASON   no 2025-26 games (rookie or new)")
    # defense vs position
    pos = positions(); mypos = pos.get(norm(player), "?")
    if opp in T and mypos != "?":
        tid = T[opp][0]
        allow = collections.defaultdict(lambda: collections.defaultdict(float))
        for d, o, pl, s in db.execute("select date, opp, player, stats from player_games where sport='NBA' and season='2025-26' and minutes>=15"):
            if pos.get(norm(pl)) == mypos:
                allow[o][d] += sum(f(json.loads(s), k) for k in keys)
        def rank(window):
            avg = {t: st.mean(sorted(v.items())[-window:][i][1] for i in range(min(window, len(v)))) for t, v in allow.items() if len(v) >= 5}
            order = sorted(avg, key=lambda t: -avg[t])
            return (order.index(tid) + 1, avg[tid]) if tid in avg else (None, None)
        r_all, r10, r5 = rank(999), rank(10), rank(5)
        if r_all[0]:
            print("  DEFENSE       %s vs %ss, %s allowed: season #%d (%.1f) | last 10 #%d | last 5 #%d of 30 (1 = allows most) -- context, not a reason"
                  % (opp, mypos, stat, r_all[0], r_all[1], r10[0], r5[0]))
    # injuries
    inj = get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries", "injuries.json", 1)
    for t in inj.get("injuries", []):
        nm = t.get("displayName", "")
        if team and T.get(team, (0, ""))[1] == nm or opp and T.get(opp, (0, ""))[1] == nm:
            for i in t.get("injuries", []):
                if i.get("status") in ("Out", "Day-To-Day", "Doubtful", "Questionable"):
                    print("  INJURY        %-22s %-24s %s" % (nm, i["athlete"]["displayName"], i.get("status")))
    # line history
    try:
        h = sqlite3.connect("lines.db", timeout=60).execute("select line, first_seen from pp where league=7 and kind='standard' and player=? and stat=? order by first_seen", (player, stat)).fetchall()
        if h:
            print("  LINE HISTORY  first %g (%s) -> now %g" % (h[0][0], h[0][1][:10], line))
    except Exception:
        pass
    # price
    po, src, game = (None, "no team match", None)
    if team in T and opp in T:
        po, src, game = dk_fair(T[team][1], T[opp][1], player, stat, line, sd)
    if game:
        print("  GAME          %s" % game)
    fair = None if po is None else (po if side == "over" else 1 - po)
    print("  PRICE         %s -> fair %s (2-pick needs 57.7%%, 3-pick 55%%)" % (src, "%.0f%%" % (100 * fair) if fair is not None else "--"))
    s_rate = hit(vals) if vals else (0, 0)
    ok_rate = s_rate[1] and s_rate[0] / s_rate[1] >= 0.55
    verdict = "BET" if fair is not None and fair >= 0.577 and ok_rate else ("LEAN" if fair is not None and fair >= 0.55 else "PASS")
    print("  VERDICT       %s" % verdict)
    return dict(player=player, stat=stat, line=line, side=side, fair=fair, verdict=verdict)


if __name__ == "__main__":
    a = sys.argv[1:]
    opp = a[a.index("--opp") + 1] if "--opp" in a else None
    a = [x for i, x in enumerate(a) if x != "--opp" and (i == 0 or a[i - 1] != "--opp")]
    card(a[0], a[1], float(a[2]) if len(a) > 2 and a[2].replace(".", "").isdigit() else None, a[3] if len(a) > 3 else "over", opp)
