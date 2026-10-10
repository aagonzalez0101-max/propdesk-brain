"""CALL TRACKER -- every projection call we make, bet or not, graded from box scores (from 2026-09-30).
Tracks TOO CLOSE calls too, so "skip the coin flips" keeps getting measured.

    python _calls.py grade     # settle pending calls (soccer: FotMob, NHL: NHL API, MLB: statsapi)
    python _calls.py report    # record by call type, by sport, since 9/30

Screens append automatically: _soccer.py (every board row), _props.py nhl (every screened leg, one per player/stat/line).
"""
import sys, os, json, datetime, collections

LOG = "calls_log.jsonl"


def log(rows):
    have = set()
    if os.path.exists(LOG):
        for l in open(LOG, encoding="utf-8"):
            x = json.loads(l); have.add((x["date"], x["sport"], x["player"], x["stat"], x["line"]))
    n = 0
    with open(LOG, "a", encoding="utf-8") as f:
        for r in rows:
            k = (r["date"], r["sport"], r["player"], r["stat"], r["line"])
            if k in have or not r.get("call") or r.get("kind") in ("goblin", "demon"):
                continue          # main lines only (user 10/2: goblins inflated the record; we lose on main lines)
            have.add(k); n += 1
            f.write(json.dumps(dict(r, logged=datetime.datetime.now().isoformat(timespec="seconds"), result=None), ensure_ascii=False) + "\n")
    return n


def _dir(call):
    return "over" if "OVER" in call else "under" if "UNDER" in call else None


