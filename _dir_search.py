"""DIRECTION MODEL v1 -- over or under, both sides (2026-10-07; user: "keep tweaking until we get a winning edge on overs AND unders").

    python _dir_search.py lodo        # leave-one-DAY-out test on every graded line (_dir_rows.json from `_direction.py build`)
    python _dir_search.py score       # fit on every graded line, score today's + tomorrow's PP standard lines -> direction_paper.jsonl
    python _dir_search.py grade       # grade direction_paper.jsonl from sports.db (run after `_db.py update`)

Per-sport logistic on MECHANISM features only (fit on graded PP/UD lines, as-of the game date):
  WNBA: opponent defense / offense / own defense rank, line vs the player's median + mean, last-10 hit rate (a FADE: PP already
        raised hot lines), UD's payout lean, minutes trend, home/away, rest (2 days -> under, 4+ -> over), assist stats (under),
        last meetings vs THIS opponent (playoff series).
  NHL:  line vs median, last-10, opponent defense, team offense, own defense, our projection vs line, UD lean, home, rest, D-man.
Sides offered = the ones that held up out of sample (leave-one-day-out, 10/7): NHL OVER, WNBA OVER, WNBA UNDER.
NHL UNDER is NOT offered -- every version tested lost (25-50%).
"""
import json, math, collections, sys, os, sqlite3, datetime
import numpy as np

CT = datetime.timezone(datetime.timedelta(hours=-5))
TH = 0.58
L2 = 0.10
OFFER = {("NHL", "over"), ("WNBA", "over"), ("WNBA", "under"), ("NBA", "over"), ("NBA", "under"), ("NHL", "under")}
PAPER_ONLY = {"NBA"}                 # 10/7: NBA picks come from reasons alone (no graded NBA lines yet) -> paper until ~300 graded
PAPER = "direction_paper.jsonl"
_c = sqlite3.connect("sports.db")

SPEC = {
    "WNBA": ["def_opp_pr", "off_opp_pr", "def_team_pr", "med_line", "mu_line", "l10_hit", "ud_lean_f", "ud_has", "min_trend",
             "home_f", "rest_short", "rest_long", "ast_stat", "vs_line", "vs_has"],
    "NHL": ["med_line", "l10_hit", "def_opp_pr", "off_team_pr", "def_team_pr", "proj_line_f", "proj_has", "ud_lean_f", "ud_has",
            "home_f", "rest_short", "rest_long", "d_pos"],
}
FLD = {"points": ("pts",), "rebounds": ("reb",), "assists": ("ast",), "ptsrebsasts": ("pts", "reb", "ast"), "ptsrebs": ("pts", "reb"),
       "ptsasts": ("pts", "ast"), "rebsasts": ("reb", "ast"), "3ptmade": ("tpm",), "pointsrebounds": ("pts", "reb"), "pointsassists": ("pts", "ast"),
       "reboundsassists": ("reb", "ast"), "3pointersmade": ("tpm",), "pointsreboundsassists": ("pts", "reb", "ast")}
_vs = {}


def last_vs(r):
    if r["sport"] != "WNBA" or not r.get("opp"):
        return None
    k = (r["player"], r["opp"])
    if k not in _vs:
        _vs[k] = [(d, json.loads(s)) for d, s in _c.execute("select date,stats from player_games where sport='WNBA' and player=? and opp=? order by date", k)]
    prev = [(d, s) for d, s in _vs[k] if r["date"] > d >= "2026-05-01"]
    f = FLD.get(r["sk"])
    if not prev or not f:
        return None
    vals = [sum(float(s.get(x) or 0) for x in f) for d, s in prev[-3:]]
    return sum(vals) / len(vals) / r["line"]


