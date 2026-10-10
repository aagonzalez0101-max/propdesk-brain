"""Does the HANDEDNESS SPLIT IMPROVING predict a prop hitting?

The capper's rule (2026-09-28 video): take the player's overall hit rate, then filter it to the
hand the pitcher throws today. If the number goes UP, that is a green light; if it goes DOWN he
downgrades the play. We already print the split -- we have never gated on it.

Walk-forward, no leakage: at each game, the split is computed ONLY from that hitter's earlier
games. A player's full-season vs-RHP line includes today, which is exactly the leak in
[[feedback-asof-leak]].
"""
import json, collections, math, sys

MIN_PRIOR = 30      # prior starts before a game is scoreable
MIN_HAND  = 8       # prior starts against THIS hand


def load():
    hit = {json.loads(l)["name"]: json.loads(l)["games"] for l in open("_hitters_v2.jsonl", encoding="utf-8")}
    hd = json.load(open("_hands_v2.json", encoding="utf-8"))
    opp = hd["opp"]
    hand = hd["hand"]
    return hit, opp, hand


def run(stat="hrr", line=0.5):
    hit, opp, hand = load()
    rows = []
    for nm, gs in hit.items():
        prior_all, prior_by = [], collections.defaultdict(list)
        for g in gs:
            pid = opp.get("%s|%s" % (g["date"], g["tid"]))
            h = hand.get(str(pid)) if pid else None
            v = g.get(stat)
            if v is None:
                continue
            ok = v > line
            if h and len(prior_all) >= MIN_PRIOR and len(prior_by[h]) >= MIN_HAND:
                r_all = sum(prior_all) / len(prior_all)
                r_hand = sum(prior_by[h]) / len(prior_by[h])
                rows.append(dict(name=nm, date=g["date"], hand=h, r_all=r_all, r_hand=r_hand,
                                 delta=r_hand - r_all, hit=ok))
            prior_all.append(ok)
            if h:
                prior_by[h].append(ok)
    return rows


def report(rows, tag):
    n = len(rows)
    base = sum(1 for r in rows if r["hit"]) / n
    up = [r for r in rows if r["delta"] > 0]
    dn = [r for r in rows if r["delta"] <= 0]
    pu = sum(1 for r in up if r["hit"]) / len(up)
    pd = sum(1 for r in dn if r["delta"] is not None and r["hit"]) / len(dn)
    pp = (sum(1 for r in up if r["hit"]) + sum(1 for r in dn if r["hit"])) / n
    z = (pu - pd) / math.sqrt(pp * (1 - pp) * (1 / len(up) + 1 / len(dn)))
    print("\n=== %s ===  %d scoreable player-games, base rate %.1f%%" % (tag, n, 100 * base))
    print("  split IMPROVES vs this hand : %5d games, hit %.1f%%" % (len(up), 100 * pu))
    print("  split gets WORSE            : %5d games, hit %.1f%%" % (len(dn), 100 * pd))
    print("  difference %+.1f points, z = %+.2f  ->  %s"
          % (100 * (pu - pd), z, "REAL SIGNAL" if abs(z) > 2 else "NOT distinguishable from noise"))
    print("\n  by SIZE of the split gap:")
    b = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        k = max(-3, min(3, int(round(r["delta"] * 20))))     # 5pp buckets
        b[k][0] += 1
        b[k][1] += 1 if r["hit"] else 0
    for k in sorted(b):
        cnt, w = b[k]
        if cnt >= 150:
            print("    gap %+3d to %+3d pp   %5d games   hit %.1f%%" % (k * 5 - 2, k * 5 + 2, cnt, 100 * w / cnt))


if __name__ == "__main__":
    for stat, line, tag in (("hrr", 0.5, "HRR over 0.5"), ("tb", 0.5, "Total Bases over 0.5"),
                            ("h", 0.5, "Hits over 0.5")):
        rr = run(stat, line)
        if rr:
            report(rr, tag)
