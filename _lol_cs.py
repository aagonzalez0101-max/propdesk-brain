"""Does LoL creep score have the structure kills lack? -> lol_cs.jsonl

    python _lol_cs.py [target_rows]

Kills died the ceiling test: knowing the exact game length in advance moved the spread from
2.16x to 2.16x, because kills are allocated by which teamfights happen. CS is the opposite
shape -- farm rate x minutes, a countable opportunity unit, the same thing that makes Valorant
rounds tractable. This measures whether that holds.

Writes every page as it goes, because the first attempt died on a timeout after 2,500 rows and
lost all of them.
"""
import json, os, sys, time, math, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from betting import lol as L

OUT = "lol_cs.jsonl"
F = ("Link=player,Team=team,Role=role,Kills=k,Deaths=d,Assists=a,CS=cs,Gold=gold,"
     "DateTime_UTC=dt,GameId=gid")


def pull(target=4500, start="2026-05-01 00:00:00"):
    have, cur = set(), start
    if os.path.exists(OUT):
        for l in open(OUT, encoding="utf-8"):
            try:
                r = json.loads(l); have.add((r.get("player"), r.get("gid")))
                if r.get("dt", "") > cur:
                    cur = r["dt"]
            except Exception:
                pass
        print("resuming from %s with %d rows" % (cur, len(have)), flush=True)
    f = open(OUT, "a", encoding="utf-8")
    empty = 0
    while len(have) < target:
        try:
            b = L._cargo("ScoreboardPlayers", F,
                         where='ScoreboardPlayers.DateTime_UTC >= "%s"' % cur,
                         order="ScoreboardPlayers.DateTime_UTC ASC", limit=500)
        except L.RateLimited:
            print("  throttled, waiting 60s", flush=True); time.sleep(60); continue
        if not b:
            empty += 1
            if empty >= 2:
                break
            time.sleep(4); continue
        empty = 0
        for r in b:
            key = (r.get("player"), r.get("gid"))
            if key not in have:
                have.add(key); f.write(json.dumps(r) + "\n")
        f.flush()
        last = b[-1].get("dt")
        print("  ..%s  %d rows" % (last, len(have)), flush=True)
        if last == cur:
            t = time.strptime(last, "%Y-%m-%d %H:%M:%S")
            cur = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.mktime(t) + 60))
        else:
            cur = last
    f.close()
    print("have %d rows" % len(have))


def conf(mean, phi):
    return 0.10 * math.sqrt(mean / phi) if phi > 0 else 0


def test():
    cl = []
    for l in open(OUT, encoding="utf-8"):
        r = json.loads(l)
        if not r.get("cs"):
            continue
        try:
            cl.append(dict(player=r["player"], role=r["role"], dt=r["dt"], cs=float(r["cs"]),
                           k=float(r["k"]), gold=float(r["gold"]) if r.get("gold") else 0.0))
        except Exception:
            pass
    cl.sort(key=lambda r: r["dt"])
    print("%d player-games with creep score\n" % len(cl))
    print("creep score by role:")
    byr = collections.defaultdict(list)
    for r in cl:
        byr[r["role"]].append(r["cs"])
    for ro, v in sorted(byr.items(), key=lambda x: -sum(x[1]) / len(x[1])):
        m = sum(v) / len(v); var = sum((x - m) ** 2 for x in v) / len(v)
        print("   %-8s %6.1f CS   raw spread %6.2fx   (%d games)" % (ro, m, var / m if m else 0, len(v)))
    cut = int(len(cl) * 0.75); tr, later = cl[:cut], cl[cut:]
    K = 8.0
    print("\nwalk-forward (player shrunk toward his role):")
    for stat in ("cs", "gold", "k"):
        pk = collections.Counter(); pn = collections.Counter()
        rk = collections.Counter(); rn = collections.Counter()
        for r in tr:
            pk[r["player"]] += r[stat]; pn[r["player"]] += 1
            rk[r["role"]] += r[stat]; rn[r["role"]] += 1
        role_m = {ro: rk[ro] / rn[ro] for ro in rn}
        lg = sum(pk.values()) / max(1, sum(pn.values()))
        mus, acts = [], []
        for r in later:
            m = (pk[r["player"]] + K * role_m.get(r["role"], lg)) / (pn[r["player"]] + K)
            if m > 0:
                mus.append(m); acts.append(r[stat])
        if not mus:
            continue
        n = len(mus); mean = sum(mus) / n
        var = sum((a - m) ** 2 for a, m in zip(acts, mus)) / n
        phi = var / mean
        label = {"cs": "CREEP SCORE", "gold": "GOLD", "k": "kills (control)"}[stat]
        print("  %-18s number %8.1f  spread %7.2fx  confidence %.2f" % (label, mean, phi, conf(mean, phi)))
    print("\n  bar is 0.20.  Valorant kills 0.38.  LoL map-1 kills 0.12.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        test()
    else:
        pull(int(sys.argv[1]) if len(sys.argv) > 1 else 4500)
        test()
