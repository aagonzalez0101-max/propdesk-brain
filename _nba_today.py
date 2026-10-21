"""NBA DAY-OF CONTEXT (10/21, user: "find new websites for data, the more the better for niche").
Two free sources the season database can't give us before tip-off:
    official.nba.com/referee-assignments   tonight's crew per game (chief / referee / umpire)
                                           -> crew whistle = their fouls + FTA per game in nba_games/nba_box vs league average
    rotowire.com/basketball/nba-lineups    projected or CONFIRMED starters + who may not play (% to play)
                                           -> the minutes check that would have caught Holland's DNP and Barnes' 9 minutes

    python _nba_today.py            # print tonight's crews (with whistle rating) and lineups, store in sports.db
Tables: nba_refs(date, game, chief, referee, umpire), nba_lineups(date, team, player, pos, starter, pct, status).
"""
import re, html, json, sqlite3, datetime, urllib.request, collections, statistics as st

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
CT = datetime.timezone(datetime.timedelta(hours=-5))
clean = lambda s: html.unescape(re.sub(r"<[^>]+>", " ", s)).strip()


def page(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=30).read().decode("utf-8", "ignore")


def refs():
    t = page("https://official.nba.com/referee-assignments/")
    i = t.find("<table"); j = t.find("</table>", i)
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", t[i:j], re.S):
        cells = [re.sub(r"\s*\(#\d+\)", "", clean(c)) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        cells = [c for c in cells if c]
        if len(cells) >= 4 and "@" in cells[0]:
            out.append(dict(game=cells[0], chief=cells[1], referee=cells[2], umpire=cells[3]))
    return out


def lineups():
    t = page("https://www.rotowire.com/basketball/nba-lineups.php")
    out = []
    for block in t.split('class="lineup is-nba')[1:]:
        abbrs = re.findall(r'class="lineup__abbr">([A-Z]{2,4})<', block)
        lists = re.findall(r'<ul class="lineup__list is-(visit|home)">(.*?)</ul>', block, re.S)
        for side, body in lists:
            team = abbrs[0] if side == "visit" and abbrs else (abbrs[1] if len(abbrs) > 1 else None)
            status = "Confirmed" if "is-confirmed" in body else ("Expected" if "is-expected" in body else "?")
            may_not = body.find("May Not Play")
            for m in re.finditer(r'<li class="lineup__player is-pct-play-(\d+)"[^>]*>.*?<div class="lineup__pos"\s*>(\w+)</div>\s*<a title="([^"]+)"(.*?)</li>', body, re.S):
                inj = re.search(r'class="lineup__inj"[^>]*>([^<]+)<', m.group(4))
                starter = may_not < 0 or m.start() < may_not
                out.append(dict(team=team, player=html.unescape(m.group(3)), pos=m.group(2), pct=int(m.group(1)), starter=starter,
                                status=status, inj=inj.group(1).strip() if inj else ""))
    return out


def crew_whistle(names):
    """fouls + FTA per game in games each official worked (season DB), vs league average"""
    c = sqlite3.connect("sports.db", timeout=60)
    try:
        G = c.execute("select g.game_id, g.officials, sum(b.pf), sum(b.fta) from nba_games g join nba_box b on b.game_id=g.game_id group by g.game_id").fetchall()
    except Exception:
        return None
    if len(G) < 50:
        return None
    lg_pf = st.mean(r[2] for r in G); lg_fta = st.mean(r[3] for r in G)
    per = collections.defaultdict(list)
    for gid, offs, pf, fta in G:
        for o in json.loads(offs or "[]"):
            per[o].append((pf, fta))
    rows = [per[n] for n in names if len(per.get(n, [])) >= 10]
    if not rows:
        return None
    pf = st.mean(st.mean(x[0] for x in r) for r in rows); fta = st.mean(st.mean(x[1] for x in r) for r in rows)
    return pf / lg_pf - 1, fta / lg_fta - 1, sum(len(r) for r in rows)


def main():
    day = datetime.datetime.now(CT).date().isoformat()
    c = sqlite3.connect("sports.db", timeout=60)
    c.executescript("""create table if not exists nba_refs(date text, game text, chief text, referee text, umpire text, primary key(date, game));
                       create table if not exists nba_lineups(date text, team text, player text, pos text, starter int, pct int, status text, inj text,
                       primary key(date, team, player));""")
    R = refs()
    print("REFEREE CREWS %s (%d games)" % (day, len(R)))
    for r in R:
        c.execute("insert or replace into nba_refs values (?,?,?,?,?)", (day, r["game"], r["chief"], r["referee"], r["umpire"]))
        w = crew_whistle([r["chief"], r["referee"], r["umpire"]])
        print("  %-34s %s / %s / %s%s" % (r["game"], r["chief"], r["referee"], r["umpire"],
              ("   whistle: fouls %+.0f%%, FTA %+.0f%% vs league (%d games)" % (100 * w[0], 100 * w[1], w[2])) if w else "   whistle: (needs the season backfill)"))
    L = lineups()
    print("\nLINEUPS (RotoWire)")
    by = collections.defaultdict(list)
    for p in L:
        c.execute("insert or replace into nba_lineups values (?,?,?,?,?,?,?,?)", (day, p["team"], p["player"], p["pos"], int(p["starter"]), p["pct"], p["status"], p["inj"]))
        by[p["team"]].append(p)
    for tm, P in by.items():
        s = [p["player"] for p in P if p["starter"]][:5]; q = ["%s (%s%%%s)" % (p["player"], p["pct"], " " + p["inj"] if p["inj"] else "") for p in P if not p["starter"] or p["pct"] < 100]
        print("  %-4s %-9s starters: %s%s" % (tm, P[0]["status"], ", ".join(s), ("  | may not play: " + ", ".join(q)) if q else ""))
    c.commit()


if __name__ == "__main__":
    main()
