"""
Dixon-Coles goal model for soccer, scored against Pinnacle closing odds.

Structure: each team carries an attack and a defence rating. Expected goals are

    home = exp(atk_home - def_away + home_adv)
    away = exp(atk_away - def_home)

and the scoreline distribution is the product of two Poissons, with the
Dixon-Coles low-score correction applied to the 0-0/1-0/0-1/1-1 cells. That
correction exists because independent Poissons systematically under-predict
draws, and the draw is 26.2% of all outcomes -- getting it wrong makes the
model useless regardless of how well it does on home/away.

Ratings are fitted by gradient descent on log-likelihood with exponential time
decay, and every prediction is WALK-FORWARD: a match is priced only from
matches played strictly before it. That is the same discipline that exposed the
AsOf leak in the MLB work, where a partially-swapped provider let the model
read end-of-season batter lines for the games it was being scored on.

The test that matters is not accuracy. It is whether this adds anything to
Pinnacle's closing price -- the MLB game model came back with a NEGATIVE
coefficient once the market was controlled for, and that is a live possibility
here too.
"""
from __future__ import annotations

import math
from collections import defaultdict

MAX_GOALS = 10
HALF_LIFE_DAYS = 180.0


def _dc_tau(hg, ag, lam, mu, rho):
    """Dixon-Coles correction on the four low-score cells."""
    if hg == 0 and ag == 0:
        return 1.0 - lam * mu * rho
    if hg == 0 and ag == 1:
        return 1.0 + lam * rho
    if hg == 1 and ag == 0:
        return 1.0 + mu * rho
    if hg == 1 and ag == 1:
        return 1.0 - rho
    return 1.0


def _pois(k, lam):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam + k * math.log(lam) - math.lgamma(k + 1))


class Ratings:
    """Attack/defence per team, plus home advantage and the DC rho."""

    def __init__(self):
        self.atk = defaultdict(float)
        self.dfn = defaultdict(float)
        self.home_adv = 0.25
        self.rho = -0.05
        self.base = 0.0

    def expected(self, home, away):
        lam = math.exp(self.base + self.atk[home] - self.dfn[away] + self.home_adv)
        mu = math.exp(self.base + self.atk[away] - self.dfn[home])
        return max(lam, 0.05), max(mu, 0.05)

    def outcome_probs(self, home, away):
        """(p_home, p_draw, p_away) from the corrected score matrix."""
        lam, mu = self.expected(home, away)
        ph = pd = pa = 0.0
        for hg in range(MAX_GOALS + 1):
            a = _pois(hg, lam)
            for ag in range(MAX_GOALS + 1):
                p = a * _pois(ag, mu) * _dc_tau(hg, ag, lam, mu, self.rho)
                if p <= 0:
                    continue
                if hg > ag:
                    ph += p
                elif hg == ag:
                    pd += p
                else:
                    pa += p
        tot = ph + pd + pa
        return (ph / tot, pd / tot, pa / tot) if tot > 0 else (0.44, 0.26, 0.30)

    def total_probs(self, home, away, line=2.5):
        lam, mu = self.expected(home, away)
        under = 0.0
        for hg in range(MAX_GOALS + 1):
            a = _pois(hg, lam)
            for ag in range(MAX_GOALS + 1):
                if hg + ag < line:
                    under += a * _pois(ag, mu) * _dc_tau(hg, ag, lam, mu, self.rho)
        under = min(max(under, 1e-6), 1 - 1e-6)
        return 1.0 - under, under


def _days(d1, d2):
    """football-data dates are dd/mm/yy or dd/mm/yyyy."""
    def parse(s):
        p = s.split("/")
        if len(p) != 3:
            return None
        d, m, y = p
        y = int(y)
        y += 2000 if y < 100 else 0
        return (y * 372) + (int(m) * 31) + int(d)   # ordinal-ish, good enough for decay
    a, b = parse(d1), parse(d2)
    return abs(a - b) if a and b else 0.0


def fit(rows, iters=400, lr=0.09, as_of=None):
    """Gradient descent on weighted Poisson log-likelihood.

    iters/lr matter more than they look. At 60 iterations the attack ratings
    spread only 0.246 and P(home) spans 23-58% -- the teams have barely
    separated, every draw prediction lands in one bucket, and the whole model
    looks like it has no signal when really it has not finished fitting. At 400
    the spread is ~0.65 and P(home) spans 7-83%, which is the range a real
    league produces.
    """
    r = Ratings()
    teams = {m["home"] for m in rows} | {m["away"] for m in rows}
    for t in teams:
        r.atk[t] = 0.0
        r.dfn[t] = 0.0
    if not rows:
        return r
    r.base = math.log(max(sum(m["hg"] + m["ag"] for m in rows) / (2.0 * len(rows)), 0.2))

    weights = []
    for m in rows:
        d = _days(m["date"], as_of) if as_of else 0.0
        weights.append(math.exp(-d / HALF_LIFE_DAYS) if as_of else 1.0)

    for _ in range(iters):
        g_atk = defaultdict(float)
        g_dfn = defaultdict(float)
        g_home = 0.0
        for m, w in zip(rows, weights):
            if w < 1e-4:
                continue
            lam, mu = r.expected(m["home"], m["away"])
            eh, ea = m["hg"] - lam, m["ag"] - mu
            g_atk[m["home"]] += w * eh
            g_dfn[m["away"]] -= w * eh
            g_atk[m["away"]] += w * ea
            g_dfn[m["home"]] -= w * ea
            g_home += w * eh
        n = max(sum(weights), 1.0)
        for t in teams:
            r.atk[t] += lr * g_atk[t] / n
            r.dfn[t] += lr * g_dfn[t] / n
        r.home_adv += lr * g_home / n
        # keep ratings centred so attack/defence stay identifiable
        ma = sum(r.atk.values()) / len(teams)
        md = sum(r.dfn.values()) / len(teams)
        for t in teams:
            r.atk[t] -= ma
            r.dfn[t] -= md
    return r


def walk_forward(rows, min_train=400, refit_every=80):
    """Price each match from prior matches only. Returns (row, probs) pairs."""
    rows = sorted(rows, key=lambda m: (m["season"], m["date"]))
    out = []
    model = None
    for i, m in enumerate(rows):
        if i < min_train:
            continue
        if model is None or (i - min_train) % refit_every == 0:
            model = fit(rows[max(0, i - 2500):i], as_of=m["date"])
        if m["home"] not in model.atk or m["away"] not in model.atk:
            continue
        out.append((m, model.outcome_probs(m["home"], m["away"])))
    return out
