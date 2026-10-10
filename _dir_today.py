"""Score a day's ARCHIVED PrizePicks lines exactly as the morning run would have (data up to the night before), then grade the
filter's picks straight from ESPN / NHL box scores -- for days not yet loaded into sports.db.  python _dir_today.py 2026-10-07"""
import sys, os, json, glob, datetime, collections, requests
import _direction as D, _dir_search as S

DAY = sys.argv[1]
CT = datetime.timezone(datetime.timedelta(hours=-5))
lines, seen = [], set()
for f in __import__("_arch").files(os.path.join("lines_archive", "*", "pp_*_*.json")):
    lg = int(os.path.basename(f).split("_")[1])
    if lg not in (8, 3) or os.path.getsize(f) < (120 if f.endswith(".gz") else 500):
        continue
    d = __import__("_arch").load(f)
    inc = {(x["type"], x["id"]): x for x in d.get("included", [])}
    for x in d.get("data", []):
        at = x["attributes"]
        if at.get("odds_type") != "standard" or x["id"] in seen:
            continue
        st = at.get("start_time")
        if not st or datetime.datetime.fromisoformat(st).astimezone(CT).date().isoformat() != DAY:
            continue
        pl = inc.get(("new_player", ((x.get("relationships") or {}).get("new_player", {}).get("data") or {}).get("id")), {}).get("attributes", {})
        if "+" in (pl.get("name") or "") or float(at["line_score"]) < 1.5:
            continue
        seen.add(x["id"])                                               # FIRST snapshot of the line = what the morning saw
        lines.append(dict(sport="NHL" if lg == 8 else "WNBA", player=pl.get("name"), team=pl.get("team"), opp=at.get("description"),
                          stat=at.get("stat_type"), line=float(at["line_score"]), start=st, venue="PP"))
print("%s archived standard lines: %d" % (DAY, len(lines)))
homes = {"NHL": S.nhl_home(DAY), "WNBA": S.wnba_home(DAY)}
for l in lines:
    l["home"] = homes[l["sport"]].get(D.TEAMFIX.get(l["team"], l["team"]) if l["sport"] == "WNBA" else l["team"])
pg, tg = D.load_db()
# as-of the morning: drop any db game on/after DAY
for k in pg:
    pg[k] = [g for g in pg[k] if g[0] < DAY]
live, miss = D.featurize(lines, pg, tg, live=True)
for r in live:
    r["home"] = next((l["home"] for l in lines if l["player"] == r["player"] and l["stat"] == r["stat"]), None)
R = S.graded()
R = [r for r in R if r["date"] != DAY]
S.prep(live, R)
scored = []
for sp in ("NHL", "WNBA"):
    M = S.fit([[r[k] for k in S.SPEC[sp]] for r in R if r["sport"] == sp], [r["over"] for r in R if r["sport"] == sp], S.L2)
    X = [r for r in live if r["sport"] == sp]
    if X:
        for r, p in zip(X, S.pred(M, [[r[k] for k in S.SPEC[sp]] for r in X])):
            scored.append(dict(r, p=float(p)))
T = S.top_tier(scored)


def box(sp):
    out = {}
    if sp == "WNBA":
        sb = requests.get("https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard?dates=%s" % DAY.replace("-", ""), timeout=30).json()
        for e in sb["events"]:
            fin = e["status"]["type"].get("completed")
            s = requests.get("https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/summary?event=" + e["id"], timeout=30).json()
            for t in s.get("boxscore", {}).get("players", []):
                st = t["statistics"][0]
                for a in st["athletes"]:
                    if a.get("stats"):
                        d_ = dict(zip(st["labels"], a["stats"]))
                        out[D.norm(a["athlete"]["displayName"])] = (fin, {"pts": float(d_["PTS"]), "reb": float(d_["REB"]), "ast": float(d_["AST"]),
                                                                        "tpm": float(d_["3PT"].split("-")[0])})
    else:
        sc = requests.get("https://api-web.nhle.com/v1/score/%s" % DAY, timeout=30).json()
        for g in sc.get("games", []):
            fin = g.get("gameState") in ("OFF", "FINAL")
            b = requests.get("https://api-web.nhle.com/v1/gamecenter/%s/boxscore" % g["id"], timeout=30).json()
            for side in ("homeTeam", "awayTeam"):
                for grp in ("forwards", "defense"):
                    for p in (b.get("playerByGameStats") or {}).get(side, {}).get(grp, []):
                        nm = p["name"]["default"]
                        out[D.nkey("NHL", nm)] = (fin, {"sog": p.get("sog", 0), "goals": p.get("goals", 0), "assists": p.get("assists", 0),
                                                       "points": p.get("points", 0), "hits": p.get("hits", 0), "blocks": p.get("blockedShots", 0)})
    return out


B = {"WNBA": box("WNBA"), "NHL": box("NHL")}
print("filter picks for %s (model never saw this day):" % DAY)
res = []
for r in T:
    k = D.nkey(r["sport"], r["player"]) if r["sport"] == "NHL" else D.norm(r["player"])
    fields = D.STATMAP[r["sport"]][r["sk"]][0]
    fin, st = B[r["sport"]].get(k, (None, None))
    if st is None:
        out = "no box (DNP?)"
    else:
        a = sum(st.get(f, 0) for f in fields)
        if not fin:
            out = "IN PROGRESS (%g)" % a
        elif a == r["line"]:
            out = "PUSH (%g)" % a
        else:
            w = (a > r["line"]) == (r["side"] == "over"); out = ("W" if w else "L") + " (%g)" % a; res.append((r, w))
    print("  %-5s %-22s %-4s vs %-4s %-16s %-5s %5.1f  model %3.0f%%  -> %s" % (r["sport"], r["player"][:22], r["team"], r["opp"], r["stat"][:16],
          r["side"].upper(), r["line"], 100 * r["conf"], out))
json.dump([dict(sport=r["sport"], player=r["player"], team=r["team"], opp=r["opp"], stat=r["stat"], side=r["side"], line=r["line"], conf=r["conf"], win=w)
           for r, w in res], open("_dir_today_%s.json" % DAY, "w"))
