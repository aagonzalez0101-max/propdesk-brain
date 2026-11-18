"""TENNIS STANDARD-LINE RESEARCH (11/18, user: "standard plays that has very good backtesting potential ... red clay court filter and
just courts in general, when they win/lose, favored ... form h2h, form in general").

PP's tennis standards sit near the market (our archive: standards 44-41). So the backtest rebuilds a PP-style line for every
completed best-of-3 ATP/WTA match 2019-2026 (tennis-data xlsx, Pinnacle odds, set scores): the half-point line where our
Pinnacle-fitted match model (_tennis_pp) says 50/50, for Total Games Won, Total Games and Fantasy (no aces/DF in the data, so
fantasy = 10 + GW - GL + 3*(SW - SL)). Then: does the over/under at that line beat 57.7% under any condition the model does
NOT use -- surface, indoor/outdoor, favourite size, form vs the market, head-to-head, rank, round?
FOUND on 2019-2022, must HOLD on 2023-2026.
    python _tennis_research.py
"""
import glob, collections, itertools, math, re, json
import pandas as pd
import _tennis_pp as T

import os
DEMON = os.environ.get("DEMON") == "1"     # 11/18: demon pass -- line where the model says ~35% over, b/e ~40%
TGT = .35 if DEMON else .5
BE = .40 if DEMON else .577
frames = []
for f in sorted(glob.glob("tennis/*_20*.xls*")):
    yr = int(re.search(r"(\d{4})", f).group(1))
    if yr < 2017:
        continue
    d = pd.read_excel(f); d["tour"] = "atp" if "atp_" in f else "wta"; d["yr"] = yr
    frames.append(d)
D = pd.concat(frames, ignore_index=True)
D = D.rename(columns={"Best of": "BestOf"}); D["Date"] = pd.to_datetime(D["Date"], errors="coerce"); D = D[D["Date"].notna()]; D = D.sort_values("Date").reset_index(drop=True)

# ---------- fitted model per (tour, p) -- p rounded to .01
LINES = {}


def model(tour, p):
    k = (tour, round(p, 2))
    if k not in LINES:
        hA, hB, _ = T.fit(k[1], None, tour)
        d, _ = T.summarize(hA, hB)
        out = {}
        for name, f in (("games won", lambda x: x[0]), ("total games", lambda x: x[0] + x[1]),
                        ("fantasy", lambda x: 10 + x[0] - x[1] + 3 * (x[2] - x[3]))):
            best = None
            for L in [v + .5 for v in range(-15, 45)]:
                po = T.p_over(d, f, L)
                if best is None or abs(po - TGT) < abs(best[1] - TGT):
                    best = (L, po)
            out[name] = best
        LINES[k] = out
    return LINES[k]


