"""Valorant kill model -- kills per player over maps 1..n, built like the CS2 one.

    python _val_model.py test          # walk-forward bias and hit rate on real maps
    python _val_model.py price <player> <line> [--maps 2] [--winp 0.5]

The pieces, in the order they matter:

  1. ROUNDS.  The old Valorant attempt over-projected by 3.7 kills because it multiplied a kill
     rate by an assumed round count. Rounds are not a constant: a blowout is 15 rounds, a close
     map is 25, overtime more. So rounds are drawn EMPIRICALLY from maps whose pre-map win
     probability was similar, never from the mean.
  2. WIN/LOSS SPLIT. A player kills more on a map his team wins (league ~0.79 vs ~0.61 per
     round). Rounds and the split are correlated -- a blowout is few rounds AND a high rate for
     the winner -- so they are drawn together as a (rounds, won) pair, not independently.
  3. AGENT. Priced per agent where we know the pick, shrunk toward the player's own rate.
  4. OPPONENT. A light defensive adjustment: how many kills per round the opponent concedes.
  5. Kills are Poisson around that mean.

Everything is shrunk toward the league, so a thin sample never posts a fake edge.
"""
import json, sys, math, random, collections, bisect

PROF = "val_profiles.json"
MAPS = "val_maps.jsonl"
D_ROUNDS = 4000.0      # pseudo-rounds shrinking an opponent's defence toward neutral
MIN_ROUNDS = 13
random.seed(11)


def load_profiles():
    return json.load(open(PROF, encoding="utf-8"))


def load_maps():
    rows = []
    for l in open(MAPS, encoding="utf-8"):
        r = json.loads(l)
        if r.get("pid") and r.get("kills") is not None and (r.get("rounds") or 0) >= MIN_ROUNDS:
            rows.append(r)
    rows.sort(key=lambda r: (r["date"], r["match"], r["game_id"]))
    return rows


class State:
    """Elo on map results + the (rounds, won) draws + opponent defence, all built from history."""

    def __init__(self, rows):
        self.elo = collections.defaultdict(lambda: 1500.0)
        self.draws = collections.defaultdict(list)     # win-prob bucket -> [(rounds, won), ...]
        self.dk = collections.Counter(); self.dr = collections.Counter()
        self.lg = 0.0
        k, rd = 0, 0
        seen = set()
        for r in rows:
            k += r["kills"]; rd += r["rounds"]
            self.dk[r["opp"]] += r["kills"]; self.dr[r["opp"]] += r["rounds"]
            gid = r["game_id"]
            if gid in seen:
                continue
            seen.add(gid)
            a, b = r["team"], r["opp"]
            ea = 1 / (1 + 10 ** ((self.elo[b] - self.elo[a]) / 400))
            bucket = round(min(0.95, max(0.05, ea)), 1)
            self.draws[bucket].append((r["rounds"], r["win"]))
            s = 1.0 if r["win"] else 0.0
            self.elo[a] += 24 * (s - ea)
            self.elo[b] += 24 * ((1 - s) - (1 - ea))
        self.lg = k / rd
        # subsample so pricing stays fast
        for b in self.draws:
            if len(self.draws[b]) > 400:
                self.draws[b] = random.sample(self.draws[b], 400)

    def winp(self, team, opp):
        return 1 / (1 + 10 ** ((self.elo[opp] - self.elo[team]) / 400))

    def defence(self, opp):
        """>1 = concedes more kills per round than the league."""
        k, r = self.dk[opp], self.dr[opp]
        adj = (k + D_ROUNDS * self.lg) / (r + D_ROUNDS)
        return adj / self.lg

    def sample(self, winp, n=400):
        b = round(min(0.95, max(0.05, winp)), 1)
        pool = self.draws.get(b) or self.draws.get(round(min(0.9, max(0.1, winp)), 1)) or []
        if not pool:
            pool = [(21, 1), (21, 0)]
        return [pool[i % len(pool)] for i in range(n)] if len(pool) < n else random.sample(pool, n)


def mean_kills(prof, S, pid, opp_team, winp, maps=2, agent=None):
    """Expected kills over `maps` maps: integrate over the (rounds, won) distribution."""
    p = prof["players"].get(str(pid)) if isinstance(pid, int) else prof["players"].get(pid)
    if not p:
        return None
    base = p["kpr"]
    if agent and p.get("by_agent", {}).get(agent):
        base = p["by_agent"][agent]["kpr"]
    win_r = p.get("kpr_win") or base
    loss_r = p.get("kpr_loss") or base
    # keep the agent adjustment relative, applied to both sides of the split
    scale = base / p["kpr"] if p["kpr"] else 1.0
    d = S.defence(opp_team)
    tot = 0.0
    draws = S.sample(winp)
    for rounds, won in draws:
        rate = (win_r if won else loss_r) * scale * d
        tot += rate * rounds
    return maps * tot / len(draws)


