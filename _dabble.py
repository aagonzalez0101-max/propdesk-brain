"""DABBLE scanner (2026-10-06, user: "how's Dabble looking, remember the crazy lines we had" -- 10/2 James Cook U10.5 on Dabble
while the books had 7.5).

    python _dabble.py [NFL NBA NHL MLB WNBA]    # every Dabble player prop in the next 72h vs the sharp books

Free public API (no key): api.dabble.com/competitions -> /competitions/<id>/sport-fixtures -> /sportfixtures/details/<fixture>
 -> playerProps (player, stat, value, over/under, selectionId) + prices (decimal, per selection). Dabble PRICES every leg.
Sharp side: Pinnacle props + FanDuel ladders (NFL), moved to Dabble's number with _mismatch.p_over_at (Poisson for low counts,
push-aware on whole numbers). Flag = sharp probability beats Dabble's implied (1/price) by 4+ pts, or Dabble's LINE sits
1.5+ off the sharp median. Output: console + site/dabble.json.
"""
import sys, re, json, time, datetime
import requests

H = {"User-Agent": "Mozilla/5.0"}
API = "https://api.dabble.com"
CT = datetime.timezone(datetime.timedelta(hours=-5))
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
COMP = {"NFL": "NFL", "NBA": "NBA", "NHL": "US NHL", "MLB": "US Major League Baseball", "WNBA": "WNBA"}
# dabble stat key -> our sharp stat name
STAT = {"passing-yards": "passing yards", "rushing-yards": "rushing yards", "receiving-yards": "receiving yards", "receptions": "receptions",
        "rushing-attempts": "rush attempts", "passing-attempts": "pass attempts", "passing-completions": "pass completions",
        "passing-touchdowns": "touchdown passes", "points": "points", "rebounds": "rebounds", "assists": "assists",
        "three-pointers-made": "threes made", "shots-on-goal": "shots on goal", "goalie-saves": "saves", "saves": "saves",
        "strikeouts": "strikeouts", "pitcher-strikeouts": "strikeouts", "hits-allowed": "hits allowed", "pitching-outs": "pitching outs"}


def fixtures(name, hours=72):
    comps = requests.get(API + "/competitions", headers=H, timeout=30).json()["data"]
    cid = next((c["id"] for c in comps if c.get("name") == name), None)
    if not cid:
        return []
    now = datetime.datetime.now(datetime.timezone.utc)
    fx = requests.get(API + "/competitions/%s/sport-fixtures" % cid, headers=H, timeout=30).json().get("data", [])
    return [f for f in fx if f.get("isDisplayed") and now < datetime.datetime.fromisoformat(f["advertisedStart"].replace("Z", "+00:00")) < now + datetime.timedelta(hours=hours)]


def props(fid):
    d = requests.get(API + "/sportfixtures/details/%s" % fid, headers=H, timeout=30).json()["data"]
    price = {p["selectionId"]: p["price"] for p in d.get("prices", [])}
    out = []
    for p in d.get("playerProps", []):
        if len(p.get("stats") or []) != 1:
            continue                                         # combos (pts+reb etc.) skipped for the sharp match
        out.append(dict(player=p["playerName"], team=p.get("teamAbbreviation"), stat=p["stats"][0], line=float(p["value"]), side=p.get("lineType"),
                        price=price.get(p["selectionId"]), game=d["name"], start=d["advertisedStart"]))
    return out


def main(sports):
    import _props as P, _mismatch as M
    rows = []
    for sp in sports:
        try:
            pin = P.pinnacle_props(M.PIN_LEAGUE[sp])
        except Exception as e:
            print(sp, "pinnacle:", e); pin = {}
        by = {}
        for (pl, st, ln), pr in pin.items():
            by.setdefault((pl, st), []).append((ln, pr))
        if sp == "NFL":
            try:
                import _fanduel
                for (pl, st, ln), pr in _fanduel.props("nfl").items():
                    r = by.setdefault((pl, st), [])
                    if not any(l == ln for l, _ in r):
                        r.append((ln, pr))
            except Exception as e:
                print("fanduel:", e)
        fx = fixtures(COMP[sp])
        print("%s: %d Dabble fixtures, %d sharp players" % (sp, len(fx), len({k[0] for k in by})))
        for f in fx:
            for p in props(f["id"]):
                st = STAT.get(p["stat"])
                R = by.get((norm(p["player"]), st)) if st else None
                if not R or not p["price"]:
                    continue
                po = M.p_over_at(R, p["line"], st)
                if po is None:
                    continue
                ps = po if p["side"] == "over" else 1 - po
                imp = 1 / p["price"]
                l0, p0 = min(R, key=lambda r: abs(r[1] - 0.5))
                gap = p["line"] - l0
                rows.append(dict(p, sport=sp, sharp=round(ps, 3), implied=round(imp, 3), edge=round(ps - imp, 3), sharp_line=l0, line_gap=round(gap, 1)))
            time.sleep(0.3)
    rows.sort(key=lambda r: -r["edge"])
    json.dump(rows, open("site/dabble.json", "w", encoding="utf-8"), ensure_ascii=False)
    print("\nDABBLE vs SHARP -- best edges (sharp prob of Dabble's side minus Dabble's implied)")
    for r in rows[:30]:
        t = datetime.datetime.fromisoformat(r["start"].replace("Z", "+00:00")).astimezone(CT).strftime("%a %I:%M%p")
        flag = "<<<" if r["edge"] >= 0.04 or abs(r["line_gap"]) >= 1.5 else ""
        print("  %-4s %-22s %-4s %-18s %-5s %-6s @%-5.2f implied %2.0f%%  sharp %2.0f%%  edge %+3.0f  (sharp line %s, gap %+.1f)  %s %s" % (
            r["sport"], r["player"][:22], r["team"] or "", r["stat"][:18], r["side"], r["line"], r["price"], 100 * r["implied"], 100 * r["sharp"],
            100 * r["edge"], r["sharp_line"], r["line_gap"], t, flag))


if __name__ == "__main__":
    main([s.upper() for s in sys.argv[1:]] or ["NFL", "NHL", "MLB", "NBA"])
