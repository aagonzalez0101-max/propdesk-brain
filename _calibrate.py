"""SELF-CORRECTING CALIBRATION (2026-10-02). Every graded call on real app lines -> per market x side: how often it really won vs what
the model said. The correction is shrunk by sample size (adj = gap * n / (n + 150)) so 25 calls barely move it and 400 move it most of
the way. The card (_card.py) and the site read calibration.json; the daily grade run rebuilds it.

    python _calibrate.py          # rebuild calibration.json and print the table

Measured 10/2 (1,491 calls): WNBA overs -6.5 (model too high), WNBA unders +11.7, NHL shots over +0.6, NHL saves under -4.8, NHL
assists under -6.4, MLB overs -14.5.
"""
import json, collections

SHRINK = 150.0


def side(c):
    return "over" if "OVER" in c else "under"


def market(sport, stat):
    k = "".join(ch for ch in (stat or "").lower() if ch.isalnum())
    if sport == "NHL":
        return "NHL saves" if "saves" in k else "NHL shots" if "shot" in k else "NHL goals" if k == "goals" else \
               "NHL assists" if "assist" in k else "NHL points" if "point" in k else "NHL other"
    if sport == "SOCCER":
        return "SOC " + ("passes" if "pass" in k else "saves" if "save" in k else "sot" if "target" in k else "shots" if "shot" in k else "other")
    return sport


def prob(r):
    s = side(r["call"])
    if r.get("p_pin") is not None:
        return r["p_pin"] if s == "over" else 1 - r["p_pin"]
    if r.get("p_role") is not None:
        return r["p_role"] if r.get("side") in (None, s) else 1 - r["p_role"]
    for k in ("p_over", "p"):
        if r.get(k) is not None:
            return r[k] if s == "over" else 1 - r[k]
    return None


if __name__ == "__main__":
    by = collections.defaultdict(list)
    for l in open("calls_log.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if r.get("result") not in ("W", "L") or (r.get("call") or "")[:4] not in ("TAKE", "LEAN") or r["sport"] == "SOCCER" or __import__("_calls").is_alt(r):
            continue                      # soccer stores P differently per stat; calibrated separately once it has volume
        p = prob(r)
        if p is None:
            continue
        by["%s|%s" % (market(r["sport"], r["stat"]), side(r["call"]))].append((p, r["result"] == "W"))
    out = {}
    for k, L in by.items():
        n = len(L); act = sum(w for _, w in L) / n; mod = sum(p for p, _ in L) / n
        out[k] = dict(n=n, actual=round(act, 4), model=round(mod, 4), adj=round((act - mod) * n / (n + SHRINK), 4))
    json.dump(out, open("calibration.json", "w"), indent=1)
    for k in sorted(out, key=lambda k: -out[k]["n"]):
        v = out[k]
        print("%-22s n=%-4d actual %5.1f%%  model %5.1f%%  -> adjust %+.1f pts" % (k, v["n"], 100 * v["actual"], 100 * v["model"], 100 * v["adj"]))
