"""Esports card: Glicko ratings (bo3.gg history) vs Pinnacle moneylines.

    python _esports_today.py            # next 36h
    python _esports_today.py 48         # next 48h

Ratings come from esports_matches.json (refresh: python _esports_elo.py fetch 5).
Only teams with 8+ rated matches and an RD under 120 are priced -- a new or
rarely-seen team's rating is noise. Measured: Glicko 63.1% accuracy overall,
tier C 61.6% / S 58.9%. The model has NOT been tested against prices yet, so
every row here is PAPER until it has a CLV / hit-rate record.
"""
import sys, json, io, re, datetime, urllib.request, collections, difflib
sys.path.insert(0, "betting")
import freeodds as fo
import _esports_elo as E          # rebinds stdout to utf-8 on import

UA = {"User-Agent": "Mozilla/5.0 Chrome/124", "Accept": "application/json"}
g = lambda u: json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30).read())
CT = datetime.timezone(datetime.timedelta(hours=-5))
dec = lambda a: 1 + a / 100 if a > 0 else 1 + 100 / -a
amer = lambda p: round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower().replace("esports", "").replace("gaming", "").replace("team", ""))


def upcoming(hours):
    now = datetime.datetime.now(datetime.timezone.utc)
    out = []
    for off in range(0, 1000, 100):
        d = g("https://api.bo3.gg/api/v1/matches?page[offset]=%d&page[limit]=100&sort=start_date"
              "&filter[matches.status][in]=upcoming&with=teams" % off)
        for m in d["results"]:
            t = datetime.datetime.fromisoformat(m["start_date"])
            if t > now + datetime.timedelta(hours=hours):
                return out
            if m.get("team1") and m.get("team2"):
                out.append(m)
        if len(d["results"]) < 100:
            break
    return out


def pinnacle():
    mu = fo._get("%s/0.1/sports/12/matchups?withSpecials=false&brandId=0" % fo.PIN) or []
    mk = fo._get("%s/0.1/sports/12/markets/straight?primaryOnly=true" % fo.PIN) or []
    px = {m["matchupId"]: {p.get("designation"): p.get("price") for p in m.get("prices", [])}
          for m in mk if m.get("key") == "s;0;m" and m.get("period") == 0}
    rows = []
    for m in mu:
        if m.get("parentId") or m.get("type") != "matchup" or m["id"] not in px:
            continue
        p = px[m["id"]]
        if p.get("home") is None or p.get("away") is None:
            continue
        s = {q["alignment"]: q["name"] for q in m["participants"]}
        ih, ia = 1 / dec(p["home"]), 1 / dec(p["away"])
        rows.append(dict(home=s["home"], away=s["away"], ph=p["home"], pa=p["away"],
                         fh=ih / (ih + ia), league=m["league"]["name"], start=m["startTime"]))
    return rows


def main(hours=36):
    R, RD, (n, acc, ll) = E.glicko()
    seen = collections.Counter()
    for r in json.load(open(E.F, encoding="utf-8")).values():
        seen[r["t1"]] += 1
        seen[r["t2"]] += 1
    print("Glicko on %d graded matches: %.1f%% accuracy" % (n, 100 * acc))
    bo = upcoming(hours)
    pin = pinnacle()
    print("bo3.gg upcoming w/ both teams: %d | Pinnacle esports lines: %d\n" % (len(bo), len(pin)))
    q = __import__("math").log(10) / 400
    out = []
    for p in pin:
        best = None
        for m in bo:
            for flip in (False, True):
                t1, t2 = (m["team2"], m["team1"]) if flip else (m["team1"], m["team2"])
                sc = (difflib.SequenceMatcher(None, norm(p["home"]), norm(t1["name"])).ratio()
                      + difflib.SequenceMatcher(None, norm(p["away"]), norm(t2["name"])).ratio()) / 2
                if not best or sc > best[0]:
                    best = (sc, m, t1, t2)
        if not best or best[0] < 0.8:
            continue
        _, m, th, ta = best
        a, b = th["id"], ta["id"]
        if min(seen[a], seen[b]) < 8 or max(RD[a], RD[b]) > 120:
            continue
        gf = lambda rd: 1 / (1 + 3 * q * q * rd * rd / 9.8696) ** 0.5
        mh = 1 / (1 + 10 ** (-gf((RD[a] ** 2 + RD[b] ** 2) ** 0.5) * (R[a] - R[b]) / 400))
        for side, mp, fp, price in ((p["home"], mh, p["fh"], p["ph"]), (p["away"], 1 - mh, 1 - p["fh"], p["pa"])):
            ev = mp * dec(price) - 1
            out.append((ev, side, p["home"] + " v " + p["away"], mp, fp, price, m["tier"], p["league"],
                        datetime.datetime.fromisoformat(p["start"].replace("Z", "+00:00")).astimezone(CT)))
    out.sort(reverse=True)
    print("%-6s %-22s %-40s %6s %6s %6s %4s  %s" % ("EV", "side", "match", "model", "fair", "price", "tier", "league / CT"))
    for ev, side, match, mp, fp, price, tier, lg, t in out:
        if mp <= fp:
            continue
        print("%+5.1f%% %-22s %-40s %5.1f%% %5.1f%% %+6d %4s  %s %s" % (
            100 * ev, side[:22], match[:40], 100 * mp, 100 * fp, price, (tier or "?").upper(), lg[:28], t.strftime("%a %H:%M")))
    print("\nPAPER ONLY: Glicko has never been graded against prices. EV above ~25% is a mismatch bug.")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 36)
