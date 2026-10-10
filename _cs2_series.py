"""CS2 Maps 1+2 priced the way HE reads it: by SERIES STATE, with head-to-head and assists.

    python _cs2_series.py test                    # walk-forward bias and calibration
    python _cs2_series.py price <player> <line> [kills|hs|assists] [--winp 0.55] [--opp "Team"]

Three things this adds over `_cs2_model.py`:

1. **Series state, not per-map win.** A Maps 1+2 line resolves on how the SERIES went, and the
   three states are far apart (34,365 player-series):

       lost both  24.6 kills   0.581 per round
       split 1-1  29.1 kills   0.664
       won both   31.6 kills   0.745

   The old model averaged two independent map coin flips, which smears that 7-kill spread into
   one number. Here the state is drawn first -- P(2-0)=p^2, P(1-1)=2p(1-p), P(0-2)=(1-p)^2 --
   and rounds come from the empirical distribution FOR THAT STATE, because a 2-0 is short and a
   1-1 is long. Drawing them together is the same fix that took Valorant's bias from +3.7 to -0.03.

2. **Head-to-head.** He used it as a main filter. It is included but shrunk hard: a player faces
   a given team 2-6 times, and that is exactly where a real-looking number is noise. The weight
   is capped, and `price` prints the sample so it can never be mistaken for a fact.

3. **Assists.** Present in the history since the first pull, never priced until now.
"""
import json, sys, math, random, collections

F = "cs2_maps.jsonl"
F_EXTRA = ("cs2_maps_old.jsonl",)   # the older pull -- 84MB of it. Missing this ran the model on a QUARTER of the history.
MIN_ROUNDS = 13
K_PLAYER = 400.0        # pseudo-rounds shrinking a player toward the league
K_H2H = 300.0           # pseudo-rounds shrinking head-to-head toward his own rate -- deliberately heavy
# MEASURED on 6,000 held-out series, Maps 1+2 totals. The old model used 1.10, which was the
# spread of a SINGLE map -- over two maps the outcomes are correlated through the series result,
# so the real spread is more than double. Using 1.10 made the model overconfident: it said 70%
# where the truth was 62%.
PHI = {"kills": 2.44, "hs": 1.89, "assists": 1.59}
# Measured bias on held-out series: the model runs slightly HIGH on kills and assists, and half
# a kill is enough to flip a marginal line from under to over -- which is exactly what it did on
# the 2026-09-22 board (old model nearly all unders, this one nearly all overs). Subtract it.
# Measured on the full 100k-series history, fitting on one held-out half and verifying on the
# other. The bias DRIFTS between slices (+0.65 to +0.91 on kills), so correcting by the larger
# figure overshoots to -0.20. These are the midpoints; the residual either way is under 0.2 of a
# kill, which is nothing beside a 6.2-kill typical miss. Do not chase this number.
BIAS = {"kills": 0.75, "hs": 0.35, "assists": 0.0}
random.seed(13)


def load():
    """Both history files, deduped on (game, player) -- the same sources the live model uses."""
    import os
    rows, seen = [], set()
    for fn in (F,) + F_EXTRA:
        if not os.path.exists(fn):
            continue
        for l in open(fn, encoding="utf-8"):
            r = json.loads(l)
            k = (r.get("game_id"), r.get("player"))
            if k in seen:
                continue
            seen.add(k)
            if r.get("kills") is None or (r.get("rounds") or 0) < MIN_ROUNDS:
                continue
            rows.append(r)
    rows.sort(key=lambda r: (r["date"], r["match"], r.get("map_no") or 0))
    return rows


def series_rows(rows):
    """One row per player-series: the first two maps only."""
    by = collections.defaultdict(list)
    for r in rows:
        by[(r["player"], r["match"])].append(r)
    out = []
    for (pid, match), ms in by.items():
        ms.sort(key=lambda x: x.get("map_no") or 0)
        if len(ms) < 2:
            continue
        m = ms[:2]
        out.append(dict(player=pid, match=match, date=m[0]["date"], team=m[0]["team"],
                        tier=m[0].get("tier"),
                        opp=m[0]["opp"], state=sum(x["win"] for x in m),
                        rounds=sum(x["rounds"] for x in m),
                        kills=sum(x["kills"] for x in m),
                        hs=sum((x["hs"] or 0) for x in m),
                        assists=sum((x["assists"] or 0) for x in m)))
    out.sort(key=lambda r: r["date"])
    return out


