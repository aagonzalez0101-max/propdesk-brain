"""OVER MODEL (11/17, user: "why their models are overs, and why we cant make one that works also?" -> "yes run the overs model too").
Overs lose on average because PP's line sits near the TYPICAL game and averages run above it, and because streak / teammate-out bumps
are priced before we see them. So this searches only for things a line can MISS, on top of edge_rows.json (_edge_research.py, pregame
prices only):
    typical-game (median) projection above the line      close spread (starters play the whole game)      high game total
    opponent on a back-to-back / rest advantage             a 28+ mpg teammate NEWLY out (played the team's previous game, not this one)
    soft defense vs his type, PP line below the sharp main line, market 52%+
Walk-forward (found on the first half of the days, must hold on the second half) + slip replay via _es_research.search. NBA only.
    python _over_model.py
"""
import json, sqlite3, collections, datetime, re, unicodedata, os, urllib.request, statistics
import _es_research as E

nn = lambda s: re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())
S = sqlite3.connect("sports.db")
BOX = {}; TEAMG = collections.defaultdict(lambda: collections.defaultdict(set)); MPG = collections.defaultdict(list)
for g, d, pl, tm, opp, mn in S.execute("select game_id, date, player, team, opp, min from nba_box where date>='2026-10-20' and min>0"):
    BOX[(d, nn(pl))] = (g, tm, opp)
    TEAMG[tm][d].add(nn(pl)); MPG[(tm, nn(pl))].append((d, mn))
TEAMD = {t: sorted(v) for t, v in TEAMG.items()}

# closing spread / total per GAME from ESPN game summaries (pickcenter; the scoreboard drops odds once a game is final). Cached.
CACHE = "_nba_odds_cache.json"
odds = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
if odds and not any(isinstance(v, dict) and "sp" in v for v in odds.values()):
    odds = {}                                                   # old scoreboard-format cache -> rebuild
from concurrent.futures import ThreadPoolExecutor


def fetch(g):
    try:
        s = json.load(urllib.request.urlopen(urllib.request.Request("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=%s" % g,
                                                                   headers={"User-Agent": "Mozilla/5.0"}), timeout=30))
        pc = (s.get("pickcenter") or [{}])[0]
        comp = s["header"]["competitions"][0]["competitors"]
        home = next(c["team"]["abbreviation"] for c in comp if c.get("homeAway") == "home")
        away = next(c["team"]["abbreviation"] for c in comp if c.get("homeAway") == "away")
        sp = pc.get("spread")                                    # ESPN: spread is from the HOME team's side (-14.5 = home favoured by 14.5)
        return g, {"sp": {home: -sp, away: sp} if sp is not None else {}, "tot": pc.get("overUnder")}
    except Exception:
        return g, None


need = sorted({b[0] for b in BOX.values()} - set(odds))
with ThreadPoolExecutor(8) as ex:
    for g, v in ex.map(fetch, need):
        if v:
            odds[g] = v
json.dump(odds, open(CACHE, "w"))


def rest(team, d):
    ds = [x for x in TEAMD.get(team, []) if x < d]
    return (datetime.date.fromisoformat(d) - datetime.date.fromisoformat(ds[-1])).days if ds else 9


def new_star_out(team, d, me):
    ds = [x for x in TEAMD.get(team, []) if x < d]
    if not ds:
        return False
    prev, now = TEAMG[team][ds[-1]], TEAMG[team].get(d, set())
    for p in prev - now - {me}:
        m = [mn for dd, mn in MPG[(team, p)] if dd < d]
        if len(m) >= 3 and statistics.mean(m) >= 28:
            return True
    return False


R = [r for r in json.load(open("edge_rows.json")) if r["sp"] == "nba" and r["real"]]
rows = []
for r in R:
    b = BOX.get((r["day"], nn(r["player"])))
    if not b:
        continue
    g, tm, opp = b
    o_ = odds.get(g) or {}; sp = (o_.get("sp") or {}).get(tm); tot = o_.get("tot")
    rt, ro = rest(tm, r["day"]), rest(opp, r["day"])
    f = {"median 10%+ above line": r["med_rel"] >= .10, "median 20%+ above line": r["med_rel"] >= .20,
         "season 60%+ over": r["so"] >= .6, "close spread (< 6)": sp is not None and abs(sp) < 6,
         "team favoured 6+": sp is not None and sp >= 6, "team underdog 6+": sp is not None and sp <= -6,
         "high total (230+)": tot is not None and tot >= 230, "low total (<= 222)": tot is not None and tot <= 222,
         "opp on back-to-back": ro == 1, "rest advantage (he rested more)": rt > ro, "he is on a back-to-back": rt == 1,
         "28+ mpg teammate NEWLY out": new_star_out(tm, r["day"], nn(r["player"])),
         "soft D vs type (8%+)": r["defn"] is not None and r["defn"] >= .08, "big line (20.5+)": r["line"] >= 20.5,
         "starter (30+ min)": r["min5"] >= 30, "minutes rising (L3 110%+)": r["min_tr"] >= 1.10,
         "PP line below sharp main line": r["gap"] is not None and r["gap"] < 0,
         "market 52%+ over": r["mkt"] is not None and r["mkt"] >= .52, "PP dropped the line": r["move"] < 0}
    rows.append(dict(day=r["day"], who=r["player"], game=g, won=bool(r["over"]),
                     rank=(r["mkt"] if r["mkt"] is not None else .5) + r["med_rel"] / 10, f=f))
print("NBA OVER MODEL: %d realistic over lines with box + odds, %d with a spread" % (len(rows), sum(1 for r in rows if r["f"]["close spread (< 6)"] or r["f"]["team favoured 6+"] or r["f"]["team underdog 6+"])))
base = sum(r["won"] for r in rows) / len(rows)
print("base: every realistic NBA over hits %.1f%%" % (100 * base))
for k in rows[0]["f"]:
    X = [r for r in rows if r["f"][k]]
    if X:
        print("  %-34s %4d-%-4d %5.1f%%" % (k, sum(r["won"] for r in X), len(X) - sum(r["won"] for r in X), 100 * sum(r["won"] for r in X) / len(X)))
E.search("NBA OVERS (walk-forward)", rows)
