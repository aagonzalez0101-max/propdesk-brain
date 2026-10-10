"""EUROLEAGUE data + backtests (2026-10-07, user: "backtest ... lengthy ... then player props, Courtside has Euro overs-only alt lines").
Free official API (api-live.euroleague.net), no key.

    python _euro.py pull [first_season]   # every game + box score E2012..now -> euro_games.jsonl, euro_players.jsonl (cached in _euro/)
    python _euro.py sides                 # walk-forward Elo + home + rest: accuracy, calibration, margin/total effects, every season
    python _euro.py props                 # walk-forward P(player >= X) for alt-line overs (pts/reb/ast/PRA): calibration by bucket
"""
import os, sys, json, math, time, datetime, collections
import requests
from concurrent.futures import ThreadPoolExecutor

API = "https://api-live.euroleague.net/v2/competitions/E/seasons/%s/games"
H = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
CACHE = "_euro"
CT = datetime.timezone(datetime.timedelta(hours=-5))


def get(u):
    for a in range(4):
        try:
            r = requests.get(u, headers=H, timeout=40)
            if r.status_code == 200:
                time.sleep(0.9)                                             # 10/7: 8 threads got HTTP 429 -> one request ~1/s
                return r.json()
            if r.status_code == 429:
                time.sleep(25 * (a + 1)); continue
        except Exception:
            pass
        time.sleep(1 + a)
    return None


def pull(first=2012, cache_only=False):
    """newest season first, so recent seasons are usable while older ones download. cache_only=True: just rebuild the files."""
    os.makedirs(CACHE, exist_ok=True)
    this = datetime.date.today().year
    games, players = [], []
    for yr in range(this, first - 1, -1):
        sc = "E%d" % yr
        gf = os.path.join(CACHE, "%s_games.json" % sc)
        d = json.load(open(gf, encoding="utf-8")) if (os.path.exists(gf) and (cache_only or yr < this)) else (None if cache_only else get(API % sc))
        if not d:
            continue
        json.dump(d, open(gf, "w", encoding="utf-8"))
        G = [g for g in d["data"] if g.get("played")]
        print(sc, len(G), "played", flush=True)

        def box(g):
            f = os.path.join(CACHE, "%s_%s.json" % (sc, g["gameCode"]))
            if os.path.exists(f):
                return g, json.load(open(f, encoding="utf-8"))
            if cache_only:
                return g, None
            b = get((API % sc) + "/%s/stats" % g["gameCode"])
            if b:
                json.dump(b, open(f, "w", encoding="utf-8"))
            return g, b
        with ThreadPoolExecutor(1) as ex:
            for g, b in ex.map(box, G):
                hc, ac = g["local"]["club"]["code"], g["road"]["club"]["code"]
                row = dict(season=sc, code=g["gameCode"], date=g["date"][:10], round=g.get("round"), phase=(g.get("phaseType") or {}).get("code"),
                           home=hc, away=ac, hs=g["local"]["score"], as_=g["road"]["score"])
                games.append(row)
                if not b:
                    continue
                for side, team, opp, home in (("local", hc, ac, 1), ("road", ac, hc, 0)):
                    for p in (b.get(side) or {}).get("players", []):
                        s = p.get("stats") or {}
                        mins = (s.get("timePlayed") or 0) / 60
                        if mins <= 0:
                            continue
                        players.append(dict(season=sc, code=g["gameCode"], date=row["date"], team=team, opp=opp, home=home,
                                            pid=p["player"]["person"]["code"], name=p["player"]["person"]["name"], mins=round(mins, 1),
                                            pts=s.get("points", 0), reb=s.get("totalRebounds", 0), ast=s.get("assistances", 0),
                                            tpm=s.get("fieldGoalsMade3", 0), start=bool(s.get("startFive"))))
    with open("euro_games.jsonl", "w", encoding="utf-8") as f:
        for r in sorted(games, key=lambda r: (r["date"], r["code"])):
            f.write(json.dumps(r) + "\n")
    with open("euro_players.jsonl", "w", encoding="utf-8") as f:
        for r in players:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("games %d  player-games %d" % (len(games), len(players)))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "pull"
    if cmd == "pull":
        pull(int(sys.argv[2]) if len(sys.argv) > 2 else 2012)
    elif cmd == "build":
        pull(int(sys.argv[2]) if len(sys.argv) > 2 else 2012, cache_only=True)


