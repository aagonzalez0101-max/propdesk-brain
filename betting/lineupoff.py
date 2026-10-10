"""
Lineup-based offence, replacing the team-season-average approach.

`mlbmodel.offense_factor` asks "how good is this TEAM at hitting". That is a
season aggregate, so it cannot tell the difference between a club's best nine
and the same club resting three regulars on a Sunday. Every game against a
given opponent gets the same offensive input.

That is almost certainly why the game model's probability spread is 0.056
against the market's 0.086 -- it is not distinguishing games the market
distinguishes. Lineup composition varies materially day to day and is knowable
before first pitch, which makes it exactly the kind of information a
compressed model is missing.

This module builds the factor from the NINE HITTERS ACTUALLY PLAYING, weighted
by the plate appearances each batting slot receives. Slot share is stable and
well measured: leadoff gets ~12.5% of a team's PA, the nine-hole ~10.1%.
"""
from __future__ import annotations

from . import mlbdata as D

# Share of team plate appearances by batting order slot. Leadoff bats most.
SLOT_PA_SHARE = [0.1247, 0.1218, 0.1190, 0.1162, 0.1134,
                 0.1106, 0.1078, 0.1050, 0.1015]

# A batter needs this many PA before his own line outweighs the league mean.
BATTER_PA_REG = 200.0

# Platoon splits at the individual level are noisier than team level.
BVH_PA_REG = 300.0


def _regress(val: float, n: float, prior: float, k: float) -> float:
    if not n:
        return prior
    w = n / (n + k)
    return w * val + (1 - w) * prior


def lineup_ops(order: list, vs_hand: str, lg: dict) -> dict:
    """
    Slot-weighted OPS for an actual batting order.

    Returns the weighted OPS plus how much of the lineup we could price -- a
    card with three unknowns is far less trustworthy than a full nine, and the
    caller should know that rather than silently getting a league-average fill.
    """
    lg_ops = lg.get("league_ops") or 0.710
    tot_w = 0.0
    acc = 0.0
    known = 0
    for i, bid in enumerate((order or [])[:9]):
        w = SLOT_PA_SHARE[i]
        b = D.batter_stats(int(bid))
        if not b or not b.get("pa"):
            acc += lg_ops * w
            tot_w += w
            continue
        ops = (b.get("obp") or 0) + (b.get("slg") or 0)
        if not ops:
            ab = b.get("ab") or 0
            h = b.get("h") or 0
            tb = b.get("tb") or 0
            pa = b.get("pa") or 1
            obp = (h + (b.get("bb") or 0)) / pa
            slg = (tb / ab) if ab else 0.0
            ops = obp + slg
        ops = _regress(ops, b["pa"], lg_ops, BATTER_PA_REG)
        acc += ops * w
        tot_w += w
        known += 1
    return {"ops": (acc / tot_w) if tot_w else lg_ops, "known": known,
            "n": len((order or [])[:9])}


def factor(team_id: int, order: list, vs_hand: str, lg: dict,
           elasticity: float = 1.83) -> dict:
    """
    Runs factor for an actual lineup: 1.10 means ~10% more runs than average.

    Falls back to the team-season path when the order is unusable (fewer than
    six priceable hitters), because a mostly-unknown card is worse information
    than the season aggregate, not better.
    """
    from . import mlbmodel as MM
    lg_ops = lg.get("league_ops") or 0.710
    lu = lineup_ops(order, vs_hand, lg)
    if lu["known"] < 6:
        base = MM.offense_factor(team_id, vs_hand, lg)
        base["source"] = "team-season (lineup too sparse)"
        return base

    # platoon delta still comes from the team split -- individual splits are
    # too noisy to trust nine at a time
    overall = D.team_hitting(team_id)
    split = D.team_hitting_vs_hand(team_id, vs_hand)
    delta = 0.0
    if split.get("ops") and split.get("pa") and overall.get("ops"):
        w = split["pa"] / (split["pa"] + BVH_PA_REG)
        delta = (split["ops"] - overall["ops"]) * w

    # park-neutralise using the team's own park factor
    pf = D.PARK_FACTORS.get(str(team_id), D.DEFAULT_PARK) if hasattr(D, "PARK_FACTORS") else 1.0
    ops = lu["ops"] / (pf ** 0.5 if pf else 1.0) + delta

    k_rate = ((overall.get("k", 0) / overall["pa"]) if overall.get("pa") else lg["k_rate"])
    return {"factor": (ops / lg_ops) ** elasticity if lg_ops else 1.0,
            "ops": ops, "base_ops": lu["ops"], "platoon_delta": delta,
            "source": f"lineup({lu['known']}/9)", "pa": split.get("pa", 0),
            "k_rate": _regress(k_rate, overall.get("pa", 0), lg["k_rate"], 700.0)}
