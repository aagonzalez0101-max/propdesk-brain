"""NHL GOALIE SAVES (2026-10-08, user: "nothing on goalies? we gotta look at EVERY single thing").
sports.db has no goalie saves, so the direction model skipped every saves line. This grades EVERY archived PrizePicks standard
saves line straight from the NHL boxscore API, measures the under/over split, and scores today's board.

    python _goalies.py test      # every archived PP standard Goalie Saves line 9/30+ vs the actual saves -> rates by split
    python _goalies.py today     # today's PP standard saves lines with the measured rule + each goalie's recent saves/pulls

Mechanism for the under: a goalie pulled after a bad start (or a blowout / low-shot night) lands far below the line, while the
over is capped by shot volume; PP sets the number near the average, so the distribution's left tail is free money for unders."""
import os, sys, json, glob, datetime, collections, requests

CT = datetime.timezone(datetime.timedelta(hours=-5))
NHL = "https://api-web.nhle.com/v1"
CACHE = "_nhl_goalie_box"
norm = lambda s: "".join(ch for ch in (s or "").lower() if ch.isalnum())


def lastname_key(name):
    p = (name or "").replace(".", ". ").split()
    return norm(p[0][:1] + "".join(p[1:])) if len(p) > 1 else norm(name)


def box(gid):
    os.makedirs(CACHE, exist_ok=True)
    f = os.path.join(CACHE, "%s.json" % gid)
    if os.path.exists(f):
        return json.load(open(f, encoding="utf-8"))
    b = requests.get("%s/gamecenter/%s/boxscore" % (NHL, gid), timeout=30).json()
    if b.get("gameState") in ("OFF", "FINAL"):
        json.dump(b, open(f, "w", encoding="utf-8"))
    return b


def goalie_games(day):
    """{lastname_key: dict(saves, sa, toi, team, opp, home, decision, started, pulled)} for every finished game that day (CT)."""
    out = {}
    sc = requests.get("%s/score/%s" % (NHL, day), timeout=30).json()
    for g in sc.get("games", []):
        if g.get("gameState") not in ("OFF", "FINAL"):
            continue
        b = box(g["id"])
        for side, oside in (("homeTeam", "awayTeam"), ("awayTeam", "homeTeam")):
            gl = (b.get("playerByGameStats") or {}).get(side, {}).get("goalies", [])
            for p in gl:
                toi = p.get("toi") or "0:00"
                mins = int(toi.split(":")[0]) + int(toi.split(":")[1]) / 60
                if mins <= 0:
                    continue
                sv = p.get("saves")
                if sv is None:
                    sa = p.get("saveShotsAgainst") or "0/0"; sv = int(sa.split("/")[0])
                out[lastname_key(p["name"]["default"])] = dict(saves=sv, mins=mins, team=b[side]["abbrev"], opp=b[oside]["abbrev"],
                                                                home=side == "homeTeam", started=p.get("starter", True), pulled=mins < 55 and p.get("starter", True),
                                                                ga=p.get("goalsAgainst"))
    return out


def pp_saves_lines():
    best = {}
    for f in __import__("_arch").files(os.path.join("lines_archive", "*", "pp_8_*.json")):
        if os.path.getsize(f) < (120 if f.endswith(".gz") else 500):
            continue
        d = __import__("_arch").load(f); inc = {(x["type"], x["id"]): x for x in d.get("included", [])}
        for x in d.get("data", []):
            a = x["attributes"]
            if a.get("odds_type") != "standard" or "save" not in (a.get("stat_type") or "").lower():
                continue
            pl = inc.get(("new_player", x["relationships"]["new_player"]["data"]["id"]), {}).get("attributes", {})
            if x["id"] not in best:                                         # FIRST snapshot = the line we'd have bet
                best[x["id"]] = dict(player=pl.get("name"), team=pl.get("team"), opp=a.get("description"), line=float(a["line_score"]), start=a.get("start_time"))
    return list(best.values())


def test():
    L = pp_saves_lines()
    days = sorted({datetime.datetime.fromisoformat(l["start"]).astimezone(CT).date().isoformat() for l in L})
    G = {d: goalie_games(d) for d in days if d < datetime.datetime.now(CT).date().isoformat()}
    rows, seen = [], set()
    for l in L:
        d = datetime.datetime.fromisoformat(l["start"]).astimezone(CT).date().isoformat()
        g = G.get(d, {}).get(lastname_key(l["player"]))
        k = (l["player"], d)
        if not g or k in seen or g["saves"] == l["line"]:
            continue                                                        # didn't play (PP voids) / dup / push
        seen.add(k)
        rows.append(dict(l, day=d, **g, under=int(g["saves"] < l["line"])))
    json.dump(rows, open("_goalie_rows.json", "w"))
    def rep(lab, X):
        if X:
            print("  %-40s n=%3d  UNDER %5.1f%%" % (lab, len(X), 100 * sum(r["under"] for r in X) / len(X)))
    print("NHL GOALIE SAVES -- every archived PrizePicks standard line, graded from NHL box scores")
    rep("ALL", rows)
    for d in sorted({r["day"] for r in rows}):
        rep("  " + d, [r for r in rows if r["day"] == d])
    rep("goalie PULLED (started, <55 min)", [r for r in rows if r["pulled"]])
    rep("full game", [r for r in rows if not r["pulled"]])
    rep("home goalie", [r for r in rows if r["home"]]); rep("road goalie", [r for r in rows if not r["home"]])
    for lo, hi in ((0, 24.5), (24.5, 27.5), (27.5, 40)):
        rep("line %.1f-%.1f" % (lo, hi), [r for r in rows if lo <= r["line"] < hi])
    print("  avg line %.1f  avg saves %.1f" % (sum(r["line"] for r in rows) / len(rows), sum(r["saves"] for r in rows) / len(rows)))


if __name__ == "__main__":
    {"test": test}[sys.argv[1] if len(sys.argv) > 1 else "test"]()
