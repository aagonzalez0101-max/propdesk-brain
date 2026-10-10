"""
Game model v3 -- everything measurable, thrown at the run-margin projection.

Diagnosis that motivated it: v1/v2 project a run margin with sd 0.546 against
actual margins of sd 4.486, and correlate with actual margin at just +0.175.
That is ~3% of variance explained. The probability conversion is fine -- tuning
the normal's SD changes the spread but leaves Brier at 0.245 and winner% at
55.4% regardless. The RUN PROJECTION is what cannot distinguish games.

So v3 adds every input we have a measured handle on, and the test is simply
whether margin correlation rises above 0.175:

  pitcher vs pitcher   true RA9 (FIP-based, HR-regressed) -- already validated
  batters vs pitcher   Statcast arsenal: usage-weighted wOBA/whiff by pitch
                       type across the actual posted order
  lineup quality       slot-weighted OPS of the nine actually playing
  weather              Open-Meteo wind vectored against park azimuth + temp
  bullpen              regressed RA9, weighted by innings the starter leaves
  form (L10)           included but expected to add nothing -- season ratings
                       beat 30-day form in the WNBA test (MAE 8.71 vs 9.06)

Every term is switchable so the backtest can attribute credit rather than
report one number.
"""
from __future__ import annotations

import math
import statistics as st

from . import mlbdata as D
from . import mlbmodel as MM
from . import lineupoff as LO


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def team_form(team_id: int, day: str, n: int = 10) -> float:
    """Run differential per game over the last n, regressed. ~0 = neutral."""
    try:
        log = D._get(f"/teams/{team_id}",
                     {"hydrate": f"stats(group=hitting,type=gameLog,season=2026)"},
                     ttl=21600, cache_name=f"tform_{team_id}_2026")
    except Exception:
        return 0.0
    return 0.0          # placeholder: filled by caller with real game results


def project(ctx: dict, lg: dict, *, use_lineup=True, use_arsenal=True,
            use_weather=True, use_bullpen=True, form=None) -> dict:
    """Expected runs for each side, plus the pieces, so terms can be attributed."""
    hs = MM.pitcher_true_talent(D.pitcher_stats(ctx["home_sp"]["id"]), lg)
    as_ = MM.pitcher_true_talent(D.pitcher_stats(ctx["away_sp"]["id"]), lg)

    posted = D.posted_lineup(ctx["game_pk"])
    h_order = posted.get("home") or D.projected_lineup(ctx["home_id"])
    a_order = posted.get("away") or D.projected_lineup(ctx["away_id"])

    if use_lineup and h_order and a_order:
        ho = LO.factor(ctx["home_id"], h_order, as_["hand"], lg)
        ao = LO.factor(ctx["away_id"], a_order, hs["hand"], lg)
    else:
        ho = MM.offense_factor(ctx["home_id"], as_["hand"], lg)
        ao = MM.offense_factor(ctx["away_id"], hs["hand"], lg)

    # arsenal: how the OPPOSING order handles each starter's pitch mix
    h_ars = a_ars = 1.0
    if use_arsenal:
        try:
            from . import savant as S
            h_ars = (S.lineup_whiff_mult(ctx["home_sp"]["id"], a_order, 2026) or {}).get("mult", 1.0)
            a_ars = (S.lineup_whiff_mult(ctx["away_sp"]["id"], h_order, 2026) or {}).get("mult", 1.0)
        except Exception:
            pass
    # a higher whiff multiplier means the pitcher misses more bats -> fewer runs
    h_sup = 1.0 / (h_ars ** 0.5)      # suppression applied to AWAY offence
    a_sup = 1.0 / (a_ars ** 0.5)

    park = ctx.get("park_factor", 1.0)
    wx = 1.0
    if use_weather:
        try:
            from . import weather as W
            w = W.game_weather(ctx) or {}
            wx = 1.0 + (w.get("runs", 0.0) or 0.0) / 9.0   # key is "runs", not "run_delta"
        except Exception:
            pass

    # starter carries exp_ip, bullpen covers the rest
    def side_runs(opp_sp, opp_pen_id, off, sup):
        ip = max(1.0, min(9.0, opp_sp["exp_ip"]))
        pen = MM.bullpen_ra9(opp_pen_id, lg) if use_bullpen else opp_sp["true_ra9"]
        ra9 = (opp_sp["true_ra9"] * ip + pen * (9.0 - ip)) / 9.0
        return (ra9 / 9.0) * 9.0 * off["factor"] * park * wx * sup / 9.0 * 9.0

    h_runs = side_runs(as_, ctx["away_id"], ho, a_sup) * MM.HFA_FULL_GAME
    a_runs = side_runs(hs, ctx["home_id"], ao, h_sup)

    if form:
        h_runs += form.get("home", 0.0) * 0.15
        a_runs += form.get("away", 0.0) * 0.15

    margin = h_runs - a_runs
    return {"home_runs": h_runs, "away_runs": a_runs, "margin": margin,
            "total": h_runs + a_runs,
            "h_off": ho["factor"], "a_off": ao["factor"],
            "h_ars": h_ars, "a_ars": a_ars, "wx": wx,
            "hs_ra9": hs["true_ra9"], "as_ra9": as_["true_ra9"],
            "hs_ip": hs["exp_ip"], "as_ip": as_["exp_ip"]}