def prep(rows, ref):
    """all model features. `ref` = the graded rows whose distribution sets the percentile cut points."""
    for r in rows:
        h = r["hist"]; L = r["line"]; n = len(h); mu = sum(h) / n; med = sorted(h)[n // 2]; l10 = h[-10:]
        m = [x for x in r.get("hist_min") or [] if x]
        r["mu_line"] = min(mu / L, 3.0); r["med_line"] = min(med / L, 3.0)
        r["l10_hit"] = sum(x > L for x in l10) / len(l10)
        r["min_trend"] = (sum(m[-3:]) / 3 / (sum(m) / len(m))) if len(m) >= 6 else 1.0
        pl = (r["our_proj"] / L) if r.get("our_proj") else None
        r["proj_has"] = 1.0 if pl else 0.0; r["proj_line_f"] = min((pl or 1.0) - 1.0, 1.0)
        ud = (r["ud_mult"] - 1.0) if r.get("ud_mult") else None
        r["ud_has"] = 1.0 if ud is not None else 0.0; r["ud_lean_f"] = ud or 0.0
        r["home_f"] = 1.0 if r.get("home") in (1, True) else 0.0
        rs = r.get("rest") or 3
        r["rest_short"] = 1.0 if rs <= 2 else 0.0; r["rest_long"] = 1.0 if rs >= 4 else 0.0
        r["ast_stat"] = 1.0 if ("ast" in r["sk"] or "assist" in r["sk"]) else 0.0
        lv = last_vs(r); r["vs_has"] = 1.0 if lv else 0.0; r["vs_line"] = (min(lv, 2.5) - 1.0) if lv else 0.0
        r["d_pos"] = 1.0 if r.get("pos") == "D" else 0.0
    for k in ("def_opp", "off_opp", "def_team", "off_team", "pace"):
        for sp in ("NHL", "WNBA", "NBA"):
            src = ref if sp != "NBA" else rows                          # no graded NBA lines yet: rank within the slate itself
            xs = sorted(r[k] for r in src if r["sport"] == sp and r.get(k) is not None)
            for r in rows:
                if r["sport"] == sp:
                    r[k + "_pr"] = (sum(1 for x in xs if x < r[k]) / len(xs)) if (xs and r.get(k) is not None) else 0.5
    return rows


def fit(X, y, l2):
    X = np.asarray(X, float); y = np.asarray(y, float); m, s = X.mean(0), X.std(0) + 1e-9
    Z = np.hstack([np.ones((len(X), 1)), (X - m) / s]); w = np.zeros(Z.shape[1])
    for _ in range(3000):
        p = 1 / (1 + np.exp(-Z @ w)); g = Z.T @ (p - y) / len(y) + l2 * np.r_[0, w[1:]]; w -= 0.5 * g
    return w, m, s


def pred(M, X):
    w, m, s = M; Z = np.hstack([np.ones((len(X), 1)), (np.asarray(X, float) - m) / s]); return 1 / (1 + np.exp(-Z @ w))


def graded():
    R = [r for r in json.load(open("_dir_rows.json")) if r["line"] >= 1.5 and r["sport"] in ("NHL", "WNBA") and r.get("over") is not None]
    return prep(R, R)


def lodo_out(R=None, spec=None, l2=None):
    R = R or graded(); spec = spec or SPEC; l2 = L2 if l2 is None else l2; out = []
    for sp in ("NHL", "WNBA"):
        S = [r for r in R if r["sport"] == sp]
        for d in sorted({r["date"] for r in S}):
            tr = [r for r in S if r["date"] != d]; te = [r for r in S if r["date"] == d]
            if len(tr) < 150 or not te:
                continue
            M = fit([[r[k] for k in spec[sp]] for r in tr], [r["over"] for r in tr], l2)
            for r, p in zip(te, pred(M, [[r[k] for k in spec[sp]] for r in te])):
                out.append(dict(r, p=float(p)))
    return out


def votes(r):
    """independent MEASURED mechanisms (10/7): +1 = points over, -1 = points under. The top tier needs the model's side backed by
    3+ of these and contradicted by none -- model confidence alone ranked badly (its 66%+ tier hit only 53%)."""
    v = []
    if r["sport"] == "WNBA":
        v.append(-1 if r["home_f"] == 0 else +1)                      # road -> under 58%
        if r["rest_short"]: v.append(-1)                               # 2 days rest -> under 63%
        if r["rest_long"]: v.append(+1)                                # 4+ days -> over 56%
        if r["ast_stat"]: v.append(-1)                                 # assist stats -> under 65%
        if r["def_opp_pr"] <= .3: v.append(-1)                         # tough opponent D
        if r["def_opp_pr"] >= .7: v.append(+1)                         # soft opponent D
        if r["l10_hit"] >= .7: v.append(-1)                            # hot streak = PP already raised it -> fade
        if r["med_line"] >= 1.3: v.append(-1)                          # line far BELOW history = market knows (minutes/role)
        if r["ud_has"] and r["ud_lean_f"] > 0.02: v.append(-1)         # Underdog pays more on the over -> it expects under
        if r["ud_has"] and r["ud_lean_f"] < -0.02: v.append(+1)
    elif r["sport"] == "NBA":
        # _nba_mech.py, 2 seasons / 81k player-games: opponent D moves NBA players more than WNBA (assists 38% vs 50% over own avg);
        # rest/back-to-back does NOTHING in the NBA -> no rest vote. Line-vs-history votes carried over from WNBA, unproven here.
        if r["def_opp_pr"] <= .2: v.append(-1)
        if r["def_opp_pr"] >= .8: v.append(+1)
        if r["ast_stat"]: v.append(-1)
        if r["l10_hit"] >= .7: v.append(-1)
        if r["med_line"] >= 1.3: v.append(-1)
        if r["med_line"] <= 0.85: v.append(-1)
        if r["med_line"] >= 1.15 and r["l10_hit"] <= .6: v.append(+1)
    else:
        if r["med_line"] >= 1.1: v.append(+1)
        if r["med_line"] <= 0.85: v.append(-1)
        if r["proj_has"] and r["proj_line_f"] >= .15: v.append(+1)     # our role model 15%+ over the line
        if r["def_opp_pr"] >= .7: v.append(+1)
        if r["off_team_pr"] >= .7: v.append(+1)
        if r["l10_hit"] >= .8: v.append(+1)
        if r["ud_has"] and r["ud_lean_f"] < -0.02: v.append(+1)
        if r["ud_has"] and r["ud_lean_f"] > 0.02: v.append(-1)
    return v


WHY = {"WNBA": [("home_f", lambda r: r["home_f"] == 0, -1, "road"), ("", lambda r: r["home_f"] == 1, +1, "home"),
                ("", lambda r: r["rest_short"], -1, "2 days rest"), ("", lambda r: r["rest_long"], +1, "4+ days rest"),
                ("", lambda r: r["ast_stat"], -1, "assist stat"), ("", lambda r: r["def_opp_pr"] <= .3, -1, "tough D"),
                ("", lambda r: r["def_opp_pr"] >= .7, +1, "soft D"), ("", lambda r: r["l10_hit"] >= .7, -1, "hot-streak line (fade)"),
                ("", lambda r: r["med_line"] >= 1.3, -1, "line far below history"),
                ("", lambda r: r["ud_has"] and r["ud_lean_f"] > 0.02, -1, "UD leans under"),
                ("", lambda r: r["ud_has"] and r["ud_lean_f"] < -0.02, +1, "UD leans over")],
       "NHL": [("", lambda r: r["med_line"] >= 1.1, +1, "median over line"), ("", lambda r: r["proj_has"] and r["proj_line_f"] >= .15, +1, "our proj +15%"),
               ("", lambda r: r["def_opp_pr"] >= .7, +1, "soft D"), ("", lambda r: r["off_team_pr"] >= .7, +1, "high-volume team"),
               ("", lambda r: r["l10_hit"] >= .8, +1, "8+/10 recent"), ("", lambda r: r["ud_has"] and r["ud_lean_f"] < -0.02, +1, "UD leans over")]}


WHY["NBA"] = [("", lambda r: r["def_opp_pr"] <= .2, -1, "tough D (bottom 20%)"), ("", lambda r: r["def_opp_pr"] >= .8, +1, "soft D (top 20%)"),
              ("", lambda r: r["ast_stat"], -1, "assist stat"), ("", lambda r: r["l10_hit"] >= .7, -1, "hot-streak line (fade)"),
              ("", lambda r: r["med_line"] >= 1.3, -1, "line far below history"), ("", lambda r: r["med_line"] <= 0.85, -1, "line above his median"),
              ("", lambda r: r["med_line"] >= 1.15 and r["l10_hit"] <= .6, +1, "median over line, not inflated")]


def why(r, side):
    sg = 1 if side == "over" else -1
    return ", ".join(lab for _, f, s_, lab in WHY[r["sport"]] if s_ == sg and f(r))


def top_tier(rows, k=6):
    """rows carry p. Keep offered sides with conf>=0.55, 3+ agreeing votes, 0 against; 1 leg per player; top k per sport-day."""
    pool = []
    for r in rows:
        side = "over" if r["p"] >= 0.5 else "under"; conf = max(r["p"], 1 - r["p"]); sg = 1 if side == "over" else -1
        v = votes(r); ag = sum(1 for x in v if x == sg); an = sum(1 for x in v if x == -sg)
        if (r["sport"], side) in OFFER and conf >= 0.55 and ag >= 3 and an == 0:
            pool.append(dict(r, side=side, conf=conf, agree=ag))
        elif r["sport"] == "NHL" and side == "under" and conf >= 0.58 and an == 0:
            # 10/9 user: "go by the model, not 'NHL = overs'". Leave-one-day-out: model >= 58% under hit 59.0% (n=61); NHL under
            # REASONS added nothing (54-55%), so the model's confidence alone qualifies it. PAPER tier until ~100 graded live.
            pool.append(dict(r, side=side, conf=conf, agree=0, tier_note="NHL model-under (paper)"))
    out = []
    for key in sorted({(r["sport"], r["date"], r["side"]) for r in pool}):          # 10/9: cap per SIDE so unders never crowd out overs (or vice versa)
        seen = set()
        for r in sorted([r for r in pool if (r["sport"], r["date"], r["side"]) == key], key=lambda r: (-r["agree"], -r["conf"])):
            if r["player"] in seen:
                continue
            seen.add(r["player"]); out.append(r)
            if len(seen) >= k:
                break
    return out


def lodo():
    out = lodo_out()
    T = top_tier(out)
    w = sum(1 for r in T if r["over"] == (r["side"] == "over"))
    print("TOP TIER (every pick passing the filter, max 6 per sport-day, 3+ reasons agree, 0 against), leave-one-day-out: %d-%d  %.1f%%" % (w, len(T) - w, 100 * w / max(len(T), 1)))
    for sp in ("NHL", "WNBA"):
        for sd in ("over", "under"):
            X = [r for r in T if r["sport"] == sp and r["side"] == sd]
            if X:
                ww = sum(1 for r in X if r["over"] == (sd == "over")); print("   %-5s %-5s %d-%d  %.1f%%" % (sp, sd.upper(), ww, len(X) - ww, 100 * ww / len(X)))
    print("leave-one-day-out, %d lines, threshold %.2f, L2 %.2f" % (len(out), TH, L2))
    for sp in ("NHL", "WNBA"):
        for side in ("over", "under"):
            X = [r for r in out if r["sport"] == sp and (r["p"] if side == "over" else 1 - r["p"]) >= TH]
            if X:
                h = sum(r["over"] == (side == "over") for r in X) / len(X)
                z = (h - 0.577) / math.sqrt(0.577 * 0.423 / len(X))
                print("  %-5s %-5s n=%4d  hit %5.1f%%  vs 57.7%% b/e z=%+.1f  %s" % (sp, side.upper(), len(X), 100 * h, z, "OFFERED" if (sp, side) in OFFER else "not offered"))


def last_played(days=6):
    """(sport, team) -> dates of games played in the last few days, from the league schedules (not sports.db)."""
    import requests
    out = collections.defaultdict(list)
    today = datetime.datetime.now(CT).date()
    for i in range(0, days + 1):
        d = (today - datetime.timedelta(days=i)).isoformat()
        try:
            j = requests.get("https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard?dates=%s" % d.replace("-", ""), timeout=20).json()
            for e in j.get("events", []):
                if e["status"]["type"].get("state") in ("in", "post"):
                    for c in e["competitions"][0]["competitors"]:
                        out[("WNBA", c["team"]["abbreviation"])].append(d)
        except Exception as e:
            print("wnba sched:", e)
        try:
            j = requests.get("https://api-web.nhle.com/v1/score/%s" % d, timeout=20).json()
            for g in j.get("games", []):
                if g.get("gameState") not in ("FUT", "PRE"):
                    out[("NHL", g["homeTeam"]["abbrev"])].append(d); out[("NHL", g["awayTeam"]["abbrev"])].append(d)
        except Exception as e:
            print("nhl sched:", e)
    return out


def nhl_home(day):
    import requests
    out = {}
    try:
        d = requests.get("https://api-web.nhle.com/v1/schedule/%s" % day, timeout=20).json()
        for wk in d.get("gameWeek", []):
            if wk.get("date") != day:
                continue
            for g in wk.get("games", []):
                out[g["homeTeam"]["abbrev"]] = 1; out[g["awayTeam"]["abbrev"]] = 0
    except Exception as e:
        print("nhl schedule:", e)
    return out


def wnba_home(day, lg="wnba"):
    import requests
    out = {}
    try:
        d = requests.get("https://site.api.espn.com/apis/site/v2/sports/basketball/%s/scoreboard?dates=%s" % (lg, day.replace("-", "")), timeout=20).json()
        for e in d.get("events", []):
            for c in e["competitions"][0]["competitors"]:
                out[c["team"]["abbreviation"]] = 1 if c.get("homeAway") == "home" else 0
    except Exception as e:
        print("wnba schedule:", e)
    return out


def score():
    import _props as P, _direction as D
    R = graded()
    models = {sp: fit([[r[k] for k in SPEC[sp]] for r in R if r["sport"] == sp], [r["over"] for r in R if r["sport"] == sp], L2) for sp in ("NHL", "WNBA")}
    now = datetime.datetime.now(datetime.timezone.utc)
    lines = []
    leagues = [(8, "NHL"), (3, "WNBA")] + ([(7, "NBA")] if datetime.datetime.now(CT).date().isoformat() >= "2026-10-19" or "--nba" in sys.argv else [])
    for lg, sp in leagues:
        try:
            for l in P.prizepicks(lg, max_age=int(os.environ.get("PP_MAX_AGE", 1800))):
                if l.get("kind") != "standard" or "+" in (l.get("player") or "") or l["line"] < 1.5:
                    continue
                if datetime.datetime.fromisoformat(l["start"]).astimezone(datetime.timezone.utc) < now:
                    continue
                lines.append(dict(sport=sp, player=l["player"], team=l.get("team"), opp=l.get("opp"), stat=l["stat"], line=l["line"], start=l["start"], venue="PP"))
        except Exception as e:
            print(sp, "pp:", e)
    homes = {}
    for l in lines:
        day = datetime.datetime.fromisoformat(l["start"]).astimezone(CT).date().isoformat()
        if (l["sport"], day) not in homes:
            homes[(l["sport"], day)] = nhl_home(day) if l["sport"] == "NHL" else wnba_home(day, l["sport"].lower())
        l["home"] = homes[(l["sport"], day)].get(D.TEAMFIX.get(l["team"], l["team"]) if l["sport"] == "WNBA" else D.NBA_FIX.get(l["team"], l["team"]))
    last = last_played()
    for l in lines:
        day = datetime.datetime.fromisoformat(l["start"]).astimezone(CT).date().isoformat()
        tm = D.TEAMFIX.get(l["team"], l["team"]) if l["sport"] == "WNBA" else l["team"]
        l["last_sched"] = max([d for d in last.get((l["sport"], tm), []) if d < day], default=None)
    pg, tg = D.load_db()
    live, miss = D.featurize(lines, pg, tg, live=True)
    if miss:
        print("  skipped:", dict(miss.most_common(6)))
    for r in live:
        r["home"] = next((l["home"] for l in lines if l["player"] == r["player"] and l["stat"] == r["stat"]), None)
    prep(live, R)
    scored = []
    for sp in ("NHL", "WNBA"):
        S = [r for r in live if r["sport"] == sp]
        if S:
            for r, p in zip(S, pred(models[sp], [[r[k] for k in SPEC[sp]] for r in S])):
                scored.append(dict(r, p=float(p)))
    for r in live:                                                    # NBA: no trained model yet -> side + strength from the votes
        if r["sport"] == "NBA":
            net = sum(votes(r)); scored.append(dict(r, p=0.5 + 0.03 * net))
    picks = [dict(sport=r["sport"], date=r["date"], player=r["player"], team=r["team"], opp=r["opp"], stat=r["stat"], line=r["line"],
                  side=r["side"], p=round(float(r["conf"]), 3), agree=r["agree"], why=why(r, r["side"]), start=r.get("start"), home=r.get("home"),
                  tier="PAPER" if r["sport"] in PAPER_ONLY else "TOP", logged=datetime.datetime.now(CT).isoformat(timespec="minutes"), result=None)
             for r in top_tier(scored)]
    picks.sort(key=lambda x: (x["sport"], -x["agree"], -x["p"]))
    have = set()
    if os.path.exists(PAPER):
        have = {(json.loads(l)["player"], json.loads(l)["stat"], json.loads(l)["line"], json.loads(l)["date"]) for l in open(PAPER, encoding="utf-8")}
    with open(PAPER, "a", encoding="utf-8") as f:
        for x in picks:
            if (x["player"], x["stat"], x["line"], x["date"]) not in have:
                f.write(json.dumps(x, ensure_ascii=False) + "\n")
    print("DIRECTION TOP TIER (paper) -- %d live lines -> %d picks (every pick passing the filter, max 6 per sport-day, 3+ reasons agree, none against)" % (len(live), len(picks)))
    for x in picks:
        st = datetime.datetime.fromisoformat(x["start"]).astimezone(CT).strftime("%a %I:%M%p")
        print("  %-5s %-22s %-4s vs %-4s %-18s %-5s %5.1f  model %3.0f%%  %d: %s   %s" % (x["sport"], x["player"][:22], x["team"] or "", x["opp"] or "",
              x["stat"][:18], x["side"].upper(), x["line"], 100 * x["p"], x["agree"], x["why"], st))


def grade():
    import _direction as D
    if not os.path.exists(PAPER):
        return
    rows = [json.loads(l) for l in open(PAPER, encoding="utf-8")]
    pg, tg = D.load_db()
    for x in rows:
        if x.get("result"):
            continue
        spec = D.STATMAP[x["sport"]].get(D.norm(x["stat"]))
        games = pg.get((x["sport"], D.nkey(x["sport"], x["player"])))
        if not spec or not games:
            continue
        g = next((gm for gm in games if abs((datetime.date.fromisoformat(gm[0]) - datetime.date.fromisoformat(x["date"])).days) <= 1 and gm[0] >= x["date"]), None)
        if not g:
            continue
        vals = [g[5].get(f) for f in spec[0]]
        if any(v is None for v in vals):
            continue
        a = sum(float(v) for v in vals); x["actual"] = a
        x["result"] = "PUSH" if a == x["line"] else ("W" if (a > x["line"]) == (x["side"] == "over") else "L")
    with open(PAPER, "w", encoding="utf-8") as f:
        for x in rows:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    c = collections.Counter((x["sport"], x["side"], x["result"]) for x in rows if x.get("result") in ("W", "L"))
    for sp in ("NHL", "WNBA"):
        for side in ("over", "under"):
            w, l = c[(sp, side, "W")], c[(sp, side, "L")]
            if w + l:
                print("  direction paper %-5s %-5s %d-%d  %.1f%%" % (sp, side.upper(), w, l, 100 * w / (w + l)))


if __name__ == "__main__":
    {"lodo": lodo, "score": score, "grade": grade}[sys.argv[1]]()

