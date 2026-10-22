"""NBA PAPER LEDGER (10/22, user: "log hella paper slips and legs, standard, with model projections so we can build -- don't post, just save").
Every PrizePicks NBA standard line on the slate is saved with what every model said BEFORE tip, then graded from sports.db the next day,
so each rule (projection side, tiers, unders, new team, roster cuts, book price, niche vs main) gets a real forward record.

    python _nba_paper.py log [date]     # snapshot every standard line + projections -> nba_paper_legs.jsonl, auto paper slips -> nba_paper_slips.jsonl
    python _nba_paper.py grade          # fill actuals for finished games (run after `_nba_season.py ingest`)
    python _nba_paper.py report         # hit rate by rule / tier / group / side (only graded legs)
"""
import sys, os, json, time, datetime, sqlite3, collections, statistics as st, urllib.request
import _nba_board as B, _nba_finder as NF, _props as PR

CT = datetime.timezone(datetime.timedelta(hours=-5))
LEGS, SLIPS = "nba_paper_legs.jsonl", "nba_paper_slips.jsonl"
ESPN = {"NYK": "NY", "GSW": "GS", "SAS": "SA", "NOP": "NO", "UTA": "UTAH", "WAS": "WSH"}
MAIN = {"Points", "Rebounds", "Assists", "3-PT Made"}


def pp():
    for w in (0, 30, 60, 90):
        time.sleep(w)
        try:
            d = json.load(urllib.request.urlopen(urllib.request.Request("https://partner-api.prizepicks.com/projections?league_id=7&per_page=1000",
                                                                        headers={"User-Agent": "Mozilla/5.0"}), timeout=40))
            json.dump(d, open("data/nba_finder/pp_nba_full.json", "w", encoding="utf-8")); return d
        except Exception as e:
            print("PrizePicks retry:", e)
    return json.load(open("data/nba_finder/pp_nba_full.json", encoding="utf-8"))


