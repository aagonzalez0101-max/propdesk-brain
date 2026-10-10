"""Hourly SHARP prop snapshots (2026-10-09, user: "how about vs sharps -- do we have where they were?" -> we didn't: only PP/UD boards
were archived). Saves Pinnacle player props (NHL/NFL/WNBA/NBA/CFB/MLB) + FanDuel NFL/CFB alt ladders as compact rows so we can later
measure: where the sharps were when PP posted a line, how they moved by game time, and whether PP lagged them (the speed edge).

    python _snap_sharps.py      # -> lines_archive/<date>/sharp_<HHMMSS>.json  {"ts":..., "rows": [[book, sport, player, stat, line, p_over], ...]}
"""
import os, json, datetime
import _props as P, _mismatch as M

CT = datetime.timezone(datetime.timedelta(hours=-5))
now = datetime.datetime.now(CT)
rows = []
for sp, lid in M.PIN_LEAGUE.items():
    try:
        for (pl, st, ln), p in P.pinnacle_props(lid).items():
            rows.append(["pinnacle", sp, pl, st, ln, round(p, 4)])
    except Exception as e:
        print(sp, "pinnacle:", e)
try:
    import _fanduel
    for sp in ("nfl", "cfb"):
        for (pl, st, ln), p in _fanduel.props(sp).items():
            rows.append(["fanduel", sp.upper(), pl, st, ln, round(p, 4)])
except Exception as e:
    print("fanduel:", e)
d = os.path.join("lines_archive", now.date().isoformat())
os.makedirs(d, exist_ok=True)
f = os.path.join(d, "sharp_%s.json" % now.strftime("%H%M%S"))
json.dump(dict(ts=now.isoformat(timespec="minutes"), rows=rows), open(f, "w"))
print("sharp snapshot: %d prices -> %s" % (len(rows), f))
