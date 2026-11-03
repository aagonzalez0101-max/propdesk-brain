"""TENNIS PRIZEPICKS PRICER (11/3, user: "tennis -- they play overnight and all day on PP, a market we can abuse").

Every PP tennis line priced off Pinnacle. Pinnacle prices the winner, sets, total games, games spread and each player's
games (team totals); PP posts Total Games / Total Games Won / Fantasy Score / 1st Set Games / Sets / Tie Breaks. A match
model fitted to Pinnacle turns each PP number into a fair probability. Calibrated on 21,222 2022+ ATP/WTA matches.

MODEL: each player holds serve with a fixed probability (hA, hB). Exact DP over games -> tiebreak -> set -> best-of-3 gives
the joint distribution of games won, sets, tiebreaks and first-set games. (hA, hB) are fitted to Pinnacle's de-vigged
moneyline + total-games price; with no total posted, hA + hB is pinned to the tour's average holds. Pinnacle's team totals
are NOT used in the fit -- they are the out-of-sample check printed per match ("fit check").
PP fantasy (Rotowire): 10 per match + 1 per game won - 1 per game lost + 3 per set won - 3 per set lost + 1 ace - 1 DF,
no win bonus. Aces/DFs use tour averages per service game (free per-player serve data is offline) -- the soft part.

    python _tennis_pp.py            # price the board, flag edges, archive every priced line -> tennis_pp_paper.jsonl
    python _tennis_pp.py grade      # settle archived lines from ESPN set scores (games/sets/tiebreaks; not aces/DF)
PAPER until the archive grades a real sample -- no PP tennis lines were archived before 11/3, so there is no backtest yet.
"""
import sys, os, json, math, re, datetime, unicodedata, functools, requests
from concurrent.futures import ThreadPoolExecutor
import _ppcache as C

CT = __import__("zoneinfo").ZoneInfo("America/Chicago")
from _kbo import PIN, PH
OUT = "tennis_pp_paper.jsonl"
BE = {"standard": 1 / 3 ** 0.5, "goblin": 0.75, "demon": 0.40}     # PP 2-pick break-evens (goblin/demon: over only)
HOLD = {"atp": 0.825, "wta": 0.525, "chall": 0.80, "itf_w": 0.50, "itf_m": 0.75}   # fitted 11/3 on 21k 2022+ matches (with FORM below)
FORM = 0.20     # day-to-day form: hold gap is gap-0.2 / gap / gap+0.2 (25/50/25) -- without it the model had 10pp too many 3-setters
ACE = {"atp": 0.55, "wta": 0.25, "chall": 0.45, "itf_w": 0.18, "itf_m": 0.35}    # aces per service game, tour average
DF = {"atp": 0.30, "wta": 0.33, "chall": 0.32, "itf_w": 0.38, "itf_m": 0.33}     # double faults per service game


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", " ", s).split()


def tour_of(league):
    l = league.lower()
    if "itf" in l:
        return "itf_w" if "women" in l else "itf_m"
    if "challenger" in l:
        return "chall"
    return "wta" if "wta" in l else "atp"


