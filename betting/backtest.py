"""
Historical backtest against REAL closing prices.

The Odds API's historical endpoint is paid-only, which for a while made it
impossible to ask the only question that matters: if we had bet this model
yesterday, at the prices actually on the board, would we have made money?

ESPN answers it for free. Its summary endpoint keeps a `pickcenter` block on
completed games carrying the DraftKings closing moneyline and total. One book
rather than a twenty-book consensus, and no first-five-innings market -- but a
real, quoted, two-sided price that existed before the game.

What this can and cannot test:

  ML      -- yes, real closing moneyline, de-vigged from the two sides
  Totals  -- yes, real closing total (juice assumed -110 when not quoted)
  F5      -- NO. Nobody publishes historical first-five lines for free, and F5
             is the market the engine actually likes best. That gap is why the
             live forward test (`bet.py score`) still matters.

Prices are DraftKings closing numbers. Novig would generally have been a
better price, so results here are, if anything, pessimistic on price.
"""
from __future__ import annotations

import statistics as st
from dataclasses import dataclass, field
from datetime import date, timedelta

import requests

from . import mlbdata as D
from . import mlbmodel as MM
from .asof import AsOf as _AsOfProvider
from .oddsmath import (american_to_decimal, devig_american, ev_percent,
                       kelly_fraction)

ESPN_SB = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"
ESPN_SUM = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/summary"


def espn_games(day: str) -> list[dict]:
    """
    Completed games for a date (YYYY-MM-DD) with closing odds and final score.

    Cached, because a finished game's closing line never changes.
    """
    key = day.replace("-", "")
    cached = D._cache_get(f"espn_{key}", 2592000)
    if cached is not None:
        return cached

    try:
        r = requests.get(ESPN_SB, params={"dates": key, "limit": 100}, timeout=30)
        r.raise_for_status()
        events = r.json().get("events", [])
    except (requests.RequestException, ValueError) as e:
        print(f"  [espn] scoreboard {day} failed: {e}")
        return []

    out = []
    for ev in events:
        try:
            comp = ev["competitions"][0]
            if comp.get("status", {}).get("type", {}).get("state") != "post":
                continue
            home = away = None
            for t in comp["competitors"]:
                side = t.get("homeAway")
                rec = {"team": t["team"]["displayName"],
                       "score": int(t.get("score", 0) or 0)}
                if side == "home":
                    home = rec
                else:
                    away = rec
            if not home or not away:
                continue

            odds = _closing_odds(ev["id"])
            if not odds:
                continue
            out.append({
                "date": day, "espn_id": ev["id"],
                "home_team": home["team"], "away_team": away["team"],
                "home_score": home["score"], "away_score": away["score"],
                **odds,
            })
        except (KeyError, IndexError, TypeError, ValueError):
            continue

    D._cache_put(f"espn_{key}", out)
    return out


def _closing_odds(event_id: str) -> dict | None:
    """DraftKings closing moneyline and total from the summary pickcenter."""
    try:
        r = requests.get(ESPN_SUM, params={"event": event_id}, timeout=30)
        r.raise_for_status()
        pc = r.json().get("pickcenter") or []
    except (requests.RequestException, ValueError):
        return None
    if not pc:
        return None

    # Prefer DraftKings; otherwise take whichever book is listed first.
    book = next((p for p in pc if "draftkings" in
                 str(p.get("provider", {}).get("name", "")).lower()), pc[0])
    hml = (book.get("homeTeamOdds") or {}).get("moneyLine")
    aml = (book.get("awayTeamOdds") or {}).get("moneyLine")
    if hml is None or aml is None:
        return None
    return {
        "book": book.get("provider", {}).get("name", "?"),
        "ml_home": float(hml), "ml_away": float(aml),
        "total": book.get("overUnder"),
        "over_odds": float(book.get("overOdds") or -110),
        "under_odds": float(book.get("underOdds") or -110),
    }


# --------------------------------------------------------------------- bets

@dataclass
class SimBet:
    date: str
    matchup: str
    market: str
    selection: str
    price: float
    model_p: float
    market_p: float
    ev: float
    stake: float
    won: int | None = None      # 1 win, 0 loss, None push
    pnl: float = 0.0


@dataclass
class SimResult:
    bets: list[SimBet] = field(default_factory=list)
    skipped: int = 0
    games: int = 0

    def summary(self, label: str) -> None:
        settled = [b for b in self.bets if b.won is not None]
        if not settled:
            print(f"\n{label}: no bets cleared the threshold.")
            return
        w = sum(1 for b in settled if b.won == 1)
        l = len(settled) - w
        staked = sum(b.stake for b in settled)
        pnl = sum(b.pnl for b in settled)
        roi = (pnl / staked * 100) if staked else 0.0
        avg_ev = st.mean([b.ev for b in settled])
        print(f"\n{label}")
        print(f"  record   {w}-{l}  ({w/len(settled):.1%})")
        print(f"  staked   ${staked:.2f}   P&L ${pnl:+.2f}   ROI {roi:+.1f}%")
        print(f"  avg predicted EV {avg_ev:+.1f}%   "
              f"-> expected P&L ${staked*avg_ev/100:+.2f}")


