"""
Unified player-prop projections across every market the book offers.

Strikeouts were the first market modelled and for a while the only one, which
left most of the board unpriced. Everything here reuses components that are
already validated rather than inventing new ones:

  pitcher outs          expected innings x 3. The innings projection is the
                        best-validated piece in the whole model (corr 0.71
                        against actual, bias -0.08) and this market carries
                        the most books of any prop -- six.
  pitcher walks         regressed BB/BF x expected batters faced
  pitcher hits allowed  regressed H/BF x expected batters faced
  pitcher earned runs   true RA9 x expected innings, converted to earned
  batter singles        the 1B component of the batter rate model
  batter doubles        the 2B component
  batter home runs      the HR component (thin market -- often one book)

The distributions matter as much as the means. Counts of discrete events with
a variable number of chances are overdispersed relative to Poisson, so these
use the same negative binomial the run model does. Outs are the exception:
innings pitched is roughly symmetric around the expectation and bounded by the
hook, so it gets a discretised normal.
"""
from __future__ import annotations

import math

from .mlbmodel import BF_REG, K_RATE_REG, _nb_pmf, regress

# Innings pitched varies about 1.3 innings around its expectation, driven by
# the manager's hook rather than anything the pitcher controls smoothly.
IP_SD = 1.30

# Earned runs are ~92% of total runs allowed league-wide.
ER_FRACTION = 0.92

# Overdispersion for count props. Slightly above Poisson for the same reason
# strikeouts are: the number of chances is itself random.
COUNT_VAR_RATIO = 1.15


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def outs_pmf(exp_ip: float, kmax: int = 27) -> list[float]:
    """
    Distribution over recorded outs for a starter.

    Discretised normal around expected innings. A pitcher does not get pulled
    smoothly -- he gets pulled -- so the spread reflects hook variance rather
    than pitch-level randomness.
    """
    mean_outs = exp_ip * 3.0
    sd = IP_SD * 3.0
    out = []
    for k in range(kmax + 1):
        lo = (k - 0.5 - mean_outs) / sd
        hi = (k + 0.5 - mean_outs) / sd
        out.append(max(_norm_cdf(hi) - _norm_cdf(lo), 0.0))
    total = sum(out)
    return [x / total for x in out] if total else out


def pitcher_walks_pmf(sp: dict, raw: dict, lg: dict, opp_bb_mult: float = 1.0,
                      kmax: int = 10) -> dict:
    """Walks allowed: regressed BB rate over expected batters faced."""
    bf = raw.get("bf", 0.0) or (raw.get("ip", 0.0) * lg["bf_per_ip"])
    lg_bb = lg.get("bb9", 3.4) / 9.0 / lg["bf_per_ip"]
    rate = regress((raw.get("bb", 0.0) / bf) if bf else lg_bb, bf, lg_bb, BF_REG)
    rate *= opp_bb_mult
    exp_bf = sp["exp_ip"] * lg["bf_per_ip"]
    mean = rate * exp_bf
    return {"mean": mean, "rate": rate, "exp_bf": exp_bf,
            "pmf": _nb_pmf(mean, COUNT_VAR_RATIO, kmax)}


def pitcher_hits_pmf(sp: dict, raw: dict, lg: dict, lgh: dict,
                     opp_h_mult: float = 1.0, kmax: int = 16) -> dict:
    """Hits allowed: regressed H rate over expected batters faced."""
    bf = raw.get("bf", 0.0) or (raw.get("ip", 0.0) * lg["bf_per_ip"])
    lg_h = lgh["h_rate"]
    rate = regress((raw.get("h", 0.0) / bf) if bf else lg_h, bf, lg_h, BF_REG)
    rate *= opp_h_mult
    exp_bf = sp["exp_ip"] * lg["bf_per_ip"]
    mean = rate * exp_bf
    return {"mean": mean, "rate": rate, "exp_bf": exp_bf,
            "pmf": _nb_pmf(mean, COUNT_VAR_RATIO, kmax)}


def pitcher_er_pmf(sp: dict, lg: dict, opp_off_factor: float = 1.0,
                   park: float = 1.0, kmax: int = 12) -> dict:
    """
    Earned runs: the same true-RA9 talent estimate the game model uses,
    scaled to expected innings and converted from total runs to earned.
    """
    ra9 = sp["true_ra9"] * opp_off_factor * park
    mean = (ra9 / 9.0) * sp["exp_ip"] * ER_FRACTION
    return {"mean": mean, "ra9": ra9,
            "pmf": _nb_pmf(mean, 1.45, kmax)}


def batter_component_pmf(rates: dict, exp_pa: float, key: str,
                         kmax: int = 5) -> dict:
    """
    Singles, doubles or home runs for one hitter.

    Each is a binomial over plate appearances at that hitter's regressed rate
    for the specific outcome, mixed over how many trips he actually gets.
    """
    from .batters import _pa_distribution

    rate = max(rates.get(key, 0.0), 1e-6)
    out = [0.0] * (kmax + 1)
    for n, p_n in _pa_distribution(exp_pa):
        for k in range(min(n, kmax) + 1):
            comb = math.exp(math.lgamma(n + 1) - math.lgamma(k + 1)
                            - math.lgamma(n - k + 1))
            out[k] += p_n * comb * (rate ** k) * ((1 - rate) ** (n - k))
    total = sum(out)
    pmf = [x / total for x in out] if total else out
    return {"mean": sum(i * p for i, p in enumerate(pmf)), "rate": rate,
            "pmf": pmf}


