"""Valorant priced by SERIES STATE, with assists and (once the v2 pull lands) headshots.

    python _val_series.py test                      # walk-forward bias and calibration
    python _val_series.py price <player> <line> [kills|assists|hs] [--winp .55] [--maps 2] [--agent viper]

Mirrors `_cs2_series.py`. The three series states are just as far apart in Valorant as in CS2
(37,563 player-series, maps 1+2):

    lost both  25.2 kills   0.612 per round    9.5 assists
    split 1-1  29.9 kills   0.696              11.6
    won both   32.2 kills   0.781              12.6

Map 1 is priced too (`--maps 1`), since he bets both.

The agent term follows his rule: **his own record on that agent leads**, and the role average
only fills in when the sample is thin -- "he can drop 30 on omen, bc hes good asf". Spread is
measured per stat rather than assumed, which is what the old Valorant model got wrong and what
the CS2 model still gets wrong live.
"""
import json, sys, math, random, collections

F = "val_maps.jsonl"
F2 = "val_maps2.jsonl"          # v2 pull: adds hsp / fb / fd / adr
MIN_ROUNDS = 13
K_PLAYER = 400.0
K_AGENT = 150.0
K_H2H = 300.0
random.seed(17)


def load():
    import os
    path = F2 if os.path.exists(F2) and os.path.getsize(F2) > 5_000_000 else F
    rows = []
    for l in open(path, encoding="utf-8"):
        r = json.loads(l)
        if r.get("pid") and r.get("kills") is not None and (r.get("rounds") or 0) >= MIN_ROUNDS:
            rows.append(r)
    rows.sort(key=lambda r: (r["date"], r["match"], r["game_id"]))
    return rows, path


def series_rows(rows, maps=2):
    by = collections.defaultdict(list)
    for r in rows:
        by[(r["pid"], r["match"])].append(r)
    out = []
    for (pid, match), ms in by.items():
        ms.sort(key=lambda x: x["game_id"])
        if len(ms) < maps:
            continue
        m = ms[:maps]
        hs = None
        if all(x.get("hsp") is not None for x in m):
            hs = sum(round(x["kills"] * x["hsp"] / 100.0) for x in m)
        out.append(dict(player=pid, match=match, date=m[0]["date"], team=m[0]["team"],
                        opp=m[0]["opp"], agent=m[0]["agent"], role=m[0].get("role"),
                        state=sum(x["win"] for x in m),
                        rounds=sum(x["rounds"] for x in m),
                        kills=sum(x["kills"] for x in m),
                        assists=sum((x["assists"] or 0) for x in m),
                        hs=hs))
    out.sort(key=lambda r: r["date"])
    return out


class State:
    def __init__(self, srows, maps=2):
        self.maps = maps
        tot = collections.Counter()
        for r in srows:
            tot["k"] += r["kills"]; tot["a"] += r["assists"]; tot["rd"] += r["rounds"]
        self.lg_k = tot["k"] / tot["rd"]
        self.lg_a = tot["a"] / tot["rd"]
        self.state_mult, self.rounds = {}, collections.defaultdict(list)
        for st in range(maps + 1):
            s = [r for r in srows if r["state"] == st]
            if not s:
                continue
            k = sum(r["kills"] for r in s); rd = sum(r["rounds"] for r in s)
            self.state_mult[st] = (k / rd) / self.lg_k
            pool = [r["rounds"] for r in s]
            self.rounds[st] = random.sample(pool, 600) if len(pool) > 600 else pool
        pk = collections.Counter(); prd = collections.Counter(); pa = collections.Counter()
        phs = collections.Counter()      # headshots (from hsp% x kills), for the hs line
        ak = collections.Counter(); ard = collections.Counter()      # per player+agent
        rk = collections.Counter(); rrd = collections.Counter()      # per role
        h2h = collections.defaultdict(lambda: [0, 0])
        for r in srows:
            pk[r["player"]] += r["kills"]; prd[r["player"]] += r["rounds"]; pa[r["player"]] += r["assists"]
            if r.get("hs") is not None:
                phs[r["player"]] += r["hs"]
            ak[(r["player"], r["agent"])] += r["kills"]; ard[(r["player"], r["agent"])] += r["rounds"]
            if r.get("role"):
                rk[r["role"]] += r["kills"]; rrd[r["role"]] += r["rounds"]
            e = h2h[(r["player"], r["opp"])]; e[0] += r["kills"]; e[1] += r["rounds"]
        self.kpr = {p: (pk[p] + K_PLAYER * self.lg_k) / (prd[p] + K_PLAYER) for p in prd}
        self.apr = {p: (pa[p] + K_PLAYER * self.lg_a) / (prd[p] + K_PLAYER) for p in prd}
        self.role_kpr = {ro: rk[ro] / rrd[ro] for ro in rrd if rrd[ro] > 2000}
        tot_hs = sum(phs.values()); tot_k_hs = sum(pk[p] for p in phs)
        self.lg_hspk = (tot_hs / tot_k_hs) if tot_k_hs else 0.30
        # headshots per kill, shrunk 60 pseudo-kills toward the league -- the same guard CS2 uses
        self.hspk = {p: (phs[p] + 60 * self.lg_hspk) / (pk[p] + 60) for p in phs}
        self.ak, self.ard = ak, ard
        self.h2h = dict(h2h)

    def agent_rate(self, player, agent):
        """His own record on this agent leads; the role rate only fills a thin sample."""
        base = self.kpr.get(player, self.lg_k)
        k, rd = self.ak.get((player, agent), 0), self.ard.get((player, agent), 0)
        if rd < 60:
            return base, rd
        return (k + K_AGENT * base) / (rd + K_AGENT), rd

    def h2h_rate(self, player, opp, base):
        e = self.h2h.get((player, opp))
        if not e or e[1] < 40:
            return base, 0
        return (e[0] + K_H2H * base) / (e[1] + K_H2H), e[1]

    def mean(self, player, winp, kind="kills", agent=None, opp=None):
        base, an = self.agent_rate(player, agent) if agent else (self.kpr.get(player, self.lg_k), 0)
        if opp:
            base, _ = self.h2h_rate(player, opp, base)
        n = self.maps
        probs = {st: math.comb(n, st) * winp ** st * (1 - winp) ** (n - st) for st in range(n + 1)}
        mu = 0.0
        for st, p in probs.items():
            rds = self.rounds.get(st) or [21 * n]
            mu += p * base * self.state_mult.get(st, 1.0) * (sum(rds) / len(rds))
        if kind == "assists":
            mu *= self.apr.get(player, self.lg_a) / max(1e-9, self.kpr.get(player, self.lg_k))
        elif kind == "hs":
            mu *= self.hspk.get(player, self.lg_hspk)
        return mu, an


