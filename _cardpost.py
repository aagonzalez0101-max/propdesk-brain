"""CARD -> DISCORD (2026-10-09, user: "full names like the alerts, make it look cool, which to take and why with a large description").
One message per slip: a header card (verdict, hit chance, value, stake) + one card per leg (headshot, HIGHER/LOWER, the line, and a
stats-backed WHY from sports.db: L10, season, last season, vs this opponent, minutes/TOI, opponent defence, model reasons, sharp price).
Called by _pair2x.py; webhook = notify.json "discord_webhook" (#card).
    python _cardpost.py "Taylor Hall" CAR CHI "Shots On Goal" 1.5 over      # preview one leg's WHY text
"""
import json, sqlite3, statistics, datetime, requests, time

try:                                                    # 10/10 user: "make everything Texas time" -- Central, DST-aware
    from zoneinfo import ZoneInfo
    CT = ZoneInfo("America/Chicago")
except Exception:
    CT = datetime.timezone(datetime.timedelta(hours=-5))
ESPORTS = ("CS2", "VAL", "DOTA2", "DOTA 2", "DOTA")
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


ESPORT_FILES = {"CS2": "cs2_maps.jsonl", "VAL": "val_maps2.jsonl", "Dota2": "dota_matches.jsonl"}
_ES_CACHE = {}


def _norm(s):
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def esports_games(leg):
    """10/10 user: CS2/VAL/Dota legs said 'no box-score history' -- the data was in our map files, the card never read it.
    One row per SERIES for the maps the line covers (MAPS 1-2 by default, 'MAP 3' = map 3): stat summed over those maps, and summed
    over players for combos ("Ws + Mira + kaori"). 'season' = last 45 days vs older; 'mins' = rounds (CS2/VAL) or minutes (Dota)."""
    sp = "Dota2" if leg["sport"].upper().startswith("DOTA") else leg["sport"].upper()
    f = ESPORT_FILES.get(sp)
    if not f:
        return None
    st = leg["stat"].upper()
    key = "hs" if "HEADSHOT" in st else "kills" if "KILL" in st else None
    if not key:
        return None
    maps = (3,) if "MAP 3" in st else (1,) if "MAP 1 " in st + " " and "1-2" not in st else (1, 2)
    names = {_norm(n) for n in leg["player"].split(" + ")}
    ids = set()
    if sp == "CS2":
        try:
            for pid, v in json.load(open("cs2_nicks.json", encoding="utf-8")).items():
                if _norm(v.get("nick")) in names:
                    ids.add(str(pid))
        except Exception:
            pass
    rows = _ES_CACHE.get((sp, tuple(sorted(names))))
    if rows is None:
        rows = []
        try:
            for l in open(f, encoding="utf-8"):
                r = json.loads(l)
                who = str(r.get("player")) if sp == "CS2" else _norm(r.get("name"))
                if (who in ids) if sp == "CS2" else (who in names):
                    rows.append(r)
        except Exception:
            return None
        _ES_CACHE[(sp, tuple(sorted(names)))] = rows
    series, seen = {}, set()
    for r in rows:
        k = (r.get("game_id") or r.get("match_id"), r.get("player") or r.get("pid") or r.get("account_id") or r.get("name"))
        if k in seen:                                     # 10/10: two pullers ran at once and wrote every map twice -> 102 "kills"
            continue
        seen.add(k)
        sid = r.get("match") if sp != "Dota2" else "%s|%s" % (r["date"], _norm(r.get("opp")))
        series.setdefault(sid, []).append(r)
    G = []
    cut = (datetime.date.today() - datetime.timedelta(days=45)).isoformat()
    for sid, R in series.items():
        if sp == "CS2":
            order = sorted({r["map_no"] for r in R})
            pick = [r for r in R if r["map_no"] in maps]
        else:                                             # VAL / Dota: maps ordered by game/match id inside the series
            gid = "game_id" if sp == "VAL" else "match_id"
            order = sorted({int(r[gid]) for r in R})
            want = {order[i - 1] for i in maps if i <= len(order)}
            pick = [r for r in R if int(r[gid]) in want]
        if len({(r.get("map_no") or r.get("game_id") or r.get("match_id")) for r in pick}) < len(maps):
            continue                                      # series ended before the maps the line needs (e.g. 2-0, no map 3)
        v = sum(float(r.get(key) or 0) for r in pick)
        span = sum(float(r.get("rounds") or r.get("minutes") or 0) for r in pick) / max(len(names), 1)
        d = min(r["date"] for r in pick)
        G.append(dict(season="recent" if d >= cut else "older", date=d, opp=pick[0].get("opp"), mins=span, v=v))
    G.sort(key=lambda g: g["date"])
    return G or None


