"""LINE MOVEMENT on our legs (2026-10-03). User: "that's how we know we chose something good" (Talbot 8.5 -> 9.5 = CLV).

    python _linemove.py [YYYY-MM-DD]     # every UD snapshot since the night before -> each card/five leg: first seen vs now

Moved WITH us = the line went up on an over / down on an under, or our side's multiplier dropped (the app is charging more for
it) -> closing-line value, the best early proof a pick was good. Moved AGAINST us = the opposite. Pulled = gone from the board.
"""
import sys, os, glob, json, datetime, re
import _props as P

CT = datetime.timezone(datetime.timedelta(hours=-5))
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())


def parse(d):
    G = {x["id"]: x for x in d.get("games", [])}; A = {a["id"]: a for a in d.get("appearances", [])}; Pl = {p["id"]: p for p in d.get("players", [])}
    out = {}
    for l in d.get("over_under_lines", []):
        ap = (l.get("over_under") or {}).get("appearance_stat") or {}
        a = A.get(ap.get("appearance_id")) or {}
        pl = Pl.get(a.get("player_id")) or {}
        name = ("%s %s" % (pl.get("first_name") or "", pl.get("last_name") or "")).strip()
        sides = {("under" if o.get("choice") == "lower" else "over"): float(o.get("payout_multiplier") or 1) for o in l.get("options", [])}
        k = (norm(name), norm(ap.get("display_stat")))
        line = float(l["stat_value"])
        # keep the main line: the one whose multipliers are closest to even
        score = sum(abs(v - 1) for v in sides.values())
        if k not in out or score < out[k][2]:
            out[k] = (line, sides, score)
    return out


def main(day):
    prev = (datetime.date.fromisoformat(day) - datetime.timedelta(days=1)).isoformat()
    files = __import__("_arch").files(os.path.join("lines_archive", prev, "ud_all_2*.json")) + __import__("_arch").files(os.path.join("lines_archive", day, "ud_all_*.json"))
    snaps = []
    for f in files:
        try:
            snaps.append((os.path.basename(os.path.dirname(f)) + " " + f.replace(".gz", "")[-11:-5], parse(__import__("_arch").load(f))))
        except Exception:
            pass
    now = {}
    for sp in ("NHL", "NFL", "CFB", "WNBA"):
        for l in P.underdog(sp):
            k = (norm(l["player"]), norm(l["stat"])); sc = sum(abs(v - 1) for v in l["mult"].values())
            if k not in now or sc < now[k][2]:
                now[k] = (l["line"], l["mult"], sc)
    legs = []
    for f in glob.glob(os.path.join("cards", "%s*.json" % day)):
        c = json.load(open(f))
        if isinstance(c, list):
            for s in c:
                legs += s.get("legs", [])
        else:
            legs += c.get("legs", []) + c.get("extra", [])
    seen = set()
    print("LINE MOVES on %s legs (%d UD snapshots since %s 9pm)" % (day, len(snaps), prev))
    for g in legs:
        k = (norm(g["player"]), norm(g["stat"]))
        if (k, g["side"]) in seen:
            continue
        seen.add((k, g["side"]))
        first = next(((t, s[k]) for t, s in snaps if k in s), None)
        cur = now.get(k)
        if not first:
            print("  %-22s %-16s %-5s  no earlier snapshot" % (g["player"], g["stat"], g["side"])); continue
        (t0, (l0, m0, _)) = first
        if not cur:
            verdict, txt = "PULLED", "gone from the board"
        else:
            l1, m1, _ = cur
            dl = (l1 - l0) * (1 if g["side"] == "over" else -1)
            dm = (m0.get(g["side"], 1) - m1.get(g["side"], 1))
            verdict = "WITH US" if dl > 0 or (dl == 0 and dm > 0.02) else ("AGAINST" if dl < 0 or dm < -0.02 else "flat")
            txt = "%s %s x%.2f  ->  now %s x%.2f" % (t0, l0, m0.get(g["side"], 1), l1, m1.get(g["side"], 1))
        print("  %-8s %-22s %-16s %-5s  %s" % (verdict, g["player"][:22], g["stat"][:16], g["side"], txt))


if __name__ == "__main__":
    main(next((a for a in sys.argv[1:] if len(a) == 10), datetime.datetime.now(CT).date().isoformat()))
