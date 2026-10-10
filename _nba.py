"""NBA prop screen -- the WNBA recipe ported. Counting, not projecting.

    python _nba.py pull 2025-10-21 2026-06-30   # build the game-log cache (once per season)
    python _nba.py board                        # tonight's Underdog + PrizePicks lines, screened
    python _nba.py audit                        # the over/under balance test
    python _nba.py player "Nikola Jokic" 35.5   # one player against any line
    python _nba.py minutes                      # who is trending up or down on minutes

Same five rules that make the WNBA screen honest:
  * every rate is counted on games he actually PLAYED (MIN_MINUTES), and the same filter applies
    to the baseline -- the asymmetry there is what produced 96% overs and closed WNBA for a month
  * no projection; we count how often he cleared THIS number, shrunk so a 4-game sample cannot
    post 100%
  * minutes first: a role change is the thing that breaks a prop, and it shows in the box score
    before it shows in the news
  * the balance check runs on demand, and a one-sided board means our bug, not an edge
  * nothing is bet until it has a forward record: 150 picks beating break-even by 3+ points
"""
import json, sys, os, re, time, collections, itertools, urllib.request
import requests   # ESPN 403s urllib but serves requests, same as betting/wnbadata

H = {"User-Agent": "Mozilla/5.0"}
PPUA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept": "application/json"}
UA = {"User-Agent": "Mozilla/5.0 Chrome/124", "Accept": "application/json"}
g = lambda u, h=H: requests.get(u, headers=h, timeout=45).json()
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())

SB = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=%s"
SUM = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=%s"
CACHE = "nba_logs.json"
MIN_MINUTES = 12.0
FLOOR = 0.60
SHRINK = 6.0

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
    "blks+stls": lambda s: s["blk"] + s["stl"],
    "fantasy points": lambda s: (s["pts"] + 1.2 * s["reb"] + 1.5 * s["ast"]
                                 + 3 * s["stl"] + 3 * s["blk"] - s["to"]),
}
ALIAS = {"pra": "pts+rebs+asts", "points+rebounds+assists": "pts+rebs+asts",
         "pts + rebs + asts": "pts+rebs+asts", "pts + rebs": "pts+rebs",
         "pts + asts": "pts+asts", "rebs + asts": "rebs+asts",
         "three pointers made": "3-pointers made", "3-pt made": "3-pointers made",
         "fantasy score": "fantasy points", "blks + stls": "blks+stls"}
BOX_KEYS = ["min", "fg", "3pt", "ft", "oreb", "dreb", "reb", "ast", "stl", "blk", "to", "pf", "pts"]


def parse_box(ev_id):
    """One game -> list of player lines.

    ESPN gives positional stat strings plus a `names` header like
    ['MIN','PTS','FG','3PT','FT','REB','AST','TO','STL','BLK',...], so map by the SHORT names
    (`keys` uses long camelCase and pairs like 'fieldGoalsMade-fieldGoalsAttempted').
    """
    d = g(SUM % ev_id)
    out = []
    teams = [(t.get("team") or {}).get("id") for t in (d.get("boxscore") or {}).get("players", [])]
    for ti, team in enumerate((d.get("boxscore") or {}).get("players", [])):
        tid = (team.get("team") or {}).get("id")
        opp = teams[1 - ti] if len(teams) == 2 else None
        for grp in team.get("statistics", []):
            names = [str(n).upper() for n in grp.get("names", [])]
            for ath in grp.get("athletes", []):
                if ath.get("didNotPlay"):
                    continue
                st = ath.get("stats") or []
                if len(st) != len(names):
                    continue
                row = dict(zip(names, st))

                def num(k, default=0.0):
                    v = row.get(k)
                    try:
                        return float(str(v).replace("+", ""))
                    except (TypeError, ValueError):
                        return default

                tpm = 0.0
                if "-" in str(row.get("3PT", "")):
                    try:
                        tpm = float(str(row["3PT"]).split("-")[0])
                    except ValueError:
                        pass
                fga = fta = 0.0
                for k, tgt in (("FG", "fga"), ("FT", "fta")):
                    if "-" in str(row.get(k, "")):
                        try:
                            v = float(str(row[k]).split("-")[1])
                            if tgt == "fga":
                                fga = v
                            else:
                                fta = v
                        except ValueError:
                            pass
                out.append(dict(pid=(ath.get("athlete") or {}).get("id"),
                                name=(ath.get("athlete") or {}).get("displayName"),
                                team=tid, opp=opp,          # opponent: needed for matchup + head-to-head
                                min=num("MIN"), pts=num("PTS"), reb=num("REB"),
                                ast=num("AST"), stl=num("STL"), blk=num("BLK"),
                                to=num("TO"), tpm=tpm,
                                fga=fga, fta=fta,           # shot volume = his share of the offence
                                starter=bool(ath.get("starter"))))
    return out