def over(mu, line, phi):
    k = int(math.floor(line))
    if phi <= 1.0001:
        t = math.exp(-mu); c = t
        for i in range(1, k + 1):
            t *= mu / i; c += t
        return max(0.0, 1 - c)
    r = mu / (phi - 1.0); p = 1.0 / phi
    t = p ** r; c = t
    for i in range(1, k + 1):
        t *= (r + i - 1) / i * (1 - p); c += t
    return max(0.0, min(1.0, 1 - c))


def elo(srows, maps=2):
    e = collections.defaultdict(lambda: 1500.0); out = {}; seen = set()
    for r in srows:
        key = (r["match"], r["team"])
        if key in seen:
            continue
        seen.add(key)
        a, b = r["team"], r["opp"]
        ea = 1 / (1 + 10 ** ((e[b] - e[a]) / 400))
        out[key] = ea
        s = r["state"] / maps
        e[a] += 20 * (s - ea); e[b] += 20 * ((1 - s) - (1 - ea))
    return out


def measure_phi(S, later, wp, kind, field):
    mus, acts = [], []
    for r in later:
        v = r.get(field)
        if v is None:
            continue
        mu, _ = S.mean(r["player"], wp.get((r["match"], r["team"]), 0.5), kind, r["agent"], r["opp"])
        if mu > 0:
            mus.append(mu); acts.append(v)
    if len(mus) < 200:
        return None, 0
    mean = sum(mus) / len(mus)
    var = sum((a - m) ** 2 for a, m in zip(acts, mus)) / len(mus)
    return var / mean, len(mus)


def test(maps=2, sample=4000):
    rows, path = load()
    sr = series_rows(rows, maps)
    cut = int(len(sr) * 0.75)
    S = State(sr[:cut], maps); wp = elo(sr[:cut], maps)
    later = sr[cut:]
    if len(later) > sample:
        later = random.sample(later, sample)
    print("source %s | maps 1..%d | walk-forward on %d series (trained on %d)\n" % (path, maps, len(later), cut))
    for kind, field in (("kills", "kills"), ("assists", "assists"), ("hs", "hs")):
        phi, n = measure_phi(S, later, wp, kind, field)
        if phi is None:
            print("%-8s no data yet (needs the v2 pull for headshots)" % kind); continue
        errs, buckets = [], collections.defaultdict(lambda: [0, 0])
        preds = []; acts = []
        for r in later:
            v = r.get(field)
            if v is None:
                continue
            mu, _ = S.mean(r["player"], wp.get((r["match"], r["team"]), 0.5), kind, r["agent"], r["opp"])
            if mu <= 0:
                continue
            errs.append(mu - v); preds.append(mu); acts.append(v)
            for off in (-3, 0, 3):
                line = round(mu + off) - 0.5
                if line <= 0:
                    continue
                b = round(over(mu, line, phi) * 10) / 10
                buckets[b][0] += 1; buckets[b][1] += 1 if v > line else 0
        m = len(errs)
        print("%-8s n=%d  model %.2f  actual %.2f  bias %+.2f  miss %.2f  spread %.2fx" %
              (kind, m, sum(preds) / m, sum(acts) / m, sum(errs) / m,
               sum(abs(e) for e in errs) / m, phi))
        cal = [(b, c, w) for b, (c, w) in sorted(buckets.items()) if c >= 100]
        print("   said/happened:  " + "   ".join("%d%%/%d%%" % (round(100 * b), round(100 * w / c))
                                                  for b, c, w in cal))


if __name__ == "__main__":
    a = sys.argv[1:]
    maps = int(a[a.index("--maps") + 1]) if "--maps" in a else 2
    if not a or a[0] == "test":
        test(maps)
    else:
        print(__doc__)
