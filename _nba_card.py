"""NBA CARD v2 (10/28, user: "trust the stats/data ... add it all together then run it").
Combines, on the value finder's own logged legs (nba_value_paper.jsonl, STANDARD lines only):
  1. RECALIBRATION   p_ctx -> real hit rate, fit walk-forward (only days BEFORE the leg's day), per side, 5-pt bins, shrunk to 50%
  2. FILTER STACK    (measured 10/25: overs role+h2h 67%, unders role+last season 61%)
        this season: 2+ games, ALL on the side;  overs: 2+ meetings with this opponent, 50%+;  unders: last season 60%+ (15+ games)
  3. NEW-TEAM FIX    a player on a new team can't use last season or old-team h2h, so he passes on THIS season only if he has 3+ games
        all on the side at stable minutes (cur avg min >= 85% of exp_min) -- Watson (DEN -> CLE) was vetoed by the old gate
  4. RANK            passing legs sorted by recalibrated p (top-N per day)

    python _nba_card.py replay            # walk-forward replay over every graded day, old gate vs new gate
    python _nba_card.py [YYYY-MM-DD]      # card for a day from that day's logged legs
"""
import sys, json, sqlite3, collections, statistics as st

STAT = {"Points": lambda r: r["pts"], "Rebounds": lambda r: r["reb"], "Assists": lambda r: r["ast"],
        "Pts+Rebs+Asts": lambda r: r["pts"] + r["reb"] + r["ast"], "Pts+Rebs": lambda r: r["pts"] + r["reb"], "Pts+Asts": lambda r: r["pts"] + r["ast"],
        "Rebs+Asts": lambda r: r["reb"] + r["ast"], "3-PT Made": lambda r: r["tpm"], "3-PT Attempted": lambda r: r["tpa"],
        "FG Attempted": lambda r: r["fga"], "FG Made": lambda r: r["fgm"], "Two Pointers Attempted": lambda r: r["fga"] - r["tpa"],
        "Fantasy Score": lambda r: r["pts"] + 1.2 * r["reb"] + 1.5 * r["ast"] + 3 * r["stl"] + 3 * r["blk"] - r["tov"],
        "Free Throws Made": lambda r: r["ftm"], "Steals": lambda r: r["stl"], "Blocked Shots": lambda r: r["blk"], "Blks+Stls": lambda r: r["stl"] + r["blk"],
        "Turnovers": lambda r: r["tov"]}
COLS = "date,team,opp,min,pts,reb,ast,stl,blk,tov,fga,fgm,tpa,tpm,ftm"
THIS, LAST_LO, LAST_HI = "2026-10-20", "2025-10-20", "2026-04-20"


def load_box(players):
    c = sqlite3.connect("sports.db"); B = collections.defaultdict(list)
    for p in players:
        for r in c.execute("select %s,g.stype from nba_box b join nba_games g on g.game_id=b.game_id where b.player=? and (b.dnp=0 or b.dnp is null) and b.date>='2024-10-01' order by b.date" % ",".join("b." + x for x in COLS.split(",")), (p,)):
            d = dict(zip(COLS.split(",") + ["stype"], r))
            if d["min"] is not None and d["stype"] in ("regular", "post"):
                B[p].append(d)
    return B


def feats(r, B):
    rows = B.get(r["player"], []); f = STAT.get(r["stat"])
    if not f:
        return None
    day, ln, over = r["day"], r["line"], r["side"] == "over"
    ok = (lambda v: v > ln) if over else (lambda v: v < ln)
    cur = [x for x in rows if x["date"] >= THIS and x["date"] < day and x["stype"] == "regular"]
    ls = [x for x in rows if LAST_LO <= x["date"] < LAST_HI and x["stype"] == "regular" and x["min"] >= 15]
    hh = [f(x) for x in rows if x["opp"] == r["opp"] and x["date"] < day]
    if len(cur) < 2:
        return None
    cv = [f(x) for x in cur]
    teams_last = {x["team"] for x in ls}
    new_team = bool(ls) and r["team"] not in teams_last
    return dict(n_cur=len(cur), all_cur=all(ok(v) for v in cv), cur_min=st.mean(x["min"] for x in cur), new_team=new_team,
                h2h_n=len(hh), h2h=(sum(ok(v) for v in hh) / len(hh)) if hh else None,
                ls_n=len(ls), ls=(sum(ok(f(x)) for x in ls) / len(ls)) if len(ls) >= 15 else None)


def old_gate(r, x):
    if x["new_team"] or not x["all_cur"]:
        return False
    if r["side"] == "over":
        return x["h2h_n"] >= 2 and x["h2h"] >= .5
    return x["ls"] is not None and x["ls"] >= .6


def new_gate(r, x):
    if not x["all_cur"]:
        return False
    if x["new_team"]:                                          # this season only, stricter
        return x["n_cur"] >= 3 and x["cur_min"] >= 0.85 * r["exp_min"]
    return old_gate(r, x)


class Cal:
    """walk-forward: p_ctx -> hit rate from graded legs of EARLIER days only"""
    def __init__(self, graded):
        self.g = graded

    def p(self, r):
        prior = [x for x in self.g if x["day"] < r["day"] and x["side"] == r["side"] and abs(x["p_ctx"] - r["p_ctx"]) <= .05]
        if len(prior) < 30:
            return 0.5 + (r["p_ctx"] - 0.5) * 0.3                    # too little history: shrink hard toward 50%
        w = sum(x["result"] == "W" for x in prior); n = len(prior)
        return (w + 0.5 * 20) / (n + 20)


