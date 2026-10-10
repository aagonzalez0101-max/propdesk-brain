"""
Batter prop model: hits, total bases, home runs.

Prices per-plate-appearance outcome rates against the opposing starter, then
compounds them over the number of trips the hitter is expected to get.

On lineups: official cards post about two hours before first pitch, but prop
lines are up long before that -- and the soft opening numbers are exactly
where the edge is. So the model runs on a projected order rebuilt from the
last week of actual batting orders and upgrades to the official card once it
exists. Being one slot off costs about 0.1 plate appearances; waiting for
certainty costs the entire edge.
"""
from __future__ import annotations

import math

from .mlbmodel import BF_REG, regress

PA_REG_BATTER = 250.0    # PA before a hitter's own rates outweigh league average
PA_REG_SPLIT = 180.0     # platoon splits are noisier -- regress harder
PA_PER_SLOT = 0.105      # plate appearances gained per slot moved up the order


def log5(bat_rate: float, pit_rate: float, lg_rate: float) -> float:
    """
    Odds-ratio matchup adjustment (Bill James' log5).

    A .300 hitter facing a pitcher who allows .270 in a .250 league does not
    hit .300, and does not hit the average of the two either. log5 gives the
    right answer.
    """
    lg_rate = min(max(lg_rate, 1e-6), 1 - 1e-6)
    bat_rate = min(max(bat_rate, 1e-6), 1 - 1e-6)
    pit_rate = min(max(pit_rate, 1e-6), 1 - 1e-6)
    num = (bat_rate * pit_rate) / lg_rate
    den = num + ((1 - bat_rate) * (1 - pit_rate)) / (1 - lg_rate)
    return num / den if den > 0 else bat_rate


# A team's plate appearances are not all taken by the nine men who started.
# Pinch hitters, defensive replacements, and blowout removals siphon off a
# share of them. Measured over 505 batter-games in 2026, starters averaged
# 3.952 PA against the 4.217 that dividing team PA by nine predicts -- a 6.3%
# overestimate that flowed straight into hits (+9%), total bases (+10.5%) and
# home runs (+20%), making every batter prop look like an Over.
STARTER_PA_SHARE = 0.937


def expected_pa(slot: int, pa_per_team_game: float = 37.8) -> float:
    """
    Expected plate appearances for a STARTER in a given batting-order slot.

    The order turns over ~4.2 times, so the leadoff hitter gets roughly 0.8
    more trips than the nine-hole. Scaled by STARTER_PA_SHARE because the
    starter does not finish every game he begins.
    """
    base = (pa_per_team_game * STARTER_PA_SHARE) / 9.0
    return max(base + (5 - slot) * PA_PER_SLOT, 1.0)


def true_rates(b: dict, career: dict, split: dict, lgh: dict) -> dict:
    """
    Regressed per-PA outcome rates for one hitter.

    Season is blended with career by sample size, then the platoon split is
    applied as a regressed DELTA rather than used directly -- an individual's
    split against one hand is usually a couple hundred PA and mostly noise.
    """
    season_pa = b.get("pa", 0.0)
    car_pa = career.get("pa", 0.0)

    singles_s = max(b.get("h", 0.0) - b.get("2b", 0.0)
                    - b.get("3b", 0.0) - b.get("hr", 0.0), 0.0)
    singles_c = max(career.get("h", 0.0) - career.get("2b", 0.0)
                    - career.get("3b", 0.0) - career.get("hr", 0.0), 0.0)
    bb = {**b, "1b": singles_s}
    cc = {**career, "1b": singles_c}

    def blend(key: str, lg_key: str) -> float:
        prior_pa = max(car_pa - season_pa, 0.0)
        prior_ct = max(cc.get(key, 0.0) - bb.get(key, 0.0), 0.0)
        tot_pa = season_pa + prior_pa
        tot_ct = bb.get(key, 0.0) + prior_ct
        raw = (tot_ct / tot_pa) if tot_pa > 0 else lgh[lg_key]
        return regress(raw, tot_pa, lgh[lg_key], PA_REG_BATTER)

    rates = {
        "1b": blend("1b", "1b_rate"),
        "2b": blend("2b", "2b_rate"),
        "3b": blend("3b", "3b_rate"),
        "hr": blend("hr", "hr_rate"),
        "bb": blend("bb", "bb_rate"),
        "k": blend("k", "k_rate"),
    }

    if split.get("pa", 0) > 0 and season_pa > 0:
        w = split["pa"] / (split["pa"] + PA_REG_SPLIT)
        for key in ("hr", "bb", "k"):
            d = (split.get(key, 0.0) / split["pa"]) - (bb.get(key, 0.0) / season_pa)
            rates[key] = max(rates[key] + d * w, 1e-5)
        split_1b = max(split.get("h", 0.0) - split.get("2b", 0.0)
                       - split.get("3b", 0.0) - split.get("hr", 0.0), 0.0)
        d1 = (split_1b / split["pa"]) - (singles_s / season_pa)
        rates["1b"] = max(rates["1b"] + d1 * w, 1e-5)

    rates["h"] = rates["1b"] + rates["2b"] + rates["3b"] + rates["hr"]
    return rates