def over_under(pmf: list[float], line: float) -> tuple[float, float]:
    """P(over), P(under) with pushes removed."""
    over = sum(p for k, p in enumerate(pmf) if k > line)
    under = sum(p for k, p in enumerate(pmf) if k < line)
    live = over + under
    return (over / live, under / live) if live > 0 else (0.5, 0.5)


# Which markets this module can price, and how.
PITCHER_MARKETS = {
    "pitcher_strikeouts": "K",
    "pitcher_outs": "Outs",
    "pitcher_walks": "BB",
    "pitcher_hits_allowed": "H allowed",
    "pitcher_earned_runs": "ER",
}
BATTER_MARKETS = {
    "batter_hits": "H",
    "batter_total_bases": "TB",
    "batter_singles": "1B",
    "batter_doubles": "2B",
    "batter_home_runs": "HR",
}


# ------------------------------------------------- hits + runs + RBIs (H+R+RBI)
#
# A staple market (4 books) and the only common batter prop the model couldn't
# price, because runs and RBIs depend on TEAMMATES, not just the hitter.
#
# Derived from 2026 league totals rather than assumed:
#   H/PA .2164   R/PA .1181   RBI/PA .1130   -> H+R+RBI/PA .4475
#   38.66% of times-on-base become runs
#   0.522 RBI per hit
#
# Decomposed so each piece is attributable:
#   runs = home runs (always score) + other times on base x P(scores)
#   RBI  = home runs x (1 + runners on) + other hits x RBI-per-hit
#
# Batting slot matters and pulls the two apart: a leadoff hitter scores more
# because there are eight hitters behind him, and drives in fewer because the
# bases are emptier. Cleanup is the mirror image. These multipliers are
# centred on 1.0 so the league total is preserved.

P_SCORE_GIVEN_ON_BASE = 0.319   # excludes home runs, which score by definition
HR_RBI_MULTIPLIER = 1.60        # a home run drives in himself plus ~0.6 runners
RBI_PER_NON_HR_HIT = 0.347

RUN_SLOT_MULT = {1: 1.15, 2: 1.10, 3: 1.05, 4: 1.00, 5: 0.97,
                 6: 0.94, 7: 0.92, 8: 0.90, 9: 0.88}
RBI_SLOT_MULT = {1: 0.80, 2: 0.90, 3: 1.10, 4: 1.20, 5: 1.15,
                 6: 1.05, 7: 0.98, 8: 0.92, 9: 0.88}

# H+R+RBI is a sum of three positively correlated counts -- a home run adds one
# to each at once -- so it is far more overdispersed than any single component.
#
# Calibrated against outcomes, not assumed. At 1.38 the mean was right (1.828
# projected vs 1.838 actual over 358 batter-games) but the SHAPE was wrong:
# P(over 1.5) came out .502 against an observed .455, i.e. too little mass on
# the 0-and-1 outcomes that decide the most common line. Raising dispersion
# moves mass to zero, which is what a real distribution of this stat looks
# like -- plenty of hitters go 0-for-4 with nothing.
HRR_VAR_RATIO = 2.05


def hits_runs_rbis(rates: dict, exp_pa: float, slot: int,
                   kmax: int = 10) -> dict:
    """
    Projected hits + runs + RBIs for one hitter, with the pieces exposed.

    `rates` is the batter model's per-PA output after the starter, park,
    arsenal and head-to-head adjustments, so the matchup work already applied
    to hits carries through to runs and RBIs.
    """
    hr = rates.get("hr", 0.0)
    hits = rates.get("h", 0.0)
    bb = rates.get("bb", 0.0)

    non_hr_hits = max(hits - hr, 0.0)
    non_hr_on_base = max(hits + bb - hr, 0.0)

    r_mult = RUN_SLOT_MULT.get(slot, 1.0)
    rbi_mult = RBI_SLOT_MULT.get(slot, 1.0)

    r_per_pa = (hr + non_hr_on_base * P_SCORE_GIVEN_ON_BASE) * r_mult
    rbi_per_pa = (hr * HR_RBI_MULTIPLIER
                  + non_hr_hits * RBI_PER_NON_HR_HIT) * rbi_mult

    exp_h = hits * exp_pa
    exp_r = r_per_pa * exp_pa
    exp_rbi = rbi_per_pa * exp_pa
    mean = exp_h + exp_r + exp_rbi

    return {"mean": mean, "exp_h": exp_h, "exp_r": exp_r, "exp_rbi": exp_rbi,
            "pmf": _nb_pmf(mean, HRR_VAR_RATIO, kmax)}


BATTER_MARKETS["batter_hits_runs_rbis"] = "H+R+RBI"