def load_rows():
    seen = {}
    for l in open("nba_value_paper.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if r.get("kind") == "standard" and r.get("stat") in STAT:
            seen[(r["day"][:10], r["player"], r["stat"], r["side"])] = dict(r, day=r["day"][:10])
    return list(seen.values())


def rep(name, S):
    if S:
        w = sum(r["result"] == "W" for r in S)
        print("  %-52s %4d-%-4d %5.1f%%" % (name, w, len(S) - w, 100 * w / len(S)))


def replay():
    R = load_rows(); G = [r for r in R if r.get("result") in ("W", "L")]
    B = load_box({r["player"] for r in G}); cal = Cal(G)
    for r in G:
        r["f"] = feats(r, B)
    G = [r for r in G if r["f"]]
    days = sorted({r["day"] for r in G}); print("graded standard legs with 2+ games this season: %d over days %s..%s" % (len(G), days[0], days[-1]))
    evald = [r for r in G if r["day"] >= "2026-10-22"]            # first two days only feed the calibration
    for r in evald:
        r["cp"] = cal.p(r)
    print("\nBASELINE and GATES (days 10/22 on, walk-forward calibration):")
    rep("every leg", evald)
    rep("model p_ctx >= .65 (the old 'confidence')", [r for r in evald if r["p_ctx"] >= .65])
    rep("recalibrated p >= .60 alone", [r for r in evald if r["cp"] >= .60])
    O = [r for r in evald if old_gate(r, r["f"])]; N = [r for r in evald if new_gate(r, r["f"])]
    rep("OLD gate (stack, same-team only)", O)
    rep("  old gate overs", [r for r in O if r["side"] == "over"]); rep("  old gate unders", [r for r in O if r["side"] == "under"])
    rep("NEW gate (stack + new-team fix)", N)
    rep("  new gate overs", [r for r in N if r["side"] == "over"]); rep("  new gate unders", [r for r in N if r["side"] == "under"])
    rep("  ONLY the added new-team legs", [r for r in N if r["f"]["new_team"]])
    for lo in (.50, .55, .58, .60):
        rep("NEW gate + recalibrated p >= %.2f" % lo, [r for r in N if r["cp"] >= lo])
    print("\nTOP-6 PER DAY by recalibrated p, NEW gate (distinct players):")
    tot = [0, 0]
    for d in sorted({r["day"] for r in N}):
        seen, top = set(), []
        for r in sorted([r for r in N if r["day"] == d], key=lambda r: -r["cp"]):
            if r["player"] not in seen:
                seen.add(r["player"]); top.append(r)
            if len(top) == 6:
                break
        w = sum(r["result"] == "W" for r in top); tot[0] += w; tot[1] += len(top)
        print("  %s  %d/%d  %s" % (d, w, len(top), " ".join(("W" if r["result"] == "W" else "L") for r in top)))
    print("  all days top-6: %d/%d = %.1f%%  (2-pick b/e 57.7%%)" % (tot[0], tot[1], 100 * tot[0] / max(1, tot[1])))


def live_lines(day):
    """(player, stat, line) of STANDARD lines on the board file right now -- a logged leg whose line moved or was pulled is stale (10/29 Avdija 11.5 -> 12.5)"""
    d = json.load(open("data/nba_finder/pp_nba_full.json", encoding="utf-8"))
    P = {x["id"]: x["attributes"] for x in d["included"] if x["type"] == "new_player"}
    return {(P.get(a["relationships"]["new_player"]["data"]["id"], {}).get("name"), a["attributes"]["stat_type"], float(a["attributes"]["line_score"]))
            for a in d["data"] if a["attributes"].get("odds_type") == "standard" and a["attributes"]["start_time"].startswith(day)}


def card(day):
    R = load_rows(); G = [r for r in R if r.get("result") in ("W", "L")]
    LIVE = live_lines(day)
    stale = [r for r in R if r["day"] == day and (r["player"], r["stat"], float(r["line"])) not in LIVE]
    T = [r for r in R if r["day"] == day and (r["player"], r["stat"], float(r["line"])) in LIVE]
    if stale:
        print("dropped %d logged legs whose line moved or was pulled: %s" % (len(stale), ", ".join(sorted({"%s %s %g" % (r["player"].split()[-1], r["stat"], r["line"]) for r in stale})[:8])))
    B = load_box({r["player"] for r in R if r["day"] in (day,) or r in G}); cal = Cal(G)
    out = []
    for r in T:
        r["f"] = feats(r, B)
        if r["f"] and new_gate(r, r["f"]):
            r["cp"] = cal.p(r); out.append(r)
    print("NBA CARD v2 %s: %d legs pass the new gate (recalibrated p, one per player)" % (day, len(out)))
    seen = set()
    for r in sorted(out, key=lambda r: -r["cp"]):
        if r["player"] in seen:
            continue
        seen.add(r["player"]); x = r["f"]
        print("  %-22s %-5s %-16s %5s  cal %.0f%% (model %.0f%%) proj %5.1f | this season %d/%d | h2h %s | last szn %s%s" % (
            r["player"][:22], r["side"].upper(), r["stat"][:16], r["line"], 100 * r["cp"], 100 * r["p_ctx"], r["proj"], x["n_cur"], x["n_cur"],
            ("%.0f%% (n=%d)" % (100 * x["h2h"], x["h2h_n"])) if x["h2h"] is not None else "--",
            ("%.0f%%" % (100 * x["ls"])) if x["ls"] is not None else "--", "  NEW TEAM" if x["new_team"] else ""))


if __name__ == "__main__":
    a = sys.argv[1:]
    replay() if a[:1] == ["replay"] else card(a[0] if a else __import__("datetime").date.today().isoformat())
