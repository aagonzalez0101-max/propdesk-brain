"""Dota 2 PrizePicks kills lines -> paper projections (2026-10-07, user: "do dota2 too").
    python _dota_proj.py            # live PP Dota board (league 174) vs each player's last 30 pro maps (dota_matches.jsonl, OpenDota)
MAPS 1-2 kills = two maps summed; P(over) by resampling pairs of his own recent maps. Combos = the players' sums.
No graded Dota line history exists yet (archive started 10/7) -> PAPER until ~150 graded lines; results go to dota_paper.jsonl."""
import json, random, re, datetime, collections, os
import _props as P

CT = datetime.timezone(datetime.timedelta(hours=-5))
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
games = collections.defaultdict(list)
for l in open("dota_matches.jsonl", encoding="utf-8"):
    r = json.loads(l)
    games[norm(r.get("name"))].append((r["date"], r["kills"], r.get("minutes")))
for k in games:
    games[k].sort()


def sims(names, n=4000, last=30):
    pools = []
    for nm in names:
        g = [k for d, k, m in games.get(norm(nm), [])][-last:]
        if len(g) < 8:
            return None, None
        pools.append(g)
    random.seed(1)
    out = [sum(random.choice(p) + random.choice(p) for p in pools) for _ in range(n)]
    return out, min(len(p) for p in pools)


rows = []
for l in P.prizepicks(174, max_age=900):
    if l.get("kind") != "standard" or "Kills" not in l["stat"] or "MAPS 1-2" not in l["stat"]:
        continue
    names = [x.strip() for x in l["player"].split("+")]
    s, n = sims(names)
    if s is None:
        rows.append((l, None, None, None)); continue
    po = sum(x > l["line"] for x in s) / len(s); mu = sum(s) / len(s)
    rows.append((l, po, mu, n))
print("DOTA 2 (paper) -- PrizePicks MAPS 1-2 kills vs last 30 pro maps")
pap = []
for l, po, mu, n in sorted(rows, key=lambda x: -abs((x[1] or .5) - .5)):
    st = datetime.datetime.fromisoformat(l["start"]).astimezone(CT).strftime("%a %I:%M%p")
    if po is None:
        print("  %-34s %-5s line %5.1f   no history" % (l["player"][:34], l["team"], l["line"])); continue
    side = "OVER" if po >= .5 else "UNDER"; p = max(po, 1 - po)
    tag = "LEAN" if p >= .62 else ""
    print("  %-34s %-5s vs %-12s line %5.1f  proj %5.1f  %-5s %3.0f%%  %s  %s" % (l["player"][:34], l["team"], (l.get("opp") or "")[:12], l["line"], mu, side, 100 * p, tag, st))
    if tag:
        pap.append(dict(date=datetime.datetime.fromisoformat(l["start"]).astimezone(CT).date().isoformat(), player=l["player"], team=l["team"], opp=l.get("opp"),
                        stat=l["stat"], line=l["line"], side=side.lower(), p=round(p, 3), proj=round(mu, 1), start=l["start"], result=None))
have = set()
if os.path.exists("dota_paper.jsonl"):
    have = {(json.loads(x)["player"], json.loads(x)["line"], json.loads(x)["date"]) for x in open("dota_paper.jsonl", encoding="utf-8")}
with open("dota_paper.jsonl", "a", encoding="utf-8") as f:
    for x in pap:
        if (x["player"], x["line"], x["date"]) not in have:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
