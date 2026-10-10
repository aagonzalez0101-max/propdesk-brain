"""Grade every prop the boards priced, then compare RAW vs CALIBRATED -> prop_graded.jsonl

    python _propgrade.py

Same question we asked of the moneyline: does the calibration staircase help or hurt? The
boards store both numbers on every pick, so the honest test is to grade all of them off the
box scores and see which one picked better bets. Markets: K (strikeouts), OUTS (outs recorded),
ER (earned runs), HITS (hits allowed) for starters; HRR (hits+runs+RBIs) for batters.
"""
import json, glob, os, time, collections, urllib.request

API = "https://statsapi.mlb.com/api/v1"
UA = {"User-Agent": "Mozilla/5.0"}
OUT = "prop_graded.jsonl"
g = lambda u: json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=45).read())
be = lambda o: abs(o) / (abs(o) + 100) if o < 0 else 100 / (o + 100)
dec = lambda o: 1 + (o / 100 if o > 0 else 100 / abs(o))


def board_props():
    picks = {}
    for f in sorted(glob.glob("pp/boards/2026-09-*.json")):
        try:
            b = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for p in b.get("picks", []):
            if p.get("market") in ("K", "OUTS", "ER", "HITS", "HRR") and p.get("raw") is not None:
                picks.setdefault((b["day"], p["game"], p["market"], p["selection"], p["line"], p["side"]), p)
    return picks


def day_actuals(day, cache={}):
    """name -> {K, OUTS, ER, HITS, HRR} from every final box score that day."""
    if day in cache:
        return cache[day]
    out = {}
    try:
        sched = g("%s/schedule?sportId=1&date=%s" % (API, day))
    except Exception:
        cache[day] = out
        return out
    for dt in sched.get("dates", []):
        for gm in dt["games"]:
            if gm["status"]["detailedState"] != "Final":
                continue
            try:
                box = g("%s/game/%d/boxscore" % (API, gm["gamePk"]))
            except Exception:
                continue
            for side in ("away", "home"):
                for pid, pl in box["teams"][side]["players"].items():
                    nm = pl["person"]["fullName"]
                    st = pl.get("stats", {})
                    p, b = st.get("pitching") or {}, st.get("batting") or {}
                    rec = out.setdefault(nm, {})
                    if p:
                        ip = p.get("inningsPitched")
                        if ip is not None:
                            whole, _, frac = str(ip).partition(".")
                            rec["OUTS"] = int(whole) * 3 + int(frac or 0)
                        rec["K"] = p.get("strikeOuts")
                        rec["ER"] = p.get("earnedRuns")
                        rec["HITS"] = p.get("hits")
                    if b and b.get("atBats") is not None:
                        rec["HRR"] = (b.get("hits") or 0) + (b.get("runs") or 0) + (b.get("rbi") or 0)
            time.sleep(0.05)
    cache[day] = out
    return out


def main():
    picks = board_props()
    days = sorted({k[0] for k in picks})
    print("%d prop picks on %d days" % (len(picks), len(days)))
    rows = []
    for i, day in enumerate(days, 1):
        act = day_actuals(day)
        n = 0
        for (d2, game, mkt, sel, line, side), p in picks.items():
            if d2 != day:
                continue
            v = (act.get(sel) or {}).get(mkt)
            if v is None:
                continue
            won = (v > line) if side.upper() == "OVER" else (v < line)
            if v == line:
                continue                      # push
            rows.append(dict(day=day, market=mkt, selection=sel, line=line, side=side,
                             odds=p.get("odds"), raw=p["raw"], cal=p["calibrated"],
                             season=p.get("season_rate"), samples=p.get("samples"),
                             actual=v, won=bool(won)))
            n += 1
        print("  %s graded %d  (%d/%d days)" % (day, n, i, len(days)), flush=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print("wrote %d graded props -> %s" % (len(rows), OUT))


if __name__ == "__main__":
    main()
