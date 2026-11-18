"""NFL EDGE RESEARCH (11/17, user: "keep testing like we did for nba and find an edge with any possible stat"). Every archived PP CLOSING
standard NFL line (cloud lines.db, league 9) graded against sports.db weekly stats, with AS-OF features: season hit rate at the line,
last 3, volume trend (targets / carries / attempts), opponent rank vs the position + stat (prior weeks only), spread + total
(nflverse), sharp market at PP's number (lines.db sharp), PP vs the sharp main line, PP line move. Walk-forward split by week and slip
replay via _es_research.search.
    python _nfl_research.py
"""
import json, sqlite3, collections, datetime, re, csv, io, urllib.request, statistics
import _es_research as E

CT = __import__("zoneinfo").ZoneInfo("America/Chicago")
norm = lambda s: re.sub(r"[^a-z]", "", (s or "").lower().replace("jr.", "").replace(" iii", "").replace(" ii", ""))
STAT = {"Receiving Yards": ("receiving_yards", "targets", "receiving yards"), "Rec Targets": ("targets", "targets", None),
        "Receptions": ("receptions", "targets", "receptions"), "Rush Yards": ("rushing_yards", "carries", "rushing yards"),
        "Rush Attempts": ("carries", "carries", "rush attempts"), "Rush+Rec Yds": ("rushing_yards+receiving_yards", "carries+targets", None),
        "Pass Yards": ("passing_yards", "attempts", "passing yards"), "Pass Attempts": ("attempts", "attempts", "pass attempts"),
        "Pass Completions": ("completions", "attempts", "pass completions")}
ev = lambda e, s: sum(float(s.get(k) or 0) for k in e.split("+"))
week_of = lambda day: 1 + (datetime.date.fromisoformat(day) - datetime.date(2026, 9, 8)).days // 7

# stats
S = sqlite3.connect("sports.db")
G = collections.defaultdict(dict); allowed = collections.defaultdict(lambda: collections.defaultdict(float))
for pl, wk, tm, opp, st in S.execute("select player, date, team, opp, stats from player_games where sport='NFL' and season='2026'"):
    s = json.loads(st); w = int(wk[1:])
    G[norm(pl)][w] = dict(team=tm, opp=opp, s=s)
    for e in {v[0] for v in STAT.values()}:
        allowed[(opp, e, s.get("position"))][w] += ev(e, s)


def opp_rank(opp, e, pos, before):
    per = {}
    for (t, ee, pp), wk in allowed.items():
        if ee == e and pp == pos:
            v = [x for w, x in wk.items() if w < before]
            if len(v) >= 3:
                per[t] = statistics.mean(v)
    if opp not in per:
        return None
    return sorted(per, key=lambda t: -per[t]).index(opp) + 1, len(per)       # 1 = allows the MOST