def log(day=None):
    day = day or datetime.datetime.now(CT).date().isoformat()
    done = {(r["date"], r["player"], r["stat"], r["line"]) for r in map(json.loads, open(LEGS, encoding="utf-8"))} if os.path.exists(LEGS) else set()
    d = pp(); P = {x["id"]: x["attributes"] for x in d["included"] if x["type"] == "new_player"}
    alt, main = B.fanduel(); pin = collections.defaultdict(list)
    try:
        for (pl, stt, ln), p in PR.pinnacle_props(487).items():
            if stt in B.PIN_STAT:
                pin[(B.norm(pl), B.PIN_STAT[stt])].append((ln, p))
    except Exception as e:
        print("pinnacle:", e)
    SD = B.spreads(); db = sqlite3.connect("sports.db", timeout=60)
    names = {B.norm(r[0]): r[0] for r in db.execute("select distinct player from nba_box where date >= '2024-10-01'")}
    stamp = datetime.datetime.now(CT).isoformat(timespec="minutes"); out = []
    for p in d["data"]:
        a = p["attributes"]
        if a.get("odds_type") != "standard" or a["stat_type"] not in NF.BOX:
            continue
        t = datetime.datetime.fromisoformat(a["start_time"]).astimezone(CT)
        if t.date().isoformat() != day:
            continue
        pl = P.get(p["relationships"]["new_player"]["data"]["id"], {}); ppn = pl.get("name") or ""
        name = names.get(B.norm(ppn))
        if not name or "+" in ppn:
            continue
        stat, ln = a["stat_type"], float(a["line_score"])
        if (day, name, stat, ln) in done:
            continue
        R = NF.db_rows(db, name, stat)
        rows = [x for x in R["last"] if x[2] >= 20]; samp = "25-26"
        if len(rows) < 15:
            rows = [x for x in R.get("prev", []) if x[2] >= 20]; samp = "24-25"
        if len(rows) < 10:
            continue
        v = [x[3] for x in rows]
        rate = lambda X, side: (lambda D: round(sum((x > ln) if side == "over" else (x < ln) for x in D) / len(D), 3) if D else None)([x for x in X if x != ln])
        proj20, projS = st.mean(v[-20:]), st.mean(v)
        side = "over" if proj20 > ln else "under"
        s, l20, l10 = rate(v, side), rate(v[-20:], side), rate(v[-10:], side)
        fo = B.fair_over(B.norm(name), stat, ln, alt, main, pin, SD) if stat in B.KEYS else {}
        real = {k: x for k, x in fo.items() if not k.endswith("~")}
        book = round(st.mean(real.values()), 3) if real else None
        last_team = db.execute("select team from nba_box where player=? and min>0 and date between '2025-10-01' and '2026-08-01' order by date desc limit 1", (name,)).fetchone()
        tm = ESPN.get(pl.get("team"), pl.get("team")); opp = ESPN.get(a.get("description"), a.get("description"))
        rc = [(m, n, r) for m, n, r, _ in NF.roster_change(db, name, stat, ln, side)]
        h2h = [x[3] for x in rows if x[1] == opp]
        cur = [r[0] for r in db.execute("select %s from nba_box b join nba_games g using(game_id) where b.player=? and g.season='2026-27' and b.min>0 and g.stype='regular' order by b.date"
                                        % NF.re.sub(r"\b([a-z]+)\b", r"b.\1", NF.BOX[stat]), (name,))]
        tier = min(s or 0, l20 or 0)
        out.append(dict(date=day, logged=stamp, start=a["start_time"], player=name, team=tm, opp=opp, stat=stat, line=ln,
                        group="main" if stat in MAIN else ("combo" if "+" in stat else "niche"),
                        side=side, proj_l20=round(proj20, 2), proj_season=round(projS, 2), gap=round((proj20 - ln) / max(ln, 1), 3),
                        rate_season=s, rate_l20=l20, rate_l10=l10, tier="85+" if tier >= .85 else ("75-85" if tier >= .75 else ("62-75" if tier >= .62 else "<62")),
                        sample=samp, n=len(v), book_over=book, book_side=None if book is None else round(book if side == "over" else 1 - book, 3),
                        new_team=bool(last_team and samp == "25-26" and last_team[0] != tm), roster=rc, h2h=h2h[-5:], this_season=cur,
                        role=("START" if R["tonight"] and R["tonight"][0] else ("BENCH" if R["tonight"] else "?")), actual=None, result=None))
    with open(LEGS, "a", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("logged %d paper legs for %s -> %s" % (len(out), day, LEGS))
    slips(out, day)


def slips(legs, day):
    """auto paper slips per rule (one player per slip, different games where possible), so each RULE gets a slip-level record too"""
    def best(filt, k=2):
        pool = sorted([l for l in legs if filt(l)], key=lambda l: -((l["rate_season"] or 0) + (l["rate_l20"] or 0) + (l["book_side"] or 0)))
        pick, used = [], set()
        for l in pool:
            if l["player"] in used:
                continue
            pick.append(l); used.add(l["player"])
            if len(pick) == k:
                break
        return pick if len(pick) == k else None
    rules = {
        "TOP 85+ (any)": lambda l: l["tier"] == "85+",
        "TOP 85+ starters, same team": lambda l: l["tier"] == "85+" and l["role"] == "START" and not l["new_team"],
        "MAIN/COMBO UNDER (proj under)": lambda l: l["side"] == "under" and l["group"] in ("main", "combo") and l["tier"] in ("85+", "75-85", "62-75"),
        "BOOK 57.7+ (priced)": lambda l: (l["book_side"] or 0) >= .577,
        "NICHE 75+": lambda l: l["group"] == "niche" and l["tier"] in ("85+", "75-85"),
        "NEW TEAM 85+": lambda l: l["new_team"] and l["tier"] == "85+",
        "BIG GAP 25%+ (proj vs line)": lambda l: abs(l["gap"]) >= .25 and l["tier"] != "<62",
    }
    n = 0
    with open(SLIPS, "a", encoding="utf-8") as f:
        for rule, fl in rules.items():
            for k, mult in ((2, 3.0), (3, 6.0)):
                pk = best(fl, k)
                if pk:
                    f.write(json.dumps(dict(date=day, rule=rule, legs=[(l["player"], l["stat"], l["line"], l["side"]) for l in pk], mult=mult, result=None),
                                       ensure_ascii=False) + "\n"); n += 1
    print("logged %d paper slips -> %s" % (n, SLIPS))


def grade():
    db = sqlite3.connect("sports.db", timeout=60)
    def act(r):
        x = db.execute("select %s, min from nba_box where player=? and date in (?, date(?, '+1 day'))" % NF.BOX[r["stat"]], (r["player"], r["date"], r["date"])).fetchone()
        return x
    L = [json.loads(l) for l in open(LEGS, encoding="utf-8")] if os.path.exists(LEGS) else []
    g = 0
    for r in L:
        if r["result"]:
            continue
        x = act(r)
        if not x:
            continue
        if not x[1]:
            r["result"] = "DNP"; g += 1; continue
        r["actual"] = x[0]
        r["result"] = "PUSH" if x[0] == r["line"] else ("W" if (x[0] > r["line"]) == (r["side"] == "over") else "L"); g += 1
    open(LEGS, "w", encoding="utf-8").write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in L))
    key = {(r["date"], r["player"], r["stat"], r["line"]): r for r in L}
    S = [json.loads(l) for l in open(SLIPS, encoding="utf-8")] if os.path.exists(SLIPS) else []
    for s in S:
        if s["result"]:
            continue
        res = [key.get((s["date"], p, st_, ln), {}).get("result") for p, st_, ln, _ in s["legs"]]
        if any(x is None for x in res):
            continue
        live = [x for x in res if x not in ("PUSH", "DNP")]
        s["result"] = "L" if "L" in live else ("W" if live else "VOID")
    open(SLIPS, "w", encoding="utf-8").write("".join(json.dumps(s, ensure_ascii=False) + "\n" for s in S))
    print("graded %d legs" % g); report()


