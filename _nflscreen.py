"""Screen tonight's NFL props on each player's own game log, with the two
filters yesterday's 4-2 card said we were missing.

Yesterday, six legs on the opener went 4-2 (+30.3%). Both losers were
predictable from the card itself:

  * Hunter Henry over 3.5 receptions had a 53% own rate -- a coin flip dressed
    as a play. The five legs at 67-82% went 4-1. So: FLOOR at 60%.
  * Rashid Shaheed over 4.5 targets and Cooper Kupp under 4.5 targets were the
    same bet priced twice. JSN took 11 of Seattle's targets and both the WR2
    over and the WR3 under resolved off that one fact. Counting them as two
    independent legs overstates a card's diversification. So: FLAG same-team
    same-stat legs and never let them into one ticket.

The rate itself is deliberately NOT a model. For each posted line we ask how
often this player cleared THIS number, using the raw empirical frequency across
his games rather than a projection off an average -- memory's rate x opportunity
rule. Shrunk with empirical Bayes toward the positional mean so a 3-game sample
cannot post a 100% rate.

Week 1 caveat that applies to every row: 2025 usage may not describe a 2026
role. That is why these are paper unless the role is confirmed.
"""
from __future__ import annotations

import collections
import csv
import io
import json
import sys
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace", write_through=True)

OWN_RATE_FLOOR = 0.60          # Hunter Henry sat at 0.53 and lost
SHRINK_PRIOR = 4.0             # games of positional prior mixed into every rate
STATS = ("https://github.com/nflverse/nflverse-data/releases/download/"
         "stats_player/stats_player_week_%d.csv")

# Underdog display stat -> nflverse column
COL = {
    "Rush Yards": "rushing_yards",
    "Rush Attempts": "carries",
    "Receiving Yards": "receiving_yards",
    "Receptions": "receptions",
    "Targets": "targets",
    "Pass Yards": "passing_yards",
    "Completions": "completions",
    "Pass Attempts": "attempts",
    "Pass TDs": "passing_tds",
    "Rush + Rec Yards": ("rushing_yards", "receiving_yards"),
    "Pass + Rush Yards": ("passing_yards", "rushing_yards"),
    "Interceptions": "passing_interceptions",    # 10/29: was "interceptions" -- not in the current weekly file, so every QB read 0 picks (Love "7/7 INT-free" was really 2/7)
}
# stats that compete for the same team resource -- two legs from the same team
# on any of these are one bet, not two
COMPETES = {"Targets": "targets", "Receptions": "targets",
            "Receiving Yards": "targets",
            "Rush Yards": "carries", "Rush Attempts": "carries"}


def load_logs(season: int) -> dict:
    """player name -> list of per-game rows for that season (regular season)."""
    u = STATS % season
    raw = urllib.request.urlopen(
        urllib.request.Request(u, headers={"User-Agent": "M/5"}),
        timeout=180).read().decode("utf-8", "replace")
    out = collections.defaultdict(list)
    for r in csv.DictReader(io.StringIO(raw)):
        if (r.get("season_type") or "REG") != "REG":
            continue
        out[(r.get("player_display_name") or "").strip()].append(r)
    return out


def val(row, col):
    def one(c):
        try:
            return float(row.get(c) or 0)
        except ValueError:
            return 0.0
    return sum(one(c) for c in col) if isinstance(col, tuple) else one(col)


def rate(logs, col, line, side):
    """Raw empirical hit rate plus the shrunk estimate."""
    vals = [val(r, col) for r in logs]
    if not vals:
        return None
    n = len(vals)
    hit = sum(1 for v in vals
              if (v > line if side == "higher" else v < line))
    raw = hit / n
    # shrink toward 0.5: a 3-game 100% is not a 100% prop
    shrunk = (hit + 0.5 * SHRINK_PRIOR) / (n + SHRINK_PRIOR)
    return dict(n=n, raw=raw, shrunk=shrunk, vals=vals)


def live_lines():
    """10/7: Underdog is closed -> PrizePicks standard NFL lines (league 9). PP stat names mapped onto COL's UD-style names."""
    import _props as P
    PPMAP = {"Rush Yards": "Rush Yards", "Rush Attempts": "Rush Attempts", "Receiving Yards": "Receiving Yards", "Receptions": "Receptions",
             "Rec Targets": "Targets", "Pass Yards": "Pass Yards", "Pass Completions": "Completions", "Pass Attempts": "Pass Attempts",
             "Pass TDs": "Pass TDs", "Rush+Rec Yds": "Rush + Rec Yards", "Pass+Rush Yds": "Pass + Rush Yards", "INT": "Interceptions"}
    rows = []
    for l in P.prizepicks(9, max_age=900):
        if l.get("kind") != "standard" or l["stat"] not in PPMAP:
            continue
        rows.append(("%s vs %s" % (l.get("team"), (l.get("opp") or "")[:4]), l["player"], PPMAP[l["stat"]], l["line"], {"higher": 1.0, "lower": 1.0}))
    return rows


