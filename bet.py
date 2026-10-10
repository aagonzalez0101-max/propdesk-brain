"""
Sports betting engine -- command line.

    python bet.py mlb                 Today's MLB board: F5 edges, ranked
    python bet.py mlb --props         ...also pitcher strikeout props (+1 credit/game)
    python bet.py mlb --batters       ...also batter hits/total-bases props (+2 credits/game)
    python bet.py mlb --all           F5 + K props + batter props
    python bet.py mlb --date 2026-08-26
    python bet.py mlb --min-ev 3      Only show edges above 3% EV
    python bet.py mlb --wide          Price F5 across all books (2x credits)
    python bet.py mlb --totals        Include totals (UNVALIDATED - see warning)
    python bet.py mlb --max-games 10  Widen the shortlist (default 6)

    python bet.py ml                  Moneyline: where Novig beats the consensus
    python bet.py ml --sport WNBA     ...any sport
    python bet.py board               Raw market board with fair values & holds
    python bet.py calibrate           Re-measure model-vs-market F5 bias
    python bet.py validate            Score the run model against real outcomes
    python bet.py kbias               Check strikeout projection bias vs reality
    python bet.py score               Forward test: model vs market on settled games

    python bet.py credits             Odds API budget status
    python bet.py bankroll            Show bankroll
    python bet.py deposit <amount>    Add funds
    python bet.py log                 Log a bet interactively
    python bet.py pending             Show unsettled bets
    python bet.py settle <id> <w|l|p> Settle a bet
    python bet.py close <id> <odds>   Record the closing line (for CLV)
    python bet.py stats               Record, ROI, and CLV by market
    python bet.py ladder              Ladder challenge status ($1 -> $1000)

Design in one line: the market decides how good the teams are; the model only
gets a vote on the parts it measures better than the market does.
"""
from __future__ import annotations

import sys
from datetime import date

from rich import box
from rich.console import Console
from rich.table import Table

from betting import db, engine
from betting import mlbdata as D
from betting import oddsapi as O
from betting.market import (archive_market, parse_h2h, parse_market_key,
                            parse_player_props, parse_totals)

console = Console(width=150)
db.init()

MIN_STAKE = 0.50


def _abbr(team: str) -> str:
    """'Arizona Diamondbacks' -> 'Diamondbacks'. Keeps tables readable."""
    return team.split()[-1][:12] if team else "?"