def pull(start, end):
    """Walk the schedule and cache every box score. Finished games never change."""
    import datetime
    logs = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
    seen = {r["game"] for v in logs.values() for r in v}
    d0 = datetime.date.fromisoformat(start); d1 = datetime.date.fromisoformat(end)
    day = d0; added = 0
    while day <= d1:
        try:
            sb = g(SB % day.strftime("%Y%m%d"))
        except Exception:
            day += datetime.timedelta(days=1); continue
        for ev in sb.get("events", []):
            if ev["status"]["type"]["state"] != "post" or ev["id"] in seen:
                continue
            try:
                for s in parse_box(ev["id"]):
                    if s["min"] < MIN_MINUTES or not s["pid"]:
                        continue
                    logs.setdefault(str(s["pid"]), []).append(dict(s, date=day.isoformat(), game=ev["id"]))
                added += 1
            except Exception:
                pass
            time.sleep(0.15)
        if added and added % 40 == 0:
            json.dump(logs, open(CACHE, "w", encoding="utf-8")); print("  %d games cached" % added, flush=True)
        day += datetime.timedelta(days=1)
    for pid in logs:
        logs[pid].sort(key=lambda r: r["date"])
    json.dump(logs, open(CACHE, "w", encoding="utf-8"))
    print("cached %d players from %d new games -> %s" % (len(logs), added, CACHE))


def load():
    if not os.path.exists(CACHE):
        sys.exit("no %s yet -- run: python _nba.py pull 2025-10-21 2026-06-30" % CACHE)
    return json.load(open(CACHE, encoding="utf-8"))


def own_rate(log, stat, line, side, base=0.5):
    f = STATS[stat]
    vals = [f(r) for r in log]
    if not vals:
        return None, 0, None
    hits = sum(1 for v in vals if (v > line if side == "over" else v < line))
    return (hits + SHRINK * base) / (len(vals) + SHRINK), len(vals), sum(vals) / len(vals)


def minutes_flag(log):
    """A role change shows in the box score before it shows in the news."""
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


def by_name(logs):
    idx = {}
    for pid, log in logs.items():
        if log:
            idx.setdefault(norm(log[-1]["name"]), (pid, log))
    return idx


def ud_board():
    d = g("https://api.underdogfantasy.com/v1/over_under_lines", UA)
    P = {p["id"]: p for p in d["players"]}
    A = {a["id"]: a for a in d["appearances"]}
    G = {gm["id"]: gm for gm in d.get("games", []) if gm.get("sport_id") == "NBA"}
    out = []
    for l in d["over_under_lines"]:
        ap = (l.get("over_under") or {}).get("appearance_stat") or {}
        a = A.get(ap.get("appearance_id"))
        if not a or a.get("match_id") not in G:
            continue
        pl = P.get(a.get("player_id")) or {}
        stat = ALIAS.get((ap.get("display_stat") or "").lower(), (ap.get("display_stat") or "").lower())
        if stat not in STATS:
            continue
        sides = {}
        for o in l.get("options", []):
            try:
                sides["under" if o.get("choice") == "lower" else "over"] = float(o.get("american_price"))
            except (TypeError, ValueError):
                pass
        out.append(dict(app="Underdog", player=("%s %s" % (pl.get("first_name") or "", pl.get("last_name") or "")).strip(),
                        stat=stat, line=float(l["stat_value"]), prices=sides,
                        game=G[a["match_id"]].get("title")))
    return out


def pp_board():
    try:
        L = g("https://partner-api.prizepicks.com/leagues", PPUA)
        lid = next((x["id"] for x in L["data"] if x["attributes"]["name"].upper() == "NBA"), None)
        d = g("https://partner-api.prizepicks.com/projections?per_page=1000&league_id=%s" % lid, PPUA)
    except Exception as e:
        print("  (prizepicks unavailable: %s)" % e)
        return []
    inc = {(x["type"], x["id"]): x for x in d.get("included", [])}
    out = []
    for x in d["data"]:
        a = x["attributes"]
        pl = inc.get(("new_player", x["relationships"]["new_player"]["data"]["id"]), {}).get("attributes", {})
        stat = ALIAS.get((a.get("stat_type") or "").lower(), (a.get("stat_type") or "").lower())
        if stat not in STATS:
            continue
        out.append(dict(app="PrizePicks", player=pl.get("name"), stat=stat,
                        line=float(a["line_score"]), kind=a.get("odds_type"),
                        prices={}, game=a.get("description")))
    return out


