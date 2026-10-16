"""LoL prop grader (2026-10-04, user: "CS2, VAL, LoL, Dota -- I wanna be the best at it").

    python _lol_grade.py            # every archived UD + PP LoL kills line -> actual kills -> lol_lines_graded.jsonl
    python _lol_grade.py report     # the claims cappers make, tested against the graded lines

Results come from the OFFICIAL lolesports feed (free, the site's public key): getSchedule -> getEventDetails -> per-game
livestats window, last frame = final kills per player. Leaguepedia rate-limits anonymous calls (10/3), so it is not used.
Lines come from lines_archive/ (UD ud_all_*.json from 9/30, PP pp_121_*.json from 10/4).
Maps 1+2 props sum the first two games; 'Maps 1+2+3' with no game 3 is VOID.
"""
import sys, os, re, json, glob, time, datetime, collections
import requests

H = {"x-api-key": "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z", "User-Agent": "Mozilla/5.0"}
API = "https://esports-api.lolesports.com/persisted/gw"
FEED = "https://feed.lolesports.com/livestats/v1/window/%s"
OUT = "lol_lines_graded.jsonl"
CACHE = "_lol_games_cache.json"
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
GENERIC = {"esports", "esport", "team", "gaming", "club", "academy", "the", "and", "kia", "xian", "beijing"}
toks = lambda s: {t for t in re.split(r"[^a-z0-9]+", (s or "").lower()) if len(t) > 1 and t not in GENERIC}


def archived_lines():
    rows = {}
    for f in __import__("_arch").files("lines_archive/*/ud_all_*.json"):
        try:
            d = __import__("_arch").load(f)
        except Exception:
            continue
        G = {x["id"]: x for x in d.get("games", [])}; A = {a["id"]: a for a in d.get("appearances", [])}; P = {p["id"]: p for p in d.get("players", [])}
        for l in d.get("over_under_lines", []):
            ap = (l.get("over_under") or {}).get("appearance_stat") or {}; a = A.get(ap.get("appearance_id")) or {}
            g = G.get(a.get("match_id")) or {}
            if g.get("sport_id") != "LOL":
                continue
            p = P.get(a.get("player_id")) or {}
            name = ("%s %s" % (p.get("first_name") or "", p.get("last_name") or "")).strip()
            mult = {("under" if o.get("choice") == "lower" else "over"): float(o.get("payout_multiplier") or 1) for o in l.get("options", [])}
            k = ("UD", name, ap.get("display_stat"), g.get("title"), g.get("scheduled_at"))
            rows.setdefault(k, dict(app="UD", player=name, stat=ap.get("display_stat"), match=g.get("title"), start=g.get("scheduled_at"),
                                    line=float(l["stat_value"]), mult=mult))
    for f in __import__("_arch").files("lines_archive/*/pp_121_*.json"):
        try:
            d = __import__("_arch").load(f)
        except Exception:
            continue
        inc = {(x["type"], x["id"]): x for x in d.get("included", [])}
        for x in d.get("data", []):
            a = x["attributes"]
            if a.get("odds_type") != "standard":
                continue
            pl = inc.get(("new_player", x["relationships"]["new_player"]["data"]["id"]), {}).get("attributes", {})
            k = ("PP", pl.get("name"), a.get("stat_type"), a.get("description"), a.get("start_time"))
            rows.setdefault(k, dict(app="PP", player=pl.get("name"), team=pl.get("team"), stat=a.get("stat_type"), match=a.get("description"),
                                    start=a.get("start_time"), line=float(a["line_score"])))
    # 10/16: the raw pp_121_*.json snapshots are compacted into lines.db, and UD closed 10/5 -> the grader found 0 lines and wrote an
    # empty file every night. Read every PP LoL standard line from lines.db (team code is enough for find()).
    try:
        import sqlite3
        for pl, team, stat, line, start in sqlite3.connect("lines.db").execute(
                "select player, team, stat, line, start from pp where league=121 and kind='standard'"):
            k = ("PP", pl, stat, team, start)
            rows.setdefault(k, dict(app="PP", player=pl, team=team, stat=stat, match="", start=start, line=float(line)))
    except Exception as e:
        print("lines.db LoL:", e)
    return list(rows.values())


def maps_needed(stat, app):
    """'MAPS 1-3 Kills' -> games 1..3; 'MAPS 1-2' / 'Maps 1+2' -> 1..2; 'MAP 3 Kills' -> game 3 only (10/16: '1-3' was read as 1-2)."""
    st = (stat or "")
    m = re.search(r"MAPS?\s*(\d)\s*[-+]\s*(?:\d\s*[-+]\s*)?(\d)", st, re.I)
    if m:
        return list(range(int(m.group(1)), int(m.group(2)) + 1))
    m = re.search(r"MAP\s*(\d)\b", st, re.I)
    if m:
        return [int(m.group(1))]
    return [1, 2] if app == "PP" else [1]


def schedule(since):
    evs, tok = [], None
    for _ in range(12):
        u = API + "/getSchedule?hl=en-US" + ("&pageToken=%s" % tok if tok else "")
        s = requests.get(u, headers=H, timeout=30).json()["data"]["schedule"]
        evs += [e for e in s["events"] if e.get("type") == "match"]
        tok = (s.get("pages") or {}).get("older")
        if not tok or min(e["startTime"] for e in s["events"]) < since:
            break
        time.sleep(0.5)
    return evs


