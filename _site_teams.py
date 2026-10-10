"""PROP DESK -- team pages (2026-09-30). User: "search a team -> it shows the players, rankings and how it works".

    python _site_teams.py        # adds DB[sport].teams to site/players.json (run after _site_players.py)

Every sport: injuries (ESPN), next game, players with lines tonight, offense and defense ranks (computed on the page from
the same defense-vs-position tables the player pages use).
NFL extra (nflverse play-by-play): record, points for/against, offense and defense EPA per play, pass rate, plays per game,
explosive-play rate, red-zone TD rate, sacks, plus who gets the ball (target share, carry share) -- 2026 and 2025.
"""
import os, io, csv, gzip, json, statistics as st, collections, urllib.request

OUT = os.path.join("site", "players.json")
NFL_ESPN = {"LA": "LAR", "WAS": "WSH"}
NAMES = {"ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens", "BUF": "Buffalo Bills", "CAR": "Carolina Panthers",
         "CHI": "Chicago Bears", "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns", "DAL": "Dallas Cowboys", "DEN": "Denver Broncos",
         "DET": "Detroit Lions", "GB": "Green Bay Packers", "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars",
         "KC": "Kansas City Chiefs", "LA": "Los Angeles Rams", "LAC": "Los Angeles Chargers", "LV": "Las Vegas Raiders", "MIA": "Miami Dolphins",
         "MIN": "Minnesota Vikings", "NE": "New England Patriots", "NO": "New Orleans Saints", "NYG": "New York Giants", "NYJ": "New York Jets",
         "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers", "SEA": "Seattle Seahawks", "SF": "San Francisco 49ers", "TB": "Tampa Bay Buccaneers",
         "TEN": "Tennessee Titans", "WAS": "Washington Commanders"}


def pbp(y):
    f = "_site_cache/pbp_%d.csv.gz" % y
    if not os.path.exists(f):
        u = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_%d.csv.gz" % y
        open(f, "wb").write(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=180).read())
    return list(csv.DictReader(io.StringIO(gzip.decompress(open(f, "rb").read()).decode("utf-8"))))


def ranks(d, high_is_1=True):
    order = sorted(d, key=lambda t: d[t], reverse=high_is_1)
    return {t: i + 1 for i, t in enumerate(order)}


def nfl_season(y):
    R = [r for r in pbp(y) if r.get("season_type") == "REG"]
    plays = [r for r in R if r.get("play_type") in ("pass", "run") and r.get("epa") not in ("", "NA")]
    T = collections.defaultdict(lambda: dict(off=[], de=[], pas=0, n=0, games=set(), expl=0, sacks_for=0, sacks_against=0,
                                             rz=0, rz_td=0, tgt=collections.Counter(), car=collections.Counter(), tgt_n=0, car_n=0))
    for r in plays:
        o, d = r["posteam"], r["defteam"]
        e = float(r["epa"])
        T[o]["off"].append(e); T[d]["de"].append(e); T[o]["n"] += 1; T[o]["games"].add(r["game_id"]); T[d]["games"].add(r["game_id"])
        if r["play_type"] == "pass":
            T[o]["pas"] += 1
        yg = float(r["yards_gained"] or 0) if r.get("yards_gained") not in ("", "NA") else 0
        if (r["play_type"] == "pass" and yg >= 20) or (r["play_type"] == "run" and yg >= 10):
            T[o]["expl"] += 1
        if r.get("sack") == "1":
            T[d]["sacks_for"] += 1; T[o]["sacks_against"] += 1
        if r.get("receiver_player_name") and r.get("pass_attempt") == "1":
            T[o]["tgt"][r["receiver_player_name"]] += 1; T[o]["tgt_n"] += 1
        if r["play_type"] == "run" and r.get("rusher_player_name") and r.get("qb_scramble") != "1":
            T[o]["car"][r["rusher_player_name"]] += 1; T[o]["car_n"] += 1
    # red zone drives: a drive that reached the 20; TD if the drive ended in a touchdown
    drives = collections.defaultdict(dict)
    for r in R:
        if not r.get("posteam") or r.get("drive") in ("", "NA"):
            continue
        k = (r["game_id"], r["posteam"], r["drive"])
        dv = drives[k]
        try:
            if float(r.get("yardline_100") or 99) <= 20:
                dv["rz"] = True
        except ValueError:
            pass
        if r.get("touchdown") == "1" and r.get("td_team") == r["posteam"]:
            dv["td"] = True
    for (g, t, _), dv in drives.items():
        if dv.get("rz"):
            T[t]["rz"] += 1
            T[t]["rz_td"] += 1 if dv.get("td") else 0
    # final scores -> record, points for / against
    fin = {}
    for r in R:
        if r.get("home_team") and r.get("total_home_score") not in ("", "NA"):
            fin[r["game_id"]] = (r["home_team"], r["away_team"], float(r["total_home_score"]), float(r["total_away_score"]), int(r["week"]))
    rec = collections.defaultdict(lambda: dict(w=0, l=0, t=0, pf=[], pa=[], games=[]))
    for gid, (h, a, hs, as_, wk) in fin.items():
        for me, op, ms, os_ in ((h, a, hs, as_), (a, h, as_, hs)):
            x = rec[me]; x["pf"].append(ms); x["pa"].append(os_)
            x["w" if ms > os_ else "l" if ms < os_ else "t"] += 1
            x["games"].append(dict(wk=wk, opp=op, home=me == h, pf=int(ms), pa=int(os_)))
    out = {}
    for t, x in T.items():
        if len(x["games"]) == 0:
            continue
        g = len(x["games"])
        rc = rec.get(t, {})
        out[t] = dict(games=g, off_epa=round(st.mean(x["off"]), 3) if x["off"] else None, def_epa=round(st.mean(x["de"]), 3) if x["de"] else None,
                      pass_rate=round(x["pas"] / max(1, x["n"]), 3), plays=round(x["n"] / g, 1), expl=round(x["expl"] / max(1, x["n"]), 3),
                      sacks=round(x["sacks_for"] / g, 2), sacked=round(x["sacks_against"] / g, 2),
                      rz=round(x["rz_td"] / x["rz"], 3) if x["rz"] else None,
                      ppg=round(st.mean(rc["pf"]), 1) if rc.get("pf") else None, papg=round(st.mean(rc["pa"]), 1) if rc.get("pa") else None,
                      record="%d-%d%s" % (rc.get("w", 0), rc.get("l", 0), "-%d" % rc["t"] if rc.get("t") else ""),
                      results=sorted(rc.get("games", []), key=lambda z: z["wk"]),
                      targets=[[n, c, round(c / max(1, x["tgt_n"]), 3)] for n, c in x["tgt"].most_common(8)],
                      carries=[[n, c, round(c / max(1, x["car_n"]), 3)] for n, c in x["car"].most_common(5)])
    for k, hi in (("off_epa", True), ("def_epa", False), ("pass_rate", True), ("plays", True), ("expl", True), ("sacks", True),
                  ("sacked", False), ("rz", True), ("ppg", True), ("papg", False)):
        vals = {t: v[k] for t, v in out.items() if v.get(k) is not None}
        rk = ranks(vals, hi)
        for t in out:
            out[t][k + "_rk"] = rk.get(t)
    return out


