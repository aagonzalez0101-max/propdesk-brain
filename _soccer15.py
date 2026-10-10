"""Over-1.5-goals screen (measured 82.1% when all three filters pass, n=1355).

Filters (from the Linemaker system, re-measured on 20,283 matches):
  1 both teams >=1.0 goals/game over last 15
  2 head-to-head >=80% over 1.5 (min 4 meetings)
  3 both teams scored in >=4 of last 5
Base rate 75.6% -> 77.4% -> 78.5% -> 82.1%. Fair price at 82.1% is -460, so bet
only at -450 or better.

  python _soccer15.py "Barcelona" "Osasuna"
  python _soccer15.py --day 2026-09-16      (screens Pinnacle fixtures for the day)
"""
import json, sys, collections, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

D = [r for r in json.load(open("soccer_rows.json", encoding="utf-8")) if r.get("hg") is not None]
for r in D:
    d, m, y = r["date"].split("/")
    r["dt"] = f"20{y}-{m}-{d}" if len(y) == 2 else f"{y}-{m}-{d}"
D.sort(key=lambda r: r["dt"])
HIST = collections.defaultdict(list)
H2H = collections.defaultdict(list)
for r in D:
    tot = r["hg"] + r["ag"]
    HIST[r["home"]].append((r["dt"], r["hg"], tot))
    HIST[r["away"]].append((r["dt"], r["ag"], tot))
    H2H[tuple(sorted((r["home"], r["away"])))].append(tot)


def screen(home, away):
    hh, ha = HIST.get(home, []), HIST.get(away, [])
    if len(hh) < 10 or len(ha) < 10:
        return None
    gh = sum(x[1] for x in hh[-15:]) / len(hh[-15:])
    ga = sum(x[1] for x in ha[-15:]) / len(ha[-15:])
    sh = sum(1 for x in hh[-5:] if x[1] > 0)
    sa = sum(1 for x in ha[-5:] if x[1] > 0)
    pair = H2H.get(tuple(sorted((home, away))), [])
    hr = (sum(1 for t in pair if t > 1.5) / len(pair)) if len(pair) >= 4 else None
    p1, p3 = gh >= 1.0 and ga >= 1.0, sh >= 4 and sa >= 4
    p2 = hr is not None and hr >= 0.8
    est = 0.821 if (p1 and p2 and p3) else (0.785 if (p1 and p3) else (0.774 if p1 else 0.756))
    return dict(gh=gh, ga=ga, sh=sh, sa=sa, h2h=hr, n=len(pair), p1=p1, p2=p2, p3=p3,
                pass_all=p1 and p2 and p3, est=est)


if __name__ == "__main__":
    if sys.argv[1] == "--day":
        import datetime
        sys.path.insert(0, "betting")
        import freeodds as fo
        mu = fo._get("%s/0.1/sports/29/matchups?withSpecials=false&brandId=0" % fo.PIN) or []
        lo = datetime.datetime.fromisoformat(sys.argv[2] + "T05:00:00+00:00")
        hi = lo + datetime.timedelta(hours=26)
        hits = 0
        for m in mu:
            if m.get("parentId") or m.get("type") != "matchup":
                continue
            t = datetime.datetime.fromisoformat(m["startTime"].replace("Z", "+00:00"))
            if not (lo <= t < hi):
                continue
            s = {q["alignment"]: q["name"] for q in m["participants"]}
            r = screen(s.get("home", ""), s.get("away", ""))
            if r and r["pass_all"]:
                hits += 1
                line = "%s v %s  gpg %.2f/%.2f  scored %d/5,%d/5  h2h %.0f%% (n=%d) -> est %.1f%%, bet at -450 or better" % (
                    s.get("home"), s.get("away"), r["gh"], r["ga"], r["sh"], r["sa"],
                    100 * r["h2h"], r["n"], 100 * r["est"])
                print(line)
        print("")
        print("%d fixtures pass all three filters" % hits)
    else:
        r = screen(sys.argv[1], sys.argv[2])
        print(json.dumps(r, indent=1) if r else "not enough history for these teams")
