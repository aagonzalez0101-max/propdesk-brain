"""LAPTOP NIGHTLY (10/24, user: "is play by play on for these games -- keep testing players and team tendencies"). The cloud runs the
daily loop, but play-by-play (nba_pbp.db) is laptop-only, so it only grew when built by hand: 16 of 28 regular-season games by 10/24.
Windows task "PropDesk PBP" runs this at 6:00 AM CT: ingest the last two days of NBA games, then rebuild play-by-play + lineups.

    python _laptop_nightly.py
"""
import os, sys, datetime, subprocess

CT = datetime.timezone(datetime.timedelta(hours=-5))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(os.environ, PYTHONIOENCODING="utf-8")
LOG = os.path.join("daily_log", "laptop_nightly.txt")


def run(args, to=1800):
    p = subprocess.run([sys.executable] + args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=to, env=ENV)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write("%s  %s\n%s\n" % (datetime.datetime.now(CT).strftime("%m/%d %H:%M"), " ".join(args), ((p.stdout or "") + (p.stderr or ""))[-1500:]))


if __name__ == "__main__":
    os.makedirs("daily_log", exist_ok=True)
    today = datetime.datetime.now(CT).date()
    run(["_nba_season.py", "ingest", (today - datetime.timedelta(days=2)).isoformat(), (today - datetime.timedelta(days=1)).isoformat()])
    run(["_nba_pbp.py", "build"])
    run(["_nba_lineups.py", "build"])