def board():
    logs = load(); idx = by_name(logs)
    lines = ud_board() + pp_board()
    print("%d NBA lines on the board" % len(lines))
    if not lines:
        print("nothing posted -- the NBA season is not running yet. The screen is ready for opening night.")
        return []
    rows = []
    for l in lines:
        hit = idx.get(norm(l["player"]))
        if not hit:
            continue
        pid, log = hit
        flag, season_min, recent = minutes_flag(log)
        for side in ("over", "under"):
            r, n, avg = own_rate(log, l["stat"], l["line"], side)
            if r is None or n < 8 or r < FLOOR:
                continue
            rows.append(dict(l, side=side, rate=r, games=n, avg=avg, flag=flag,
                             season_min=season_min, mins=recent))
    rows.sort(key=lambda r: -r["rate"])
    print("\n%-22s %-6s %-15s %6s %6s %7s %12s %s" %
          ("player", "side", "stat", "line", "hits", "average", "minutes", "flag"))
    for r in rows[:25]:
        note = r["flag"] or ""
        if note in ("CUT HARD", "trending down"):
            note += " helps" if r["side"] == "under" else " FIGHTS"
        print("%-22s %-6s %-15s %6.1f %5.0f%% %7.1f %6.0f->%-4.0f %s" %
              (r["player"][:22], r["side"], r["stat"][:15], r["line"], 100 * r["rate"],
               r["avg"], r["season_min"], r["mins"], note))
    o = sum(1 for r in rows if r["side"] == "over")
    print("\n%d clear the %.0f%% floor -- %d overs, %d unders" % (len(rows), 100 * FLOOR, o, len(rows) - o))
    if rows and (o / len(rows) > 0.8 or o / len(rows) < 0.2):
        print("ONE-SIDED -- that is our bug, not an edge. Do not bet it.")
    return rows


def audit():
    logs = load()
    tot = collections.Counter()
    for pid, log in logs.items():
        if len(log) < 10:
            continue
        for stat in ("points", "rebounds", "assists", "pts+rebs+asts", "3-pointers made"):
            vals = [STATS[stat](r) for r in log]
            half = len(vals) // 2
            base = sum(vals[:half]) / half
            line = round(base * 2) / 2
            for v in vals[half:]:
                if v > line:
                    tot[(stat, "over")] += 1
                elif v < line:
                    tot[(stat, "under")] += 1
    print("Second half vs his own first-half average (a fair baseline splits near 50/50)\n")
    for stat in ("points", "rebounds", "assists", "pts+rebs+asts", "3-pointers made"):
        o, u = tot[(stat, "over")], tot[(stat, "under")]
        if o + u:
            print("  %-16s %5d over / %5d under = %.0f%% overs" % (stat, o, u, 100 * o / (o + u)))


def minutes():
    logs = load()
    rows = []
    for pid, log in logs.items():
        flag, season, recent = minutes_flag(log)
        if flag and len(log) >= 10:
            rows.append((recent - season, log[-1]["name"], season, recent, flag, len(log)))
    rows.sort()
    print("Minutes movers (last 3 games vs season)\n")
    for ch, nm, s, r, flag, n in rows[:12] + rows[-12:]:
        print("  %-24s %5.1f -> %5.1f  (%+.1f)  %s" % (nm[:24], s, r, ch, flag))


def player(name, line=None, stat="pts+rebs+asts"):
    logs = load(); idx = by_name(logs)
    hit = idx.get(norm(name)) or next(((p, l) for k, (p, l) in idx.items() if norm(name) in k), None)
    if not hit:
        print("no player called", name); return
    pid, log = hit
    flag, season, recent = minutes_flag(log)
    print("%s -- %d games with %d+ minutes   (%.1f min, last 3 %.1f%s)" %
          (log[-1]["name"], len(log), MIN_MINUTES, season, recent, "  " + flag if flag else ""))
    for s in ("points", "rebounds", "assists", "pts+rebs+asts", "3-pointers made", "fantasy points"):
        vals = [STATS[s](r) for r in log]
        print("  %-16s avg %6.1f   last 5: %s" % (s, sum(vals) / len(vals),
                                                  " ".join("%.0f" % v for v in vals[-5:])))
    if line:
        for side in ("over", "under"):
            r, n, avg = own_rate(log, stat, float(line), side)
            print("  %s %s %s: %.0f%% over %d games" % (stat, side, line, 100 * r, n))


if __name__ == "__main__":
    a = sys.argv[1:]
    cmd = a[0] if a else "board"
    if cmd == "pull":
        pull(a[1], a[2])
    elif cmd == "audit":
        audit()
    elif cmd == "minutes":
        minutes()
    elif cmd == "player":
        player(a[1], a[2] if len(a) > 2 else None, a[3] if len(a) > 3 else "pts+rebs+asts")
    else:
        board()