class State:
    """Everything the pricer needs, built only from series that already happened."""

    def __init__(self, srows):
        self.lg = {}
        tot = collections.Counter()
        for r in srows:
            tot["k"] += r["kills"]; tot["hs"] += r["hs"]; tot["a"] += r["assists"]; tot["rd"] += r["rounds"]
        self.lg_k = tot["k"] / tot["rd"]
        self.lg_hs = tot["hs"] / max(1, tot["k"])          # headshots per kill
        self.lg_a = tot["a"] / tot["rd"]
        # per-state: kills per round relative to league, and the rounds distribution
        self.state_mult = {}
        self.rounds = collections.defaultdict(list)
        for st in (0, 1, 2):
            s = [r for r in srows if r["state"] == st]
            if not s:
                continue
            k = sum(r["kills"] for r in s); rd = sum(r["rounds"] for r in s)
            self.state_mult[st] = (k / rd) / self.lg_k
            self.rounds[st] = [r["rounds"] for r in s]
            if len(self.rounds[st]) > 600:
                self.rounds[st] = random.sample(self.rounds[st], 600)
        # player rates
        # Kill rate by EVENT TIER. Shrinking a thin player toward the global league rate pulls a
        # tier-b player toward tier-s numbers and produced 29-kill projections against 21.5 lines
        # in a lower-tier match. Same lesson as Dota: anchor to the right peer group.
        tk = collections.Counter(); trd = collections.Counter()
        for r in srows:
            tk[r.get("tier")] += r["kills"]; trd[r.get("tier")] += r["rounds"]
        self.tier_k = {t: tk[t] / trd[t] for t in trd if trd[t] > 20000}
        self.player_tier = {}
        pk = collections.Counter(); prd = collections.Counter()
        phs = collections.Counter(); pa = collections.Counter()
        h2h = collections.defaultdict(lambda: [0, 0])
        for r in srows:
            self.player_tier[r["player"]] = r.get("tier")
            pk[r["player"]] += r["kills"]; prd[r["player"]] += r["rounds"]
            phs[r["player"]] += r["hs"]; pa[r["player"]] += r["assists"]
            e = h2h[(r["player"], r["opp"])]
            e[0] += r["kills"]; e[1] += r["rounds"]
        self.kpr = {p: (pk[p] + K_PLAYER * self.tier_k.get(self.player_tier.get(p), self.lg_k))
                       / (prd[p] + K_PLAYER) for p in prd}
        self.hspk = {p: (phs[p] + 60 * self.lg_hs) / (pk[p] + 60) for p in pk}
        self.apr = {p: (pa[p] + K_PLAYER * self.lg_a) / (prd[p] + K_PLAYER) for p in prd}
        self.h2h = dict(h2h)
        self.maps = len(srows)

    def h2h_rate(self, player, opp):
        """His rate against THIS opponent, shrunk hard toward his own overall rate."""
        base = self.kpr.get(player, self.lg_k)
        e = self.h2h.get((player, opp))
        if not e or e[1] < 26:                 # under two series of history: no signal
            return base, 0
        rate = (e[0] + K_H2H * base) / (e[1] + K_H2H)
        return rate, e[1]

    def mean(self, player, winp, kind="kills", opp=None):
        """Expected total over maps 1+2, integrating over the three series states."""
        base, h2h_n = self.h2h_rate(player, opp) if opp else (self.kpr.get(player, self.lg_k), 0)
        probs = {2: winp * winp, 1: 2 * winp * (1 - winp), 0: (1 - winp) ** 2}
        mu = 0.0
        for st, p in probs.items():
            rds = self.rounds.get(st) or [45]
            avg_rounds = sum(rds) / len(rds)
            mu += p * base * self.state_mult.get(st, 1.0) * avg_rounds
        if kind == "hs":
            mu *= self.hspk.get(player, self.lg_hs)
        elif kind == "assists":
            mu *= (self.apr.get(player, self.lg_a) / max(1e-9, self.kpr.get(player, self.lg_k)))
        return max(0.0, mu - BIAS.get(kind, 0.0)), h2h_n


def over(mu, line, phi=2.44):
    """P(total > line). Negative binomial when the spread is wider than Poisson."""
    k = int(math.floor(line))
    if phi <= 1.0001:
        term = math.exp(-mu); cum = term
        for i in range(1, k + 1):
            term *= mu / i; cum += term
        return max(0.0, 1 - cum)
    r = mu / (phi - 1.0); p = 1.0 / phi
    term = p ** r; cum = term
    for i in range(1, k + 1):
        term *= (r + i - 1) / i * (1 - p); cum += term
    return max(0.0, min(1.0, 1 - cum))


