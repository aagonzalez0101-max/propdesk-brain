"""Same September picks, re-priced as conservative STRAIGHTS (user, 2026-09-28):
props at -160, goblin/alt props at 1.6x, run lines +1.5/+2.5 at -180, ML 60%+ at its real price."""
import requests
ns = {}; exec(open("_top5_replay.py", encoding="utf-8").read().split("def run(")[0], ns)
days, cand, grade, dec, imp, boards = ns["days"], ns["cand"], ns["grade"], ns["dec"], ns["imp"], ns["boards"]
H = {"User-Agent": "Mozilla/5.0"}; S = "https://statsapi.mlb.com/api/v1"
sc = {}
d = requests.get(S + "/schedule", params=dict(sportId=1, startDate=days[0], endDate=days[-1]), headers=H, timeout=60).json()
for dt in d.get("dates", []):
    for g in dt.get("games", []):
        if g["status"]["detailedState"] == "Final":
            a, h = g["teams"]["away"], g["teams"]["home"]
            sc[(dt["date"], a["team"]["name"], h["team"]["name"])] = (a.get("score"), h.get("score"))
props, mls = [], []
for dd in days:
    for p in sorted([p for p in cand.get(dd, []) if p["market"] != "ML"], key=lambda p: -p.get("ev", 0))[:5]:
        r = grade(dd, p)
        if r is not None: props.append((dd, p, r))
    for p in boards[dd].get("picks", []):
        if p.get("market") == "ML" and p.get("odds") is not None and p.get("raw") is not None and p.get("calibrated") is not None \
           and p["raw"] > imp(p["odds"]) and p["calibrated"] > imp(p["odds"]) and p["calibrated"] >= 0.60:
            away, home = p["game"].split(" @ "); s = sc.get((dd, away, home))
            if s and None not in s:
                me, opp = (s[0], s[1]) if p["selection"] == away else (s[1], s[0])
                mls.append((dd, p, me - opp))
def show(lbl, wins, n, price_dec):
    be = 1 / price_dec; wr = wins / n; roi = wr * price_dec - 1
    print("  %-46s %3d bets  win %5.1f%%  needs %5.1f%%  ROI %+6.1f%%" % (lbl, n, 100 * wr, 100 * be, 100 * roi))
pw = sum(r for _, _, r in props); pn = len(props)
print("PROPS (the board's top 5/day):")
show("as straights at -160", pw, pn, 1 + 100 / 160)
show("as goblin/alt at 1.6x", pw, pn, 1.6)
print("\nMONEYLINE favourites the model has at 60%%+ (%d games):" % len(mls))
show("straight ML at the real price", sum(m > 0 for *_, m in mls), len(mls), sum(dec(p["odds"]) for _, p, _ in mls) / len(mls))
show("same teams +1.5 at -180", sum(m > -2 for *_, m in mls), len(mls), 1 + 100 / 180)
show("same teams +2.5 at -180 (generous price)", sum(m > -3 for *_, m in mls), len(mls), 1 + 100 / 180)
show("same teams +1.5 at -300 (typical price)", sum(m > -2 for *_, m in mls), len(mls), 1 + 100 / 300)
