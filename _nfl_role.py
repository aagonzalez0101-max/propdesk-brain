"""NFL ROLE + VOLUME model (10/13, user: "do what you said ... RB and WR and now TE, QB").
Week 5 showed the misses come from WHO gets the ball (Braelon Allen 116, Ollie Gordon 88), not per-touch efficiency. So:
    projection = player's SHARE of his team's volume (recent-weighted, absent teammates' share handed to the active players)
                 x team VOLUME (team carries / targets / pass attempts per game)
                 x per-touch EFFICIENCY (YPC / yds per target / YPA, blended with last season)
                 [x half-shrunk opponent defense factor, optional]
Positions: RB (rush yds/att, rec), WR/TE (targets, rec, rec yds), QB (attempts, completions, pass yds).
    import _nfl_role as R; R.project("Braelon Allen", "Rush Yards", week=6, absent={"Breece Hall"})
    python _nfl_role.py test 4 5        # walk-forward grade on archived PP lines for those weeks
Absent teammates: live = ESPN Out/Doubtful/IR; backtest proxy = a teammate who held share but has no stat row that week.
"""
import csv, re, sys, os, collections, statistics as st, sqlite3, datetime, json

norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
f = lambda r, k: float(r.get(k) or 0)
W26 = [r for r in csv.DictReader(open("nfl_2026_weekly.csv", encoding="utf-8")) if r.get("season_type", "REG") == "REG"] if os.path.exists("nfl_2026_weekly.csv") else []
_W25 = None


def w25():
    global _W25
    if _W25 is None:
        p = "nfl_2025_weekly.csv"
        if not os.path.exists(p):
            import urllib.request
            open(p, "wb").write(urllib.request.urlopen(urllib.request.Request(
                "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2025.csv", headers={"User-Agent": "x"}), timeout=120).read())
        _W25 = [r for r in csv.DictReader(open(p, encoding="utf-8")) if r.get("season_type", "REG") == "REG"]
    return _W25


# stat -> (volume key, group, efficiency numerator key or None)
STATS = {"Rush Yards": ("carries", "RB", "rushing_yards"), "Rush Attempts": ("carries", "RB", None),
         "Receiving Yards": ("targets", "REC", "receiving_yards"), "Receptions": ("targets", "REC", "receptions"), "Rec Targets": ("targets", "REC", None),
         "Pass Yards": ("attempts", "QB", "passing_yards"), "Pass Attempts": ("attempts", "QB", None), "Pass Completions": ("attempts", "QB", "completions")}
GROUP = {"RB": ("RB",), "REC": ("WR", "TE", "RB"), "QB": ("QB",)}


def _team_week(rows, team, wk, vkey):
    return sum(f(r, vkey) for r in rows if r["team"] == team and int(r["week"]) == wk)