# ------------------------------------------------------------------ sides: walk-forward Elo + home + rest
def load_games(prefix="euro"):
    G = [json.loads(l) for l in open(prefix + "_games.jsonl", encoding="utf-8")]
    return [g for g in G if g["hs"] is not None and g["as_"] is not None]


def sides(K=20.0, HOME=110.0, REG=0.75, prefix="euro"):
    G = load_games(prefix)
    elo = collections.defaultdict(lambda: 1500.0); last = {}; season = None
    rows = []
    for g in G:
        if g["season"] != season:                                   # regress toward the mean between seasons
            for t in elo:
                elo[t] = 1500 + REG * (elo[t] - 1500)
            season = g["season"]
        h, a = g["home"], g["away"]
        d = datetime.date.fromisoformat(g["date"])
        rh = (d - last[h]).days if h in last else 9; ra = (d - last[a]).days if a in last else 9
        diff = elo[h] + HOME - elo[a]
        p = 1 / (1 + 10 ** (-diff / 400))
        margin = g["hs"] - g["as_"]
        rows.append(dict(season=g["season"], date=g["date"], p=p, diff=diff, win=int(margin > 0), margin=margin, total=g["hs"] + g["as_"],
                         rh=rh, ra=ra, phase=g.get("phase")))
        mov = math.log(abs(margin) + 1) * (2.2 / ((abs(diff) * 0.001) + 2.2))
        ch = K * mov * ((1 if margin > 0 else 0) - p)
        elo[h] += ch; elo[a] -= ch; last[h] = d; last[a] = d
    R = [r for r in rows if r["season"] >= "E2014"]                     # 2 seasons of burn-in
    ll = -sum(math.log(r["p"] if r["win"] else 1 - r["p"]) for r in R) / len(R)
    base = sum(r["win"] for r in R) / len(R)
    llb = -sum(math.log(base if r["win"] else 1 - base) for r in R) / len(R)
    acc = sum((r["p"] >= .5) == bool(r["win"]) for r in R) / len(R)
    print("EUROLEAGUE SIDES, walk-forward Elo (K=%g, home=%g), %d games E2014-now" % (K, HOME, len(R)))
    print("  accuracy %.1f%%   log-loss %.4f  vs home-only %.4f (home wins %.1f%%)" % (100 * acc, ll, llb, 100 * base))
    print("  calibration:")
    for lo, hi in ((.5, .6), (.6, .7), (.7, .8), (.8, .9), (.9, 1.0)):
        X = [r for r in R if lo <= max(r["p"], 1 - r["p"]) < hi]
        if X:
            w = sum((r["p"] >= .5) == bool(r["win"]) for r in X)
            print("     fav %.0f-%.0f%%  n=%4d  won %.1f%%" % (100 * lo, 100 * hi, len(X), 100 * w / len(X)))
    print("  by season: " + "  ".join("%s %.0f%%" % (s[1:], 100 * sum((r["p"] >= .5) == bool(r["win"]) for r in R if r["season"] == s) /
                                     max(1, sum(1 for r in R if r["season"] == s))) for s in sorted({r["season"] for r in R})))
    # REST: margin vs Elo expectation (diff/28 ~ points), and totals vs season mean
    exp = lambda r: r["diff"] / 28.0
    smean = {s: sum(r["total"] for r in R if r["season"] == s) / max(1, sum(1 for r in R if r["season"] == s)) for s in {r["season"] for r in R}}
    print("  REST (days since last game; Euroleague double-round weeks = 2 days):")
    for lab, f in (("home 2 days or less, away 3+", lambda r: r["rh"] <= 2 and r["ra"] >= 3), ("away 2 days or less, home 3+", lambda r: r["ra"] <= 2 and r["rh"] >= 3),
                   ("both 2 days or less", lambda r: r["rh"] <= 2 and r["ra"] <= 2), ("both 3+ days", lambda r: r["rh"] >= 3 and r["ra"] >= 3)):
        X = [r for r in R if f(r)]
        if X:
            m = sum(r["margin"] - exp(r) for r in X) / len(X); t = sum(r["total"] - smean[r["season"]] for r in X) / len(X)
            sd = (sum((r["margin"] - exp(r) - m) ** 2 for r in X) / len(X)) ** .5
            print("     %-30s n=%4d  home margin vs Elo %+5.2f (se %.2f)   total vs season avg %+5.2f" % (lab, len(X), m, sd / math.sqrt(len(X)), t))
    json.dump(rows, open("_euro_sides.json", "w"))


