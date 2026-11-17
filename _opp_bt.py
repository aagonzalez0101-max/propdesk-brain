"""OPP CHECK BACKTEST (11/15, user: "add all 3"). Old team-level opp check vs the new position-aware one (_stack OPP_MODE=pos),
on every archived PP CLOSING standard line (lines.db, NBA league 7 + NHL league 8) graded against the box. Same 7 checks, same rules;
only the opp vote changes. Reports each measured rule under both modes + what the new check blocked and added.
    python _opp_bt.py [nba|nhl|both]
"""
import sys, json, sqlite3, datetime, collections
import _stack as S

CT = S.CT


def legs(sp):
    L = sqlite3.connect("lines.db", timeout=30); c = sqlite3.connect("sports.db", timeout=60)
    lg = 7 if sp == "nba" else 8
    ST = S.stats_for(sp)
    close = {}
    for pl, team, st, line, start, seen in L.execute("select player, team, stat, line, start, last_seen from pp where league=? and kind='standard'", (lg,)):
        if st not in ST or not pl or not start:
            continue
        day = datetime.datetime.fromisoformat(start).astimezone(CT).date().isoformat()
        k = (day, S.pkey(sp, pl), st)
        if k not in close or (seen or "") > close[k][1]:
            close[k] = (line, seen or "", pl, team, start)
    box = {}
    if sp == "nba":
        for d, p, tm, opp, *v in c.execute("select b.date, b.player, b.team, b.opp, " + ",".join("b." + k for k in S.COLS) + " from nba_box b where b.min>0"):
            box[(d, S.nn(p))] = (tm, opp, dict(zip(S.COLS, [x or 0 for x in v])))
    else:
        for d, p, tm, opp, mn, st in c.execute("select date, player, team, opp, minutes, stats from player_games where sport='NHL' and date>='2026-09-25'"):
            j = json.loads(st)
            if j.get("gtype") == "reg" and mn:
                box[(d, S.pkey("nhl", p))] = (tm, opp, {k: float(j.get(k) or 0) for k in S.NHL_COLS})
    out = collections.defaultdict(list)
    for (day, k, st), (line, _, pl, team, start) in close.items():
        b = box.get((day, k))
        if not b:
            continue
        act = S.val(b[2], ST[st])
        if act != line:
            out[day].append(dict(sport=sp, player=pl, team=b[0], opp=b[1], stat=st, line=line, start=start, act=act))
    return out


def run(sp):
    days = legs(sp)
    S.first_line = lambda *a: None              # line-move check off for both modes (lines.db first_seen is the same either way)
    R = []
    for day in sorted(days):
        D = S.Data(day, sp)
        for leg in days[day]:
            row = {}
            for mode in ("team", "pos"):
                S.OPP_MODE = mode
                r = S.check(D, leg, day)
                if not r:
                    break
                row[mode] = (r["po"], r["pu"], r["v"]["opp"])
            if len(row) == 2:
                R.append(dict(leg, day=day, over=int(leg["act"] > leg["line"]), **row))
    print("%s: %d graded closing lines, %s .. %s" % (sp.upper(), len(R), min(r["day"] for r in R), max(r["day"] for r in R)))

    def rep(lab, X):
        w = sum(X); n = len(X)
        return "%-34s %4d-%-4d %5.1f%%" % (lab, w, n - w, 100 * w / n) if n else "%-34s   --" % lab

    rules = [("UNDER 4+ agree, 0 against", "under", None)] + ([("POINTS OVER 4+ agree, 0 against", "over", {"Points"})] if sp == "nhl" else [])
    for lab, side, stats in rules:
        print("\n " + lab)
        q = lambda r, m: (r[m][1] >= 4 and r[m][0] == 0) if side == "under" else (r[m][0] >= 4 and r[m][1] == 0)
        ok = lambda r: stats is None or r["stat"] in stats
        win = lambda r: (1 - r["over"]) if side == "under" else r["over"]
        old = [r for r in R if ok(r) and q(r, "team")]; new = [r for r in R if ok(r) and q(r, "pos")]
        print("   OLD (team opp)  " + rep("", [win(r) for r in old]))
        print("   NEW (pos opp)   " + rep("", [win(r) for r in new]))
        blk = [r for r in old if not q(r, "pos")]; add = [r for r in new if not q(r, "team")]
        print("   blocked by new  " + rep("(these would have hit)", [win(r) for r in blk]))
        print("   added by new    " + rep("(these hit)", [win(r) for r in add]))
    print("\n opp vote alone:")
    for m in ("team", "pos"):
        print("   %-4s says UNDER %s" % (m, rep("", [1 - r["over"] for r in R if r[m][2] == -1])))
        print("   %-4s says OVER  %s" % (m, rep("", [r["over"] for r in R if r[m][2] == 1])))
        print("   %-4s fires on %d of %d lines" % (m, sum(1 for r in R if r[m][2] != 0), len(R)))


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "both"
    for sp in (["nba", "nhl"] if a == "both" else [a]):
        run(sp)
