"""Replay: each September day, the board's top 5 WORTH IT/STRONG plays by EV (ML or props),
5% of the morning roll each, from $100, graded against real results. (asked 2026-09-28)"""
import json, glob, os, requests, collections, unicodedata, re
from concurrent.futures import ThreadPoolExecutor
H = {"User-Agent": "Mozilla/5.0"}; S = "https://statsapi.mlb.com/api/v1"
norm = lambda s: re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", (s or "").lower()).encode("ascii", "ignore").decode())
imp = lambda o: (-o) / ((-o) + 100) if o < 0 else 100 / (o + 100)
dec = lambda o: (100 / -o) + 1 if o < 0 else o / 100 + 1
boards = {}
for f in sorted(glob.glob("pp/boards/*.json")):
    try: boards[os.path.basename(f)[:10]] = json.load(open(f, encoding="utf-8"))
    except Exception: pass
days = sorted(boards)
res = {}
d = requests.get(S + "/schedule", params=dict(sportId=1, startDate=days[0], endDate=days[-1]), headers=H, timeout=60).json()
for dt in d.get("dates", []):
    for g in dt.get("games", []):
        if g["status"]["detailedState"] != "Final": continue
        a, h = g["teams"]["away"], g["teams"]["home"]
        res[(dt["date"], a["team"]["name"], h["team"]["name"])] = a["team"]["name"] if a.get("isWinner") else h["team"]["name"]
ids = {}
for t in requests.get(S + "/teams?sportId=1", headers=H, timeout=30).json()["teams"]:
    try: r = requests.get(S + "/teams/%d/roster?rosterType=fullSeason" % t["id"], headers=H, timeout=25).json()
    except Exception: continue
    for p in r.get("roster", []): ids.setdefault(norm(p["person"]["fullName"]), (p["person"]["id"], p["position"]["abbreviation"]))
cand = collections.defaultdict(list)
for day in days:
    for p in boards[day].get("picks", []):
        if p.get("verdict") not in ("WORTH IT", "STRONG") or p.get("odds") is None: continue
        if p["market"] == "ML":
            raw, cal = p.get("raw"), p.get("calibrated")
            if raw is None or cal is None or not (raw > imp(p["odds"]) and cal > imp(p["odds"])): continue
        cand[day].append(p)
logs = {}
def gl(k):
    pid, grp = k
    try:
        d = requests.get(S + "/people/%d/stats" % pid, params=dict(stats="gameLog", group=grp, season=2026), headers=H, timeout=25).json()
        return k, {x["date"]: x["stat"] for x in ((d.get("stats") or [{}])[0].get("splits") or [])}
    except Exception: return k, {}
need = set()
for day, ps in cand.items():
    for p in ps:
        if p["market"] != "ML" and norm(p["selection"]) in ids:
            pid, pos = ids[norm(p["selection"])]
            need.add((pid, "pitching" if p["market"] in ("K", "ER", "OUTS") else "hitting"))
with ThreadPoolExecutor(12) as ex: logs = dict(ex.map(gl, sorted(need)))
def val(m, s):
    g = lambda k: s.get(k) or 0
    return {"HRR": g("hits") + g("runs") + g("rbi"), "HITS": g("hits"), "TB": g("totalBases"), "K": g("strikeOuts"),
            "ER": g("earnedRuns"), "OUTS": g("outs")}.get(m)
def grade(day, p):
    if p["market"] == "ML":
        away, home = p["game"].split(" @ ")
        w = res.get((day, away, home))
        return None if w is None else (w == p["selection"])
    v = ids.get(norm(p["selection"]))
    if not v: return None
    grp = "pitching" if p["market"] in ("K", "ER", "OUTS") else "hitting"
    s = logs.get((v[0], grp), {}).get(day)
    if s is None: return None                     # DNP -> void
    x = val(p["market"], s)
    if x is None or x == p["line"]: return None   # push -> void
    return x > p["line"] if p["side"] == "OVER" else x < p["line"]
def run(filt, label):
    B = 100.0; lo = 100.0; n = w = 0; flat = 0.0
    for day in days:
        ps = sorted([p for p in cand.get(day, []) if filt(p)], key=lambda p: -p.get("ev", 0))[:5]
        start = B
        for p in ps:
            r = grade(day, p)
            if r is None: continue
            n += 1; w += r
            ret = (dec(p["odds"]) - 1) if r else -1
            flat += ret; B += start * 0.05 * ret
        lo = min(lo, B)
    print("  %-40s %3d bets  %3d-%-3d  flat ROI %+6.1f%%   $100 -> $%-6.0f low $%.0f" % (label, n, w, n - w, 100 * flat / max(n, 1), B, lo))
print("September boards: %d days\n" % len(days))
run(lambda p: True, "TOP 5 / day, ML or props (as asked)")
run(lambda p: p.get("ev", 0) <= 0.25, "same, dropping EV>25% (bug-signal rule)")
run(lambda p: p["market"] == "ML", "moneylines only")
run(lambda p: p["market"] != "ML", "props only")
