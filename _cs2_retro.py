"""Re-price already-graded real Underdog lines with v6 vs v7 using ONLY maps dated before the line's day."""
import json, math, collections, sys, io, contextlib
import _cs2_model as M, _cs2_live as L
cut = sys.argv[1] if len(sys.argv) > 1 else "2026-09-17"
maps_all = M.load()
M_load = M.load
M.load = lambda: [m for m in maps_all if m[0] < cut]
S, n = L.build_state()
M.load = M_load
coef = json.load(open("cs2_v7_coef.json")); cal = json.load(open("cs2_calib.json"))
calib = lambda p: 1 / (1 + math.exp(-(cal["a"] + cal["b"] * math.log(max(1e-6, p) / max(1e-6, 1 - p)))))
rows = [json.loads(l) for l in open("cs2_priced_all.jsonl")]
latest = {}
for r in rows:
    if r.get("result") in ("W", "L") and r["start"][:10] >= cut and r["side"] == "higher":
        latest[(r["match_id"], r["player"], r["stat"])] = r
out = []
for r in latest.values():
    pid, clan, opp = r["pid"], r.get("clan"), r.get("opp_clan")
    if not clan or not opp or S.pmaps[pid] < 8:
        continue
    saved = None
    if r.get("market_winp") is not None:
        mp = L.match_to_map_winp(r["market_winp"]); saved = (S.elo[clan], S.elo[opp])
        S.elo[clan] = M.ELO_BASE + 200 * math.log10(mp / (1 - mp)); S.elo[opp] = M.ELO_BASE - 200 * math.log10(mp / (1 - mp))
    res = {}
    for ver in ("v6", "v7"):
        m = 1.0
        if ver == "v7":
            season = S.pk[pid] / max(1, S.pr[pid])
            rec = S.v7["rec"][pid]; rf = (sum(rec) / len(rec) / max(.3, season)) if rec else 1.0
            m = 1 + (coef["const"] + coef["recent_form"] * (rf - 1) + coef["tier"] * S.v7["tier"].get(pid, 0)
                     + coef["elo_gap/100"] * (S.elo[clan] - S.elo[opp]) / 100 + coef["n_maps/100"] * min(200, S.pmaps[pid]) / 100
                     + coef["bo3"] * (1 if r["maps"] == 2 else 0) + coef["fk_rate*10"] * 10 * S.v7["fk"][pid] / max(1, S.pr[pid]))
            m = max(.85, min(1.15, m))
        sc = S.hs_rate.get(pid, S.lg_hs) if r["kind"] == "hs" else 1.0
        o = S.kpr
        S.kpr = lambda q, op=None, _o=o, _m=m * sc: _o(q, op) * _m
        po, mu = S.p_over(pid, clan, opp, r["line"], r["maps"])
        S.kpr = o
        res[ver] = (calib(po), mu)
    if saved: S.elo[clan], S.elo[opp] = saved
    over = r["actual"] > r["line"]
    out.append((r, res, over))
be = 0.534
print("maps as of < %s: %d | graded lines re-priced: %d" % (cut, n, len(out)))
for ver in ("v6", "v7"):
    for thr in (0.0, 0.03, 0.05, 0.08):
        w = l = 0
        for r, res, over in out:
            p = res[ver][0]
            for side, prob, win in (("higher", p, over), ("lower", 1 - p, (not over) and r["actual"] < r["line"])):
                if prob - be >= thr:
                    w += win; l += (not win)
        if w + l: print("  %s edge>=%2d%%: %d-%d (%.1f%%)" % (ver, 100 * thr, w, l, 100 * w / (w + l)))
    for nm in (1, 2):
        w = l = 0
        for r, res, over in out:
            if r["maps"] != nm: continue
            p = res[ver][0]
            for prob, win in ((p, over), (1 - p, (not over) and r["actual"] < r["line"])):
                if prob - be >= 0.03: w += win; l += (not win)
        if w + l: print("  %s edge>=3%% maps=%d: %d-%d (%.1f%%)" % (ver, nm, w, l, 100 * w / (w + l)))

dump = []
for r, res, over in out:
    for ver in ("v6", "v7"):
        p = res[ver][0]
        for side, prob, win in (("OVER", p, over), ("UNDER", 1 - p, (not over) and r["actual"] < r["line"])):
            dump.append(dict(ver=ver, player=r["player"], match=r["match"], mid=r["match_id"], start=r["start"], stat=r["stat"],
                             maps=r["maps"], line=r["line"], side=side, actual=r["actual"], prob=prob, win=bool(win),
                             push=r["actual"] == r["line"]))
json.dump(dump, open("_cs2_retro_dump.json", "w"))
