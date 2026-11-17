"""NBA 1Q / 1H / 2H PROPS (11/16, user: "do we have value for 1Q or 1H legs ... with the millions of legs of info plus espn play by play").
PP posts these in their own leagues: NBA1Q = 192, NBA1H = 84, NBA2H = 80. nba_pbp.db gives each player's points (made shots + ft_made) and
rebounds (oreb + dreb events) and assists (nba_shots.assist) by period. 11/16: events were DUPLICATED for 601 games (rebounds +2.1
per player-game) -- deduped; pbp now matches the box 99.7-99.9% on pts/reb/ast. Fantasy lines skipped.
Grades every archived CLOSING standard line (cloud lines.db), then tests simple as-of rules walk-forward (found on the first half of
the days, must hold on the second half), then prices today's board.
    python _period_props.py
"""
import sqlite3, json, re, unicodedata, collections, datetime, statistics

CT = __import__("zoneinfo").ZoneInfo("America/Chicago")
nn = lambda s: re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().replace("jr", "").replace("iii", "").replace("ii", ""))
LEAGUE = {192: ("1Q", (1,)), 84: ("1H", (1, 2)), 80: ("2H", (3, 4, 5, 6, 7))}   # 11/16: PP 2H includes overtime
STATS = ("Points", "Rebounds", "Assists", "Pts+Rebs+Asts")

P = sqlite3.connect("nba_pbp.db")
# 11/16: nba_pbp.db dates are UTC (133 of 179 games carry the NEXT day) -> take each game's local date from sports.db nba_box
BOXD = {g: d for g, d in sqlite3.connect("sports.db").execute("select distinct game_id, date from nba_box")}
pts = collections.defaultdict(lambda: collections.defaultdict(float)); reb = collections.defaultdict(lambda: collections.defaultdict(float))
ast = collections.defaultdict(lambda: collections.defaultdict(float))
gdate = {}
for g, d, per, pl, p_, an in P.execute("select game_id, date, period, player, pts, assist from nba_shots where made=1 and date>='2026-10-20'"):
    pts[(nn(pl), g)][per] += p_; gdate[(nn(pl), g)] = BOXD.get(g, d)
    if an:
        ast[(nn(an), g)][per] += 1
for g, d, per, pl, k in P.execute("select game_id, date, period, player, kind from nba_events where date>='2026-10-20' and kind in ('ft_made','oreb','dreb')"):
    if k == "ft_made":
        pts[(nn(pl), g)][per] += 1
    else:
        reb[(nn(pl), g)][per] += 1
    gdate[(nn(pl), g)] = BOXD.get(g, d)
# every player-game that appears (sub_in covers a scoreless, reboundless player who played)
for g, d, pl in P.execute("select game_id, date, player from nba_events where date>='2026-10-20' and kind='sub_in'"):
    gdate.setdefault((nn(pl), g), BOXD.get(g, d))
H = collections.defaultdict(list)          # player -> [(date, {period: pts}, {period: reb})]
for (pl, g), d in gdate.items():
    H[pl].append((d, pts.get((pl, g), {}), reb.get((pl, g), {}), ast.get((pl, g), {})))
for v in H.values():
    v.sort(key=lambda x: x[0])


def val(rec, stat, pers):
    src = {"Points": (1,), "Rebounds": (2,), "Assists": (3,), "Pts+Rebs+Asts": (1, 2, 3)}[stat]
    return sum(rec[i].get(p, 0) for i in src for p in pers)


L = sqlite3.connect("lines.db")
rows = []
for lg, (lab, pers) in LEAGUE.items():
    close = {}
    for pl, st, line, start, fs, ls in L.execute("select player, stat, line, start, first_seen, last_seen from pp where league=? and kind='standard'", (lg,)):
        if st not in STATS or not start:
            continue
        day = datetime.datetime.fromisoformat(start).astimezone(CT).date().isoformat()
        k = (day, nn(pl), st)
        o = close.setdefault(k, dict(open=(fs or "~", line), close=(ls or "", line)))
        if (fs or "~") < o["open"][0]:
            o["open"] = (fs, line)
        if (ls or "") > o["close"][0]:
            o["close"] = (ls, line)
    for (day, pl, st), o in close.items():
        g = [r for r in H.get(pl, []) if r[0] == day]
        if not g:
            continue
        ln = o["close"][1]; act = val(g[0], st, pers)
        if act == ln:
            continue
        pr = [val(r, st, pers) for r in H[pl] if r[0] < day]
        if len(pr) < 5:
            continue
        rows.append(dict(lab=lab, st=st, day=day, pl=pl, line=ln, act=act, over=int(act > ln), n=len(pr),
                         so=sum(x > ln for x in pr) / len(pr), l5o=sum(x > ln for x in pr[-5:]), avg_rel=(statistics.mean(pr) - ln) / max(ln, 1),
                         med_rel=(statistics.median(pr) - ln) / max(ln, 1), move=ln - o["open"][1]))
print("graded %d archived PP period lines with 5+ prior games (NBA 1Q/1H/2H points + rebounds)" % len(rows))


def fmt(X, side):
    w = sum(r["over"] if side == "over" else 1 - r["over"] for r in X); n = len(X)
    return "%4d-%-4d %5.1f%%" % (w, n - w, 100 * w / n) if n else "    --         "