def stats_for(leg):
    """Numbers behind the leg. None when the sport/stat has no history we can read."""
    sp, st = leg["sport"], leg["stat"].lower()
    if sp.upper() in ("CS2", "VAL", "DOTA2", "DOTA 2", "DOTA"):
        G = esports_games(leg)
        if not G:
            return None
        db = None
    else:
        keys = NHL_STAT.get(st) if sp == "NHL" else HOOP_STAT.get(st) if sp in ("WNBA", "NBA") else None
        if not keys:
            return None
        try:
            db = sqlite3.connect("sports.db")
            R = _rows(db, sp, leg["player"])
        except Exception:
            return None
        if sp == "NHL" and leg.get("team"):              # "T. Hall" can be two players -- keep his current team's rows + older seasons of the same id
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
    if sp.upper() in ESPORTS:                             # esports: "recent" = last 45 days, "older" = before -- never relabel old as recent
        cur = "recent"
        seas = [g for g in G if g["season"] == "recent"]
        prev = [g for g in G if g["season"] == "older"]
    else:
        cur = max(g["season"] for g in G)
        seas = [g for g in G if g["season"] == cur]
        older = sorted({g["season"] for g in G if g["season"] != cur})
        prev = [g for g in G if older and g["season"] == older[-1]]
    l10 = G[-10:]
    opp = (leg.get("opp") or "")[:3].upper()
    if sp.upper() in ESPORTS:                             # esports opponents are full team names ("Team Vitality" vs "Vitality")
        on = _norm(leg.get("opp")).replace("team", "").replace("esports", "").replace("gaming", "")
        vs = [g for g in G if on and len(on) >= 3 and (on in _norm(g["opp"]) or _norm(g["opp"]).replace("team", "") in on)]
    else:
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


def _dot(hit, n):
    """PickFinder-style dot for how often the stat went the way of the call: green 60%+, yellow 50-60%, red under 50%"""
    if not n:
        return "⚪"
    r = hit / n
    return "🟢" if r >= 0.6 else "🟡" if r >= 0.5 else "🔴"


def _day(d):
    try:
        x = datetime.date.fromisoformat(d)
        return "%s %d/%d" % (x.strftime("%a"), x.month, x.day)
    except Exception:
        return d


