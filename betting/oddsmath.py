"""
Odds math: conversions, de-vigging, expected value, and Kelly staking.

Everything in this system reduces to one comparison:
    model probability  vs  de-vigged market probability
If the model is higher by enough to clear the threshold, it's a bet.

All probabilities are floats in (0, 1). All American odds are ints/floats
like -138 or +133.
"""
from __future__ import annotations

import math

# ---------------------------------------------------------------- conversions

def american_to_decimal(american: float) -> float:
    """-138 -> 1.7246,  +133 -> 2.33"""
    if american == 0:
        raise ValueError("American odds cannot be 0")
    return 1.0 + (american / 100.0 if american > 0 else 100.0 / abs(american))


def decimal_to_american(dec: float) -> float:
    if dec <= 1.0:
        raise ValueError(f"Decimal odds must be > 1.0, got {dec}")
    return (dec - 1.0) * 100.0 if dec >= 2.0 else -100.0 / (dec - 1.0)


def american_to_prob(american: float) -> float:
    """Implied probability INCLUDING vig (a.k.a. the raw/quoted probability)."""
    return 1.0 / american_to_decimal(american)


def prob_to_american(p: float) -> float:
    """Fair American price for a true probability p (no vig added)."""
    if not 0.0 < p < 1.0:
        raise ValueError(f"Probability must be in (0,1), got {p}")
    return decimal_to_american(1.0 / p)


def prob_to_decimal(p: float) -> float:
    if not 0.0 < p < 1.0:
        raise ValueError(f"Probability must be in (0,1), got {p}")
    return 1.0 / p


# ------------------------------------------------------------------ de-vigging
#
# A two-way market quotes probabilities that sum to >1. The excess is the
# bookmaker's hold. De-vigging strips it out to recover implied true
# probability. Which method you use matters more than most people think:
# on a -300 favorite the methods can disagree by 2+ percentage points,
# which is larger than most edges you'll ever find.


def overround(raw_probs: list[float]) -> float:
    """Total booked probability. 1.045 means a 4.5% hold."""
    return sum(raw_probs)


def hold_pct(raw_probs: list[float]) -> float:
    """Hold as a percentage. Novig runs ~1%, retail books ~4.5%."""
    return (sum(raw_probs) - 1.0) * 100.0


def devig_multiplicative(raw_probs: list[float]) -> list[float]:
    """
    Proportional scaling: p_i = q_i / sum(q).

    Simplest and most common. Its flaw: it removes vig proportionally, but
    books don't apply vig proportionally -- they load more onto longshots
    (the favorite-longshot bias). This systematically OVERSTATES favorites.
    """
    total = sum(raw_probs)
    return [q / total for q in raw_probs]


def devig_additive(raw_probs: list[float]) -> list[float]:
    """
    Subtract the excess equally: p_i = q_i - (sum(q) - 1)/n.

    Assumes vig is applied in flat probability points. Can produce negative
    values on lopsided markets, so we clamp and renormalise.
    """
    n = len(raw_probs)
    excess = (sum(raw_probs) - 1.0) / n
    out = [max(q - excess, 1e-6) for q in raw_probs]
    total = sum(out)
    return [p / total for p in out]


def devig_power(raw_probs: list[float], tol: float = 1e-10) -> list[float]:
    """
    Power method: find k such that sum(q_i ** k) == 1, then p_i = q_i ** k.

    Handles the favorite-longshot bias far better than multiplicative because
    the exponent compresses longshots more than favourites. This is the
    default for two-way markets in this system.

    Solved by bisection on k, which is monotonic and always brackets.
    """
    if any(q <= 0 for q in raw_probs):
        raise ValueError("All raw probabilities must be positive")
    if abs(sum(raw_probs) - 1.0) < tol:
        return list(raw_probs)

    lo, hi = 0.05, 10.0
    for _ in range(200):
        k = (lo + hi) / 2.0
        s = sum(q ** k for q in raw_probs)
        if abs(s - 1.0) < tol:
            break
        # sum(q^k) decreases as k increases (all q < 1)
        if s > 1.0:
            lo = k
        else:
            hi = k
    k = (lo + hi) / 2.0
    out = [q ** k for q in raw_probs]
    total = sum(out)
    return [p / total for p in out]


def devig_shin(raw_probs: list[float], tol: float = 1e-10) -> list[float]:
    """
    Shin (1993): models the book as protecting itself against a proportion z
    of insider money. Recovers true probability from:

        q_i = ( sqrt(z^2 + 4(1-z) * p_i^2 / S) + z ) / 2      [normalised]

    Inverted here for the 2-way case, which has a closed form, and solved
    numerically otherwise. Widely regarded as the most accurate de-vig on
    liquid two-way markets; it is what we cross-check the power method against.
    """
    S = sum(raw_probs)
    if abs(S - 1.0) < tol:
        return list(raw_probs)

    # Bisect on z so the recovered probabilities sum to 1.
    #
    # At z = 0 this reduces to p_i = q_i / sqrt(S), which sums to sqrt(S) > 1
    # whenever there is vig; the sum decreases monotonically as z rises. So
    # [0, 0.5] always brackets the root for any realistic overround.
    def probs_for(z: float) -> list[float]:
        return [
            max((math.sqrt(z * z + 4.0 * (1.0 - z) * (q * q) / S) - z) / (2.0 * (1.0 - z)), 1e-9)
            for q in raw_probs
        ]

    lo, hi = 0.0, 0.5
    for _ in range(200):
        z = (lo + hi) / 2.0
        s = sum(probs_for(z))
        if abs(s - 1.0) < tol:
            break
        if s > 1.0:
            lo = z
        else:
            hi = z
    out = probs_for((lo + hi) / 2.0)
    total = sum(out)
    return [p / total for p in out]