def _arg(flag: str, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


# ------------------------------------------------------------------- MLB board

def cmd_mlb() -> None:
    game_date = _arg("--date", date.today().isoformat())
    min_ev = float(_arg("--min-ev", "2.0"))
    want_props = "--props" in sys.argv or "--all" in sys.argv
    want_totals = "--totals" in sys.argv
    want_batters = "--batters" in sys.argv or "--all" in sys.argv
    # Batter props cost 2 credits per game (hits + total bases). Home runs are
    # quoted by a single book, so the market is too thin to price and it is
    # left out of the default pull.
    batter_games = int(_arg("--batter-games", "3"))
    batter_markets = "batter_hits,batter_total_bases"
    bankroll = db.bankroll_total()

    if bankroll <= 0:
        console.print("[yellow]No bankroll set. Run:  python bet.py deposit 115[/]")
        bankroll = 100.0
        console.print("[dim]Using $100 placeholder for stake sizing.[/dim]\n")

    calib = engine.load_calibration()
    lg = D.league_averages()

    console.print(f"[bold cyan]MLB {game_date}[/]  bankroll ${bankroll:.2f}  "
                  f"min EV {min_ev:.1f}%   [dim]{O.budget_report()}[/dim]\n")

    games = D.schedule(game_date)
    if not games:
        console.print("[yellow]No games scheduled.[/]")
        return

    # Full-game moneylines and totals: one bulk call, used as the anchor.
    #
    # Keyed by EVENT ID, never by (away, home). The bulk feed spans several
    # days, so a team in a three-game series appears repeatedly and a
    # team-keyed dict silently keeps the last one -- anchoring tonight's F5
    # against tomorrow's moneyline, with tomorrow's starting pitchers baked
    # into it. That produces enormous phantom edges that look like the best
    # bets on the board.
    odds_games = O.get_odds("MLB", markets="h2h,totals",
                            regions="us,us_ex", ttl=900)
    fg_by_eid = {}
    totals_by_eid = {}
    for g in odds_games:
        m = parse_h2h(g)
        if not m:
            continue
        eid = g.get("id")
        fg_by_eid[eid] = m
        archive_market("MLB", f"{m.label_b} @ {m.label_a}", m)
        tm = parse_totals(g)
        if tm:
            totals_by_eid[eid] = tm
            archive_market("MLB", f"{m.label_b} @ {m.label_a}", tm)

    # NOTE: do not key events by (away, home) -- the feed spans multiple days,
    # so a team in a series appears more than once and the later date wins.
    # Match on start time via O.match_event instead.
    all_events = O.get_events("MLB")

    all_edges = []
    skipped = []
    calib_pairs = []

    # ---- Shortlist before spending anything -------------------------------
    #
    # F5 odds cost credits per game (they aren't on the bulk endpoint), and
    # pulling all 15 games daily would burn ~900 credits/month against a 460
    # budget. So the model runs first on FREE data and ranks games by how far
    # its F5 delta departs from what books typically shade. We only buy odds
    # for the games most likely to be mispriced.
    from betting import mlbmodel as MM

    max_games = int(_arg("--max-games", "6"))
    # F5 odds live only on the per-event endpoint, priced per region. The
    # exchange region alone (Novig + ProphetX) costs half as much as adding
    # retail and still contains the book actually being bet, plus two of the
    # lowest-hold prices on the board. --wide buys the full 14-book picture
    # when a fair value from two books isn't good enough.
    f5_regions = "us,us_ex" if "--wide" in sys.argv else "us_ex"
    candidates = []
    for g in games:
        ctx = D.game_context(g)
        if ctx["state"] not in ("Preview", "Live"):
            continue
        if O.match_event(odds_games, ctx["away_team"], ctx["home_team"],
                         ctx.get("start")) is None:
            continue
        try:
            pr = MM.project_game(ctx, lg)
        except Exception as exc:
            skipped.append(f"{ctx['away_team']} @ {ctx['home_team']}: {exc}")
            continue
        raw_delta = (pr.f5_home_ml - pr.fg_home_win) * 100.0
        # Interest = how far our de-biased delta strays from the market's
        # typical F5-vs-FG shading. Big strays are where lazy pricing shows.
        interest = abs(raw_delta - calib["mlb_f5_delta_bias"])
        candidates.append((interest, ctx))

    candidates.sort(key=lambda x: -x[0])
    shortlist = candidates[:max_games]
    if len(candidates) > len(shortlist):
        console.print(f"[dim]Shortlisted {len(shortlist)} of {len(candidates)} games "
                      f"by model interest (saves "
                      f"{(len(candidates)-len(shortlist))*2} credits). "
                      f"--max-games to widen.[/dim]\n")

    for interest, ctx in shortlist:
        key = (ctx["away_team"], ctx["home_team"])
        eid = O.match_event(all_events, ctx["away_team"], ctx["home_team"],
                            ctx.get("start"))
        # Anchor on the SAME event, matched by start time.
        odds_eid = O.match_event(odds_games, ctx["away_team"], ctx["home_team"],
                                 ctx.get("start"))
        fg = fg_by_eid.get(odds_eid)

        f5 = None
        if eid:
            try:
                ev = O.get_event_odds("MLB", eid, "h2h_1st_5_innings",
                                      regions=f5_regions, ttl=900)
                f5 = parse_market_key(ev, "h2h_1st_5_innings",
                                      ctx["home_team"], ctx["away_team"])
            except O.BudgetExceeded as e:
                skipped.append(f"{key[0]} @ {key[1]}: {e}")
            except RuntimeError as e:
                skipped.append(f"{key[0]} @ {key[1]}: {e}")

        if f5 is not None:
            archive_market("MLB", f"{key[0]} @ {key[1]}", f5)

        ge = engine.mlb_f5_edges(ctx, fg, f5, lg, calib, bankroll, min_ev)
        all_edges.extend((ctx, e) for e in ge.edges)

        # Full-game totals -- OFF by default, and deliberately so.
        #
        # Measured against a live slate the run model's game-to-game spread is
        # sd 0.55 runs while the market's line spread is sd 0.79, correlation
        # 0.60. Being under-dispersed means the model compresses toward the
        # league average and therefore screams UNDER on every high-total game
        # (it said 7.65 on a 9.0 line, 9.44 on a 10.5). Mean over-probability
        # disagreement was -4.31pp: a systematic under lean, not an edge.
        #
        # The missing inputs are the ones that widen the market's range --
        # wind and weather, umpire strike zone, and the actual posted lineup.
        # Until those are modelled this would bleed money with confidence.
        if want_totals:
            for e in engine.mlb_total_edges(ctx, totals_by_eid.get(odds_eid), lg,
                                            bankroll, max(min_ev, 3.0)):
                all_edges.append((ctx, e))

        if ge.market_fg is not None and ge.market_f5 is not None:
            calib_pairs.append((ge.market_fg, ge.market_f5,
                                ge.projection.fg_home_win,
                                ge.projection.f5_home_ml))

        # Archive every prediction, bet or not, so the model can be scored later.
        if ge.predicted_f5 is not None:
            db.log_prediction(game_date, "MLB", ge.matchup, "F5 ML",
                              ctx["home_team"], ge.predicted_f5,
                              market_prob=ge.market_f5)

        if want_props and eid:
            try:
                ev = O.get_event_odds("MLB", eid, "pitcher_strikeouts",
                                      regions="us", ttl=900)
                props = parse_player_props(ev, "pitcher_strikeouts")
                for _pname, _mkts in props.items():
                    for _m in _mkts:
                        archive_market("MLB", f"{key[0]} @ {key[1]}", _m)
                for e in engine.mlb_strikeout_edges(ctx, props, lg, calib,
                                                    bankroll, max(min_ev, 3.0)):
                    all_edges.append((ctx, e))
            except (O.BudgetExceeded, RuntimeError) as e:
                skipped.append(f"props {key[0]} @ {key[1]}: {e}")

    # ---- batter props: hits / total bases, on the most interesting games ----
    if want_batters:
        lgh = D.league_hitting_rates()
        for interest, ctx in shortlist[:batter_games]:
            key = (ctx["away_team"], ctx["home_team"])
            eid = O.match_event(all_events, ctx["away_team"], ctx["home_team"],
                                ctx.get("start"))
            if not eid:
                continue
            try:
                ev = O.get_event_odds("MLB", eid, batter_markets,
                                      regions="us", ttl=900)
            except (O.BudgetExceeded, RuntimeError) as e:
                skipped.append(f"batters {key[0]} @ {key[1]}: {e}")
                continue
            pm = {}
            for mk in batter_markets.split(","):
                parsed = parse_player_props(ev, mk)
                pm[mk] = parsed
                for _p, _mkts in parsed.items():
                    for _m in _mkts:
                        archive_market("MLB", f"{key[0]} @ {key[1]}", _m)
            try:
                for e in engine.mlb_batter_edges(ctx, pm, lg, lgh, calib,
                                                 bankroll, max(min_ev, 4.0)):
                    all_edges.append((ctx, e))
            except Exception as exc:
                skipped.append(f"batter model {key[0]} @ {key[1]}: {exc}")

    _print_edges(all_edges, game_date)

    if calib_pairs:
        import statistics as st
        md = [(f5 - fg) * 100 for fg, f5, _, _ in calib_pairs]
        xd = [(m5 - mfg) * 100 for _, _, mfg, m5 in calib_pairs]
        console.print(f"\n[dim]Slate check: model F5 delta mean {st.mean(xd):+.2f}pp, "
                      f"market {st.mean(md):+.2f}pp, applied bias correction "
                      f"{calib['mlb_f5_delta_bias']:+.2f}pp "
                      f"(shrink {calib['mlb_f5_shrink']:.2f}).[/dim]")

    if skipped:
        console.print(f"\n[yellow]Skipped {len(skipped)}:[/] {skipped[0]}")
    console.print(f"\n[dim]{O.budget_report()}[/dim]")


def _print_edges(rows, game_date: str) -> None:
    if not rows:
        console.print("[yellow]No bets clear the EV threshold today.[/]")
        console.print("[dim]That is a normal and correct result. Most days the "
                      "market is priced properly and the right move is no action.[/dim]")
        return

    rows.sort(key=lambda x: -x[1].ev_pct)

    t = Table(box=box.SIMPLE_HEAD, header_style="bold")
    t.add_column("#", width=3)
    t.add_column("Bet", width=38)
    t.add_column("Mkt", width=7)
    t.add_column("Model", justify="right", width=7)
    t.add_column("Fair", justify="right", width=7)
    t.add_column("NEED", justify="right", width=7, style="bold yellow")
    t.add_column("Novig", justify="right", width=7)
    t.add_column("Best", justify="right", width=13)
    t.add_column("EV", justify="right", width=7)
    t.add_column("Stake", justify="right", width=7)

    for i, (ctx, e) in enumerate(rows, 1):
        ev_style = "bold green" if e.ev_pct >= 5 else "green"
        nv = f"{e.novig_price:+.0f}" if e.novig_price is not None else "--"
        # The line is part of the bet -- without it "Glasnow Over" is ambiguous
        # when two different lines are both listed.
        label = e.selection if e.point is None else f"{e.selection} {e.point}"
        t.add_row(
            str(i), label[:38], e.market,
            f"{e.model_prob:.1%}", f"{e.fair_price:+.0f}",
            f"{e.min_price:+.0f}", nv,
            f"{e.best_price:+.0f} {e.best_book[:6]}",
            f"[{ev_style}]{e.ev_pct:+.1f}%[/]",
            f"${e.stake:.2f}" if e.stake >= MIN_STAKE else "--",
        )
    console.print(t)
    console.print("[bold yellow]NEED[/] is the worst price still worth taking. "
                  "Check Novig; if it's that number or better, the bet is on.")
    console.print("[dim]Novig prices for props aren't in the API, which is why "
                  "the threshold matters more than the quoted best price.[/dim]")


# ------------------------------------------------------------------- raw board

def cmd_ml() -> None:
    """
    Moneyline board: where Novig's price beats the rest of the market.

    No model opinion is applied. The run model correlates only r=0.50 with the
    market on full-game moneylines, so its view is not worth betting; the
    exploitable part is Novig's low hold producing prices better than the
    consensus true probability.
    """
    sport = (_arg("--sport", "MLB")).upper()
    book = _arg("--book", "novig")
    min_ev = float(_arg("--min-ev", "1.0"))
    bankroll = db.bankroll_total() or 100.0

    games = O.get_odds(sport, markets="h2h", regions="us,us_ex", ttl=900)
    rows = []
    for g in games:
        m = parse_h2h(g)
        if not m:
            continue
        archive_market(sport, f"{m.label_b} @ {m.label_a}", m)
        matchup = f"{_abbr(m.label_b)} @ {_abbr(m.label_a)}"
        for e in engine.ml_price_edges(m, bankroll, book, min_ev, matchup):
            rows.append((matchup, e, m))

    console.print(f"[bold cyan]{sport} moneyline -- {book} vs market consensus[/]  "
                  f"bankroll ${bankroll:.2f}  min EV {min_ev:.1f}%\n")
    if not rows:
        console.print(f"[yellow]No {book} moneyline beats the consensus by "
                      f"{min_ev:.1f}%+ right now.[/]")
        console.print("[dim]Expected most of the time. Novig sits within a "
                      "point of the exchange consensus on nearly every game, "
                      "which is exactly why its prices are good -- edges here "
                      "are occasional, not daily.[/dim]")
    else:
        rows.sort(key=lambda x: -x[1].ev_pct)
        t = Table(box=box.SIMPLE_HEAD, header_style="bold")
        for c in ("#", "Matchup", "Side", "Consensus", "Fair", f"{book}", "EV", "Stake"):
            t.add_column(c, justify="right" if c not in ("Matchup", "Side") else "left")
        for i, (matchup, e, m) in enumerate(rows, 1):
            t.add_row(str(i), matchup, _abbr(e.selection),
                      f"{e.market_prob:.1%}", f"{e.fair_price:+.0f}",
                      f"{e.best_price:+.0f}",
                      f"[green]{e.ev_pct:+.1f}%[/]",
                      f"${e.stake:.2f}" if e.stake >= MIN_STAKE else "--")
        console.print(t)
        console.print(f"[dim]Consensus excludes {book} itself, so its price "
                      f"never helps set the benchmark judging it.[/dim]")

    # Holds, so it's visible how much juice each book is taking.
    hold_rows = []
    for g in games[:1]:
        m = parse_h2h(g)
        if m:
            hold_rows = sorted(m.holds().items(), key=lambda x: x[1])
    if hold_rows:
        lo = ", ".join(f"{b} {h:.2f}%" for b, h in hold_rows[:4])
        hi = ", ".join(f"{b} {h:.2f}%" for b, h in hold_rows[-2:])
        console.print(f"\n[dim]Hold, lowest: {lo}  |  highest: {hi}[/dim]")
    console.print(f"\n[dim]{O.budget_report()}[/dim]")


def cmd_board() -> None:
    sport = (_arg("--sport", "MLB")).upper()
    games = O.get_odds(sport, markets="h2h", regions="us,us_ex", ttl=900)
    t = Table(box=box.SIMPLE_HEAD, title=f"{sport} fair values")
    for c, j in (("Matchup", "left"), ("Books", "right"), ("Fair home", "right"),
                 ("Exch", "right"), ("Retail", "right"), ("Disagree", "right"),
                 ("Best home", "right"), ("Best away", "right"), ("Low hold", "left")):
        t.add_column(c, justify=j)
    for g in games:
        m = parse_h2h(g)
        if not m:
            continue
        c = m.consensus()
        d = m.disagreement_pp()
        ba, bb = m.best("a"), m.best("b")
        holds = sorted(c["holds"].items(), key=lambda x: x[1])
        t.add_row(
            f"{_abbr(m.label_b)} @ {_abbr(m.label_a)}", str(c["n_books"]),
            f"{c['fair_a']:.1%}" if c["fair_a"] else "--",
            f"{c['exchange_fair_a']:.1%}" if c["exchange_fair_a"] else "--",
            f"{c['retail_fair_a']:.1%}" if c["retail_fair_a"] else "--",
            f"{d:+.2f}" if d is not None else "--",
            f"{ba.price:+.0f} {ba.book[:6]}" if ba else "--",
            f"{bb.price:+.0f} {bb.book[:6]}" if bb else "--",
            f"{holds[0][0][:9]} {holds[0][1]:.1f}%" if holds else "--",
        )
    console.print(t)
    console.print(f"\n[dim]{O.budget_report()}[/dim]")


# ----------------------------------------------------------------- calibration

def cmd_calibrate() -> None:
    lg = D.league_averages()
    from betting import mlbmodel as MM

    odds_games = O.get_odds("MLB", markets="h2h", regions="us,us_ex", ttl=900)
    fg_by_eid = {}
    for g in odds_games:
        m = parse_h2h(g)
        if m:
            fg_by_eid[g.get("id")] = m
    # NOTE: do not key events by (away, home) -- the feed spans multiple days,
    # so a team in a series appears more than once and the later date wins.
    # Match on start time via O.match_event instead.
    all_events = O.get_events("MLB")

    pairs = []
    for g in D.schedule():
        ctx = D.game_context(g)
        key = (ctx["away_team"], ctx["home_team"])
        odds_eid = O.match_event(odds_games, ctx["away_team"], ctx["home_team"],
                                 ctx.get("start"))
        if ctx["state"] not in ("Preview", "Live") or odds_eid is None:
            continue
        eid = O.match_event(all_events, ctx["away_team"], ctx["home_team"],
                            ctx.get("start"))
        if not eid:
            continue
        try:
            ev = O.get_event_odds("MLB", eid, "h2h_1st_5_innings",
                                  regions="us_ex", ttl=900)
        except (O.BudgetExceeded, RuntimeError) as e:
            console.print(f"[yellow]stopped: {e}[/]")
            break
        f5 = parse_market_key(ev, "h2h_1st_5_innings", ctx["home_team"], ctx["away_team"])
        fgp = fg_by_eid[odds_eid].fair_prob()
        f5p = f5.fair_prob() if f5 else None
        if fgp is None or f5p is None:
            continue
        pr = MM.project_game(ctx, lg)
        pairs.append((fgp, f5p, pr.fg_home_win, pr.f5_home_ml))

    if len(pairs) < 5:
        console.print(f"[yellow]Only {len(pairs)} usable games -- need 5+.[/]")
        return
    calib = engine.calibrate_f5(pairs)
    engine.save_calibration(calib)
    console.print(f"[green]Calibrated on {len(pairs)} games:[/]")
    for k, v in calib.items():
        console.print(f"  {k:24} {v}")
    console.print("\n[dim]Shrink weight is intentionally not auto-tuned here -- "
                  "agreeing with the market says nothing about who is right. "
                  "It should only rise once forward-tested CLV justifies it.[/dim]")


def cmd_kbias() -> None:
    """Re-measure the strikeout projection bias against actual starts."""
    import statistics as st
    from datetime import timedelta

    from betting import mlbmodel as MM

    lg = D.league_averages()
    seen = {}
    for i in range(1, int(_arg("--days", "8")) + 1):
        d = (date.today() - timedelta(days=i)).isoformat()
        for g in D.schedule(d):
            c = D.game_context(g)
            for s_ in ("home_sp", "away_sp"):
                if c.get(s_):
                    seen[c[s_]["id"]] = c[s_]["fullName"]

    rows = []
    for pid in list(seen)[:80]:
        raw = D.pitcher_stats(pid)
        if not raw or raw.get("ip", 0) < 25:
            continue
        sp = MM.pitcher_true_talent(raw, lg)
        starts = [x for x in D.pitcher_recent_starts(pid, 40) if x["bf"] > 0]
        if len(starts) < 8:
            continue
        proj = MM.project_strikeouts(sp, {"k_rate": lg["k_rate"]}, lg)
        rows.append((proj["mean"], st.mean([x["k"] for x in starts]),
                     sp["exp_ip"], st.mean([x["ip"] for x in starts])))
    if len(rows) < 15:
        console.print(f"[yellow]Only {len(rows)} usable pitchers.[/]")
        return

    pk = [r[0] for r in rows]; ak = [r[1] for r in rows]
    pi = [r[2] for r in rows]; ai = [r[3] for r in rows]

    def corr(a, b):
        ma, mb = st.mean(a), st.mean(b)
        cov = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / len(a)
        return cov / (st.pstdev(a) * st.pstdev(b)) if st.pstdev(a) and st.pstdev(b) else 0

    resid = st.mean(pk) - st.mean(ak)
    console.print(f"[bold]Strikeout projection check[/]  n={len(rows)} pitchers")
    console.print(f"  K/start  projected {st.mean(pk):.3f}  actual {st.mean(ak):.3f}  "
                  f"residual bias {resid:+.3f}  corr {corr(pk, ak):+.3f}")
    console.print(f"  IP/start projected {st.mean(pi):.3f}  actual {st.mean(ai):.3f}  "
                  f"bias {st.mean(pi)-st.mean(ai):+.3f}  corr {corr(pi, ai):+.3f}")
    console.print(f"\n  K_PROJ_BIAS currently {MM.K_PROJ_BIAS:.2f}. "
                  f"Residual above should sit near 0.00 -- if it drifts, "
                  f"set K_PROJ_BIAS to {MM.K_PROJ_BIAS + resid:.2f} in betting/mlbmodel.py")


def cmd_validate() -> None:
    from betting import validate as V
    days = int(_arg("--days", "9"))
    rows = V.collect(days=days, max_games=int(_arg("--max", "140")))
    V.report(rows)


# ---------------------------------------------------------------- bookkeeping

def cmd_score() -> None:
    """Score archived predictions against outcomes -- model vs market."""
    from betting import validate as V
    V.score_predictions(int(_arg("--days", "30")))


def cmd_ladder() -> None:
    """
    Ladder status: one bet a day, entire balance rides each rung.

    Kelly sizing does not apply -- the stake is always everything -- so bet
    SELECTION is the only lever. That makes EV per rung the whole game: the
    edge compounds every step, and so does its absence.
    """
    from betting.oddsmath import american_to_decimal
    import math

    meta = db.ladder_meta()
    rows = db.ladder_rows()
    bal = db.ladder_balance()
    pending = [r for r in rows if r["result"] == "pending"]

    console.print(f"[bold cyan]LADDER[/]  ${meta['start']:.2f} -> ${meta['target']:.0f}"
                  f"   started {meta['started'][:10]}\n")
    if rows:
        t = Table(box=box.SIMPLE_HEAD)
        for c_ in ("rung", "date", "bet", "odds", "stake", "result", "balance"):
            t.add_column(c_, justify="right" if c_ not in ("bet", "date", "result") else "left")
        for r in rows:
            res = r["result"]
            style = ("green" if res == "win" else "red" if res == "loss" else "yellow")
            t.add_row(str(r["rung"]), r["event_date"], r["selection"][:34],
                      f"{r['odds']:+.0f}", f"${r['stake']:.2f}",
                      f"[{style}]{res}[/]",
                      f"${r['balance']:.2f}" if r["balance"] is not None else "--")
        console.print(t)

    settled = [r for r in rows if r["result"] in ("win", "loss", "push")]
    wins = sum(1 for r in settled if r["result"] == "win")
    console.print(f"\n[bold]Balance ${bal:.2f}[/]   rungs cleared {wins}"
                  f"   next rung #{len(rows) + (0 if pending else 1)}")

    if bal <= 0:
        console.print("[red]Ladder busted. Reset with a fresh $1 to start over.[/]")
        return
    if pending:
        p = pending[0]
        console.print(f"[yellow]Rung {p['rung']} pending:[/] {p['selection']} "
                      f"{p['odds']:+.0f} -> ${p['stake']*american_to_decimal(p['odds']):.2f} if it hits")

    # How much further to go, at a few plausible prices.
    need = meta["target"] / max(bal, 0.01)
    console.print(f"\n[dim]${bal:.2f} -> ${meta['target']:.0f} needs {need:.0f}x more:[/dim]")
    for am in (-115, 100, 130, 175):
        d = american_to_decimal(am)
        n = math.ceil(math.log(need) / math.log(d))
        console.print(f"[dim]   {n:2} straight wins at {am:+.0f}[/dim]")


def cmd_credits() -> None:
    console.print(O.budget_report())
    led = O._load_ledger()
    calls = led.get("calls", [])[-12:]
    if calls:
        t = Table(box=box.SIMPLE, title="recent calls")
        t.add_column("when"); t.add_column("endpoint"); t.add_column("cost", justify="right")
        for c in calls:
            t.add_row(c["at"][5:16], c["endpoint"][-46:], str(c["cost"]))
        console.print(t)


def cmd_bankroll() -> None:
    avail, total = db.bankroll(), db.bankroll_total()
    console.print(f"[bold]Available:[/] ${avail:.2f}   "
                  f"[bold]Total (incl. pending):[/] ${total:.2f}")
    s = db.summary()
    if s["n"]:
        console.print(f"Settled: {s['n']}  {s['wins']}W-{s['losses']}L-{s['pushes']}P  "
                      f"P&L ${s['pnl']:+.2f}  ROI {s['roi']:+.1f}%")


def cmd_deposit() -> None:
    if len(sys.argv) < 3:
        console.print("[red]Usage: python bet.py deposit <amount> [platform][/]")
        return
    amt = float(sys.argv[2])
    plat = sys.argv[3] if len(sys.argv) > 3 else "novig"
    db.deposit(amt, plat)
    console.print(f"[green]{'Deposited' if amt>=0 else 'Withdrew'} ${abs(amt):.2f} "
                  f"({plat}). Bankroll now ${db.bankroll_total():.2f}[/]")


def cmd_log() -> None:
    from rich.prompt import FloatPrompt, Prompt
    console.print("[bold]Log a bet[/]")
    event = Prompt.ask("Event (e.g. 'Rays @ Tigers')")
    market = Prompt.ask("Market", default="F5 ML")
    sel = Prompt.ask("Selection")
    odds = FloatPrompt.ask("Odds taken (American)")
    stake = FloatPrompt.ask("Stake")
    mp = Prompt.ask("Model probability (blank if none)", default="")
    book = Prompt.ask("Book", default="novig")
    bid = db.log_bet(date.today().isoformat(), "MLB", event, market, sel,
                     odds, stake, book=book,
                     model_prob=float(mp) if mp else None)
    console.print(f"[green]Logged bet #{bid}.[/] Bankroll now ${db.bankroll():.2f}")


def cmd_pending() -> None:
    rows = db.pending()
    if not rows:
        console.print("No pending bets.")
        return
    t = Table(box=box.SIMPLE_HEAD)
    for c in ("id", "date", "event", "market", "selection", "odds", "stake", "model"):
        t.add_column(c)
    for r in rows:
        t.add_row(str(r["id"]), r["event_date"], r["event"][:26], r["market"],
                  r["selection"][:22], f"{r['odds']:+.0f}", f"${r['stake']:.2f}",
                  f"{r['model_prob']:.1%}" if r["model_prob"] else "--")
    console.print(t)


def cmd_settle() -> None:
    if len(sys.argv) < 4:
        console.print("[red]Usage: python bet.py settle <id> <win|loss|push>[/]")
        return
    m = {"w": "win", "l": "loss", "p": "push", "v": "void"}
    res = m.get(sys.argv[3][0].lower(), sys.argv[3].lower())
    pnl = db.settle(int(sys.argv[2]), res)
    console.print(f"[green]Bet #{sys.argv[2]} settled {res}: ${pnl:+.2f}[/]  "
                  f"Bankroll ${db.bankroll():.2f}")


def cmd_close() -> None:
    if len(sys.argv) < 4:
        console.print("[red]Usage: python bet.py close <id> <closing_odds>[/]")
        return
    v = db.record_closing(int(sys.argv[2]), float(sys.argv[3]))
    verdict = "beat the close" if v > 0 else "lost to the close"
    console.print(f"[green]CLV {v:+.2f}pp -- {verdict}.[/]")


def cmd_stats() -> None:
    s = db.summary()
    if not s["n"]:
        console.print("No settled bets yet.")
        return
    console.print(f"[bold]{s['n']} settled[/]  {s['wins']}W-{s['losses']}L-{s['pushes']}P")
    console.print(f"Staked ${s['staked']:.2f}  P&L ${s['pnl']:+.2f}  ROI {s['roi']:+.1f}%")
    if s["n_clv"]:
        console.print(f"[bold]Average CLV {s['avg_clv']:+.2f}pp[/] over {s['n_clv']} bets"
                      f"  {'-- beating the close' if s['avg_clv']>0 else '-- losing to the close'}")
        console.print("[dim]CLV is the number that matters. Positive CLV with a "
                      "losing record is variance; negative CLV with a winning "
                      "record is luck that will not last.[/dim]")
    rows = db.by_market()
    if rows:
        t = Table(box=box.SIMPLE_HEAD, title="by market")
        for c in ("market", "n", "W", "staked", "P&L", "ROI", "CLV"):
            t.add_column(c, justify="right" if c != "market" else "left")
        for r in rows:
            roi = (r["pnl"] / r["staked"] * 100) if r["staked"] else 0
            t.add_row(r["market"], str(r["n"]), str(r["w"]), f"${r['staked']:.2f}",
                      f"${r['pnl']:+.2f}", f"{roi:+.1f}%",
                      f"{r['avg_clv']:+.2f}" if r["avg_clv"] is not None else "--")
        console.print(t)


COMMANDS = {
    "mlb": cmd_mlb, "ml": cmd_ml, "board": cmd_board, "calibrate": cmd_calibrate,
    "validate": cmd_validate, "kbias": cmd_kbias, "score": cmd_score,
    "ladder": cmd_ladder, "credits": cmd_credits, "bankroll": cmd_bankroll,
    "deposit": cmd_deposit, "log": cmd_log, "pending": cmd_pending,
    "settle": cmd_settle, "close": cmd_close, "stats": cmd_stats,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        console.print(__doc__, highlight=False)
        return
    cmd = sys.argv[1].lower()
    fn = COMMANDS.get(cmd)
    if fn is None:
        console.print(f"[red]Unknown command: {cmd}[/]")
        console.print(__doc__, highlight=False)
        return
    try:
        fn()
    except O.BudgetExceeded as e:
        console.print(f"[red]Credit budget: {e}[/]")
    except KeyboardInterrupt:
        console.print("\n[dim]cancelled[/dim]")


if __name__ == "__main__":
    main()
