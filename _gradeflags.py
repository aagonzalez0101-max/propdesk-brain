"""Grade the pre-bet flags against what actually happened.

Reads _slatecheck_<day>.json (the flags a day's slate WOULD have shown before
first pitch) plus final scores, and asks the only question that matters: did
picks carrying a flag AGAINST the model's side do worse than clean picks?

A flag is AGAINST the side when it hurts the team we picked:
    opener           our team's "starter" is an opener
    -NN vs xHP       our team hits badly vs today's starter's hand
    pen: X out       one of OUR relievers is unavailable
and FOR the side when the same thing hits the opponent.

Leak note: the slate check pulls season stats as of NOW, so each team's
numbers include up to one or two of the graded games (~1 of 145). Bullpen
workload is keyed to the date and is clean.

Usage:  python _gradeflags.py 2026-09-09 2026-09-10
"""
from __future__ import annotations

import io
import json
import sys
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace", write_through=True)


def get(u):
    return json.load(urllib.request.urlopen(
        urllib.request.Request(u, headers={"User-Agent": "M/5"}), timeout=60))


def dec(o):
    return 1 + (o / 100 if o > 0 else 100 / -o)


def opener_team(day):
    """last name of each probable starter -> team name, for the OPENER flags."""
    s = get("https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=%s&hydrate=probablePitcher" % day)
    out = {}
    for d in s.get("dates", []):
        for g in d["games"]:
            for side in ("away", "home"):
                p = g["teams"][side].get("probablePitcher") or {}
                if p.get("fullName"):
                    out[p["fullName"].split()[-1]] = g["teams"][side]["team"]["name"]
    return out


def classify(flag, side, game, sp_team):
    """+1 = hurts our side, -1 = hurts the opponent, 0 = neutral."""
    away, home = game.split(" @ ")
    opp = home if side == away else away
    short = lambda t: t.split()[-1]
    if flag.startswith("OPENER"):
        nm = flag.split()[1]
        t = sp_team.get(nm)
        return 1 if t == side else -1 if t == opp else 0
    if "vs " in flag and "HP" in flag:
        t = flag.split()[0]
        return 1 if t == short(side) else -1 if t == short(opp) else 0
    if " pen: " in flag:
        t = flag.split()[0]
        return 1 if t == short(side) else -1 if t == short(opp) else 0
    return 0


def main():
    days = sys.argv[1:] or ["2026-09-10"]
    finals = json.load(open("_finals_0909_0910.json", encoding="utf-8"))
    rows = []
    for day in days:
        sc = json.load(open("_slatecheck_%s.json" % day, encoding="utf-8"))
        spt = opener_team(day)
        for r in sc:
            if not r.get("side") or r.get("edge") is None:
                continue
            sc_ = finals.get("%s|%s" % (day, r["game"]))
            if not sc_:
                continue
            away, home = r["game"].split(" @ ")
            won = (sc_[0] > sc_[1]) if r["side"] == away else (sc_[1] > sc_[0])
            cls = [(f, classify(f, r["side"], r["game"], spt)) for f in r["flags"]]
            against = sum(1 for _, c in cls if c > 0)
            forus = sum(1 for _, c in cls if c < 0)
            pl = (dec(r["odds"]) - 1) if won else -1.0
            rows.append(dict(day=day, game=r["game"], side=r["side"], edge=r["edge"], odds=r["odds"],
                             won=won, pl=pl, against=against, forus=forus, cls=cls,
                             score="%d-%d" % tuple(sc_)))

    print("EVERY GRADED PICK  (+ = flag against our side, - = flag against the opponent)\n")
    print("%-10s %-22s %6s %7s %-4s %-6s  %s" % ("day", "side", "edge", "odds", "res", "score", "flags"))
    for r in sorted(rows, key=lambda x: (x["day"], -x["edge"])):
        fl = "  ".join(("+" if c > 0 else "-" if c < 0 else "o") + f for f, c in r["cls"]) or "clean"
        print("%-10s %-22s %+5.1fpp %+7.0f %-4s %-6s  %s"
              % (r["day"][5:], r["side"][:22], 100 * r["edge"], r["odds"],
                 "W" if r["won"] else "L", r["score"], fl))

    def tally(lab, rs):
        if not rs:
            print("  %-40s  n=0" % lab)
            return
        w = sum(r["won"] for r in rs)
        u = sum(r["pl"] for r in rs)
        print("  %-40s %2d-%-2d  %+6.2fu  ROI %+6.1f%%" % (lab, w, len(rs) - w, u, 100 * u / len(rs)))

    print("\nTALLY (1u flat on the model's side)\n")
    g = [r for r in rows if r["edge"] >= 0.05]
    tally("ALL board picks", rows)
    tally("  no flag against our side", [r for r in rows if r["against"] == 0])
    tally("  1+ flag against our side", [r for r in rows if r["against"] >= 1])
    tally("GATED picks (5pp+)", g)
    tally("  gated + clean", [r for r in g if r["against"] == 0])
    tally("  gated + flagged against", [r for r in g if r["against"] >= 1])

    print("\nWHAT THE TOP GATED PICK WOULD HAVE BEEN, PER DAY\n")
    for day in days:
        d = [r for r in g if r["day"] == day]
        if not d:
            continue
        top = max(d, key=lambda r: r["edge"])
        clean = [r for r in d if r["against"] == 0]
        ctop = max(clean, key=lambda r: r["edge"]) if clean else None
        print("  %s  by edge alone : %-22s %s (%s)" % (day, top["side"][:22], "W" if top["won"] else "L", top["score"]))
        if ctop:
            print("  %s  with the check: %-22s %s (%s)%s"
                  % (day, ctop["side"][:22], "W" if ctop["won"] else "L", ctop["score"],
                     "   <- same pick" if ctop is top else "   <- CHANGED"))
        else:
            print("  %s  with the check: every gated pick carried a flag against it" % day)


if __name__ == "__main__":
    main()
