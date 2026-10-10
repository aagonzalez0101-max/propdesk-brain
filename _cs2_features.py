"""Walk-forward feature screen for CS2 kills: which extra metrics explain what the model misses?

    python _cs2_features.py

For every player-map (after warm-up, player with 8+ maps) we take the model's expected kills
(v6 pieces: shrunk opponent-adjusted KPR x (won, map-length) multiplier x rounds -- using the
ACTUAL rounds/result so we isolate the player-skill part) and the residual = actual - expected.
Each candidate metric is computed from data dated BEFORE the map. A metric earns a place only if
it moves the residual in a consistent, significant direction (bucket means + correlation t-stat).
"""
import math, collections, statistics as S
import _cs2_model as M

maps = M.load()
st = M.State()
# pre-map trackers
p_adr = collections.Counter(); p_adr_n = collections.Counter()
p_fk = collections.Counter(); p_hs = collections.Counter(); p_kills = collections.Counter()
p_map_k = collections.Counter(); p_map_r = collections.Counter()
p_last_team = {}; p_team_streak = collections.Counter()
p_recent = collections.defaultdict(lambda: collections.deque(maxlen=10))   # recent KPR / season KPR
rows = []
for i, (date, match, mno, gid, teams) in enumerate(maps):
    names = list(teams)
    if i >= 1500:
        lg = st.lg_k / st.lg_r
        for t, o in ((names[0], names[1]), (names[1], names[0])):
            for r in teams[t]:
                q = r["player"]
                if st.pmaps[q] < 8 or r["hs"] is None:
                    continue
                exp = st.kpr(q, o) * st.mult_wr(r["win"], r["rounds"]) * r["rounds"]
                res = (r["kills"] - exp) / max(1.0, exp)            # relative residual
                season = st.pk[q] / max(1, st.pr[q])
                f = dict(
                    hs_pct=p_hs[q] / max(1, p_kills[q]),                                   # role proxy (AWP low)
                    fk_rate=p_fk[q] / max(1, st.pr[q]),                                    # entry role proxy
                    adr_vs_kpr=(p_adr[q] / max(1, p_adr_n[q])) / 100 / max(.3, season),    # damage not converted yet
                    map_kpr=((p_map_k[(q, r["map"])] + 60 * season) / (p_map_r[(q, r["map"])] + 60)) / max(.3, season),
                    new_team=1.0 if p_last_team.get(q) != t else 0.0,
                    team_streak=min(30, p_team_streak[q]) if p_last_team.get(q) == t else 0,
                    recent_form=(sum(p_recent[q]) / len(p_recent[q]) / max(.3, season)) if p_recent[q] else 1.0,
                    tier={"s": 3, "a": 2, "b": 1}.get(r.get("tier"), 0),
                    bo=r.get("bo") or 0,
                    map_no=mno,
                    n_maps=min(200, st.pmaps[q]),
                    team_elo_gap=st.elo[t] - st.elo[o],
                )
                rows.append((res, f))
    # update trackers AFTER prediction
    for t, ps in teams.items():
        for r in ps:
            q = r["player"]
            if r["adr"] is not None:
                p_adr[q] += r["adr"]; p_adr_n[q] += 1
            if r["fk"] is not None:
                p_fk[q] += r["fk"]
            if r["hs"] is not None:
                p_hs[q] += r["hs"]; p_kills[q] += r["kills"]
            p_map_k[(q, r["map"])] += r["kills"]; p_map_r[(q, r["map"])] += r["rounds"]
            p_team_streak[q] = p_team_streak[q] + 1 if p_last_team.get(q) == t else 1
            p_last_team[q] = t
            p_recent[q].append(r["kills"] / r["rounds"])
    st.update(teams)

print("player-maps screened: %d | mean relative residual %+.3f (sd %.3f)" % (
    len(rows), S.mean(x[0] for x in rows), S.pstdev(x[0] for x in rows)))
for key in rows[0][1]:
    xs = [f[key] for _, f in rows]; ys = [r for r, _ in rows]
    mx, my = S.mean(xs), S.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        continue
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    r_ = cov / math.sqrt(sxx * sum((y - my) ** 2 for y in ys))
    t = r_ * math.sqrt((len(xs) - 2) / max(1e-12, 1 - r_ * r_))
    qs = sorted(xs)
    cuts = [qs[int(len(qs) * k / 5)] for k in range(1, 5)]
    b = collections.defaultdict(list)
    for x, y in zip(xs, ys):
        b[sum(x > c for c in cuts)].append(y)
    print("%-13s r=%+.3f t=%+6.1f | quintile residuals: %s" % (
        key, r_, t, "  ".join("%+.3f" % S.mean(b[k]) for k in sorted(b))))

# ---- fit the survivors on the first half, score the second half
import json
KEEP = ["recent_form", "map_kpr", "tier", "team_elo_gap", "n_maps", "bo", "fk_rate"]
def x_of(f):
    return [1.0, f["recent_form"] - 1, f["map_kpr"] - 1, f["tier"], f["team_elo_gap"] / 100, f["n_maps"] / 100,
            1.0 if f["bo"] == 3 else 0.0, f["fk_rate"] * 10]
h = len(rows) // 2
X = [x_of(f) for _, f in rows[:h]]; Y = [r for r, _ in rows[:h]]
k = len(X[0])
A = [[sum(a[i] * a[j] for a in X) for j in range(k)] for i in range(k)]
bvec = [sum(a[i] * y for a, y in zip(X, Y)) for i in range(k)]
for c in range(k):                                   # gaussian elimination
    p = max(range(c, k), key=lambda rr: abs(A[rr][c])); A[c], A[p] = A[p], A[c]; bvec[c], bvec[p] = bvec[p], bvec[c]
    for rr in range(k):
        if rr != c:
            fct = A[rr][c] / A[c][c]
            A[rr] = [A[rr][j] - fct * A[c][j] for j in range(k)]; bvec[rr] -= fct * bvec[c]
beta = [bvec[i] / A[i][i] for i in range(k)]
names = ["const", "recent_form", "map_kpr", "tier", "elo_gap/100", "n_maps/100", "bo3", "fk_rate*10"]
print("\nfit on first half:", ", ".join("%s %+.4f" % (n, b) for n, b in zip(names, beta)))
ev = rows[h:]
base = sum(r * r for r, _ in ev) / len(ev)
adj = sum((r - sum(b * x for b, x in zip(beta, x_of(f)))) ** 2 for r, f in ev) / len(ev)
print("holdout residual MSE: v6 %.5f -> v7 %.5f (%.2f%% of the unexplained variance removed)" % (base, adj, 100 * (1 - adj / base)))
json.dump(dict(zip(names, beta)), open("cs2_v7_coef.json", "w"))
