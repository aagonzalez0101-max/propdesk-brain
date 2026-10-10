"""
Outcome validation: does the run model actually describe reality?

Comparing the model to the market only tells you whether you agree with the
market. This module compares projections to what actually happened on the
field, which is the only test that matters.

One caveat is stated up front because it changes how much these numbers are
worth: season-to-date team and pitcher stats include the games being
predicted, so there is mild look-ahead bias. That makes these results
optimistic in absolute terms. They are still the right test of whether the
run-scoring machinery -- the distribution shape, the park and platoon
adjustments, the starter/bullpen blend -- is sane. A model that cannot hit the
mean run total even WITH look-ahead is broken beyond rescue.

For a bias-free read, forward-test: log predictions before games start and
score them afterwards. `bet.py log` and `bet.py clv` do that.
"""
from __future__ import annotations

import math
import statistics as st
from datetime import date, timedelta

from . import mlbdata as D
from . import mlbmodel as MM


def f5_actual(game_pk: int) -> tuple[float, float] | None:
    """Actual runs scored in innings 1-5 by (home, away)."""
    data = D._get(f"/game/{game_pk}/linescore", ttl=604800,
                  cache_name=f"ls_{game_pk}")
    innings = data.get("innings") or []
    if len(innings) < 5:
        return None
    home = sum((i.get("home", {}) or {}).get("runs", 0) or 0 for i in innings[:5])
    away = sum((i.get("away", {}) or {}).get("runs", 0) or 0 for i in innings[:5])
    return float(home), float(away)


def fg_actual(game_pk: int) -> tuple[float, float] | None:
    data = D._get(f"/game/{game_pk}/linescore", ttl=604800,
                  cache_name=f"ls_{game_pk}")
    t = data.get("teams") or {}
    h, a = (t.get("home") or {}).get("runs"), (t.get("away") or {}).get("runs")
    if h is None or a is None:
        return None
    return float(h), float(a)


def collect(days: int = 10, max_games: int = 140, verbose: bool = True) -> list[dict]:
    """Project every completed game in the window and pair with actual results."""
    lg = D.league_averages()
    out = []
    today = date.today()

    for d in range(1, days + 1):
        day = (today - timedelta(days=d)).isoformat()
        for g in D.schedule(day):
            if len(out) >= max_games:
                break
            ctx = D.game_context(g)
            if ctx["state"] != "Final":
                continue
            if not ctx.get("home_sp") or not ctx.get("away_sp"):
                continue
            act5 = f5_actual(ctx["game_pk"])
            act9 = fg_actual(ctx["game_pk"])
            if act5 is None or act9 is None:
                continue
            try:
                pr = MM.project_game(ctx, lg)
            except Exception:
                continue
            out.append({
                "date": day, "matchup": f"{ctx['away_team']} @ {ctx['home_team']}",
                "proj_f5_home": pr.f5_home, "proj_f5_away": pr.f5_away,
                "proj_f5_total": pr.f5_total, "act_f5_home": act5[0],
                "act_f5_away": act5[1], "act_f5_total": act5[0] + act5[1],
                "proj_fg_total": pr.fg_total, "act_fg_total": act9[0] + act9[1],
                "p_f5_home": pr.f5_home_ml, "p_fg_home": pr.fg_home_win,
                "f5_home_won": 1 if act5[0] > act5[1] else (0 if act5[0] < act5[1] else None),
                "fg_home_won": 1 if act9[0] > act9[1] else 0,
            })
        if verbose:
            print(f"  collected {len(out)} games through {day}", end="\r")
        if len(out) >= max_games:
            break
    if verbose:
        print()
    return out


def _brier(probs: list[float], outcomes: list[int]) -> float:
    return sum((p - o) ** 2 for p, o in zip(probs, outcomes)) / len(probs)


def _logloss(probs: list[float], outcomes: list[int]) -> float:
    eps = 1e-9
    return -sum(o * math.log(max(p, eps)) + (1 - o) * math.log(max(1 - p, eps))
                for p, o in zip(probs, outcomes)) / len(probs)


