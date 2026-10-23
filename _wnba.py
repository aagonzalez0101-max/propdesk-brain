"""WNBA prop screen -- counting, not modelling. The NFL recipe applied to the sport he plays best.

    python _wnba.py board            # tonight's Underdog + PrizePicks lines, screened
    python _wnba.py audit            # the over/under balance test that closed this market
    python _wnba.py player <name>    # one player's log against any line

Why this exists: WNBA props were parked at "unresolved" because the old model produced 96%
OVERS (520 overs, 6 unders), which is the same one-sidedness that killed MLB Outs. The
suspected cause was written down at the time: the validation only scored games where she
logged 12+ minutes, but the BASELINE still averaged in her DNPs and six-minute nights, which
drags the baseline down and hands the over a free edge.

So this screen does two things differently:
  * every rate is computed on games where she actually played (MIN_MINUTES), and the same
    filter applies to the baseline -- no asymmetry
  * there is no projection at all. We count how often she cleared THIS number in games she
    played, shrunk toward the positional rate so a 4-game sample can't post 100%

`audit` reports the over/under split. If the screen still comes back one-sided, the market
stays closed -- that is the test this market failed before.
"""
import json, sys, os, re, math, collections, urllib.request

sys.path.insert(0, ".")
from betting import wnbadata as W

UA = {"User-Agent": "Mozilla/5.0 Chrome/124", "Accept": "application/json"}
PPUA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept": "application/json"}
g = lambda u, h=UA: json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=60).read())
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())

MIN_MINUTES = 12.0     # she has to have actually played; applied to EVERY rate, both sides
FLOOR = 0.60           # same own-rate floor that works on NFL props
SHRINK = 6.0           # pseudo-games pulling a rate toward the league base
CACHE = "wnba_logs.json"

# Underdog / PrizePicks stat names -> how to compute it from a box score line
STATS = {
    "points": lambda s: s["pts"],
    "rebounds": lambda s: s["reb"],
    "assists": lambda s: s["ast"],
    "pts+rebs+asts": lambda s: s["pts"] + s["reb"] + s["ast"],
    "pts+rebs": lambda s: s["pts"] + s["reb"],
    "pts+asts": lambda s: s["pts"] + s["ast"],
    "rebs+asts": lambda s: s["reb"] + s["ast"],
    "3-pointers made": lambda s: s["tpm"],
    "steals": lambda s: s["stl"],
    "blocks": lambda s: s["blk"],
    "turnovers": lambda s: s["to"],
    "fantasy points": lambda s: (s["pts"] + 1.2 * s["reb"] + 1.5 * s["ast"]
                                 + 3 * s["stl"] + 3 * s["blk"] - s["to"]),
}
ALIAS = {"pra": "pts+rebs+asts", "points+rebounds+assists": "pts+rebs+asts",
         "pts + rebs + asts": "pts+rebs+asts", "pts + rebs": "pts+rebs",
         "pts + asts": "pts+asts", "rebs + asts": "rebs+asts",
         "three pointers made": "3-pointers made", "3-pt made": "3-pointers made",
         "fantasy score": "fantasy points"}


def season_logs(start="2026-05-01", end=None, refresh=False):
    """player id -> list of box score lines, only games she played MIN_MINUTES."""
    if os.path.exists(CACHE) and not refresh:
        return json.load(open(CACHE, encoding="utf-8"))
    end = end or W.date.today().isoformat()
    games = [x for x in W.games_between(start, end) if x["final"]]
    logs = collections.defaultdict(list)
    for i, gm in enumerate(games, 1):
        try:
            bx = W.boxscore(gm["id"])
        except Exception:
            continue
        for team_id, players in bx.items():
            for s in players:
                if (s.get("min") or 0) < MIN_MINUTES:
                    continue
                logs[s["id"]].append(dict(date=gm["date"], name=s["name"], team=team_id, **{
                    k: s.get(k) or 0 for k in ("min", "pts", "reb", "ast", "stl", "blk", "to", "tpm")}))
        if i % 25 == 0:
            print("  %d/%d games" % (i, len(games)), flush=True)
    out = {k: sorted(v, key=lambda r: r["date"]) for k, v in logs.items()}
    json.dump(out, open(CACHE, "w", encoding="utf-8"))
    print("cached %d players from %d games" % (len(out), len(games)))
    return out


