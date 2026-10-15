"""THE DAILY LOOP -- every sport screened, every call logged, everything graded, every day (2026-10-01).
User: "we can't get this model going unless we keep testing every day, every sport."

    python _daily.py lines [YYYY-MM-DD]   # snapshot boards + run every screen (paper calls logged) + glitch scan + site data
    python _daily.py grade                # pull results into sports.db + grade every ledger + print the scorecard
    python _daily.py all                  # grade, then lines

Scheduled (Windows Task Scheduler, see _daily_tasks.cmd): 08:30 grade, 09:00 lines, 21:00 lines (night-before = when the
edge exists -- the morning board is already corrected, see memory project_prop_clv). Every step runs on its own; a failed
step is reported, never hidden, and never stops the rest. Output: daily_log/<date>_<mode>.txt.
"""
import sys, os, subprocess, datetime, time

CT = datetime.timezone(datetime.timedelta(hours=-5))
os.makedirs("daily_log", exist_ok=True)
PY = sys.executable


def run(label, args, timeout=1800, log=None, _retry=True):
    t0 = time.time()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        p = subprocess.run([PY] + args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=env)
        out = (p.stdout or "") + (p.stderr or "")
        ok = p.returncode == 0
    except subprocess.TimeoutExpired:
        out, ok = "TIMEOUT after %ds" % timeout, False
    if not ok and _retry and any(w in out for w in ("10054", "URLError", "ConnectionReset", "timed out", "429", "RemoteDisconnected")):
        time.sleep(60)                                    # network blip (10/2: NHL API reset the connection) -> one retry
        return run(label + " (retry)", args, timeout, log, _retry=False)
    line = "%-34s %s  %4.0fs" % (label, "ok  " if ok else "FAIL", time.time() - t0)
    print(line, flush=True)
    if log:
        log.write("\n===== %s =====\n%s\n" % (line, out[-(20000 if "_pair2x" in " ".join(args) else 6000):]))
        log.flush()
    return ok, out


