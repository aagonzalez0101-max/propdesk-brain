"""TOP-5 BETS PER SPORT (2026-10-06, user: "I'm looking at 5 for each esport and sport ... the rest go in another category").

    python _top5.py [YYYY-MM-DD]     # graded: each sport's 5 best calls of the day (= BETS) vs everything else (= REST)

BETS = the 5 highest-confidence calls per sport per day, one per player, main lines only.
  NHL / SOCCER / WNBA / MLB / GOLF : calls_log TAKE/LEAN ranked by our probability of the called side
  CS2                              : cs2_paper.jsonl ranked by model edge
  LoL                              : PP/UD single kills lines, top+mid, ranked by how far the line sits above the
                                     player's previous maps 1+2 series average (bigger cushion for the under first)
REST = every other graded call that day. A sport only earns money from its BETS row.
"""
import sys, json, re, datetime, collections, statistics as st
from _calls import is_alt

norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())


def rec(rows):
    w = sum(1 for r in rows if r)
    return "%d-%d" % (w, len(rows) - w) + (" (%.0f%%)" % (100 * w / len(rows)) if rows else "")


def calls(day):
    R = [json.loads(l) for l in open("calls_log.jsonl", encoding="utf-8") if l.strip()]
    by = collections.defaultdict(list)
    for r in R:
        if r.get("date") != day or is_alt(r) or r.get("result") not in ("W", "L") or not str(r.get("call", "")).startswith(("TAKE", "LEAN")):
            continue
        p = r.get("p") or r.get("p_over") or ((r.get("value") or 0) / (r.get("mult") or 1) if r.get("value") else None)
        if p is not None and "UNDER" in r["call"] and r.get("p_over") is not None:
            p = 1 - r["p_over"]
        by[r["sport"]].append((p or 0, r["player"], r["result"] == "W"))
    return by


def cs2(day):
    out = []
    for l in open("cs2_paper.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if str(r.get("start", ""))[:10] == day and r.get("result") in ("W", "L"):
            out.append((r.get("edge") or 0, r["player"], r["result"] == "W"))
    return out


def lol(day):
    import _lol_check as C
    out = []
    for l in open("lol_lines_graded.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if str(r.get("start", ""))[:10] != day or r.get("result") not in ("OVER", "UNDER") or "+" in (r["player"] or ""):
            continue
        if r.get("role") not in ("top", "mid") or "1+2+3" in (r.get("stat") or "") or "1-3" in (r.get("stat") or ""):
            continue
        ser = [x[1] for x in C.series_log(r["player"]) if x[1] is not None]
        if ser and ser[0] == r.get("actual"):
            ser = ser[1:]                                        # never let the graded series score itself
        if len(ser) < 3:
            continue
        cushion = r["line"] - st.mean(ser[:8])
        out.append((cushion, r["player"], r["result"] == "UNDER"))
    return out


def split(rows):
    rows = sorted(rows, key=lambda x: -x[0])
    seen, bets, rest = set(), [], []
    for score, player, won in rows:
        if player not in seen and len(bets) < 5:
            seen.add(player); bets.append(won)
        else:
            rest.append(won)
    return bets, rest


def main(day):
    print("TOP-5 BETS vs REST, %s (main lines only)" % day)
    print("  %-8s %-18s %-18s" % ("sport", "BETS (top 5)", "REST"))
    table = dict(calls(day))
    table["CS2"] = cs2(day)
    try:
        table["LoL (unders)"] = lol(day)
    except Exception as e:
        print("  LoL failed:", e)
    for sp, rows in sorted(table.items()):
        if not rows:
            continue
        b, r = split(rows)
        print("  %-8s %-18s %-18s" % (sp, rec(b), rec(r)))


if __name__ == "__main__":
    main(next((a for a in sys.argv[1:] if len(a) == 10), (datetime.date.today() - datetime.timedelta(days=1)).isoformat()))
