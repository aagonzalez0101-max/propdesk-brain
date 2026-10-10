"""DIRECTION MODEL (2026-10-07, user: "fuck trying to be so accurate that we are close to the lines -- figure out if it's gonna go
under or over"; then: "add more defense and offense rankings and efficiencies and do it again ... more research in depth").

    python _direction.py build     # every archived PP STANDARD line (NHL/WNBA/soccer) + its actual from sports.db -> _dir_rows.json
    python _direction.py test      # walk-forward by date: base (player vs line) vs + team offense / opponent defense features

Target = did it go OVER (pushes dropped). Every feature is AS-OF the day before the game (no leak): the player's own games and both
teams' games strictly before the game date.
"""
import os, sys, re, json, glob, math, sqlite3, datetime, collections

import unicodedata
norm = lambda s: re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())


def nkey(sp, name):
    """NHL boxes store 'A. Carrier' -> key on first initial + last name; everyone else on the full name."""
    if sp != "NHL":
        return norm(name)
    parts = (name or "").replace(".", ". ").split()
    return norm(parts[0][:1] + "".join(parts[1:])) if len(parts) > 1 else norm(name)
LEAGUES = {8: "NHL", 3: "WNBA", 82: "SOCCER", 7: "NBA"}
OUT = "_dir_rows.json"

# PP stat -> (player stat fields summed, team-level driver for the team's OFFENSE, team-level driver the OPPONENT ALLOWS)
STATMAP = {
    "NHL": {"shotsongoal": (("sog",), "sog", "sog"), "goals": (("goals",), "goals", "goals"), "assists": (("assists",), "goals", "goals"),
            "points": (("points",), "goals", "goals"), "hits": (("hits",), None, None), "blockedshots": (("blocks",), None, "sog")},
    "WNBA": {"points": (("pts",), "pts", "pts"), "rebounds": (("reb",), "reb", "reb"), "assists": (("ast",), "ast", "ast"),
             "ptsrebsasts": (("pts", "reb", "ast"), "pts", "pts"), "ptsrebs": (("pts", "reb"), "pts", "pts"), "ptsasts": (("pts", "ast"), "pts", "pts"),
             "rebsasts": (("reb", "ast"), "reb", "ast"), "3ptmade": (("tpm",), "tpm", "tpm")},
    "SOCCER": {"passesattempted": (("passes",), "passes", "passes"), "shots": (("shots",), "shots", "shots"),
               "shotsontarget": (("sot",), "sot", "sot"), "goaliesaves": (("saves",), None, None)},
}
STATMAP["WNBA"].update({"pointsrebounds": STATMAP["WNBA"]["ptsrebs"], "pointsassists": STATMAP["WNBA"]["ptsasts"],
                        "reboundsassists": STATMAP["WNBA"]["rebsasts"], "3pointersmade": STATMAP["WNBA"]["3ptmade"],
                        "pointsreboundsassists": STATMAP["WNBA"]["ptsrebsasts"]})
STATMAP["NBA"] = dict(STATMAP["WNBA"])                                   # same box-score fields (pts/reb/ast/tpm)
NBA_FIX = {"GSW": "GS", "NYK": "NY", "SAS": "SA", "NOP": "NO", "UTA": "UTAH", "WAS": "WSH"}   # PrizePicks -> ESPN (team_games)


def nba_ids():
    """ESPN numeric team id -> the abbreviation team_games uses (player_games stores ids, team_games abbreviations)."""
    try:
        import requests
        t = requests.get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams", timeout=30).json()["sports"][0]["leagues"][0]["teams"]
        return {x["team"]["id"]: x["team"]["abbreviation"] for x in t}
    except Exception:
        return {}


GOALIE_SAVES = {"NHL": ("goaliesaves", "saves"), "SOCCER": ("goaliesaves",)}