def lines(day, log):
    tomorrow = (datetime.date.fromisoformat(day) + datetime.timedelta(days=1)).isoformat()
    # 10/3 fix: the 21:00 run rebuilt TODAY's five/card after kickoff and overwrote the morning picks -> evening = tomorrow's card
    cday = tomorrow if datetime.datetime.now(CT).hour >= 18 else day
    steps = [
        ("snapshot every board", ["_snap_lines.py"], 900),
        ("capper videos (2eZ + Fantasy Aces)", ["_cappers.py", day], 300),
        ("NHL props (today)", ["_props.py", "nhl", day], 900),
        ("NHL props (tomorrow)", ["_props.py", "nhl", tomorrow], 900),
        ("WNBA props (today)", ["_bball.py", "screen", "wnba", day], 900),
        ("NBA props (today)", ["_bball.py", "screen", "nba", day], 900),
        ("Soccer props (today)", ["_soccer.py", day], 900),
        ("Soccer props (tomorrow)", ["_soccer.py", tomorrow], 900),
        ("NFL props screen", ["_nflscreen.py"], 900),
        ("CFB key-number spreads", ["_cfb.py", "board", day], 300),
        ("CS2 paper card", ["_cs2_live.py", "card"], 900),
        ("CS2 SLIPS (measured rule)", ["_cs2_card.py", cday], 300),
        ("Valorant paper card", ["_val_live.py", "card"], 900),
        ("KBO board v2 (Elo + starter + opener)", ["_kbo_model.py", "board"], 600),
        ("NPB board (starters + ERA gap)", ["_npb.py"], 600),
        ("tennis boost-leg board", ["_tennis_board.py"], 900),
        ("live-ticket watcher (late scratches)", ["_watch.py"], 300),
        ("Golf strokes screen (paper)", ["_golf.py", "screen"], 900),
        ("site: player pages + reads", ["_site_players.py", "WNBA", "NHL", "NFL", "CFB", "SOCCER", "CS2", "VAL"], 1800),   # MLB paused (playoffs)
        ("site: team pages", ["_site_teams.py"], 900),
        ("site: player photos", ["_site_images.py"], 1200),
        ("glitch scan", ["_glitch.py", "--no-refresh"], 600),
        ("sharp vs app mismatches (Pinnacle + FanDuel)", ["_mismatch.py"], 1500),
        ("Dabble prices vs sharp", ["_dabble.py"], 1200),
        ("THE DAILY FIVE (cards/<date>__five.json)", ["_five.py", cday], 1500),
        ("card of the day (cards/<date>.json)", ["_card.py", cday], 300),
        ("A/B card: baseline", ["_card.py", cday, "--config", "baseline"], 300),
        ("A/B card: + calibration", ["_card.py", cday, "--config", "calibration"], 300),
        ("A/B card: + 65% bar", ["_card.py", cday, "--config", "bar_0.65"], 300),
        ("A/B card: + 2-pickers only", ["_card.py", cday, "--config", "only_2picks"], 300),
        ("A/B card: + rank by probability", ["_card.py", cday, "--config", "rank_by_prob"], 300),
        ("A/B card: + WNBA unders only", ["_card.py", cday, "--config", "wnba_unders_only"], 300),
        ("A/B card: + NHL TAKE overs (clear price)", ["_card.py", cday, "--config", "nhl_take_overs"], 300),
        ("A/B card: + NHL shots overs", ["_card.py", cday, "--config", "nhl_shots_over"], 300),
        ("line moves on our legs (CLV)", ["_linemove.py", cday], 600),
        ("DIRECTION picks (NHL/WNBA; NBA from 10/19, paper)", ["_dir_search.py", "score"], 1200),
        ("DOTA 2 kills projections (paper)", ["_dota_proj.py"], 600),
        ("sharp-priced standard board (both sides)", ["_sharp_board.py", "standard"], 1500),
        ("CARD: standard+goblin 2x pairs and 3-pick 6x (PP lines first)", ["_pair2x.py"], 1800),
        ("DRAFTKINGS sides: fair prices to beat -> Discord", ["_sides.py", "post"], 300),
        ("overseas basketball: archive Pinnacle lines", ["_intl_hoops.py", "snap"], 300),
        ("site: page build + log reads", ["_site_build2.py"], 600),
    ]
    for label, args, to in steps:
        run(label, args, to, log)


ES_KEYS = ("CS2", "Valorant", "Dota", "LoL", "esports")                       # esports steps -> the 6:30 AM grade
SHARED_KEYS = ("SLIPS", "model calls", "tracker", "yesterday's card", "recalibrate probabilities", "projection vs actual")   # both runs (idempotent)