def injuries():
    """ESPN injury report (free). 10/4 user: 'for NFL remember to add the injuries'. -> {player: status}, {team: [(player,pos,status)]}"""
    import requests
    st, byteam = {}, collections.defaultdict(list)
    try:
        d = requests.get("https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries", headers={"User-Agent": "Mozilla/5.0"}, timeout=30).json()
    except Exception as e:
        print("injury feed failed:", e); return st, byteam
    for t in d.get("injuries", []):
        for i in t.get("injuries", []):
            a = i.get("athlete") or {}
            nm, s_ = a.get("displayName"), i.get("status")
            pos = (a.get("position") or {}).get("abbreviation")
            if nm and s_ in ("Out", "Doubtful", "Questionable", "Injured Reserve"):
                st[nm] = s_; byteam[t.get("displayName", "")].append((nm, pos, s_))
    return st, byteam


def main():
    lines = live_lines()
    inj, inj_team = injuries()
    print("injury report: %d skill/other players listed" % len(inj))
    logs25, logs26 = load_logs(2025), load_logs(2026)
    print("live UD NFL lines: %d   2026 logs: %d players   2025 logs: %d players" % (len(lines), len(logs26), len(logs25)))
    print()

    wk_n = collections.Counter(int(r.get("week") or 0) for rs in logs26.values() for r in rs)
    last_wk = max(w for w, n in wk_n.items() if n >= 300)        # last FULL week (Thursday's game alone is ~2 teams)
    out = []
    for ttl, name, stat, sv, opts in lines:
        col = COL.get(stat)
        if col is None or sv is None:
            continue
        if inj.get(name) in ("Out", "Doubtful", "Injured Reserve"):
            continue                                   # listed OUT/DOUBTFUL -> never a leg (UD/PP void at best, a loss at worst)
        g26, g25 = logs26.get(name, []), logs25.get(name, [])
        if not g26 or max(int(r.get("week") or 0) for r in g26) < last_wk:
            continue                                   # didn't play the latest week -> hurt/inactive/role unknown (start-rate-needs-a-date)
        t26 = ((g26[-1].get("team") or g26[-1].get("recent_team") or "").strip()) if g26 else ""
        t25 = ((g25[-1].get("team") or g25[-1].get("recent_team") or "").strip()) if g25 else ""
        moved = bool(t25 and t26 and t25 != t26)
        # CURRENT season first (10/3): 3+ games in 2026 -> 2026 only (the role he has NOW); a mover's 2025 never counts;
        # otherwise 2025 + 2026 together, still needing 6 games
        g = g26 if (len(g26) >= 3 or moved) else g25 + g26
        if len(g) < (3 if g is g26 else 6):
            continue
        try:
            line = float(sv)
        except (TypeError, ValueError):
            continue
        for side, mult in opts.items():
            r = rate(g, col, line, side)
            if not r:
                continue
            try:
                m = float(mult)
            except (TypeError, ValueError):
                continue
            out.append(dict(game=ttl, player=name, stat=stat, line=line,
                            side=side, mult=m, n=r["n"], raw=r["raw"],
                            shrunk=r["shrunk"], last=r["vals"][-5:],
                            team25=t25, team26=t26 or t25, moved=moved, season="2026" if g is g26 else "2025+26",
                            status=inj.get(name, "")))

    passed = [r for r in out if r["shrunk"] >= OWN_RATE_FLOOR]
    passed.sort(key=lambda r: -r["shrunk"])

    print("PROPS CLEARING THE %.0f%% OWN-RATE FLOOR   (%d of %d screened)\n"
          % (100 * OWN_RATE_FLOOR, len(passed), len(out)))
    print("%-22s %-5s %-19s %6s %-6s %4s %6s %6s %5s %s"
          % ("player", "team", "stat", "line", "side", "n", "raw", "shrunk",
             "mult", "flag"))
    for r in passed[:28]:
        flag = ("NEW TEAM %s->%s (2026 games only)" % (r["team25"], r["team26"]) if r["moved"] else "") + ("" if r["season"] == "2026" else " [incl. 2025]")                + (" QUESTIONABLE" if r.get("status") == "Questionable" else "")
        print("%-22s %-5s %-19s %6.1f %-6s %4d %5.0f%% %5.0f%% %5.2f %s"
              % (r["player"][:22], r["team26"], r["stat"][:19], r["line"],
                 r["side"], r["n"], 100 * r["raw"], 100 * r["shrunk"],
                 r["mult"], flag))

    # the correlation filter -- same team, same contested resource
    print("\n\nSAME-RESOURCE CONFLICTS  (never put two of these on one ticket)")
    byres = collections.defaultdict(list)
    for r in passed[:28]:
        res = COMPETES.get(r["stat"])
        if res:
            byres[(r["team26"], res)].append(r)     # TEAM, not game
    found = False
    for (team, res), rs in sorted(byres.items()):
        names = {x["player"] for x in rs}
        if len(names) > 1:
            found = True
            print("  %-4s %-8s ->  %s" % (team, res, ", ".join(sorted(names))))
            print("     these resolve off the same target/carry share; "
                  "they are ONE bet, not several")
    if not found:
        print("  none among the top rows")

    json.dump(passed, open("_nfl_screen_out.json", "w"), indent=1)
    print("\nwrote %d rows -> _nfl_screen_out.json" % len(passed))


if __name__ == "__main__":
    main()