days = sorted({r["day"] for r in rows}); half = days[len(days) // 2]
RULES = {
    "every line": lambda r, o: True,
    "season 60%+ this side": lambda r, o: (r["so"] if o else 1 - r["so"]) >= .6,
    "season 70%+ this side": lambda r, o: (r["so"] if o else 1 - r["so"]) >= .7,
    "season 60%+ & L5 4/5+": lambda r, o: (r["so"] if o else 1 - r["so"]) >= .6 and (r["l5o"] if o else 5 - r["l5o"]) >= 4,
    "average 20%+ past the line": lambda r, o: r["avg_rel"] >= .2 if o else r["avg_rel"] <= -.2,
    "median 20%+ past the line": lambda r, o: r["med_rel"] >= .2 if o else r["med_rel"] <= -.2,
    "PP moved the line toward this side": lambda r, o: r["move"] < 0 if o else r["move"] > 0,
    "PP moved the line away from this side": lambda r, o: r["move"] > 0 if o else r["move"] < 0,
    "low line (<= 3.5)": lambda r, o: r["line"] <= 3.5,
    "big line (>= 10.5)": lambda r, o: r["line"] >= 10.5,
}
for lab in ("1Q", "1H", "2H"):
    for st in STATS:
        X = [r for r in rows if r["lab"] == lab and r["st"] == st]
        if len(X) < 100:
            continue
        A = [r for r in X if r["day"] < half]; B = [r for r in X if r["day"] >= half]
        print("\n%s %s -- %d lines   (first half | second half | all)   2-pick b/e 57.7%%" % (lab, st, len(X)))
        for side in ("over", "under"):
            o = side == "over"
            for name, f in RULES.items():
                a = [r for r in A if f(r, o)]; b = [r for r in B if f(r, o)]; t = a + b
                if len(t) < 30:
                    continue
                wa = (sum(r["over"] if o else 1 - r["over"] for r in a) / len(a)) if a else 0
                wb = (sum(r["over"] if o else 1 - r["over"] for r in b) / len(b)) if b else 0
                flag = "  <== HOLDS" if len(a) >= 20 and len(b) >= 20 and wa >= .577 and wb >= .577 else ""
                print("  %-5s %-38s %s | %s | %s%s" % (side.upper(), name, fmt(a, side), fmt(b, side), fmt(t, side), flag))
json.dump(rows, open("period_props_graded.json", "w"))


# ---- TODAY: price the live 1Q / 1H / 2H boards with the rules that held (11/16) ----
def today():
    import _ppcache
    import sys; day = sys.argv[1] if len(sys.argv) > 1 else datetime.datetime.now(CT).date().isoformat()   # python _period_props.py [YYYY-MM-DD]
    RULE = {("1Q", "Rebounds"): ("season 60%+ under", lambda f: f["su"] >= .6, "1Q reb unders 80-54 59.7%"),
            ("1Q", "Assists"): ("median 20%+ below line", lambda f: f["med_rel"] <= -.2, "1Q ast unders 35-23 60.3%"),
            ("2H", "Points"): ("average 20%+ below line", lambda f: f["avg_rel"] <= -.2, "2H pts unders 148-100 59.7% (base 55.8%)"),
            ("2H", "Pts+Rebs+Asts"): ("average 20%+ below line", lambda f: f["avg_rel"] <= -.2, "2H PRA unders 120-82 59.4% (base 55.6%)")}
    print("\nTODAY %s -- period UNDERS that meet a rule that held walk-forward" % day)
    for lg, (lab, pers) in LEAGUE.items():
        try:
            d = _ppcache.projections(lg, 600)
        except Exception as e:
            print("  %s: board unavailable (%s)" % (lab, e)); continue
        PLR = {i["id"]: i["attributes"] for i in d.get("included", []) if i["type"] == "new_player"}
        n = 0
        for x in d.get("data", []):
            a = x["attributes"]
            if a.get("odds_type") != "standard" or a["stat_type"] not in STATS:
                continue
            if datetime.datetime.fromisoformat(a["start_time"]).astimezone(CT).date().isoformat() != day:
                continue
            n += 1
            rule = RULE.get((lab, a["stat_type"]))
            if not rule:
                continue
            p = PLR[x["relationships"]["new_player"]["data"]["id"]]; pl = nn(p["name"]); ln = float(a["line_score"])
            pr = [val(r, a["stat_type"], pers) for r in H.get(pl, []) if r[0] < day]
            if len(pr) < 5:
                continue
            f = dict(su=sum(v < ln for v in pr) / len(pr), med_rel=(statistics.median(pr) - ln) / max(ln, 1), avg_rel=(statistics.mean(pr) - ln) / max(ln, 1))
            if rule[1](f):
                st = datetime.datetime.fromisoformat(a["start_time"]).astimezone(CT).strftime("%I:%M%p")
                print("  %-3s %-22s %-4s U%-5g %-14s | season under %2.0f%% | avg %.1f med %.1f | last 8: %s | %s CT  [%s]" % (
                    lab, p["name"][:22], p.get("team"), ln, a["stat_type"], 100 * f["su"], statistics.mean(pr), statistics.median(pr),
                    " ".join("%g" % v for v in pr[::-1][:8]), st, rule[2]))
        print("  (%s: %d standard lines on the board today)" % (lab, n))


today()