def report():
    L = [json.loads(l) for l in open(LEGS, encoding="utf-8")] if os.path.exists(LEGS) else []
    G = [r for r in L if r["result"] in ("W", "L")]
    if not G:
        print("no graded legs yet"); return
    def show(title, key):
        c = collections.defaultdict(lambda: [0, 0])
        for r in G:
            for k in key(r):
                c[k][0] += r["result"] == "W"; c[k][1] += 1
        print(title)
        for k, (w, n) in sorted(c.items()):
            print("   %-34s %4d-%-4d %3.0f%%" % (k, w, n - w, 100 * w / n))
    show("BY TIER x SIDE", lambda r: ["%s %s" % (r["tier"], r["side"])])
    show("BY GROUP x SIDE", lambda r: ["%s %s" % (r["group"], r["side"])])
    show("BOOK-PRICED", lambda r: ["book side %s" % ("57.7+" if (r["book_side"] or 0) >= .577 else ("<57.7" if r["book_side"] is not None else "no price"))])
    show("FLAGS", lambda r: (["NEW TEAM"] if r["new_team"] else ["same team"]) + (["roster cut (<55% w/ returner)"] if any(x[2] is not None and x[2] < .55 for x in r["roster"]) else []) + ["role " + r["role"]])
    S = [json.loads(l) for l in open(SLIPS, encoding="utf-8")] if os.path.exists(SLIPS) else []
    c = collections.defaultdict(lambda: [0, 0, 0.0])
    for s in S:
        if s["result"] in ("W", "L"):
            c[(s["rule"], len(s["legs"]))][0] += s["result"] == "W"; c[(s["rule"], len(s["legs"]))][1] += 1
            c[(s["rule"], len(s["legs"]))][2] += (s["mult"] - 1) if s["result"] == "W" else -1
    if c:
        print("PAPER SLIPS (flat $1)")
        for (rule, k), (w, n, net) in sorted(c.items()):
            print("   %-34s %d-pick %3d-%-3d net %+.1f u" % (rule, k, w, n - w, net))


if __name__ == "__main__":
    a = sys.argv[1:]
    {"log": lambda: log(a[1] if len(a) > 1 else None), "grade": grade, "report": report}.get(a[0] if a else "report", report)()
