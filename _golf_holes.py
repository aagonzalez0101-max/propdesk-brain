"""GOLF HOLE STATS vs PRIZEPICKS (11/18, user: "lets build golf ... its priority these next few hours").

The strokes model graded 50/50 vs PP (10/8). This tests the COUNTING stats PP posts with both sides open -- Birdies Or Better, Pars,
Bogeys or Worse -- straight against every archived PP line (cloud lines.db, league 1), graded from ESPN hole-by-hole scorecards
(free: leaderboard/{event}/playersummary?player=ID -> scoreType per hole).
    python _golf_holes.py grade     # closing PP line per player/round/stat -> golf_pp_graded.json, over/under by stat, kind, line
    python _golf_holes.py rates     # player hole-type rates (for the model) from the cached scorecards
"""
import sys, os, json, re, sqlite3, datetime, collections, unicodedata, urllib.request, statistics
from concurrent.futures import ThreadPoolExecutor

CT = __import__("zoneinfo").ZoneInfo("America/Chicago")
H = {"User-Agent": "Mozilla/5.0"}
CACHE = "_golf_cards"
nn = lambda s: re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())
STATS = {"Birdies Or Better": ("BIRDIE", "EAGLE", "DOUBLE_EAGLE", "ALBATROSS", "HOLE_IN_ONE"), "Pars": ("PAR",),
         "Bogeys or Worse": ("BOGEY", "DOUBLE_BOGEY", "TRIPLE_BOGEY", "QUADRUPLE_BOGEY", "OTHER")}


def card(tour, eid, pid):
    os.makedirs(CACHE, exist_ok=True)
    fn = os.path.join(CACHE, "%s_%s.json" % (eid, pid))
    if os.path.exists(fn):
        return json.load(open(fn, encoding="utf-8"))
    u = "https://site.web.api.espn.com/apis/site/v2/sports/golf/%s/leaderboard/%s/playersummary?player=%s" % (tour, eid, pid)
    try:
        d = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=60).read())
    except Exception:
        return None
    out = {}
    for r in d.get("rounds") or []:
        holes = r.get("linescores") or []
        if len(holes) == 18:
            out[str(r["period"])] = [((h.get("scoreType") or {}).get("name") or "OTHER") for h in holes]
    json.dump(out, open(fn, "w"))
    return out


def count(holes, stat):
    names = STATS[stat]
    if stat == "Bogeys or Worse":
        return sum(1 for h in holes if h not in STATS["Birdies Or Better"] and h != "PAR")
    return sum(1 for h in holes if h in names)


def rounds_index():
    """(norm player, CT date) -> (tour, event, player_id, round), straight from ESPN PGA leaderboards since 9/25 (tee time per round).
    golf_rounds.jsonl misses rounds for events pulled mid-week, so the leaderboards are read fresh (cached per event)."""
    ix = {}
    g = lambda u: json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=60).read())
    cal = (g("https://site.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard?dates=2026").get("leagues") or [{}])[0].get("calendar") or []
    evs = [c["id"] for c in cal if "2026-09-25" <= (c.get("startDate") or "")[:10] <= datetime.date.today().isoformat()]
    os.makedirs(CACHE, exist_ok=True)
    for eid in evs:
        fn = os.path.join(CACHE, "lb_%s.json" % eid)
        if os.path.exists(fn):
            comp = json.load(open(fn, encoding="utf-8"))
        else:
            try:
                d = g("https://site.web.api.espn.com/apis/site/v2/sports/golf/leaderboard?event=%s" % eid)
            except Exception:
                continue
            comp = [dict(id=c.get("id"), name=(c.get("athlete") or {}).get("displayName"),
                         tees=[(r.get("period"), r.get("teeTime")) for r in c.get("linescores") or []])
                    for c in ((d.get("events") or [{}])[0].get("competitions") or [{}])[0].get("competitors", [])]
            json.dump(comp, open(fn, "w"))
        for c in comp:
            for per, tee in c["tees"]:
                if tee:
                    dd = datetime.datetime.fromisoformat(tee.replace("Z", "+00:00")).astimezone(CT).date().isoformat()
                    ix[(nn(c["name"]), dd)] = ("pga", eid, c["id"], per)
    return ix


