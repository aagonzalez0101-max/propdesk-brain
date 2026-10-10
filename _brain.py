"""CLOUD BRAIN SCHEDULER (2026-10-10, user: "I need everything to be auto"). Runs inside one ~5h40m GitHub Actions job
(.github/workflows/brain.yml) that re-dispatches itself, so the laptop can be OFF.

Each minute it checks what is due (Central time) and has not run yet; after every task it uploads the data bundle so the next run
(and the laptop) start from the newest ledgers.
    08:30  grade      python _daily.py grade      results -> sports.db, every ledger graded, post-mortem
    09:15  lines AM   python _daily.py lines      boards, screens, direction picks, THE CARD -> Discord #card
    21:00  lines PM   python _daily.py lines      tomorrow's card the night before (lock early -- lines get pulled)
    hourly :05        snapshots + raised lines + card-leg line watch + Dota projections
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
DAILY = [("grade", (8, 30), [["_daily.py", "grade"]], 7200, 4200),
         ("lines_am", (9, 15), [["_daily.py", "lines"]], 5400, 2400),
         ("lines_pm", (21, 0), [["_daily.py", "lines"]], 5400, 2400)]
HOURLY = [["_snap_lines.py"], ["_snap_sharps.py"], ["_raised.py"], ["_linewatch.py"], ["_dota_proj.py"]]


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
        if not did:
            time.sleep(60)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 340)
