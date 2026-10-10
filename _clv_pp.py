"""Early vs late betting on PrizePicks (2026-10-09, user: "if we'd made the bets the day before vs right before kickoff").
Every archived PP standard line (hourly snapshots since 10/6, twice a day before) has a FIRST number and a LAST number before the
game; _dir_rows.json graded each against the actual. Questions:
  1) how often / how far do lines move?
  2) when a line moves, does the move point to the right side (is PP's late number sharper)?
  3) betting the side the line later moved toward: hit at the EARLY number vs at the LATE number (= the value of being early)."""
import json, collections
R = [r for r in json.load(open("_dir_rows.json")) if r.get("first_line") is not None and r.get("venue", "PP") == "PP" and r["sport"] in ("NHL", "WNBA")]
print("archived PP standard lines with first+last numbers: %d" % len(R))
mv = [r for r in R if r["line"] != r["first_line"]]
print("  moved before the game: %d (%.0f%%)   by sport: %s" % (len(mv), 100 * len(mv) / len(R), dict(collections.Counter(r["sport"] for r in mv))))
print("  size of moves: %s" % dict(sorted(collections.Counter(round(abs(r["line"] - r["first_line"]), 1) for r in mv).items())))
up = [r for r in mv if r["line"] > r["first_line"]]; dn = [r for r in mv if r["line"] < r["first_line"]]
def rate(X, f):
    return (sum(1 for r in X if f(r)), len(X))
for lab, X, side in (("line moved UP  (PP raised it)", up, "over"), ("line moved DOWN (PP lowered it)", dn, "under")):
    if not X:
        continue
    early_w, n = rate(X, lambda r: (r["actual"] > r["first_line"]) if side == "over" else (r["actual"] < r["first_line"]))
    late_w, _ = rate(X, lambda r: (r["actual"] > r["line"]) if side == "over" else (r["actual"] < r["line"]))
    push_e = sum(1 for r in X if r["actual"] == r["first_line"])
    print("\n  %s: n=%d" % (lab, n))
    print("    betting the %s at the EARLY number: %d-%d  %.1f%%" % (side.upper(), early_w, n - early_w - push_e, 100 * early_w / max(n - push_e, 1)))
    print("    betting the %s at the LATE number:  %d-%d  %.1f%%" % (side.upper(), late_w, n - late_w, 100 * late_w / n))
print("\n  lines that did NOT move: over %.1f%% (n=%d)" % (100 * sum(r["over"] for r in R if r["line"] == r["first_line"]) / max(1, len(R) - len(mv)), len(R) - len(mv)))
