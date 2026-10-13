"""BASKETBALL ROLE model (10/13, user: "do NBA then"). The NFL lesson carried over: the player's own average alone ~ the line; a ROLE
model alone ~ the line; where they AGREE by a margin is the edge. In basketball the role is MINUTES:
    role projection = projected minutes (recent-weighted last 3 games: 0.5 / 0.3 / 0.2 -- catches da Silva-type role jumps)
                      x per-minute production (this season, shrunk to last season with 300 minutes of prior)
    raw  = this season's per-game average (4 games of last season as prior)
    python _bb_role.py test wnba            # walk-forward grade on archived PP lines (lines.db), pre-game logs only
    import _bb_role as B; B.models("nba", "Jalen Brunson", "Points", "2026-10-21")
"""
import sys, os, json, re, sqlite3, datetime, statistics as st, collections
import _bball as BB

norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
LG = {"wnba": 3, "nba": 7, "nbap": 237}


def parts(stat):
    return BB.COMBO.get(norm(stat))


def models(league, player, stat, day, ids=None):
    """(raw, role, proj_min) from games strictly before `day` (YYYY-MM-DD); None if not enough data."""
    pp = parts(stat)
    if not pp:
        return None
    ids = ids or BB.roster("nba" if league == "nbap" else league)
    a = ids.get(norm(player))
    if not a:
        return None
    G = [x for x in BB.logs("nba" if league == "nbap" else league, a[0]) if x["date"] < day and x["min"] > 0]
    if league != "nbap":
        G = [x for x in G if not x.get("pre")]          # 10/13: opening-night lines were projected off preseason minutes (Edwards 22 min)
    if len(G) < 4:
        return None
    cur_season = G[-1]["season"]
    cur = [x for x in G if x["season"] == cur_season]
    prv = [x for x in G if x["season"] != cur_season]
    if len(cur) < 3:
        return None
    val = lambda x: sum(x[p] for p in pp)
    raw = (sum(val(x) for x in cur) + (st.mean(val(x) for x in prv) * 4 if prv else 0)) / (len(cur) + (4 if prv else 0))
    last = cur[-3:][::-1]
    w = [0.5, 0.3, 0.2][:len(last)]
    pmin = sum(wi * x["min"] for wi, x in zip(w, last)) / sum(w)
    m_c, v_c = sum(x["min"] for x in cur), sum(val(x) for x in cur)
    m_p, v_p = sum(x["min"] for x in prv), sum(val(x) for x in prv)
    prior = v_p / m_p if m_p >= 100 else (v_c / m_c if m_c else 0)
    rate = (v_c + prior * 300) / (m_c + 300) if m_c + 300 else prior
    return raw, pmin * rate, pmin


def actual(league, player, stat, day, ids):
    pp = parts(stat); a = ids.get(norm(player))
    if not pp or not a:
        return None
    for x in BB.logs("nba" if league == "nbap" else league, a[0]):
        if x["date"] in (day, (datetime.date.fromisoformat(day) + datetime.timedelta(days=1)).isoformat()) and x["min"] > 0:
            return sum(x[p] for p in pp)
    return None


def test(league):
    ids = BB.roster(league)
    L = sqlite3.connect("lines.db")
    lines = {}
    for pl, stat, line, start, ls in L.execute("SELECT player, stat, line, start, last_seen FROM pp WHERE league=? AND kind='standard' ORDER BY last_seen", (LG[league],)):
        if parts(stat) and start and (ls or "") <= start.replace("T", " ")[:19] + "z" and "+" not in pl:
            d = datetime.datetime.fromisoformat(start).astimezone(datetime.timezone(datetime.timedelta(hours=-5))).date().isoformat()
            lines[(pl, stat, d)] = float(line)
    R = []
    for (pl, stat, d), line in lines.items():
        if d >= datetime.date.today().isoformat():
            continue
        m = models(league, pl, stat, d, ids); a = actual(league, pl, stat, d, ids)
        if not m or a is None or a == line:
            continue
        R.append(dict(pl=pl, stat=stat, day=d, line=line, actual=a, raw=m[0], role=m[1], pmin=m[2]))
    return R


