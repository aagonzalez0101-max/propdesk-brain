"""NBA NICHE SCREEN (10/20, user: "niche markets like 1Q props, see who is crazy"). The sharp books barely price PrizePicks' niche NBA
stats (FG made/attempted, 3-PT attempted, free throws, personal fouls, turnovers, blocks+steals, double-double, fantasy), so PP sets
them loosely and our own numbers carry the weight -- his Mobley MORE 3 dunks win was this kind of line.

    python _nba_niche.py               # every niche PP line, all dates
    python _nba_niche.py 2026-10-21

Per line: 2025-26 rate (games with 20+ minutes, ESPN game logs), last 20, this preseason, and the gap between his average and the line.
CRAZY = season AND last 20 both >= 75% on one side with the average 20%+ past the line; LEAN = both >= 68%. No sharp price exists for
most of these, so it is an own-model call (feedback_no_pinnacle_gate) -- the bet bar still wants role/minutes unchanged.
"""
import sys, json, re, os, time, datetime, urllib.request, statistics as st

CT = datetime.timezone(datetime.timedelta(hours=-5))
CACHE = os.path.join("data", "nba_finder"); os.makedirs(CACHE, exist_ok=True)
norm = lambda s: re.sub(r"[^a-z]", "", __import__("unicodedata").normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())   # 10/21: "Dončić" was "doni"
NICHE = {"FG Made", "FG Attempted", "3-PT Attempted", "Free Throws Made", "Free Throws Attempted", "Personal Fouls", "Turnovers",
         "Blks+Stls", "Double-Double", "Fantasy Score", "Two Pointers Made", "Two Pointers Attempted", "Steals", "Blocked Shots", "3-PT Made",
         "Dunks", "Offensive Rebounds", "Defensive Rebounds"}


def get(url, cache=None, hours=12):
    f = os.path.join(CACHE, cache) if cache else None
    if f and os.path.exists(f) and time.time() - os.path.getmtime(f) < hours * 3600:
        return json.load(open(f, encoding="utf-8"))
    for w in (0, 20, 45, 90):
        try:
            time.sleep(w)
            d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=40)); break
        except Exception:
            if w == 90:
                raise
    if f:
        json.dump(d, open(f, "w", encoding="utf-8"))
    return d


def ma(x):
    try:
        m, a = str(x).split("-"); return float(m), float(a)
    except Exception:
        return 0.0, 0.0


def value(stat, g):
    fgm, fga = ma(g.get("FG")); tpm, tpa = ma(g.get("3PT")); ftm, fta = ma(g.get("FT"))
    f = lambda k: float(g.get(k) or 0)
    pts, reb, ast, blk, stl, to = f("PTS"), f("REB"), f("AST"), f("BLK"), f("STL"), f("TO")
    return {"FG Made": fgm, "FG Attempted": fga, "3-PT Attempted": tpa, "3-PT Made": tpm, "Free Throws Made": ftm, "Free Throws Attempted": fta,
            "Personal Fouls": f("PF"), "Turnovers": to, "Blks+Stls": blk + stl, "Steals": stl, "Blocked Shots": blk,
            "Two Pointers Made": fgm - tpm, "Two Pointers Attempted": fga - tpa,
            "Double-Double": float(sum(x >= 10 for x in (pts, reb, ast, blk, stl)) >= 2),
            "Fantasy Score": pts + 1.2 * reb + 1.5 * ast + 3 * blk + 3 * stl - to}.get(stat)


def logs(name):
    s = get("https://site.web.api.espn.com/apis/common/v3/search?query=%s&limit=5&type=player" % name.replace(" ", "%20"), "s_%s.json" % norm(name), 240)
    it = [i for i in s.get("items", []) if "nba" in json.dumps(i).lower()]
    if not it:
        return [], []
    pid = it[0]["id"]; out = {}
    for season in ("2026", "2027"):
        gl = get("https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/%s/gamelog?season=%s" % (pid, season),
                 "gl_%s_%s.json" % (pid, season), 240 if season == "2026" else 3)
        lab = gl.get("labels", []); ev = gl.get("events", {}); rows = []
        for stt in gl.get("seasonTypes", []):
            if "Regular" not in stt.get("displayName", "") and "Pre" not in stt.get("displayName", ""):
                continue
            for cat in stt.get("categories", []):
                for e in cat.get("events", []):
                    d = dict(zip(lab, e["stats"])); d["date"] = ev.get(e["eventId"], {}).get("gameDate", "")[:10]; d["pre"] = "Pre" in stt["displayName"]
                    rows.append(d)
        out[season] = sorted(rows, key=lambda r: r["date"])
    last = [g for g in out.get("2026", []) if not g["pre"] and float(g.get("MIN") or 0) >= 20]
    pre = [g for g in out.get("2027", []) if g["pre"]]
    return last, pre


