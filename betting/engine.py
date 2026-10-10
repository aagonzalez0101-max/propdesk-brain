"""
The edge engine: where the model is allowed to disagree with the market.

This is the most important design decision in the system, so it's worth
stating plainly.

Measured against a live 20-book MLB board, the from-scratch model correlates
with the market at r=0.50 on full-game moneylines. That is not good enough to
bet. The market aggregates lineup news, weather, injuries, umpire assignments
and sharp money that this model does not see, and betting against it on
absolute team strength is a losing proposition.

But the same model correlates at r=0.73 on the DERIVATIVE -- the question of
how a first-five-innings line should differ from the full-game line. That
question is answered almost entirely by things the model does measure well:
starting pitcher talent, how deep he goes, and bullpen quality. It is also a
thinner market that books price more lazily.

So the engine is market-anchored:

    predicted_F5  =  market_FG_fair  +  calibrated_model_delta

We take the market's word on how good the teams are, and only apply our own
opinion to the part we are actually better at. An edge exists when the real F5
market disagrees with that prediction.

The same principle drives the props: anchor on the market's implied workload,
and apply the model where it has real information.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import mlbmodel as MM
from .market import Edge, TwoWayMarket, build_edge
from .oddsmath import kelly_stake

ROOT = Path(__file__).resolve().parent.parent
CALIB_PATH = ROOT / "data" / "calibration.json"

# Defaults until `bet.py calibrate` measures real ones.
DEFAULT_CALIB = {
    "mlb_f5_delta_bias": -1.67,   # model delta minus market delta, in pp
    "mlb_f5_shrink": 0.60,        # how much of our delta disagreement to trust
    # Props are shrunk HARD toward the market. The K projection correlates
    # +0.82 with actual strikeouts, which is real skill, but we have no
    # historical prop CLOSING LINES to prove we beat the books' number -- that
    # archive does not exist publicly and we only started building it today.
    # Until forward-tested CLV says otherwise, the market gets the benefit of
    # the doubt. Raise this only on evidence, never on a hot week.
    "mlb_k_prop_shrink": 0.35,
    # Batter props carry more per-player error than pitcher K props, so they
    # start shrunk at least as hard. Same rule: raise only on measured CLV.
    "mlb_batter_prop_shrink": 0.35,
    "samples": 0,
}


def load_calibration() -> dict:
    if CALIB_PATH.exists():
        try:
            return {**DEFAULT_CALIB, **json.loads(CALIB_PATH.read_text())}
        except json.JSONDecodeError:
            pass
    return dict(DEFAULT_CALIB)


def save_calibration(c: dict) -> None:
    CALIB_PATH.parent.mkdir(parents=True, exist_ok=True)
    CALIB_PATH.write_text(json.dumps(c, indent=2))


# ------------------------------------------------------------------ shrinkage

def shrink(model_p: float, market_p: float, weight: float) -> float:
    """
    Pull a model probability toward the market.

    weight=1.0 trusts the model completely; 0.0 ignores it. Anything in
    between is a statement about how much unique information the model has.
    Because our disagreement is measured in a market we KNOW is mostly
    efficient, shrinking is not timidity -- it is the correct posterior.
    """
    return market_p + (model_p - market_p) * weight


# ---------------------------------------------------------------------- MLB

@dataclass
class GameEdges:
    matchup: str
    projection: MM.GameProjection
    market_fg: float | None
    market_f5: float | None
    predicted_f5: float | None
    edges: list[Edge] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def mlb_f5_edges(ctx: dict, fg_market: TwoWayMarket | None,
                 f5_market: TwoWayMarket | None, lg: dict,
                 calib: dict, bankroll: float,
                 min_ev: float = 2.0) -> GameEdges:
    """
    Find F5 moneyline edges for one game using the market-anchored method.
    """
    pr = MM.project_game(ctx, lg)
    ge = GameEdges(
        matchup=f"{ctx['away_team']} @ {ctx['home_team']}",
        projection=pr, market_fg=None, market_f5=None, predicted_f5=None,
    )

    if fg_market is None:
        ge.notes.append("no full-game market -- cannot anchor")
        return ge
    fg_fair = fg_market.fair_prob()
    if fg_fair is None:
        ge.notes.append("full-game market unpriceable")
        return ge
    ge.market_fg = fg_fair

    # The model's opinion on how F5 should differ from the full game,
    # de-biased by the measured systematic offset.
    raw_delta = (pr.f5_home_ml - pr.fg_home_win) * 100.0
    delta = raw_delta - calib["mlb_f5_delta_bias"]

    predicted = min(max(fg_fair + delta / 100.0, 0.02), 0.98)
    ge.predicted_f5 = predicted

    if f5_market is None:
        ge.notes.append("no F5 market posted")
        return ge
    f5_fair = f5_market.fair_prob()
    if f5_fair is None:
        ge.notes.append("F5 market unpriceable")
        return ge
    ge.market_f5 = f5_fair

    # Shrink our prediction toward the actual F5 market.
    home_p = shrink(predicted, f5_fair, calib["mlb_f5_shrink"])

    for side, prob, team in (("a", home_p, ctx["home_team"]),
                             ("b", 1.0 - home_p, ctx["away_team"])):
        e = build_edge("F5 ML", team, None, prob, f5_market, side,
                       min_ev_pct=min_ev)
        if e and e.ev_pct >= min_ev:
            e.stake = kelly_stake(prob, e.best_price, bankroll)
            e.note = (f"SP {pr.away_sp['name'] if side=='a' else pr.home_sp['name']} "
                      f"opposing; model delta {raw_delta:+.1f}pp")
            ge.edges.append(e)

    return ge


def mlb_strikeout_edges(ctx: dict, prop_markets: dict[str, list[TwoWayMarket]],
                        lg: dict, calib: dict, bankroll: float,
                        min_ev: float = 3.0, season: int = 2026) -> list[Edge]:
    """
    Pitcher strikeout props.

    Props get a higher EV threshold than moneylines because prop lines are
    stickier, limits are lower, and our projection error is larger.
    """
    from . import mlbdata as D
    from . import savant as S

    pr = MM.project_game(ctx, lg)
    out: list[Edge] = []
    posted = D.posted_lineup(ctx["game_pk"]) if ctx.get("game_pk") else {}

    for sp, opp_off, opp_side in ((pr.home_sp, pr.away_off, "away"),
                                  (pr.away_sp, pr.home_off, "home")):
        markets = prop_markets.get(sp["name"])
        if not markets:
            continue

        # How the lineup he actually faces performs against HIS pitch mix --
        # not just how strikeout-prone they are in general. deGrom's slider
        # and change generate 40-46% whiffs, and a lineup that chases those
        # specifically is worth more strikeouts than its season K rate says.
        sp_id = (ctx.get(f"{'away' if opp_side == 'home' else 'home'}_sp")
                 or {}).get("id")
        lineup = (posted.get(opp_side)
                  or D.projected_lineup(ctx[f"{opp_side}_id"]))
        ars = {"mult": 1.0, "covered": 0, "n": 0}
        if sp_id and lineup:
            ars = S.lineup_whiff_mult(sp_id, lineup, season)

        proj = MM.project_strikeouts(sp, opp_off, lg, arsenal_mult=ars["mult"])
        for m in markets:
            if m.point is None:
                continue
            over_p, under_p = MM.prop_over_prob(proj["pmf"], m.point)
            mkt_over = m.fair_prob()
            if mkt_over is None:
                continue
            over_p = shrink(over_p, mkt_over, calib["mlb_k_prop_shrink"])

            for side, prob, lbl in (("a", over_p, "Over"), ("b", 1 - over_p, "Under")):
                e = build_edge("K prop", f"{sp['name']} {lbl}", m.point, prob,
                               m, side, min_ev_pct=min_ev)
                if e and e.ev_pct >= min_ev:
                    e.stake = kelly_stake(prob, e.best_price, bankroll)
                    e.note = (f"proj {proj['mean']:.1f}K on {proj['exp_bf']:.0f} BF "
                              f"({sp['exp_ip']:.1f} IP); team K x{proj['team_mult']:.3f}, "
                              f"arsenal whiff x{proj['arsenal_mult']:.3f} "
                              f"({ars['covered']}/{ars['n']} hitters covered)")
                    out.append(e)
    return out


def mlb_total_edges(ctx: dict, total_market: TwoWayMarket | None,
                    lg: dict, bankroll: float, min_ev: float = 3.0,
                    shrink_w: float = 0.45) -> list[Edge]:
    """Full-game totals. Shrunk hard -- totals are among the sharpest markets."""
    if total_market is None or total_market.point is None:
        return []
    pr = MM.project_game(ctx, lg)
    over_p, _ = MM.total_over_prob(pr.fg_home, pr.fg_away, total_market.point)
    mkt_over = total_market.fair_prob()
    if mkt_over is None:
        return []
    over_p = shrink(over_p, mkt_over, shrink_w)

    out = []
    for side, prob, lbl in (("a", over_p, "Over"), ("b", 1 - over_p, "Under")):
        e = build_edge("Total", lbl, total_market.point,
                       prob, total_market, side, min_ev_pct=min_ev)
        if e and e.ev_pct >= min_ev:
            e.stake = kelly_stake(prob, e.best_price, bankroll)
            e.note = f"model total {pr.fg_total:.2f}"
            out.append(e)
    return out


# --------------------------------------------------------------- calibration

def calibrate_f5(pairs: list[tuple[float, float, float, float]]) -> dict:
    """
    Measure the systematic offset between model and market F5 deltas.

    `pairs` is a list of (market_fg, market_f5, model_fg, model_f5) as
    probabilities. Returns updated calibration values.

    The bias term is the honest part: if our F5 deltas are systematically
    steeper than the market's, that is a modelling artefact, not fifteen
    simultaneous edges. Removing it is what stops the system from firing off
    the same wrong bet every single day.
    """
    import statistics as st

    if len(pairs) < 5:
        return load_calibration()

    mkt_deltas = [(f5 - fg) * 100 for fg, f5, _, _ in pairs]
    mdl_deltas = [(m5 - mfg) * 100 for _, _, mfg, m5 in pairs]

    bias = st.mean(mdl_deltas) - st.mean(mkt_deltas)

    mx, my = st.mean(mdl_deltas), st.mean(mkt_deltas)
    var = st.pvariance(mdl_deltas)
    cov = sum((a - mx) * (b - my) for a, b in zip(mdl_deltas, mkt_deltas)) / len(pairs)
    slope = (cov / var) if var > 1e-9 else 0.0
    r = (cov / (st.pstdev(mdl_deltas) * st.pstdev(mkt_deltas))
         if st.pstdev(mdl_deltas) > 0 and st.pstdev(mkt_deltas) > 0 else 0.0)

    calib = load_calibration()
    calib.update({
        "mlb_f5_delta_bias": round(bias, 3),
        "mlb_f5_delta_r": round(r, 3),
        "mlb_f5_delta_slope": round(slope, 3),
        "samples": len(pairs),
    })
    # NOTE: the shrink weight is deliberately NOT set from this comparison.
    #
    # Agreeing with the market tells us nothing about who is RIGHT -- only
    # outcomes can do that. A high correlation here means our delta carries
    # the same information the market already priced; a low one means we
    # disagree, but disagreement is equally consistent with "we found an edge"
    # and "we are wrong". Deriving the shrink from slope would let a model
    # that is merely noisy award itself a large weight.
    #
    # So shrink stays conservative until forward-tested CLV justifies raising
    # it. `bet.py clv` reports whether our bets are beating the closing line;
    # that -- not this function -- is what earns a higher weight.
    return calib


# --------------------------------------------------------------- batter props

BATTER_MARKETS = {
    "batter_hits": ("hits_pmf", "H"),
    "batter_total_bases": ("tb_pmf", "TB"),
    "batter_home_runs": ("hr", "HR"),
}


def mlb_batter_edges(ctx: dict, prop_markets: dict[str, dict[str, list]],
                     lg: dict, lgh: dict, calib: dict, bankroll: float,
                     min_ev: float = 4.0, season: int = 2026) -> list[Edge]:
    """
    Price hits / total bases / home run props for both lineups.

    Runs on the projected batting order when the official card isn't posted --
    which is most of the time when the numbers are softest. Each hitter is
    priced through the full factor stack: regressed talent, the opposing
    starter via log5, park, the Statcast pitch-arsenal matchup, and
    head-to-head history.

    The EV bar is higher than for moneylines because prop limits are small,
    lines move slower, and our per-hitter error is larger than our per-team
    error.
    """
    from . import batters as BT
    from . import mlbdata as D
    from . import savant as S

    out: list[Edge] = []
    shrink_w = calib.get("mlb_batter_prop_shrink", 0.35)

    # Official lineup if it exists, otherwise the projected order.
    posted = D.posted_lineup(ctx["game_pk"]) if ctx.get("game_pk") else {}

    for side, opp_key in (("home", "away_sp"), ("away", "home_sp")):
        opp = ctx.get(opp_key)
        if not opp:
            continue
        raw = D.pitcher_stats(opp["id"])
        if not raw:
            continue
        sp = BT.pitcher_for_props(raw, MM.pitcher_true_talent(raw, lg))

        order = posted.get(side) or D.projected_lineup(ctx[f"{side}_id"])
        lineup_src = "official" if posted.get(side) else "projected"
        if not order:
            continue

        # Warm every lookup for this lineup at once -- serially this is ~45
        # round trips per side and turns a fast run into a slow one.
        D.prefetch_batters(order[:9], opp["id"], sp.get("hand", "R"))

        for slot, pid in enumerate(order[:9], 1):
            b = D.batter_stats(int(pid))
            if not b or b.get("pa", 0) < 60:
                continue
            name = b["name"]
            if not any(name in mkts for mkts in prop_markets.values()):
                continue

            career = D.batter_career(int(pid))
            split = D.batter_vs_hand(int(pid), sp.get("hand", "R"))
            ars = S.arsenal_matchup(int(pid), opp["id"], season)
            wh = S.whiff_matchup(int(pid), opp["id"], season)
            bvp = D.batter_vs_pitcher(int(pid), opp["id"])

            pr = BT.project(b, career, split, sp, slot, lgh,
                            ctx.get("park_factor", 1.0),
                            arsenal_mult=ars["mult"], whiff_mult=wh, bvp=bvp)

            why = (f"slot {slot} ({lineup_src}) vs {sp['name']}; "
                   f"{S.describe(ars)}")
            if ars["mult"] != 1.0:
                why += f"; arsenal x{ars['mult']:.3f}"
            if pr.get("bvp_weight", 0) > 0:
                why += f"; BvP {pr['bvp_pa']:.0f}PA @{pr['bvp_weight']:.0%}"

            for mkey, (pmf_key, tag) in BATTER_MARKETS.items():
                markets = prop_markets.get(mkey, {}).get(name)
                if not markets:
                    continue
                for m in markets:
                    if m.point is None:
                        continue
                    if pmf_key == "hr":
                        p_over = min(pr["rates"]["hr"] * pr["exp_pa"], 0.95)
                        # HR props are almost always "0.5" -- P(at least one).
                        p_over = 1.0 - (1.0 - pr["rates"]["hr"]) ** pr["exp_pa"]
                        if m.point > 0.5:
                            continue
                        over_p = p_over
                    else:
                        over_p, _ = BT.over_under(pr[pmf_key], m.point)

                    mkt_over = m.fair_prob()
                    if mkt_over is None:
                        continue
                    over_p = shrink(over_p, mkt_over, shrink_w)

                    for sd, prob, lbl in (("a", over_p, "Over"),
                                          ("b", 1 - over_p, "Under")):
                        e = build_edge(f"{tag} prop", f"{name} {lbl}", m.point,
                                       prob, m, sd, min_ev_pct=min_ev)
                        if e and e.ev_pct >= min_ev:
                            e.stake = kelly_stake(prob, e.best_price, bankroll)
                            e.note = why
                            out.append(e)
    return out


# ------------------------------------------------------------- moneyline edges

def ml_price_edges(mkt: TwoWayMarket, bankroll: float, book: str = "novig",
                   min_ev: float = 1.0, matchup: str = "") -> list[Edge]:
    """
    Moneyline edges from PRICE, not from a model opinion.

    This is deliberate. Measured against a live 20-book board the run model
    correlates r=0.50 with the market on full-game moneylines -- not good
    enough to bet, because the market prices lineup news, weather, umpires and
    sharp money the model never sees. Betting a 0.50-correlation opinion into
    an efficient market is how bankrolls die.

    What IS reliably exploitable is price. Novig is an exchange running ~1%
    hold against 4-5% at retail books, so its number is frequently better than
    the true probability the rest of the market agrees on. That gap is a real,
    repeatable edge that requires being right about nothing.

    The consensus deliberately EXCLUDES the book being bet, so its own price
    never contributes to the benchmark used to judge it.
    """
    fair_a = mkt.fair_prob(exclude={book})
    if fair_a is None:
        return []

    out: list[Edge] = []
    for side, prob, label in (("a", fair_a, mkt.label_a),
                              ("b", 1.0 - fair_a, mkt.label_b)):
        q = mkt.novig_quote(side) if book == "novig" else next(
            (x for x in (mkt.quotes_a if side == "a" else mkt.quotes_b)
             if x.book == book), None)
        if q is None:
            continue
        e = build_edge("ML", label, None, prob, mkt, side, min_ev_pct=min_ev)
        if e is None:
            continue
        # Re-price against the book actually being bet rather than the best
        # price on the board, which may be at a book with no account.
        from .oddsmath import ev_percent
        e.best_price = q.price
        e.best_book = book
        e.ev_pct = ev_percent(prob, q.price)
        e.market_prob = prob
        if e.ev_pct >= min_ev:
            e.stake = kelly_stake(prob, q.price, bankroll)
            e.note = (f"{matchup}: consensus fair {prob:.1%} "
                      f"(excl {book}) vs {book} {q.price:+.0f}")
            out.append(e)
    return out