def injuries(sport, team):
    import _news
    rows = []
    for name, status, comment, pos in _news.team_rows(sport, team):
        s = (status or "").lower()
        if not s or s == "active":
            continue
        rows.append([name, status, pos, (comment or "")[:150]])
    order = {"out": 0, "injured reserve": 1, "doubtful": 2, "questionable": 3}
    rows.sort(key=lambda r: next((v for k, v in order.items() if k in r[1].lower()), 9))
    return rows[:14]


if __name__ == "__main__":
    D = json.load(open(OUT, encoding="utf-8"))
    for sp, d in D.items():
        if not isinstance(d, dict) or "players" not in d:
            continue
        teams = {}
        for P in d["players"].values():
            for t, nm in ((P.get("team"), P.get("team_name")), (P.get("opp"), P.get("opp_name"))):
                if t and t not in teams:
                    teams[t] = dict(id=t, name=nm or t, players=[], next=None)
            if P.get("team") in teams:
                teams[P["team"]]["players"].append(P["id"])
                if P.get("opp") and not teams[P["team"]]["next"]:
                    teams[P["team"]]["next"] = dict(opp=P["opp"], opp_name=P.get("opp_name") or P["opp"], start=P.get("start"), home=P.get("home"))
            if P.get("opp") in teams and not teams[P["opp"]]["next"] and P.get("team"):
                teams[P["opp"]]["next"] = dict(opp=P["team"], opp_name=P.get("team_name") or P["team"], start=P.get("start"),
                                               home=(not P["home"]) if P.get("home") is not None else None)
        if sp == "NFL":
            s26, s25 = nfl_season(2026), nfl_season(2025)
            for t in set(s26) | set(s25):
                teams.setdefault(t, dict(id=t, name=t, players=[], next=None))
            for t, x in teams.items():
                x["name"] = NAMES.get(t, x["name"])
                x["s2026"], x["s2025"] = s26.get(t), s25.get(t)
        if sp in ("NFL", "WNBA", "MLB", "NHL"):
            for t, x in teams.items():
                try:
                    x["inj"] = injuries(sp.lower(), NFL_ESPN.get(t, t) if sp == "NFL" else t)
                except Exception:
                    x["inj"] = []
        d["teams"] = teams
        print("%-7s %d teams" % (sp, len(teams)))
    json.dump(D, open(OUT, "w", encoding="utf-8"), separators=(",", ":"))
    print("wrote %s (%.0f KB)" % (OUT, os.path.getsize(OUT) / 1e3))
