"""SINGLES vs PARLAYS -- live record (10/27, user: "eventually sportsbook single betting is good, straight bets beat it imo").

For every leg of every PrizePicks slip he bets, record what FanDuel offers on the SAME player/stat at that moment (same line? our
side's American price), then grade it as a $1 single next to what the PP slips really paid. Settles the argument with his own legs.

    python _single_check.py snap [YYYY-MM-DD]    # price today's open PP legs on FanDuel -> single_check.jsonl (rerun is safe)
    python _single_check.py grade                # grade legs from the box scores + report singles vs slips

FanDuel = free public JSON (NBA tabs: points/rebounds/assists/threes/combos + "N+" ladders; NFL via _fanduel). PP-only markets
(FGA, 2PA, FG made, passes...) are logged as NOT OFFERED -- that gap is part of the answer.
Measured context: singles at -120 need 54.5%; a 3x 2-pick needs 57.7%/leg; Kelly at 60% legs = ~12% (single) vs ~4% (2-pick).
"""
import sys, os, re, json, datetime, sqlite3
import _fanduel as F

CT = datetime.timezone(datetime.timedelta(hours=-5))
LOG = "single_check.jsonl"
LEG = re.compile(r"^(.+?)\s+([OU])\s?(\d+(?:\.\d+)?)\s+(.+?)(?:\s*\(.*\))?$")
NBA_TABS = ("player-points", "player-rebounds", "player-assists", "player-threes", "player-combos")
# PP stat -> FanDuel market suffix ("Player - <suffix>") and ladder name ("25+ <ladder>")
NBA_STAT = {"points": ("Points", "Points"), "rebounds": ("Rebounds", "Rebounds"), "assists": ("Assists", "Assists"),
            "3-pt made": ("Made Threes", "Made Threes"), "pts+rebs": ("Pts + Reb", "Pts + Reb"), "pts+asts": ("Pts + Ast", "Pts + Ast"),
            "rebs+asts": ("Reb + Ast", "Reb + Ast"), "pts+rebs+asts": ("Pts + Reb + Ast", "Pts + Reb + Ast")}
n = F.norm


def nba_board():
    """(player, fd stat) -> {"ou": {line: (over_odds, under_odds)}, "ladder": {N: over_odds}}"""
    d = F.g("%s/content-managed-page?page=CUSTOM&customPageId=nba&_ak=%s&timezone=America%%2FChicago" % (F.BASE, F.AK))
    out = {}
    for e in ((d.get("attachments") or {}).get("events") or {}).values():
        if " @ " not in e.get("name", "") or "(" in e["name"]:          # skip the "(TD24)" virtual/sim games
            continue
        for tab in NBA_TABS:
            x = F.g("%s/event-page?_ak=%s&eventId=%s&tab=%s" % (F.BASE, F.AK, e["eventId"], tab))
            for m in ((x.get("attachments") or {}).get("markets") or {}).values():
                name, R = m.get("marketName", ""), m.get("runners") or []
                odds = lambda r: ((r.get("winRunnerOdds") or {}).get("americanDisplayOdds") or {}).get("americanOdds")
                if " - " in name:
                    pl, st = name.split(" - ", 1)
                    ov = next((r for r in R if r.get("runnerName", "").endswith("Over")), None)
                    un = next((r for r in R if r.get("runnerName", "").endswith("Under")), None)
                    if ov and un:
                        out.setdefault((n(pl), st), {"ou": {}, "ladder": {}})["ou"][float(ov.get("handicap") or 0)] = (odds(ov), odds(un))
                else:
                    mm = re.match(r"(?:To Score )?(\d+)\+ (.+)$", name)
                    if mm:
                        for r in R:
                            out.setdefault((n(r.get("runnerName")), mm.group(2)), {"ou": {}, "ladder": {}})["ladder"][int(mm.group(1))] = odds(r)
    return out


def price(leg, B):
    k = NBA_STAT.get(leg["stat"].lower())
    if not k:
        return dict(offered=False, why="PP-only market")
    q = B.get((n(leg["player"]), k[0])) or B.get((n(leg["player"]), k[1]))
    if not q:
        return dict(offered=False, why="player not posted")
    ln, over = leg["line"], leg["side"] == "O"
    if ln in q["ou"]:
        o, u = q["ou"][ln]
        return dict(offered=True, same_line=True, fd_line=ln, odds=o if over else u, other=u if over else o)
    if over and int(ln + 0.5) in q["ladder"] and ln % 1:                # O24.5 == "25+"
        return dict(offered=True, same_line=True, fd_line=ln, odds=q["ladder"][int(ln + 0.5)], other=None, ladder=True)
    if q["ou"]:
        main = min(q["ou"], key=lambda x: abs(x - ln)); o, u = q["ou"][main]
        return dict(offered=True, same_line=False, fd_line=main, odds=o if over else u, other=u if over else o)
    return dict(offered=False, why="no matching line")


