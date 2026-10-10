"""NEWS CHECK -- injuries, ruled-out players, lineup status, and teammates out, for every lookup (2026-09-30).
User: "add a news for injuries or team movement thing to each lookup when it comes to picking sides."
Example that started it: Alanna Smith OUT -> Jessica Shepard's line moved 10.5 -> 11.5 on PrizePicks.

    python _news.py wnba DAL          # team injury list + who it affects
    python _news.py mlb "San Diego Padres"

Used inside the screens: news.flags(sport, team, player) -> ["OUT: ...", "TEAMMATE OUT: ... (role up)", "QUESTIONABLE: ..."].
Sources (free): ESPN injuries for WNBA/NBA/NFL/NHL/MLB; statsapi transactions (MLB, last 3 days); MLB posted lineups.
"""
import sys, json, re, datetime, urllib.request, unicodedata

UA = {"User-Agent": "Mozilla/5.0"}
g = lambda u: json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30).read())
norm = lambda s: re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())
PATH = {"wnba": "basketball/wnba", "nba": "basketball/nba", "nfl": "football/nfl", "nhl": "hockey/nhl", "mlb": "baseball/mlb"}
_cache = {}


def injuries(sport):
    """team (abbrev AND full name, normalized) -> [(player, status, comment)]"""
    if sport in _cache:
        return _cache[sport]
    out = {}
    try:
        d = g("https://site.api.espn.com/apis/site/v2/sports/%s/injuries" % PATH[sport])
    except Exception:
        _cache[sport] = out
        return out
    for t in d.get("injuries", []):
        rows = [(i["athlete"]["displayName"], i.get("status"), (i.get("shortComment") or "")[:160],
                 ((i["athlete"].get("position") or {}).get("abbreviation") or "")) for i in t.get("injuries", [])]
        keys = {norm(t.get("displayName"))}
        for i in t.get("injuries", []):
            ab = ((i.get("athlete") or {}).get("team") or {}).get("abbreviation")
            if ab:
                keys.add(norm(ab))
        for k in keys:
            out.setdefault(k, []).extend(rows)
    _cache[sport] = out
    return out


def team_rows(sport, team):
    inj = injuries(sport)
    k = norm(team)
    if k in inj:
        return inj[k]
    for key, v in inj.items():
        if k and (k in key or key in k):
            return v
    return []


def flags(sport, team, player=None, game_day=None):
    """Plain-language flags for one leg. 'Out' teammates are the role-up signal."""
    f = []
    today = game_day or datetime.date.today().isoformat()
    for name, status, comment, pos in team_rows(sport, team):
        # ESPN keeps season-ending and old notes: only count it for tonight if it's OUT / questionable / doubtful
        st = (status or "").lower()
        if player and norm(name) == norm(player):
            f.append("%s: %s" % ("OUT" if "out" in st else (status or "STATUS").upper(), comment[:90] or status))
        elif sport == "mlb" and pos in ("SP", "RP", "P"):
            continue                                              # an injured pitcher doesn't change a hitter's role
        elif "60-day" in st:
            continue                                              # 60-day IL = long gone, already in everyone's numbers
        elif "out" in st or "-il" in st.replace(" ", "-").lower() or "injured list" in st:
            last = last_game(sport, name)
            c = (comment or "").lower()
            # a game-specific ruling ("ruled out for Game 2 ... Wednesday") is news even after a long absence: the app
            # moved Shepard 10.5 -> 11.5 on Alanna Smith (last game 8/31) being ruled out for Game 2 (2026-09-30)
            dow = datetime.date.fromisoformat(today).strftime("%A").lower()
            tonight = "ruled out" in c and any(w in c for w in ("game ", "tonight", dow, "playoff", "postseason"))
            if last and last >= (datetime.date.fromisoformat(today) - datetime.timedelta(days=10)).isoformat():
                f.append("NEW TEAMMATE OUT: %s (played %s -> role up for others)" % (name, last))
            elif tonight:
                f.append("TEAMMATE RULED OUT TONIGHT: %s (last played %s -- check if the line moved)" % (name, last or "?"))
            # long absences are already in everyone's numbers -> not a flag
        elif any(w in st for w in ("questionable", "doubtful", "day-to-day", "game-time")):
            f.append("TEAMMATE %s: %s" % (status.upper(), name))
    return f


def last_game(sport, player):
    """last game date for a player from sports.db (None if unknown)."""
    import sqlite3, os
    if not os.path.exists("sports.db"):
        return None
    c = sqlite3.connect("sports.db")
    r = c.execute("SELECT MAX(date) FROM player_games WHERE sport=? AND player=?", (sport.upper(), player)).fetchone()
    if r and r[0]:
        return r[0]
    # fallback must match initial + last name: a bare last name gave Rodolfo Duran Jarren Duran's games (2026-09-30)
    parts = player.split()
    r = c.execute("SELECT MAX(date) FROM player_games WHERE sport=? AND (player LIKE ? OR player = ?)",
                  (sport.upper(), parts[0][0] + "% " + parts[-1], parts[0][0] + ". " + parts[-1])).fetchone()
    return r[0] if r else None


def mlb_lineup(team_name, day):
    """(posted?, {player: spot}) for a team's lineup today (statsapi)."""
    import requests
    d = requests.get("https://statsapi.mlb.com/api/v1/schedule", params=dict(sportId=1, date=day, hydrate="lineups"), headers=UA, timeout=30).json()
    for dt in d.get("dates", []):
        for gm in dt["games"]:
            for side in ("away", "home"):
                if gm["teams"][side]["team"]["name"] == team_name:
                    L = (gm.get("lineups") or {}).get(side + "Players") or []
                    return bool(L), {p["fullName"]: i + 1 for i, p in enumerate(L)}
    return False, {}


def mlb_transactions(days=3):
    import requests
    end = datetime.date.today(); start = end - datetime.timedelta(days=days)
    d = requests.get("https://statsapi.mlb.com/api/v1/transactions", params=dict(startDate=start.isoformat(), endDate=end.isoformat()),
                     headers=UA, timeout=30).json()
    return [(t.get("date"), (t.get("toTeam") or t.get("fromTeam") or {}).get("name"), t.get("description")) for t in d.get("transactions", [])]


if __name__ == "__main__":
    sp, team = sys.argv[1], " ".join(sys.argv[2:])
    print("%s %s injury report:" % (sp.upper(), team))
    for r in team_rows(sp, team):
        print("   %-24s %-14s %s" % r[:3])
    if sp == "mlb":
        posted, L = mlb_lineup(team, datetime.date.today().isoformat())
        print("lineup posted:", posted, L if posted else "")
        for t in mlb_transactions():
            if t[1] and norm(team) in norm(t[1]):
                print("   move:", t)
