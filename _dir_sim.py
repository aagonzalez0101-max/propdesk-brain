"""$10 bankroll simulation, ALL graded sports (2026-10-07, user: "each sport ... the top of the top ... run the test again since
beginning"). Picks per day, never using that day's results:
  NHL / WNBA  direction filter (model trained on every OTHER day; 3+ measured reasons agree, 0 against; max 6/sport-day)
  CS2         under when the line is in the top 20% (kills >= 30.5 / HS >= 16.5) AND our kill model sits 5%+ below it (62-63%)
  GOBLINS     (mode "mix") NHL goblins where the player cleared it in 9+ of his last 10 -> paired with a standard leg at ~2.1x
Slips = PrizePicks 2-pick power (3x), never two legs from one game, highest confidence first. Stake = PCT of the morning roll, min $1.
    python _dir_sim.py [start] [pct] [std|mix]
"""
import sys, json, datetime, collections
import _dir_search as D

START = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
PCT = float(sys.argv[2]) if len(sys.argv) > 2 else 0.05
MODE = sys.argv[3] if len(sys.argv) > 3 else "std"
CT = datetime.timezone(datetime.timedelta(hours=-5))
FROM = "2026-09-29"

legs = []
for r in D.top_tier(D.lodo_out(D.graded())):
    legs.append(dict(day=r["date"], sport=r["sport"], game=frozenset((r["team"], r["opp"])), who="%s %s %s%s" % (r["player"].split()[-1], r["stat"][:10], r["side"][0].upper(), r["line"]),
                     conf=r["conf"], win=r["over"] == (r["side"] == "over"), kind="std"))
cs = {}
for l in open("cs2_priced_all.jsonl", encoding="utf-8"):
    r = json.loads(l)
    if r.get("result") in ("W", "L") and r.get("actual") is not None:
        cs[(r["match_id"], r["player"], r["stat"], r["maps"], r["line"])] = r
for r in cs.values():
    cut = 30.5 if r["kind"] == "k" else 16.5
    if r["line"] >= cut and r["model_mu"] < 0.95 * r["line"] and r["actual"] != r["line"]:
        day = datetime.datetime.fromisoformat(r["start"].replace("Z", "+00:00")).astimezone(CT).date().isoformat()
        legs.append(dict(day=day, sport="CS2", game=frozenset((r["team"], r["opp"])), who="%s %s U%s" % (r["player"], "K" if r["kind"] == "k" else "HS", r["line"]),
                         conf=0.62 + (0.05 if (r.get("map_winp") or 1) < .45 else 0), win=r["actual"] < r["line"], kind="std"))
if MODE == "mix":
    import _dir_search as S
    G = [r for r in json.load(open("_dir_goblins.json")) if r["sport"] == "NHL"]
    for r in G:
        h = r["hist"][-10:]
        if sum(x > r["line"] for x in h) / len(h) >= 0.9:
            legs.append(dict(day=r["date"], sport="NHL-gob", game=frozenset((r["team"], r["opp"])), who="%s %s gob O%s" % (r["player"].split()[-1], r["stat"][:6], r["line"]),
                             conf=0.75, win=bool(r["over"]), kind="gob"))
legs = [l for l in legs if l["day"] >= FROM]
# one leg per player per day (CS2 can list a player on kills and HS)
seen, L2 = set(), []
for l in sorted(legs, key=lambda l: -l["conf"]):
    k = (l["day"], l["who"].split()[0])
    if k not in seen:
        seen.add(k); L2.append(l)
legs = L2

roll = START; tot = collections.Counter()
print("start $%.2f | stake %.0f%% of morning roll per slip (min $1) | mode %s\n" % (START, 100 * PCT, MODE))
for day in sorted({l["day"] for l in legs}):
    std = sorted([l for l in legs if l["day"] == day and l["kind"] == "std"], key=lambda l: -l["conf"])
    gob = sorted([l for l in legs if l["day"] == day and l["kind"] == "gob"], key=lambda l: -l["conf"])
    slips, used = [], set()
    for i, a in enumerate(std):
        if id(a) in used:
            continue
        b = next((x for x in std[i + 1:] if id(x) not in used and x["game"] != a["game"]), None)
        if b:
            slips.append((a, b, 3.0)); used |= {id(a), id(b)}
    for a in std:                                                    # leftover standard + goblin at ~2.1x
        if id(a) in used:
            continue
        g = next((x for x in gob if id(x) not in used and x["game"] != a["game"]), None)
        if g:
            slips.append((a, g, 2.1)); used |= {id(a), id(g)}
    morning = roll; stake = max(1.0, round(PCT * morning, 2)); net_day = 0; w = 0; txt = []
    for a, b, mult in slips:
        if roll < stake:
            break
        win = a["win"] and b["win"]
        net = stake * (mult - 1) if win else -stake
        roll += net; net_day += net; w += win; tot[(a["sport"], a["win"])] += 1; tot[(b["sport"], b["win"])] += 1
        txt.append("%s%s+%s%s" % (a["who"], "✓" if a["win"] else "✗", b["who"], "✓" if b["win"] else "✗"))
    sports = "/".join(sorted({x["sport"] for s in slips for x in s[:2]}))
    print("%s  %-22s %d/%d slips  stake $%-5.2f  %+6.2f -> $%.2f" % (day[5:], sports, w, len(txt), stake, net_day, roll))
print("\nEND $%.2f (%+.0f%%)" % (roll, 100 * (roll / START - 1)))
for sp in sorted({k[0] for k in tot}):
    print("   legs %-8s %d-%d" % (sp, tot[(sp, True)], tot[(sp, False)]))
