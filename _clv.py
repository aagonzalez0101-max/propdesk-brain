"""CLV TRACKER (11/20, user: "i love the clv tracker"). Every leg we bet since the challenge started (10/10): the line we got vs the line
PrizePicks CLOSED at (last standard line seen before start, cloud lines.db). CLV in points, signed so + = we beat the close:
    under: entry - close   (we took U14.5, it closed 13.5 -> +1: the market moved toward our side after we bet)
    over : close - entry
Beating the close over hundreds of legs is the fastest proof a process has an edge -- long before the W-L record settles.
Also: sharp-book closing P(our side) at OUR number where the books priced it (pregame snapshots only).
    python _clv.py            # report + clv.json (used by the tracker page)
"""
import json, sqlite3, re, datetime, collections, unicodedata, statistics

CT = __import__("zoneinfo").ZoneInfo("America/Chicago")
nn = lambda s: re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())
SHARP_STAT = {"Points": "points", "Rebounds": "rebounds", "Assists": "assists", "3-PT Made": "threes made", "Pts+Rebs+Asts": "pts & rebs & asts",
              "Shots On Goal": "shots on goal", "Pass Yards": "passing yards", "Rush Yards": "rushing yards", "Receiving Yards": "receiving yards",
              "Receptions": "receptions"}


def load_closes():
    L = sqlite3.connect("lines.db")
    close = {}       # (norm player, stat, CT day) -> (last_seen, line)
    for pl, st, ln, start, ls in L.execute("select player, stat, line, start, last_seen from pp where kind='standard' and start >= '2026-10-09'"):
        try:
            day = datetime.datetime.fromisoformat(start).astimezone(CT).date().isoformat()
        except Exception:
            continue
        k = (nn(pl), st, day)
        if k not in close or (ls or "") > close[k][0]:
            close[k] = (ls or "", ln, start)
    sharp = collections.defaultdict(list)
    for book, sp, pl, st, ln, p, ts in L.execute("select book, sport, player, stat, line, p_over, ts from sharp where ts >= '2026-10-09'"):
        sharp[(nn(pl), st)].append((ts, ln, p))
    return close, sharp


def main():
    close, sharp = load_closes()
    R = [json.loads(l) for l in open("live_paper.jsonl", encoding="utf-8") if l.strip()]
    R = [r for r in R if r.get("kind") == "LIVE" and (r.get("date") or "") >= "2026-10-10"]
    rows = []
    for r in R:
        for x in r.get("legs") or []:
            pl, st, ln, side = x.get("player"), x.get("stat"), x.get("line"), (x.get("side") or "").lower()
            if pl is None or ln is None or side not in ("over", "under"):
                continue
            day = r.get("game_date") or r.get("date")
            c = close.get((nn(pl), st, day))
            row = dict(date=day, sport=r.get("sport"), player=pl, stat=st, side=side, entry=float(ln), close=None, clv=None,
                       sharp_close=None, result=x.get("result"), tag=(r.get("system_tag") or "")[:40], slip=r.get("result"))
            if c:
                cl = float(c[1]); row["close"] = cl
                row["clv"] = (float(ln) - cl) if side == "under" else (cl - float(ln))
                ss = SHARP_STAT.get(st)
                if ss:
                    try:
                        t0 = datetime.datetime.fromisoformat(c[2])
                        snaps = []
                        for ts, l_, p in sharp.get((nn(pl), ss), []):
                            if l_ == float(ln):
                                t = datetime.datetime.fromisoformat(ts)
                                if t0 - datetime.timedelta(days=2) <= t < t0:        # pregame only (live snapshots leak)
                                    snaps.append((t, p))
                        if snaps:
                            p = max(snaps)[1]; row["sharp_close"] = p if side == "over" else 1 - p
                    except Exception:
                        pass
            rows.append(row)
    json.dump(rows, open("clv.json", "w"), indent=0)
    have = [r for r in rows if r["clv"] is not None]
    print("CLV TRACKER since 10/10: %d legs logged, %d matched to a PP closing line" % (len(rows), len(have)))
    if not have:
        return
    beat = sum(r["clv"] > 0 for r in have); same = sum(r["clv"] == 0 for r in have); lost = sum(r["clv"] < 0 for r in have)
    print("  beat the close %d | same %d | worse %d   avg CLV %+.2f pts" % (beat, same, lost, statistics.mean(r["clv"] for r in have)))
    for lab, f in (("legs that WON", lambda r: r["result"] == "W"), ("legs that LOST", lambda r: r["result"] == "L")):
        X = [r for r in have if f(r)]
        if X:
            print("  %-15s n=%3d  avg CLV %+.2f" % (lab, len(X), statistics.mean(r["clv"] for r in X)))
    print("\n  by sport:")
    for sp, X in sorted(collections.defaultdict(list, {k: [r for r in have if r["sport"] == k] for k in {r["sport"] for r in have}}).items()):
        print("   %-18s n=%3d  beat %2d / worse %2d  avg %+.2f" % (sp, len(X), sum(r["clv"] > 0 for r in X), sum(r["clv"] < 0 for r in X), statistics.mean(r["clv"] for r in X)))
    print("\n  biggest moves (last 15):")
    for r in sorted(have, key=lambda r: r["date"])[-15:]:
        print("   %s %-22s %-14s %s%-5g close %-5g CLV %+g  %s" % (r["date"], r["player"][:22], r["stat"][:14], r["side"][0].upper(), r["entry"], r["close"], r["clv"], r["result"] or ""))


if __name__ == "__main__":
    main()
