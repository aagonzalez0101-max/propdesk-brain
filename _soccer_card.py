"""SOCCER CARD (11/24, user: "add the soccer 2-pick to tomorrow's card, not part of the nba shi kinda like our 1q stuff").
One 2-pick a day: the top 2 UNDERS on Shots / Attempted Dribbles from soccer_paper.jsonl (written by _soccer.py, which the cloud runs at
7:45 AM + 9 PM for today and tomorrow), ranked by model p, distinct matches, PP standard line still live at our number.
Backtest (cloud soccer_paper, 10/1-11/23, one slip/day): shots 2-pick 16/36 cashed (+33% ROI); shots+dribbles 16/37 (+30%).
Legs: shots unders 200-119 (62.7%, Oct 61% / Nov 67%), dribble unders 57-23. Goalie saves (47% Nov) and crosses (1-9 Nov) never.
Stake = the card slip size (feedback_card_cap: $15, $20 once the roll passes $400). Separate from the NBA model plan.
    python _soccer_card.py            # build + post today's soccer 2-pick (DRYRUN=1: print only)
    python _soccer_card.py grade      # settle soccer_card.jsonl from graded soccer_paper rows
"""
import os, sys, json, datetime

CT = __import__("zoneinfo").ZoneInfo("America/Chicago")
STATS = ("Shots", "Attempted Dribbles")
OUT = "soccer_card.jsonl"
PP_SOCCER = 82


def rows_for(day):
    latest = {}
    for l in open("soccer_paper.jsonl", encoding="utf-8"):
        if not l.strip():
            continue
        r = json.loads(l)
        if r.get("date") == day and r.get("side") == "under" and r.get("stat") in STATS and r.get("p") is not None:
            latest[(r["player"], r["stat"])] = r                    # later screen runs overwrite earlier ones
    return list(latest.values())


def live_lines():
    import _ppcache as C, _stack as S
    d = C.projections(PP_SOCCER, 600)
    P = {i["id"]: i["attributes"] for i in d.get("included", []) if i["type"] == "new_player"}
    out = {}
    for x in d["data"]:
        a = x["attributes"]
        if a.get("odds_type") == "standard":
            out.setdefault((S.nn(P.get(x["relationships"]["new_player"]["data"]["id"], {}).get("name", "")), a["stat_type"]), []).append(float(a["line_score"]))
    return out, S.nn


def build():
    now = datetime.datetime.now(CT); day = now.strftime("%Y-%m-%d")
    R = [r for r in rows_for(day) if r.get("start") and datetime.datetime.fromisoformat(r["start"]).astimezone(CT) > now + datetime.timedelta(minutes=10)]
    try:
        live, nn = live_lines()
    except Exception as e:
        print("PP soccer board unavailable (%s) -- not posting" % e); return
    legs, matches, why = [], set(), []
    for r in sorted(R, key=lambda r: -r["p"]):
        m = r.get("fotmob_id") or (r.get("start"), tuple(sorted([r.get("team") or "", r.get("opp") or ""])))
        cur = live.get((nn(r["player"]), r["stat"]))
        if not cur or r["line"] not in cur:
            why.append("%s %s (PP line now %s)" % (r["player"], r["stat"], cur or "pulled")); continue
        if m in matches:
            continue
        matches.add(m); legs.append(r)
        if len(legs) == 2:
            break
    if len(legs) < 2:
        print("soccer card %s: %d qualifying legs -- no slip today" % (day, len(legs))); return
    road = json.load(open("road.json")) if os.path.exists("road.json") else {}
    roll = float(road.get("roll_now") or 0); stake = 20 if roll > 400 else 15
    t = lambda r: datetime.datetime.fromisoformat(r["start"]).astimezone(CT).strftime("%I:%M %p").lstrip("0")
    body = "\n".join("%s U%g %s -- model %.0f%% (%s v %s, %s CT)" % (r["player"], r["line"], r["stat"], 100 * r["p"], r.get("team"), r.get("opp"), t(r)) for r in legs)
    head = "**SOCCER 2-PICK %s ($%d)** -- separate from the NBA plan\n" % (day, stake)
    note = "\n_shots/dribble unders: one slip/day backtest 16/36 cashed, +33%% ROI (n small); legs 62.7%%_"
    if why:
        note += "\n_skipped (line moved/pulled): " + "; ".join(why[:4]) + "_"
    print(head + body + note)
    if os.environ.get("DRYRUN"):
        print("(dry run: not posted or logged)"); return
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(day=day, stake=stake, logged=now.isoformat(timespec="seconds"), result=None,
                                legs=[dict(player=r["player"], stat=r["stat"], line=r["line"], side="under", p=r["p"], start=r["start"]) for r in legs])) + "\n")
    import _notify
    _notify.send("CARD", head + body + note)


def grade():
    if not os.path.exists(OUT):
        print("no soccer card yet"); return
    res = {}
    for l in open("soccer_paper.jsonl", encoding="utf-8"):
        if l.strip():
            r = json.loads(l)
            if r.get("result") in ("W", "L") and r.get("side") == "under":
                res[(r["date"], r["player"], r["stat"], r["line"])] = r["result"]
    C = [json.loads(l) for l in open(OUT, encoding="utf-8") if l.strip()]
    for c in C:
        if c.get("result") is None:
            rs = [res.get((c["day"], x["player"], x["stat"], x["line"])) for x in c["legs"]]
            if all(rs):
                c["result"] = "W" if all(x == "W" for x in rs) else "L"
                c["net"] = c["stake"] * 2 if c["result"] == "W" else -c["stake"]
    open(OUT, "w", encoding="utf-8").write("".join(json.dumps(c) + "\n" for c in C))
    g = [c for c in C if c.get("result")]
    print("soccer card: %d-%d, net $%+.0f" % (sum(c["result"] == "W" for c in g), sum(c["result"] == "L" for c in g), sum(c["net"] for c in g)))


if __name__ == "__main__":
    grade() if sys.argv[1:2] == ["grade"] else build()
