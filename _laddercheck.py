"""The pre-bet check for an MLB side, run BEFORE a ladder rung is named.

Why this exists: on 2026-09-11 the rung went out as "Mariners ML" off the model
and the run-line table alone. The checks that changed the read -- bullpen
availability, the offense against TODAY's starter's hand, and price shopping --
were run only after the money was down. The ladder rule already required the
full checklist; it was skipped because it lived in memory instead of in code.

Every item here is something the ML model cannot see:

  opener      a "starter" with 0 GS or under 3.5 IP per appearance is a bullpen
              game; the model prices him as a starter (Hagen Smith, 2026-09-10)
  bullpen     season pen ERA plus who threw 30+ pitches or pitched twice in the
              last three days -- the model has no bullpen term at all
  vs hand     team OPS against the opposing starter's hand; the model regresses
              this delta hard and can shrink a 58-point swing to nothing
  price       Kalshi vs Pinnacle vs the price actually offered; -167 vs -150 was
              most of the edge on the Mariners ML

Form (last 5 starts, last 14 days) is printed for context only. Measured: season
ratings beat recent form, so it is not a reason to move off a pick.

Usage:
    python _laddercheck.py "Seattle Mariners" "Athletics"          # away home
    python _laddercheck.py "Seattle Mariners" "Athletics" --taken -167
"""
from __future__ import annotations

import collections
import datetime as dt
import io
import json
import sys
import urllib.parse
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace", write_through=True)
API = "https://statsapi.mlb.com/api/v1"


def get(u):
    return json.load(urllib.request.urlopen(
        urllib.request.Request(u, headers={"User-Agent": "M/5"}), timeout=60))


def ip_float(ip):
    w, _, f = str(ip or 0).partition(".")
    return int(w) + int(f or 0) / 3.0


def imp(o):
    return (-o / (-o + 100.0)) if o < 0 else (100.0 / (o + 100.0))


def find_game(day, away, home):
    s = get("%s/schedule?sportId=1&date=%s&hydrate=probablePitcher,lineups" % (API, day))
    for d in s.get("dates", []):
        for g in d["games"]:
            if (g["teams"]["away"]["team"]["name"] == away
                    and g["teams"]["home"]["team"]["name"] == home):
                return g
    return None


def starter(p, day=None):
    """Season line, handedness, and the opener test."""
    if not p:
        return None
    pid = p["id"]
    hand = (get("%s/people/%d" % (API, pid))["people"][0].get("pitchHand") or {}).get("code", "?")
    s = get("%s/people/%d/stats?stats=season&season=2026&group=pitching" % (API, pid))
    sp = [x["stat"] for q in s.get("stats", []) for x in q.get("splits", [])]
    d = sp[0] if sp else {}
    gp = int(d.get("gamesPlayed") or 0)
    gs = int(d.get("gamesStarted") or 0)
    ipa = ip_float(d.get("inningsPitched")) / max(gp, 1)
    gl = get("%s/people/%d/stats?stats=gameLog&season=2026&group=pitching" % (API, pid))
    apps = [x for q in gl.get("stats", []) for x in q.get("splits", [])
            if not day or (x.get("date") or "") < day]   # as-of: no same-day/leaked games
    start_rows = [x for x in apps if int(x["stat"].get("gamesStarted") or 0) >= 1]
    starts = [x["stat"] for x in start_rows][-5:]
    er = sum(int(x.get("earnedRuns") or 0) for x in starts)
    ip = sum(ip_float(x.get("inningsPitched")) for x in starts)
    # recent-role tests (2026-09-14 post-mortem: Reynaldo Lopez was flagged as an
    # OPENER on season IP/app, the label was wrong so the flag was dismissed, and
    # the real problem -- short outings right off the IL -- went unpriced)
    last3 = [ip_float(x["stat"].get("inningsPitched")) for x in start_rows[-3:]]
    short = len(last3) >= 2 and sum(last3) / len(last3) < 4.7
    il_return = False
    import datetime as _dt
    dates = [_dt.date.fromisoformat(x["date"]) for x in apps if x.get("date")]
    if len(dates) >= 2:
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
        # a 21+ day gap among the last 2 appearances = just back from the IL
        il_return = any(g >= 21 for g in gaps[-2:])
    return dict(name=p["fullName"], hand=hand, era=d.get("era"), whip=d.get("whip"),
                hr9=d.get("homeRunsPer9"), gs=gs, ipa=ipa,
                # opener = genuinely not a starter: few starts, or recent starts under 3 IP
                opener=(gs == 0 or (len(last3) >= 2 and max(last3) < 3.0)),
                short=short, last3=last3, il_return=il_return,
                l5_era=(9 * er / ip) if ip else None, l5_er=[int(x.get("earnedRuns") or 0) for x in starts])