hist = collections.defaultdict(list)       # player -> [(won, market p)]
h2h = collections.defaultdict(int)          # (a, b) -> a's wins over b
rows = []
for r in D.itertuples(index=False):
    w, l = r.Winner, r.Loser
    pw_, pl_ = r.PSW, r.PSL
    if not (isinstance(pw_, (int, float)) and isinstance(pl_, (int, float)) and pw_ > 1 and pl_ > 1):
        pw_, pl_ = r.AvgW, r.AvgL
    ok = isinstance(pw_, (int, float)) and isinstance(pl_, (int, float)) and pw_ > 1 and pl_ > 1 and not math.isnan(pw_) and not math.isnan(pl_)
    pw = (1 / pw_) / (1 / pw_ + 1 / pl_) if ok else None
    sets = []
    for i in (1, 2, 3):
        a, b = getattr(r, "W%d" % i), getattr(r, "L%d" % i)
        if pd.notna(a) and pd.notna(b):
            sets.append((int(a), int(b)))
    good = ok and r.Comment == "Completed" and r.BestOf == 3 and len(sets) >= 2 and r.yr >= 2019
    if good:
        gw, gl = sum(a for a, b in sets), sum(b for a, b in sets)
        sw, sl = sum(a > b for a, b in sets), sum(b > a for a, b in sets)
        for me, op, p, my in ((w, l, pw, (gw, gl, sw, sl)), (l, w, 1 - pw, (gl, gw, sl, sw))):
            H = hist[me][-10:]
            form = (sum(x for x, _ in H) - sum(q for _, q in H)) if len(H) >= 5 else None   # wins above what the market expected
            hh = h2h[(me, op)] - h2h[(op, me)]; hn = h2h[(me, op)] + h2h[(op, me)]
            M = model(r.tour, p)
            act = {"games won": my[0], "total games": my[0] + my[1], "fantasy": 10 + my[0] - my[1] + 3 * (my[2] - my[3])}
            rk_me = r.WRank if me == w else r.LRank; rk_op = r.LRank if me == w else r.WRank
            rows.append(dict(day=r.Date.date().isoformat(), who=me, p=p, surf=r.Surface, court=r.Court, game=(r.Date, w, l), tour=r.tour, act=act, M=M, f={
                "CLAY": r.Surface == "Clay", "HARD": r.Surface == "Hard", "GRASS": r.Surface == "Grass", "INDOOR": r.Court == "Indoor",
                "ATP": r.tour == "atp", "WTA": r.tour == "wta",
                "fav 75%+": p >= .75, "fav 60-75%": .60 <= p < .75, "coin flip 40-60%": .40 <= p < .60, "dog 25-40%": .25 <= p < .40, "dog <25%": p < .25,
                "hot form (+2 wins vs mkt, L10)": form is not None and form >= 2, "cold form (-2)": form is not None and form <= -2,
                "won h2h (+1 or better)": hn > 0 and hh >= 1, "lost h2h (-1 or worse)": hn > 0 and hh <= -1, "no h2h": hn == 0,
                "top 30 player": pd.notna(rk_me) and rk_me <= 30, "opp ranked 100+": pd.notna(rk_op) and rk_op > 100,
                "early round (R1/R2)": r.Round in ("1st Round", "2nd Round"), "QF or later": r.Round in ("Quarterfinals", "Semifinals", "The Final")}))
    if ok:
        hist[w].append((1, pw)); hist[l].append((0, 1 - pw))
    h2h[(w, l)] += 1

print("TENNIS: %d player-match rows (best of 3, 2019-2026, Pinnacle/avg odds), %d model fits" % (len(rows), len(LINES)))
half = "2023-01-01"
if os.environ.get("TOPN") == "1":
    # 11/18 user: "only top 3-5 picks a day ... or 6 legs if spicy". Cells learned on 2019-22 ONLY, picked + graded on 2023-26.
    cell = lambda r, stat, side: "%s|%s|%s|%d|%s" % (stat, r["tour"], r["surf"], min(9, int(r["p"] * 10)), side)
    tr = collections.defaultdict(lambda: [0, 0])
    legs = []
    for r in rows:
        for stat in ("games won", "total games", "fantasy"):
            L, _ = r["M"][stat]; a = r["act"][stat]
            if a == L:
                continue
            for side in ("over", "under"):
                won = (a > L) if side == "over" else (a < L)
                if r["day"] < half:
                    c = tr[cell(r, stat, side)]; c[0] += won; c[1] += 1
                else:
                    legs.append((r["day"], r["game"], r["who"], cell(r, stat, side), won))
    rate = {k: (w + 50) / (n + 100) for k, (w, n) in tr.items() if n >= 200}       # shrunk toward 50%
    good = [(d, g, who, rate[c], won) for d, g, who, c, won in legs if rate.get(c, 0) >= .577]
    byday = collections.defaultdict(list)
    for x in good:
        byday[x[0]].append(x)
    print("cells beating 57.7%% on 2019-22: %d   test days 2023-26 with a qualifying leg: %d" % (sum(1 for v in rate.values() if v >= .577), len(byday)))
    for k in sorted(rate, key=lambda k: -rate[k])[:12]:
        print("   %-40s train %.1f%% n=%d" % (k, 100 * rate[k], tr[k][1]))
    for N in (3, 5, 6):
        W = Lw = 0; s2 = [0, 0]; s3 = [0, 0]; s6 = [0, 0]
        for d, X in byday.items():
            X.sort(key=lambda x: -x[3]); pick = []; gs = set()
            for x in X:
                if x[1] in gs:
                    continue
                gs.add(x[1]); pick.append(x)
                if len(pick) == N:
                    break
            W += sum(x[4] for x in pick); Lw += sum(not x[4] for x in pick)
            for i in range(0, len(pick) - 1, 2):
                s2[pick[i][4] and pick[i + 1][4]] += 1
            if len(pick) >= 3:
                s3[all(x[4] for x in pick[:3])] += 1
            if N == 6 and len(pick) == 6:
                s6[all(x[4] for x in pick)] += 1
        n2 = sum(s2); n3 = sum(s3)
        print("TOP %d/day: legs %d-%d (%.1f%%) | 2-picks %d-%d ROI %+.0f%% (3x) | 3-pick %d-%d ROI %+.0f%% (6x)%s" % (
            N, W, Lw, 100 * W / max(W + Lw, 1), s2[1], s2[0], 100 * (3 * s2[1] - n2) / max(n2, 1), s3[1], s3[0], 100 * (6 * s3[1] - n3) / max(n3, 1),
            (" | 6-pick %d-%d ROI %+.0f%% (37.5x)" % (s6[1], s6[0], 100 * (37.5 * s6[1] - sum(s6)) / max(sum(s6), 1))) if N == 6 else ""))
    raise SystemExit