def own_rate(log, stat, line, side, base=0.5):
    """How often she cleared this exact number in games she played. Shrunk toward `base`."""
    f = STATS[stat]
    vals = [f(r) for r in log]
    if not vals:
        return None, 0, None
    hits = sum(1 for v in vals if (v > line if side == "over" else v < line))
    n = len(vals)
    shrunk = (hits + SHRINK * base) / (n + SHRINK)
    return shrunk, n, sum(vals) / n


def minutes_flag(log):
    """A minute restriction shows up in the box score before it shows up in the news.

    No free WNBA injury feed exists (ESPN blocks it, RotoWire ignores the sport filter), so we
    measure the thing the news would tell us: is she playing materially fewer minutes lately
    than she has all season? Fewer minutes means fewer chances, which leans UNDER on every
    counting stat.

    Caveat that keeps this honest: a blowout also cuts minutes. Two short games in a row is a
    hint, not a diagnosis -- and late-season games are more lopsided, so the flag fires more
    often in September than it should.
    """
    mins = [r["min"] for r in log]
    if len(mins) < 6:
        return None, 0.0, 0.0
    season = sum(mins) / len(mins)
    recent = sum(mins[-3:]) / 3
    drop = (recent - season) / season if season else 0.0
    if drop <= -0.20:
        return "CUT HARD", season, recent
    if drop <= -0.12:
        return "trending down", season, recent
    if drop >= 0.12:
        return "trending up", season, recent
    return None, season, recent


def ud_board():
    d = g("https://api.underdogfantasy.com/v1/over_under_lines")
    P = {p["id"]: p for p in d["players"]}
    A = {a["id"]: a for a in d["appearances"]}
    G = {gm["id"]: gm for gm in d.get("games", []) if gm.get("sport_id") == "WNBA"}
    out = []
    for l in d["over_under_lines"]:
        ap = (l.get("over_under") or {}).get("appearance_stat") or {}
        a = A.get(ap.get("appearance_id"))
        if not a or a.get("match_id") not in G:
            continue
        pl = P.get(a.get("player_id")) or {}
        stat = (ap.get("display_stat") or "").lower()
        stat = ALIAS.get(stat, stat)
        if stat not in STATS:
            continue
        out.append(dict(app="Underdog", player=("%s %s" % (pl.get("first_name") or "", pl.get("last_name") or "")).strip(),
                        stat=stat, line=float(l["stat_value"]), game=G[a["match_id"]].get("title"),
                        start=G[a["match_id"]].get("scheduled_at")))
    return out


GOBLIN_MULT, DEMON_MULT = 0.75, 1.25   # payout multipliers PrizePicks applies; override per app


def pp_all_types():
    """Every PrizePicks line INCLUDING goblins and demons -> {(player, stat): {type: line}}."""
    try:
        L = __import__("_ppcache").leagues()
        lid = next((x["id"] for x in L["data"] if x["attributes"]["name"].upper() == "WNBA"), None)
        d = __import__("_ppcache").projections(lid)
    except Exception as e:
        print("prizepicks unavailable:", e)
        return {}
    inc = {(x["type"], x["id"]): x for x in d.get("included", [])}
    out = collections.defaultdict(dict)
    for x in d["data"]:
        a = x["attributes"]
        pl = inc.get(("new_player", x["relationships"]["new_player"]["data"]["id"]), {}).get("attributes", {})
        stat = ALIAS.get((a.get("stat_type") or "").lower(), (a.get("stat_type") or "").lower())
        if stat not in STATS:
            continue
        out[(pl.get("name"), stat)][a.get("odds_type")] = float(a["line_score"])
    return out