def elo_winp(srows):
    """Map win probability per series from a simple Elo on series results."""
    elo = collections.defaultdict(lambda: 1500.0)
    out = {}
    seen = set()
    for r in srows:
        key = (r["match"], r["team"])
        if key in seen:
            continue
        seen.add(key)
        a, b = r["team"], r["opp"]
        ea = 1 / (1 + 10 ** ((elo[b] - elo[a]) / 400))
        out[(r["match"], r["team"])] = ea
        s = r["state"] / 2.0
        elo[a] += 20 * (s - ea); elo[b] += 20 * ((1 - s) - (1 - ea))
    return out


def test(sample=4000):
    rows = load()
    sr = series_rows(rows)
    cut = int(len(sr) * 0.75)
    S = State(sr[:cut])
    wp = elo_winp(sr[:cut])
    later = sr[cut:]
    if len(later) > sample:
        later = random.sample(later, sample)
    print("walk-forward on %d player-series (trained on %d)\n" % (len(later), cut))
    for kind, field in (("kills", "kills"), ("hs", "hs"), ("assists", "assists")):
        errs = []; preds = []; acts = []
        buckets = collections.defaultdict(lambda: [0, 0])
        for r in later:
            p = wp.get((r["match"], r["team"]), 0.5)
            mu, n = S.mean(r["player"], p, kind, r["opp"])
            if mu <= 0:
                continue
            a = r[field]
            errs.append(mu - a); preds.append(mu); acts.append(a)
            for off in (-3, 0, 3):
                line = round(mu + off) - 0.5
                if line <= 0:
                    continue
                pr = over(mu, line, PHI[kind])
                b = round(pr * 10) / 10
                buckets[b][0] += 1
                buckets[b][1] += 1 if a > line else 0
        if not errs:
            continue
        n = len(errs)
        print("%-8s n=%d   model %.2f   actual %.2f   bias %+.2f   average miss %.2f" %
              (kind, n, sum(preds) / n, sum(acts) / n, sum(errs) / n,
               sum(abs(e) for e in errs) / n))
        cal = [(b, c, w) for b, (c, w) in sorted(buckets.items()) if c >= 100]
        print("   we said / it happened:  " +
              "   ".join("%d%%/%d%%" % (round(100 * b), round(100 * w / c)) for b, c, w in cal))
    # how often does head-to-head even have a sample?
    have = sum(1 for r in later if S.h2h_rate(r["player"], r["opp"])[1] >= 26)
    print("\nhead-to-head had 26+ rounds of history on %d of %d series (%.0f%%)" %
          (have, len(later), 100 * have / len(later)))


def price(player, line, kind="kills", winp=0.5, opp=None):
    rows = load(); sr = series_rows(rows); S = State(sr)
    nicks = json.load(open("cs2_nicks.json", encoding="utf-8"))
    pid = next((int(k) for k, v in nicks.items()
                if (v.get("nick") or "").lower() == player.lower()), None)
    if pid is None:
        print("no player called", player); return
    mu, n = S.mean(pid, winp, kind, opp)
    po = over(mu, float(line), PHI.get(kind, 2.44))
    print("%s -- %s on maps 1+2, line %s   (team %d%% to win a map%s)" %
          (player, kind, line, round(100 * winp), ", vs %s" % opp if opp else ""))
    print("  model mean %.1f     over %.0f%%     under %.0f%%" % (mu, 100 * po, 100 * (1 - po)))
    if opp:
        print("  head-to-head sample: %d rounds%s" % (n, " (too thin to move it)" if n < 26 else ""))
    print("  series states: 2-0 %.0f%%   1-1 %.0f%%   0-2 %.0f%%" %
          (100 * winp * winp, 100 * 2 * winp * (1 - winp), 100 * (1 - winp) ** 2))


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] == "test":
        test()
    elif a[0] == "price":
        wp = float(a[a.index("--winp") + 1]) if "--winp" in a else 0.5
        opp = a[a.index("--opp") + 1] if "--opp" in a else None
        kind = a[3] if len(a) > 3 and not a[3].startswith("--") else "kills"
        price(a[1], a[2], kind, wp, opp)
    else:
        print(__doc__)
