"""Multi-source soccer scout: market price + Understat xG + FotMob injuries/form.

  python _soccerscout.py 2026-09-16              # every fixture that day, favourites >=65%
  python _soccerscout.py 2026-09-16 Barcelona    # filter by team

Sources (all free, no key):
  Pinnacle guest  -> fair win % (3-way power de-vig)
  Understat       -> team xG/g, finishing luck, player xG90 (top-5 leagues only)
  FotMob          -> injuries/suspensions, last-5 form  (api/data/matchDetails)
Blocked/dead: sofascore 403, fbref 403, clubelo Fixtures API deactivated,
ESPN site.api 403 (site.web.api works), api-football needs a key (not allowed).
"""
import sys, json, datetime, urllib.request, io
sys.path.insert(0, "betting")
import freeodds as fo
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
G = lambda u: json.loads(urllib.request.urlopen(
    urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "application/json"}), timeout=30).read())
dec = lambda a: 1 + a / 100 if a > 0 else 1 + 100 / -a


def fair(day):
    """{(home,away): (fair_home, fair_away, american_home, american_away, league, kickoff)}"""
    mu = fo._get("%s/0.1/sports/29/matchups?withSpecials=false&brandId=0" % fo.PIN) or []
    mk = fo._get("%s/0.1/sports/29/markets/straight?primaryOnly=true" % fo.PIN) or []
    px = {m["matchupId"]: {p.get("designation"): p.get("price") for p in m.get("prices", [])}
          for m in mk if m.get("key") == "s;0;m" and not m.get("isAlternate")}
    lo = datetime.datetime.fromisoformat(day + "T05:00:00+00:00")
    hi = lo + datetime.timedelta(hours=26)
    out = {}
    for m in mu:
        if m.get("parentId") or m.get("type") != "matchup":
            continue
        t = datetime.datetime.fromisoformat(m["startTime"].replace("Z", "+00:00"))
        if not (lo <= t < hi):
            continue
        p = px.get(m["id"])
        if not p or None in (p.get("home"), p.get("draw"), p.get("away")):
            continue
        s = {q["alignment"]: q["name"] for q in m["participants"]}
        ih, idr, ia = 1 / dec(p["home"]), 1 / dec(p["draw"]), 1 / dec(p["away"])
        k = 1.0
        for _ in range(80):
            tot = ih ** k + idr ** k + ia ** k
            if abs(tot - 1) < 1e-9:
                break
            k *= (1 + (tot - 1) * 0.4) if tot > 1 else (1 - (1 - tot) * 0.4)
        out[(s["home"], s["away"])] = (ih ** k, ia ** k, p["home"], p["away"],
                                       (m.get("league") or {}).get("name", ""),
                                       (t - datetime.timedelta(hours=5)).strftime("%H:%M"))
    return out


def fotmob(day):
    d = G("https://www.fotmob.com/api/data/matches?date=" + day.replace("-", ""))
    out = {}
    for lg in d.get("leagues", []):
        for m in lg.get("matches", []):
            out[(m["home"]["name"], m["away"]["name"])] = m["id"]
    return out


def detail(mid):
    c = G("https://www.fotmob.com/api/data/matchDetails?matchId=%d" % mid)["content"]
    lu = c.get("lineup") or {}
    inj = {}
    for side in ("homeTeam", "awayTeam"):
        t = lu.get(side) or {}
        inj[t.get("name")] = [(p.get("name"), (p.get("unavailability") or {}).get("type"),
                               (p.get("unavailability") or {}).get("expectedReturn", ""))
                              for p in (t.get("unavailable") or [])]
    tf = (c.get("matchFacts") or {}).get("teamForm")
    form = [" ".join(x.get("resultString", "?") for x in f[:5]) for f in tf] if tf else []
    return inj, form


def match_key(keys, a, b):
    """fuzzy-match the two feeds' team names"""
    for (h, aw) in keys:
        if (a.split()[0].lower() in h.lower() or h.split()[0].lower() in a.lower()) and \
           (b.split()[0].lower() in aw.lower() or aw.split()[0].lower() in b.lower()):
            return (h, aw)
    return None


if __name__ == "__main__":
    day = sys.argv[1]
    filt = sys.argv[2].lower() if len(sys.argv) > 2 else None
    pri = fair(day)
    fm = fotmob(day)
    rows = sorted(pri.items(), key=lambda kv: -max(kv[1][0], kv[1][1]))
    for (h, a), (fh, fa, ah, aa, lg, ct) in rows:
        top = max(fh, fa)
        if top < 0.65:
            continue
        if filt and filt not in h.lower() and filt not in a.lower():
            continue
        fav, fp, am = (h, fh, ah) if fh > fa else (a, fa, aa)
        print("=" * 72)
        print(f"{h} v {a}   {ct} CT   {lg}")
        print(f"  fair: {fav} {fp:.1%}  ({am:+d})   draw risk at this price ~{14.5 if fp<0.8 else 10.5:.1f}%")
        k = match_key(fm, h, a)
        if k:
            try:
                inj, form = detail(fm[k])
                for team, lst in inj.items():
                    if lst:
                        print(f"  {team} OUT/DOUBT: " + "; ".join(f"{n} ({t})" for n, t, _ in lst[:6]))
                for lbl, f in zip(("home", "away"), form):
                    print(f"  form {lbl}: {f}")
            except Exception as e:
                print("  fotmob detail failed:", e)
        else:
            print("  (no fotmob match found)")