def goblins(gob=GOBLIN_MULT, dem=DEMON_MULT):
    """Is the easier line worth the smaller payout? Compare all three on our own hit rates.

    A goblin cuts the line AND the payout, so it only wins if our rate rises by more than the
    payout falls: p_goblin * gob > p_standard. A demon does the reverse -- it pays more, so it
    wins on any line we are only slightly less likely to hit. The app shows the exact
    multipliers; defaults here are the usual 0.75 / 1.25.
    """
    logs = season_logs()
    idx = by_name(logs)
    board = pp_all_types()
    rows = []
    for (player, stat), lines in board.items():
        hit = idx.get(norm(player or ""))
        if not hit or len(lines) < 2:
            continue
        pid, log = hit
        for side in ("over", "under"):
            best = None
            cells = {}
            for kind, line in lines.items():
                r, n, avg = own_rate(log, stat, line, side)
                if r is None or n < 8:
                    continue
                mult = {"goblin": gob, "demon": dem}.get(kind, 1.0)
                # for an UNDER a goblin is the HARDER (lower) line, so the roles flip
                cells[kind] = dict(line=line, rate=r, value=r * mult, mult=mult, avg=avg)
            if len(cells) < 2:
                continue
            best = max(cells, key=lambda k: cells[k]["value"])
            std = cells.get("standard")
            if not std:
                continue
            gain = cells[best]["value"] / std["value"] - 1 if std["value"] else 0
            rows.append(dict(player=player, stat=stat, side=side, cells=cells,
                             best=best, gain=gain, std_rate=std["rate"]))
    rows.sort(key=lambda r: -r["gain"])
    print("Where the alternate line beats the standard one  (goblin pays %.2fx, demon pays %.2fx)\n" % (gob, dem))
    print("  %-18s %-6s %-14s %26s %26s %26s   take" %
          ("player", "side", "stat", "goblin", "standard", "demon"))
    shown = 0
    for r in rows:
        if r["gain"] <= 0.02 or r["std_rate"] < 0.45:
            continue
        cellstr = []
        for kind in ("goblin", "standard", "demon"):
            c = r["cells"].get(kind)
            cellstr.append("%5.1f  %3.0f%% -> %4.2f" % (c["line"], 100 * c["rate"], c["value"]) if c else "        -         ")
        print("  %-18s %-6s %-14s %26s %26s %26s   %s (+%.0f%%)" %
              (r["player"][:18], r["side"], r["stat"][:14], cellstr[0], cellstr[1], cellstr[2],
               r["best"].upper(), 100 * r["gain"]))
        shown += 1
        if shown >= 20:
            break
    if not shown:
        print("  nothing -- the standard line is the best version of every pick today")
    print("\n  'value' is our hit rate times the payout multiplier. Higher is better, and it is")
    print("  the only fair way to compare an easier line that pays less against a harder one")
    print("  that pays more. Set the real multipliers from the app: _wnba.py goblins 0.8 1.3")


def pp_board():
    try:
        L = __import__("_ppcache").leagues()
        lid = next((x["id"] for x in L["data"] if x["attributes"]["name"].upper() == "WNBA"), None)
        if not lid:
            return []
        d = __import__("_ppcache").projections(lid)
    except Exception as e:
        print("prizepicks unavailable:", e)
        return []
    inc = {(x["type"], x["id"]): x for x in d.get("included", [])}
    out = []
    for x in d["data"]:
        a = x["attributes"]
        if a.get("odds_type") != "standard":
            continue
        pl = inc.get(("new_player", x["relationships"]["new_player"]["data"]["id"]), {}).get("attributes", {})
        stat = (a.get("stat_type") or "").lower()
        stat = ALIAS.get(stat, stat)
        if stat not in STATS:
            continue
        out.append(dict(app="PrizePicks", player=pl.get("name"), stat=stat, line=float(a["line_score"]),
                        game=a.get("description"), start=a.get("start_time")))
    return out


def by_name(logs):
    idx = {}
    for pid, log in logs.items():
        if log:
            idx.setdefault(norm(log[-1]["name"]), (pid, log))
    return idx


