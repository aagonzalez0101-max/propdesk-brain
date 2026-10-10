"""Does the PROJECTION CALL work on past bets? (2026-09-30)
Real lines + pre-game projections only:
  MLB  -- _pitcher_bt.json (September board K / ER / OUTS rows, graded) + board HRR/HITS rows graded from statsapi
  CS2  -- cs2_paper_audited.jsonl, date-verified grades only (model_mu vs the real UD/PP line)
  VAL  -- val_paper.jsonl graded rows
Gap = (projection - line) / SD, SD = that market's residual spread (actual - projection), measured on the same rows.
Each row is bet in the direction the CALL says; hit rate reported per call type.
"""
import json, math, collections, statistics as st

def call(gap):
    if gap >= 0.5: return "TAKE OVER"
    if gap <= -0.5: return "TAKE UNDER"
    if abs(gap) < 0.25: return "TOO CLOSE"
    return "LEAN OVER" if gap > 0 else "LEAN UNDER"

def evaluate(name, rows):
    """rows: dicts with market, mu, line, actual"""
    rows = [r for r in rows if r["mu"] is not None and r["actual"] is not None and r["actual"] != r["line"]]
    if not rows:
        print(name, "no rows"); return
    sd = {}
    for m in {r["market"] for r in rows}:
        res = [r["actual"] - r["mu"] for r in rows if r["market"] == m]
        sd[m] = max(st.pstdev(res), 0.5) if len(res) > 5 else None
    tally = collections.defaultdict(lambda: [0, 0])
    per = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
    for r in rows:
        s = sd.get(r["market"])
        if not s:
            continue
        c = call((r["mu"] - r["line"]) / s)
        over = r["actual"] > r["line"]
        win = over if "OVER" in c else (not over) if "UNDER" in c else over      # TOO CLOSE scored as 'over' just to show it's a coin flip
        tally[c][0] += win; tally[c][1] += 1
        per[r["market"]][c][0] += win; per[r["market"]][c][1] += 1
    print("\n=== %s  (%d graded rows with a real line) ===" % (name, len(rows)))
    for c in ("TAKE OVER", "LEAN OVER", "TOO CLOSE", "LEAN UNDER", "TAKE UNDER"):
        w, n = tally[c]
        if n:
            z = (w / n - .535) / math.sqrt(.535 * .465 / n)
            print("   %-11s %5d bets  hit %.1f%%   (vs 53.5%% b/e: z=%+.1f)" % (c, n, 100 * w / n, z))
    for m, d in sorted(per.items()):
        print("     %-8s sd %.2f  " % (m, sd[m]) + "  ".join("%s %d/%d" % (c.replace("TAKE ", "T-").replace("LEAN ", "L-").replace("TOO CLOSE", "CLOSE"), v[0], v[1]) for c, v in d.items()))

# ---- MLB pitcher props (real board lines, box-score graded)
P = json.load(open("_pitcher_bt.json"))
seen = set(); mlb = []
for r in P:
    k = (r["day"], r["selection"], r["market"], r["line"])
    if k in seen or r.get("projected_mean") is None:
        continue
    seen.add(k)
    # the file stores win for the pick's side; recover the actual from side + win is impossible, so re-derive over/under
    over = r["win"] if r["side"] == "OVER" else (not r["win"])
    mlb.append(dict(market=r["market"], mu=r["projected_mean"], line=r["line"], actual=r["line"] + (0.5 if over else -0.5)))
evaluate("MLB pitcher props (Sept boards: K / ER / OUTS)", mlb)

# ---- CS2 (date-verified grades only)
cs = [json.loads(l) for l in open("cs2_paper_audited.jsonl", encoding="utf-8")]
cs2 = [dict(market=r.get("kind") or "kills", mu=r.get("model_mu"), line=float(r["line"]), actual=r.get("audit_actual"))
       for r in cs if r.get("audit_result")]
evaluate("CS2 (date-verified, real UD/PP lines)", cs2)

# ---- Valorant
va = [json.loads(l) for l in open("val_paper.jsonl", encoding="utf-8")]
val = [dict(market=r.get("kind") or "kills", mu=r.get("model_mu"), line=float(r["line"]), actual=r.get("actual"))
       for r in va if r.get("actual") is not None]
evaluate("VALORANT (real UD/PP lines)", val)
