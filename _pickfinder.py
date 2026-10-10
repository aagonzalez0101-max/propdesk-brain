"""The PickFinder stack, systematised -- every filter a capper runs, plus the one they skip.

    python _pickfinder.py mlb  "Ronald Acuna Jr" hrr 0.5 --vs "Andrew Abbott" --price -363
    python _pickfinder.py mlb  "Aaron Judge" hits 0.5 --vs "Garrett Crochet"
    python _pickfinder.py wnba "Chelsea Gray" ast 3.5 --opp PHX --price -140

Built after watching TWO6ZERO's 2026-09-24 card (his method went 3-for-3; his one gut pick,
"Dodgers ML, no research needed", was the only loser). His stack:

    1. does a PITCHER HEAD-TO-HEAD exist   -- he refuses to bet a hitter without one
    2. all-time vs that pitcher
    3. vs HANDEDNESS (LHP/RHP)             -- the split we were NOT checking
    4. last 5 / last 10 / last 15
    5. whole season
    6. head-to-head vs that TEAM
    7. the price                           -- THE ONE HE SKIPS

Point 7 is why his Acuna leg was a losing bet even though it won: 0.5+ HRR is a 73.3% event
over 105 games and he paid -363, which implies 78.4%. A 73% event sold at 78% is -6.5%.
And it is why "Dodgers ML, 85-90% hit rate" was wrong -- they are 99-65, i.e. 60.4%.

RULE: a rate is only a bet when the price sits BELOW it. This tool prints both and says so.
"""
import sys, json, re, datetime, statistics
import requests

H = {"User-Agent": "Mozilla/5.0"}
MLB = "https://statsapi.mlb.com/api/v1"
norm = lambda s: re.sub(r"[^a-z]", "", (s or "").lower())


def implied(american):
    a = float(american)
    return (-a) / ((-a) + 100) if a < 0 else 100 / (a + 100)


def american(p):
    # a rate of exactly 1.0 (or 0.0) has no price; clamp so an 18-of-18 does not divide by zero
    p = min(0.995, max(0.005, p))
    return "%+d" % (round(-100 * p / (1 - p)) if p >= .5 else round(100 * (1 - p) / p))


def shrink(rate, n, k=12):
    """A 100%-of-5 is not 100%. Pull every rate toward a coin flip by k pseudo-games."""
    return (rate * n + 0.5 * k) / (n + k)


def mlb_person(name):
    r = requests.get(MLB + "/people/search", params=dict(names=name), headers=H, timeout=25).json()
    p = r.get("people") or []
    return p[0] if p else None


def mlb_value(stat, s):
    g = lambda k: s.get(k) or 0
    return {"hrr": g("hits") + g("runs") + g("rbi"), "hits": g("hits"), "runs": g("runs"),
            "rbi": g("rbi"), "tb": g("totalBases"), "hr": g("homeRuns"),
            "k": g("strikeOuts")}.get(stat)


def mlb_report(name, stat, line, vs_pitcher=None, price=None):
    me = mlb_person(name)
    if not me:
        print("no player called %r" % name); return
    st = requests.get(MLB + "/people/%d/stats" % me["id"],
                      params=dict(stats="gameLog", group="hitting", season=2026),
                      headers=H, timeout=30).json()
    sp = (st.get("stats") or [{}])[0].get("splits") or []
    if not sp:
        print("no 2026 game log for %s" % me["fullName"]); return
    vals, opps = [], []
    for x in sp:
        v = mlb_value(stat, x["stat"])
        if v is None:
            continue
        vals.append(v)
        opps.append((x.get("opponent") or {}).get("name", "?"))
    hit = lambda s: sum(1 for v in s if v > line) / len(s) if s else 0
    print("=" * 74)
    print("%s -- %s OVER %.1f" % (me["fullName"].upper(), stat.upper(), line))
    print("=" * 74)
    print("\n  WINDOW          rate        games   avg")
    for lbl, s in (("whole season", vals), ("last 15", vals[-15:]), ("last 10", vals[-10:]),
                   ("last 5", vals[-5:])):
        if s:
            print("  %-15s %5.0f%%       %-7d %.2f" % (lbl, 100 * hit(s), len(s), statistics.mean(s)))
    # --- handedness split: the piece we were missing
    for code, lbl in (("vl", "vs LHP"), ("vr", "vs RHP")):
        try:
            d = requests.get(MLB + "/people/%d/stats" % me["id"],
                             params=dict(stats="statSplits", group="hitting", season=2026,
                                         sitCodes=code), headers=H, timeout=25).json()
            sl = (d.get("stats") or [{}])[0].get("splits") or []
            if sl:
                s2 = sl[0]["stat"]
                print("  %-15s AVG %s  OPS %s  (%s PA)" % (lbl, s2.get("avg"), s2.get("ops"), s2.get("plateAppearances")))
        except Exception:
            pass
    # --- head to head vs the opposing starter
    h2h_n = 0
    if vs_pitcher:
        pit = mlb_person(vs_pitcher)
        if pit:
            try:
                d = requests.get(MLB + "/people/%d/stats" % me["id"],
                                 params=dict(stats="vsPlayer", group="hitting",
                                             opposingPlayerId=pit["id"]),
                                 headers=H, timeout=25).json()
                # CAREER total lives in the 'vsPlayerTotal' block. The first split of the first block is
                # ONE season -- that bug showed Machado 2-for-4 vs Boyd when his career is 9-for-19 (2026-09-29).
                blocks = sorted(d.get("stats") or [], key=lambda b: (b.get("type") or {}).get("displayName") != "vsPlayerTotal")
                for blk in blocks:
                    for s3 in (blk.get("splits") or []):
                        t = s3["stat"]
                        h2h_n = t.get("plateAppearances") or 0
                        print("\n  PITCHER HEAD-TO-HEAD (career) vs %s" % pit["fullName"])
                        print("    %s PA, %s AB, %s H, %s HR, %s RBI, AVG %s, OPS %s" % (
                            t.get("plateAppearances"), t.get("atBats"), t.get("hits"),
                            t.get("homeRuns"), t.get("rbi"), t.get("avg"), t.get("ops")))
                        break
                    break
            except Exception as e:
                print("\n  head-to-head lookup failed: %s" % str(e)[:60])
            if not h2h_n:
                print("\n  PITCHER HEAD-TO-HEAD vs %s: NONE" % pit["fullName"])
                print("    TWO6ZERO refuses to bet a hitter without one. Treat as a downgrade.")
    raw = hit(vals)
    sh = shrink(raw, len(vals))
    print("\n  ---------------------------------------------------------------")
    print("  RAW RATE      %.1f%% over %d games" % (100 * raw, len(vals)))
    print("  SHRUNK        %.1f%%   (a small sample is not a rate)" % (100 * sh))
    print("  FAIR PRICE    %s raw / %s shrunk" % (american(raw), american(sh)))
    if price is not None:
        imp = implied(price)
        print("\n  THEIR PRICE   %+d  = %.1f%% implied" % (price, 100 * imp))
        print("  EDGE          %+.1f%% on raw    %+.1f%% on shrunk" % (100 * (raw / imp - 1), 100 * (sh / imp - 1)))
        verdict = "TAKE" if sh > imp else ("thin -- raw clears but shrunk does not" if raw > imp else "PASS")
        print("  VERDICT       %s" % verdict)
        if raw > imp > sh:
            print("                the price sits between the raw and shrunk rate; size small")
    else:
        print("\n  no --price given. A rate is not a bet until the number is below it.")


