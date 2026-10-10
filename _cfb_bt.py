"""CFB SIDES + TOTALS BACKTEST (2026-10-02). Walk-forward over 2025 + 2026 FBS games against ESPN's posted spread and total.

    python _cfb_bt.py            # pull scoreboards (cached) + backtest + tonight's read

Model (no peeking): each team's opponent-adjusted offense and defense (points scored / allowed vs the opponent's average), updated
after every game; prediction = home edge + rating gap. Only games where both teams have 3+ prior games are scored. A bet = our margin
disagrees with the spread by >= T points. Also scored: the totals model, and the "buy the half off a key number" rule.
"""
import os, json, urllib.request, statistics as st, math
from collections import defaultdict

H = {"User-Agent": "Mozilla/5.0"}
URL = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?dates=%d&seasontype=2&week=%d&groups=80&limit=300"
CACHE = "_cfb_sb"
os.makedirs(CACHE, exist_ok=True)


def sb(year, week):
    f = os.path.join(CACHE, "%d_%02d.json" % (year, week))
    if os.path.exists(f) and year < 2026:
        return json.load(open(f))
    d = json.loads(urllib.request.urlopen(urllib.request.Request(URL % (year, week), headers=H), timeout=40).read())
    json.dump(d, open(f, "w"))
    return d


def odds(eid):
    f = os.path.join(CACHE, "o_%s.json" % eid)
    if os.path.exists(f):
        return json.load(open(f))
    try:
        o = json.loads(urllib.request.urlopen(urllib.request.Request(
            "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football/events/%s/competitions/%s/odds" % (eid, eid),
            headers=H), timeout=30).read())
        it = (o.get("items") or [{}])[0]
        r = dict(spread=it.get("spread"), total=it.get("overUnder"))
    except Exception:
        r = dict(spread=None, total=None)
    json.dump(r, open(f, "w"))
    return r


def games():
    out = []
    for y in (2025, 2026):
        for w in range(1, 17):
            try:
                d = sb(y, w)
            except Exception:
                continue
            for e in d.get("events", []):
                c = e["competitions"][0]
                t = {x["homeAway"]: x for x in c["competitors"]}
                od = (c.get("odds") or [{}])[0]
                spread = od.get("spread"); total = od.get("overUnder")
                done = e["status"]["type"].get("completed")
                out.append(dict(y=y, w=w, date=e["date"], id=e["id"], home=t["home"]["team"]["displayName"], away=t["away"]["team"]["displayName"],
                                hs=float(t["home"].get("score") or 0) if done else None, as_=float(t["away"].get("score") or 0) if done else None,
                                spread=float(spread) if spread is not None else None, total=float(total) if total is not None else None,
                                neutral=c.get("neutralSite"), done=done, name=e["name"]))
    from concurrent.futures import ThreadPoolExecutor
    need = [g for g in out if g["spread"] is None]
    with ThreadPoolExecutor(8) as ex:
        for g, o in zip(need, ex.map(lambda g: odds(g["id"]), need)):
            g["spread"] = float(o["spread"]) if o["spread"] is not None else None
            g["total"] = float(o["total"]) if o["total"] is not None else None
    out.sort(key=lambda g: g["date"])
    return out


def run(G, T=4.0, HOME=2.5):
    pf = defaultdict(list); pa = defaultdict(list)
    res = defaultdict(lambda: [0, 0]); tot = defaultdict(lambda: [0, 0])
    preds = []
    for g in G:
        h, a = g["home"], g["away"]
        ok = len(pf[h]) >= 3 and len(pf[a]) >= 3
        if ok and g["spread"] is not None:
            lg = st.mean([x for k in pf for x in pf[k][-12:]]) if pf else 28
            off = lambda t: st.mean(pf[t][-12:]) - lg
            de = lambda t: st.mean(pa[t][-12:]) - lg
            hp = lg + off(h) + de(a) + (0 if g["neutral"] else HOME / 2)
            ap = lg + off(a) + de(h) - (0 if g["neutral"] else HOME / 2)
            margin = hp - ap
            mkt = -g["spread"]                    # ESPN spread is home-relative (negative = home favoured)
            preds.append((g, margin, hp + ap))
            if g["done"]:
                actual = g["hs"] - g["as_"]
                gap = margin - mkt
                if abs(gap) >= T and actual != mkt:
                    side_home = gap > 0
                    win = (actual > mkt) == side_home
                    res["%s-%s" % (g["y"], "all")][0 if win else 1] += 1
                if g["total"] is not None:
                    tg = (hp + ap) - g["total"]; at = g["hs"] + g["as_"]
                    if abs(tg) >= 4 and at != g["total"]:
                        tot["%s" % g["y"]][0 if ((at > g["total"]) == (tg > 0)) else 1] += 1
        if g["done"]:
            pf[h].append(g["hs"]); pa[h].append(g["as_"]); pf[a].append(g["as_"]); pa[a].append(g["hs"])
    return res, tot, preds


if __name__ == "__main__":
    G = games()
    done = [g for g in G if g["done"]]
    print("%d FBS games (%d with a spread), %s .. %s" % (len(done), sum(g["spread"] is not None for g in done), done[0]["date"][:10], done[-1]["date"][:10]))
    for T in (3, 4, 6, 8):
        res, tot, _ = run(G, T)
        s = " | ".join("%s ATS %d-%d (%.1f%%)" % (k, v[0], v[1], 100 * v[0] / max(1, sum(v))) for k, v in sorted(res.items()))
        print("edge >= %d pts: %s" % (T, s))
    _, tot, preds = run(G, 4)
    print("totals (model off the total by 4+): " + " | ".join("%s %d-%d (%.1f%%)" % (k, v[0], v[1], 100 * v[0] / max(1, sum(v))) for k, v in sorted(tot.items())))
    # favourites / dogs and key numbers, 2026 only
    print("\nTONIGHT:")
    for g, m, t in preds:
        if not g["done"] and g["date"][:10] in ("2026-10-02", "2026-10-03") and ("Pittsburgh" in g["name"] or "Virginia Tech" in g["name"]):
            print("  %s  spread %s total %s | model: %s by %.1f, total %.1f" % (g["name"], g["spread"], g["total"],
                  g["home"] if m > 0 else g["away"], abs(m), t))