def grade():
    L = sqlite3.connect("lines.db")
    close = {}
    for pl, st, line, kind, start, ls in L.execute("select player, stat, line, kind, start, last_seen from pp where league=1"):
        if st not in STATS or not start:
            continue
        d = datetime.datetime.fromisoformat(start).astimezone(CT).date().isoformat()
        k = (nn(pl), d, st, kind)
        if k not in close or (ls or "") > close[k][1]:
            close[k] = (line, ls or "", pl)
    ix = rounds_index()
    jobs = []
    for (p, d, st, kind), (line, _, pl) in close.items():
        m = ix.get((p, d))
        if m:
            jobs.append((m, p, d, st, kind, line, pl))
    need = sorted({(m[0], m[1], m[2]) for m, *_ in jobs})
    print("PP golf lines: %d closing lines, %d matched to an ESPN round, %d scorecards to fetch" % (len(close), len(jobs), len(need)))
    with ThreadPoolExecutor(8) as ex:
        cards = dict(zip(need, ex.map(lambda t: card(*t), need)))
    rows = []
    for (tour, eid, pid, rnd), p, d, st, kind, line, pl in jobs:
        c = cards.get((tour, eid, pid)) or {}
        h = c.get(str(rnd))
        if not h:
            continue
        a = count(h, st)
        rows.append(dict(player=pl, date=d, stat=st, kind=kind, line=line, act=a, tour=tour, event=eid, rnd=rnd))
    json.dump(rows, open("golf_pp_graded.json", "w"))
    print("graded %d lines\n" % len(rows))
    for st in STATS:
        for kind in ("standard", "goblin", "demon"):
            X = [r for r in rows if r["stat"] == st and r["kind"] == kind and r["act"] != r["line"]]
            if not X:
                continue
            o = sum(r["act"] > r["line"] for r in X)
            print("%-18s %-8s n=%4d  OVER %5.1f%%  UNDER %5.1f%%   mean line %.2f  mean actual %.2f  median actual %.1f" % (
                st, kind, len(X), 100 * o / len(X), 100 * (1 - o / len(X)), statistics.mean(r["line"] for r in X),
                statistics.mean(r["act"] for r in X), statistics.median(r["act"] for r in X)))
        X = [r for r in rows if r["stat"] == st and r["kind"] == "standard" and r["act"] != r["line"]]
        for ln in sorted({r["line"] for r in X}):
            Y = [r for r in X if r["line"] == ln]
            if len(Y) >= 15:
                o = sum(r["act"] > ln for r in Y)
                print("     line %4.1f  n=%3d  over %5.1f%%  under %5.1f%%" % (ln, len(Y), 100 * o / len(Y), 100 * (1 - o / len(Y))))
        for t in ("pga", "eur", "lpga"):
            Y = [r for r in X if r["tour"] == t]
            if Y:
                o = sum(r["act"] > r["line"] for r in Y)
                print("     %-5s n=%3d  over %5.1f%%" % (t, len(Y), 100 * o / len(Y)))
        for rd in (1, 2, 3, 4):
            Y = [r for r in X if r["rnd"] == rd]
            if Y:
                o = sum(r["act"] > r["line"] for r in Y)
                print("     R%d    n=%3d  over %5.1f%%" % (rd, len(Y), 100 * o / len(Y)))




# ------------------------------------------------------------------ player model (walk-forward on the archived PP lines)
def season_cards(players):
    """every 2026 PGA event: leaderboard (cached) -> scorecards for the given players (norm names). Returns rows per player-round."""
    g = lambda u: json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=60).read())
    cal = (g("https://site.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard?dates=2026").get("leagues") or [{}])[0].get("calendar") or []
    evs = [(c["id"], (c.get("startDate") or "")[:10]) for c in cal if (c.get("startDate") or "")[:10] <= datetime.date.today().isoformat()]
    jobs = []
    for eid, sd in evs:
        fn = os.path.join(CACHE, "lb_%s.json" % eid)
        if not os.path.exists(fn):
            try:
                d = g("https://site.web.api.espn.com/apis/site/v2/sports/golf/leaderboard?event=%s" % eid)
            except Exception:
                continue
            try:
                comp = [dict(id=c.get("id"), name=(c.get("athlete") or {}).get("displayName"),
                             tees=[(r.get("period"), r.get("teeTime")) for r in c.get("linescores") or []])
                        for c in ((d.get("events") or [{}])[0].get("competitions") or [{}])[0].get("competitors", [])]
            except Exception:
                comp = []                                  # team events / odd formats
            json.dump(comp, open(fn, "w"))
        for c in json.load(open(fn, encoding="utf-8")):
            if nn(c["name"]) in players:
                jobs.append((eid, sd, c))
    print("season cards: %d events, %d player-events to read" % (len(evs), len(jobs)), flush=True)
    with ThreadPoolExecutor(8) as ex:
        cards = list(ex.map(lambda j: card("pga", j[0], j[2]["id"]), jobs))
    rows = []
    for (eid, sd, c), cd in zip(jobs, cards):
        tees = dict((str(p), t) for p, t in c["tees"])
        for rnd, h in (cd or {}).items():
            t = tees.get(rnd)
            d = datetime.datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(CT).date().isoformat() if t else sd
            rows.append(dict(p=nn(c["name"]), event=eid, rnd=int(rnd), date=d, **{s: count(h, s) for s in STATS}))
    return rows


