"""CS2 kill-prop model, walk-forward. Built 2026-09-16 on bo3.gg per-map stats.

    python _cs2_model.py test          # walk-forward calibration vs a naive baseline
    python _cs2_model.py price <player> <team> <opp> <line> [maps]   # P(over) for a live line

MODEL (every piece measured in cs2_maps.jsonl, see feedback_esports_props_only.md):
  1. player KPR, shrunk toward the league mean with K pseudo-rounds (HLTV: 30 maps ~ real)
  2. win / loss multiplier on KPR (measured: win 0.740 vs loss 0.582 per round)
  3. team map-win probability from an Elo on MAP results
  4. (rounds, won) drawn from the EMPIRICAL joint distribution of maps whose pre-map win
     probability was similar -- this carries the blowout / overtime tails the cappers talk about
  5. kills | rounds, won ~ Poisson (measured variance/mean 1.10 -> Poisson is close enough)
  P(over line) = average over the empirical (rounds, won) draws of the Poisson tail.
Only information dated BEFORE each map is used when it is predicted.
"""
import json, sys, math, collections, bisect

F = "cs2_maps.jsonl"
F_EXTRA = ("cs2_maps_old.jsonl",)   # older pages pulled in parallel
K_ROUNDS = 400          # shrinkage: pseudo-rounds of league-average KPR (~18 maps)
ELO_K, ELO_BASE = 24, 1500
MARGIN_MULT = True      # v4: KPR multiplier by (won, map length) -- blowout winner 0.93 vs loser 0.41
DECAY = 1.0            # v3: per-player recency decay per map played (1.0 = none)
D_ROUNDS = 6000        # tuned 2026-09-17 walk-forward: 100 worse, 400<1500<6000 best (light touch)
BUCKETS = (0.0, 0.35, 0.45, 0.55, 0.65, 1.01)   # pre-map win prob bins for the rounds draw


def load():
    import os
    rows = []
    seen = set()
    for fn in (F,) + F_EXTRA:
        if os.path.exists(fn):
            for l in open(fn, encoding="utf-8"):
                r = json.loads(l)
                k = (r["game_id"], r["player"])
                if k not in seen:
                    seen.add(k)
                    rows.append(r)
    rows = [r for r in rows if r["rounds"] and r["rounds"] >= 13 and r["win"] in (0, 1) and r["kills"] is not None]
    maps = collections.defaultdict(list)
    for r in rows:
        maps[r["game_id"]].append(r)
    out = []
    for gid, ps in maps.items():
        teams = collections.defaultdict(list)
        for p in ps:
            teams[p["team"]].append(p)
        if len(teams) != 2 or any(len(v) != 5 for v in teams.values()):
            continue
        out.append((ps[0]["date"], ps[0]["match"], ps[0]["map_no"], gid, dict(teams)))
    out.sort()
    return out


def poisson_over(mu, line):
    """P(X > line) for Poisson(mu), line like 14.5."""
    k = int(math.floor(line))
    term = math.exp(-mu)
    cdf = term
    for i in range(1, k + 1):
        term *= mu / i
        cdf += term
    return max(0.0, 1.0 - cdf)