def wnba_report(name, stat, line, opp=None, price=None):
    P = json.load(open("wnba_player_ctx.json", encoding="utf-8"))
    gs = P.get(norm(name))
    if not gs:
        print("no context games for %r (run the join in wnba_player_ctx.json)" % name); return
    gs = sorted(gs, key=lambda x: x["date"])
    def val(g):
        return {"pts": g.get("pts"), "reb": g.get("reb"), "ast": g.get("ast"),
                "tpm": g.get("tpm"), "rebast": (g.get("reb") or 0) + (g.get("ast") or 0),
                "pra": (g.get("pts") or 0) + (g.get("reb") or 0) + (g.get("ast") or 0)}.get(stat)
    vals = [val(g) for g in gs if val(g) is not None]
    hit = lambda s: sum(1 for v in s if v > line) / len(s) if s else 0
    print("=" * 74)
    print("%s -- %s OVER %.1f" % (name.upper(), stat.upper(), line))
    print("=" * 74)
    print("\n  WINDOW          rate        games   avg")
    for lbl, s in (("whole season", vals), ("last 15", vals[-15:]), ("last 10", vals[-10:]),
                   ("last 5", vals[-5:])):
        if s:
            print("  %-15s %5.0f%%       %-7d %.1f" % (lbl, 100 * hit(s), len(s), statistics.mean(s)))
    if opp:
        vo = [val(g) for g in gs if g.get("opp") == opp and val(g) is not None]
        if vo:
            print("  %-15s %5.0f%%       %-7d %.1f   <- head to head" % ("vs " + opp, 100 * hit(vo), len(vo), statistics.mean(vo)))
        else:
            print("  vs %-12s no games" % opp)
    blow = [val(g) for g in gs if abs(g.get("margin") or 0) >= 12 and val(g) is not None]
    if blow:
        print("  %-15s %5.0f%%       %-7d %.1f   <- minutes risk" % ("in blowouts", 100 * hit(blow), len(blow), statistics.mean(blow)))
    mins = [g.get("min") for g in gs if g.get("min")]
    if mins:
        print("\n  minutes: season %.1f, last 5 %.1f %s" % (
            statistics.mean(mins), statistics.mean(mins[-5:]),
            "<- TRENDING DOWN" if statistics.mean(mins[-5:]) < statistics.mean(mins) - 2 else ""))
    raw = hit(vals); sh = shrink(raw, len(vals))
    print("\n  ---------------------------------------------------------------")
    print("  RAW RATE      %.1f%% over %d games" % (100 * raw, len(vals)))
    print("  SHRUNK        %.1f%%" % (100 * sh))
    print("  FAIR PRICE    %s raw / %s shrunk" % (american(raw), american(sh)))
    if price is not None:
        imp = implied(price)
        print("\n  THEIR PRICE   %+d  = %.1f%% implied" % (price, 100 * imp))
        print("  EDGE          %+.1f%% on raw    %+.1f%% on shrunk" % (100 * (raw / imp - 1), 100 * (sh / imp - 1)))
        print("  VERDICT       %s" % ("TAKE" if sh > imp else ("thin" if raw > imp else "PASS")))


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) < 4:
        print(__doc__); sys.exit()
    sport, name, stat, line = a[0], a[1], a[2], float(a[3])
    opt = lambda f: (a[a.index(f) + 1] if f in a else None)
    price = opt("--price")
    price = float(price) if price else None
    if sport == "mlb":
        mlb_report(name, stat, line, opt("--vs"), price)
    elif sport == "wnba":
        wnba_report(name, stat, line, opt("--opp"), price)
    else:
        print("sports: mlb, wnba")
