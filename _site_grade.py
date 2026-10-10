"""PROP DESK -- log and grade the site's verdicts (2026-09-30). User: "all these bets can be graded later".

    python _site_grade.py log      # snapshot today's Bet / Lean rows from site/prop_desk.html -> site_reads.jsonl (run by _site_build2.py)
    python _site_grade.py grade    # fill results from sports.db (run `python _db.py update` first), print the record
    python _site_grade.py report   # record only

A row is graded from the player's box score on the game date (US Central, +1 day allowed for late West-coast starts).
NFL rows are skipped until NFL box scores are dated in sports.db.
"""
import sys, os, json, subprocess, sqlite3, datetime
from collections import defaultdict

F = "site_reads.jsonl"
CT = datetime.timezone(datetime.timedelta(hours=-5))

NODE = r"""
const fs=require('fs');const h=fs.readFileSync('site/prop_desk.html','utf8');const src=h.match(/<script>([\s\S]*)<\/script>/)[1];
const el=()=>({innerHTML:'',hidden:true,value:'',querySelectorAll:()=>[],classList:{toggle(){}}});
global.document={querySelector:()=>el(),getElementById:()=>null,createElement:()=>el(),body:{appendChild(){}},addEventListener(){}};global.window={scrollTo(){}};global.localStorage={getItem:()=>null,setItem(){}};
const A=new Function(src+';return {allRows, statDefs};')();
const out=A.allRows().filter(r=>r.V.kind==='bet'||r.V.kind==='lean').map(r=>({sport:r.sp,player:r.P.name,team:r.P.team,opp:r.P.opp,
  start:r.P.start,stat:r.stat,key:r.sk,parts:A.statDefs(r.sp,r.P)[r.sk][2],line:r.line,side:r.side,verdict:r.V.kind,read:r.V.r.kind,
  money:!!r.V.r.money,p:+r.V.best.p.toFixed(3),be:+r.V.best.be.toFixed(3),venue:r.V.best.v,mult:r.V.best.mult}));
process.stdout.write(JSON.stringify(out));
"""


def game_day(start):
    try:
        return datetime.datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(CT).date().isoformat()
    except Exception:
        return None


def log():
    rows = json.loads(subprocess.run(["node", "-e", NODE], capture_output=True, text=True, encoding="utf-8", check=True).stdout)
    have = set()
    if os.path.exists(F):
        for l in open(F, encoding="utf-8"):
            r = json.loads(l)
            have.add((r["date"], r["sport"], r["player"], r["key"], r["line"], r["side"]))
    new = 0
    with open(F, "a", encoding="utf-8") as fh:
        for r in rows:
            r["date"] = game_day(r["start"]) or datetime.datetime.now(CT).date().isoformat()
            k = (r["date"], r["sport"], r["player"], r["key"], r["line"], r["side"])
            if k in have:
                continue
            have.add(k)
            r["logged"] = datetime.datetime.now(CT).isoformat(timespec="minutes")
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            new += 1
    print("site reads logged: %d new (%d bets, %d leans on the board now)" % (
        new, sum(r["verdict"] == "bet" for r in rows), sum(r["verdict"] == "lean" for r in rows)))


def derive(sport, x):
    """box-score json from sports.db -> the keys the site uses"""
    if sport == "MLB":
        if x.get("group") == "pitching":
            ip = str(x.get("inningsPitched") or "0").split(".")
            outs = x.get("outs") if x.get("outs") is not None else int(ip[0]) * 3 + (int(ip[1]) if len(ip) > 1 else 0)
            return dict(pk=x.get("strikeOuts"), outs=outs, er=x.get("earnedRuns"), ha=x.get("hits"), bba=x.get("baseOnBalls"))
        h = x.get("hits") or 0
        return dict(h=h, tb=x.get("totalBases"), r=x.get("runs"), rbi=x.get("rbi"), k=x.get("strikeOuts"), bb=x.get("baseOnBalls"),
                    s1=h - (x.get("doubles") or 0) - (x.get("triples") or 0) - (x.get("homeRuns") or 0))
    if sport == "NHL":
        d = dict(x)
        if x.get("pos") == "G":
            d["ga"] = (x.get("shots_against") or 0) - (x.get("saves") or 0)
        return d
    return x


def actual(c, r):
    if r["sport"] == "NFL":
        return None
    parts = r["player"].split()
    names = [r["player"]] + ([parts[0][0] + ". " + " ".join(parts[1:])] if r["sport"] == "NHL" and len(parts) > 1 else [])
    d0 = datetime.date.fromisoformat(r["date"])
    days = [d0.isoformat(), (d0 + datetime.timedelta(days=1)).isoformat()]
    for nm in names:
        for day in days:
            rows = c.execute("SELECT stats, team FROM player_games WHERE sport=? AND player=? AND date=?", (r["sport"], nm, day)).fetchall()
            for js, team in rows:
                x = derive(r["sport"], json.loads(js))
                if r["sport"] == "NHL" and r["team"] and team != r["team"] and len(rows) > 1:
                    continue
                vals = [x.get(p) for p in r["parts"]]
                if any(v is None for v in vals):
                    continue
                if r["sport"] == "MLB" and r["key"] in ("pk", "outs", "er", "ha", "bba") and "outs" not in x:
                    continue
                return sum(vals)
    return None


def grade():
    if not os.path.exists(F):
        print("nothing logged yet"); return
    c = sqlite3.connect("sports.db")
    today = datetime.datetime.now(CT).date().isoformat()
    rows = [json.loads(l) for l in open(F, encoding="utf-8")]
    n = 0
    for r in rows:
        if r.get("result") or r["date"] >= today:
            continue
        v = actual(c, r)
        if v is None:
            continue
        r["actual"] = v
        r["result"] = "P" if v == r["line"] else ("W" if (v > r["line"]) == (r["side"] == "over") else "L")
        n += 1
    with open(F, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("graded %d rows" % n)
    report(rows)


def report(rows=None):
    rows = rows or [json.loads(l) for l in open(F, encoding="utf-8")]
    g = [r for r in rows if r.get("result") in ("W", "L")]
    pend = sum(1 for r in rows if not r.get("result"))
    print("\nSITE READS  graded %d  pending %d" % (len(g), pend))
    for label, f in (("BETS", lambda r: r["verdict"] == "bet"), ("LEANS (model)", lambda r: r["verdict"] == "lean" and r["read"] == "model"),
                     ("LEANS (quick read)", lambda r: r["verdict"] == "lean" and r["read"] == "quick")):
        s = [r for r in g if f(r)]
        if not s:
            continue
        w = sum(r["result"] == "W" for r in s)
        exp = sum(r["p"] for r in s) / len(s)
        be = sum(r["be"] for r in s) / len(s)
        print("  %-20s %3d-%-3d  %5.1f%%   expected %4.1f%%  break-even %4.1f%%" % (label, w, len(s) - w, 100 * w / len(s), 100 * exp, 100 * be))
        by = defaultdict(lambda: [0, 0])
        for r in s:
            by[r["sport"]][0 if r["result"] == "W" else 1] += 1
        print("  " + " " * 20 + "  ".join("%s %d-%d" % (k, a, b) for k, (a, b) in sorted(by.items())))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    {"log": log, "grade": grade, "report": report}[cmd]()