def report(rows: list[dict]) -> dict:
    """Score the projections and print a readable summary."""
    if len(rows) < 10:
        print("Not enough completed games to validate.")
        return {}

    def corr(a, b):
        ma, mb = st.mean(a), st.mean(b)
        cov = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / len(a)
        sa, sb = st.pstdev(a), st.pstdev(b)
        return cov / (sa * sb) if sa > 0 and sb > 0 else 0.0

    res = {"n": len(rows)}
    print(f"\n{'='*66}\nOUTCOME VALIDATION  ({len(rows)} completed games)\n{'='*66}")

    for label, pk, ak in (("F5 total runs", "proj_f5_total", "act_f5_total"),
                          ("FG total runs", "proj_fg_total", "act_fg_total")):
        p = [r[pk] for r in rows]
        a = [r[ak] for r in rows]
        bias = st.mean(p) - st.mean(a)
        mae = sum(abs(x - y) for x, y in zip(p, a)) / len(p)
        print(f"\n{label}")
        print(f"  projected mean {st.mean(p):5.2f}   actual mean {st.mean(a):5.2f}   bias {bias:+.3f}")
        print(f"  MAE {mae:5.2f}   corr {corr(p, a):+.3f}")
        print(f"  projected sd   {st.pstdev(p):5.2f}   actual sd   {st.pstdev(a):5.2f}")
        res[f"{pk}_bias"] = bias
        res[f"{pk}_corr"] = corr(p, a)

    # Win probability calibration -- the number that decides if we can bet.
    for label, probk, wonk in (("F5 moneyline", "p_f5_home", "f5_home_won"),
                               ("FG moneyline", "p_fg_home", "fg_home_won")):
        pairs = [(r[probk], r[wonk]) for r in rows if r[wonk] is not None]
        if len(pairs) < 10:
            continue
        probs = [p for p, _ in pairs]
        outs = [o for _, o in pairs]
        base = st.mean(outs)
        print(f"\n{label} calibration  (n={len(pairs)}, {'ties dropped' if 'F5' in label else 'no ties'})")
        print(f"  mean predicted {st.mean(probs):.3f}   actual home win rate {base:.3f}")
        print(f"  Brier {_brier(probs, outs):.4f}   vs always-base-rate {_brier([base]*len(outs), outs):.4f}")
        print(f"  LogLoss {_logloss(probs, outs):.4f}   vs always-base-rate {_logloss([base]*len(outs), outs):.4f}")

        # Bucketed calibration
        buckets = [(0, .40), (.40, .45), (.45, .50), (.50, .55), (.55, .60), (.60, 1.0)]
        print(f"  {'bucket':>12} {'n':>4} {'pred':>7} {'actual':>7}")
        for lo, hi in buckets:
            sel = [(p, o) for p, o in pairs if lo <= p < hi]
            if len(sel) < 4:
                continue
            print(f"  {f'{lo:.2f}-{hi:.2f}':>12} {len(sel):>4} "
                  f"{st.mean([p for p,_ in sel]):>7.3f} {st.mean([o for _,o in sel]):>7.3f}")
        res[f"{probk}_brier"] = _brier(probs, outs)
        res[f"{probk}_brier_base"] = _brier([base] * len(outs), outs)

    print(f"\n{'='*66}")
    print("Reminder: season-to-date inputs include these games, so this is")
    print("optimistic. Treat it as a sanity check on the run model, not proof")
    print("of an edge. Forward-tested CLV is the real test.")
    print("=" * 66)
    return res


# ------------------------------------------------- forward test: model vs market

def score_predictions(days_back: int = 30) -> dict:
    """
    The only test that matters: on the same games, is the MODEL closer to the
    truth than the MARKET was?

    Backtesting the raw model against a base rate answers a different and much
    easier question. What we actually bet is a disagreement with a price, so
    the honest scoreboard compares model probability and market probability on
    identical games and asks which had the lower Brier score.

    Historical odds are paid-tier only, so this cannot be run retroactively --
    it scores predictions archived live, before each game, with the market
    price attached. Every daily run adds to it.

    Rule of thumb: below ~100 scored predictions the difference is noise. Do
    not conclude anything from a good week.
    """
    from datetime import date, timedelta

    from . import db
    from . import mlbdata as D

    cutoff = (date.today() - timedelta(days=days_back)).isoformat()
    with db.conn() as c:
        rows = c.execute(
            """SELECT * FROM predictions
               WHERE event_date >= ? AND market_prob IS NOT NULL
               ORDER BY event_date""", (cutoff,)).fetchall()

    scored = []
    for r in rows:
        # Predictions store the HOME side; resolve the game and its F5 result.
        parts = r["event"].split(" @ ")
        if len(parts) != 2:
            continue
        away, home = parts
        games = D.schedule(r["event_date"])
        pk = None
        for g in games:
            ctx = D.game_context(g)
            if ctx["away_team"] == away and ctx["home_team"] == home:
                if ctx["state"] != "Final":
                    break
                pk = ctx["game_pk"]
                break
        if pk is None:
            continue

        if r["market"] == "F5 ML":
            act = f5_actual(pk)
            if act is None or act[0] == act[1]:
                continue          # F5 ties push on a 2-way line
            won = 1 if act[0] > act[1] else 0
        else:
            act = fg_actual(pk)
            if act is None:
                continue
            won = 1 if act[0] > act[1] else 0

        scored.append({"date": r["event_date"], "event": r["event"],
                       "market": r["market"], "model": r["model_prob"],
                       "mkt": r["market_prob"], "won": won})

    if not scored:
        print("No settled predictions with market prices yet.")
        print("Every `bet.py mlb` run archives them; check back after games finish.")
        return {}

    model_b = _brier([s["model"] for s in scored], [s["won"] for s in scored])
    mkt_b = _brier([s["mkt"] for s in scored], [s["won"] for s in scored])
    model_l = _logloss([s["model"] for s in scored], [s["won"] for s in scored])
    mkt_l = _logloss([s["mkt"] for s in scored], [s["won"] for s in scored])

    # Did our disagreements land on the right side?
    right = sum(1 for s in scored
                if (s["model"] > s["mkt"]) == (s["won"] == 1))
    disagreed = [s for s in scored if abs(s["model"] - s["mkt"]) > 0.01]
    right_big = sum(1 for s in disagreed
                    if (s["model"] > s["mkt"]) == (s["won"] == 1))

    n = len(scored)
    print(f"\n{'='*62}\nFORWARD TEST: model vs market  (n={n})\n{'='*62}")
    print(f"  Brier    model {model_b:.4f}   market {mkt_b:.4f}   "
          f"{'MODEL AHEAD' if model_b < mkt_b else 'market ahead'}")
    print(f"  LogLoss  model {model_l:.4f}   market {mkt_l:.4f}   "
          f"{'MODEL AHEAD' if model_l < mkt_l else 'market ahead'}")
    print(f"  Leaned the right way: {right}/{n} ({right/n:.1%})")
    if disagreed:
        print(f"  On {len(disagreed)} real disagreements (>1pp): "
              f"{right_big}/{len(disagreed)} ({right_big/len(disagreed):.1%})")
    if n < 100:
        print(f"\n  n={n} is too small to conclude anything. Need ~100+.")
    print("=" * 62)
    return {"n": n, "model_brier": model_b, "market_brier": mkt_b,
            "right_rate": right / n}