# ------------------------------------------------------------------ the match model (exact DP)
def tb_win(pa, pb):
    """P(A wins a 7-point tiebreak) with A serving first; pa/pb = P(server wins a point)."""
    @functools.lru_cache(None)
    def f(a, b):
        if a >= 7 and a - b >= 2:
            return 1.0
        if b >= 7 and b - a >= 2:
            return 0.0
        if a >= 6 and b >= 6 and a == b:                   # deuce-like: two points, serve alternates each point
            n = a + b
            s1 = pa if ((n + 1) // 2) % 2 == 0 else 1 - pb
            s2 = pa if ((n + 2) // 2) % 2 == 0 else 1 - pb
            w2, l2 = s1 * s2, (1 - s1) * (1 - s2)
            return w2 / (w2 + l2) if w2 + l2 else 0.5
        n = a + b
        p = pa if ((n + 1) // 2) % 2 == 0 else 1 - pb      # A serves point 0, B points 1-2, A 3-4, ...
        return p * f(a + 1, b) + (1 - p) * f(a, b + 1)
    return f(0, 0)


def point_from_hold(h):
    """invert game-hold(p) -> p"""
    def hold(p):
        q = 1 - p
        return p ** 4 * (1 + 4 * q + 10 * q * q) + 20 * p ** 3 * q ** 3 * p * p / (1 - 2 * p * q)
    lo, hi = 0.3, 0.95
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if hold(mid) < h else (lo, mid)
    return (lo + hi) / 2


@functools.lru_cache(None)
def set_dist(hA, hB, a_first):
    """{(gA, gB, tiebreak): prob} for one set; a_first = A serves the first game."""
    pa, pb = point_from_hold(hA), point_from_hold(hB)
    tbA = tb_win(pa, pb) if a_first else 1 - tb_win(pb, pa)   # 13th "game": A serves first iff A served game 1
    out = {}
    def go(a, b, p):
        if p < 1e-12:
            return
        if (a == 6 and b <= 4) or (b == 6 and a <= 4) or a == 7 or b == 7:
            out[(a, b, 0)] = out.get((a, b, 0), 0) + p; return
        if a == 6 and b == 6:
            out[(7, 6, 1)] = out.get((7, 6, 1), 0) + p * tbA
            out[(6, 7, 1)] = out.get((6, 7, 1), 0) + p * (1 - tbA); return
        a_serves = ((a + b) % 2 == 0) == a_first
        w = hA if a_serves else 1 - hB
        go(a + 1, b, p * w); go(a, b + 1, p * (1 - w))
    go(0, 0, 1.0)
    return out


@functools.lru_cache(None)
def match_dist(hA, hB):
    """best of 3. {(gwA, gwB, setsA, setsB, tiebreaks, set1_games): prob}, coin-flip first server."""
    res = {}
    for a_first0, w0 in ((True, 0.5), (False, 0.5)):
        stack = [((0, 0, 0, 0, 0, None), a_first0, w0)]
        while stack:
            (ga, gb, sa, sb, tb, s1), af, p = stack.pop()
            if sa == 2 or sb == 2:
                k = (ga, gb, sa, sb, tb, s1); res[k] = res.get(k, 0) + p; continue
            for (x, y, t), q in set_dist(hA, hB, af).items():
                n = x + y                               # games in the set, the tiebreak counts as the 13th game
                nxt_af = af if n % 2 == 0 else not af
                stack.append(((ga + x, gb + y, sa + (x > y), sb + (y > x), tb + t, s1 if s1 is not None else x + y), nxt_af, p * q))
    return res


@functools.lru_cache(None)
def mixed(hA, hB):
    """real matches are more lopsided than a fixed-hold model: one player is simply better on the day. Mix the hold gap
    +-FORM. Calibrated 11/3: ATP P(3 sets) model .34 vs actual .37, games 23.4 vs 23.6; WTA .38/.35, 22.3/22.0
    (fixed-hold model was .46/.37 and 24.9/23.6)."""
    out = {}
    for e, w in ((-FORM, .25), (0, .5), (FORM, .25)):
        a = round(min(.97, max(.25, hA + e / 2)), 3); b = round(min(.97, max(.25, hB - e / 2)), 3)
        for k, p in match_dist(a, b).items():
            out[k] = out.get(k, 0) + w * p
    return out


def summarize(hA, hB):
    d = mixed(round(hA, 3), round(hB, 3))
    pwin = sum(p for k, p in d.items() if k[2] == 2)
    return d, pwin


def p_over(d, f, line):
    return sum(p for k, p in d.items() if f(k) > line)


def fit(p_fav_A, total=None, tour="atp", three=None):
    """find (hA, hB) matching P(A wins) and, if given, (line, P(over)) for total games; else P(3 sets); else tour-average holds."""
    best = None
    target_sum = 2 * HOLD[tour]
    def err(hA, hB):
        d, pw = summarize(hA, hB)
        e = (pw - p_fav_A) ** 2
        if total:
            e += (p_over(d, lambda k: k[0] + k[1], total[0]) - total[1]) ** 2
        elif three is not None:
            e += (sum(p for k, p in d.items() if k[2] + k[3] == 3) - three) ** 2
        else:
            e += 0.25 * (hA + hB - target_sum) ** 2
        return e
    grid = [x / 100 for x in range(28, 97, 3)]
    for hA in grid:
        for hB in grid:
            e = err(hA, hB)
            if best is None or e < best[0]:
                best = (e, hA, hB)
    for step in (0.01, 0.004):
        _, a0, b0 = best
        for hA in [a0 + i * step for i in range(-3, 4)]:
            for hB in [b0 + i * step for i in range(-3, 4)]:
                if 0.3 < hA < 0.98 and 0.3 < hB < 0.98:
                    e = err(hA, hB)
                    if e < best[0]:
                        best = (e, hA, hB)
    return best[1], best[2], best[0]


def poisson_cdf_shift(mu_a, mu_d):
    """distribution of aces - DF (Skellam), as {value: prob} trimmed"""
    pa = [math.exp(-mu_a) * mu_a ** k / math.factorial(k) for k in range(30)]
    pd = [math.exp(-mu_d) * mu_d ** k / math.factorial(k) for k in range(30)]
    out = {}
    for i, x in enumerate(pa):
        for j, y in enumerate(pd):
            if x * y > 1e-9:
                out[i - j] = out.get(i - j, 0) + x * y
    return out


def fantasy_dist(d, who, tour):
    """PP fantasy for player A (who=0) or B (who=1)."""
    out = {}
    for k, p in d.items():
        gw, gl, sw, sl = (k[0], k[1], k[2], k[3]) if who == 0 else (k[1], k[0], k[3], k[2])
        base = 10 + gw - gl + 3 * (sw - sl)
        svc = (k[0] + k[1]) / 2
        for v, q in poisson_cdf_shift(ACE[tour] * svc, DF[tour] * svc).items():
            out[base + v] = out.get(base + v, 0) + p * q
    return out


# ------------------------------------------------------------------ Pinnacle
def devig2(a, b):
    ia = 1 / (1 + a / 100 if a > 0 else 1 - 100 / a); ib = 1 / (1 + b / 100 if b > 0 else 1 - 100 / b)
    return ia / (ia + ib)


def pinnacle():
    lg = requests.get(PIN + "/0.1/sports/33/leagues?all=false", headers=PH, timeout=25).json()
    def one(L):
        if "doubles" in L["name"].lower():
            return []
        try:
            mu = requests.get(PIN + "/0.1/leagues/%d/matchups" % L["id"], headers=PH, timeout=20).json()
            mk = requests.get(PIN + "/0.1/leagues/%d/markets/straight" % L["id"], headers=PH, timeout=20).json()
        except Exception:
            return []
        if not isinstance(mu, list) or not isinstance(mk, list):
            return []
        M = {}
        for m in mu:
            ps = m.get("participants", [])
            if m.get("type") != "matchup" or len(ps) != 2 or m.get("isLive"):
                continue
            base = m.get("parentId") or m["id"]
            g = M.setdefault(base, dict(league=L["name"], start=m.get("startTime")))
            if not m.get("parentId"):
                al = {p["alignment"]: p["name"] for p in ps}
                g.update(home=al.get("home"), away=al.get("away"))
            g.setdefault("ids", []).append((m["id"], "games" if m.get("parentId") else "sets"))
        idmap = {i: (b, kind) for b, g in M.items() for i, kind in g.get("ids", [])}
        for x in mk:
            if x.get("matchupId") not in idmap or x.get("isAlternate"):
                continue
            b, kind = idmap[x["matchupId"]]; g = M[b]
            px = {p.get("designation") or p.get("participantId"): p for p in x.get("prices", [])}
            per = x.get("period")
            if x["type"] == "moneyline" and per == 0 and "home" in px:
                g["ml"] = devig2(px["home"]["price"], px["away"]["price"])
            elif x["type"] == "total" and per == 0 and kind == "games" and "over" in px:
                g["total"] = (px["over"]["points"], devig2(px["over"]["price"], px["under"]["price"]))
            elif x["type"] == "total" and per == 0 and kind == "sets" and "over" in px and px["over"].get("points") == 2.5:
                g["three_sets"] = devig2(px["over"]["price"], px["under"]["price"])
            elif x["type"] == "total" and per == 1 and kind == "games" and "over" in px:
                g["set1"] = (px["over"]["points"], devig2(px["over"]["price"], px["under"]["price"]))
            elif x["type"] == "team_total" and per == 0 and kind == "games":
                side = x.get("side")
                pr = {p["designation"]: p for p in x["prices"]}
                if side in ("home", "away") and "over" in pr:
                    g["tt_" + side] = (pr["over"]["points"], devig2(pr["over"]["price"], pr["under"]["price"]))
        return [g | {"tour": tour_of(L["name"])} for g in M.values() if g.get("ml") is not None and g.get("home")]
    with ThreadPoolExecutor(12) as ex:
        return [g for r in ex.map(one, lg) for g in r]


# ------------------------------------------------------------------ PrizePicks
STATS = {"Total Games": lambda k, w: k[0] + k[1], "Total Games Won": lambda k, w: k[w], "Total Sets": lambda k, w: k[2] + k[3],
         "Total Tie Breaks": lambda k, w: k[4], "1st Set Total Games": lambda k, w: k[5]}


def pp_board():
    d = C.projections(5, 900)
    P = {i["id"]: i["attributes"] for i in d.get("included", []) if i["type"] == "new_player"}
    out = []
    for x in d["data"]:
        a = x["attributes"]
        if a.get("stat_type") not in list(STATS) + ["Fantasy Score"]:
            continue
        p = P.get(x["relationships"]["new_player"]["data"]["id"], {})
        out.append(dict(pid=x["id"], player=p.get("name"), opp=(a.get("description") or "").replace(" 1st Set", ""), stat=a["stat_type"],
                        line=float(a["line_score"]), kind=a.get("odds_type"), start=a["start_time"], promo=a.get("discount_name")))
    return out


def find_match(G, player, opp):
    ln, lo = norm(player)[-1:] , norm(opp)[-1:]
    for g in G:
        h, a = norm(g["home"]), norm(g["away"])
        if ln and lo and ((ln[0] in h and lo[0] in a) or (ln[0] in a and lo[0] in h)):
            return g, (0 if ln[0] in h else 1)
    return None, None


def run():
    G = pinnacle(); B = pp_board()
    now = datetime.datetime.now(datetime.timezone.utc)
    print("TENNIS PP PRICER -- %d PP lines (games/sets/fantasy), %d Pinnacle matches\n" % (len(B), len(G)))
    fitted = {}; rows = []
    for l in B:
        st = datetime.datetime.fromisoformat(l["start"])
        if st < now:
            continue
        g, side = find_match(G, l["player"], l["opp"])
        if not g:
            continue
        key = id(g)
        if key not in fitted:
            hA, hB, e = fit(g["ml"], g.get("total"), g["tour"], g.get("three_sets"))
            d, pw = summarize(hA, hB)
            chk = []
            for s, i in (("tt_home", 0), ("tt_away", 1)):
                if g.get(s):
                    chk.append("%s %s: model %.0f%% vs Pinnacle %.0f%%" % (["home", "away"][i], g[s][0],
                               100 * p_over(d, lambda k, i=i: k[i], g[s][0]), 100 * g[s][1]))
            if g.get("set1"):
                chk.append("set1 %s: model %.0f%% vs Pin %.0f%%" % (g["set1"][0], 100 * p_over(d, lambda k: k[5], g["set1"][0]), 100 * g["set1"][1]))
            fitted[key] = (d, hA, hB, chk)
        d, hA, hB, chk = fitted[key]
        if l["stat"] == "Fantasy Score":
            fd = fantasy_dist(d, side, g["tour"]); po = sum(p for v, p in fd.items() if v > l["line"]); pu = sum(p for v, p in fd.items() if v < l["line"])
        else:
            f = STATS[l["stat"]]
            po = p_over(d, lambda k: f(k, side), l["line"]); pu = sum(p for k, p in d.items() if f(k, side) < l["line"])
        be = BE.get(l["kind"], BE["standard"])
        if l["kind"] == "standard":
            side_take, p = ("over", po) if po >= pu else ("under", pu)
        else:
            side_take, p = "over", po
        r = dict(l, side=side_take, p=round(p, 4), be=round(be, 4), edge=round(p - be, 4), tour=g["tour"], league=g["league"],
                 hold=(round(hA if side == 0 else hB, 3), round(hB if side == 0 else hA, 3)), pin_win=round(g["ml"] if side == 0 else 1 - g["ml"], 3),
                 pin_total=g.get("total"), fit_check=chk, logged=now.isoformat())
        rows.append(r)
    rows.sort(key=lambda r: -r["edge"])
    print("%-22s %-20s %-20s %-9s %5s %-6s %5s  %5s  %s" % ("player", "vs", "stat", "type", "line", "side", "p", "b/e", "start CT"))
    for r in rows:
        if r["edge"] < 0.03:
            continue
        t = datetime.datetime.fromisoformat(r["start"]).astimezone(CT).strftime("%a %I:%M %p")
        print("%-22s %-20s %-20s %-9s %5.1f %-6s %4.0f%%  %4.0f%%  %s  [win %.0f%%, %s]" % (
            r["player"][:22], r["opp"][:20], r["stat"][:20], r["kind"], r["line"], r["side"].upper(), 100 * r["p"], 100 * r["be"], t,
            100 * r["pin_win"], r["league"][:18]))
    print("\nmodel fit checks (Pinnacle team totals / set-1 totals were NOT used in the fit):")
    for d, hA, hB, chk in list(fitted.values())[:12]:
        if chk:
            print("   " + " | ".join(chk))
    seen = set()
    if os.path.exists(OUT):
        seen = {json.loads(x)["pid"] for x in open(OUT, encoding="utf-8")}
    new = [r for r in rows if r["pid"] not in seen]
    with open(OUT, "a", encoding="utf-8") as f:
        for r in new:
            f.write(json.dumps(r) + "\n")
    print("\narchived %d new priced lines -> %s (%d priced, %d PP lines had no Pinnacle match)" % (len(new), OUT, len(rows), len(B) - len(rows)))


def grade():
    R = [json.loads(x) for x in open(OUT, encoding="utf-8")] if os.path.exists(OUT) else []
    H = {"User-Agent": "Mozilla/5.0"}; res = {}
    days = sorted({datetime.datetime.fromisoformat(r["start"]).astimezone(datetime.timezone.utc).date() for r in R if not r.get("result")})
    for day in days:
        for tour in ("atp", "wta"):
            try:
                j = requests.get("https://site.api.espn.com/apis/site/v2/sports/tennis/%s/scoreboard?dates=%s" % (tour, day.strftime("%Y%m%d")), headers=H, timeout=20).json()
            except Exception:
                continue
            for e in j.get("events", []):
                for gr in e.get("groupings", []):
                    for c in gr.get("competitions", []):
                        if not c["status"]["type"].get("completed"):
                            continue
                        cs = [x for x in c.get("competitors", []) if "athlete" in x]
                        if len(cs) != 2:
                            continue
                        ls = [[int(s.get("value") or 0) for s in x.get("linescores", [])] for x in cs]
                        if "retired" in json.dumps(c["status"]).lower():
                            continue
                        res[frozenset(norm(cs[0]["athlete"]["displayName"])[-1:] + norm(cs[1]["athlete"]["displayName"])[-1:])] = (cs, ls)
    n = 0
    for r in R:
        if r.get("result"):
            continue
        k = frozenset(norm(r["player"])[-1:] + norm(r["opp"])[-1:])
        if k not in res:
            continue
        cs, ls = res[k]
        me = 0 if norm(r["player"])[-1] in norm(cs[0]["athlete"]["displayName"]) else 1
        a, b = ls[me], ls[1 - me]
        sets_w = sum(x > y for x, y in zip(a, b)); sets_l = sum(y > x for x, y in zip(a, b))
        tbs = sum(1 for x, y in zip(a, b) if {x, y} == {6, 7})
        val = {"Total Games": sum(a) + sum(b), "Total Games Won": sum(a), "Total Sets": len(a), "Total Tie Breaks": tbs,
               "1st Set Total Games": a[0] + b[0] if a else None}.get(r["stat"])
        if val is None:
            continue                                      # fantasy needs aces/DF -- graded by hand for now
        r["actual"] = val
        r["result"] = "PUSH" if val == r["line"] else ("W" if (val > r["line"]) == (r["side"] == "over") else "L")
        n += 1
    with open(OUT, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r) + "\n" for r in R)
    g = [r for r in R if r.get("result") in ("W", "L")]
    for lab, sel in (("all priced", g), ("edge >= 3pp", [r for r in g if r["edge"] >= 0.03]), ("edge >= 6pp", [r for r in g if r["edge"] >= 0.06])):
        w = sum(r["result"] == "W" for r in sel)
        print("%-12s %d-%d %s" % (lab, w, len(sel) - w, ("(%.0f%%, mean model p %.0f%%)" % (100 * w / len(sel), 100 * sum(r["p"] for r in sel) / len(sel))) if sel else ""))
    print("graded %d new" % n)


if __name__ == "__main__":
    grade() if sys.argv[1:2] == ["grade"] else run()