def bullpen(tid, day):
    s = get("%s/teams/%d/stats?season=2026&stats=statSplits&group=pitching&sitCodes=rp&gameType=R"
            % (API, tid))
    d = s["stats"][0]["splits"][0]["stat"]
    end = dt.date.fromisoformat(day) - dt.timedelta(days=1)
    start = end - dt.timedelta(days=2)
    sch = get("%s/schedule?sportId=1&teamId=%d&startDate=%s&endDate=%s" % (API, tid, start, end))
    pitches, apps = collections.Counter(), collections.Counter()
    for dd in sch.get("dates", []):
        for g in dd["games"]:
            if g["status"]["detailedState"] != "Final":
                continue
            bx = get("%s/game/%d/boxscore" % (API, g["gamePk"]))
            side = "home" if bx["teams"]["home"]["team"]["id"] == tid else "away"
            t = bx["teams"][side]
            for pid in t.get("pitchers", [])[1:]:          # skip the starter
                pl = t["players"].get("ID%d" % pid, {})
                n = int((pl.get("stats", {}).get("pitching") or {}).get("numberOfPitches") or 0)
                nm = pl.get("person", {}).get("fullName", "?")
                pitches[nm] += n
                apps[nm] += 1
    tired = sorted(((pitches[k], apps[k], k) for k in pitches
                    if pitches[k] >= 30 or apps[k] >= 2), reverse=True)
    return dict(era=d.get("era"), whip=d.get("whip"),
                load=sum(pitches.values()), tired=tired)


def offense(tid, vs_hand):
    code = "vl" if vs_hand == "L" else "vr"
    s = get("%s/teams/%d/stats?season=2026&stats=season&group=hitting&gameType=R" % (API, tid))
    v = get("%s/teams/%d/stats?season=2026&stats=statSplits&group=hitting&sitCodes=%s&gameType=R"
            % (API, tid, code))
    return (s["stats"][0]["splits"][0]["stat"].get("ops"),
            v["stats"][0]["splits"][0]["stat"].get("ops"))


def prices(away, home):
    sys.path.insert(0, ".")
    from betting import freeodds as F
    out = {}
    for src, fn in (("kalshi", F.kalshi_mlb), ("pinnacle", F.pinnacle_mlb)):
        try:
            for e in fn():
                if e["away_team"] == away and e["home_team"] == home:
                    for o in e["bookmakers"][0]["markets"][0]["outcomes"]:
                        out.setdefault(o["name"], {})[src] = o["price"]
        except Exception as exc:
            out.setdefault("_err", {})[src] = str(exc)
    return out


