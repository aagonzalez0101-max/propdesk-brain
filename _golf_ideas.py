"""Golf idea tests (2026-10-08, user: "keep tweaking"). Each idea is checked on ~100k historical rounds (is it real?) and on the
graded PrizePicks lines (does PP miss it?).
  A) hot/cold previous round: does round k's score vs the field carry into round k+1 (beyond skill)?
  B) round number: are PP lines too high/low by round?
  C) leaderboard: final-round leaders / chasers, and players at the cut line in round 2."""
import json, collections, statistics as st
R = [json.loads(l) for l in open("golf_rounds.jsonl", encoding="utf-8")]
ev = collections.defaultdict(list)
for r in R:
    ev[(r["event"], r["round"])].append(r)
favg = {k: st.mean(x["strokes"] for x in v) for k, v in ev.items() if len(v) >= 30}
# player career relative mean as a crude skill (leave-one-out not needed for a correlation sign check)
rel = collections.defaultdict(dict)
for (e, rd), v in ev.items():
    if (e, rd) in favg:
        for x in v:
            rel[(e, x["player_id"])][rd] = x["strokes"] - favg[(e, rd)]
skill = collections.defaultdict(list)
for (e, p), d in rel.items():
    skill[p] += list(d.values())
sk = {p: st.mean(v) for p, v in skill.items() if len(v) >= 20}
print("A) previous round vs field -> next round vs field (both minus player skill)")
pairs = []
for (e, p), d in rel.items():
    if p not in sk:
        continue
    for rd in (1, 2, 3):
        if rd in d and rd + 1 in d:
            pairs.append((d[rd] - sk[p], d[rd + 1] - sk[p], rd))
for lo, hi in ((-99, -4), (-4, -2), (-2, 0), (0, 2), (2, 4), (4, 99)):
    X = [b for a, b, rd in pairs if lo <= a < hi]
    if len(X) > 300:
        print("   prev round %+3d..%+3d vs his norm   n=%6d   next round vs his norm %+5.2f" % (lo, hi, len(X), st.mean(X)))
print("C) final round by 54-hole position (score vs field, minus skill)")
tot = collections.defaultdict(dict)
for (e, p), d in rel.items():
    if all(k in d for k in (1, 2, 3, 4)) and p in sk:
        tot[e][p] = (d[1] + d[2] + d[3], d[4] - sk[p])
for lo, hi, lab in ((0, 1, "54-hole leader"), (1, 5, "2nd-5th"), (5, 20, "6th-20th"), (20, 999, "21st+")):
    X = []
    for e, d in tot.items():
        order = sorted(d.values(), key=lambda x: x[0])
        X += [x[1] for x in order[lo:hi]]
    if X:
        print("   %-16s n=%6d   R4 vs his norm %+5.2f" % (lab, len(X), st.mean(X)))
print("   R2 by position after R1 (cut pressure):")
r2 = collections.defaultdict(list)
for e in {k[0] for k in favg}:
    d = {p: v for (ee, p), v in rel.items() if ee == e and 1 in v and 2 in v and p in sk}
    if len(d) < 60:
        continue
    order = sorted(d.items(), key=lambda kv: kv[1][1]); n = len(order)
    for i, (p, v) in enumerate(order):
        b = "top 20%" if i < .2 * n else ("cut zone 45-70%" if .45 * n <= i < .7 * n else ("bottom 30%" if i >= .7 * n else "mid"))
        r2[b].append(v[2] - sk[p])
for b, X in r2.items():
    print("     %-16s n=%6d   R2 vs his norm %+5.2f" % (b, len(X), st.mean(X)))
print("B) graded PrizePicks lines by round (single-course events)")
C = [json.loads(l) for l in open("calls_log.jsonl", encoding="utf-8")]
C = [r for r in C if r["sport"] == "GOLF" and r.get("actual") is not None and r["actual"] != r["line"] and "MULTI-COURSE (course per player unknown)" not in (r.get("flags") or [])]
for rd in sorted({r["round"] for r in C}):
    X = [r for r in C if r["round"] == rd]
    print("   round %d  n=%3d  under %.1f%%  mean actual-line %+.2f" % (rd, len(X), 100 * sum(r["actual"] < r["line"] for r in X) / len(X), st.mean(r["actual"] - r["line"] for r in X)))
