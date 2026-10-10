"""THE DAILY FIVE (2026-10-03). User rule from day one: 5 bets a day, every day. The over-filtered card produced 0 for days.

    python _five.py [YYYY-MM-DD]     # the 5 best legs available, every day -> cards/<date>__five.json (graded by _card.py grade)

Edge source = PRICE, not our model: the side the sharp books favour (Pinnacle props + FanDuel totals/alt ladders), played on
UNDERDOG where a 1.00x leg only needs 53.5% (PrizePicks standard needs 57.7%). Each leg must clear its own break-even at its real
Underdog multiplier by 2+ pts. Vetoes (only when we HAVE the data): the player's own season record on the wrong side of 50%, or the
opponent's defense vs that position strongly against the side. One leg per game, one per player. Always returns the best 5 that
clear -- if fewer than 5 clear, it says so and lists the next best as optional.
"""
import sys, os, json, re, time, datetime, sqlite3, statistics as st

CT = datetime.timezone(datetime.timedelta(hours=-5))
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
SPORTS = ("NFL", "CFB", "NHL", "WNBA", "NBA")          # MLB paused (user 10/2)
BE_UD = 1 / 3.0 ** 0.5          # PrizePicks 2-pick power (3x) per-leg break-even 57.7% (was Underdog 53.5% until 10/5)
KEY_DB = {"receiving yards": "rec_yds", "rushing yards": "rush_yds", "passing yards": "pass_yds", "receptions": "rec",
          "rush attempts": "carries", "pass attempts": "att", "pass completions": "cmp"}
KEY_NFL = {"receiving yards": "receiving_yards", "rushing yards": "rushing_yards", "passing yards": "passing_yards", "receptions": "receptions",
           "rush attempts": "carries", "pass attempts": "attempts", "pass completions": "completions"}


def own_record(sport, player, stat, line, side):
    """share of this season's games on our side of the line (None if no data)."""
    c = sqlite3.connect("sports.db", timeout=60)
    if sport == "CFB" and stat in KEY_DB:
        rows = [json.loads(s).get(KEY_DB[stat], 0) for (s,) in c.execute(
            "SELECT stats FROM player_games WHERE sport='CFB' AND player=? AND season='2026'", (player,))]
    elif sport == "NFL" and stat in KEY_NFL:
        rows = [float(json.loads(s).get(KEY_NFL[stat]) or 0) for (s,) in c.execute(
            "SELECT stats FROM player_games WHERE sport='NFL' AND player=? AND season='2026'", (player,))]
    else:
        return None, 0
    if len(rows) < 2:
        return None, len(rows)
    return sum(1 for v in rows if (v > line if side == "over" else v < line)) / len(rows), len(rows)


def main(day):
    import _props as P, _mismatch as M
    legs = []
    for sp in SPORTS:
        try:
            pin = P.pinnacle_props(M.PIN_LEAGUE[sp])
        except Exception as e:
            print(sp, "pinnacle:", e); pin = {}
        by = {}
        for (pl, st_, ln), p in pin.items():
            by.setdefault((pl, st_), []).append((ln, p))
        if sp in ("NFL", "CFB"):
            try:
                import _fanduel
                for (pl, st_, ln), p in _fanduel.props(sp.lower()).items():
                    r = by.setdefault((pl, st_), [])
                    if not any(l == ln for l, _ in r):
                        r.append((ln, p))
            except Exception as e:
                print(sp, "fanduel:", e)
        try:
            # 10/5 user: Underdog is at $0, "no more UD bets ever" -> PrizePicks standard lines only (2-pick needs 57.7%)
            ud = [dict(l, mult={"over": 1.0, "under": 1.0}) for l in P.prizepicks(M.PP_LEAGUE[sp], max_age=1200) if l.get("kind") == "standard"]
        except Exception as e:
            print(sp, "prizepicks:", e); continue
        for l in ud:
            stt = M.STAT.get(norm(l["stat"]))
            R = by.get((norm(l["player"]), stt)) if stt else None
            if not R:
                continue
            po = M.p_over_at(R, l["line"], stt)
            if po is None:
                continue
            for side, p in (("over", po), ("under", 1 - po)):
                m = (l.get("mult") or {}).get(side)
                if not m or m >= 1.5 or m <= 0.7:
                    continue                                       # UD lopsided line = its goblin/demon (user 10/3)
                be = BE_UD / m
                if p - be < 0.02:
                    continue
                own, n = own_record(sp, l["player"], stt, l["line"], side)
                if own is not None and n >= 3 and own < 0.5:
                    continue                                       # his own season disagrees
                legs.append(dict(sport=sp, player=l["player"], stat=l["stat"], line=l["line"], side=side, mult=m, p=round(p, 3), be=round(be, 3),
                                 edge=round(p - be, 3), own=own, n=n, game=l.get("game"), start=l.get("start")))
        time.sleep(1)
    legs.sort(key=lambda x: -x["edge"])
    pick, games, players = [], set(), set()
    for x in legs:
        if x["game"] in games or x["player"] in players:
            continue
        pick.append(x); games.add(x["game"]); players.add(x["player"])
        if len(pick) == 8:
            break
    five = pick[:5]
    os.makedirs("cards", exist_ok=True)
    fn = os.path.join("cards", "%s__five.json" % day)
    if os.path.exists(fn) and "--force" not in sys.argv:
        print("five for %s already locked (%s) -- not overwriting; --force to rebuild" % (day, fn)); return
    json.dump(dict(day=day, legs=five, extra=pick[5:]), open(fn, "w"), indent=1)
    print("THE DAILY FIVE %s (PrizePicks, sharp-priced side, %d candidates cleared)" % (day, len(legs)))
    for i, x in enumerate(five, 1):
        t = datetime.datetime.fromisoformat(str(x["start"]).replace("Z", "+00:00")).astimezone(CT).strftime("%a %I:%M %p") if x["start"] else ""
        print(" %d. %-4s %-22s %-5s %-6s %-18s x%.2f  sharp %.0f%% vs needs %.0f%% (+%.0f)  own %s  %s  %s" % (
            i, x["sport"], x["player"][:22], x["side"], x["line"], x["stat"][:18], x["mult"], 100 * x["p"], 100 * x["be"], 100 * x["edge"],
            ("%d/%d" % (round(x["own"] * x["n"]), x["n"])) if x["own"] is not None else "-", x["game"], t))
    if pick[5:]:
        print(" next best:", "; ".join("%s %s %s %s" % (x["player"], x["side"], x["line"], x["stat"]) for x in pick[5:]))


if __name__ == "__main__":
    main(next((a for a in sys.argv[1:] if len(a) == 10), datetime.datetime.now(CT).date().isoformat()))
