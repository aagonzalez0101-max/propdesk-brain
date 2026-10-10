"""Overseas basketball on Courtside (2026-10-07, user: "you know how overseas baseball is working? let's add these for basketball").
Same idea as KBO/NPB: Courtside's local-league prices vs Pinnacle's sharp fair number, then our own model once results build up.

    python _intl_hoops.py snap      # archive Pinnacle ML / spread / total for every league below -> intl_hoops_lines.jsonl
    python _intl_hoops.py board     # today's games with the fair (de-vigged) price + break-even for Courtside

Step 1 (now): archive lines twice a day so we have opening + closing prices for a real backtest.
Step 2 (next): free results feed per league -> Elo + rest/travel (WNBA measured: 2 days rest -> under 63%) -> model vs fair.
"""
import sys, json, datetime, time, requests
import _kbo as K

CT = datetime.timezone(datetime.timedelta(hours=-5))
LEAGUES = {382: "Euroleague", 268: "ABA", 197721: "Japan B1", 203908: "Chile LNB", 280: "Australia NBL", 197913: "Turkey BSL",
           208618: "Lithuania LKL"}
OUT = "intl_hoops_lines.jsonl"
imp = lambda o: (-o) / ((-o) + 100) if o < 0 else 100 / (o + 100)


def pull(lid):
    mu = requests.get(K.PIN + "/0.1/leagues/%d/matchups?brandId=0" % lid, headers=K.PH, timeout=25).json()
    mk = requests.get(K.PIN + "/0.1/leagues/%d/markets/straight" % lid, headers=K.PH, timeout=25).json()
    games = {}
    for m in mu:
        if m.get("parent") or len(m.get("participants") or []) != 2:
            continue
        ps = m["participants"]
        games[m["id"]] = dict(home=next((p["name"] for p in ps if p.get("alignment") == "home"), ps[0]["name"]),
                              away=next((p["name"] for p in ps if p.get("alignment") == "away"), ps[1]["name"]), start=m.get("startTime"))
    for r in mk:
        g = games.get(r.get("matchupId"))
        if not g or r.get("period") != 0:
            continue
        pr = {p.get("designation"): (p["price"], p.get("points")) for p in (r.get("prices") or [])}
        if r["type"] == "moneyline" and "home" in pr and "away" in pr:
            h, a = imp(pr["home"][0]), imp(pr["away"][0]); g["ml"] = (pr["home"][0], pr["away"][0]); g["fair_home"] = round(h / (h + a), 4)
        elif r["type"] == "spread" and "home" in pr and not r.get("isAlternate"):
            g["spread_home"] = pr["home"][1]; g["spread_px"] = (pr["home"][0], pr.get("away", (None,))[0])
        elif r["type"] == "total" and "over" in pr and not r.get("isAlternate"):
            g["total"] = pr["over"][1]; g["total_px"] = (pr["over"][0], pr.get("under", (None,))[0])
    return games


def snap():
    now = datetime.datetime.now(CT).isoformat(timespec="minutes"); n = 0
    with open(OUT, "a", encoding="utf-8") as f:
        for lid, name in LEAGUES.items():
            try:
                for gid, g in pull(lid).items():
                    f.write(json.dumps(dict(ts=now, league=name, lid=lid, gid=gid, **g), ensure_ascii=False) + "\n"); n += 1
            except Exception as e:
                print(name, "failed:", e)
            time.sleep(0.5)
    print("archived %d games across %d leagues -> %s" % (n, len(LEAGUES), OUT))


def board():
    print("OVERSEAS BASKETBALL -- Pinnacle fair price = the break-even for Courtside (paper until the model is built)")
    for lid, name in LEAGUES.items():
        try:
            G = pull(lid)
        except Exception as e:
            print(name, "failed:", e); continue
        rows = sorted([g for g in G.values() if g.get("fair_home")], key=lambda g: g["start"] or "")
        if not rows:
            continue
        print("\n" + name)
        for g in rows:
            st = datetime.datetime.fromisoformat(g["start"].replace("Z", "+00:00")).astimezone(CT).strftime("%a %m/%d %I:%M%p")
            fh = g["fair_home"]; fa = 1 - fh
            am = lambda p: ("-%d" % round(100 * p / (1 - p))) if p > .5 else ("+%d" % round(100 * (1 - p) / p))
            print("  %-24s @ %-24s %s   fair %s %s / %s %s   spread %s  total %s" % (g["away"][:24], g["home"][:24], st, g["away"].split()[-1], am(fa),
                  g["home"].split()[-1], am(fh), g.get("spread_home"), g.get("total")))
        time.sleep(0.5)


if __name__ == "__main__":
    {"snap": snap, "board": board}[sys.argv[1] if len(sys.argv) > 1 else "board"]()
