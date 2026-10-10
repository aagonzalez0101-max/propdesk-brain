"""Per-game form log: what each team's starter and bullpen ACTUALLY did.

Builds form_log.jsonl (one row per team per game) so the daily slate can ask
"how is this bullpen throwing THIS WEEK", not just season ERA.

  python _formlog.py 2026-09-01 2026-09-13      # backfill a range
  python _formlog.py 2026-09-13                 # one day
  python _formlog.py --report 14                # per-team last-N-day summary
"""
import json,sys,datetime,urllib.request,collections,os

API="https://statsapi.mlb.com/api/v1"
LOG="form_log.jsonl"

def get(u):
    for _ in range(3):
        try: return json.loads(urllib.request.urlopen(u,timeout=45).read())
        except Exception as e: err=e
    raise err

def day_rows(day):
    sched=get(f"{API}/schedule?sportId=1&date={day}")
    rows=[]
    for d in sched.get("dates",[]):
        for g in d["games"]:
            if g["status"]["detailedState"]!="Final": continue
            pk=g["gamePk"]
            box=get(f"{API}/game/{pk}/boxscore"); ls=get(f"{API}/game/{pk}/linescore")
            inn=ls.get("innings",[])
            for side,opp in (("away","home"),("home","away")):
                t=box["teams"][side]; name=t["team"]["name"]
                pitchers=[t["players"][f"ID{p}"] for p in t["pitchers"]]
                if not pitchers: continue
                def ip(p): return float(p["stats"]["pitching"].get("inningsPitched") or 0)
                sp=pitchers[0]; rel=pitchers[1:]
                sp_ip=ip(sp); sp_er=sp["stats"]["pitching"].get("earnedRuns",0)
                pen_ip=sum(ip(p) for p in rel); pen_er=sum(p["stats"]["pitching"].get("earnedRuns",0) for p in rel)
                late=sum((i.get(opp,{}).get("runs") or 0) for i in inn if i["num"]>=7)
                rows.append(dict(day=day,game_pk=pk,team=name,opp=box["teams"][opp]["team"]["name"],
                    runs=g["teams"][side].get("score"),runs_against=g["teams"][opp].get("score"),
                    sp=sp["person"]["fullName"],sp_ip=sp_ip,sp_er=sp_er,
                    sp_pitches=sp["stats"]["pitching"].get("numberOfPitches",0),
                    opener=sp_ip<=3.0,
                    pen_ip=round(pen_ip,1),pen_er=pen_er,
                    pen_arms=[p["person"]["fullName"] for p in rel],
                    late_runs_allowed=late))
    return rows

def report(ndays):
    rows=[json.loads(x) for x in open(LOG,encoding="utf-8")] if os.path.exists(LOG) else []
    if not rows: print("form_log.jsonl is empty"); return
    last=max(r["day"] for r in rows)
    cut=(datetime.date.fromisoformat(last)-datetime.timedelta(days=ndays-1)).isoformat()
    rows=[r for r in rows if r["day"]>=cut]
    agg=collections.defaultdict(lambda: dict(g=0,sp_ip=0,sp_er=0,pen_ip=0,pen_er=0,late=0,open=0))
    for r in rows:
        a=agg[r["team"]]; a["g"]+=1
        for k,s in (("sp_ip","sp_ip"),("sp_er","sp_er"),("pen_ip","pen_ip"),("pen_er","pen_er")): a[k]+=r[s]
        a["late"]+=r["late_runs_allowed"]; a["open"]+=1 if r["opener"] else 0
    print(f"FORM, last {ndays} days ({cut} to {last})   sorted by bullpen ERA\n")
    print(f'{"team":24s} {"G":>2} {"SP IP/g":>7} {"SP ERA":>6} {"PEN IP/g":>8} {"PEN ERA":>7} {"late R/g":>8} {"opener":>6}')
    for t,a in sorted(agg.items(),key=lambda kv:-(9*kv[1]["pen_er"]/max(kv[1]["pen_ip"],.1))):
        print(f'{t:24s} {a["g"]:2d} {a["sp_ip"]/a["g"]:7.2f} {9*a["sp_er"]/max(a["sp_ip"],.1):6.2f} '
              f'{a["pen_ip"]/a["g"]:8.2f} {9*a["pen_er"]/max(a["pen_ip"],.1):7.2f} {a["late"]/a["g"]:8.2f} {a["open"]:6d}')

if __name__=="__main__":
    if sys.argv[1]=="--report": report(int(sys.argv[2]) if len(sys.argv)>2 else 14); sys.exit()
    d0=datetime.date.fromisoformat(sys.argv[1])
    d1=datetime.date.fromisoformat(sys.argv[2]) if len(sys.argv)>2 else d0
    seen=set()
    if os.path.exists(LOG):
        seen={(r["game_pk"],r["team"]) for r in (json.loads(x) for x in open(LOG,encoding="utf-8"))}
    n=0
    with open(LOG,"a",encoding="utf-8") as f:
        d=d0
        while d<=d1:
            for r in day_rows(d.isoformat()):
                if (r["game_pk"],r["team"]) in seen: continue
                f.write(json.dumps(r)+"\n"); n+=1
            print(d.isoformat(),"done",n,"rows",flush=True)
            d+=datetime.timedelta(days=1)
    print("wrote",n,"rows to",LOG)
