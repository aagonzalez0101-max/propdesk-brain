"""User 10/9: "if the projection on the STANDARD line is good as f*** in our model, take the GOBLIN" -- backtest.
Join every graded standard line (_dir_rows.json) to the same player/stat/day goblin (_dir_goblins.json) and measure the goblin's
hit rate when our signals strongly like the OVER on the standard line. Goblin pair at 1.8x needs 74.5% per leg."""
import json, collections, sys
import _dir_search as D
G = json.load(open("_dir_goblins.json"))
gob = collections.defaultdict(list)
for g in G:
    gob[(g["sport"], g["player"], g["sk"], g["date"])].append(g)
R = D.graded()                                            # standard lines, features prepped
lo = {(r["sport"], r["player"], r["sk"], r["date"], r["line"]): r["p"] for r in D.lodo_out(R)}   # out-of-sample P(over)
rows = []
for r in R:
    gs = gob.get((r["sport"], r["player"], r["sk"], r["date"]))
    if not gs:
        continue
    p = lo.get((r["sport"], r["player"], r["sk"], r["date"], r["line"]))
    v = D.votes(r); ag = sum(1 for x in v if x == 1); an = sum(1 for x in v if x == -1)
    for g in gs:
        rows.append(dict(sport=r["sport"], p=p, ag=ag, an=an, proj=r.get("proj_line_f"), has=r.get("proj_has"), med=r["med_line"],
                         std_over=r["over"], gob_over=g["over"], gap=r["line"] - g["line"], gline=g["line"]))
def rep(lab, X):
    if X:
        print("  %-62s n=%4d  goblin hit %5.1f%%   (standard over %5.1f%%)" % (lab, len(X), 100 * sum(x["gob_over"] for x in X) / len(X),
              100 * sum(x["std_over"] for x in X) / len(X)))
print("GOBLIN when the model likes the standard OVER (needs 74.5% for a 1.8x pair)")
rep("all goblins with a matched standard line", rows)
for sp in ("NHL", "WNBA"):
    S = [x for x in rows if x["sport"] == sp]
    rep(sp + " all", S)
    rep(sp + " model P(over std) >= 0.55 (out-of-sample)", [x for x in S if x["p"] and x["p"] >= .55])
    rep(sp + " model P(over std) >= 0.60", [x for x in S if x["p"] and x["p"] >= .60])
    rep(sp + " model >= 0.55 AND 3+ over reasons, 0 against", [x for x in S if x["p"] and x["p"] >= .55 and x["ag"] >= 3 and x["an"] == 0])
    rep(sp + " median >= 1.2x standard line", [x for x in S if x["med"] >= 1.2])
    rep(sp + " median >= 1.2x AND model >= 0.55", [x for x in S if x["med"] >= 1.2 and x["p"] and x["p"] >= .55])
    rep(sp + " our role proj >= +15% over standard", [x for x in S if x["has"] and x["proj"] >= .15])
print("\nclustering check (unique player-days / days):")
import itertools
G2 = collections.defaultdict(list)
for r in R:
    gs = gob.get((r["sport"], r["player"], r["sk"], r["date"]))
    p = lo.get((r["sport"], r["player"], r["sk"], r["date"], r["line"]))
    if gs and p and p >= .55:
        G2[(r["sport"], r["player"], r["date"])].append(min(gs, key=lambda g: abs(g["line"] - r["line"]))["over"])   # ONE goblin per player-day: the one nearest the standard line
for sp in ("NHL", "WNBA"):
    X = [(k, v) for k, v in G2.items() if k[0] == sp]
    hits = [v[0] for k, v in X]
    print("  %s model>=0.55: %d unique player-days over %d days -> nearest goblin hit %.1f%%" % (sp, len(X), len({k[2] for k, v in X}), 100 * sum(hits) / max(len(hits), 1)))