def pp_lines_db(kinds=("standard",)):
    """10/9 cloud move: the same last-seen line per projection id, read from lines.db (every PP change since 9/30, 25 MB) instead of
    the multi-GB raw archive; today's raw snapshots not yet compacted are layered on top."""
    import sqlite3
    best = {}
    c = sqlite3.connect("lines.db")
    for pid, lg, nm, team, stat, kind, line, start, fs, ls in c.execute(
            "SELECT proj_id, league, player, team, stat, kind, line, start, first_seen, last_seen FROM pp ORDER BY rowid"):
        if lg not in LEAGUES or kind not in kinds or "+" in (nm or ""):
            continue                                                   # same as the archive reader: keep the last STANDARD state
        b = best.get(pid)
        best[pid] = dict(kind=kind, first_line=b["first_line"] if b else line, nsnap=(b["nsnap"] if b else 0) + 1, sport=LEAGUES[lg],
                         player=nm, team=team, stat=stat, line=line, start=start, seen="%s-%s-%s" % (ls[:4], ls[5:7], ls[8:10]) if "-" in ls[:5] else ls[:10])
    raw = pp_lines(kinds, days=[datetime.datetime.now().strftime("%Y-%m-%d")])
    for r in raw:
        best.setdefault(("raw", r["player"], r["stat"], r["start"]), r)
    return [b for b in best.values() if b["kind"] in kinds]


def pp_lines(kinds=("standard",), days=None):
    if days is None and os.environ.get("PROPDESK_CLOUD"):
        return pp_lines_db(kinds)                                      # cloud: no raw archive history, use lines.db
    """last-seen line per projection id across every archived snapshot (standard by default; goblins on request -- 10/7 user:
    goblin pairs pay ~1.5-1.8x, goblin + standard ~2-2.2x)."""
    best = {}
    files = [f for d in days for f in __import__("_arch").files(os.path.join("lines_archive", d, "pp_*_*.json"))] if days else \
        __import__("_arch").files(os.path.join("lines_archive", "*", "pp_*_*.json"))
    for f in files:
        lg = int(os.path.basename(f).split("_")[1])
        if lg not in LEAGUES or os.path.getsize(f) < (120 if f.endswith(".gz") else 500):
            continue
        try:
            d = __import__("_arch").load(f)
        except Exception:
            continue
        inc = {(x["type"], x["id"]): x for x in d.get("included", [])}
        for x in d.get("data", []):
            at = x["attributes"]
            if at.get("odds_type") not in kinds:
                continue
            rel = (x.get("relationships") or {}).get("new_player", {}).get("data") or {}
            pl = inc.get(("new_player", rel.get("id")), {}).get("attributes", {})
            nm = pl.get("name") or ""
            if "+" in nm:
                continue                                               # combos out
            first = best.get(x["id"], {}).get("first_line", float(at["line_score"]))
            nsnap = best.get(x["id"], {}).get("nsnap", 0) + 1
            best[x["id"]] = dict(kind=at.get("odds_type"), first_line=first, nsnap=nsnap, sport=LEAGUES[lg], player=nm, team=pl.get("team"), stat=at.get("stat_type"), line=float(at["line_score"]),
                                 start=at.get("start_time"), seen=os.path.basename(os.path.dirname(f)))
    return list(best.values())


