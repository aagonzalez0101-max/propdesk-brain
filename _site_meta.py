"""PROP DESK -- the site's extra panels (2026-10-02): track record, today's card, glitch watch, NPB board, real-money record.
    python _site_meta.py     # -> site/meta.json (injected by _site_build2.py)"""
import json, os, datetime, collections
CT = datetime.timezone(datetime.timedelta(hours=-5))
today = datetime.datetime.now(CT).date().isoformat()
out = {"built": datetime.datetime.now(CT).isoformat(timespec="minutes")}
# 1) model track record: graded calls by sport x tier, and by day for the TAKE tier
from _calls import is_alt as _is_alt
rec = collections.defaultdict(lambda: [0, 0]); daily = collections.defaultdict(lambda: [0, 0]); close = [0, 0]
for l in open("calls_log.jsonl", encoding="utf-8"):
    r = json.loads(l); c = (r.get("call") or ""); res = r.get("result")
    if _is_alt(r):
        continue                                               # main lines only (goblins/demons + UD lopsided lines)
    if res in ("W", "L") and c[:4] in ("TAKE", "LEAN"):
        k = (r["sport"], c); rec[k][0 if res == "W" else 1] += 1
        if c.startswith("TAKE"):
            daily[(r["date"], r["sport"])][0 if res == "W" else 1] += 1
    elif str(res).startswith("CLOSE"):
        close[0 if res.endswith("over") else 1] += 1
out["record"] = [dict(sport=k[0], call=k[1], w=v[0], l=v[1]) for k, v in sorted(rec.items())]
out["daily"] = [dict(date=k[0], sport=k[1], w=v[0], l=v[1]) for k, v in sorted(daily.items())]
out["too_close"] = dict(over=close[0], under=close[1])
# 2) site reads (Bet / Lean labels)
sr = collections.defaultdict(lambda: [0, 0])
if os.path.exists("site_reads.jsonl"):
    for l in open("site_reads.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if r.get("result") in ("W", "L"):
            sr[(r["verdict"], r["read"])][0 if r["result"] == "W" else 1] += 1
out["site_reads"] = [dict(verdict=k[0], read=k[1], w=v[0], l=v[1]) for k, v in sorted(sr.items())]
# 3) real money
money = []; open_t = []
for l in open("live_paper.jsonl", encoding="utf-8"):
    r = json.loads(l)
    if r.get("kind") != "LIVE" or r.get("date", "") < "2026-09-29":
        continue
    row = dict(date=r.get("date"), book=r.get("book"), market=r.get("market"), selection=r.get("selection"), stake=r.get("stake"),
               to_return=r.get("to_return"), result=r.get("result"), net=r.get("net"))
    (open_t if r.get("result") == "PENDING" else money).append(row)
out["money"] = money; out["open"] = open_t
# 4) today's card, glitch watch, NPB
cf = os.path.join("cards", "%s.json" % today)
out["card"] = json.load(open(cf, encoding="utf-8")) if os.path.exists(cf) else []
out["card_date"] = today
gf = os.path.join("site", "glitch.json")
out["glitch"] = json.load(open(gf, encoding="utf-8"))[:30] if os.path.exists(gf) else []
nf = os.path.join("site", "npb.json")
out["npb"] = json.load(open(nf, encoding="utf-8")) if os.path.exists(nf) else []
tf = os.path.join("site", "tennis.json")
out["tennis"] = json.load(open(tf, encoding="utf-8")) if os.path.exists(tf) else []
cal = "calibration.json"
out["calibration"] = json.load(open(cal)) if os.path.exists(cal) else {}
json.dump(out, open(os.path.join("site", "meta.json"), "w", encoding="utf-8"), ensure_ascii=False)
print("site/meta.json: %d record rows, %d card slips, %d glitches, %d NPB games, %d money rows" % (
    len(out["record"]), len(out["card"]), len(out["glitch"]), len(out["npb"]), len(money)))