if __name__ == "__main__" and sys.argv[1:2] == ["test"]:
    lg = sys.argv[2] if len(sys.argv) > 2 else "wnba"
    R = test(lg)
    def rec(S, k):
        w = sum((r[k] > r["line"]) == (r["actual"] > r["line"]) for r in S); return "%d-%d (%.0f%%)" % (w, len(S) - w, 100 * w / max(len(S), 1))
    print("%s graded PP lines: %d" % (lg.upper(), len(R)))
    print("  raw average alone   ", rec(R, "raw"))
    print("  role (minutes) alone", rec(R, "role"))
    for t in (0.05, 0.10, 0.15, 0.20):
        S = [r for r in R if (r["raw"] - r["line"]) * (r["role"] - r["line"]) > 0 and min(abs(r["raw"] - r["line"]), abs(r["role"] - r["line"])) / r["line"] >= t]
        print("  BOTH agree, %2d%%+ off line: %s" % (100 * t, rec(S, "raw")))
    S = [r for r in R if (r["raw"] - r["line"]) * (r["role"] - r["line"]) > 0 and min(abs(r["raw"] - r["line"]), abs(r["role"] - r["line"])) / r["line"] >= 0.10]
    for side in ("over", "under"):
        print("     side %-5s %s" % (side, rec([r for r in S if (r["raw"] > r["line"]) == (side == "over")], "raw")))
    json.dump(R, open("_bb_role_test_%s.json" % lg, "w"))


def test_calls(sport, since="2026-09-01"):
    """Backtest on graded calls_log rows (line + actual already settled). sport = 'WNBA' or 'NBA' (NBA here = preseason)."""
    lg = sport.lower()
    ids = BB.roster(lg)
    seen = {}
    for x in open("calls_log.jsonl", encoding="utf-8"):
        r = json.loads(x)
        if r.get("sport") != sport or r.get("actual") is None or (r.get("date") or "") < since or not parts(r["stat"]):
            continue
        m = r.get("mult")
        if isinstance(m, dict):
            m = m.get("over")
        if r.get("venue") == "UD" and m is not None and not (0.85 <= m <= 1.15):
            continue
        if r.get("kind") not in (None, "standard"):
            continue
        seen[(r["date"], r["player"], r["stat"], r["line"])] = r
    R = []
    for (d, pl, stat, line), r in seen.items():
        if r["actual"] == line:
            continue
        m = models(lg, pl, stat, d, ids)
        if m:
            R.append(dict(pl=pl, stat=stat, day=d, line=float(line), actual=float(r["actual"]), raw=m[0], role=m[1], pmin=m[2]))
    return R


if __name__ == "__main__" and sys.argv[1:2] == ["calls"]:
    sp = sys.argv[2]
    R = test_calls(sp)
    def rec(S, k):
        w = sum((r[k] > r["line"]) == (r["actual"] > r["line"]) for r in S); return "%d-%d (%.0f%%)" % (w, len(S) - w, 100 * w / max(len(S), 1))
    print("%s graded call-log lines: %d" % (sp, len(R)))
    print("  raw average alone   ", rec(R, "raw"))
    print("  role (minutes) alone", rec(R, "role"))
    for t in (0.05, 0.10, 0.15, 0.20):
        S = [r for r in R if (r["raw"] - r["line"]) * (r["role"] - r["line"]) > 0 and min(abs(r["raw"] - r["line"]), abs(r["role"] - r["line"])) / r["line"] >= t]
        print("  BOTH agree, %2d%%+ off line: %s" % (100 * t, rec(S, "raw")))
    S = [r for r in R if (r["raw"] - r["line"]) * (r["role"] - r["line"]) > 0 and min(abs(r["raw"] - r["line"]), abs(r["role"] - r["line"])) / r["line"] >= 0.10]
    for side in ("over", "under"):
        print("     side %-5s %s" % (side, rec([r for r in S if (r["raw"] > r["line"]) == (side == "over")], "raw")))
    D = [r for r in R if (r["raw"] - r["line"]) * (r["role"] - r["line"]) < 0 and abs(r["role"] - r["line"]) / r["line"] >= 0.10]
    print("  DISAGREE, role 10%%+ off (role side): %s" % rec(D, "role"))
    json.dump(R, open("_bb_role_calls_%s.json" % sp, "w"))


def grade():
    """Grade nba_role_paper.jsonl (NBA unders where the own average AND the minutes model agree) from ESPN gamelogs."""
    F = "nba_role_paper.jsonl"
    if not os.path.exists(F):
        print("no NBA role paper yet"); return
    rows = [json.loads(l) for l in open(F, encoding="utf-8") if l.strip()]
    ids = BB.roster("nba")
    for r in rows:
        if r.get("result") or r["day"] >= datetime.date.today().isoformat():
            continue
        a = actual("nba", r["player"], r["stat"], r["day"], ids)
        if a is None:
            continue
        r["actual"] = a
        r["result"] = "PUSH" if a == r["line"] else ("W" if a < r["line"] else "L")
    open(F, "w", encoding="utf-8").write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    g = [r for r in rows if r.get("result") in ("W", "L")]
    print("NBA ROLE UNDERS paper: %d-%d (%d open)" % (sum(r["result"] == "W" for r in g), sum(r["result"] == "L" for r in g), sum(1 for r in rows if not r.get("result"))))


if __name__ == "__main__" and sys.argv[1:2] == ["grade"]:
    grade()