def grade():
    import _soccer, _props
    rows = [json.loads(l) for l in open(LOG, encoding="utf-8")]
    n = 0
    today = datetime.date.today().isoformat()
    _lb = {}
    for r in rows:
        if r.get("result") is not None or r.get("date", "") >= today:
            continue                                  # skip today's slate: games not finished yet (10/2: grader timed out)
        v = None
        try:
            if r["sport"] == "SOCCER" and r.get("fotmob_id"):
                f = os.path.join(_soccer.CACHE, "p%s.json" % r["fotmob_id"])
                if os.path.exists(f):
                    os.remove(f)
                pd = _soccer.player_data(r["fotmob_id"])
                day2 = (datetime.date.fromisoformat(r["date"]) + datetime.timedelta(days=1)).isoformat()
                m = next((m for m in pd.get("recentMatches") or [] if (m.get("matchDate") or {}).get("utcTime", "")[:10] in (r["date"], day2)), None)
                if m and not m.get("playedInMatch"):
                    r["result"] = "VOID"; n += 1; continue
                if m:
                    box = _soccer.match(m["id"]).get("playerStats", {}).get(str(r["fotmob_id"]))
                    if box:
                        v = _soccer.STAT[r["stat"].lower()](box.get("stats") or [])
                        v = 0 if v is None and r["stat"].lower() in _soccer.ZERO_OK else v
            elif r["sport"] == "NHL":
                p = _props.nhl_player(r["player"])
                L = _props.nhl_logs(p["playerId"], r.get("field") == "saves")
                day2 = (datetime.date.fromisoformat(r["date"]) + datetime.timedelta(days=1)).isoformat()
                hit = [x for x in L if x["date"] in (r["date"], day2)]
                if hit:
                    v = hit[0].get(r.get("field"))
            elif r["sport"] == "GOLF" and r.get("event_id") and r.get("round"):
                import urllib.request as _u
                if r["event_id"] not in _lb:                  # one leaderboard download per event, not per row
                    _lb[r["event_id"]] = json.loads(_u.urlopen(_u.Request("https://site.web.api.espn.com/apis/site/v2/sports/golf/leaderboard?event=%s" % r["event_id"],
                                                          headers={"User-Agent": "Mozilla/5.0"}), timeout=40).read())["events"][0]
                lb = _lb[r["event_id"]]
                for c in lb["competitions"][0]["competitors"]:
                    if (c.get("athlete") or {}).get("displayName", "").lower().replace(" ", "") == r["player"].lower().replace(" ", ""):
                        v = next((ls.get("value") for ls in c.get("linescores") or [] if ls.get("period") == r["round"] and ls.get("value")), None)
            elif r["sport"] in ("MLB", "WNBA", "NBA"):
                v = _db_actual(r)                     # box scores from sports.db (run `python _db.py update` first)
        except Exception:
            continue
        if v is None:
            continue
        r["actual"] = v
        over = v > r["line"]
        d = _dir(r["call"])
        r["result"] = "PUSH" if v == r["line"] else ("CLOSE-" + ("over" if over else "under")) if d is None else ("W" if (over if d == "over" else not over) else "L")
        n += 1
    with open(LOG, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("graded %d" % n)


_DBC = None
_WN = {"points": ["pts"], "pts": ["pts"], "rebounds": ["reb"], "assists": ["ast"], "3pointersmade": ["tpm"], "3ptmade": ["tpm"],
       "ptsrebsasts": ["pts", "reb", "ast"], "pointsrebounds": ["pts", "reb"], "ptsrebs": ["pts", "reb"], "pointsassists": ["pts", "ast"],
       "ptsasts": ["pts", "ast"], "reboundsassists": ["reb", "ast"], "rebsasts": ["reb", "ast"]}


def _db_actual(r):
    """MLB / WNBA / NBA result for one call from sports.db, on the call date or the next day (late West-coast starts)."""
    global _DBC
    import sqlite3, re
    if _DBC is None:
        _DBC = sqlite3.connect("sports.db", timeout=300)
    k = re.sub(r"[^a-z0-9]", "", r["stat"].lower())
    d0 = datetime.date.fromisoformat(r["date"])
    for day in (d0.isoformat(), (d0 + datetime.timedelta(days=1)).isoformat()):
        for (js,) in _DBC.execute("SELECT stats FROM player_games WHERE sport=? AND player=? AND date=?", (r["sport"], r["player"], day)):
            x = json.loads(js)
            if r["sport"] == "MLB":
                f = r.get("field")
                pitch = f in ("strikeOuts", "outs", "earnedRuns") and "batter" not in k
                if (x.get("group") == "pitching") != pitch:
                    continue
                if f == "hrr":
                    return (x.get("hits") or 0) + (x.get("runs") or 0) + (x.get("rbi") or 0)
                if f == "outs":
                    ip = str(x.get("inningsPitched") or "0").split(".")
                    return x.get("outs") if x.get("outs") is not None else int(ip[0]) * 3 + (int(ip[1]) if len(ip) > 1 else 0)
                return x.get(f)
            parts = _WN.get(k)
            if parts and all(x.get(p) is not None for p in parts):
                return sum(x[p] for p in parts)
    return None


def is_alt(r):
    """goblins/demons are out of every record (user 10/2-10/3). UD has no 'goblin' tag: its lopsided-priced lines (a 0.5 goals over at
    2.5-7x, a 0.6x under) ARE its goblins/demons -- 10/3: NHL goals 'unders' at 3-7x made NHL look 84%."""
    if r.get("kind") in ("goblin", "demon") or "GOBLIN" in str(r.get("call")) or "DEMON" in str(r.get("call")):
        return True
    m = r.get("mult")
    ms = [v for v in (m.values() if isinstance(m, dict) else [m]) if isinstance(v, (int, float))]
    return r.get("venue") == "UD" and any(v >= 1.5 or v <= 0.7 for v in ms)


def report(day=None):
    """python _calls.py report [YYYY-MM-DD]  -> BETS (TAKE) first, then LEANS, per sport; main lines only."""
    rows = [json.loads(l) for l in open(LOG, encoding="utf-8")] if os.path.exists(LOG) else []
    rows = [r for r in rows if not is_alt(r) and (day is None or r.get("date") == day)]
    g = [r for r in rows if r.get("result") in ("W", "L")]
    print("CALLS %s: %d main-line calls, %d graded, %d pending  (goblins/demons + UD lopsided lines removed)" % (
        day or "since 9/30", len(rows), len(g), sum(r.get("result") is None for r in rows)))
    by = collections.defaultdict(lambda: [0, 0])
    for r in g:
        k = r["call"].split(" ->")[0].split(" |")[0]
        by[(k.split()[0], r["sport"], k)][0] += r["result"] == "W"; by[(k.split()[0], r["sport"], k)][1] += 1
    for tier, head in (("TAKE", "BETS"), ("LEAN", "LEANS")):
        ks = sorted(k for k in by if k[0] == tier)
        W = sum(by[k][0] for k in ks); N = sum(by[k][1] for k in ks)
        print()
        print(" %s  %d-%d%s" % (head, W, N - W, "  (%.0f%%)" % (100 * W / N) if N else ""))
        for k in ks:
            w, n = by[k]
            print("   %-7s %-11s %d-%d  (%.0f%%)" % (k[1], k[2], w, n - w, 100 * w / n))
    cl = [r for r in rows if str(r.get("result", "")).startswith("CLOSE-")]
    if cl:
        o = sum(r["result"] == "CLOSE-over" for r in cl)
        print()
        print(" TOO CLOSE: %d graded -> over %d, under %d" % (len(cl), o, len(cl) - o))


if __name__ == "__main__":
    (report(*sys.argv[2:3]) if sys.argv[1] == "report" else grade())


# ------------------------------------------------------------------ shared legs file for the slip builder (2026-09-30)
def legs_dump(sport, day, rows):
    """rows: dicts with player, team, opp, stat, line, side, p (our prob of THAT side), venue, kind, mult (payout of that
    side, UD) , call, flags, p_pin. Written per sport per day to legs/<day>_<sport>.json (overwritten each screen)."""
    os.makedirs("legs", exist_ok=True)
    out = []
    for r in rows:
        if r.get("p") is None or r.get("line") is None:
            continue
        out.append({k: r.get(k) for k in ("sport", "player", "team", "opp", "stat", "line", "side", "p", "venue", "kind",
                                          "mult", "call", "flags", "p_pin", "start")})
    json.dump(out, open(os.path.join("legs", "%s_%s.json" % (day, sport)), "w", encoding="utf-8"), ensure_ascii=False)
    return len(out)
