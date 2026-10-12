"""NFL odd PrizePicks props (first-reception yds, longest rec/rush, 1Q stats, completions in first 10...) priced from nflverse play-by-play own-rates.
    python _nfl_oddprops.py <dir with pbp_2025.csv.gz + pbp_2026.csv.gz>
10/12 user: PP posts these with no sharp market (Puka first reception U10.5). Paper log: nfl_odd_paper.jsonl."""
import gzip, csv, collections, re, sys, json, time
sys.path.insert(0, r"C:\Users\aagon\Desktop\sports betting")
import _props as P
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
ids = {}
for r in csv.DictReader(open(r"C:\Users\aagon\Desktop\sports betting\nfl_2026_weekly.csv", encoding="utf-8")):
    ids[norm(r["player_display_name"])] = r["player_id"]
f = lambda r, k: float(r.get(k) or 0)
G = collections.defaultdict(lambda: collections.defaultdict(list))     # pid -> game -> plays
for y in (2025, 2026):
    for r in csv.DictReader(gzip.open(r"%s\pbp_%d.csv.gz" % (sys.argv[1], y), "rt", encoding="utf-8")):
        if r["season_type"] != "REG" or r.get("two_point_attempt") == "1" or not r["qtr"] or r["qtr"] in ("5",):
            continue
        k = (y, r["game_id"])
        for role, idk in (("rec", "receiver_player_id"), ("rush", "rusher_player_id"), ("pass", "passer_player_id")):
            pid = r.get(idk)
            if pid:
                G[pid][k].append((int(float(r["play_id"])), role, r))
def stats(plays):
    plays.sort(key=lambda t: t[0])
    recs = [p for _, role, p in plays if role == "rec" and p["complete_pass"] == "1"]
    rush = [p for _, role, p in plays if role == "rush" and p["play_type"] == "run"]
    pas = [p for _, role, p in plays if role == "pass" and p["pass_attempt"] == "1" and p["sack"] != "1"]
    o = {}
    o["Yards on First Reception"] = f(recs[0], "receiving_yards") if recs else 0.0
    o["Longest Reception"] = max([f(p, "receiving_yards") for p in recs], default=0.0)
    o["Quarters with 1+ Reception"] = float(len({p["qtr"] for p in recs if p["qtr"] in "1234"}))
    o["Rush Yards in First 5 Attempts"] = sum(f(p, "rushing_yards") for p in rush[:5])
    o["Completions in First 10 Pass Attempts"] = float(sum(p["complete_pass"] == "1" for p in pas[:10])) if len(pas) >= 10 else None
    s = c = 0
    for p in pas:
        c = c + 1 if p["complete_pass"] == "1" else 0; s = max(s, c)
    o["Consecutive Pass Completions"] = float(s) if pas else None
    o["Longest Rush"] = max([f(p, "rushing_yards") for p in rush], default=0.0)
    o["Longest Completion"] = max([f(p, "yards_gained") for p in pas if p["complete_pass"] == "1"], default=0.0) if pas else None
    q1 = lambda L, k: sum(f(p, k) for p in L if p["qtr"] == "1")
    o["1Q Receiving Yards"] = q1(recs, "receiving_yards"); o["1Q Rush Yards"] = q1(rush, "rushing_yards")
    o["1Q Pass Yards"] = sum(f(p, "yards_gained") for p in pas if p["qtr"] == "1" and p["complete_pass"] == "1") if pas else None
    return o
lines = []
for lg in (9, 245):
    for l in P.prizepicks(lg, max_age=900):
        if l.get("kind") == "standard" and l["start"][:10] == "2026-10-12":
            st = l["stat"] if lg == 9 else "1Q " + l["stat"]
            lines.append(dict(l, stat=st))
    time.sleep(2)
out = []
for l in lines:
    pid = ids.get(norm(l["player"]))
    if not pid or pid not in G: continue
    games = sorted(G[pid].items())
    vals = [(k[0], stats(pl).get(l["stat"])) for k, pl in games]
    vals = [(y, v) for y, v in vals if v is not None]
    if len(vals) < 6: continue
    v26 = [v for y, v in vals if y == 2026]; vall = [v for y, v in vals]
    ov = lambda V: sum(v > l["line"] for v in V) / max(len([v for v in V if v != l["line"]]), 1)
    pa, p26 = ov(vall), ov(v26) if v26 else None
    side = "over" if pa >= .5 else "under"; rate = pa if side == "over" else 1 - pa
    r26 = (p26 if side == "over" else 1 - p26) if p26 is not None else None
    out.append((rate, l["player"], l["stat"], l["line"], side, len(vall), r26, len(v26), sorted(vall)[len(vall)//2], v26[-5:]))
out.sort(key=lambda t: -t[0])
print("%-6s %-22s %-36s %6s %-5s %-14s %-14s %s" % ("rate", "player", "stat", "line", "side", "2025-26 n", "2026 only", "median | 2026 games"))
for t in out[:25]:
    print("%5.0f%% %-22s %-36s %6s %-5s n=%-11d %-14s med %s | %s" % (100 * t[0], t[1][:22], t[2][:36], t[3], t[4], t[5], ("%.0f%% n=%d" % (100 * t[6], t[7])) if t[6] is not None else "--", t[8], t[9]))
