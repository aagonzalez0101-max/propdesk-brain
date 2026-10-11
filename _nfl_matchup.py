"""NFL MATCHUP layer (2026-10-11, user: "show his usual, how this defense holds, what that means").
  python _nfl_matchup.py test      # weekly re-test: does the defense-adjusted projection beat the player's own average on graded PP lines?
  import _nfl_matchup as NM; NM.matchup("Chase Brown", "Rush Yards", "MIA")   # -> dict for the card (info only until the test passes)
Defense factor = what this defense allowed to the player's POSITION per game (weeks so far) / league average for that position.
10/11 result on 799 graded lines: raw avg 57.1%, defense-adjusted 54.8%, matchup flips 48.8%, soft-D overs 43.7% -> INFO ONLY.
The test runs every Monday; `nfl_matchup_status.json` flips to "on" only if adjusted beats raw by 2+ pts on 500+ lines.
"""
import csv, io, re, json, sys, collections, statistics as st, os

norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
f = lambda r, k: float(r.get(k) or 0)
SK = {"Receiving Yards": lambda r: f(r, "receiving_yards"), "Receptions": lambda r: f(r, "receptions"), "Rush Yards": lambda r: f(r, "rushing_yards"),
      "Rush Attempts": lambda r: f(r, "carries"), "Pass Yards": lambda r: f(r, "passing_yards"), "Rec Targets": lambda r: f(r, "targets"),
      "Rush+Rec Yds": lambda r: f(r, "rushing_yards") + f(r, "receiving_yards"), "Pass Attempts": lambda r: f(r, "attempts"),
      "Pass Completions": lambda r: f(r, "completions")}
_R = None


def _rows():
    global _R
    if _R is None:
        _R = list(csv.DictReader(io.StringIO(open("nfl_2026_weekly.csv", encoding="utf-8").read()))) if os.path.exists("nfl_2026_weekly.csv") else []
    return _R


def _allowed(stat):
    A = collections.defaultdict(lambda: collections.defaultdict(float))
    for r in _rows():
        A[(r["opponent_team"], r["position"])][int(r["week"])] += SK[stat](r)
    return A


def factor(stat, dteam, pos, before_week=99):
    A = _allowed(stat)
    mine = [v for w, v in A[(dteam, pos)].items() if w < before_week]
    lg = []
    for (t, p), W in A.items():
        if p == pos:
            x = [v for w, v in W.items() if w < before_week]
            if x:
                lg.append(sum(x) / len(x))
    if len(mine) < 2 or not lg or st.mean(lg) <= 0:
        return None, None, None
    per = sum(mine) / len(mine); fac = per / st.mean(lg)
    teams = sorted({t for (t, p) in A if p == pos}, key=lambda t: -(sum(v for w, v in A[(t, pos)].items() if w < before_week) / max(len([w for w in A[(t, pos)] if w < before_week]), 1)))
    return fac, per, (teams.index(dteam) + 1 if dteam in teams else None)


def matchup(player, stat, opp):
    if stat not in SK:
        return None
    rows = [r for r in _rows() if norm(r["player_display_name"]) == norm(player)]
    if not rows:
        return None
    pos = rows[-1]["position"]; vals = [SK[stat](r) for r in sorted(rows, key=lambda r: int(r["week"]))]
    fac, per, rank = factor(stat, opp, pos)
    if fac is None:
        return None
    avg = sum(vals) / len(vals)
    return dict(pos=pos, avg=avg, fac=fac, allowed=per, rank=rank, proj=avg * fac)


def test():
    rows = json.load(open("_nfl_bt_rows.json")) if os.path.exists("_nfl_bt_rows.json") else []
    X = []
    for r in rows:
        if r.get("stat") in SK and r.get("opp") and r.get("pos"):
            fac, _, _ = factor(r["stat"], r["opp"], r["pos"], r["wk"])
            if fac:
                X.append((r, r["avg"] * fac))
    def hit(Y, proj):
        Y = [(r, a) for r, a in Y if r["line"] > 0 and abs(proj(r, a) - r["line"]) / r["line"] >= 0.10]
        return (sum((r["over"] if proj(r, a) > r["line"] else not r["over"]) for r, a in Y) / len(Y), len(Y)) if Y else (0, 0)
    raw, n1 = hit(X, lambda r, a: r["avg"]); adj, n2 = hit(X, lambda r, a: a)
    on = n2 >= 500 and adj >= raw + 0.02
    json.dump(dict(raw=raw, adj=adj, n=n2, status="on" if on else "info-only"), open("nfl_matchup_status.json", "w"))
    print("NFL matchup test: raw avg %.1f%% (n=%d) vs defense-adjusted %.1f%% (n=%d) -> %s" % (100 * raw, n1, 100 * adj, n2, "ON" if on else "info only"))


if __name__ == "__main__" and sys.argv[1:] == ["test"]:
    test()
