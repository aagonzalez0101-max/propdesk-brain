"""Walk-forward test of the HEADSHOT prop pricing (kills model x shrunk HS rate)."""
import math, collections, json, sys
import _cs2_model as M
HS_PRIOR = float(sys.argv[1]) if len(sys.argv) > 1 else 60
maps = M.load(); S = M.State()
hk = collections.Counter(); hh = collections.Counter(); lgk = lgh = 0
rows = []
c = json.load(open("cs2_calib.json"))
cal = lambda p: 1 / (1 + math.exp(-(c["a"] + c["b"] * math.log(max(1e-6, p) / max(1e-6, 1 - p)))))
for i, (date, match, mno, gid, teams) in enumerate(maps):
    names = list(teams)
    if i >= 800 and i % 3 == 0:
        lg_rate = lgh / lgk if lgk else .53
        for t, o in ((names[0], names[1]), (names[1], names[0])):
            for r in teams[t]:
                q = r["player"]
                if S.pmaps[q] < 8 or r["hs"] is None:
                    continue
                rate = (hh[q] + HS_PRIOR * lg_rate) / (hk[q] + HS_PRIOR)
                mu_naive = (hh[q] + 1) / (S.pmaps[q] + 1)
                line = math.floor(mu_naive) + 0.5
                orig = S.kpr
                S.kpr = lambda p, op=None, _o=orig: _o(p, op) * rate
                pm, mu = S.p_over(q, t, o, line)
                S.kpr = orig
                rows.append((pm, cal(pm), M.poisson_over(mu_naive, line), r["hs"] > line))
    for ps in teams.values():
        for r in ps:
            if r["hs"] is not None and r["kills"] is not None:
                hk[r["player"]] += r["kills"]; hh[r["player"]] += r["hs"]; lgk += r["kills"]; lgh += r["hs"]
    S.update(teams)
n = len(rows)
b = lambda k: sum((x[k] - x[3]) ** 2 for x in rows) / n
print("HS prior %d | rows %d | over rate %.1f%% | Brier raw %.4f  calibrated %.4f  naive %.4f" % (HS_PRIOR, n, 100 * sum(x[3] for x in rows) / n, b(0), b(1), b(2)))
cb = collections.defaultdict(list)
for x in rows:
    cb[min(19, int(x[1] * 20))].append(x[3])
for k in sorted(cb):
    v = cb[k]
    if len(v) > 50: print("  cal P %.2f-%.2f n=%6d actual %.1f%%" % (k / 20, (k + 1) / 20, len(v), 100 * sum(v) / len(v)))
