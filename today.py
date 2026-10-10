"""TODAY CARD -- one command per sport. Only rules that PASSED a test are here.

    python today.py mlb          # board first: python _tmr.py <day>
    python today.py nfl | cfb | soccer | tennis | esports | all

Every line names the RULE and its measured hit rate. Unmeasured ideas do not
appear. Rejected ones live in reference_capper_tactics.md so we never rebuild
them.
"""
import sys, json, glob, datetime, subprocess, io
sys.path.insert(0, "betting")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace",
                              line_buffering=True)
CT = datetime.timezone(datetime.timedelta(hours=-5))
today = datetime.datetime.now(CT).date().isoformat()
dec = lambda a: 1 + a / 100 if a > 0 else 1 + 100 / -a
amer = lambda p: round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def hdr(t):
    print("\n" + "=" * 74 + "\n" + t + "\n" + "=" * 74)


def mlb(day):
    hdr("MLB  " + day)
    b = sorted(glob.glob("pp/boards/%s_*.json" % day))
    if not b:
        print("  no board today. build it:  python _tmr.py " + day)
        return
    print("  board: " + b[-1])
    print("  RULE: run line, model sign-stable, +5% EV AT YOUR PRICE, clean flags.")
    print("  (run lines are our only market with a live winning record: 6-2)")
    subprocess.run([sys.executable, "_runlines.py", b[-1]], timeout=900)
    print("\n  re-price vs 26-30 books (Kalshi alone was 6pp off on 09-16):")
    print("    python _repricer.py %s mlb %s" % (b[-1], day))
    print("  then the flags before betting:")
    print("    python _laddercheck.py <away> <home> --day %s --taken <price>" % day)


def nfl(day):
    hdr("NFL  " + day)
    print("  RULE 1  wind >= 12 mph -> UNDER. 55.5% (z=+3.52, n=1031), +7.8% ROI at -110")
    print("  RULE 2  6-pt teaser, UNDERDOG legs ONLY (+1.5..+2.5 -> +7.5..+8.5)")
    print("          2020-26: 76.6% per leg; 2-leg 61.5% vs 52.4% break-even = +17.5%")
    print("          NEVER the favourite leg: decayed to 71.2%, now below break-even")
    print("  RULE 3  #1 target OVER receiving yds: 61.2% on REAL Underdog lines (wk1, n=49)")
    print("          QB pass yds = 46% = coin flip, skip. RB3/WR4 unders: NOT an edge --")
    print("          the old 93%/83% counted DNPs as wins; books VOID a DNP (real: 33%)")
    print("  RULE 4  buy the half point off 3 (+5.4pp). Off 7 is only +2.9pp now")
    print("\n  props screen:  python _nflscreen.py    (needs _ud_tonight.json)")


