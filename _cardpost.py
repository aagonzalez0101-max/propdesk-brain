"""CARD -> DISCORD (2026-10-09, user: "full names like the alerts, make it look cool, which to take and why with a large description").
One message per slip: a header card (verdict, hit chance, value, stake) + one card per leg (headshot, HIGHER/LOWER, the line, and a
stats-backed WHY from sports.db: L10, season, last season, vs this opponent, minutes/TOI, opponent defence, model reasons, sharp price).
Called by _pair2x.py; webhook = notify.json "discord_webhook" (#card).
    python _cardpost.py "Taylor Hall" CAR CHI "Shots On Goal" 1.5 over      # preview one leg's WHY text
"""
import json, sqlite3, statistics, datetime, requests, time

CT = datetime.timezone(datetime.timedelta(hours=-5))
NHL_STAT = {"shots on goal": ("sog",), "points": ("points",), "assists": ("assists",), "goals": ("goals",), "hits": ("hits",),
            "blocked shots": ("blocks",)}
HOOP_STAT = {"points": ("pts",), "rebounds": ("reb",), "assists": ("ast",), "pts+rebs+asts": ("pts", "reb", "ast"),
             "pts+asts": ("pts", "ast"), "pts+rebs": ("pts", "reb"), "rebs+asts": ("reb", "ast"), "3-pt made": ("tpm",)}
NHL_TEAM = {"ANA": "Anaheim", "BOS": "Boston", "BUF": "Buffalo", "CAR": "Carolina", "CBJ": "Columbus", "CGY": "Calgary", "CHI": "Chicago",
            "COL": "Colorado", "DAL": "Dallas", "DET": "Detroit", "EDM": "Edmonton", "FLA": "Florida", "LAK": "Los Angeles", "MIN": "Minnesota",
            "MTL": "Montreal", "NJD": "New Jersey", "NSH": "Nashville", "NYI": "NY Islanders", "NYR": "NY Rangers", "OTT": "Ottawa",
            "PHI": "Philadelphia", "PIT": "Pittsburgh", "SEA": "Seattle", "SJS": "San Jose", "STL": "St. Louis", "TBL": "Tampa Bay",
            "TOR": "Toronto", "UTA": "Utah", "VAN": "Vancouver", "VGK": "Vegas", "WPG": "Winnipeg", "WSH": "Washington"}


def cfg():
    try:
        return json.load(open("notify.json", encoding="utf-8"))
    except Exception:
        return {}


def _rows(db, sport, player):
    if sport == "NHL":                                   # NHL rows store "T. Hall"
        first, last = player.split(" ", 1)
        return db.execute("select season,date,opp,minutes,stats,team from player_games where sport='NHL' and player=? order by date",
                          ("%s. %s" % (first[0], last),)).fetchall()
    return db.execute("select season,date,opp,minutes,stats,team from player_games where sport=? and player=? order by date",
                      (sport, player)).fetchall()


def stats_for(leg):
    """Numbers behind the leg. None when the sport/stat isn't in sports.db."""
    sp, st = leg["sport"], leg["stat"].lower()
    keys = NHL_STAT.get(st) if sp == "NHL" else HOOP_STAT.get(st) if sp in ("WNBA", "NBA") else None
    if not keys:
        return None
    try:
        db = sqlite3.connect("sports.db")
        R = _rows(db, sp, leg["player"])
    except Exception:
        return None
    if sp == "NHL" and leg.get("team"):                  # "T. Hall" can be two players -- keep his current team's rows + older seasons of the same id
        R = [r for r in R if r[5] == leg["team"]] or R
    G = []
    for season, date, opp, mins, js, team_ in R:
        s = json.loads(js)
        if sp == "NHL" and s.get("gtype") not in (None, "reg", "post"):
            continue
        G.append(dict(season=season, date=date, opp=opp, mins=mins or 0, v=sum(float(s.get(k) or 0) for k in keys)))
    if not G:
        return None
    line, over = leg["line"], leg["side"] == "over"
    hit = lambda X: sum((g["v"] > line) if over else (g["v"] < line) for g in X)
    cur = max(g["season"] for g in G)
    seas = [g for g in G if g["season"] == cur]
    older = sorted({g["season"] for g in G if g["season"] != cur})
    prev = [g for g in G if older and g["season"] == older[-1]]
    l10 = G[-10:]
    opp = (leg.get("opp") or "")[:3].upper()
    vs = [g for g in G if opp and (g["opp"] or "").upper().startswith(opp)]
    mean = lambda X: statistics.mean(g["v"] for g in X) if X else None
    out = dict(l10=l10, l10_avg=mean(l10), l10_hit=hit(l10), l10_vals=[g["v"] for g in l10],
               seas_n=len(seas), seas_avg=mean(seas), seas_hit=hit(seas), prev_n=len(prev), prev_avg=mean(prev), prev_hit=hit(prev),
               vs_n=len(vs), vs_avg=mean(vs), vs_hit=hit(vs), mins=statistics.mean(g["mins"] for g in l10), last=G[-1]["date"])
    if sp == "NHL":
        # opponent shots allowed per game (this + last season) with league rank; his team's shots per game
        T = {}
        for team_, js in db.execute("select team,stats from player_games where sport='NHL' and season>=? group by game_id,team",
                                    (str(int(cur) - 1),)):
            s = json.loads(js)
            t = T.setdefault(team_, {"for": [], "agst": []})
            t["for"].append(s.get("team_sog") or 0); t["agst"].append(s.get("opp_sog") or 0)
        allowed = {t: statistics.mean(v["agst"]) for t, v in T.items() if len(v["agst"]) > 10}
        rank = sorted(allowed, key=lambda t: -allowed[t])
        if opp in allowed:
            out.update(opp_allowed=allowed[opp], opp_rank=rank.index(opp) + 1, n_teams=len(rank))
        if leg.get("team") in T and len(T[leg["team"]]["for"]) > 10:
            out["team_for"] = statistics.mean(T[leg["team"]]["for"])
    return out