def project(player, stat, week, absent=None, opp=None, use_d=False, rows=None):
    """Walk-forward: only weeks < `week` are used. Returns dict(proj, share, vol, eff, team) or None."""
    rows = W26 if rows is None else rows
    if stat not in STATS:
        return None
    vkey, grp, ekey = STATS[stat]
    n = norm(player)
    mine = sorted([r for r in rows if norm(r["player_display_name"]) == n and int(r["week"]) < week], key=lambda r: int(r["week"]))
    if not mine:
        return None
    team = mine[-1]["team"]
    pos_ok = GROUP[grp]
    tw = sorted({int(r["week"]) for r in rows if r["team"] == team and int(r["week"]) < week})
    if not tw:
        return None
    vol_by_wk = {w: _team_week(rows, team, w, vkey) for w in tw}
    # player's share per week he played (recent-weighted: newest 0.5, then 0.3, then 0.2 spread over the rest)
    sh = [(int(r["week"]), f(r, vkey) / vol_by_wk[int(r["week"])]) for r in mine if r["team"] == team and vol_by_wk.get(int(r["week"]))]
    if not sh:
        return None
    sh.sort()
    wts = [0.5, 0.3] + [0.2 / max(len(sh) - 2, 1)] * max(len(sh) - 2, 0)
    wts = wts[:len(sh)]
    share = sum(w * s for w, (_, s) in zip(wts, reversed(sh))) / sum(wts)
    # absent teammates: their recent-weighted share goes to the active group, proportional to current shares
    absent = {norm(a) for a in (absent or [])}
    if absent:
        mates = collections.defaultdict(list)
        for r in rows:
            if r["team"] == team and int(r["week"]) < week and r["position"] in pos_ok and vol_by_wk.get(int(r["week"])):
                mates[norm(r["player_display_name"])].append((int(r["week"]), f(r, vkey) / vol_by_wk[int(r["week"])]))
        def ws(v):
            v = sorted(v)[-3:]
            return sum(s for _, s in v) / len(v)
        freed = sum(ws(v) for k, v in mates.items() if k in absent)
        active = {k: ws(v) for k, v in mates.items() if k not in absent and v[-1][0] >= tw[-1] - 1}
        tot = sum(active.values())
        if freed > 0 and tot > 0 and n in active:
            share += freed * active[n] / tot
    vol = st.mean(vol_by_wk.values())
    eff = 1.0
    if ekey:
        num = sum(f(r, ekey) for r in mine); den = sum(f(r, vkey) for r in mine)
        p25 = [r for r in w25() if norm(r["player_display_name"]) == n]
        n25, d25 = sum(f(r, ekey) for r in p25), sum(f(r, vkey) for r in p25)
        k = 40.0 if vkey == "carries" else 30.0 if vkey == "targets" else 120.0     # last season = k touches of prior
        lg = {"carries": 4.3, "targets": {"receiving_yards": 7.8, "receptions": 0.65}.get(ekey, 7.8), "attempts": {"passing_yards": 6.7, "completions": 0.64}.get(ekey, 6.7)}[vkey]
        prior = (n25 / d25) if d25 >= 10 else lg
        eff = (num + prior * k) / (den + k) if den + k > 0 else prior
    proj = share * vol * eff
    if use_d and opp:
        ps = mine[-1]["position"]
        key = ekey or vkey
        A = collections.defaultdict(lambda: collections.defaultdict(float))
        for r in rows:
            if int(r["week"]) < week and r["position"] == ps:
                A[r["opponent_team"]][r["week"]] += f(r, key)
        avg = {t: st.mean(v.values()) for t, v in A.items() if len(v) >= 2}
        if opp in avg and avg:
            proj *= 0.5 * (avg[opp] / st.mean(avg.values())) + 0.5
    return dict(proj=proj, share=share, vol=vol, eff=eff, team=team)


def raw_avg(player, stat, week, rows=None):
    """The old way: the player's own blended per-game average (2026 + 4 games of 2025 prior)."""
    rows = W26 if rows is None else rows
    vkey, grp, ekey = STATS[stat]
    key = ekey or vkey
    n = norm(player)
    a = [f(r, key) for r in rows if norm(r["player_display_name"]) == n and int(r["week"]) < week]
    b = [f(r, key) for r in w25() if norm(r["player_display_name"]) == n]
    if not a:
        return None
    return (sum(a) + (st.mean(b) * 4 if b else 0)) / (len(a) + (4 if b else 0))


