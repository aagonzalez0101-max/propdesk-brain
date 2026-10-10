"""The $100 backtest re-graded at REALISTIC prices (2026-09-28): props as straights at -160/-180 or as a
standard 2-pick at 3x, ML 60%+ at its real price (or +1.5 at -300). Then a 3-month day-resample."""
import random, requests
ns = {}; exec(open("_top5_replay.py", encoding="utf-8").read().split("def run(")[0], ns)
days, cand, grade, dec, imp, boards = ns["days"], ns["cand"], ns["grade"], ns["dec"], ns["imp"], ns["boards"]
H = {"User-Agent": "Mozilla/5.0"}; S = "https://statsapi.mlb.com/api/v1"
sc = {}
d = requests.get(S + "/schedule", params=dict(sportId=1, startDate=days[0], endDate=days[-1]), headers=H, timeout=60).json()
for dt in d.get("dates", []):
    for g in dt.get("games", []):
        if g["status"]["detailedState"] == "Final":
            a, h = g["teams"]["away"], g["teams"]["home"]; sc[(dt["date"], a["team"]["name"], h["team"]["name"])] = (a.get("score"), h.get("score"))
DAY = {}
for dd in days:
    pr = [grade(dd, p) for p in sorted([p for p in cand.get(dd, []) if p["market"] != "ML"], key=lambda p: -p.get("ev", 0))[:5]]
    pr = [r for r in pr if r is not None]
    ml = []
    for p in boards[dd].get("picks", []):
        if p.get("market") == "ML" and p.get("odds") is not None and p.get("raw") is not None and p.get("calibrated") is not None \
           and p["raw"] > imp(p["odds"]) and p["calibrated"] > imp(p["odds"]) and p["calibrated"] >= 0.60:
            away, home = p["game"].split(" @ "); s = sc.get((dd, away, home))
            if s and None not in s:
                me, opp = (s[0], s[1]) if p["selection"] == away else (s[1], s[0]); ml.append((dec(p["odds"]), me - opp))
    DAY[dd] = (pr, ml)
def day_returns(dd, prop_mode, ml_mode):
    pr, ml = DAY[dd]; out = []
    if prop_mode == "-160": out += [(1 + 100 / 160 - 1) if r else -1 for r in pr]
    elif prop_mode == "-180": out += [(1 + 100 / 180 - 1) if r else -1 for r in pr]
    elif prop_mode == "2pick3x":
        for i in range(0, len(pr) - 1, 2): out.append(2.0 if (pr[i] and pr[i + 1]) else -1)
    if ml_mode == "straight": out += [(o - 1) if m > 0 else -1 for o, m in ml]
    elif ml_mode == "+1.5@-300": out += [(1 / 3) if m > -2 else -1 for o, m in ml]
    return out
def month(prop_mode, ml_mode):
    B = 100.0; n = 0; flat = 0.0
    for dd in days:
        s = B
        for r in day_returns(dd, prop_mode, ml_mode): B += s * 0.05 * r; n += 1; flat += r
    return B, n, flat / max(n, 1)
def three(prop_mode, ml_mode, runs=10000):
    pool = [day_returns(dd, prop_mode, ml_mode) for dd in days]; out = []
    for _ in range(runs):
        B = 100.0
        for _ in range(91):
            s = B
            for r in random.choice(pool): B += s * 0.05 * r
        out.append(B)
    out.sort(); return out[len(out) // 10], out[len(out) // 2], out[9 * len(out) // 10]
random.seed(3)
print("  %-50s %-6s %-8s %-11s %s" % ("scenario", "bets", "ROI", "Sept: $100->", "3 months: bad 10% / MEDIAN / good 10%"))
for lbl, pm, mm in (("OLD: board prices (the $299 run)", None, None),
                    ("props straight -160  + ML 60%+ straight", "-160", "straight"),
                    ("props straight -180  + ML 60%+ straight", "-180", "straight"),
                    ("props straight -160  + ML 60%+ as +1.5 @ -300", "-160", "+1.5@-300"),
                    ("props as 2-pick standard 3x + ML 60%+ straight", "2pick3x", "straight"),
                    ("ML 60%+ straight ONLY", "none", "straight")):
    if pm is None: print("  %-50s %-6s %-8s %-11s %s" % (lbl, "142", "+17.2%", "$299", "(overstated)")); continue
    B, n, roi = month(pm, mm); a, b, c = three(pm, mm)
    print("  %-50s %-6d %+-7.1f%% $%-10.0f $%.0f / $%.0f / $%.0f" % (lbl, n, 100 * roi, B, a, b, c))