def why_text(leg, S):
    """10/10 user (phone screenshot): one fact per line with an icon -- columns and long lines wrap badly on a phone."""
    sp, line, over = leg["sport"], leg["line"], leg["side"] == "over"
    word = "over" if over else "under"
    es = sp.upper() in ESPORTS
    P = []
    if S:
        opp = leg.get("opp") if es else (leg.get("opp") or "")[:3]
        P.append("%s Last 10 · **%d/%d** %s" % (_dot(S["l10_hit"], len(S["l10"])), S["l10_hit"], len(S["l10"]), word))
        if S["seas_n"]:
            P.append("%s %s · **%d/%d**" % (_dot(S["seas_hit"], S["seas_n"]), "Last 45 days" if es else "This season", S["seas_hit"], S["seas_n"]))
        if S["prev_n"]:
            P.append("%s %s · **%.0f%%**" % (_dot(S["prev_hit"], S["prev_n"]), "Before that" if es else "Last season", 100 * S["prev_hit"] / S["prev_n"]))
        if S["vs_n"]:
            P.append("%s vs %s · **%d/%d**" % (_dot(S["vs_hit"], S["vs_n"]), opp, S["vs_hit"], S["vs_n"]))
        P.append("")
        P.append("📊 %s · avg **%.1f**" % (" ".join("%g" % v for v in S["l10_vals"]), S["l10_avg"]))
        if S.get("opp_allowed"):
            n = S["n_teams"]
            tag = " · soft D" if S["opp_rank"] <= n // 3 else " · tight D" if S["opp_rank"] > 2 * n // 3 else ""
            P.append("🛡️ %s allow **%.1f** shots (%s most)%s" % (opp, S["opp_allowed"], _ord(S["opp_rank"]), tag))
        if es:
            P.append("⏱️ %.0f %s per series" % (S["mins"], "min" if sp.upper().startswith("DOTA") else "rounds"))
        else:
            P.append("⏱️ %.1f %s a game" % (S["mins"], "min TOI" if sp == "NHL" else "min"))
        P.append("📅 Last played %s" % _day(S["last"]))
    else:
        P.append("_No game history for this market yet_")
    why = leg.get("why") or ""
    reasons = why.split(":", 1)[-1].split("|")[0].strip() if ":" in why else ""
    P.append("🤖 Model **%.0f%%** %s" % (100 * leg["p"], "HIGHER" if over else "LOWER"))
    if reasons:
        P.append("✅ %s: %s" % (why.split(":")[0], reasons))
    if leg.get("sharp") is not None:
        P.append("💹 Sharp books **%.0f%%**%s" % (100 * leg["sharp"], "" if leg["sharp"] >= 0.5 else " · disagrees"))
    if "RAISED" in why:
        P.append("📈 PP raised this line today")
    if S and len(S["l10"]) >= 5 and S["l10_hit"] / len(S["l10"]) < 0.5:
        P.append("⚠️ Only %d/%d went %s lately" % (S["l10_hit"], len(S["l10"]), word))
    if S and (datetime.date.today() - datetime.date.fromisoformat(S["last"])).days > 10:
        P.append("⚠️ Hasn't played in %d days" % (datetime.date.today() - datetime.date.fromisoformat(S["last"])).days)
    return chr(10).join(P)


PP_LG = {"NHL": 8, "WNBA": 3, "NBA": 7, "NFL": 9, "CFB": 15, "CS2": 265, "VAL": 159, "DOTA2": 174, "LOL": 121, "SOCCER": 82}
_IMG = {}


def headshot(player, sport):
    """player photo from the newest PrizePicks snapshot of that league (10/10: card legs had no headshots)"""
    lid = PP_LG.get((sport or "").upper().replace(" ", ""))
    if not lid:
        return None
    if lid not in _IMG:
        _IMG[lid] = {}
        try:
            import glob, os, _arch
            fs = sorted(_arch.files(os.path.join("lines_archive", "*", "pp_%d_*.json" % lid)), key=lambda f: (os.path.basename(os.path.dirname(f)), f.replace(".gz", "")))
            if fs:
                d = _arch.load(fs[-1])
                for x in d.get("included", []):
                    a = x.get("attributes") or {}
                    if x.get("type") == "new_player" and a.get("image_url"):
                        _IMG[lid][a.get("name")] = a["image_url"]
        except Exception:
            pass
    return _IMG[lid].get(player)


