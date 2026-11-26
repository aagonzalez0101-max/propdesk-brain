"""NFL 1Q / 1H FANTASY SCORE grader (11/21, user: friend's copied 6-pick of 1Q/1H fantasy overs).
PP scoring: pass yd .04, pass TD 4, INT -1, rush/rec yd .1, rush/rec TD 6, reception 1, fumble lost -1, 2pt 2.
Rebuilt from nflverse play-by-play (free). PP leagues: 35 = NFL 1H, 245 = NFL 1Q.
    python _nfl_period_fs.py grade                 # every archived 1Q/1H standard fantasy line vs actual -> over/under hit rates
    python _nfl_period_fs.py player "Saquon Barkley" 1H 5.5 PIT
"""
import sys, json, sqlite3, datetime, collections, re, unicodedata
import pandas as pd

CT = __import__("zoneinfo").ZoneInfo("America/Chicago")
nn = lambda s: re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())
PBP = {2025: "data/nflverse/pbp_2025.parquet", 2026: "data/nflverse/fresh/pbp_2026.parquet"}
COLS = ["game_id", "season", "week", "game_date", "season_type", "qtr", "posteam", "defteam", "home_team", "away_team",
        "passer_player_id", "passing_yards", "pass_touchdown", "interception", "receiver_player_id", "receiving_yards", "complete_pass",
        "rusher_player_id", "rushing_yards", "rush_touchdown", "fumble_lost", "fumbled_1_player_id", "two_point_conv_result",
        "td_player_id"]


def names():
    m = {}
    for y in (2024, 2025, 2026):
        try:
            w = pd.read_csv("nfl_%d_weekly.csv" % y, usecols=["player_id", "player_display_name", "position"])
            for r in w.itertuples():
                m[r.player_id] = (r.player_display_name, r.position)
        except Exception:
            pass
    return m


def period_scores():
    """-> {(player_id, game_id): {'1Q': pts, '1H': pts}}, game info"""
    S = collections.defaultdict(lambda: {"1Q": 0.0, "1H": 0.0, "team": None})
    G = {}
    for y, f in PBP.items():
        d = pd.read_parquet(f, columns=COLS)
        # 11/26 BUG FIX: a player with 0 first-half points never got an entry, so his zero games vanished -> 1H overs inflated (the
        # "1H WR over 62.6%" rule) and 1Q unders deflated. Register everyone who passed, was targeted or ran in ANY quarter, at 0.
        for r in d.itertuples(index=False):
            for pid in (r.passer_player_id, r.receiver_player_id, r.rusher_player_id):
                if isinstance(pid, str):
                    k = (pid, r.game_id)
                    S[k].update(team=r.posteam, opp=r.defteam, date=r.game_date, week=r.week, season=int(r.game_id[:4]))
        d = d[d.qtr <= 2]
        for r in d.itertuples(index=False):
            G[r.game_id] = (r.game_date, r.home_team, r.away_team, r.season_type, r.week)
            per = ["1H"] + (["1Q"] if r.qtr == 1 else [])
            pts = collections.defaultdict(float)
            if isinstance(r.passer_player_id, str):
                pts[r.passer_player_id] += (r.passing_yards or 0) * .04 if r.passing_yards == r.passing_yards else 0
                pts[r.passer_player_id] += 4 * (r.pass_touchdown == 1) - (r.interception == 1)
            if isinstance(r.receiver_player_id, str) and r.complete_pass == 1:
                ry = r.receiving_yards if r.receiving_yards == r.receiving_yards else 0
                pts[r.receiver_player_id] += 1 + .1 * ry + 6 * (r.pass_touchdown == 1)
            if isinstance(r.rusher_player_id, str):
                ry = r.rushing_yards if r.rushing_yards == r.rushing_yards else 0
                pts[r.rusher_player_id] += .1 * ry + 6 * (r.rush_touchdown == 1)
            if r.fumble_lost == 1 and isinstance(r.fumbled_1_player_id, str):
                pts[r.fumbled_1_player_id] -= 1
            if r.two_point_conv_result == "success":
                for pid in (r.passer_player_id, r.receiver_player_id, r.rusher_player_id):
                    if isinstance(pid, str):
                        pts[pid] += 2
            for pid, v in pts.items():
                k = (pid, r.game_id)
                for p in per:
                    S[k][p] += v
                S[k]["team"] = r.posteam
                S[k]["opp"] = r.defteam
                S[k]["date"] = r.game_date
                S[k]["week"] = r.week
                S[k]["season"] = int(r.game_id[:4])
    return S, G