def grade(log, part="all"):
    steps = [
        ("sports.db update (results)", ["_db.py", "update"], 3600),
        ("golf rounds update", ["_golf.py", "pull", "2026"], 1800),
        ("CFB box scores update", ["_cfb.py", "pull", "2026"], 2400),
        ("grade model calls (all sports)", ["_calls.py", "grade"], 1800),
        ("HISTORY: grade every archived PP standard line (base rate per market)", ["_history.py", "build"], 1200),
        ("archive: compact to lines.db + gzip raw older than 1 day", ["_archive_compact.py", "1"], 3600),
        ("DIRECTION: rebuild graded lines", ["_direction.py", "build"], 1800),
        ("DIRECTION: grade paper picks", ["_dir_search.py", "grade"], 600),
        ("POST-MORTEM: why each NHL leg hit or missed (yesterday)", ["_postmortem.py"], 900),
        ("Valorant: grade the full priced board", ["_val_grade.py", "val_priced_all.jsonl", "15"], 1500),
        ("Dota 2: pull new pro matches (OpenDota)", ["_dota_pull.py", "200"], 1500),
        ("Dota 2: grade paper legs from the pulled maps", ["_dota_grade.py"], 300),
        ("RAISED lines: grade the over at the raised number (NFL/CFB)", ["_raised_grade.py"], 300),
        ("NFL AGREE: grade raw+role agreement legs", ["_nfl_role.py", "grade"], 300),
        ("NBA ROLE UNDERS: grade", ["_bb_role.py", "grade"], 600),
        # 10/10: CS2/VAL history had stopped at 9/18 and 9/25 (never in the loop) -> the card's last-10 was weeks old
        ("CS2: pull new maps (bo3.gg, newest first, resumable)", ["_cs2_pull.py", "4"], 1500),
        ("Valorant: pull new maps (vlr.gg, newest first, resumable)", ["_val_pull.py", "3"], 1500),
        ("DIRECTION: re-test leave-one-day-out", ["_dir_search.py", "lodo"], 900),
        ("grade site reads", ["_site_grade.py", "grade"], 600),
        ("grade props paper (NHL)", ["_props.py", "grade"], 900),
        ("grade soccer paper", ["_soccer.py", "grade"], 900),
        ("grade CS2 paper (fast, bo3 window)", ["_cs2_grade.py", "3000"], 1500),
        ("grade Valorant paper (vlr.gg)", ["_val_grade.py"], 900),
        ("grade CS2 rule slips", ["_cs2_card.py", "grade"], 120),
        ("grade LoL lines (lolesports feed)", ["_lol_grade.py"], 1800),
        ("KBO results + starters", ["_kbo.py", "pull", "2026"], 900),
        ("KBO starters (new games)", ["_kbo_sp.py", "pull", "2026"], 900),
        ("grade KBO v2 calls", ["_kbo_model.py", "grade"], 120),
        ("grade yesterday's card", ["_card.py", "grade"], 300),
        ("recalibrate probabilities", ["_calibrate.py"], 120),
        ("recalibrate esports models vs graded results (CS2/VAL/Dota)", ["_calib_es.py"], 300),
        ("experiment replay (one change at a time)", ["_experiments.py", "replay"], 300),
        ("Discord: update the pinned Road-to-$500 tracker", ["_tracker.py"], 120),
        ("NFL BETA: grade paper legs when nflverse posts the week", ["_nfl_beta_grade.py"], 300),
        ("SLIPS: grade every logged league slip, bet + paper", ["_paper_slips_grade.py"], 600),
        ("NFL: re-test defense-adjusted projections vs raw (turns ON only if proven)", ["_nfl_matchup.py", "test"], 300),
        ("GATE: grade the legs the form/H2H gate dropped (is it saving us?)", ["_gate_grade.py"], 300),
        ("Discord: projection vs actual for yesterday's legs", ["_projcheck.py", "--post"], 600),
    ]
    for label, args, to in steps:
        run(label, args, to, log)
    print("\n--- SCORECARD ---")
    for label, args in (("TOP-5 BETS vs REST (yesterday)", ["_top5.py"]), ("model calls by sport", ["_calls.py", "report"]), ("site reads", ["_site_grade.py", "report"]),
                        ("real money (mission)", ["_mission.py"])):
        ok, out = run(label, args, 600, log)
        print(out[-2500:])


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    day = next((a for a in sys.argv[2:] if len(a) == 10 and a[4] == "-"), datetime.datetime.now(CT).date().isoformat())
    stamp = datetime.datetime.now(CT).strftime("%Y-%m-%d_%H%M")
    with open(os.path.join("daily_log", "%s_%s.txt" % (stamp, mode)), "w", encoding="utf-8") as log:
        print("DAILY %s %s" % (mode.upper(), stamp))
        if mode in ("grade", "all"):
            grade(log)
        elif mode == "grade_sports":
            grade(log, "sports")
        elif mode == "grade_es":
            grade(log, "es")
        if mode in ("lines", "all"):
            lines(day, log)
