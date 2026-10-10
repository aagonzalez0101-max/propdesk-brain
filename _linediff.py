"""Compare the newest line snapshot against an earlier one.

Line movement is the closest thing to a free opinion we get. The market's
overnight drift IS the sharp money's revision, so a price that moves TOWARD our
side is confirmation and one that moves away is the market telling us something
we did not know. Both readings are worth more than a single day's W/L, which is
the whole reason the CLV work existed.

Two rules this file exists to enforce:

  * Compare in PROBABILITY POINTS, not in American odds. A move from -104 to
    -115 and a move from +285 to +265 look similar in odds and are nothing
    alike in probability (5.1pp vs 1.4pp).
  * Steam is directional. Report which SIDE the money came in on, not the
    absolute size of the move, or a market tightening on both sides reads as
    a signal when it is just the book cutting vig into first pitch.

Usage:
    python _linediff.py                 # newest vs previous snapshot
    python _linediff.py 2026-09-10      # newest vs first snapshot of that day
"""
from __future__ import annotations

import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace", write_through=True)

LOG = "line_moves.jsonl"


def imp(o):
    """American odds -> implied probability, vig included."""
    return (-o / (-o + 100.0)) if o < 0 else (100.0 / (o + 100.0))


def load():
    return [json.loads(l) for l in open(LOG, encoding="utf-8") if l.strip()]



def _edge(r):
    """Snapshots written by hand stored raw/cal but no edge -- derive it from the price."""
    if r.get("edge") is not None:
        return r["edge"]
    p = r.get("raw") if r.get("raw") is not None else r.get("cal")
    o = r.get("odds")
    if p is None or o is None:
        return 0.0
    be = abs(o) / (abs(o) + 100) if o < 0 else 100 / (o + 100)
    return p - be

def diff(old, new):
    o = {(r["sel"], r["game"]): r for r in old["ml"]}
    print("ML MOVEMENT   %s  ->  %s\n" % (old["ts"][5:16], new["ts"][5:16]))
    print("%-22s %8s %8s %9s %9s  %s"
          % ("side", "was", "now", "mkt move", "our edge", "read"))
    for r in new["ml"]:
        p = o.get((r["sel"], r["game"]))
        if not p:
            print("%-22s %8s %+8.0f %9s %+8.1fpp  NEW"
                  % (r["sel"][:22], "--", r["odds"], "--", 100 * _edge(r)))
            continue
        move = 100 * (imp(r["odds"]) - imp(p["odds"]))
        # toward us = the price shortened on the side we like
        if abs(move) < 0.5:
            read = "flat"
        elif move > 0:
            read = "TOWARD us -- market agreeing"
        else:
            read = "away -- market fading us"
        print("%-22s %+8.0f %+8.0f %+8.1fpp %+8.1fpp  %s"
              % (r["sel"][:22], p["odds"], r["odds"], move,
                 100 * _edge(r), read))

    ow = {(r["team"], r["line"]): r for r in old.get("runlines", [])}
    moved = []
    for r in new.get("runlines", []):
        p = ow.get((r["team"], r["line"]))
        if not p:
            continue
        m = 100 * (imp(r["odds"]) - imp(p["odds"]))
        if abs(m) >= 1.0:
            moved.append((abs(m), r["team"], r["line"], p["odds"], r["odds"], m,
                          r["ev"]))
    if moved:
        moved.sort(reverse=True)
        print("\nRUN LINES THAT MOVED 1pp OR MORE")
        print("%-22s %6s %8s %8s %9s %8s"
              % ("side", "line", "was", "now", "move", "EV now"))
        for _, t, ln, a, b, m, ev in moved[:14]:
            print("%-22s %+6.1f %+8.0f %+8.0f %+8.1fpp %+7.1f%%"
                  % (t[:22], ln, a, b, m, 100 * ev))
    else:
        print("\nno run line moved as much as 1pp")


if __name__ == "__main__":
    snaps = load()
    if len(snaps) < 2:
        print("only %d snapshot(s) -- take another to diff" % len(snaps))
        sys.exit(0)
    new = snaps[-1]
    if len(sys.argv) > 1:
        cand = [s for s in snaps[:-1] if s.get("day") == sys.argv[1]]
        old = cand[0] if cand else snaps[-2]
    else:
        old = snaps[-2]
    diff(old, new)
