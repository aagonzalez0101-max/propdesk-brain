"""Capture CLOSING prices from the FREE feeds -> closing_lines.jsonl

    python _closing.py mlb           # games starting within 90 minutes
    python _closing.py mlb --all     # the whole slate, right now
    python _closing.py report        # did we beat the close? (the CLV answer)

Why this matters more than the win/loss record: beating the closing price is the signal that an
edge is real, and it shows up in roughly 50 bets instead of the several hundred a profit curve
needs (Buchdahl, see [[reference_betting_library]]). Our ladder has ~15 bets. Without this we
are a season away from knowing whether it is skill.

The existing `_closingsnap.py` does the same job through the PAID odds API and would spend his
credits, so this version uses only what is free: Pinnacle's guest feed and Kalshi's public
market, de-vigged, which [[project_line_shop_result]] measured as tracking each other within
1-2 points.
"""
import json, sys, os, datetime, collections

sys.path.insert(0, "betting")
from betting import freeodds as F

OUT = "closing_lines.jsonl"
dec = lambda a: 1 + (a / 100 if a > 0 else 100 / abs(a))
imp = lambda a: 1 / dec(a)


def devig(home_odds, away_odds):
    ih, ia = imp(home_odds), imp(away_odds)
    t = ih + ia
    return ih / t, ia / t


def snapshot(sport="mlb", window_min=90, everything=False):
    now = datetime.datetime.now(datetime.timezone.utc)
    rows = F.pinnacle_mlb() if sport == "mlb" else F.pinnacle_nfl()
    kept = 0
    with open(OUT, "a", encoding="utf-8") as f:
        for r in rows:
            start = datetime.datetime.fromisoformat(r["commence_time"].replace("Z", "+00:00"))
            mins = (start - now).total_seconds() / 60
            if not everything and not (-15 <= mins <= window_min):
                continue
            try:
                px = {o["name"]: float(o["price"])
                      for o in r["bookmakers"][0]["markets"][0]["outcomes"]}
            except Exception:
                continue
            h, a = r["home_team"], r["away_team"]
            if h not in px or a not in px:
                continue
            ph, pa = devig(px[h], px[a])
            f.write(json.dumps(dict(
                ts=now.isoformat(), sport=sport, game="%s @ %s" % (a, h),
                start=r["commence_time"], minutes_to_start=round(mins),
                home=h, away=a, home_odds=px[h], away_odds=px[a],
                home_fair=round(ph, 4), away_fair=round(pa, 4), source="pinnacle")) + "\n")
            kept += 1
    print("snapshotted %d %s games%s -> %s" % (kept, sport.upper(),
          "" if everything else " starting within %d min" % window_min, OUT))


def report():
    """Join the ledger to the closing snapshots and report CLV by market."""
    if not os.path.exists(OUT):
        print("no closing snapshots yet -- run: python _closing.py mlb --all"); return
    close = {}
    for l in open(OUT, encoding="utf-8"):
        c = json.loads(l)
        k = (c["game"], c["start"][:10])
        # keep the snapshot taken CLOSEST to first pitch
        if k not in close or abs(c["minutes_to_start"]) < abs(close[k]["minutes_to_start"]):
            close[k] = c
    bets = [json.loads(l) for l in open("live_paper.jsonl", encoding="utf-8") if l.strip()]
    by = collections.defaultdict(list)
    for b in bets:
        if b.get("kind") != "LIVE" or not b.get("odds") or not b.get("game"):
            continue
        k = (b["game"], (b.get("first") or b.get("date") or "")[:10])
        c = close.get(k) or close.get((b["game"], b.get("date", "")[:10]))
        if not c:
            continue
        sel = b.get("selection") or ""
        fair = c["home_fair"] if sel in c["home"] else (c["away_fair"] if sel in c["away"] else None)
        if fair is None:
            continue
        ours = imp(b["odds"])                     # what we paid, with vig
        by[b.get("market", "?")].append(dict(sel=sel, date=b.get("date"), paid=ours,
                                             close=fair, edge=fair - ours, result=b.get("result")))
    if not by:
        print("no bets matched a closing snapshot yet -- snapshots have to be taken on bet days")
        return
    print("%-10s %6s %10s %10s %10s" % ("market", "bets", "we paid", "closed at", "CLV"))
    allrows = []
    for m, rows in sorted(by.items()):
        allrows += rows
        paid = sum(r["paid"] for r in rows) / len(rows)
        clos = sum(r["close"] for r in rows) / len(rows)
        print("%-10s %6d %9.1f%% %9.1f%% %+9.1fpp" % (m, len(rows), 100 * paid, 100 * clos,
                                                      100 * (clos - paid)))
    paid = sum(r["paid"] for r in allrows) / len(allrows)
    clos = sum(r["close"] for r in allrows) / len(allrows)
    beat = sum(1 for r in allrows if r["edge"] > 0)
    print("-" * 50)
    print("%-10s %6d %9.1f%% %9.1f%% %+9.1fpp" % ("ALL", len(allrows), 100 * paid, 100 * clos,
                                                  100 * (clos - paid)))
    print("\nbeat the close on %d of %d bets (%.0f%%)" % (beat, len(allrows), 100 * beat / len(allrows)))
    print("positive CLV means the market moved toward our side after we bet -- that is the")
    print("earliest honest sign the picks are real. Negative means we are taking stale prices.")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] == "report":
        report()
    else:
        snapshot(a[0], everything="--all" in a)