def board():
    logs = season_logs()
    idx = by_name(logs)
    lines = ud_board() + pp_board()
    print("%d lines on the board (%d Underdog, %d PrizePicks)"
          % (len(lines), sum(1 for x in lines if x["app"] == "Underdog"),
             sum(1 for x in lines if x["app"] == "PrizePicks")))
    rows = []
    for l in lines:
        hit = idx.get(norm(l["player"]))
        if not hit:
            continue
        pid, log = hit
        for side in ("over", "under"):
            r, n, avg = own_rate(log, l["stat"], l["line"], side)
            if r is None or n < 8:
                continue
            flag, season_min, recent_min = minutes_flag(log)
            rows.append(dict(l, side=side, rate=r, games=n, avg=avg, pid=pid,
                             mins=recent_min, season_min=season_min, flag=flag))
    rows.sort(key=lambda r: -r["rate"])
    picks = [r for r in rows if r["rate"] >= FLOOR]
    print("\n%-20s %-6s %-15s %5s %6s %7s %12s %-5s %s" %
          ("player", "side", "stat", "line", "hits", "average", "minutes", "app", "minutes flag"))
    for r in picks[:25]:
        mins = "%.0f -> %.0f" % (r.get("season_min") or 0, r.get("mins") or 0)
        note = r.get("flag") or ""
        if note in ("CUT HARD", "trending down") and r["side"] == "under":
            note += ", helps the under"
        elif note == "trending up" and r["side"] == "over":
            note += ", helps the over"
        elif note in ("CUT HARD", "trending down") and r["side"] == "over":
            note += ", FIGHTS the over"
        print("%-20s %-6s %-15s %5.1f %5.0f%% %7.1f %12s %-5s %s" %
              (r["player"][:20], r["side"], r["stat"][:15], r["line"], 100 * r["rate"],
               r["avg"], mins, r["app"][:5], note))
    o = sum(1 for r in picks if r["side"] == "over")
    print("\n%d picks clear the %.0f%% floor -- %d overs, %d unders"
          % (len(picks), 100 * FLOOR, o, len(picks) - o))
    if picks and (o / len(picks) > 0.8 or o / len(picks) < 0.2):
        print("ONE-SIDED. That is the flag that closed this market before -- do not bet it yet.")
    return picks


def audit():
    """The test the market failed: is the screen balanced once the minutes filter is honest?"""
    logs = season_logs()
    tot = collections.Counter()
    for pid, log in logs.items():
        if len(log) < 10:
            continue
        for stat in ("points", "rebounds", "assists", "pts+rebs+asts"):
            vals = [STATS[stat](r) for r in log]
            half = len(vals) // 2
            base = sum(vals[:half]) / half            # first-half average = the "book line"
            line = round(base * 2) / 2
            later = vals[half:]
            tot[(stat, "over")] += sum(1 for v in later if v > line)
            tot[(stat, "under")] += sum(1 for v in later if v < line)
    print("Against each player's own first-half average, how did the second half land?")
    print("(a fair baseline splits close to 50/50 -- the old version was 96%% overs)\n")
    for stat in ("points", "rebounds", "assists", "pts+rebs+asts"):
        o, u = tot[(stat, "over")], tot[(stat, "under")]
        print("  %-16s %4d over / %4d under  = %.0f%% overs" % (stat, o, u, 100 * o / max(1, o + u)))


def player(name, line=None, stat="pts+rebs+asts"):
    logs = season_logs()
    idx = by_name(logs)
    hit = idx.get(norm(name)) or next(((p, l) for k, (p, l) in idx.items() if norm(name) in k), None)
    if not hit:
        print("no player called", name); return
    pid, log = hit
    print("%s -- %d games with %d+ minutes" % (log[-1]["name"], len(log), MIN_MINUTES))
    print("  %-16s %6s %6s" % ("stat", "average", "last 5"))
    for s in ("points", "rebounds", "assists", "pts+rebs+asts", "3-pointers made"):
        vals = [STATS[s](r) for r in log]
        print("  %-16s %6.1f  %s" % (s, sum(vals) / len(vals), " ".join("%.0f" % v for v in vals[-5:])))
    if line:
        for side in ("over", "under"):
            r, n, avg = own_rate(log, stat, float(line), side)
            print("  %s %s %s: %.0f%% over %d games" % (stat, side, line, 100 * r, n))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "board"
    if cmd == "board":
        board()
    elif cmd == "audit":
        audit()
    elif cmd == "goblins":
        goblins(float(sys.argv[2]) if len(sys.argv) > 2 else GOBLIN_MULT,
                float(sys.argv[3]) if len(sys.argv) > 3 else DEMON_MULT)
    elif cmd == "player":
        player(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None,
               sys.argv[4] if len(sys.argv) > 4 else "pts+rebs+asts")
    else:
        print(__doc__)
