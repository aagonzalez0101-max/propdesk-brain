"""CLOUD BRAIN SCHEDULER (2026-10-10, user: "I need everything to be auto"). Runs inside one ~5h40m GitHub Actions job
(.github/workflows/brain.yml) that re-dispatches itself, so the laptop can be OFF.

Each minute it checks what is due (Central time) and has not run yet; after every task it uploads the data bundle so the next run
(and the laptop) start from the newest ledgers.
    00:45  grade_sports  python _daily.py grade_sports  results -> sports.db, every sports ledger graded, post-mortem (10/14)
    06:30  grade         python _daily.py grade_es      esports pulls + grading, slips, tracker, scorecard
    07:45  lines AM   python _daily.py lines      boards, screens, direction picks, THE CARD -> Discord #card (~8:20)
    10:00  last call  picks + CS2/Dota projections + card    final check before the 11 AM games lock
    15:00  lines mid  picks + CS2/Dota projections + card    new lines for TONIGHT's games (the 9 PM card is tomorrow's)
    21:00  lines PM   python _daily.py lines      tomorrow's card the night before (lock early -- lines get pulled)
    hourly :05        snapshots + raised lines + card-leg line watch + Dota projections
    :20 / :35 / :50   LINE-RELEASE SCAN (24/7, overnight too; with :05 hourly = every 15 min): fresh picks + CS2 on the live board, posts ONLY new qualifying slips
Done-markers live in _brain_done.json (inside the bundle), so a restarted chain never repeats or skips a slot.
    python _brain.py [minutes=340]
"""
import os, sys, json, time, datetime, subprocess

try:                                                    # 10/10 user: everything in Texas time (Central, DST-aware)
    from zoneinfo import ZoneInfo
    CT = ZoneInfo("America/Chicago")
except Exception:
    CT = datetime.timezone(datetime.timedelta(hours=-5))
DONE_F = "_brain_done.json"
# (name, CT slot, commands, hard timeout s, typical runtime s -- the laptop measured grade ~63 min, lines ~35 min)
# 10/10 user: "games start at 11 AM" -> the morning card must be out by ~8:15, with a last pre-11 AM check. Night games get a 3 PM pass.
# 10/14 user: "grading around 12am for sports, esports around normal time" -> sports grade right after the last West-coast games
# (~12:45 AM; the late tip ends ~midnight), esports + the scorecard keep the 6:30 AM slot (EU/Asia maps finish overnight).
DAILY = [("grade_sports", (0, 45), [["_daily.py", "grade_sports"]], 7200, 3600),
         ("grade", (6, 30), [["_daily.py", "grade_es"]], 7200, 4200),
         ("lines_am", (7, 45), [["_daily.py", "lines"]], 5400, 2400),
         ("lines_10", (10, 0), [["_dir_search.py", "score"], ["_cs2_live.py", "card"], ["_dota_proj.py"], ["_pair2x.py"]], 3000, 900),
         ("lines_mid", (15, 0), [["_dir_search.py", "score"], ["_cs2_live.py", "card"], ["_dota_proj.py"], ["_pair2x.py"]], 3600, 1200),
         # 10/14 user: "most of the wins were here" (tacos + preseason bench unders post in the afternoon) -> a pre-game evening card
         ("lines_eve", (17, 0), [["_promos.py"], ["_dir_search.py", "score"], ["_pair2x.py"]], 2400, 1200),
         ("lines_pm", (21, 0), [["_daily.py", "lines"]], 5400, 2400)]
HOURLY = [["_snap_lines.py"], ["_promos.py"], ["_sides.py", "moves"], ["_snap_sharps.py"], ["_raised.py"], ["_linewatch.py"], ["_dota_proj.py"]]   # 10/13: promos were laptop-only


def load():
    try:
        return json.load(open(DONE_F))
    except Exception:
        return {}


def run(argv, timeout):
    t = time.time()
    try:
        r = subprocess.run([sys.executable] + argv, timeout=timeout, env=dict(os.environ, PYTHONIOENCODING="utf-8", PROPDESK_CLOUD="1"))
        ok = r.returncode == 0
    except subprocess.TimeoutExpired:
        ok = False
    print("  %-28s %s %5.0fs" % (" ".join(argv), "ok  " if ok else "FAIL", time.time() - t), flush=True)


