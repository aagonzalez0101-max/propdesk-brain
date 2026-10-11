"""ESPORTS CALIBRATION (2026-10-10, user: "calibrate everything" after Dota's 81-87% Spirit overs went 6 and 12 kills).
Maps each model's stated probability to what it ACTUALLY hit on graded lines, per market, so the card and the projection boards
stop showing confidence the models never earned.
    python _calib_es.py          # rebuild esports_calib.json from graded data and print the table
    import _calib_es; _calib_es.cal("dota", 0.87) -> the measured hit rate for an 87% call
Bins of stated p, shrunk toward the market's overall hit rate (k=20 pseudo-lines), then forced monotone (pool-adjacent-violators),
so a thin bin can't claim more than it showed. Rebuilt nightly in the grade run.
"""
import json, os

OUT = "esports_calib.json"
BINS = [0.0, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 1.01]
K = 20


def _rows(market):
    out, seen = [], set()
    if market == "cs2" and os.path.exists("cs2_priced_all.jsonl"):
        for l in open("cs2_priced_all.jsonl", encoding="utf-8"):
            r = json.loads(l)
            if r.get("result") in ("W", "L") and r.get("model_p") and r.get("maps") == 2:
                k = (r.get("match_id"), r.get("pid"), r.get("kind"), r.get("line"))
                if k not in seen:
                    seen.add(k); out.append((r["model_p"], r["result"] == "W"))
    elif market == "val" and os.path.exists("val_priced_all.jsonl"):
        for l in open("val_priced_all.jsonl", encoding="utf-8"):
            r = json.loads(l)
            if r.get("result") in ("W", "L") and r.get("model_p"):
                k = (r.get("match"), r.get("player"), r.get("stat"), r.get("line"))
                if k not in seen:
                    seen.add(k); out.append((r["model_p"], r["result"] == "W"))
    elif market == "dota" and os.path.exists("dota_paper.jsonl"):
        for l in open("dota_paper.jsonl", encoding="utf-8"):
            r = json.loads(l)
            if r.get("result") in ("W", "L") and r.get("p"):
                out.append((r["p"], r["result"] == "W"))
    return out


def build():
    table = {}
    for m in ("cs2", "val", "dota"):
        R = _rows(m)
        if not R:
            continue
        base = sum(w for _, w in R) / len(R)
        bins = []
        for lo, hi in zip(BINS, BINS[1:]):
            X = [w for p, w in R if lo <= p < hi]
            bins.append(dict(lo=lo, hi=hi, n=len(X), raw=(sum(X) / len(X)) if X else None, cal=(sum(X) + K * base) / (len(X) + K)))
        # pool adjacent violators: calibrated rate may not fall as stated p rises
        blocks = [[b["cal"], b["n"] + K, [i]] for i, b in enumerate(bins)]
        i = 0
        while i < len(blocks) - 1:
            if blocks[i][0] > blocks[i + 1][0]:
                v = (blocks[i][0] * blocks[i][1] + blocks[i + 1][0] * blocks[i + 1][1]) / (blocks[i][1] + blocks[i + 1][1])
                blocks[i] = [v, blocks[i][1] + blocks[i + 1][1], blocks[i][2] + blocks[i + 1][2]]
                del blocks[i + 1]
                i = max(i - 1, 0)
            else:
                i += 1
        for v, _, idx in blocks:
            for j in idx:
                bins[j]["cal"] = v
        table[m] = dict(n=len(R), base=base, bins=bins)
    json.dump(table, open(OUT, "w"), indent=1)
    return table


_T = None


def cal(market, p):
    """measured hit rate for a stated probability p in this market (falls back to p when no table)"""
    global _T
    if _T is None:
        try:
            _T = json.load(open(OUT))
        except Exception:
            _T = {}
    t = _T.get(market)
    if not t or p is None:
        return p
    for b in t["bins"]:
        if b["lo"] <= p < b["hi"]:
            return b["cal"]
    return p


if __name__ == "__main__":
    T = build()
    for m, t in T.items():
        print("%s: %d graded lines, overall hit %.1f%%" % (m.upper(), t["n"], 100 * t["base"]))
        for b in t["bins"]:
            if b["n"]:
                print("   model says %2d-%3d%%  n=%5d  actually hit %5.1f%%  -> calibrated %.1f%%"
                      % (100 * b["lo"], min(100 * b["hi"], 100), b["n"], 100 * b["raw"], 100 * b["cal"]))