def cfb(day):
    hdr("CFB  " + day)
    print("  RULE  buy the half point off an INTEGER spread.")
    print("        pushes: 6.2% at ~3, 7.4% at ~7, 6.3% at ~10 (n=7,350 games)")
    print("        costs ~2.2pp at -110/-120  ->  about +4pp net")
    print("  DEAD  line-move following: moved toward the cover 50.7% (n=3,518)")
    print("  DEAD  blanket unders: 49.4% (n=9,578)")
    try:
        import urllib.request
        u = ("https://site.web.api.espn.com/apis/site/v2/sports/football/college-football/"
             "scoreboard?dates=%s&groups=80&limit=100" % day.replace("-", ""))
        d = json.loads(urllib.request.urlopen(urllib.request.Request(
            u, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read())
        n = 0
        for e in d.get("events", []):
            od = (e["competitions"][0].get("odds") or [{}])[0]
            det = od.get("details", "")
            tail = det.split()[-1] if det else ""
            try:
                num = abs(float(tail))
            except ValueError:
                continue
            if num and num == int(num):
                print("    %-24s %-12s <- integer line, buy the half point"
                      % (e["shortName"], det))
                n += 1
        print("  %d integer-spread games today" % n)
    except Exception as ex:
        print("  (espn odds unavailable: %s)" % ex)


def soccer(day):
    hdr("SOCCER  " + day)
    print("  RULE 1  over 1.5 goals, all three filters -> 82.1% (n=1,355). Bet at -450+")
    subprocess.run([sys.executable, "_soccer15.py", "--day", day], timeout=600)
    print("\n  RULE 2  fair-win 70-80% favourites are the ONLY band with positive ROI")
    print("          at book prices (+5pp vs priced). Above 80% there is no edge.")
    print("  RULE 3  xG check first: python _soccerxg.py La_liga 2026 <Team>")
    print("          (Atletico ran +3.8 goals over xG in 5 games -> that side was fake)")
    print("  full scan w/ injuries+form:  python _soccerscout.py " + day)


def tennis(day):
    hdr("TENNIS  " + day)
    print("  RULE  total games UNDER, triggered by PRICE alone (no rankings needed).")
    print("        94,481 best-of-3 matches with odds:")
    print("          WTA fav 85-93% -> under 22.5 = 76.5%   (fair -325)")
    print("          WTA fav 93%+   -> under 22.5 = 89.2%")
    print("          ATP fav 85-93% -> under 22.5 = 68.1%   (fair -213)")
    print("        WTA runs ~1.5 games shorter than ATP at the same price.")
    try:
        import freeodds as fo
        mu = fo._get("%s/0.1/sports/33/matchups?withSpecials=false&brandId=0" % fo.PIN) or []
        mk = fo._get("%s/0.1/sports/33/markets/straight?primaryOnly=true" % fo.PIN) or []
        px = {m["matchupId"]: {p.get("designation"): p.get("price")
                               for p in m.get("prices", [])}
              for m in mk if m.get("key") == "s;0;m" and not m.get("isAlternate")}
        lo = datetime.datetime.fromisoformat(day + "T05:00:00+00:00")
        hi = lo + datetime.timedelta(hours=30)
        hits = 0
        for m in mu:
            if m.get("parentId") or m.get("type") != "matchup":
                continue
            t = datetime.datetime.fromisoformat(m["startTime"].replace("Z", "+00:00"))
            if not (lo <= t < hi):
                continue
            p = px.get(m["id"])
            if not p or p.get("home") is None or p.get("away") is None:
                continue
            s = {q["alignment"]: q["name"] for q in m["participants"]}
            ih, ia = 1 / dec(p["home"]), 1 / dec(p["away"])
            fh, fa = ih / (ih + ia), ia / (ih + ia)
            fav, fp = (s["home"], fh) if fh > fa else (s["away"], fa)
            lg = (m.get("league") or {}).get("name", "")
            U = lg.upper()
            wta = "WTA" in U or "WOMEN" in U
            main = ("ATP" in U or "WTA" in U) and "ITF" not in U and "CHALLENGER" not in U
            if fp >= 0.85:
                rate = (0.892 if fp >= 0.93 else 0.765) if wta else (0.787 if fp >= 0.93 else 0.681)
                hits += 1
                ct = (t - datetime.timedelta(hours=5)).strftime("%H:%M")
                print("  %s %s  %s v %s | fav %s %.0f%% -> UNDER 22.5 games, %.1f%% (fair %+d) [%s %s CT]"
                      % ("**" if main else "  ", "WTA" if wta else "ATP",
                         s["home"][:18], s["away"][:18], fav[:16], 100 * fp,
                         100 * rate, amer(rate), lg[:24], ct))
        print("  %d matches trigger the rule today  (** = ATP/WTA main tour, the ones a"
              " retail book will actually list; ITF/Challenger usually are not offered)" % hits)
    except Exception as ex:
        print("  (pinnacle tennis unavailable: %s)" % ex)


def esports(day):
    hdr("ESPORTS  " + day)
    print("  RULE  rate with GLICKO, not Elo: 63.1% vs 60.9% (n=8,601 graded)")
    print("  RULE  hunt tier B/C, not tier S. Favourite wins: C 61.6%, B 60.7%,")
    print("        S 58.9%, A 49.0%. Big events are the least predictable AND the")
    print("        most sharply priced; small ones are soft.")
    print("  DEAD  Bo1 is NOT a coin flip: Bo1 60.1% vs Bo3 60.7%, no difference")
    print("\n  refresh:  python _esports_elo.py fetch 150 && python _esports_elo.py glicko")


if __name__ == "__main__":
    what = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    day = next((a for a in sys.argv[2:] if a.count("-") == 2), today)
    fns = dict(mlb=mlb, nfl=nfl, cfb=cfb, soccer=soccer, tennis=tennis, esports=esports)
    if what == "all":
        for f in fns.values():
            f(day)
    elif what in fns:
        fns[what](day)
    else:
        print("usage: python today.py [mlb|nfl|cfb|soccer|tennis|esports|all] [YYYY-MM-DD]")