def screen(day=None):
    now = datetime.datetime.now(CT)
    d = get("https://partner-api.prizepicks.com/projections?league_id=7&per_page=1000", "pp_nba_full.json", 0.25)
    P = {x["id"]: x["attributes"] for x in d.get("included", []) if x["type"] == "new_player"}
    lines = []
    for p in d["data"]:
        a = p["attributes"]
        if a.get("odds_type") != "standard" or a["stat_type"] not in NICHE:
            continue
        t = datetime.datetime.fromisoformat(a["start_time"]).astimezone(CT)
        if t < now or (day and t.date().isoformat() != day):
            continue
        pl = P.get(p["relationships"]["new_player"]["data"]["id"], {})
        if "+" in (pl.get("name") or ""):
            continue
        lines.append((pl.get("name"), pl.get("team"), a.get("description"), a["stat_type"], float(a["line_score"]), t))
    print("NBA niche lines: %d" % len(lines))
    out = []
    import sqlite3, _nba_finder as NF                         # 10/21: season DB (every game, full box + dunks) replaces the ESPN-log pulls
    db = sqlite3.connect("sports.db", timeout=60)
    for name, team, opp, stat, ln, t in lines:
        B = NF.db_rows(db, name, stat) if stat in NF.BOX or stat == "Dunks" else None
        if B and B["last"]:
            v = [x[3] for x in B["last"] if x[2] >= 20]
            if len(v) < 15 and len([x for x in B.get("prev", []) if x[2] >= 20]) >= 15:
                v = [x[3] for x in B["prev"] if x[2] >= 20]             # 10/21: missed 2025-26 (Haliburton) -> his last full season, 2024-25
            tn = B["tonight"]; role = "START" if tn and tn[0] else ("BENCH" if tn else "?")
        else:
            try:
                last, _ = logs(name)
            except Exception:
                continue
            v = [x for x in (value(stat, g) for g in last) if x is not None]; role = "?"
        if len(v) < 15:
            continue
        vp = None
        for side in ("over", "under"):
            # 10/21: whole-number lines PUSH on the number (PP drops the leg) -- rate over decided games, not all games
            # (Jalen Smith 3PA O4: 14 of 53 games landed on exactly 4 and were counted as losses)
            hit = lambda X: (lambda D: sum((x > ln) if side == "over" else (x < ln) for x in D) / len(D) if D else None)([x for x in X if x != ln])
            a_, b_ = hit(v), hit(v[-20:]); avg = st.mean(v)
            gap = (avg - ln) / max(ln, 0.5) * (1 if side == "over" else -1)
            if a_ >= 0.68 and b_ >= 0.68:
                if vp is None:                                      # 10/21: preseason (ESPN) only for qualifying lines -- pulling it for all ~400 took 2+ hours
                    try:
                        _, pre = logs(name)
                    except Exception:
                        pre = []
                    vp = [x for x in (value(stat, g) for g in pre) if x is not None]
                tag = "CRAZY" if a_ >= 0.75 and b_ >= 0.75 and gap >= 0.20 else "LEAN"
                if role == "BENCH" and side == "over":
                    tag = "BENCH"                                   # 10/20: Holland DNP / Barnes 9 min -- bench overs are minutes bets
                rc = [m for m, n, x, a in NF.roster_change(db, name, stat, ln, side) if x is not None and x < 0.55]
                if rc:
                    tag = "BENCH"; name = name + " [ROSTER: %s back]" % ", ".join(rc)   # 10/21 Nembhard/Haliburton: wrong sample -> never CRAZY/LEAN
                out.append((min(a_, b_), tag, side, name, team, opp, stat, ln, a_, b_, len(v), avg, hit(vp), [int(x) for x in vp], t, role))
    out.sort(key=lambda r: ({"CRAZY": 0, "LEAN": 1, "BENCH": 2}[r[1]], -r[0]))
    for r in out[:30]:
        print("  %-5s %-5s %-24s %-4s %-5s %-22s %5g | season %3.0f%% (n=%d) last20 %3.0f%% avg %.1f | preseason %s %s | vs %s %s"
              % (r[1], r[2], r[3], r[4], r[15], r[6], r[7], 100 * r[8], r[10], 100 * r[9], r[11], ("%.0f%%" % (100 * r[12])) if r[12] is not None else "--", r[13][-5:], r[5], r[14].strftime("%a %I:%M%p")))
    return out


if __name__ == "__main__":
    screen(sys.argv[1] if len(sys.argv) > 1 else None)