PHI = 1.64   # measured: kills vary about 1.6x more than Poisson (CS2 is only 1.10)


def poisson_over(mu, line):
    k = int(math.floor(line))
    term = math.exp(-mu); cum = term
    for i in range(1, k + 1):
        term *= mu / i
        cum += term
    return max(0.0, 1 - cum)


def over(mu, line, phi=PHI):
    """P(kills > line) under a negative binomial with variance phi*mu.

    Poisson is wrong here: on 3,000 held-out maps the spread of the misses was 1.64x the mean,
    so a Poisson would call a 60% line 65% and we would bet edges that are not there.
    """
    if phi <= 1.0001:
        return poisson_over(mu, line)
    k = int(math.floor(line))
    r = mu / (phi - 1.0)          # NB: var = mu * phi
    p = 1.0 / phi                 # P(success)
    term = p ** r                 # P(X = 0)
    cum = term
    for i in range(1, k + 1):
        term *= (r + i - 1) / i * (1 - p)
        cum += term
    return max(0.0, min(1.0, 1 - cum))


def test(maps=1, sample=3000):
    """Walk-forward: build the state on everything before a map, then predict that map."""
    prof = load_profiles()
    rows = load_maps()
    cut = int(len(rows) * 0.75)
    S = State(rows[:cut])
    later = rows[cut:]
    if len(later) > sample:
        later = random.sample(later, sample)
    errs, preds, acts, hits, n50 = [], [], [], 0, 0
    for r in later:
        wp = S.winp(r["team"], r["opp"])
        mu = mean_kills(prof, S, str(r["pid"]), r["opp"], wp, maps=1, agent=r["agent"])
        if mu is None:
            continue
        errs.append(mu - r["kills"]); preds.append(mu); acts.append(r["kills"])
        # a fair line at our own mean: does the over hit half the time?
        line = round(mu * 2) / 2
        if abs(line - mu) < 0.4:
            n50 += 1
            hits += 1 if r["kills"] > line else 0
    n = len(errs)
    bias = sum(errs) / n
    mae = sum(abs(e) for e in errs) / n
    print("walk-forward on %d player-maps (trained on the first %d rows)" % (n, cut))
    print("  our mean:   %.2f kills per map        actual: %.2f" % (sum(preds) / n, sum(acts) / n))
    print("  bias:       %+.2f kills per map       (the old attempt was +3.7 and that killed it)" % bias)
    print("  average miss: %.2f kills" % mae)
    if n50:
        print("  on lines set AT our own mean, the over hit %d of %d = %.1f%%  (a fair model sits at 50%%)"
              % (hits, n50, 100 * hits / n50))
    # spread check: are we too confident?
    var = sum((a - p) ** 2 for a, p in zip(acts, preds)) / n
    mp = sum(preds) / n
    print("  spread of the misses: %.2f, Poisson expects about %.2f  (ratio %.2f)" % (var, mp, var / mp))
    # calibration: when we say 60%, does it land 60%?
    buckets = collections.defaultdict(lambda: [0, 0])
    for mu, a in zip(preds, acts):
        for off in (-4, -2, 0, 2, 4):
            line = round(mu + off) - 0.5
            if line <= 0:
                continue
            pr = over(mu, line)
            b = round(pr * 10) / 10
            buckets[b][0] += 1
            buckets[b][1] += 1 if a > line else 0
    print("\n  we said     it happened")
    for b in sorted(buckets):
        c, w = buckets[b]
        if c >= 150:
            print("    %3d%%        %3d%%   (%d lines)" % (round(100 * b), round(100 * w / c), c))
    return bias, mae


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "test"
    if cmd == "test":
        test()
    elif cmd == "price":
        prof = load_profiles(); S = State(load_maps())
        name = sys.argv[2]; line = float(sys.argv[3])
        mp = int(sys.argv[sys.argv.index("--maps") + 1]) if "--maps" in sys.argv else 2
        wp = float(sys.argv[sys.argv.index("--winp") + 1]) if "--winp" in sys.argv else 0.5
        hit = [(pid, p) for pid, p in prof["players"].items() if p["name"].lower() == name.lower()]
        if not hit:
            sys.exit("no player called " + name)
        pid, p = max(hit, key=lambda x: x[1]["maps"])
        mu = mean_kills(prof, S, pid, p["team"], wp, maps=mp)
        po = poisson_over(mu, line)
        print("%s (%s): model mean %.1f kills over %d map(s) at %d%% to win the map"
              % (p["name"], p["team"], mu, mp, round(100 * wp)))
        print("  over %.1f: %.0f%%    under %.1f: %.0f%%" % (line, 100 * po, line, 100 * (1 - po)))
    else:
        print(__doc__)