def calls_lines():
    """every line we ever logged (PP + UD) for NHL/WNBA/SOCCER. UD multipliers: lopsided (>=1.5 / <=0.7) = goblin-like -> dropped."""
    out = []
    for l in open("calls_log.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if r.get("sport") not in ("NHL", "WNBA", "SOCCER") or r.get("kind") in ("goblin", "demon") or r.get("line") is None:
            continue
        m = r.get("mult")
        if isinstance(m, dict):
            m = m.get("higher")
        try:
            m = float(m) if m is not None else None
        except (TypeError, ValueError):
            m = None
        if m is not None and (m >= 1.5 or m <= 0.7):
            continue
        st = r.get("start") or (r["date"] + "T19:00:00-04:00")
        try:
            datetime.datetime.fromisoformat(st.replace("Z", "+00:00"))
        except Exception:
            continue
        out.append(dict(sport=r["sport"], player=r["player"], team=r.get("team"), stat=r["stat"], line=float(r["line"]),
                        start=st.replace("Z", "+00:00"), first_line=None, nsnap=0, venue=r.get("venue") or "?", ud_mult=m if r.get("venue") == "UD" else None,
                        our_proj=r.get("proj"), our_call=r.get("call")))
    return out


def load_db():
    c = sqlite3.connect("sports.db")
    IDS = nba_ids()
    # player games by (sport, normalized name)
    pg = collections.defaultdict(list)
    for sp, date, gid, player, team, opp, mins, st, home in c.execute(
            "select sport,date,game_id,player,team,opp,minutes,stats,home from player_games where sport in ('NHL','WNBA','SOCCER','NBA') and date>='2024-09-01'"):
        if sp == "NBA":
            team, opp = IDS.get(team, team), IDS.get(opp, opp)
        pg[(sp, nkey(sp, player))].append((date, gid, team, opp, mins, json.loads(st), home))
    for k in pg:
        pg[k].sort(key=lambda x: (x[0], str(x[1])))
    tg = collections.defaultdict(list)                                  # (sport, team) -> [(date, for, against)]
    for sp, date, team, st, ost in c.execute("select sport,date,team,stats,opp_stats from team_games where sport in ('NHL','WNBA','SOCCER','NBA') and date>='2024-09-01'"):
        tg[(sp, team)].append((date, json.loads(st or "{}"), json.loads(ost or "{}")))
    for k in tg:
        tg[k].sort(key=lambda x: x[0])
    return pg, tg


TEAMFIX = {"NYL": "NY", "GSV": "GS", "LVA": "LV", "LAS": "LA", "WAS": "WSH", "CON": "CON", "PHO": "PHX", "SEA": "SEA", "MIN": "MIN",
           "IND": "IND", "ATL": "ATL", "CHI": "CHI", "DAL": "DAL", "TOR": "TOR", "POR": "POR", "CONN": "CON"}


def featurize(lines, pg, tg, live=False):
    """historical lines (live=False) need the game in sports.db for the ACTUAL; live lines use today's date + PP team/opp."""
    rows, miss = [], collections.Counter()
    LCACHE = {}
    seen = set()
    for l in lines:
        sp = l["sport"]; sk = norm(l["stat"])
        spec = STATMAP[sp].get(sk)
        if not spec:
            miss["stat:" + l["stat"]] += 1; continue
        games = pg.get((sp, nkey(sp, l["player"])))
        if games and sp == "NHL" and l.get("team"):
            tm = [x for x in games if x[2] == l["team"]]
            games = tm or games
        if not games:
            miss["no player"] += 1; continue
        try:
            sd = datetime.datetime.fromisoformat(l["start"]).astimezone(datetime.timezone(datetime.timedelta(hours=-5))).date()
        except Exception:
            miss["no start"] += 1; continue
        if live:
            gdate = sd.isoformat()
            team = games[-1][2]
            # 10/7 bug: Friday's NY lines were scored with "4+ days rest" because Wednesday's game wasn't in sports.db yet.
            # If the schedule shows a game for this team after our last recorded one, the history + rest are stale -> skip.
            if l.get("last_sched") and l["last_sched"] > games[-1][0]:
                miss["stale: team played a game not yet in sports.db"] += 1; continue
            opp = TEAMFIX.get(l.get("opp"), l.get("opp")) if sp == "WNBA" else (NBA_FIX.get(l.get("opp"), l.get("opp")) if sp == "NBA" else l.get("opp"))
            home, st, gid = l.get("home"), {}, None
        else:
            g = next((x for x in games if abs((datetime.date.fromisoformat(x[0]) - sd).days) <= 1 and x[0] >= (sd - datetime.timedelta(days=1)).isoformat()), None)
            if not g:
                miss["no game/actual"] += 1; continue
            gdate, gid, team, opp, mins, st, home = g
        key = (sp, norm(l["player"]), sk, gdate, l["line"])
        if key in seen:
            continue
        seen.add(key)
        fields, off_k, def_k = spec
        if live:
            actual = None
        else:
            vals = [st.get(f) for f in fields]
            if any(v is None for v in vals):
                miss["stat missing in box"] += 1; continue
            actual = sum(float(v) for v in vals)
            if actual == l["line"]:
                continue                                                # push
        if sp == "NHL" and st.get("gtype") == "pre":
            miss["preseason game"] += 1; continue
        prior = [x for x in games if x[0] < gdate]
        if sp == "NHL":
            prior = [x for x in prior if x[5].get("gtype") != "pre"]
        hist = []
        for x in prior[-40:]:
            v = [x[5].get(f) for f in fields]
            if all(y is not None for y in v):
                hist.append((x[0], sum(float(y) for y in v), x[4]))
        if len(hist) < 5:
            miss["<5 prior games"] += 1; continue

        def team_rate(t, k, side, before, n=20):
            if not k:
                return None
            xs = [(s if side == "for" else o).get(k) for d, s, o in tg.get((sp, t), []) if d < before]
            xs = [float(x) for x in xs if x is not None][-n:]
            return sum(xs) / len(xs) if len(xs) >= 3 else None

        def league_rate(k, side, before):
            ck = (sp, k, side, before)
            if ck in LCACHE:
                return LCACHE[ck]
            xs = []
            for (s_, t), gl in tg.items():
                if s_ != sp:
                    continue
                for d, s, o in gl[-30:]:
                    if d < before and (s if side == "for" else o).get(k) is not None:
                        xs.append(float((s if side == "for" else o).get(k)))
            LCACHE[ck] = sum(xs) / len(xs) if xs else None
            return LCACHE[ck]

        r = dict(sport=sp, player=l["player"], stat=l["stat"], sk=sk, line=l["line"], date=gdate, team=team, opp=opp, actual=actual,
                 over=None if actual is None else int(actual > l["line"]), start=l.get("start"), hist=[h[1] for h in hist], hist_min=[h[2] for h in hist],
                 kind=l.get("kind", "standard"), venue=l.get("venue", "PP"), ud_mult=l.get("ud_mult"), our_proj=l.get("our_proj"), our_call=l.get("our_call"),
                 first_line=l.get("first_line"), nsnap=l.get("nsnap"), home=home, post=bool(st.get("post")),
                 pos=st.get("pos") or (games[-1][5].get("pos") if games else None),
                 rest=(datetime.date.fromisoformat(gdate) - datetime.date.fromisoformat(prior[-1][0])).days if prior else None,
                 hist_dates=[h[0] for h in hist])
        for nm_, t, k, side in (("off_team", team, off_k, "for"), ("def_opp", opp, def_k, "against"),
                                ("def_team", team, def_k, "against"), ("off_opp", opp, off_k, "for")):
            v = team_rate(t, k, side, gdate); lg_ = league_rate(k, side, gdate) if k else None
            r[nm_] = (v / lg_) if (v is not None and lg_) else None
        if sp == "WNBA":
            pa = team_rate(team, "pace", "for", gdate); po = team_rate(opp, "pace", "for", gdate); pl_ = league_rate("pace", "for", gdate)
            r["pace"] = ((pa + po) / 2 / pl_) if (pa and po and pl_) else None
        if sp == "SOCCER":
            pa = team_rate(team, "poss", "for", gdate)
            r["poss"] = pa / 50.0 if pa else None
        rows.append(r)
    return rows, miss


def build():
    lines = pp_lines() + calls_lines()
    print("archived standard lines:", len(lines), collections.Counter(l["sport"] for l in lines))
    pg, tg = load_db()
    rows, miss = featurize(lines, pg, tg)
    json.dump(rows, open(OUT, "w", encoding="utf-8"))
    print("graded lines with features:", len(rows), collections.Counter(r["sport"] for r in rows))
    print("dropped:", dict(miss.most_common(12)))


# ---------------------------------------------------------------- model
def feats(r, use_ctx):
    h = r["hist"]; n = len(h); line = r["line"]
    mu = sum(h) / n; mu5 = sum(h[-5:]) / len(h[-5:]); mu10 = sum(h[-10:]) / len(h[-10:])
    sd = max((sum((x - mu) ** 2 for x in h) / max(n - 1, 1)) ** 0.5, 0.5)
    hit = (sum(1 for x in h if x > line) + 1) / (n + 2)
    f = {"z_season": (mu - line) / sd, "z_l10": (mu10 - line) / sd, "z_l5": (mu5 - line) / sd,
         "hit_logit": math.log(hit / (1 - hit)), "lowline": 1.0 if line < 1.5 else 0.0}
    if use_ctx:
        for k in ("off_team", "def_opp", "def_team", "off_opp", "pace", "poss"):
            v = r.get(k)
            f[k] = (v - 1.0) if v is not None else 0.0
            f[k + "_x"] = f[k] * (mu / line if line else 1.0)            # context matters more when the player sits near/over the line
    return f


def fit(X, y, l2=1.0, it=400, lr=0.1):
    import numpy as np
    X = np.asarray(X, float); y = np.asarray(y, float)
    m, s = X.mean(0), X.std(0) + 1e-9
    Z = (X - m) / s; Z = np.hstack([np.ones((len(Z), 1)), Z])
    w = np.zeros(Z.shape[1])
    for _ in range(it):
        p = 1 / (1 + np.exp(-Z @ w))
        g = Z.T @ (p - y) / len(y) + l2 * np.r_[0, w[1:]] / len(y)
        w -= lr * g * 10
    return w, m, s


def predict(model, X):
    import numpy as np
    w, m, s = model
    Z = (np.asarray(X, float) - m) / s
    Z = np.hstack([np.ones((len(Z), 1)), Z])
    return 1 / (1 + np.exp(-Z @ w))


def test():
    import numpy as np
    rows = json.load(open(OUT, encoding="utf-8"))
    rows = [r for r in rows if r["line"] >= 1.5]                       # low lines (0.5) = juiced/goblin-like; judged separately
    dates = sorted({r["date"] for r in rows})
    print("rows (line >= 1.5):", len(rows), collections.Counter(r["sport"] for r in rows), "dates", dates[0], "->", dates[-1])
    print("base over rate %.3f" % (sum(r["over"] for r in rows) / len(rows)))
    res = {}
    for name, ctx in (("BASE (player vs line)", False), ("+ OFFENSE/DEFENSE/PACE", True)):
        out = []
        for sp in ("NHL", "WNBA", "SOCCER"):
            R = [r for r in rows if r["sport"] == sp]
            ds = sorted({r["date"] for r in R})
            for d in ds[2:]:                                            # walk-forward: train on every earlier date
                tr = [r for r in R if r["date"] < d]; te = [r for r in R if r["date"] == d]
                if len(tr) < 80 or not te:
                    continue
                keys = sorted(feats(tr[0], ctx))
                mdl = fit([[feats(r, ctx)[k] for k in keys] for r in tr], [r["over"] for r in tr])
                p = predict(mdl, [[feats(r, ctx)[k] for k in keys] for r in te])
                out += [(r, float(pi)) for r, pi in zip(te, p)]
        res[name] = out
        ll = -sum(math.log(p if r["over"] else 1 - p) for r, p in out) / len(out)
        print("\n%s   out-of-sample n=%d   logloss %.4f (coin flip 0.6931)" % (name, len(out), ll))
        for lo, hi in ((0.5, 0.55), (0.55, 0.6), (0.6, 0.65), (0.65, 1.01)):
            for side in ("over", "under"):
                sel = [(r, p) for r, p in out if lo <= (p if side == "over" else 1 - p) < hi]
                if sel:
                    w = sum(1 for r, p in sel if r["over"] == (side == "over"))
                    print("   says %-5s %.2f-%.2f   n=%4d   hit %.1f%%" % (side, lo, min(hi, 1), len(sel), 100 * w / len(sel)))
        for sp in ("NHL", "WNBA", "SOCCER"):
            sel = [(r, p) for r, p in out if r["sport"] == sp and max(p, 1 - p) >= 0.6]
            if sel:
                w = sum(1 for r, p in sel if r["over"] == (p >= 0.5))
                print("   %-6s picks >=60%%: n=%d hit %.1f%%" % (sp, len(sel), 100 * w / len(sel)))
    # what the context features say, fit on everything (for the write-up)
    for sp in ("NHL", "WNBA", "SOCCER"):
        R = [r for r in rows if r["sport"] == sp]
        if len(R) < 100:
            continue
        keys = sorted(feats(R[0], True))
        w, m, s = fit([[feats(r, True)[k] for k in keys] for r in R], [r["over"] for r in R])
        print("\n%s weights (standardized, + = pushes OVER):" % sp, ", ".join("%s %+.2f" % (k, wi) for k, wi in sorted(zip(keys, w[1:]), key=lambda x: -abs(x[1]))[:8]))
    json.dump([(r["sport"], r["player"], r["stat"], r["line"], r["date"], r["over"], p) for r, p in res["+ OFFENSE/DEFENSE/PACE"]], open("_dir_oos.json", "w"))


if __name__ == "__main__" and sys.argv[1:] not in (["ctx"], ["goblins"]):
    {"build": build, "test": test}[sys.argv[1]]()


def ctx():
    """2026-10-07 deep test: across EVERY player-game in sports.db (no lines needed), how far does opponent defense / team offense /
    pace move a player off his own recent average? If the shift is small, no line-beating edge can come from it."""
    import numpy as np
    c = sqlite3.connect("sports.db")
    TESTS = [("NHL", "sog", "sog", ("2024", "2025")), ("NHL", "points", "goals", ("2024", "2025")),
             ("WNBA", "pts", "pts", None), ("WNBA", "reb", "reb", None), ("WNBA", "ast", "ast", None),
             ("SOCCER", "passes", "passes", None), ("SOCCER", "shots", "shots", None)]
    for sp, pk, tk, seasons in TESTS:
        tg = collections.defaultdict(list)
        for date, team, st, ost in c.execute("select date,team,stats,opp_stats from team_games where sport=?", (sp,)):
            s, o = json.loads(st or "{}"), json.loads(ost or "{}")
            tg[team].append((date, s.get(tk), o.get(tk), s.get("pace")))
        for t in tg:
            tg[t].sort(key=lambda x: x[0])
        idx = {t: [x[0] for x in v] for t, v in tg.items()}
        import bisect
        lgall = [x[2] for v in tg.values() for x in v if x[2] is not None]
        lgm = sum(lgall) / len(lgall)
        lgp = [x[3] for v in tg.values() for x in v if x[3]]
        lgpm = sum(lgp) / len(lgp) if lgp else None

        def trail(t, d, col, n=20):
            if t not in tg:
                return None
            i = bisect.bisect_left(idx[t], d)
            xs = [x[col] for x in tg[t][max(0, i - n):i] if x[col] is not None]
            return sum(xs) / len(xs) if len(xs) >= 8 else None
        pg = collections.defaultdict(list)
        q = "select player,date,team,opp,stats from player_games where sport=?" + (" and season in (%s)" % ",".join("'%s'" % s for s in seasons) if seasons else "")
        for player, date, team, opp, st in c.execute(q, (sp,)):
            s = json.loads(st)
            if s.get("gtype") == "pre" or s.get(pk) is None:
                continue
            pg[(player, team)].append((date, float(s[pk]), opp, team))
        X, Y, M = [], [], []
        for k, gl in pg.items():
            gl.sort()
            for i in range(10, len(gl)):
                prev = [x[1] for x in gl[max(0, i - 20):i]]
                mu = sum(prev) / len(prev)
                if mu < (1.0 if sp == "NHL" else 2.0):
                    continue
                d, a, opp, team = gl[i]
                dopp = trail(opp, d, 2); oteam = trail(team, d, 1)
                if dopp is None or oteam is None:
                    continue
                pace = None
                if lgpm:
                    p1, p2 = trail(team, d, 3), trail(opp, d, 3)
                    pace = ((p1 + p2) / 2 / lgpm - 1) if (p1 and p2) else 0.0
                X.append([dopp / lgm - 1, oteam / lgm - 1, pace or 0.0]); Y.append(a / mu - 1); M.append(mu)
        X, Y = np.array(X), np.array(Y)
        if len(Y) < 500:
            print(sp, pk, "too few", len(Y)); continue
        A = np.hstack([np.ones((len(X), 1)), X])
        b, *_ = np.linalg.lstsq(A, Y, rcond=None)
        r = [np.corrcoef(X[:, j], Y)[0, 1] if X[:, j].std() > 0 else 0 for j in range(3)]
        q10, q90 = np.percentile(X[:, 0], [10, 90])
        lo, hi = Y[X[:, 0] <= q10].mean(), Y[X[:, 0] >= q90].mean()
        # what that shift is worth at a line set on the player's mean: hit-rate change via the empirical residual spread
        sdY = Y.std()
        print("%-6s %-7s n=%6d | vs player's own avg: softest 10%% of defenses %+5.1f%%, toughest 10%% %+5.1f%% | corr def %.3f off %.3f pace %.3f | "
              "worth ~%.1f pts of hit rate at the extremes" % (sp, pk, len(Y), 100 * hi, 100 * lo, r[0], r[1], r[2],
              100 * (0.5 * math.erf((hi - lo) / 2 / sdY / math.sqrt(2)))))


if __name__ == "__main__" and sys.argv[1:] == ["ctx"]:
    ctx()


def build_goblins():
    """10/7: every archived NHL/WNBA GOBLIN line (more-only) graded from sports.db -> _dir_goblins.json"""
    lines = pp_lines(kinds=("goblin",))
    print("archived goblin lines:", len(lines), collections.Counter(l["sport"] for l in lines))
    pg, tg = load_db()
    rows, miss = featurize(lines, pg, tg)
    json.dump(rows, open("_dir_goblins.json", "w", encoding="utf-8"))
    print("graded goblins:", len(rows), collections.Counter(r["sport"] for r in rows), "over rate %.3f" % (sum(r["over"] for r in rows) / max(len(rows), 1)))


if __name__ == "__main__" and sys.argv[1:] == ["goblins"]:
    build_goblins()