class State:
    def __init__(self):
        self.elo = collections.defaultdict(lambda: ELO_BASE)
        self.pk = collections.Counter()      # player kills
        self.pr = collections.Counter()      # player rounds
        self.pmaps = collections.Counter()
        self.lg_k = 0
        self.lg_r = 0
        self.lg_kw = self.lg_rw = self.lg_kl = self.lg_rl = 0
        self.draws = {i: [] for i in range(len(BUCKETS) - 1)}   # (rounds, won) from favourite-or-not view
        # v2: opponent adjustment. D[team] = KPR the team ALLOWS / league KPR (shrunk).
        self.ak = collections.Counter()      # kills allowed (opponent player kills)
        self.ar = collections.Counter()      # opponent player-rounds
        self.padj = collections.Counter()    # player rounds weighted by opponent D at the time
        self.use_opp = True
        self.wr = collections.defaultdict(lambda: [0.0, 0.0])   # (won, rounds bucket) -> [kills, rounds]

    def bucket(self, p):
        return max(0, min(len(BUCKETS) - 2, bisect.bisect_right(BUCKETS, p) - 1))

    def winp(self, a, b):
        return 1 / (1 + 10 ** ((self.elo[b] - self.elo[a]) / 400))

    def D(self, team, k=None):
        k = D_ROUNDS if k is None else k
        lg = self.lg_k / self.lg_r if self.lg_r else 0.66
        return ((self.ak[team] + k * lg) / (self.ar[team] + k)) / lg

    def kpr(self, player, opp=None):
        lg = self.lg_k / self.lg_r if self.lg_r else 0.66
        if not self.use_opp:
            return (self.pk[player] + K_ROUNDS * lg) / (self.pr[player] + K_ROUNDS)
        skill = (self.pk[player] + K_ROUNDS * lg) / (self.padj[player] + K_ROUNDS)
        return skill * (self.D(opp) if opp is not None else 1.0)

    def mult(self):
        lg = self.lg_k / self.lg_r if self.lg_r else 0.66
        w = (self.lg_kw / self.lg_rw) / lg if self.lg_rw else 1.12
        l = (self.lg_kl / self.lg_rl) / lg if self.lg_rl else 0.88
        return w, l

    def mult_wr(self, won, rounds):
        """KPR multiplier for a (won, rounds) outcome, shrunk to the plain win/loss multiplier."""
        mw, ml = self.mult()
        base = mw if won else ml
        if not MARGIN_MULT:
            return base
        lg = self.lg_k / self.lg_r if self.lg_r else 0.66
        k, r = self.wr[(won, min(30, max(13, rounds)) // 3)]
        return (k / lg + 2000 * base) / (r + 2000)

    def dist(self, p_team_win):
        """Empirical (rounds, won) pairs for maps whose team had a similar pre-map win prob."""
        d = self.draws[self.bucket(p_team_win)]
        if len(d) < 60:                       # fall back to everything
            d = [x for v in self.draws.values() for x in v]
        if len(d) > 400:                      # evenly spaced subsample keeps it fast and deterministic
            step = len(d) / 400.0
            d = [d[int(i * step)] for i in range(400)]
        return d

    def p_over(self, player, team, opp, line, n_maps=1):
        p = self.winp(team, opp)
        base = self.kpr(player, opp)
        mw, ml = self.mult()
        d = self.dist(p)
        if not d:
            return None, None
        if n_maps == 1:
            tot = sum(poisson_over(base * self.mult_wr(w, r) * r, line) for r, w in d)
            mu = sum(base * self.mult_wr(w, r) * r for r, w in d) / len(d)
            return tot / len(d), mu
        # Maps 1+2: two independent draws; sample pairs deterministically
        n = len(d)
        acc = 0.0
        mu = 0.0
        step = max(1, n // 300)
        cnt = 0
        for i in range(0, n, step):
            r1, w1 = d[i]
            r2, w2 = d[(i * 7 + 13) % n]
            m = base * (self.mult_wr(w1, r1) * r1 + self.mult_wr(w2, r2) * r2)
            acc += poisson_over(m, line)
            mu += m
            cnt += 1
        return acc / cnt, mu / cnt

    def update(self, teams):
        (ta, pa), (tb, pb) = teams.items()
        wa = pa[0]["win"]
        p = self.winp(ta, tb)
        rounds = pa[0]["rounds"]
        self.draws[self.bucket(p)].append((rounds, wa))
        self.draws[self.bucket(1 - p)].append((rounds, 1 - wa))
        d = ELO_K * (wa - p)
        self.elo[ta] += d
        self.elo[tb] -= d
        Da, Db = self.D(ta), self.D(tb)
        for ps, dopp, opp in ((pa, Db, tb), (pb, Da, ta)):
            for r in ps:
                if DECAY < 1.0:
                    q = r["player"]
                    self.pk[q] *= DECAY; self.pr[q] *= DECAY; self.padj[q] *= DECAY
                self.padj[r["player"]] += r["rounds"] * dopp
                self.ak[opp] += r["kills"]
                self.ar[opp] += r["rounds"]
                self.pk[r["player"]] += r["kills"]
                self.pr[r["player"]] += r["rounds"]
                self.pmaps[r["player"]] += 1
                self.lg_k += r["kills"]
                self.lg_r += r["rounds"]
                wrb = self.wr[(r["win"], min(30, max(13, r["rounds"])) // 3)]
                wrb[0] += r["kills"]; wrb[1] += r["rounds"]
                if r["win"]:
                    self.lg_kw += r["kills"]; self.lg_rw += r["rounds"]
                else:
                    self.lg_kl += r["kills"]; self.lg_rl += r["rounds"]


def test(warm=800, min_maps=8, use_opp=True, k_rounds=None, d_rounds=None, decay=None, margin=None):
    global K_ROUNDS, D_ROUNDS, DECAY, MARGIN_MULT
    if decay: DECAY = decay
    if margin is not None: MARGIN_MULT = margin
    if k_rounds: K_ROUNDS = k_rounds
    if d_rounds: D_ROUNDS = d_rounds
    maps = load()
    S = State()
    S.use_opp = use_opp
    # baseline: player's own mean kills per map (shrunk the same way), Poisson around it
    rows = []
    for i, (date, match, mno, gid, teams) in enumerate(maps):
        if i >= warm:
            names = list(teams)
            for t, o in ((names[0], names[1]), (names[1], names[0])):
                for r in teams[t]:
                    if S.pmaps[r["player"]] < min_maps:
                        continue
                    lgk = S.lg_k / S.lg_r
                    base_mu = (S.pk[r["player"]] + K_ROUNDS * lgk) / (S.pr[r["player"]] + K_ROUNDS) * 21.9
                    line = math.floor(base_mu) + 0.5          # a line an app would plausibly post
                    pm, mu = S.p_over(r["player"], t, o, line)
                    pb = poisson_over(base_mu, line)
                    rows.append((pm, pb, r["kills"] > line, S.winp(t, o), mu, r["kills"]))
        S.update(teams)
    global LAST_ROWS
    LAST_ROWS = rows
    n = len(rows)
    ll = lambda p, y: -math.log(max(1e-9, p if y else 1 - p))
    bs = lambda k: sum((x[k] - x[2]) ** 2 for x in rows) / n
    print("maps %d | graded player-maps %d (after %d warm-up maps, players with %d+ maps)" % (len(maps), n, warm, min_maps))
    print("over hit rate at the naive line: %.1f%%" % (100 * sum(x[2] for x in rows) / n))
    print("Brier  model %.4f  baseline %.4f   (lower is better)" % (bs(0), bs(1)))
    print("LogLoss model %.4f  baseline %.4f" % (sum(ll(x[0], x[2]) for x in rows) / n, sum(ll(x[1], x[2]) for x in rows) / n))
    print("\ncalibration (model P(over) bucket -> actual)")
    cb = collections.defaultdict(list)
    for x in rows:
        cb[min(9, int(x[0] * 10))].append(x[2])
    for b in sorted(cb):
        v = cb[b]
        print("  %.1f-%.1f  n=%5d  actual %.1f%%" % (b / 10, (b + 1) / 10, len(v), 100 * sum(v) / len(v)))
    print("\nby pre-map team win prob (does the model's blowout logic hold?)")
    for lo, hi in ((0, .35), (.35, .5), (.5, .65), (.65, 1.01)):
        v = [x for x in rows if lo <= x[3] < hi]
        if v:
            print("  win %.2f-%.2f n=%5d  model P(over) %.1f%%  baseline %.1f%%  actual %.1f%%" % (
                lo, hi, len(v), 100 * sum(x[0] for x in v) / len(v), 100 * sum(x[1] for x in v) / len(v),
                100 * sum(x[2] for x in v) / len(v)))
    return S


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "test"
    if cmd == "test":
        test(use_opp="noopp" not in sys.argv)
