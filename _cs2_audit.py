"""Re-grade EVERY graded CS2 paper pick with the date check (the 2026-09-29 bug: picks were matched to the first
finished series between the two team names, with no date). Writes cs2_paper_audited.jsonl -- the original ledger is
not touched -- and prints the corrected records.

    python _cs2_audit.py [window]
"""
import sys, os, json, re, collections
import _cs2_grade as G

N = int(sys.argv[1]) if len(sys.argv) > 1 else 15000
SC = "_bo3_stats"
os.makedirs(SC, exist_ok=True)


def stats(gid):
    f = os.path.join(SC, "%d.json" % gid)
    if os.path.exists(f):
        return json.load(open(f, encoding="utf-8"))
    st = G.stats_for(gid, {})
    if st:
        json.dump(st, open(f, "w", encoding="utf-8"))
    return st


rows = [json.loads(l) for l in open(G.OUT, encoding="utf-8")]
graded = [r for r in rows if r.get("result") in ("W", "L")]
print("%d graded picks to audit" % len(graded), flush=True)
ms = G.window(N)
print("indexed %d bo3 matches" % len(ms), flush=True)
bypair = collections.defaultdict(list)
for m in ms:
    toks = set(re.split(r"[-]", (m.get("slug") or "").lower()))
    bypair[frozenset(t for t in toks if len(t) > 2)].append(m)

tally = collections.Counter()
for k, r in enumerate(graded):
    parts = [p.strip() for p in re.split(r"\s+vs\.?\s+", r.get("match") or "", flags=re.I)]
    want = {t for p in parts for t in re.split(r"[^A-Za-z0-9]+", p.lower()) if len(t) > 2}
    best, score = None, 0
    for key, lst in bypair.items():
        s = len(want & set(key))
        if s > score:
            best, score = lst, s
    r["audit"] = "unverifiable"
    if best and score >= 2:
        maps = int(r.get("maps") or 2)
        for m in best:
            if m.get("status") != "finished" or not G.near(m.get("start_date"), r.get("start")):
                continue
            gs = sorted(m.get("games") or [], key=lambda x: x.get("number") or 0)
            if len(gs) < maps or any(g.get("status") != "finished" for g in gs[:maps]):
                continue
            agg = {}
            ok = True
            for gm in gs[:maps]:
                st = stats(gm["id"])
                if len(st) < 10:
                    ok = False; break
                for p in st:
                    sp = p.get("steam_profile") or {}
                    nk = sp.get("nickname") or ((sp.get("player") or {}).get("nickname")) or ""
                    e = agg.setdefault(G.norm(G.base_nick(nk)), {"kills": 0, "hs": 0})
                    e["kills"] += p.get("kills") or 0
                    e["hs"] += p.get("headshots") or p.get("hs") or 0
            if not ok:
                continue
            hit = agg.get(G.norm(G.base_nick(r.get("player"))))
            if not hit:
                continue
            val = hit["hs"] if r.get("kind") == "hs" else hit["kills"]
            line = float(r["line"])
            res = "W" if ((val < line) if r.get("side") == "lower" else (val > line)) else "L"
            r["audit_actual"], r["audit_result"] = val, res
            r["audit"] = "same" if res == r["result"] else "FLIPPED"
            break
    tally[r["audit"]] += 1
    if (k + 1) % 200 == 0:
        print("  %d / %d  %s" % (k + 1, len(graded), dict(tally)), flush=True)

with open("cs2_paper_audited.jsonl", "w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("\nAUDIT:", dict(tally))
ver = [r for r in graded if r.get("audit_result")]
potd = lambda r: 0.06 <= (r.get("edge") or 0) < 0.09 and not (0.45 <= (r.get("map_winp") or .5) <= 0.55) and not r.get("suspect")
for lbl, X in (("ALL verified", ver), ("GOOD ZONE verified", [r for r in ver if potd(r)]),
               ("GOOD ZONE verified, 9/18+", [r for r in ver if potd(r) and (r.get("start") or "") >= "2026-09-18"])):
    w = sum(r["audit_result"] == "W" for r in X)
    print("%-28s %d-%d  (%.1f%%)" % (lbl, w, len(X) - w, 100 * w / max(1, len(X))))
