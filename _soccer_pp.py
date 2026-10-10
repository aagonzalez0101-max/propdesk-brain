"""SOCCER on real PrizePicks lines (2026-10-09, user: "do it" -- soccer next). The European-data 'gap' was an international break;
PP's soccer board meanwhile was national teams (WC qualifiers / Nations League), MLS, NWSL, Brazil, Saudi, Bundesliga...
This grades EVERY archived PP soccer standard line (lines.db league 82) straight from FotMob (all leagues, free):
  date -> FotMob match list -> the match with this player's team -> his box score -> actual.
Then scans which sides / stats / contexts beat the line.
    python _soccer_pp.py           # build + grade -> _soccer_pp_rows.json, then the scan
"""
import json, sqlite3, re, datetime, collections, unicodedata, time
import _soccer as S

CT = datetime.timezone(datetime.timedelta(hours=-5))
norm = lambda s: re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())
L = sqlite3.connect("lines.db")
lines = {}
for pid, pl, team, stat, line, start, opp in L.execute("SELECT proj_id, player, team, stat, line, start, NULL FROM pp WHERE league=82 AND kind='standard' ORDER BY rowid"):
    k = (stat or "").lower()
    if k in S.STAT and pl and "+" not in pl and start:
        lines[pid] = dict(player=pl, team=team, stat=k, line=line, start=start)
print("archived PP soccer standard lines:", len(lines))

day_matches = {}
def matches_on(day):
    if day in day_matches:
        return day_matches[day]
    out = []
    for tz in ("", "&timezone=America%2FChicago&ccode3=USA"):
        try:
            d = S.get("%s/matches?date=%s%s" % (S.FM, day.replace("-", ""), tz))
            for lg in d.get("leagues") or []:
                for m in lg.get("matches") or []:
                    if (m.get("status") or {}).get("finished"):
                        out.append(dict(id=m["id"], home=m["home"]["name"], away=m["away"]["name"], league=lg.get("name"), hl=m["home"].get("longName"), al=m["away"].get("longName")))
        except Exception as e:
            print("matches", day, e)
        time.sleep(0.4)
    ded = {m["id"]: m for m in out}
    day_matches[day] = list(ded.values())
    return day_matches[day]

def team_match(team, cands):
    t = norm(team)
    for m in cands:
        for nm in (m["home"], m["away"], m["hl"], m["al"]):
            n = norm(nm)
            if n and (n == t or (len(t) >= 4 and (t in n or n in t))):
                return m
    return None

rows, miss = [], collections.Counter()
for pid, l in lines.items():
    utc = datetime.datetime.fromisoformat(l["start"]).astimezone(datetime.timezone.utc)
    if utc > datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3):
        continue
    m = team_match(l["team"], matches_on(utc.date().isoformat()))
    if not m:
        miss["no match found"] += 1; continue
    try:
        box = S.match(m["id"]).get("playerStats", {})
    except Exception:
        miss["match fetch"] += 1; continue
    p = next((v for v in box.values() if norm(v.get("name")) == norm(l["player"])), None)
    if not p:
        p = next((v for v in box.values() if norm(l["player"]).endswith(norm((v.get("name") or "").split()[-1])) and len(norm((v.get("name") or "").split()[-1])) >= 4), None)
    if not p:
        miss["player not in box (DNP?)"] += 1; continue
    a = S.STAT[l["stat"]](p.get("stats") or [])
    if a is None:
        if l["stat"] in S.ZERO_OK:
            a = 0
        else:
            miss["stat missing"] += 1; continue
    a = float(a)
    if a == l["line"]:
        continue
    natl = any(w in (m["league"] or "") for w in ("Nations League", "World Cup", "Qualif", "Friendl", "Euro "))
    rows.append(dict(l, actual=a, over=int(a > l["line"]), league=m["league"], national=natl, home=norm(l["team"]) in (norm(m["home"]), norm(m["hl"])),
                     date=utc.date().isoformat(), match_id=m["id"]))
json.dump(rows, open("_soccer_pp_rows.json", "w"), ensure_ascii=False)
print("graded: %d   dropped: %s" % (len(rows), dict(miss)))
def rep(lab, X):
    if len(X) >= 20:
        print("  %-42s n=%4d  over %5.1f%%   under %5.1f%%" % (lab, len(X), 100 * sum(r["over"] for r in X) / len(X), 100 - 100 * sum(r["over"] for r in X) / len(X)))
rep("ALL", rows)
for s_ in sorted({r["stat"] for r in rows}):
    rep("stat " + s_, [r for r in rows if r["stat"] == s_])
rep("national teams", [r for r in rows if r["national"]]); rep("clubs", [r for r in rows if not r["national"]])
rep("home", [r for r in rows if r["home"]]); rep("away", [r for r in rows if not r["home"]])
for s_ in ("passes attempted", "goalie saves", "shots"):
    for nat in (True, False):
        rep("%s %s" % (s_, "national" if nat else "club"), [r for r in rows if r["stat"] == s_ and r["national"] == nat])
