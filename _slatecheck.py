"""Run the _laddercheck flags across every game on a day's board in one pass.

Same checks as _laddercheck.py (opener, bullpen availability, offense vs
today's starter's hand, price shop, lineups), but prices are fetched once and
the output is one row per game next to the model's side, so the ladder band can
be re-read with the flags in view instead of one game at a time.

Usage:  python _slatecheck.py 2026-09-11
"""
from __future__ import annotations

import glob
import io
import json
import sys

sys.path.insert(0, ".")
import _laddercheck as LC        # noqa: E402  (rebinds stdout on import)

day = sys.argv[1] if len(sys.argv) > 1 else LC.dt.date.today().isoformat()
board = json.load(open(sorted(glob.glob("pp/boards/%s_*.json" % day))[-1], encoding="utf-8"))
model = {r["game"]: r for r in board["picks"] if r["market"] == "ML"}

# prices once, both books
px = {}
from betting import freeodds as F  # noqa: E402
for src, fn in (("kalshi", F.kalshi_mlb), ("pinnacle", F.pinnacle_mlb)):
    try:
        for e in fn():
            for o in e["bookmakers"][0]["markets"][0]["outcomes"]:
                px.setdefault((e["away_team"], e["home_team"], o["name"]), {})[src] = o["price"]
    except Exception:
        pass

sched = LC.get("%s/schedule?sportId=1&date=%s&hydrate=probablePitcher,lineups" % (LC.API, day))
games = [g for d in sched.get("dates", []) for g in d["games"]]
pen_cache = {}
out = []
for g in sorted(games, key=lambda x: x["gameDate"]):
    A, H = g["teams"]["away"], g["teams"]["home"]
    an, hn = A["team"]["name"], H["team"]["name"]
    key = "%s @ %s" % (an, hn)
    flags = []
    sps = {s: LC.starter(t.get("probablePitcher")) for s, t in (("away", A), ("home", H))}
    for s, t in (("away", A), ("home", H)):
        p = sps[s]
        if not p:
            flags.append("%s SP TBD" % t["team"]["abbreviation"] if "abbreviation" in t["team"] else "%s SP TBD" % t["team"]["name"])
        elif p["opener"]:
            flags.append("OPENER %s (%dGS)" % (p["name"].split()[-1], p["gs"]))
    for s, t, opp in (("away", A, "home"), ("home", H, "away")):
        o = sps[opp]
        if not o:
            continue
        season, vs = LC.offense(t["team"]["id"], o["hand"])
        if vs and season and float(vs) - float(season) <= -0.040:
            flags.append("%s %+d vs %sHP" % (t["team"]["name"].split()[-1],
                                             round(1000 * (float(vs) - float(season))), o["hand"]))
    for t in (A, H):
        tid = t["team"]["id"]
        if tid not in pen_cache:
            pen_cache[tid] = LC.bullpen(tid, day)
        for n, k, nm in pen_cache[tid]["tired"]:
            if n >= 35 or (k >= 2 and n >= 25) or k >= 3:
                flags.append("%s pen: %s out" % (t["team"]["name"].split()[-1], nm.split()[-1]))
    lu = g.get("lineups") or {}
    posted = bool(lu.get("awayPlayers") and lu.get("homePlayers"))
    m = model.get(key)
    side = m["selection"] if m else None
    edge = (m["raw"] - m["market_prob"]) if m else None
    p = px.get((an, hn, side), {}) if side else {}
    out.append(dict(game=key, time=g["gameDate"], side=side, edge=edge, odds=m["odds"] if m else None,
                    kalshi=p.get("kalshi"), pin=p.get("pinnacle"), posted=posted, flags=flags,
                    pen={t["team"]["name"]: pen_cache[t["team"]["id"]]["era"] for t in (A, H)}))

json.dump(out, open("_slatecheck_%s.json" % day, "w"), indent=1)
CT = LC.dt.timezone(LC.dt.timedelta(hours=-5))
print("SLATE CHECK  %s  (%d games)\n" % (day, len(out)))
for r in sorted(out, key=lambda x: -(x["edge"] or -1)):
    t = LC.dt.datetime.fromisoformat(r["time"].replace("Z", "+00:00")).astimezone(CT)
    e = "%+5.1fpp" % (100 * r["edge"]) if r["edge"] is not None else "  --  "
    print("%s  %-44s side %-22s %s  K %-5s P %-5s  lineups %s"
          % (t.strftime("%I:%M%p"), r["game"][:44], (r["side"] or "-")[:22], e,
             r["kalshi"] if r["kalshi"] is not None else "-", r["pin"] if r["pin"] is not None else "-",
             "Y" if r["posted"] else "-"))
    for f in r["flags"]:
        print("            * %s" % f)