def game_kills(gid, cache):
    if gid in cache:
        return cache[gid]
    w = requests.get(FEED % gid, headers=H, timeout=30)
    if w.status_code != 200 or not w.text:
        return None
    j = w.json()
    meta = {}
    for side in ("blueTeamMetadata", "redTeamMetadata"):
        for p in j["gameMetadata"][side]["participantMetadata"]:
            meta[p["participantId"]] = (p["summonerName"], p.get("role"))
    t0 = datetime.datetime.fromisoformat(j["frames"][0]["rfc460Timestamp"].replace("Z", "+00:00"))
    for add in range(90, 15, -5):                          # the last window that exists = the end of the game
        st = (t0 + datetime.timedelta(minutes=add)).replace(microsecond=0)
        st = st.replace(second=st.second // 10 * 10)
        r = requests.get(FEED % gid + "?startingTime=" + st.strftime("%Y-%m-%dT%H:%M:%S.000Z"), headers=H, timeout=30)
        if r.status_code == 200 and r.text:
            f = r.json()["frames"][-1]
            if f.get("gameState") != "finished":
                continue
            out = {}
            for side in ("blueTeam", "redTeam"):
                for p in f[side]["participants"]:
                    nm, role = meta[p["participantId"]]
                    out[nm] = dict(kills=p["kills"], deaths=p["deaths"], assists=p["assists"], role=role, cs=p.get("creepScore"))
            cache[gid] = out
            return out
        time.sleep(0.2)
    return None


def find(evs, row):
    parts = [p.strip() for p in re.split(r"\s+vs\.?\s+", row.get("match") or "", flags=re.I)]
    try:
        t = datetime.datetime.fromisoformat(str(row["start"]).replace("Z", "+00:00"))
    except Exception:
        return None
    best, bs = None, 0
    for e in evs:
        te = datetime.datetime.fromisoformat(e["startTime"].replace("Z", "+00:00"))
        if abs((te - t).total_seconds()) > 36 * 3600:
            continue
        names = [tm.get("name", "") + " " + tm.get("code", "") for tm in e["match"]["teams"]]
        sc = sum(1 for p in parts if any(toks(p) & toks(n) or norm(p) in norm(n) or norm(n.split()[-1]) == norm(p) for n in names))
        if row.get("team"):
            sc += any(norm(row["team"]) == norm(tm.get("code")) for tm in e["match"]["teams"])
        if sc > bs:
            best, bs = e, sc
    return best if bs >= 1 else None


def grade():
    rows = archived_lines()
    print("archived LoL lines:", len(rows), collections.Counter(r["app"] for r in rows))
    since = min(str(r["start"]) for r in rows if r.get("start"))[:10]
    evs = schedule(since)
    print("lolesports matches since %s: %d" % (since, len(evs)))
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    det = {}
    out, why = [], collections.Counter()
    for r in rows:
        e = find(evs, r)
        if not e:
            why["no match"] += 1; continue
        if e.get("state") != "completed":
            why["not finished"] += 1; continue
        mid = e["match"]["id"]
        if mid not in det:
            det[mid] = requests.get(API + "/getEventDetails?hl=en-US&id=%s" % mid, headers=H, timeout=30).json()["data"]["event"]
            time.sleep(0.3)
        games = sorted([g for g in det[mid]["match"]["games"]], key=lambda g: g["number"])
        want = maps_needed(r["stat"], r["app"])
        done_ = {g["number"]: g for g in games if g["state"] == "completed"}
        played = [done_[n] for n in want if n in done_]
        if len(played) < len(want):
            r["result"] = "VOID"; out.append(r); why["void (map not played)"] += 1; continue
        tot, role, ok = 0, None, True
        names = [p.strip() for p in (r["player"] or "").split("+")]       # PP combos: 'A + B + C' = sum of each (10/4)
        stat_key = "assists" if "assist" in (r["stat"] or "").lower() else "kills"
        for g in played:
            gk = game_kills(g["id"], cache)
            if not gk:
                ok = False; break
            for one in names:
                hit = next((v for nm, v in gk.items() if norm(nm.split(" ", 1)[-1]) == norm(one) or norm(nm).endswith(norm(one))), None)
                if not hit:
                    ok = False; break
                tot += hit[stat_key]; role = hit["role"] if len(names) == 1 else "combo"
            if not ok:
                break
        if not ok:
            why["player/game stats missing"] += 1; continue
        r.update(actual=tot, role=role, league=det[mid]["league"]["name"], result=("PUSH" if tot == r["line"] else ("OVER" if tot > r["line"] else "UNDER")))
        out.append(r); why["graded"] += 1
    json.dump(cache, open(CACHE, "w"))
    with open(OUT, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(dict(why))


def report():
    import math
    R = [json.loads(l) for l in open(OUT, encoding="utf-8")]
    G = [r for r in R if r.get("result") in ("OVER", "UNDER")]
    def rep(lab, S):
        n = len(S)
        if n < 15:
            print("  %-34s n=%d" % (lab, n)); return
        u = sum(r["result"] == "UNDER" for r in S)
        print("  %-34s %4d   UNDER %5.1f%%  OVER %5.1f%%   (PP 2-pick needs 57.7%%, UD 1.00x 53.5%%)" % (lab, n, 100 * u / n, 100 * (n - u) / n))
    print("LoL kills lines graded: %d" % len(G))
    rep("ALL", G)
    for app in ("PP", "UD"):
        rep("app " + app, [r for r in G if r["app"] == app])
    rep("COMBOS (PP, 2-3 players)", [r for r in G if "+" in (r["player"] or "")])
    rep("singles", [r for r in G if "+" not in (r["player"] or "")])
    for role in ("top", "jungle", "mid", "bottom", "support"):
        rep("role " + role, [r for r in G if r.get("role") == role])
    for lg in sorted({r.get("league") for r in G}):
        rep("league " + str(lg), [r for r in G if r.get("league") == lg])


if __name__ == "__main__":
    (report if sys.argv[1:] == ["report"] else grade)()