def _ord(n):
    return "%d%s" % (n, "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


def why_text(leg, S):
    sp, line, over = leg["sport"], leg["line"], leg["side"] == "over"
    word = "over" if over else "under"
    P = []
    if S:
        P.append("**Last 10:** %.1f avg -- %s %g in **%d of %d** (%s)" % (S["l10_avg"], word, line, S["l10_hit"], len(S["l10"]),
                 ", ".join("%g" % v for v in S["l10_vals"])))
        if S["seas_n"]:
            P.append("**This season:** %.1f avg in %d games -- %s %d of %d" % (S["seas_avg"], S["seas_n"], word, S["seas_hit"], S["seas_n"]))
        if S["prev_n"]:
            P.append("**Last season:** %.1f avg in %d games -- %s **%.0f%%**" % (S["prev_avg"], S["prev_n"], word, 100 * S["prev_hit"] / S["prev_n"]))
        if S["vs_n"]:
            P.append("**vs %s:** %.1f avg in %d games -- %s %d of %d" % ((leg.get("opp") or "")[:3], S["vs_avg"], S["vs_n"], word, S["vs_hit"], S["vs_n"]))
        P.append("**Role:** %.1f %s a night over his last 10 (last played %s)" % (S["mins"], "min TOI" if sp == "NHL" else "min", S["last"]))
        if S.get("opp_allowed"):
            n = S["n_teams"]
            tag = " -- a soft defence" if S["opp_rank"] <= n // 3 else " -- a tight defence" if S["opp_rank"] > 2 * n // 3 else ""
            P.append("**Opponent:** %s allow **%.1f shots/game** (%s most of %d)%s" % (NHL_TEAM.get((leg.get("opp") or "")[:3], leg.get("opp")),
                     S["opp_allowed"], _ord(S["opp_rank"]), n, tag))
        if S.get("team_for"):
            P.append("**His team:** %s average %.1f shots a game" % (NHL_TEAM.get(leg.get("team"), leg.get("team")), S["team_for"]))
    else:
        P.append("_No box-score history in our database for this market -- the call rests on the model below._")
    why = leg.get("why") or ""
    reasons = why.split(":", 1)[-1].split("|")[0].strip() if ":" in why else ""
    if reasons:
        P.append("**Model:** %.0f%% %s -- %s agree (%s), nothing against" % (100 * leg["p"], "HIGHER" if over else "LOWER", why.split(":")[0], reasons))
    else:
        P.append("**Model:** %.0f%% %s on its projection alone -- no extra reason flags (NHL model-confidence %ss went 21-14 out of sample)"
                 % (100 * leg["p"], "HIGHER" if over else "LOWER", word))
    if leg.get("sharp") is not None:
        P.append("**Sharp book:** %.0f%% %s at this number -- %s" % (100 * leg["sharp"], word, "agrees" if leg["sharp"] >= 0.5 else "leans the other way"))
    if "RAISED" in why:
        P.append("**Line moved:** PP raised it today -- raised lines still went over 62% on paper")
    if S and len(S["l10"]) >= 5 and S["l10_hit"] / len(S["l10"]) < 0.5:
        P.append("⚠️ **Against it:** only %d of his last %d went %s -- the call leans on the matchup, not his form" % (S["l10_hit"], len(S["l10"]), word))
    if S:
        days = (datetime.date.today() - datetime.date.fromisoformat(S["last"])).days
        if days > 10:
            P.append("⚠️ **Check he's playing:** last game was %d days ago" % days)
    return "\n".join(P)


def post_slip(k, grp, ph, stake=None, mult=6.0, be=0.55):
    hook = cfg().get("discord_webhook")
    value = ph * mult - 1
    weakest = min(g["p"] for g in grp)
    SS = [stats_for(g) for g in grp]
    # the bet bar (CLAUDE.md): value + head-to-head + season must agree -- a leg whose last 10 AND last season both go the other way is out
    bad = [g["player"] for g, S in zip(grp, SS) if S and len(S["l10"]) >= 5 and S["l10_hit"] / len(S["l10"]) < 0.5
           and (not S["prev_n"] or S["prev_hit"] / S["prev_n"] < 0.5)]
    verdict = ("⚠️ SWAP %s FIRST -- form and last season both disagree" % " & ".join(bad)) if bad else               "✅ TAKE IT" if value >= 0.15 and weakest >= 0.58 else "🟡 LEAN -- small" if value > 0 else "⛔ PASS"
    head = {"title": "🧾 SLIP %d · %d-Pick Power · %gx" % (k, len(grp), mult), "color": 0x8B5CF6,
            "description": "## %s\nAll %d hit about **%.0f%%** of the time -> worth **%+.0f%%** at %gx (break-even %.0f%% a leg; ours average %.0f%%)."
                           % (verdict, len(grp), 100 * ph, 100 * value, mult, 100 * be, 100 * sum(g["p"] for g in grp) / len(grp)),
            "fields": [{"name": "Stake", "value": ("$%.2f (5%% of roll)" % stake) if stake else "5% of roll", "inline": True},
                       {"name": "Pays", "value": ("$%.2f" % (stake * mult)) if stake else "%gx" % mult, "inline": True},
                       {"name": "Rule", "value": "1 leg per team · confirm each line on your PP screen", "inline": True}]}
    E = [head]
    for g, S in zip(grp, SS):
        over = g["side"] == "over"
        t = datetime.datetime.fromisoformat(g["start"].replace("Z", "+00:00")).astimezone(CT).strftime("%a %m/%d %I:%M %p CT")
        e = {"title": "%s  %s · %s" % ("🔺 HIGHER" if over else "🔻 LOWER", g["player"], g["stat"]), "color": 0x22C55E if over else 0xEF4444,
             "description": ("## %s %g\n%s" % ("HIGHER than" if over else "LOWER than", g["line"], why_text(g, S)))[:4000],
             "fields": [{"name": "Model", "value": "%.0f%%" % (100 * g["p"]), "inline": True},
                        {"name": "Game", "value": "%s vs %s" % (g.get("team") or "", (g.get("opp") or "")[:14]), "inline": True},
                        {"name": "Start", "value": t, "inline": True}],
             "footer": {"text": "PropDesk · %s · PrizePicks" % g["sport"]}}
        if g.get("img"):
            e["thumbnail"] = {"url": g["img"]}
        E.append(e)
    if not hook:
        print(json.dumps(E, indent=1, ensure_ascii=False)[:4000]); return
    while sum(len(json.dumps(x, ensure_ascii=False)) for x in E) > 5800:      # Discord: 6000 chars per message
        longest = max(E[1:], key=lambda x: len(x["description"]))
        longest["description"] = longest["description"].rsplit("\n", 1)[0]
    r = requests.post(hook, json={"username": "PropDesk", "embeds": E}, timeout=20)
    print("discord slip %d: HTTP %s %s" % (k, r.status_code, r.text[:200] if r.status_code >= 300 else ""))
    time.sleep(1)


def roll():
    """today's roll for the 5% stake: road.json start + graded net since start (same as _road.py)"""
    try:
        R = json.load(open("road.json", encoding="utf-8"))
        L = [json.loads(x) for x in open("live_paper.jsonl", encoding="utf-8") if x.strip()]
        return R["start_roll"] + sum(r.get("net") or 0 for r in L if r.get("kind") == "LIVE" and r.get("date", "") >= R["start_date"]
                                     and not r.get("exclude") and r.get("result") in ("WIN", "LOSS", "PUSH", "VOID"))
    except Exception:
        return None


def post_embed(title, text, color=0x8B5CF6):
    hook = cfg().get("discord_webhook")
    if hook:
        requests.post(hook, json={"username": "PropDesk", "embeds": [{"title": title, "description": text[:4000], "color": color}]}, timeout=20)


if __name__ == "__main__":
    import sys
    a = sys.argv[1:]
    leg = dict(sport="NHL", player=a[0], team=a[1], opp=a[2], stat=a[3], line=float(a[4]), side=a[5], p=0.6, why="")
    print(why_text(leg, stats_for(leg)))
