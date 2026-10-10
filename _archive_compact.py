"""Compact the line archive (2026-10-09, user: "how the f*** are we gonna store everything? how do these people do it?").
Raw hourly snapshots re-save every unchanged line (92% never move) plus all PP/UD metadata. Pros store CHANGES only.
This keeps one row per line per CHANGE in lines.db (SQLite), then gzips raw snapshot files older than N days (nothing deleted).

    python _archive_compact.py [days_raw_kept=3]
Tables:
  pp(proj_id, league, player, team, stat, kind, line, start, first_seen, last_seen)   -- a new row only when the number/kind changes
  sharp(book, sport, player, stat, line, p_over, ts)                                  -- a new row only when the price moves >= 0.5 pt
"""
import os, sys, re, json, glob, gzip, sqlite3, datetime

KEEP = int(sys.argv[1]) if len(sys.argv) > 1 else 3
DB = "lines.db"
c = sqlite3.connect(DB)
c.execute("""CREATE TABLE IF NOT EXISTS pp(proj_id TEXT, league INTEGER, player TEXT, team TEXT, stat TEXT, kind TEXT, line REAL,
             start TEXT, first_seen TEXT, last_seen TEXT)""")
c.execute("CREATE INDEX IF NOT EXISTS pp_id ON pp(proj_id)")
c.execute("CREATE TABLE IF NOT EXISTS sharp(book TEXT, sport TEXT, player TEXT, stat TEXT, line REAL, p_over REAL, ts TEXT)")
c.execute("CREATE INDEX IF NOT EXISTS sharp_k ON sharp(book, sport, player, stat, line)")
c.execute("CREATE TABLE IF NOT EXISTS done(file TEXT PRIMARY KEY)")
done = {r[0] for r in c.execute("SELECT file FROM done")}
last_pp = {r[0]: (r[1], r[2]) for r in c.execute("SELECT proj_id, line, kind FROM pp GROUP BY proj_id HAVING max(rowid)")}
last_sh = {(r[0], r[1], r[2], r[3], r[4]): r[5] for r in c.execute("SELECT book, sport, player, stat, line, p_over FROM sharp GROUP BY book, sport, player, stat, line HAVING max(rowid)")}


def read(f):
    op = gzip.open if f.endswith(".gz") else open
    with op(f, "rt", encoding="utf-8") as fh:
        return json.load(fh)


files = sorted(glob.glob(os.path.join("lines_archive", "*", "*.json")) + glob.glob(os.path.join("lines_archive", "*", "*.json.gz")))
n_pp = n_sh = 0
for f in files:
    key = f.replace(".gz", "")
    if key in done:
        continue
    day = os.path.basename(os.path.dirname(f)); base = os.path.basename(key)
    m = re.match(r"(pp|sharp|ud)_?(\d*)_?(\d{6})?", base)
    ts = "%sT%s" % (day, (re.search(r"_(\d{6})\.json$", base) or re.search("(000000)", "000000")).group(1))
    try:
        d = read(f)
    except Exception:
        continue
    if base.startswith("pp_"):
        lg = int(base.split("_")[1])
        inc = {(x["type"], x["id"]): x.get("attributes", {}) for x in d.get("included", [])}
        for x in d.get("data", []):
            a = x.get("attributes", {})
            if "line_score" not in a:
                continue
            rel = ((x.get("relationships") or {}).get("new_player") or {}).get("data") or {}
            pl = inc.get(("new_player", rel.get("id")), {})
            cur = (float(a["line_score"]), a.get("odds_type"))
            if last_pp.get(x["id"]) == cur:
                c.execute("UPDATE pp SET last_seen=? WHERE rowid=(SELECT max(rowid) FROM pp WHERE proj_id=?)", (ts, x["id"]))
                continue
            last_pp[x["id"]] = cur
            c.execute("INSERT INTO pp VALUES (?,?,?,?,?,?,?,?,?,?)", (x["id"], lg, pl.get("name"), pl.get("team"), a.get("stat_type"), cur[1], cur[0],
                                                                   a.get("start_time"), ts, ts)); n_pp += 1
    elif base.startswith("sharp_"):
        for book, sp, pl, st, ln, p in d.get("rows", []):
            k = (book, sp, pl, st, ln)
            if k in last_sh and abs(last_sh[k] - p) < 0.005:
                continue
            last_sh[k] = p
            c.execute("INSERT INTO sharp VALUES (?,?,?,?,?,?,?)", (book, sp, pl, st, ln, p, d.get("ts") or ts)); n_sh += 1
    c.execute("INSERT OR IGNORE INTO done VALUES (?)", (key,))
c.commit()
print("lines.db: +%d PP line changes, +%d sharp price changes  (db %.1f MB)" % (n_pp, n_sh, os.path.getsize(DB) / 1e6))

# gzip raw snapshots older than KEEP days (readable by every tool through read(); nothing is deleted)
cut = (datetime.date.today() - datetime.timedelta(days=KEEP)).isoformat()
before = after = 0
for f in glob.glob(os.path.join("lines_archive", "*", "*.json")):
    if os.path.basename(os.path.dirname(f)) >= cut:
        continue
    raw = open(f, "rb").read(); before += len(raw)
    with gzip.open(f + ".gz", "wb", compresslevel=6) as g:
        g.write(raw)
    after += os.path.getsize(f + ".gz"); os.remove(f)
print("gzipped raw snapshots older than %s: %.2f GB -> %.2f GB" % (cut, before / 1e9, after / 1e9))