def test(weeks):
    L = sqlite3.connect("lines.db")
    wk_of = lambda d: 1 + (datetime.date.fromisoformat(d[:10]) - datetime.date(2026, 9, 8)).days // 7
    act = {(norm(r["player_display_name"]), int(r["week"])): r for r in W26}
    pos = {norm(r["player_display_name"]): r["position"] for r in W26}
    lines = {}
    for pl, stat, line, start, ls, opp in L.execute("SELECT player, stat, line, start, last_seen, NULL FROM pp WHERE league=9 AND kind='standard' ORDER BY last_seen"):
        if stat in STATS and start and (ls or "") <= start.replace("T", " ")[:19] + "z":
            lines[(pl, stat, wk_of(start))] = float(line)
    out = []
    for (pl, stat, wk), line in lines.items():
        if wk not in weeks:
            continue
        n = norm(pl); a = act.get((n, wk))
        if not a or line <= 0:
            continue
        vkey, grp, ekey = STATS[stat]
        actual = f(a, ekey or vkey)
        if actual == line:
            continue
        team = a["team"]; ps = pos.get(n, "?")
        # backtest proxy for inactives: teammates in the same group who played last week but have no row this week
        prev = {norm(r["player_display_name"]) for r in W26 if r["team"] == team and int(r["week"]) == wk - 1 and r["position"] in GROUP[grp] and f(r, vkey) >= 3}
        now_ = {norm(r["player_display_name"]) for r in W26 if r["team"] == team and int(r["week"]) == wk}
        absent = prev - now_
        pr = project(pl, stat, wk, absent=absent)
        prd = project(pl, stat, wk, absent=absent, opp=a["opponent_team"], use_d=True)
        rw = raw_avg(pl, stat, wk)
        if not pr or rw is None:
            continue
        out.append(dict(pl=pl, stat=stat, pos=ps, wk=wk, line=line, actual=actual, raw=rw, role=pr["proj"], roled=prd["proj"], absent=bool(absent & {k for k in prev})))
    return out


if __name__ == "__main__" and sys.argv[1:2] == ["test"]:
    weeks = {int(x) for x in sys.argv[2:]} or {4, 5}
    R = test(weeks)
    def rec(S, k, strong=False):
        S = [r for r in S if not strong or abs(r[k] - r["line"]) / r["line"] >= 0.10]
        w = sum((r[k] > r["line"]) == (r["actual"] > r["line"]) for r in S)
        return "%3d-%-3d %3.0f%%" % (w, len(S) - w, 100 * w / max(len(S), 1))
    print("graded lines: %d (weeks %s)" % (len(R), sorted(weeks)))
    print("%-22s %-16s %-16s %-16s | strong (10%%+ off line): raw / role / role+D" % ("group", "raw avg", "ROLE", "ROLE + D"))
    groups = [("ALL", lambda r: True), ("RB", lambda r: r["pos"] == "RB"), ("WR", lambda r: r["pos"] == "WR"), ("TE", lambda r: r["pos"] == "TE"), ("QB", lambda r: r["pos"] == "QB"),
              ("teammate absent", lambda r: r["absent"])]
    for lab, fn in groups:
        S = [r for r in R if fn(r)]
        if S:
            print("%-22s %-16s %-16s %-16s | %s / %s / %s" % (lab + " (%d)" % len(S), rec(S, "raw"), rec(S, "role"), rec(S, "roled"), rec(S, "raw", 1), rec(S, "role", 1), rec(S, "roled", 1)))
    for st_ in sorted({r["stat"] for r in R}):
        S = [r for r in R if r["stat"] == st_]
        print("  %-20s n=%3d  raw %s  role %s  role+D %s" % (st_, len(S), rec(S, "raw"), rec(S, "role"), rec(S, "roled")))
    json.dump(R, open("_nfl_role_test.json", "w"))


def grade():
    """Grade nfl_agree_paper.jsonl legs from the nflverse weekly file (refreshed by _nfl_beta_grade.py each morning)."""
    F = "nfl_agree_paper.jsonl"
    if not os.path.exists(F):
        print("no agree paper yet"); return
    rows = [json.loads(l) for l in open(F, encoding="utf-8") if l.strip()]
    act = {(norm(r["player_display_name"]), int(r["week"])): r for r in W26}
    for r in rows:
        if r.get("result"):
            continue
        a = act.get((norm(r["player"]), r["week"]))
        if not a:
            continue
        vkey, grp, ekey = STATS[r["stat"]]
        v = f(a, ekey or vkey); r["actual"] = v
        r["result"] = "PUSH" if v == r["line"] else ("W" if (v > r["line"]) == (r["side"] == "over") else "L")
    open(F, "w", encoding="utf-8").write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    g = [r for r in rows if r.get("result") in ("W", "L")]
    print("NFL AGREE (raw + role+D) paper: %d-%d (%d open)" % (sum(r["result"] == "W" for r in g), sum(r["result"] == "L" for r in g), sum(1 for r in rows if not r.get("result"))))


if __name__ == "__main__" and sys.argv[1:2] == ["grade"]:
    grade()
