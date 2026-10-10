"""Grade Valorant paper picks against vlr.gg.

Two bugs kept 19 picks ungraded since 2026-09-21:
  1. `_val_live.py grade` was never implemented -- the branch printed the docstring and exited.
  2. `val_paper.jsonl` stores the UNDERDOG match id (e.g. 223012). vlr.gg uses its own
     (753459). Fetching vlr.gg/<underdog_id> 404s or returns an unrelated page, so the id can
     never be the join key. Match on TEAM NAMES out of the vlr slug instead.
Also: a stat row's nickname key is `player`, not `nick`.
"""
import json, re, sys, unicodedata, collections
sys.path.insert(0, ".")
from betting import valorant as V

OUT = "val_paper.jsonl"
norm = lambda s: re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", (s or "").lower())
                        .encode("ascii", "ignore").decode())
def toks(s):
    return {t for t in re.split(r"[^a-z0-9]+", (s or "").lower()) if len(t) > 2}


def main(pages=8, OUT=OUT):
    rows = [json.loads(l) for l in open(OUT, encoding="utf-8")]
    import datetime as _dt
    _recent = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=4)).isoformat()
    pend = [r for r in rows if r.get("result") not in ("W", "L") or (r.get("rounds") is None and str(r.get("start", "")) >= _recent)]
    print("%d picks, %d ungraded" % (len(rows), len(pend)), flush=True)
    feed = []
    for p in range(1, pages + 1):
        try:
            feed += V.results_page(p)
        except Exception:
            break
    print("indexed %d finished matches from vlr" % len(feed), flush=True)
    cache = {}
    settled = 0
    for r in pend:
        want = toks(r.get("match"))
        best, score = None, 0
        for m in feed:
            s = len(want & toks(m.get("slug")))
            if s > score:
                best, score = m, s
        if not best or score < 2:
            print("  no vlr match for %r" % r.get("match"))
            continue
        mid = best["id"]
        if mid not in cache:
            try:
                cache[mid] = V.match(mid, best["slug"])
            except Exception as e:
                print("  fetch %s failed: %s" % (mid, str(e)[:50]))
                cache[mid] = None
        d = cache[mid]
        if not d or len(d.get("maps") or []) < int(r.get("maps") or 2):
            continue
        tot, found, rnds = 0, False, []
        for mp in d["maps"][:int(r.get("maps") or 2)]:
            rnds.append(mp.get("rounds") or 0)                 # 10/9: rounds per map -> post-mortem separates long maps/OT from model error
            for row in mp["rows"]:
                if norm(row.get("player")) == norm(r.get("player")):
                    tot += row.get("k") or 0
                    found = True
        if not found:
            print("  %s not in %s" % (r.get("player"), best["slug"][:40]))
            continue
        line = float(r["line"])
        r["actual"] = tot
        r["vlr_id"] = mid
        r["rounds"] = sum(rnds) or None; r["maps_rounds"] = rnds
        r["result"] = "W" if ((tot < line) if r.get("side") == "lower" else (tot > line)) else "L"
        settled += 1
    with open(OUT, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    g = [r for r in rows if r.get("result") in ("W", "L")]
    w = sum(1 for r in g if r["result"] == "W")
    print("\nsettled %d | RECORD %d-%d of %d (%.1f%%)"
          % (settled, w, len(g) - w, len(g), 100 * w / len(g) if g else 0))
    for r in sorted(g, key=lambda x: str(x.get("player"))):
        print("   %-14s %-6s %-6s actual %-5s %s   edge %s"
              % (r.get("player"), r.get("side"), r.get("line"), r.get("actual"), r["result"],
                 ("%+.1f%%" % (100 * r["edge"])) if r.get("edge") is not None else "-"))


if __name__ == "__main__":
    # 10/7: `python _val_grade.py val_priced_all.jsonl 15` grades the whole priced board (every line we priced), not just paper picks
    main(int(sys.argv[2]) if len(sys.argv) > 2 else 8, sys.argv[1] if len(sys.argv) > 1 else OUT)
