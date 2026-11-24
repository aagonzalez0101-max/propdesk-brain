"""TENNIS GOBLIN PARTNERS (11/24, user: "we can if we mix it with maybe some promos or some other standards ... we should implement").
The goblins _tennis_pp.py prices off Pinnacle with model edge >= 6 pts hit 84-19 (81.6%) through 11/23 (before 11/14 61-17, after 23-2).
Goblin PAIRS pay only 1.2-1.3x in his app (feedback_std_plus_goblin) -> dead. The play is ONE tennis goblin as the partner of a strong
STANDARD or promo leg (soccer 2-pick leg, taco, plan leg): standard + goblin pays ~2-2.2x; at 81.6% the standard needs ~61% (2x) / ~56% (2.2x).
Stake = the regular card tier (feedback_goblin_stakes: never bigger because the hit rate is higher).
    python _tennis_card.py            # refresh prices, post the top 3 goblin partners starting in the next 18h (DRYRUN=1: print only)
    python _tennis_card.py grade      # settle tennis_card.jsonl from graded tennis_pp_paper rows
"""
import os, sys, json, datetime, subprocess

CT = __import__("zoneinfo").ZoneInfo("America/Chicago")
OUT = "tennis_card.jsonl"
EDGE = 0.06
HOURS = 18


def build():
    now = datetime.datetime.now(CT)
    subprocess.run([sys.executable, "_tennis_pp.py"], capture_output=True, timeout=1500, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    latest = {}
    for l in open("tennis_pp_paper.jsonl", encoding="utf-8"):
        if l.strip():
            r = json.loads(l); latest[r["pid"]] = r                    # newest pricing of each PP line
    posted = set()
    if os.path.exists(OUT):
        for l in open(OUT, encoding="utf-8"):
            if l.strip():
                posted |= {x["pid"] for x in json.loads(l)["legs"]}
    C = []
    for r in latest.values():
        t = datetime.datetime.fromisoformat(r["start"]).astimezone(CT)
        if r.get("kind") == "goblin" and r.get("edge", 0) >= EDGE and now + datetime.timedelta(minutes=10) < t < now + datetime.timedelta(hours=HOURS) \
                and r["pid"] not in posted and r.get("result") is None:
            C.append(r)
    top, matches = [], set()
    for r in sorted(C, key=lambda r: -r["edge"]):
        m = tuple(sorted([r["player"], r.get("opp") or ""]))
        if m in matches:
            continue
        matches.add(m); top.append(r)
        if len(top) == 3:
            break
    if not top:
        print("tennis card: no goblin with edge >= %.0f pts in the next %dh" % (100 * EDGE, HOURS)); return
    tm = lambda r: datetime.datetime.fromisoformat(r["start"]).astimezone(CT).strftime("%a %I:%M %p")
    body = "\n".join("%s %s %g %s (goblin) -- model %.0f%% vs %.0f%% b/e, edge +%.0f | vs %s, %s CT" % (
        r["player"], r["side"].upper()[0], r["line"], r["stat"], 100 * r["p"], 100 * r["be"], 100 * r["edge"], r.get("opp"), tm(r)) for r in top)
    head = "**TENNIS GOBLIN PARTNERS** -- pair ONE with a strong standard/promo leg (pays ~2x); never 2 goblins (1.2-1.3x)\n"
    note = "\n_tennis goblins edge 6+: 84-19 (81.6%) graded; standard partner needs ~61% at 2x_"
    print(head + body + note)
    if os.environ.get("DRYRUN"):
        print("(dry run: not posted or logged)"); return
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(day=now.strftime("%Y-%m-%d"), logged=now.isoformat(timespec="seconds"),
                                legs=[{k: r.get(k) for k in ("pid", "player", "opp", "stat", "line", "side", "p", "edge", "start")} for r in top])) + "\n")
    import _notify
    _notify.send("CARD", head + body + note)


def grade():
    res = {}
    for l in open("tennis_pp_paper.jsonl", encoding="utf-8"):
        if l.strip():
            r = json.loads(l)
            if r.get("result") in ("W", "L"):
                res[r["pid"]] = r["result"]
    if not os.path.exists(OUT):
        print("no tennis card yet"); return
    legs = [x for l in open(OUT, encoding="utf-8") if l.strip() for x in json.loads(l)["legs"]]
    g = [res[x["pid"]] for x in legs if x["pid"] in res]
    print("tennis goblin partners: %d-%d graded (%d pending)" % (g.count("W"), g.count("L"), len(legs) - len(g)))


if __name__ == "__main__":
    grade() if sys.argv[1:2] == ["grade"] else build()