def model():
    from math import comb
    G = json.load(open("golf_pp_graded.json"))
    players = {nn(r["player"]) for r in G}
    R = season_cards(players)
    byp = collections.defaultdict(list)
    for r in R:
        byp[r["p"]].append(r)
    ev = collections.defaultdict(list)                       # event -> rounds (for the course factor: same-event earlier rounds)
    for r in R:
        ev[r["event"]].append(r)
    tour = {s: statistics.mean(r[s] for r in R) for s in STATS}
    print("tour averages per round:", {s: round(v, 2) for s, v in tour.items()})
    out = []
    for g_ in G:
        if g_["kind"] != "standard":
            continue
        s, L = g_["stat"], g_["line"]
        past = [r for r in byp.get(nn(g_["player"]), []) if r["date"] < g_["date"]]
        if len(past) < 8:
            continue
        k = 12                                                 # shrink toward the tour mean
        rate = (sum(r[s] for r in past) + k * tour[s]) / (len(past) + k)
        prior = [r[s] for r in ev.get(g_["event"], []) if r["date"] < g_["date"]]
        cf = (statistics.mean(prior) / tour[s]) if len(prior) >= 20 else 1.0
        mu = min(17.5, max(0.2, rate * cf)); p = mu / 18
        po = sum(comb(18, x) * p ** x * (1 - p) ** (18 - x) for x in range(19) if x > L)
        pu = sum(comb(18, x) * p ** x * (1 - p) ** (18 - x) for x in range(19) if x < L)
        if g_["act"] == L:
            continue
        side = "over" if po > pu else "under"; pm = max(po, pu) / (po + pu)
        out.append(dict(g_, mu=mu, side=side, pm=pm, won=(g_["act"] > L) == (side == "over"), n=len(past), cf=cf))
    for s in STATS:
        X = [o for o in out if o["stat"] == s]
        if not X:
            continue
        print("\n%s: %d graded standard lines with 8+ prior rounds" % (s, len(X)))
        for lo in (.5, .55, .577, .6, .65):
            Y = [o for o in X if o["pm"] >= lo]
            if Y:
                w = sum(o["won"] for o in Y)
                print("   model side %.0f%%+  %3d-%-3d  %5.1f%%   (over picks %d, under picks %d)" % (100 * lo, w, len(Y) - w, 100 * w / len(Y),
                      sum(o["side"] == "over" for o in Y), sum(o["side"] == "under" for o in Y)))
    json.dump(out, open("golf_model_graded.json", "w"))


def today():
    """PP league 1 board: standard Birdies / Pars / Bogeys lines -> the measured golf rules (11/18 paper):
         BOGEYS UNDER (blind 59.4% n=128; model-agrees 63.8% n=47) | PARS OVER when model 58%+ (60.2% n=89) |
         BIRDIES UNDER in R2/R3 (blind ~61% n=148; the player model does NOT help birdies)."""
    from math import comb
    import _ppcache as C
    d = C.projections(1, 300)
    P = {i["id"]: i["attributes"] for i in d.get("included", []) if i["type"] == "new_player"}
    B = []
    for x in d["data"]:
        a = x["attributes"]
        if a["stat_type"] in STATS and a.get("odds_type") == "standard":
            nm = P.get(x["relationships"]["new_player"]["data"]["id"], {}).get("name", "")
            B.append((nm, a["stat_type"], float(a["line_score"]), a["start_time"], a.get("allowed_wager_types"), a.get("description")))
    print("PP golf standard hole-stat lines: %d" % len(B))
    if not B:
        return
    R = season_cards({nn(b[0]) for b in B})
    tour = {s: statistics.mean(r[s] for r in R) for s in STATS}
    byp = collections.defaultdict(list)
    for r in R:
        byp[r["p"]].append(r)
    out = []
    for nm, st, L, start, sides, desc in B:
        past = byp.get(nn(nm), [])
        k = 12; rate = (sum(r[st] for r in past) + k * tour[st]) / (len(past) + k)
        p = min(.97, max(.01, rate / 18))
        po = sum(comb(18, x) * p ** x * (1 - p) ** (18 - x) for x in range(19) if x > L)
        pu = sum(comb(18, x) * p ** x * (1 - p) ** (18 - x) for x in range(19) if x < L)
        po, pu = po / (po + pu), pu / (po + pu)
        rnd = (desc or "")
        rule = ""
        if st == "Bogeys or Worse":
            rule = "BOGEYS UNDER" + (" + model %.0f%%" % (100 * pu) if pu >= .58 else "")
        elif st == "Pars" and po >= .58:
            rule = "PARS OVER (model %.0f%%)" % (100 * po)
        elif st == "Birdies Or Better":
            rule = "BIRDIES UNDER if R2/R3"
        t = datetime.datetime.fromisoformat(start).astimezone(CT).strftime("%a %I:%M %p")
        out.append((rule != "" and "if R2" not in rule, nm, st, L, rate, po, len(past), rule, t, sides))
    for ok, nm, st, L, rate, po, n, rule, t, sides in sorted(out, key=lambda o: (not o[0], o[2], -abs(o[5] - .5))):
        print("  %-24s %-18s %4.1f  his avg %4.2f (%3d rds)  P(over) %3.0f%%  %-26s %s %s" % (nm, st, L, rate, n, 100 * po, rule, t,
              "" if sides in (None, "") else "[only %s]" % sides))


if __name__ == "__main__":
    {"model": model, "today": today}.get((sys.argv[1:2] or ["grade"])[0], grade)()