def vs_pitcher(rates: dict, sp: dict, lgh: dict, park: float = 1.0) -> dict:
    """Apply the opposing starter and the park to a hitter's baseline rates."""
    # Must use the SEASON batters-faced here, not the career-blended `bf` on
    # the talent dict: hits/HR/walks allowed are season counts, and dividing a
    # season numerator by a career denominator makes every starter look
    # unhittable, which log5 then turns into a crushed rate for every batter.
    bf = sp.get("bf_season", 0.0) or 1.0
    p_hits = regress(sp.get("h_allowed", 0.0) / bf, bf, lgh["h_rate"], BF_REG)
    p_hr = regress(sp.get("hr_allowed", 0.0) / bf, bf, lgh["hr_rate"], BF_REG)
    p_bb = regress(sp.get("bb_allowed", 0.0) / bf, bf, lgh["bb_rate"], BF_REG)
    p_k = sp.get("k_rate", lgh["k_rate"])

    out = {
        "h": log5(rates["h"], p_hits, lgh["h_rate"]) * park,
        "hr": log5(rates["hr"], p_hr, lgh["hr_rate"]) * park,
        "k": log5(rates["k"], p_k, lgh["k_rate"]),
        "bb": log5(rates["bb"], p_bb, lgh["bb_rate"]),
    }
    # Split the adjusted hit rate back into 1B/2B/3B using the hitter's own mix.
    mix = rates["1b"] + rates["2b"] + rates["3b"]
    non_hr = max(out["h"] - out["hr"], 1e-6)
    if mix > 0:
        out["1b"] = non_hr * rates["1b"] / mix
        out["2b"] = non_hr * rates["2b"] / mix
        out["3b"] = non_hr * rates["3b"] / mix
    else:
        out["1b"], out["2b"], out["3b"] = non_hr * 0.75, non_hr * 0.22, non_hr * 0.03
    return out


def _pa_distribution(exp_pa: float) -> list[tuple[int, float]]:
    """
    How many plate appearances the hitter actually gets.

    Expected 4.6 means mostly 5 trips, sometimes 4. A little mass sits one
    lower for early exits, pinch hits and short games.
    """
    lo = int(exp_pa)
    frac = exp_pa - lo
    raw = [(lo, (1 - frac) * 0.92), (lo + 1, frac * 0.92), (max(lo - 1, 0), 0.08)]
    agg: dict[int, float] = {}
    for n, p in raw:
        agg[n] = agg.get(n, 0.0) + p
    total = sum(agg.values())
    return [(n, p / total) for n, p in sorted(agg.items()) if p > 0]


def hits_pmf(rate_h: float, exp_pa: float, kmax: int = 6) -> list[float]:
    """Hits distribution: binomial per trip, mixed over the PA count."""
    out = [0.0] * (kmax + 1)
    for n, p_n in _pa_distribution(exp_pa):
        for k in range(min(n, kmax) + 1):
            comb = math.exp(math.lgamma(n + 1) - math.lgamma(k + 1)
                            - math.lgamma(n - k + 1))
            out[k] += p_n * comb * (rate_h ** k) * ((1 - rate_h) ** (n - k))
    total = sum(out)
    return [x / total for x in out] if total else out


def total_bases_pmf(rates: dict, exp_pa: float, kmax: int = 12) -> list[float]:
    """
    Total bases distribution.

    Each trip yields 0-4 bases; the per-trip distribution is convolved once
    per plate appearance and mixed over the PA count. Convolution rather than
    a fitted curve because total bases is lumpy -- the home run mass matters.
    """
    per_pa = [0.0] * 5
    per_pa[1], per_pa[2] = rates["1b"], rates["2b"]
    per_pa[3], per_pa[4] = rates["3b"], rates["hr"]
    per_pa[0] = max(1.0 - sum(per_pa[1:]), 1e-9)

    out = [0.0] * (kmax + 1)
    for n, p_n in _pa_distribution(exp_pa):
        dist = [1.0] + [0.0] * kmax
        for _ in range(n):
            nxt = [0.0] * (kmax + 1)
            for i, pi in enumerate(dist):
                if pi <= 0:
                    continue
                for bases, pb in enumerate(per_pa):
                    if i + bases <= kmax:
                        nxt[i + bases] += pi * pb
            dist = nxt
        for i, pi in enumerate(dist):
            out[i] += p_n * pi
    total = sum(out)
    return [x / total for x in out] if total else out


