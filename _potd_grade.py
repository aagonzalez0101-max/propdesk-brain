"""Grade the esports pick-of-the-day ledgers (10/16, user: "we'll only really use 1-2 lines from any esport").

    python _potd_grade.py          # cs2_potd.jsonl <- results from cs2_paper.jsonl (graded by _cs2_grade.py); prints the running record

Each POTD row is the same leg _cs2_live.py priced, so its result is already in cs2_paper.jsonl: match_id + player + kind + side.
"""
import json, os

F = "cs2_potd.jsonl"


def main():
    if not os.path.exists(F):
        print("no CS2 POTD yet"); return
    R = [json.loads(x) for x in open(F, encoding="utf-8") if x.strip()]
    res = {}
    for x in open("cs2_paper.jsonl", encoding="utf-8"):
        r = json.loads(x)
        if r.get("result") in ("W", "L", "VOID"):
            side = "over" if r.get("side") == "higher" else "under"
            res[(r.get("match_id"), r["player"], r.get("kind"), side)] = (r["result"], r.get("actual"))
    n = 0
    for r in R:
        if r.get("result"):
            continue
        hit = res.get((r.get("match_id"), r["player"], r.get("kind"), r["side"]))
        if hit:
            r["result"], r["actual"] = hit; n += 1
    with open(F, "w", encoding="utf-8") as f:
        for r in R:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    g = [r for r in R if r.get("result") in ("W", "L")]
    w = sum(r["result"] == "W" for r in g)
    print("CS2 POTD: graded %d new -- forward record %d-%d%s (backtest 19-10, 65.5%%)" % (n, w, len(g) - w, " (%.0f%%)" % (100 * w / len(g)) if g else ""))


if __name__ == "__main__":
    main()
