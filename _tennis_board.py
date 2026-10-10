"""TENNIS BOOST BOARD (2026-10-02) -- the matches whose favourite is priced at or near fair, i.e. the legs for Courtside PROFIT BOOSTS.
Measured on 96,852 Pinnacle closing prices (memory project_golf_tennis_models): favourites at 1.00-1.15 return -0.5% (~fair),
men's best-of-5 favourites 0% to +1.2%; everything else -1.5% to -3.4%, and underdogs worse. A boost on fair legs = a positive bet.

    python _tennis_board.py        # next 36h: every Pinnacle tennis match, fair %, and the BOOST-LEG tier

Never a straight bet by itself: tennis moneylines have no standalone edge. Use 2-4 of these in a boosted parlay.
"""
import json, os, datetime, requests

CT = datetime.timezone(datetime.timedelta(hours=-5))
imp = lambda p: 100 / (p + 100) if p > 0 else -p / (-p + 100)
amer = lambda q: ("-%d" % round(100 * q / (1 - q))) if q >= 0.5 else "+%d" % round(100 * (1 - q) / q)


def main():
    import _kbo as K
    lg = requests.get(K.PIN + "/0.1/sports/33/leagues?all=false", headers=K.PH, timeout=25).json()
    now = datetime.datetime.now(datetime.timezone.utc)
    rows = []
    for L in lg:
        name = L.get("name", "")
        if any(w in name.lower() for w in ("doubles", "itf", "utr", "challenger women")):
            continue
        try:
            mu = requests.get(K.PIN + "/0.1/leagues/%d/matchups" % L["id"], headers=K.PH, timeout=25).json()
            mk = requests.get(K.PIN + "/0.1/leagues/%d/markets/straight" % L["id"], headers=K.PH, timeout=25).json()
        except Exception:
            continue
        mm = {m["id"]: m for m in mu if m.get("type") == "matchup" and not m.get("parentId")}
        for x in mk:
            m = mm.get(x["matchupId"])
            if not m or x["type"] != "moneyline" or x.get("period") != 0:
                continue
            st = datetime.datetime.fromisoformat(m["startTime"].replace("Z", "+00:00"))
            if not (now <= st <= now + datetime.timedelta(hours=36)):
                continue
            n = {p["alignment"]: p["name"] for p in m["participants"]}
            d = {p["designation"]: p["price"] for p in x["prices"]}
            if "home" not in d or "away" not in d:
                continue
            a, h = imp(d["away"]), imp(d["home"])
            pa = a / (a + h)
            fav, fp = (n["away"], pa) if pa >= 0.5 else (n["home"], 1 - pa)
            dog = n["home"] if fav == n["away"] else n["away"]
            bo5 = "grand slam" in name.lower() and "women" not in name.lower() and "wta" not in name.lower()
            tier = "BOOST LEG" if fp >= 0.87 or (bo5 and fp >= 0.70) else ("ok" if fp >= 0.77 else "")
            rows.append(dict(league=name, start=m["startTime"], fav=fav, dog=dog, p=round(fp, 3), fair=amer(fp), tier=tier, bo5=bo5))
    rows.sort(key=lambda r: (r["tier"] != "BOOST LEG", -r["p"]))
    json.dump(rows, open(os.path.join("site", "tennis.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print("%d tennis matches in the next 36h, %d boost legs" % (len(rows), sum(r["tier"] == "BOOST LEG" for r in rows)))
    for r in rows[:25]:
        st = datetime.datetime.fromisoformat(r["start"].replace("Z", "+00:00")).astimezone(CT).strftime("%a %I:%M %p")
        print("%-9s %-28s %-24s over %-24s %4.1f%%  fair %-5s %s" % (r["tier"], r["league"][:28], r["fav"][:24], r["dog"][:24], 100 * r["p"], r["fair"], st))


if __name__ == "__main__":
    main()
