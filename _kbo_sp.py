"""KBO starting pitchers from Naver previews -> kbo_starters.jsonl

    python _kbo_sp.py pull [year]     # one preview call per game, resumable
    python _kbo_sp.py fit             # what is a starter's ERA gap actually worth?

The team-only Elo priced NC/KT at 71% when Pinnacle said 51%, because NC were starting a
2.59 ERA ace and the model cannot see starters at all. In baseball that is the dominant
input, so the model is not bettable until this exists.

Naver's preview carries both starters with season ERA, innings, K and BB, plus their splits
against that specific opponent. One call per game, so a season is ~720 calls.
"""
import json, os, sys, math, time, collections
import requests

GAMES = "kbo_games.jsonl"
OUT = "kbo_starters.jsonl"
API = "https://api-gw.sports.naver.com/schedule/games/%s/preview"
H = {"User-Agent": "Mozilla/5.0"}


def _f(v, d=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def pull(year=None):
    games = []
    for l in open(GAMES, encoding="utf-8"):
        try:
            g = json.loads(l)
        except Exception:
            continue
        if year and g["date"][:4] != str(year):
            continue
        games.append(g)
    have = set()
    if os.path.exists(OUT):
        for l in open(OUT, encoding="utf-8"):
            try:
                have.add(json.loads(l)["gameId"])
            except Exception:
                pass
    todo = [g for g in games if g["gameId"] not in have]
    print("%d games, %d already have starters, %d to fetch" % (len(games), len(have), len(todo)),
          flush=True)
    f = open(OUT, "a", encoding="utf-8")
    got = 0
    for i, g in enumerate(todo, 1):
        try:
            r = requests.get(API % g["gameId"], headers=H, timeout=25)
            if r.status_code != 200:
                time.sleep(0.5)
                continue
            p = (r.json().get("result") or {}).get("previewData") or {}
        except Exception:
            time.sleep(2)
            continue
        row = dict(gameId=g["gameId"], date=g["date"], home=g["home"], away=g["away"],
                   hs=g["hs"], as_=g["as_"])
        ok = False
        for side, tag in (("homeStarter", "h"), ("awayStarter", "a")):
            s = p.get(side) or {}
            pi = s.get("playerInfo") or {}
            cs = s.get("currentSeasonStats") or {}
            if pi.get("name"):
                ok = True
            row[tag + "_sp"] = pi.get("name")
            row[tag + "_code"] = pi.get("pCode")
            row[tag + "_era"] = _f(cs.get("era"))
            row[tag + "_inn"] = _f(cs.get("inn"))
            row[tag + "_k"] = _f(cs.get("kk"))
            row[tag + "_bb"] = _f(cs.get("bb"))
        if ok:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            got += 1
        if i % 100 == 0:
            f.flush()
            print("  %d/%d  (%d saved)" % (i, len(todo), got), flush=True)
        time.sleep(0.25)
    f.close()
    print("done: %d starters saved -> %s" % (got, OUT))


def fit():
    """How much does the starters' ERA gap move the result, on top of team strength?"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import _kbo as K
    rows = [json.loads(l) for l in open(OUT, encoding="utf-8")]
    rows = [r for r in rows if r.get("h_era") and r.get("a_era")
            and (r.get("h_inn") or 0) >= 20 and (r.get("a_inn") or 0) >= 20]
    rows.sort(key=lambda r: r["date"])
    if len(rows) < 200:
        print("only %d usable rows -- let the pull finish" % len(rows))
        return
    allg = K.load()
    adv, _ = K.fit_home_adv(allg)
    e = K.Elo(12.0, adv, 0.60)
    by = {g["gameId"]: g for g in allg}
    print("%d games with both starters (>=20 IP)\n" % len(rows))
    # walk forward: rate every game with team-only Elo, then see what the ERA gap adds
    buckets = collections.defaultdict(lambda: [0, 0])
    resid = []
    order = sorted(allg, key=lambda g: (g["date"], g["gameId"]))
    sp = {r["gameId"]: r for r in rows}
    for g in order:
        r = sp.get(g["gameId"])
        if r and g["hs"] != g["as_"]:
            p = e.p_home(g["home"], g["away"])
            won = 1 if g["hs"] > g["as_"] else 0
            gap = r["a_era"] - r["h_era"]          # positive = home starter is better
            b = max(-3, min(3, round(gap)))
            buckets[b][0] += 1
            buckets[b][1] += won
            resid.append((gap, won - p))
        e.update(g)
    print("  home win rate by starters' ERA gap (positive = home starter better):")
    for b in sorted(buckets):
        n, w = buckets[b]
        if n >= 40:
            print("    gap %+d ERA   %5.1f%% of %4d games" % (b, 100 * w / n, n))
    n = len(resid)
    mx = sum(g for g, _ in resid) / n
    my = sum(d for _, d in resid) / n
    cov = sum((g - mx) * (d - my) for g, d in resid)
    var = sum((g - mx) ** 2 for g, _ in resid)
    beta = cov / var if var else 0
    print("\n  on top of team Elo, each 1.00 of ERA gap is worth %+.1f points of win probability"
          % (100 * beta))
    sd = math.sqrt(sum((d - my) ** 2 for _, d in resid) / n)
    se = sd / math.sqrt(var) if var else 0
    print("  (%d games; %s)" % (n, "real signal" if abs(beta) > 2 * se else "NOT distinguishable from noise"))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "fit":
        fit()
    else:
        pull(a[1] if len(a) > 1 else None)
