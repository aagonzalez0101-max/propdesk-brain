"""Esports Elo off bo3.gg (free, no key) -- replaces the stale lol_rows.json.

  python _esports_elo.py fetch 60      # pull 60 pages (100 matches each) into esports_matches.json
  python _esports_elo.py test          # walk-forward Elo accuracy by discipline

bo3.gg: api.bo3.gg/api/v1/matches?sort=-start_date&page=N&limit=100
Fields used: team1_id, team2_id, winner_team_id, start_date, tier, bo_type, slug.
Discipline is inferred from the slug (cs-go/cs2, lol, dota, valorant, rainbow-six...).
"""
import json, sys, os, urllib.request, io, math, collections

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
UA = "Mozilla/5.0 Chrome/124"
F = "esports_matches.json"
g = lambda u: json.loads(urllib.request.urlopen(
    urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "application/json"}), timeout=30).read())


def disc(slug):
    s = (slug or "").lower()
    for k, v in (("cs-go", "cs"), ("cs2", "cs"), ("counter-strike", "cs"), ("-lol-", "lol"),
                 ("league-of-legends", "lol"), ("dota", "dota"), ("valorant", "val"),
                 ("rainbow", "r6"), ("mobile-legends", "mlbb"), ("pubg", "pubg"),
                 ("rocket-league", "rl"), ("overwatch", "ow"), ("king-of-glory", "hok")):
        if k in s:
            return v
    return "other"


def fetch(pages=60, start_offset=None):
    out = json.load(open(F, encoding="utf-8")) if os.path.exists(F) else {}
    total = g("https://api.bo3.gg/api/v1/matches?page[offset]=0&page[limit]=1")["total"]["count"]
    # the feed is oldest-first, so the newest matches live at the END of the range
    off0 = start_offset if start_offset is not None else max(0, total - pages * 100)
    for i in range(pages):
        off = off0 + i * 100
        if off >= total:
            break
        try:
            d = g(f"https://api.bo3.gg/api/v1/matches?page[offset]={off}&page[limit]=100")
        except Exception as e:
            print("page", p, "fail", e)
            break
        for m in d.get("results", []):
            if m.get("status") != "finished" or not m.get("winner_team_id"):
                continue
            out[str(m["id"])] = dict(t1=m["team1_id"], t2=m["team2_id"], w=m["winner_team_id"],
                                     d=m["start_date"][:10], tier=m.get("tier"), bo=m.get("bo_type"),
                                     disc=disc(m.get("slug")))
        if i % 20 == 0:
            print(f"  offset {off}: {len(out)} matches kept", flush=True)
    json.dump(out, open(F, "w"))
    print("saved", len(out), "matches to", F)


def glicko(base=1500, rd0=350, minseen=8, c=6.0, rows=None):
    """Glicko-1 style rating (rating + RD). MEASURED 2026-09-15 on 13,019 bo3.gg
    matches: 63.1% accuracy / 0.6459 logloss, vs Elo's best 60.9% / 0.6568.
    Matches the published Glicko-2 result on CS:GO (63.1%). Use this, not Elo."""
    import collections, math
    rows = rows if rows is not None else sorted(
        json.load(open(F, encoding="utf-8")).values(), key=lambda r: r["d"])
    q = math.log(10) / 400
    R = collections.defaultdict(lambda: base)
    RD = collections.defaultdict(lambda: rd0)
    seen = collections.Counter()
    n = hit = 0
    ll = 0.0
    for m in rows:
        a, b, w = m["t1"], m["t2"], m["w"]
        if not a or not b:
            continue
        gf = lambda rd: 1 / math.sqrt(1 + 3 * q * q * rd * rd / (math.pi ** 2))
        ga, gb = gf(RD[b]), gf(RD[a])
        p = 1 / (1 + 10 ** (-ga * (R[a] - R[b]) / 400))
        if seen[a] >= minseen and seen[b] >= minseen:
            n += 1
            hit += (p >= .5) == (w == a)
            ll -= math.log(max(1e-9, p if w == a else 1 - p))
        for x, gx, px, res in ((a, ga, p, 1.0 if w == a else 0.0),
                               (b, gb, 1 - p, 1.0 if w == b else 0.0)):
            d2 = 1 / (q * q * gx * gx * px * (1 - px)) if 0 < px < 1 else 1e6
            den = 1 / (RD[x] ** 2) + 1 / d2
            R[x] += (q / den) * gx * (res - px)
            RD[x] = max(30, math.sqrt(1 / den))
        for t in (a, b):
            RD[t] = min(rd0, math.sqrt(RD[t] ** 2 + c * c))
        seen[a] += 1
        seen[b] += 1
    return R, RD, (n, hit / n if n else 0, ll / n if n else 0)


def test(k=24, base=1500):
    rows = sorted(json.load(open(F, encoding="utf-8")).values(), key=lambda r: r["d"])
    by = collections.defaultdict(list)
    for r in rows:
        by[r["disc"]].append(r)
    print(f"{'disc':6s} {'n':>6} {'graded':>7} {'acc':>7} {'logloss':>8}  (Elo walk-forward, k=%d)" % k)
    for d, lst in sorted(by.items(), key=lambda kv: -len(kv[1])):
        if len(lst) < 300:
            continue
        R = collections.defaultdict(lambda: base)
        seen = collections.Counter()
        n = hit = 0
        ll = 0.0
        for m in lst:
            a, b, w = m["t1"], m["t2"], m["w"]
            if not a or not b:
                continue
            p = 1 / (1 + 10 ** ((R[b] - R[a]) / 400))
            if seen[a] >= 8 and seen[b] >= 8:        # only grade once both teams are rated
                n += 1
                hit += (p >= 0.5) == (w == a)
                ll -= math.log(max(1e-9, p if w == a else 1 - p))
            s = 1.0 if w == a else 0.0
            R[a] += k * (s - p)
            R[b] += k * ((1 - s) - (1 - p))
            seen[a] += 1
            seen[b] += 1
        if n:
            print(f"{d:6s} {len(lst):6d} {n:7d} {hit/n:7.1%} {ll/n:8.3f}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "test"
    if cmd == "fetch":
        fetch(int(sys.argv[2]) if len(sys.argv) > 2 else 60)
    elif cmd == "glicko":
        R, RD, (n, acc, ll) = glicko()
        print(f"Glicko: n={n}  acc {acc:.1%}  logloss {ll:.4f}")
        top = sorted(R.items(), key=lambda kv: -kv[1])[:15]
        print("top rated team ids:", [(t, round(r), round(RD[t])) for t, r in top])
    else:
        test()
