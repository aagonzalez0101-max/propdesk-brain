"""Is the direction TOP TIER real? (2026-10-07)
  1) TIME SPLIT: logistic trained ONLY on lines before 10/04, top tier applied to 10/04+ (the model never saw those days).
  2) NULL TEST: replace the measured reasons with RANDOM reasons (same count, random direction) 500 times and see how often a
     random filter scores as well as the real one on the same leave-one-day-out predictions. If random does it often -> fluke.
"""
import random, math, collections
import _dir_search as D

R = D.graded()
CUT = "2026-10-04"


def hit(T):
    w = sum(1 for r in T if r["over"] == (r["side"] == "over")); return w, len(T)


# 1) time split
out = []
for sp in ("NHL", "WNBA"):
    tr = [r for r in R if r["sport"] == sp and r["date"] < CUT]; te = [r for r in R if r["sport"] == sp and r["date"] >= CUT]
    M = D.fit([[r[k] for k in D.SPEC[sp]] for r in tr], [r["over"] for r in tr], D.L2)
    for r, p in zip(te, D.pred(M, [[r[k] for k in D.SPEC[sp]] for r in te])):
        out.append(dict(r, p=float(p)))
for k in (3, 5, 99):
    T = D.top_tier(out, k=k); w, n = hit(T)
    by = collections.Counter((r["sport"], r["side"], r["over"] == (r["side"] == "over")) for r in T)
    print("TIME SPLIT (train < 10/04, test 10/04-10/07) top %-2s: %d-%d  %.1f%%   %s" % (k if k < 99 else "all", w, n - w, 100 * w / max(n, 1),
          {"%s %s" % (a, b): "%d-%d" % (by[(a, b, True)], by[(a, b, False)]) for a, b in {(x[0], x[1]) for x in by}}))

# 2) null test on leave-one-day-out predictions
lo = D.lodo_out(R)
real = D.top_tier(lo, k=99); rw, rn = hit(real)
print("\nREAL reasons, leave-one-day-out pool: %d-%d  %.1f%%" % (rw, rn - rw, 100 * rw / rn))
orig = D.votes
# candidate reason pool: every binary feature split the real reasons are drawn from, with RANDOM direction
FEATS = [("home_f", .5), ("rest_short", .5), ("rest_long", .5), ("ast_stat", .5), ("def_opp_pr", .3), ("def_opp_pr", .7), ("l10_hit", .7),
         ("med_line", 1.3), ("med_line", 1.1), ("med_line", .85), ("proj_line_f", .15), ("off_team_pr", .7), ("l10_hit", .8), ("ud_lean_f", .02),
         ("ud_lean_f", -.02), ("off_opp_pr", .7), ("off_opp_pr", .3), ("def_team_pr", .7), ("def_team_pr", .3), ("min_trend", 1.1), ("min_trend", .9)]
random.seed(7)
better = 0; scores = []
for it in range(500):
    picks = {sp: [(f, t, random.choice((">=", "<=")), random.choice((1, -1))) for f, t in random.sample(FEATS, 10 if sp == "WNBA" else 8)] for sp in ("NHL", "WNBA")}

    def fake(r, picks=picks):
        v = []
        for f, t, op, sg in picks[r["sport"]]:
            x = r.get(f, 0) or 0
            if (x >= t) if op == ">=" else (x <= t):
                v.append(sg)
        return v
    D.votes = fake
    T = D.top_tier(lo, k=99)
    if len(T) >= 60:
        w, n = hit(T); scores.append(w / n)
        if w / n >= rw / rn:
            better += 1
D.votes = orig
scores.sort()
print("NULL: %d random reason-sets gave >= 60 picks; median %.1f%%, 95th pct %.1f%%; %d matched/beat the real %.1f%% -> p ~ %.3f"
      % (len(scores), 100 * scores[len(scores) // 2], 100 * scores[int(.95 * len(scores))], better, 100 * rw / rn, (better + 1) / (len(scores) + 1)))