if os.environ.get("CALIB") == "1":
    # 11/18: calibration table for _tennis_pp -- the over rate at the model's own 50/50 line, by stat x tour x surface x player win-prob bucket.
    # _tennis_pp shifts its P(over) by (rate - 0.5) of the matching cell (shrunk by n) so the PP pricer stops repeating the model's known biases.
    cal = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        b = min(9, int(r["p"] * 10))
        for stat in ("games won", "total games", "fantasy"):
            L, _ = r["M"][stat]; a = r["act"][stat]
            if a == L:
                continue
            for key in ("%s|%s|%s|%d" % (stat, r["tour"], r["surf"], b), "%s|%s|*|%d" % (stat, r["tour"], b)):
                cal[key][0] += a > L; cal[key][1] += 1
    json.dump({k: v for k, v in cal.items()}, open("tennis_calib.json", "w"))
    print("saved tennis_calib.json: %d cells" % len(cal))
    for k in sorted(cal):
        if "|*|" in k and cal[k][1] >= 300:
            print("   %-28s over %5.1f%%  n=%d" % (k, 100 * cal[k][0] / cal[k][1], cal[k][1]))
    raise SystemExit
for stat in ("games won", "total games", "fantasy"):
    for side in (("over",) if DEMON else ("over", "under")):
        R = []
        for r in rows:
            L, _ = r["M"][stat]; a = r["act"][stat]
            if a == L:
                continue
            R.append((r["day"] < half, (a > L) if side == "over" else (a < L), r["f"]))
        keys = list(R[0][2])
        base = sum(x[1] for x in R) / len(R)
        print("\n%s %s at the 50/50 model line: %.1f%% (n=%d)" % (stat.upper(), side.upper(), 100 * base, len(R)))
        res = []
        for c in [(k,) for k in keys] + list(itertools.combinations(keys, 2)) + list(itertools.combinations(keys, 3)):
            A = [x[1] for x in R if x[0] and all(x[2][k] for k in c)]; B = [x[1] for x in R if not x[0] and all(x[2][k] for k in c)]
            if len(A) >= 150 and len(B) >= 100:
                res.append((min(sum(A) / len(A), sum(B) / len(B)), c, sum(A), len(A), sum(B), len(B)))
        res.sort(key=lambda x: -x[0])
        for lo, c, aw, an, bw, bn in res[:6]:
            flag = "  <== HOLDS %.1f%%+" % (100 * BE) if lo >= BE else ""
            print("   %-70s 19-22 %5.1f%% (n=%5d)  23-26 %5.1f%% (n=%5d)%s" % (" + ".join(c)[:70], 100 * aw / an, an, 100 * bw / bn, bn, flag))