# ------------------------------------------------------------------ props: overs-only alt lines
ALT = {"pts": (5, 8, 10, 12, 15, 18, 20, 25), "reb": (3, 4, 5, 6, 8, 10), "ast": (2, 3, 4, 5, 6, 8), "pra": (10, 15, 20, 25, 30)}


def props(window=15, minN=8, prefix="euro"):
    P = [json.loads(l) for l in open(prefix + "_players.jsonl", encoding="utf-8")]
    for r in P:
        r["pra"] = r["pts"] + r["reb"] + r["ast"]
    by = collections.defaultdict(list)
    for r in P:
        by[r["pid"]].append(r)
    # opponent defense as-of: points allowed per game (trailing 15) relative to the league
    G = load_games(prefix); allowed = collections.defaultdict(list)
    for g in G:
        allowed[g["home"]].append((g["date"], g["as_"])); allowed[g["away"]].append((g["date"], g["hs"]))
    lgm = sum(g["hs"] + g["as_"] for g in G) / (2 * len(G))
    def opp_def(t, d):
        xs = [x for dd, x in allowed[t] if dd < d][-15:]
        return (sum(xs) / len(xs) / lgm) if len(xs) >= 5 else 1.0
    out = []
    for pid, gl in by.items():
        gl.sort(key=lambda r: r["date"])
        for i in range(len(gl)):
            r = gl[i]
            if r["season"] < "E2014":
                continue
            prev = [x for x in gl[:i] if x["mins"] >= 10][-window:]
            if len(prev) < minN or r["mins"] < 10:
                continue                                                # Courtside voids DNPs; judge players who actually played 10+
            od = opp_def(r["opp"], r["date"])
            for st, xs in ALT.items():
                vals = [x[st] for x in prev]; mu = sum(vals) / len(vals)
                for X in xs:
                    if not (0.35 * X <= mu <= 2.2 * X):
                        continue
                    raw = (sum(v >= X for v in vals) + 0.5) / (len(vals) + 1)
                    out.append(dict(season=r["season"], st=st, X=X, p=raw, od=od, hit=int(r[st] >= X), mu=mu, start=r["start"]))
    print("EUROLEAGUE ALT-LINE OVERS, walk-forward (player's last %d games with 10+ min, as-of), %d priced lines" % (window, len(out)))
    for st in ALT:
        S = [o for o in out if o["st"] == st]
        print(" %s" % st.upper())
        for lo, hi in ((.5, .6), (.6, .7), (.7, .8), (.8, .9), (.9, 1.01)):
            X = [o for o in S if lo <= o["p"] < hi]
            if len(X) >= 50:
                h = sum(o["hit"] for o in X) / len(X); pm = sum(o["p"] for o in X) / len(X)
                tough = [o for o in X if o["od"] <= .96]; soft = [o for o in X if o["od"] >= 1.04]
                th = sum(o["hit"] for o in tough) / max(1, len(tough)); sh = sum(o["hit"] for o in soft) / max(1, len(soft))
                print("   our P %.0f-%.0f%%  n=%6d  actual %.1f%% (pred %.1f%%)   vs tough D %.1f%%  vs soft D %.1f%%   fair odds %s" % (
                      100 * lo, 100 * hi, len(X), 100 * h, 100 * pm, 100 * th, 100 * sh,
                      ("-%d" % round(100 * h / (1 - h))) if h > .5 else ("+%d" % round(100 * (1 - h) / h))))


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] in ("sides", "props"):
    {"sides": sides, "props": props}[sys.argv[1]](prefix=sys.argv[2] if len(sys.argv) > 2 else "euro")
