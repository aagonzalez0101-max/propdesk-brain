"""Re-price a board's ML picks against the 26-30 book consensus.

Our board takes `market_prob` from ONE book (Kalshi). That was 6pp off consensus
on 2026-09-16 SEA/LAA -- bigger than any edge we bet. This re-prices every ML
pick against `_consensus.py` and reports which picks survive.

  python _repricer.py pp/boards/2026-09-16_1519Z.json
"""
import json, sys, io, importlib.util, datetime
sys.path.insert(0, "betting")
import oddsapi as oa
oa.ENABLED = True
spec = importlib.util.spec_from_file_location("cons", "_consensus.py")
cons = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cons)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

amer = lambda p: round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)
imp = lambda a: 100 / (a + 100) if a > 0 else -a / (-a + 100)


def reprice(board_path, sport="mlb", day=None):
    b = json.load(open(board_path, encoding="utf-8"))
    day = day or b.get("day")
    fair = {}
    for r in cons.consensus(sport):
        if day and not r["start"].startswith(day) and not r["start"].startswith(
                (datetime.date.fromisoformat(day) + datetime.timedelta(days=1)).isoformat() + "T0"):
            continue
        fair[r["home"]] = (r["fair_home"], r["tightest"], r["books"])
        fair[r["away"]] = (r["fair_away"], r["tightest"], r["books"])
    out = []
    for p in b.get("picks", []):
        if p.get("market") != "ML":
            continue
        sel = p["selection"]
        hit = fair.get(sel) or next((v for k, v in fair.items() if sel.split()[-1] == k.split()[-1]), None)
        if not hit:
            continue
        cfp, tight, books = hit
        one_book = p["market_prob"]
        model = p["calibrated"]
        ev_old = model / one_book - 1
        ev_new = model / cfp - 1
        out.append(dict(sel=sel, game=p["game"], odds=p["odds"], one_book=one_book, consensus=cfp,
                        model=model, ev_old=ev_old, ev_new=ev_new, tight=tight, books=books,
                        drift=cfp - one_book))
    return out


if __name__ == "__main__":
    path = sys.argv[1]
    rows = reprice(path, sys.argv[2] if len(sys.argv) > 2 else "mlb",
                   sys.argv[3] if len(sys.argv) > 3 else None)
    print(f"{'pick':24s} {'board(1 book)':>13} {'consensus':>10} {'drift':>7} {'model':>7} "
          f"{'EV board':>9} {'EV real':>8} {'books':>6}")
    for r in sorted(rows, key=lambda r: -r["ev_new"]):
        flag = "  <-- board overstated" if r["ev_old"] - r["ev_new"] > 0.03 else ""
        print(f'{r["sel"][:24]:24s} {r["one_book"]:12.1%} {r["consensus"]:10.1%} {r["drift"]:+7.1%} '
              f'{r["model"]:7.1%} {r["ev_old"]:+9.1%} {r["ev_new"]:+8.1%} {r["books"]:6d}{flag}')
    keep = [r for r in rows if r["ev_new"] >= 0.05]
    print(f"\nsurvive at +5% EV vs consensus: {len(keep)} of {len(rows)}")
    for r in keep:
        print(f'  {r["sel"]} ({r["odds"]:+.0f})  consensus {amer(r["consensus"]):+d}  EV {r["ev_new"]:+.1%}')
