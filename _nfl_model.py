"""NFL PROP MODEL (11/21, user: "start nfl tonight"). Same idea as _prop_model.py, for PP NFL full-game standard lines.
Rows: every archived PP closing standard line (lines.db league 9, W04+) for yards/receptions/targets/attempts/completions, graded on
nflverse play-by-play (through the latest week). As-of features per side: season hit rate, last-3 hit rate, avg/median vs line,
volume trend, opponent allowed vs position (prior weeks), team spread + game total (nflverse), sharp market at PP's number (pregame
only), PP line move, position + stat. Strict walk-forward by WEEK: week W is scored by a model trained on weeks < W only.
    python _nfl_model.py backtest            # top-N per week record, per-week split
    python _nfl_model.py today 2026-11-22    # score this week's lines -> top N + 2-pick slips (paper log nfl_model_paper.jsonl)
"""
import sys, json, sqlite3, collections, statistics, datetime, csv, io, urllib.request, math
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
import _nfl_period_fs as F
from _nfl_rules_today import games, STAT, ev, FIX

CT = __import__("zoneinfo").ZoneInfo("America/Chicago")
week_of = lambda day: 1 + (datetime.date.fromisoformat(day) - datetime.date(2026, 9, 8)).days // 7
STATS = sorted(STAT)
POS = ["QB", "RB", "WR", "TE"]
SHARP = {"Receiving Yards": "receiving yards", "Receptions": "receptions", "Rush Yards": "rushing yards", "Rush Attempts": "rush attempts",
         "Pass Yards": "passing yards", "Pass Attempts": "pass attempts", "Pass Completions": "pass completions"}
PAPER = "nfl_model_paper.jsonl"