def legs_today(day):
    for l in open("live_paper.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if (r.get("game_date") or r.get("date")) != day or "Prize" not in str(r.get("book")) or not r.get("selection"):
            continue
        for s in r["selection"].split(" / "):
            m = LEG.match(s.strip())
            if m:
                yield dict(day=day, sport=r.get("sport"), player=m.group(1), side=m.group(2), line=float(m.group(3)),
                           stat=re.sub(r"\s*\(.*\)", "", m.group(4)).strip(), slip=r["selection"], promo="taco" in str(r.get("market")).lower())


def snap(day):
    if day < datetime.datetime.now(CT).date().isoformat():
        print("FanDuel only posts today's games -- a past day can't be priced"); return
    seen = set()
    if os.path.exists(LOG):
        seen = {json.loads(l)["key"] for l in open(LOG, encoding="utf-8")}
    B = None; rows = []
    for g in legs_today(day):
        g["key"] = "%s|%s|%s|%s|%s" % (day, g["player"], g["stat"], g["side"], g["line"])
        if g["key"] in seen or "NBA" not in (g["sport"] or ""):
            continue
        B = B if B is not None else nba_board()
        g.update(price(g, B), ts=datetime.datetime.now(CT).isoformat(timespec="minutes"))
        seen.add(g["key"]); rows.append(g)
    with open(LOG, "a", encoding="utf-8") as f:
        f.writelines(json.dumps(g) + "\n" for g in rows)
    for g in rows:
        if g["offered"]:
            print("  %-22s %s%-5s %-15s FanDuel %s %s at %+d%s" % (g["player"], g["side"], g["line"], g["stat"], "SAME line" if g["same_line"] else "line %s" % g["fd_line"],
                  "over" if g["side"] == "O" else "under", g["odds"], " (ladder)" if g.get("ladder") else ""))
        else:
            print("  %-22s %s%-5s %-15s NOT OFFERED (%s)" % (g["player"], g["side"], g["line"], g["stat"], g["why"]))
    print("priced %d new legs -> %s" % (len(rows), LOG))


NBA_EXPR = {"points": "pts", "rebounds": "reb", "assists": "ast", "3-pt made": "tpm", "pts+rebs": "pts+reb", "pts+asts": "pts+ast",
            "rebs+asts": "reb+ast", "pts+rebs+asts": "pts+reb+ast", "fg attempted": "fga", "fg made": "fgm",
            "two pointers attempted": "fga-tpa", "3-pt attempted": "tpa"}


def grade():
    if not os.path.exists(LOG):
        print("no legs logged yet"); return
    R = [json.loads(l) for l in open(LOG, encoding="utf-8")]
    c = sqlite3.connect("sports.db")
    for r in R:
        if r.get("result") or r["stat"].lower() not in NBA_EXPR:
            continue
        x = c.execute("SELECT %s, dnp FROM nba_box WHERE date BETWEEN ? AND date(?, '+1 day') AND lower(player)=lower(?)"
                      % NBA_EXPR[r["stat"].lower()], (r["day"], r["day"], r["player"])).fetchone()
        if not x:
            continue
        if x[1]:
            r["result"] = "VOID"; continue
        r["actual"] = x[0]
        r["result"] = "PUSH" if x[0] == r["line"] else ("W" if (x[0] > r["line"]) == (r["side"] == "O") else "L")
    with open(LOG, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r) + "\n" for r in R)
    G = [r for r in R if r.get("result") in ("W", "L")]
    dec = lambda a: 1 + (a / 100 if a > 0 else 100 / -a)
    same = [r for r in G if r.get("offered") and r.get("same_line") and r.get("odds") is not None]
    w = sum(r["result"] == "W" for r in G)
    print("legs graded %d: %d-%d (%.0f%%)  |  FanDuel offered %d of them, same line %d" % (
        len(G), w, len(G) - w, 100 * w / max(1, len(G)), sum(bool(r.get("offered")) for r in G), len(same)))
    if same:
        net = sum(dec(r["odds"]) - 1 if r["result"] == "W" else -1 for r in same)
        sw = sum(r["result"] == "W" for r in same)
        print("  as $1 FanDuel singles (same line): %d-%d  net %+.2f  ROI %+.1f%%  avg price %+d" % (
            sw, len(same) - sw, net, 100 * net / len(same), round(sum(r["odds"] for r in same) / len(same))))
    # the slips those legs were on, as actually paid (live_paper)
    slips = {r["slip"] for r in G}
    S = [json.loads(l) for l in open("live_paper.jsonl", encoding="utf-8")]
    S = [s for s in S if s.get("selection") in slips and s.get("net") is not None and s.get("stake")]
    if S:
        st = sum(float(s["stake"]) for s in S); nt = sum(float(s["net"]) for s in S)
        print("  the PP slips they came from: %d slips, staked $%.2f, net $%+.2f, ROI %+.1f%%" % (len(S), st, nt, 100 * nt / st))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["grade"]:
        grade()
    else:
        snap(a[1] if len(a) > 1 else datetime.datetime.now(CT).date().isoformat())
