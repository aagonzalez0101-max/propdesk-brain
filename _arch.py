"""Archive helpers (2026-10-09): snapshots older than 3 days are gzipped by _archive_compact.py. Every reader uses these so both
plain .json and .json.gz work -- nothing silently drops out of a backtest."""
import glob, gzip, json


def files(pattern):
    """glob that also matches the gzipped copies; sorted by (date folder, file name)."""
    out = glob.glob(pattern) + glob.glob(pattern + ".gz")
    return sorted(out, key=lambda f: f.replace("\\", "/").replace(".gz", ""))


def load(f):
    op = gzip.open if f.endswith(".gz") else open
    with op(f, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def first_line(player, stat, day):
    """10/9: the FIRST number PrizePicks posted for this player/stat on this game day (lines.db, changes-only history). Lets every tool
    flag 'PP RAISED this line' -- raised lines still went OVER 61.8% at the new number (n=55, _clv_pp.py) -> paper reason."""
    import sqlite3, os
    if not os.path.exists("lines.db"):
        return None
    c = sqlite3.connect("lines.db")
    r = c.execute("SELECT line FROM pp WHERE player=? AND stat=? AND kind='standard' AND substr(start,1,10)=? ORDER BY rowid LIMIT 1",
                  (player, stat, day)).fetchone()
    return r[0] if r else None