def by_player(S, N):
    P = collections.defaultdict(list)
    for (pid, gid), v in S.items():
        nm = N.get(pid, (pid, "?"))[0]
        P[nn(nm)].append(dict(gid=gid, pid=pid, pos=N.get(pid, ("", "?"))[1], **v))
    for k in P:
        P[k].sort(key=lambda x: x["date"])
    return P


def grade(S, N):
    P = by_player(S, N)
    L = sqlite3.connect("lines.db")
    out = []
    for lg, per in ((35, "1H"), (245, "1Q")):
        last = {}
        for pl, ln, st, ls in L.execute("select player, line, start, last_seen from pp where league=? and stat='Fantasy Score' and kind='standard'", (lg,)):
            day = datetime.datetime.fromisoformat(st).astimezone(CT).date().isoformat()
            k = (pl, day)
            if k not in last or ls > last[k][1]:
                last[k] = (ln, ls)
        for (pl, day), (ln, _) in last.items():
            g = [x for x in P.get(nn(pl), []) if x["date"] == day]
            if not g:
                continue
            a = g[0][per]
            out.append(dict(per=per, player=pl, day=day, line=ln, actual=round(a, 2), pos=g[0]["pos"], over=a > ln))
    return out


def report(rows):
    print("NFL period fantasy, archived PP closing standard lines vs actual (nflverse pbp)")
    for per in ("1Q", "1H"):
        X = [r for r in rows if r["per"] == per]
        if not X:
            continue
        o = sum(r["over"] for r in X)
        print("  %s  n=%d  OVER %d (%.1f%%)  UNDER %d (%.1f%%)" % (per, len(X), o, 100 * o / len(X), len(X) - o, 100 * (len(X) - o) / len(X)))
        for pos in ("QB", "RB", "WR", "TE"):
            Y = [r for r in X if r["pos"] == pos]
            if len(Y) >= 10:
                oo = sum(r["over"] for r in Y)
                print("     %-3s n=%3d over %.1f%%" % (pos, len(Y), 100 * oo / len(Y)))


if __name__ == "__main__":
    N = names()
    S, G = period_scores()
    if sys.argv[1] == "grade":
        rows = grade(S, N)
        json.dump(rows, open("nfl_period_fs_graded.json", "w"), indent=0)
        report(rows)


def player_card(S, N, name, per, line, opp):
    P = by_player(S, N)
    g = P.get(nn(name), [])
    pos = g[-1]["pos"] if g else "?"
    s26 = [x for x in g if x["season"] == 2026]
    s25 = [x for x in g if x["season"] == 2025]
    hit = lambda X: (sum(x[per] > line for x in X), len(X))
    # defense: what opp allowed to this position in this period, 2026, vs league avg
    allowed = collections.defaultdict(lambda: collections.defaultdict(float))
    for (pid, gid), v in S.items():
        if v.get("season") != 2026 or N.get(pid, ("", ""))[1] != pos:
            continue
        allowed[v["opp"]][gid] += v[per]
    avg = lambda d: sum(d.values()) / max(len(d), 1)
    lg = sum(avg(d) for d in allowed.values()) / max(len(allowed), 1)
    rank = sorted(allowed, key=lambda t: -avg(allowed[t]))
    h2h = [x for x in g if x["opp"] == opp]
    return dict(name=name, pos=pos, per=per, line=line, opp=opp, team=g[-1]["team"] if g else None,
                last_date=g[-1]["date"] if g else None,
                g26=[(x["week"], x["opp"], round(x[per], 1)) for x in s26],
                hit26=hit(s26), hit25=hit(s25), l5=hit(s26[-5:]),
                avg26=round(sum(x[per] for x in s26) / max(len(s26), 1), 2),
                med26=round(sorted(x[per] for x in s26)[len(s26) // 2], 2) if s26 else None,
                opp_allowed=round(avg(allowed[opp]), 2), lg_allowed=round(lg, 2),
                opp_rank=(rank.index(opp) + 1) if opp in rank else None,
                h2h=[(x["season"], x["week"], round(x[per], 1)) for x in h2h])


if __name__ == "__main__" and sys.argv[1] == "legs":
    legs = json.loads(sys.argv[2])
    out = [player_card(S, N, *l) for l in legs]
    json.dump(out, open("nfl_period_legs.json", "w"), indent=1)
    for c in out:
        print(json.dumps(c))
