"""Fit a logistic recalibration on the first half of walk-forward rows, score the second half."""
import math, sys, io, contextlib, json
import _cs2_model as M
with contextlib.redirect_stdout(io.StringIO()):
    M.test(margin=True)
rows = M.LAST_ROWS
lg = lambda p: math.log(max(1e-6, p) / max(1e-6, 1 - p))
sg = lambda z: 1 / (1 + math.exp(-z))
h = len(rows) // 2
fit, ev = rows[:h], rows[h:]
a, b = 0.0, 1.0
for it in range(300):                      # Newton-free gradient descent on logloss
    ga = gb = 0.0
    for x in fit:
        z = a + b * lg(x[0]); p = sg(z); e = p - x[2]
        ga += e; gb += e * lg(x[0])
    a -= 1.0 * ga / len(fit); b -= 1.0 * gb / len(fit)
brier = lambda f: sum((f(x) - x[2]) ** 2 for x in ev) / len(ev)
print("calibration a=%.3f b=%.3f (fit on %d rows)" % (a, b, len(fit)))
print("holdout Brier: raw model %.4f | calibrated %.4f | naive %.4f" % (
    brier(lambda x: x[0]), brier(lambda x: sg(a + b * lg(x[0]))), brier(lambda x: x[1])))
import collections
cb = collections.defaultdict(list)
for x in ev:
    cb[min(9, int(sg(a + b * lg(x[0])) * 20))].append(x[2])
for k in sorted(cb):
    v = cb[k]; print("  cal P %.2f-%.2f n=%6d actual %.1f%%" % (k / 20, (k + 1) / 20, len(v), 100 * sum(v) / len(v)))
json.dump(dict(a=a, b=b), open("cs2_calib.json", "w"))