def sync():
    subprocess.run([sys.executable, "_bundle.py", "push", "--cloud"], check=False)


def main(minutes):
    end = time.time() + minutes * 60
    done = load()
    while time.time() < end:
        now = datetime.datetime.now(CT); day = now.date().isoformat()
        did = False
        for name, (h, m), cmds, to, est in DAILY:
            key = "%s %s" % (day, name)
            slot = now.replace(hour=h, minute=m, second=0, microsecond=0)
            # due from its slot until 3 hours later (a chain gap longer than that skips it rather than running stale)
            if key not in done and slot <= now < slot + datetime.timedelta(hours=3):
                if (end - time.time()) < est * 1.3:              # not enough runway left in this job -> leave it for the next run
                    print("%s: %s due but only %.0f min left in this run -- next run takes it" % (now.strftime("%H:%M"), name, (end - time.time()) / 60))
                    break
                print("%s CT -- %s" % (now.strftime("%H:%M"), name), flush=True)
                if name == "grade" and "%s grade_sports" % day not in done:
                    cmds = [["_daily.py", "grade"]]              # the 12:45 AM sports grade was missed (chain gap) -> grade everything now
                for c in cmds:
                    run(c, to)
                done[key] = now.isoformat(timespec="minutes"); json.dump(done, open(DONE_F, "w")); sync(); did = True
                break
        if not did:
            key = "%s %02d hourly" % (day, now.hour)
            if key not in done and now.minute >= 5 and (end - time.time()) > 1500:
                print("%s CT -- hourly" % now.strftime("%H:%M"), flush=True)
                for c in HOURLY:
                    run(c, 1200)
                done[key] = now.isoformat(timespec="minutes")
                done = {k: v for k, v in done.items() if k[:10] >= (now.date() - datetime.timedelta(days=3)).isoformat()}
                json.dump(done, open(DONE_F, "w")); sync(); did = True
        # 15-min cadence (user 10/10 asked for 5; PP 429s under ~25 s/call and a scan takes 5-10 min, so 15 is the safe floor);
        # :05 is the hourly snapshot slot, scans fill :20 / :35 / :50
        if not did and now.minute in (20, 35, 50) and "%s %02d:%02d scan" % (day, now.hour, now.minute) not in done and (end - time.time()) > 900:   # 24/7 (user 10/10: "I should wake up to edge")
            # 10/10 user: "push it". LINE-RELEASE SCANNER every 30 min: early PP lines are the best ones (Hall/Talbot got pulled or raised
            # within hours). Re-score picks + CS2 on the fresh board; post ONLY slips that are new (NEW_ONLY), so Discord stays quiet otherwise.
            print("%s CT -- release scan" % now.strftime("%H:%M"), flush=True)
            for c in (["_dir_search.py", "score"], ["_cs2_live.py", "card"]):
                run(c, 600)
            os.environ["NEW_ONLY"] = "1"; os.environ["SKIP_GOBLINS"] = "1"
            run(["_pair2x.py"], 900)
            os.environ.pop("NEW_ONLY", None)
            done["%s %02d:%02d scan" % (day, now.hour, now.minute)] = now.isoformat(timespec="minutes")
            json.dump(done, open(DONE_F, "w")); sync(); did = True
        if not did:
            # 10/10: lock/skip reactions on #card slips -> ledger + tracker within a minute; push the bundle when a bet got logged
            before = os.path.getmtime("live_paper.jsonl") if os.path.exists("live_paper.jsonl") else 0
            if os.environ.get("DISCORD_BOT_TOKEN"):
                run(["_reactions.py"], 120)
                run(["_ask.py"], 300)                         # 10/16: #ask -- he types a leg, the bot answers within a minute
            if os.path.exists("live_paper.jsonl") and os.path.getmtime("live_paper.jsonl") != before:
                sync()
            time.sleep(60)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 340)