PA_REG_BVP = 300.0   # head-to-head history regresses very hard -- see below


def apply_bvp(rates: dict, bvp: dict, lgh: dict) -> tuple[dict, float]:
    """
    Fold in batter-vs-pitcher history, weighted honestly.

    These samples are 5-30 plate appearances. Regressed against a 300-PA prior,
    a 30-PA history gets about 9% weight -- which is roughly what the research
    supports. It nudges a number; it does not decide a bet. A 3-for-6 career
    line looks like destiny and is worth almost nothing, and pricing it as
    though it matters is a reliable way to talk yourself into a bad number.
    """
    pa = bvp.get("pa", 0.0) if bvp else 0.0
    if pa < 4:
        return rates, 0.0
    w = pa / (pa + PA_REG_BVP)
    out = dict(rates)
    h_rate = bvp.get("h", 0.0) / pa
    hr_rate = bvp.get("hr", 0.0) / pa
    k_rate = bvp.get("k", 0.0) / pa
    out["h"] = max(rates["h"] + (h_rate - rates["h"]) * w, 1e-4)
    out["hr"] = max(rates["hr"] + (hr_rate - rates["hr"]) * w, 1e-5)
    out["k"] = max(rates["k"] + (k_rate - rates["k"]) * w, 1e-4)
    # Rebuild the hit mix around the adjusted totals.
    mix = rates["1b"] + rates["2b"] + rates["3b"]
    non_hr = max(out["h"] - out["hr"], 1e-6)
    if mix > 0:
        out["1b"] = non_hr * rates["1b"] / mix
        out["2b"] = non_hr * rates["2b"] / mix
        out["3b"] = non_hr * rates["3b"] / mix
    return out, w


def project(b: dict, career: dict, split: dict, sp: dict, slot: int,
            lgh: dict, park: float = 1.0, arsenal_mult: float = 1.0,
            whiff_mult: float = 1.0, bvp: dict | None = None) -> dict:
    """
    Everything needed to price this hitter's props tonight.

    Factor order matters: baseline talent -> opposing starter (log5) -> park
    -> pitch-arsenal matchup -> head-to-head history. Each stage is regressed
    on its own sample size so a 40-pitch arsenal read cannot outvote 3,000
    career plate appearances.
    """
    base = true_rates(b, career, split, lgh)
    adj = vs_pitcher(base, sp, lgh, park)

    # Pitch-mix matchup: how this specific arsenal suits him, relative to the
    # average arsenal he faces (his own quality is already in `base`).
    if arsenal_mult != 1.0:
        for k in ("h", "hr", "1b", "2b", "3b"):
            adj[k] = adj[k] * arsenal_mult
    if whiff_mult != 1.0:
        adj["k"] = min(adj["k"] * whiff_mult, 0.85)

    bvp_weight = 0.0
    if bvp:
        adj, bvp_weight = apply_bvp(adj, bvp, lgh)

    pa = expected_pa(slot, lgh.get("pa_per_team_game", 37.8))
    h_pmf = hits_pmf(adj["h"], pa)
    tb_pmf = total_bases_pmf(adj, pa)
    return {
        "name": b.get("name", "?"), "slot": slot, "exp_pa": pa, "rates": adj,
        "arsenal_mult": arsenal_mult, "whiff_mult": whiff_mult,
        "bvp_weight": bvp_weight, "bvp_pa": (bvp or {}).get("pa", 0),
        "hits_pmf": h_pmf, "tb_pmf": tb_pmf,
        "exp_hits": sum(i * p for i, p in enumerate(h_pmf)),
        "exp_tb": sum(i * p for i, p in enumerate(tb_pmf)),
        "exp_hr": adj["hr"] * pa,
    }


def over_under(pmf: list[float], line: float) -> tuple[float, float]:
    """P(over), P(under) for a prop line, pushes removed."""
    over = sum(p for k, p in enumerate(pmf) if k > line)
    under = sum(p for k, p in enumerate(pmf) if k < line)
    live = over + under
    return (over / live, under / live) if live > 0 else (0.5, 0.5)


def pitcher_for_props(raw: dict, talent: dict) -> dict:
    """Attach raw counting stats the batter model needs to a talent estimate."""
    season_bf = raw.get("bf", 0.0) or (raw.get("ip", 0.0) * 4.27)
    return {**talent,
            "bf_season": season_bf,
            "h_allowed": raw.get("h", 0.0),
            "hr_allowed": raw.get("hr", 0.0),
            "bb_allowed": raw.get("bb", 0.0)}