DEVIG_METHODS = {
    "multiplicative": devig_multiplicative,
    "additive": devig_additive,
    "power": devig_power,
    "shin": devig_shin,
}


def devig(raw_probs: list[float], method: str = "power") -> list[float]:
    """De-vig a set of raw implied probabilities. Default: power."""
    if method == "worst_case":
        # Takes the HIGHEST market probability per outcome across all methods,
        # so any edge measured against it is the smallest the methods support.
        # This is a conservatism filter, not a probability distribution: the
        # result deliberately sums to slightly more than 1. Use it only to
        # test "is this edge real under every de-vig assumption?" -- never as
        # a probability in EV or Kelly.
        cols = [f(raw_probs) for f in (devig_multiplicative, devig_power, devig_shin)]
        return [max(c[i] for c in cols) for i in range(len(raw_probs))]
    if method not in DEVIG_METHODS:
        raise ValueError(f"Unknown de-vig method: {method}. Options: {list(DEVIG_METHODS)}")
    return DEVIG_METHODS[method](raw_probs)


def devig_american(prices: list[float], method: str = "power") -> list[float]:
    """Convenience: de-vig straight from American prices."""
    return devig([american_to_prob(p) for p in prices], method=method)


# ------------------------------------------------------------- edge / EV / stake

def expected_value(p: float, american: float, stake: float = 1.0) -> float:
    """
    Expected profit on `stake` at price `american` given true probability `p`.
    Positive means the bet makes money in the long run.
    """
    dec = american_to_decimal(american)
    return stake * (p * (dec - 1.0) - (1.0 - p))


def ev_percent(p: float, american: float) -> float:
    """Expected profit as a % of stake. This is the number to rank bets by."""
    return expected_value(p, american, 1.0) * 100.0


def edge_pp(model_p: float, market_p: float) -> float:
    """Raw edge in percentage points (model minus de-vigged market)."""
    return (model_p - market_p) * 100.0


def breakeven_prob(american: float) -> float:
    """Win rate needed to break even at this price."""
    return american_to_prob(american)


def min_price_for_edge(p: float, min_ev_pct: float = 0.0) -> float:
    """
    The worst American price you can accept and still clear `min_ev_pct`.

    This is the single most useful output of the whole system when betting on
    Novig: the API doesn't quote Novig props, so instead of naming a price we
    name a THRESHOLD. Check Novig; if the price is this number or better, bet.
    """
    if not 0.0 < p < 1.0:
        raise ValueError(f"Probability must be in (0,1), got {p}")
    # Solve p*(d-1) - (1-p) = min_ev  ->  d = (min_ev + 1) / p
    required_dec = (min_ev_pct / 100.0 + 1.0) / p
    # A very negative min_ev implies decimal odds at or below 1.0, which is not
    # a real price. Clamp so callers scanning with a loose threshold get a
    # usable number instead of an exception.
    required_dec = max(required_dec, 1.0001)
    return decimal_to_american(required_dec)


def kelly_fraction(p: float, american: float, multiplier: float = 0.25,
                   cap: float = 0.05) -> float:
    """
    Fraction of bankroll to stake, as fractional Kelly.

    Full Kelly is mathematically optimal for growth but assumes your
    probability estimate is exact. It isn't -- so full Kelly on an
    overconfident model is a fast way to lose everything. Quarter Kelly
    (multiplier=0.25) keeps most of the growth with a fraction of the
    variance, and `cap` is a hard ceiling on any single bet.

    Returns 0.0 when there is no edge.
    """
    dec = american_to_decimal(american)
    b = dec - 1.0
    if b <= 0:
        return 0.0
    f_star = (p * b - (1.0 - p)) / b
    if f_star <= 0:
        return 0.0
    return min(f_star * multiplier, cap)


def kelly_stake(p: float, american: float, bankroll: float,
                multiplier: float = 0.25, cap: float = 0.05,
                min_stake: float = 0.0) -> float:
    """Dollar stake from fractional Kelly, rounded to the cent."""
    frac = kelly_fraction(p, american, multiplier, cap)
    stake = round(bankroll * frac, 2)
    return stake if stake >= min_stake else 0.0


# ------------------------------------------------------------------ line value

def clv(bet_american: float, closing_american: float) -> float:
    """
    Closing line value, in percentage points of probability.

    Positive CLV means you got a better price than the market closed at. Over
    a large sample this predicts profitability far more reliably than win/loss
    record does -- it's the primary way to tell a good process from a lucky one.
    """
    return (american_to_prob(closing_american) - american_to_prob(bet_american)) * 100.0


def no_vig_clv(bet_american: float, closing_prices: list[float],
               method: str = "power") -> float:
    """CLV measured against the de-vigged closing line -- the honest version."""
    fair = devig_american(closing_prices, method=method)[0]
    return (fair - american_to_prob(bet_american)) * 100.0