def simulate_day(day: str, bankroll: float = 115.0, min_ev: float = 2.0,
                 total_shrink: float = 0.45, ml_shrink: float = 1.0,
                 verbose: bool = True, flat_stake: float | None = None,
                 point_in_time: bool = True,
                 use_weather: bool = True) -> dict[str, SimResult]:
    """
    Replay one slate: what the model would have bet, at real closing prices.

    ML bets here use the model's own opinion, which is NOT what the live
    engine does -- the engine prices moneylines from market disagreement only,
    because the model correlates just r=0.50 with the market on full-game
    sides. Running it anyway is the honest way to find out whether that
    decision was right.
    """
    # Freeze every model input at the morning of `day`. Without this the
    # model reads season-to-date stats fetched today and silently sees the
    # future -- which showed up as totals returning +34% ROI on month-old
    # games and +2% on games from this week.
    provider = _AsOfProvider(day) if point_in_time else D
    original = MM.D
    MM.D = provider
    try:
        return _simulate(day, provider, bankroll, min_ev, total_shrink,
                         ml_shrink, verbose, flat_stake, use_weather)
    finally:
        MM.D = original


def _simulate(day, D_, bankroll, min_ev, total_shrink, ml_shrink,
              verbose, flat_stake, use_weather=True):
    lg = D_.league_averages()
    games = espn_games(day)
    sched = {}
    for g in D.schedule(day):
        ctx = D.game_context(g)
        sched[(ctx["away_team"], ctx["home_team"])] = ctx

    res = {"ML": SimResult(), "Total": SimResult()}

    for g in games:
        key = (g["away_team"], g["home_team"])
        ctx = sched.get(key)
        if ctx is None or not ctx.get("home_sp") or not ctx.get("away_sp"):
            for r in res.values():
                r.skipped += 1
            continue
        try:
            pr = MM.project_game(ctx, lg, use_weather=use_weather)
        except Exception:
            for r in res.values():
                r.skipped += 1
            continue

        for r in res.values():
            r.games += 1
        matchup = f"{_short(g['away_team'])} @ {_short(g['home_team'])}"
        home_won = 1 if g["home_score"] > g["away_score"] else 0

        # ---- moneyline ----
        fair = devig_american([g["ml_home"], g["ml_away"]])
        mkt_home = fair[0]
        model_home = mkt_home + (pr.fg_home_win - mkt_home) * ml_shrink

        for side, mp, price, sel, won in (
            ("home", model_home, g["ml_home"], g["home_team"], home_won),
            ("away", 1 - model_home, g["ml_away"], g["away_team"], 1 - home_won),
        ):
            ev = ev_percent(mp, price)
            if flat_stake is None:
                if ev < min_ev:
                    continue
                stake = round(bankroll * kelly_fraction(mp, price), 2)
                if stake < 0.25:
                    continue
            else:
                # Capture every candidate at a fixed stake so different
                # selection rules (EV rank vs model confidence) can be
                # compared on identical bets without staking differences
                # confounding the result.
                stake = flat_stake
            pnl = (stake * (american_to_decimal(price) - 1)) if won else -stake
            res["ML"].bets.append(SimBet(
                day, matchup, "ML", _short(sel), price, mp,
                mkt_home if side == "home" else 1 - mkt_home,
                ev, stake, won, pnl))

        # ---- total ----
        line = g.get("total")
        if line is None:
            continue
        line = float(line)
        actual = g["home_score"] + g["away_score"]
        if actual == line:
            continue  # push
        over_won = 1 if actual > line else 0
        mkt_over = devig_american([g["over_odds"], g["under_odds"]])[0]
        model_over_raw, _ = MM.total_over_prob(pr.fg_home, pr.fg_away, line)
        model_over = mkt_over + (model_over_raw - mkt_over) * total_shrink

        for mp, price, sel, won in (
            (model_over, g["over_odds"], f"Over {line}", over_won),
            (1 - model_over, g["under_odds"], f"Under {line}", 1 - over_won),
        ):
            ev = ev_percent(mp, price)
            if flat_stake is None:
                if ev < min_ev:
                    continue
                stake = round(bankroll * kelly_fraction(mp, price), 2)
                if stake < 0.25:
                    continue
            else:
                stake = flat_stake
            pnl = (stake * (american_to_decimal(price) - 1)) if won else -stake
            res["Total"].bets.append(SimBet(
                day, matchup, "Total", sel, price, mp, mkt_over,
                ev, stake, won, pnl))

    return res


def _short(team: str) -> str:
    return team.split()[-1] if team else "?"


def run(days: int = 1, end_offset: int = 1, bankroll: float = 115.0,
        min_ev: float = 2.0, verbose: bool = True) -> dict[str, SimResult]:
    """Replay the last `days` slates ending `end_offset` days ago."""
    combined = {"ML": SimResult(), "Total": SimResult()}
    today = date.today()
    for i in range(end_offset, end_offset + days):
        day = (today - timedelta(days=i)).isoformat()
        out = simulate_day(day, bankroll, min_ev, verbose=verbose)
        for k, r in out.items():
            combined[k].bets.extend(r.bets)
            combined[k].skipped += r.skipped
            combined[k].games += r.games
        if verbose:
            print(f"  {day}: {r.games} games priced", end="\r")
    if verbose:
        print()
    return combined