def load():
    N = F.names(); S, META = games()
    P = collections.defaultdict(dict)                 # nn(name) -> week -> dict(team, opp, pos, s)
    for (pid, gid), s in S.items():
        wk, tm, opp = META[(pid, gid)]
        nm, pos = N.get(pid, (None, None))
        if nm:
            P[F.nn(nm)][wk] = dict(team=tm, opp=opp, pos=pos, s=s)
    allowed = collections.defaultdict(lambda: collections.defaultdict(float))     # (opp, expr, pos) -> wk -> total
    for k, W in P.items():
        for wk, g in W.items():
            for e in {v[0] for v in STAT.values()}:
                allowed[(g["opp"], e, g["pos"])][wk] += ev(e, g["s"])
    SP = {}
    try:
        raw = urllib.request.urlopen(urllib.request.Request("https://github.com/nflverse/nfldata/raw/master/data/games.csv",
                                                            headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read().decode()
        for r in csv.DictReader(io.StringIO(raw)):
            if r["season"] == "2026" and r["spread_line"]:
                sp = float(r["spread_line"]); tot = float(r["total_line"]) if r["total_line"] else None
                SP[(int(r["week"]), r["home_team"])] = (sp, tot, r["away_team"]); SP[(int(r["week"]), r["away_team"])] = (-sp, tot, r["home_team"])
    except Exception as e:
        print("nflverse games:", e)
    return P, allowed, SP


def opp_rel(allowed, opp, e, pos, before):
    mine = [x for w, x in allowed.get((opp, e, pos), {}).items() if w < before]
    allv = [x for (t, ee, pp), W in allowed.items() if ee == e and pp == pos for w, x in W.items() if w < before]
    if len(mine) < 3 or not allv or statistics.mean(allv) == 0:
        return None
    return statistics.mean(mine) / statistics.mean(allv) - 1


def sharp_index():
    L = sqlite3.connect("lines.db"); SH = collections.defaultdict(list)
    for book, pl, st, ln, p, ts in L.execute("select book, player, stat, line, p_over, ts from sharp where sport='NFL'"):
        SH[(pl, st)].append((datetime.datetime.fromisoformat(ts), ln, p))
    return SH


def market(SH, pl, st, ln, start):
    if st not in SHARP:
        return None
    import re, unicodedata
    n = re.sub(r"[^a-z]", "", (pl or "").lower().replace("jr.", "").replace(" iii", "").replace(" ii", ""))
    t0 = datetime.datetime.fromisoformat(start); best = {}
    for ts, l_, p in SH.get((n, SHARP[st]), []):
        if l_ == ln and t0 - datetime.timedelta(days=4) <= ts < t0:
            best[ts] = p
    return best[max(best)] if best else None


def feat_row(P, allowed, SP, SH, pl, team, st, ln, start, w, opn):
    k = F.nn(pl); W = P.get(k, {})
    e, vol = STAT[st]
    prior = [W[x] for x in sorted(W) if x < w]
    prior = [g for g in prior if ev(vol, g["s"]) > 0]
    if len(prior) < 3:
        return None
    v = [ev(e, g["s"]) for g in prior]; vv = [ev(vol, g["s"]) for g in prior]
    pos = prior[-1]["pos"]; tm = FIX.get(team, team) if team else prior[-1]["team"]
    spr, tot, opp = SP.get((w, tm), (None, None, None))
    if opp is None:
        opp = W[w]["opp"] if w in W else None
    return dict(player=pl, team=tm, opp=opp, pos=pos, stat=st, line=ln, week=w, start=start,
                so=sum(x > ln for x in v) / len(v), l3=sum(x > ln for x in v[-3:]) / len(v[-3:]),
                avg_rel=(statistics.mean(v) - ln) / max(ln, 1), med_rel=(statistics.median(v) - ln) / max(ln, 1),
                trend=(statistics.mean(vv[-3:]) / statistics.mean(vv)) if statistics.mean(vv) else 1.0,
                opp_rel=opp_rel(allowed, opp, e, pos, w) if opp else None, spread=spr, total=tot,
                mkt=market(SH, pl, st, ln, start), move=ln - opn, n=len(v))


def side_feats(r, side):
    o = side == "over"; nz = lambda x: np.nan if x is None else float(x)
    f = [r["so"] if o else 1 - r["so"], r["l3"] if o else 1 - r["l3"], r["avg_rel"] if o else -r["avg_rel"],
         r["med_rel"] if o else -r["med_rel"], r["trend"], nz(r["opp_rel"]) if o else (np.nan if r["opp_rel"] is None else -r["opp_rel"]),
         nz(r["spread"]), nz(r["total"]), (nz(r["mkt"]) if o else (np.nan if r["mkt"] is None else 1 - r["mkt"])),
         (-r["move"]) if o else r["move"], r["n"], r["line"], 1.0 if o else 0.0]
    f += [1.0 if r["pos"] == p else 0.0 for p in POS] + [1.0 if r["stat"] == s else 0.0 for s in STATS]
    return f


def proj_ok(r, side):
    return (r["avg_rel"] > 0 and r["med_rel"] > 0) if side == "over" else (r["avg_rel"] < 0 and r["med_rel"] < 0)


def model():
    return HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=60, l2_regularization=1.0)


def graded_rows(P, allowed, SP, SH):
    L = sqlite3.connect("lines.db"); close = {}
    for pl, team, st, line, start, fs, ls in L.execute("select player, team, stat, line, start, first_seen, last_seen from pp where league=9 and kind='standard'"):
        if st not in STAT or not start:
            continue
        day = datetime.datetime.fromisoformat(start).astimezone(CT).date().isoformat()
        k = (week_of(day), F.nn(pl), st)
        o = close.setdefault(k, dict(pl=pl, team=team, start=start, open=(fs or "~", line), close=(ls or "", line)))
        if (fs or "~") < o["open"][0]:
            o["open"] = (fs, line)
        if (ls or "") > o["close"][0]:
            o["close"] = (ls, line)
    rows = []
    for (w, k, st), o in close.items():
        g = P.get(k, {}).get(w)
        if not g:
            continue
        ln = o["close"][1]; act = ev(STAT[st][0], g["s"])
        if act == ln:
            continue
        r = feat_row(P, allowed, SP, SH, o["pl"], o["team"], st, ln, o["start"], w, o["open"][1])
        if r:
            r["act"] = act; rows.append(r)
    return rows


def pick(m, rows, N):
    cand = [(r, s) for r in rows for s in ("over", "under")]
    if not cand:
        return []
    Pr = m.predict_proba(np.array([side_feats(r, s) for r, s in cand], dtype=float))[:, 1]
    used = set(); out = []
    for p, (r, s) in sorted(zip(Pr, cand), key=lambda t: -t[0]):
        if r["player"] in used or not proj_ok(r, s):
            continue
        used.add(r["player"]); out.append((float(p), r, s))
        if len(out) >= N:
            break
    return out


def backtest(Ns=(10, 20, 30)):
    P, allowed, SP = load(); SH = sharp_index()
    rows = graded_rows(P, allowed, SP, SH)
    weeks = sorted({r["week"] for r in rows})
    print("NFL model: %d graded closing lines, weeks %s" % (len(rows), weeks))
    res = {n: collections.defaultdict(lambda: [0, 0]) for n in Ns}; log = []
    for w in weeks:
        tr = [r for r in rows if r["week"] < w]
        if len(tr) < 600:
            continue
        X = np.array([side_feats(r, s) for r in tr for s in ("over", "under")], dtype=float)
        y = np.array([int((r["act"] > r["line"]) == (s == "over")) for r in tr for s in ("over", "under")])
        m = model(); m.fit(X, y)
        top = pick(m, [r for r in rows if r["week"] == w], max(Ns))
        for i, (p, r, s) in enumerate(top):
            win = (r["act"] > r["line"]) == (s == "over")
            for n in Ns:
                if i < n:
                    res[n][w][0] += win; res[n][w][1] += 1
            log.append(dict(week=w, rank=i + 1, player=r["player"], stat=r["stat"], line=r["line"], side=s, p=round(p, 3), act=r["act"], win=win,
                            pos=r["pos"]))
    json.dump(log, open("nfl_model_bt.json", "w"), indent=0)
    for n in Ns:
        tot_w = sum(a for a, b in res[n].values()); tot_n = sum(b for a, b in res[n].values())
        z = (tot_w / tot_n - .577) / math.sqrt(.577 * .423 / tot_n) if tot_n else 0
        print("  top %-2d/week: %s | all %d-%d (%.1f%%) z vs b/e %+.1f" % (n, "  ".join("W%d %d/%d" % (w, a, b) for w, (a, b) in sorted(res[n].items())),
              tot_w, tot_n - tot_w, 100 * tot_w / max(tot_n, 1), z))
    agg = collections.defaultdict(lambda: [0, 0])
    for x in log:
        if x["rank"] <= 20:
            for k in (x["side"], x["pos"], x["stat"]):
                agg[k][0] += x["win"]; agg[k][1] += 1
    print("  top-20 split: " + " | ".join("%s %d/%d" % (k, a, b) for k, (a, b) in sorted(agg.items(), key=lambda t: -t[1][1])))


def today(day, N=20):
    P, allowed, SP = load(); SH = sharp_index()
    rows = graded_rows(P, allowed, SP, SH)
    X = np.array([side_feats(r, s) for r in rows for s in ("over", "under")], dtype=float)
    y = np.array([int((r["act"] > r["line"]) == (s == "over")) for r in rows for s in ("over", "under")])
    m = model(); m.fit(X, y)
    w = week_of(day); L = sqlite3.connect("lines.db"); cur = {}
    for pl, team, st, line, start, fs, ls in L.execute("select player, team, stat, line, start, first_seen, last_seen from pp where league=9 and kind='standard' and start>=? and start<?",
                                                       (day, (datetime.date.fromisoformat(day) + datetime.timedelta(days=2)).isoformat())):
        if st not in STAT:
            continue
        k = (pl, st); o = cur.setdefault(k, dict(team=team, start=start, open=line, last=(ls or "", line), fs=fs or "~"))
        if (fs or "~") < o["fs"]:
            o["fs"] = fs; o["open"] = line
        if (ls or "") > o["last"][0]:
            o["last"] = (ls, line)
    live = [r for r in (feat_row(P, allowed, SP, SH, pl, o["team"], st, o["last"][1], o["start"], w, o["open"]) for (pl, st), o in cur.items()) if r]
    top = pick(m, live, N)
    game = lambda r: tuple(sorted([r["team"] or "", r["opp"] or ""]))
    pool = list(top); slips = []
    while len(pool) >= 2:
        a = pool.pop(0); b = next((x for x in pool if game(x[1]) != game(a[1])), None)
        if not b:
            break
        pool.remove(b); slips.append((a, b))
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    with open(PAPER, "a", encoding="utf-8") as f:
        for i, (p, r, s) in enumerate(top, 1):
            f.write(json.dumps(dict(kind="leg", day=day, week=w, rank=i, player=r["player"], team=r["team"], opp=r["opp"], stat=r["stat"],
                                    line=r["line"], side=s, p=round(p, 3), start=r["start"], logged=ts, result=None)) + "\n")
        for j, (a, b) in enumerate(slips, 1):
            f.write(json.dumps(dict(kind="slip", day=day, slip=j, legs=[[x[1]["player"], x[1]["stat"], x[1]["line"], x[2]] for x in (a, b)],
                                    logged=ts, result=None)) + "\n")
    print("NFL MODEL TOP %d -- week %d (%s), %d lines scored" % (N, w, day, len(live)))
    for i, (p, r, s) in enumerate(top, 1):
        print("  %2d. %-22s %-3s %-2s v %-3s %-16s %s%-6g model %.0f%%  season %.0f%% this side  %s" % (
            i, r["player"][:22], r["team"], r["pos"], r["opp"], r["stat"][:16], s[0].upper(), r["line"], 100 * p,
            100 * (r["so"] if s == "over" else 1 - r["so"]), datetime.datetime.fromisoformat(r["start"]).astimezone(CT).strftime("%a %I:%M%p")))
    print("  slips (2-picks, distinct games):")
    for j, (a, b) in enumerate(slips, 1):
        print("   %d. %s %s%g %s  +  %s %s%g %s" % (j, a[1]["player"], a[2][0].upper(), a[1]["line"], a[1]["stat"], b[1]["player"], b[2][0].upper(), b[1]["line"], b[1]["stat"]))


if __name__ == "__main__":
    if sys.argv[1:2] == ["backtest"]:
        backtest()
    elif sys.argv[1:2] == ["today"]:
        today(sys.argv[2] if len(sys.argv) > 2 else datetime.date.today().isoformat())
