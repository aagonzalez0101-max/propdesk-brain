"""Re-screen WNBA legs on FULL-MINUTES games only (the 70%->62% Clark lesson, 2026-09-28).
role rate = games with minutes >= 85% of the player's last-5 average; h2h = vs tomorrow's opponent, 2024-26."""
import json, urllib.request, sys
from _price import prizepicks, underdog, norm
g = lambda u: json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read())
OPP = {"LV": "IND", "IND": "LV", "MIN": "NY", "NY": "MIN"}
ids = {}
for t in OPP:
    for a in g("https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/teams/%s/roster" % t.lower())["athletes"]:
        ids[norm(a["displayName"])] = (a["id"], t, a["displayName"])

def logs(pid):
    out = []
    for yr in (2024, 2025, 2026):
        try: d = g("https://site.web.api.espn.com/apis/common/v3/sports/basketball/wnba/athletes/%s/gamelog?season=%d" % (pid, yr))
        except Exception: continue
        nm = [n.lower() for n in d.get("names", [])]
        if not nm: continue
        ix = {k: nm.index(k) for k in ("minutes", "points", "totalrebounds", "assists")}
        for st in d["seasonTypes"]:
            for c in st.get("categories", []):
                for e in c.get("events", []):
                    m = d["events"][e["eventId"]]; s = e["stats"]
                    try: v = {k: float(s[i]) for k, i in ix.items()}
                    except ValueError: continue
                    out.append((m["gameDate"][:10], m["opponent"]["abbreviation"], yr, v))
    return sorted(out)

COMBO = {"points": ["points"], "rebounds": ["totalrebounds"], "assists": ["assists"],
         "ptsrebsasts": ["points", "totalrebounds", "assists"], "ptsrebs": ["points", "totalrebounds"],
         "ptsasts": ["points", "assists"], "rebsasts": ["totalrebounds", "assists"]}
ck = lambda s: norm(s).replace("rebounds", "rebs").replace("assists", "asts").replace("points", "pts") \
    .replace("ptsrebsasts", "ptsrebsasts") if norm(s) not in ("points",) else "points"

pp = prizepicks(3)
ud = underdog()
rows = []
cache = {}
for (pn, stat), odds in pp.items():
    if pn not in ids or "standard" not in odds: continue
    k = norm(stat).replace("rebs", "rebs")
    k = {"points": "points", "rebounds": "rebounds", "assists": "assists"}.get(k, k)
    if k not in COMBO: continue
    pid, team, name = ids[pn]
    if pid not in cache: cache[pid] = logs(pid)
    L = cache[pid]
    cur = [r for r in L if r[2] == 2026]
    if len(cur) < 10: continue
    last5 = sum(r[3]["minutes"] for r in cur[-5:]) / 5
    full = [r for r in cur if r[3]["minutes"] >= 0.85 * last5]
    line = float(odds["standard"])
    val = lambda r: sum(r[3][c] for c in COMBO[k])
    h2h = [r for r in L if r[1] == OPP[team] and r[3]["minutes"] >= 0.7 * last5]
    for side in ("over", "under"):
        hit = lambda r: val(r) > line if side == "over" else val(r) < line
        fr = sum(map(hit, full)) / len(full)
        hr = sum(map(hit, h2h)) / len(h2h) if h2h else None
        udp = None
        for (un, us, ul), row in ud.items():
            if un == pn and ul == line and ck(us).replace("pts", "") == ck(stat).replace("pts", ""):
                udp = row["sides"].get(side, (None,))[0]
        rows.append(dict(name=name, team=team, opp=OPP[team], stat=stat, side=side, line=line,
                         full="%d/%d" % (sum(map(hit, full)), len(full)), fr=fr,
                         h2h="%d/%d" % (sum(map(hit, h2h)), len(h2h)) if h2h else "-", hr=hr,
                         last=cur[-1][0], lastmin=cur[-1][3]["minutes"], mins=round(last5), ud=udp))
rows = [r for r in rows if r["fr"] >= 0.60 and len(r["full"]) and int(r["full"].split("/")[1]) >= 15]
rows.sort(key=lambda r: -r["fr"])
json.dump(rows, open("_wnba_rescreen.json", "w"), indent=1)
for r in rows[:30]:
    print("%-20s %-3s v %-3s %-5s %5s %-15s full %-6s %3.0f%%  h2h %-5s  last %s (%2.0f min, avg %d)  UD %s" % (
        r["name"], r["team"], r["opp"], r["side"], r["line"], r["stat"], r["full"], r["fr"] * 100,
        r["h2h"], r["last"], r["lastmin"], r["mins"], r["ud"]))