def post_slip(k, grp, ph, stake=None, mult=6.0, be=0.55):
    hook = cfg().get("discord_webhook")
    value = ph * mult - 1
    weakest = min(g["p"] for g in grp)
    SS = [stats_for(g) for g in grp]
    # the bet bar (CLAUDE.md): value + head-to-head + season must agree -- a leg whose last 10 AND last season both go the other way is out
    bad = [g["player"] for g, S in zip(grp, SS) if S and len(S["l10"]) >= 5 and S["l10_hit"] / len(S["l10"]) < 0.5
           and (not S["prev_n"] or S["prev_hit"] / S["prev_n"] < 0.5)]
    verdict = ("⚠️ SWAP %s FIRST · form and last season both disagree" % " & ".join(bad)) if bad else               "✅ TAKE IT" if value >= 0.15 and weakest >= 0.58 else "🟡 LEAN · small edge" if value > 0 else "⛔ PASS"
    head = {"title": "🧾 SLIP %d · %d-pick · %gx" % (k, len(grp), mult), "color": 0x1DB954,
            "description": chr(10).join([
                "## %s" % verdict,
                "🎯 All %d hit **%.0f%%** · worth **%+.0f%%**" % (len(grp), 100 * ph, 100 * value),
                "💵 %s" % (("**$%.2f → $%.2f**" % (stake, stake * mult)) if stake else "5%% of roll at %gx" % mult),
                "📏 Break-even %.0f%% a leg · ours avg %.0f%%" % (100 * be, 100 * sum(g["p"] for g in grp) / len(grp)),
                "📱 Confirm each line on your PP screen"])}
    E = [head]
    for g, S in zip(grp, SS):
        over = g["side"] == "over"
        _t = datetime.datetime.fromisoformat(g["start"].replace("Z", "+00:00")).astimezone(CT)
        t = "%s %d/%d %s TX" % (_t.strftime("%a"), _t.month, _t.day, _t.strftime("%I:%M %p").lstrip("0"))
        stat = (g["stat"] or "").replace("Shots On Goal", "SOG").replace("MAPS 1-2 ", "")
        e = {"title": "%s %s" % ("🔺" if over else "🔻", g["player"]), "color": 0x1ED760 if over else 0xF3727F,
             "description": chr(10).join(["## %s %g %s" % ("HIGHER" if over else "LOWER", g["line"], stat),
                                          "🕕 %s · %s vs %s" % (t, g.get("team") or "", (g.get("opp") or "")[:16]), "",
                                          why_text(g, S)])[:4000],
             "footer": {"text": "PropDesk · %s · PrizePicks" % g["sport"]}}
        img = g.get("img") or headshot(g["player"], g["sport"])
        if img:
            e["thumbnail"] = {"url": img}
        E.append(e)
    if not hook:
        print(json.dumps(E, indent=1, ensure_ascii=False)[:4000]); return
    while sum(len(json.dumps(x, ensure_ascii=False)) for x in E) > 5800:      # Discord: 6000 chars per message
        longest = max(E[1:], key=lambda x: len(x["description"]))
        longest["description"] = longest["description"].rsplit("\n", 1)[0]
    r = requests.post(hook + "?wait=true", json={"username": "PropDesk", "embeds": E}, timeout=20)
    print("discord slip %d: HTTP %s %s" % (k, r.status_code, r.text[:200] if r.status_code >= 300 else ""))
    # 10/10 user: lock/skip by REACTION (self-roles style) -> remember which message is which slip; _reactions.py does the rest
    if r.status_code == 200:
        try:
            m = r.json()
            rec = dict(msg_id=m["id"], channel_id=m["channel_id"], posted=datetime.datetime.now(CT).isoformat(timespec="minutes"), mult=mult,
                       ph=ph, stake=stake, legs=[{k_: g.get(k_) for k_ in ("sport", "player", "team", "opp", "stat", "line", "side", "p", "start")} for g in grp])
            with open("_slips_posted.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception as ex:
            print("slip record:", ex)
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


def post_embed(title, text, color=0x1DB954):
    hook = cfg().get("discord_webhook")
    if hook:
        requests.post(hook, json={"username": "PropDesk", "embeds": [{"title": title, "description": text[:4000], "color": color}]}, timeout=20)


if __name__ == "__main__":
    import sys
    a = sys.argv[1:]
    leg = dict(sport="NHL", player=a[0], team=a[1], opp=a[2], stat=a[3], line=float(a[4]), side=a[5], p=0.6, why="")
    print(why_text(leg, stats_for(leg)))