# spreads / totals (nflverse, free)
SP = {}
try:
    raw = urllib.request.urlopen(urllib.request.Request("https://github.com/nflverse/nfldata/raw/master/data/games.csv", headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read().decode()
    for r in csv.DictReader(io.StringIO(raw)):
        if r["season"] == "2026" and r["spread_line"]:
            sp = float(r["spread_line"]); tot = float(r["total_line"]) if r["total_line"] else None
            SP[(int(r["week"]), r["home_team"])] = (sp, tot); SP[(int(r["week"]), r["away_team"])] = (-sp, tot)
except Exception as e:
    print("nflverse:", e)

# sharp prices
L = sqlite3.connect("lines.db")
# 11/17 FIX: the cloud snapshots sharp prices hourly INCLUDING during games -- 47% of game-day NFL snapshots were after kickoff (live
# prices that already "know" the game). Only prices strictly BEFORE the PP start time count.
SH = collections.defaultdict(list)          # (player, stat) -> [(ts datetime, book, line, p)]
for book, pl, st, ln, p, ts in L.execute("select book, player, stat, line, p_over, ts from sharp where sport='NFL'"):
    SH[(pl, st)].append((datetime.datetime.fromisoformat(ts), book, ln, p))


def sharp(pl, st, start):
    t0 = datetime.datetime.fromisoformat(start); lo = t0 - datetime.timedelta(days=4); out = {}
    for ts, book, ln, p in SH.get((norm(pl), st), []):
        if lo <= ts < t0 and ((book, ln) not in out or ts > out[(book, ln)][0]):
            out[(book, ln)] = (ts, p)
    return out


close = {}
for pl, team, st, line, start, fs, ls in L.execute("select player, team, stat, line, start, first_seen, last_seen from pp where league=9 and kind='standard'"):
    if st not in STAT or not start:
        continue
    day = datetime.datetime.fromisoformat(start).astimezone(CT).date().isoformat()
    k = (week_of(day), norm(pl), st)
    o = close.setdefault(k, dict(pl=pl, day=day, start=start, open=(fs or "~", line), close=(ls or "", line)))
    if (fs or "~") < o["open"][0]:
        o["open"] = (fs, line)
    if (ls or "") > o["close"][0]:
        o["close"] = (ls, line)

rows = []
for (w, k, st), o in close.items():
    g = G.get(k, {}).get(w)
    if not g:
        continue
    e, vol, sst = STAT[st]; ln = o["close"][1]; act = ev(e, g["s"])
    if act == ln:
        continue
    prior = [G[k][x] for x in sorted(G[k]) if x < w]
    prior = [x for x in prior if ev(vol, x["s"]) > 0 or e.startswith("pass")]
    if len(prior) < 3:
        continue
    v = [ev(e, x["s"]) for x in prior]; vv = [ev(vol, x["s"]) for x in prior]
    pos = g["s"].get("position"); rk = opp_rank(g["opp"], e, pos, w)
    spr, tot = SP.get((w, g["team"]), (None, None))
    mk = gap = None
    if sst:
        b = sharp(o["pl"], sst, o["start"])
        ps = [p for (bk, l_), (_, p) in b.items() if l_ == ln]
        mk = sum(ps) / len(ps) if ps else None
        if b:
            gap = ln - min(b.items(), key=lambda kv: abs(kv[1][1] - .5))[0][1]
    trend = statistics.mean(vv[-3:]) / statistics.mean(vv) if statistics.mean(vv) else 1
    for side in ("over", "under"):
        o_ = side == "over"
        hit = lambda x: x > ln if o_ else x < ln
        m_side = None if mk is None else (mk if o_ else 1 - mk)
        rows.append(dict(day="W%02d" % w, who=k, game=(w, tuple(sorted((g["team"], g["opp"])))), won=hit(act),
                         rank=m_side if m_side is not None else .5, f={
            "OVER": o_, "UNDER": not o_,
            "season 60%+ this side": sum(map(hit, v)) / len(v) >= .6, "season 75%+ this side": sum(map(hit, v)) / len(v) >= .75,
            "last 3 all this side": all(hit(x) for x in v[-3:]),
            "volume rising (L3 >= 115%)": trend >= 1.15, "volume falling (L3 <= 85%)": trend <= .85,
            "opp allows most (top 8)": rk is not None and rk[0] <= 8, "opp allows least (bottom 8)": rk is not None and rk[0] > rk[1] - 8,
            "team favoured 3+": spr is not None and spr >= 3, "team underdog 3+": spr is not None and spr <= -3,
            "high total (47+)": tot is not None and tot >= 47, "low total (<= 41)": tot is not None and tot <= 41,
            "market 52%+ this side": m_side is not None and m_side >= .52, "market 55%+ this side": m_side is not None and m_side >= .55,
            "PP gives this side vs books": gap is not None and (gap < 0 if o_ else gap > 0),
            "PP moved line toward this side": (ln < o["open"][1]) if o_ else (ln > o["open"][1]),
            "yards stat": "Yards" in st or "Yds" in st, "volume stat (targets/att/rec)": st in ("Rec Targets", "Rush Attempts", "Pass Attempts", "Pass Completions", "Receptions"),
            "WR/TE": pos in ("WR", "TE"), "RB": pos == "RB", "QB": pos == "QB",
        }))
print("NFL: %d side-rows from %d graded PP closing lines (weeks %s)" % (len(rows), len(rows) // 2, ", ".join(sorted({r["day"] for r in rows}))))
E.search("NFL (split by week)", rows)