def main():
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    away, home = a[0], a[1]
    day = next((sys.argv[i + 1] for i, x in enumerate(sys.argv) if x == "--day"),
               dt.date.today().isoformat())
    taken = next((float(sys.argv[i + 1]) for i, x in enumerate(sys.argv) if x == "--taken"), None)
    g = find_game(day, away, home)
    if not g:
        print("no game %s @ %s on %s" % (away, home, day))
        return
    flags = []
    A, H = g["teams"]["away"], g["teams"]["home"]
    print("PRE-BET CHECK  %s @ %s  (%s)\n" % (away, home, day))

    sps = {}
    for side, t in (("away", A), ("home", H)):
        sps[side] = starter(t.get("probablePitcher"), day)
    print("STARTERS")
    for side, t in (("away", A), ("home", H)):
        s = sps[side]
        if not s:
            print("  %-22s TBD" % t["team"]["name"])
            flags.append("%s starter TBD" % t["team"]["name"])
            continue
        print("  %-22s %-18s %sHP  ERA %-5s WHIP %-5s HR/9 %-5s  last-5 ERA %s %s"
              % (t["team"]["name"][:22], s["name"][:18], s["hand"], s["era"], s["whip"], s["hr9"],
                 "%.2f" % s["l5_era"] if s["l5_era"] is not None else "-", s["l5_er"]))
        if s["opener"]:
            flags.append("%s is an OPENER (%d GS, recent starts %s IP) -- model prices a bullpen game as a start"
                         % (s["name"], s["gs"], s["last3"]))
        elif s["short"]:
            flags.append("%s is a SHORT STARTER (last starts %s IP) -- model assumes 5-6 IP; bulk goes to the pen"
                         % (s["name"], s["last3"]))
        if s["il_return"]:
            flags.append("%s is JUST BACK FROM A LAYOFF (21+ day gap) -- season ERA is stale, recent line %s ER"
                         % (s["name"], s["l5_er"][-2:]))

    print("\nOFFENSE vs TODAY'S STARTER'S HAND")
    for side, t, opp in (("away", A, "home"), ("home", H, "away")):
        o = sps[opp]
        if not o:
            continue
        season, vs = offense(t["team"]["id"], o["hand"])
        gap = (float(vs) - float(season)) if vs and season else 0.0
        print("  %-22s season %s   vs %sHP %s   (%+.3f)" % (t["team"]["name"][:22], season, o["hand"], vs, gap))
        if gap <= -0.040:
            flags.append("%s hits %+.0f pts of OPS WORSE vs %sHP (%s) -- model shrinks this"
                         % (t["team"]["name"], 1000 * gap, o["hand"], vs))

    print("\nBULLPENS  (season, and arms with 30+ pitches or 2 apps in the last 3 days)")
    for t in (A, H):
        b = bullpen(t["team"]["id"], day)
        print("  %-22s pen ERA %-5s WHIP %-5s  3-day load %d pitches"
              % (t["team"]["name"][:22], b["era"], b["whip"], b["load"]))
        for n, k, nm in b["tired"][:4]:
            print("      %-22s %3d pitches / %d apps" % (nm, n, k))
            # 2 appearances alone is noise (10 pitches over two days is a normal
            # warm-down); flag heavy single outings, real back-to-back work, or 3 apps
            if n >= 35 or (k >= 2 and n >= 25) or k >= 3:
                flags.append("%s: %s likely unavailable (%d pitches / %d apps)" % (t["team"]["name"], nm, n, k))

    print("\nPRICE SHOP")
    px = prices(away, home)
    for team in (away, home):
        p = px.get(team, {})
        print("  %-22s kalshi %-6s pinnacle %-6s" % (team[:22], p.get("kalshi", "-"), p.get("pinnacle", "-")))
    if taken is not None:
        best = [v for t in (away, home) for v in px.get(t, {}).values()]
        side = next((t for t in (away, home)
                     if any(abs(v - taken) < 40 for v in px.get(t, {}).values())), None)
        if side:
            bp = max(px[side].values(), key=lambda v: -imp(v))
            cost = 100 * (imp(taken) - imp(bp))
            print("  offered %+.0f on %s vs best %+.0f  -> %.1fpp paid over the best price"
                  % (taken, side, bp, cost))
            if cost >= 1.5:
                flags.append("price: %+.0f offered vs %+.0f available -- %.1fpp of edge lost at the window"
                             % (taken, bp, cost))

    lu = g.get("lineups") or {}
    posted = bool(lu.get("awayPlayers") and lu.get("homePlayers"))
    print("\nLINEUPS  %s" % ("posted" if posted else "NOT POSTED -- model is on projected lineups"))
    if not posted:
        flags.append("lineups not posted -- the lineup term is the only one with measured signal")

    print("\n" + "=" * 70)
    if flags:
        print("FLAGS (%d) -- things the model cannot see\n" % len(flags))
        for f in flags:
            print("  * " + f)
    else:
        print("no flags")


if __name__ == "__main__":
    main()
