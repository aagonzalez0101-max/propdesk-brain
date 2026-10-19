"""COVERAGE MATCHUPS (10/19, user: "zone and man coverage ... they play a lot of this type of defense and against this the guy targeted is this").

Free nflverse charting tags every pass play with man/zone and the shell (Cover 1/3 = single-high / middle of field closed,
Cover 2/4/6 = two-high). 2026 charting is only released after the season, so profiles come from the latest released season.

    python _coverage.py test            # does the coverage-adjusted target share beat the plain share? (2025, point in time)
    python _coverage.py team SF         # a defense's coverage mix
    python _coverage.py player "Terry McLaurin"   # his target share by coverage bucket

Bucket = MAN/ZONE x SINGLE/TWO-high. Adjusted share = sum over buckets of (opponent's mix) x (his share vs that bucket, shrunk
toward his overall share with K plays of prior weight).
"""
import sys, collections
import pandas as pd

SEASON = 2025
SINGLE = {"COVER_0", "COVER_1", "COVER_3"}
TWO = {"COVER_2", "COVER_4", "COVER_6", "2_MAN", "COVER_9"}
K = 40                                                    # shrinkage weight, in team pass plays


def load():
    part = pd.read_parquet("data/nflverse/part_%d.parquet" % SEASON,
                           columns=["nflverse_game_id", "play_id", "defense_man_zone_type", "defense_coverage_type"])
    pbp = pd.read_parquet("data/nflverse/pbp_%d.parquet" % SEASON,
                          columns=["game_id", "play_id", "posteam", "defteam", "week", "season_type", "pass_attempt", "sack",
                                   "receiver_player_name", "receiver_player_id", "yards_gained", "complete_pass"])
    pbp = pbp[(pbp.pass_attempt == 1) & (pbp.sack != 1) & (pbp.season_type == "REG")]
    d = pbp.merge(part, left_on=["game_id", "play_id"], right_on=["nflverse_game_id", "play_id"], how="inner")
    mz = d.defense_man_zone_type.map({"MAN_COVERAGE": "MAN", "ZONE_COVERAGE": "ZONE"})
    sh = d.defense_coverage_type.map(lambda c: "SINGLE" if c in SINGLE else ("TWO" if c in TWO else None))
    d["bucket"] = mz + "-" + sh
    return d[d.bucket.notna()]


def test():
    d = load()
    weeks = sorted(d.week.unique())
    rows = []
    for w in weeks:
        if w < 5:
            continue
        prior, cur = d[d.week < w], d[d.week == w]
        dmix = prior.groupby("defteam").bucket.value_counts(normalize=True)
        team_plays = prior.groupby(["posteam", "bucket"]).size()
        team_all = prior.groupby("posteam").size()
        pl = prior[prior.receiver_player_id.notna()]
        pb = pl.groupby(["receiver_player_id", "posteam", "bucket"]).size()
        pa = pl.groupby(["receiver_player_id", "posteam"]).size()
        for (gid, team, opp), g in cur.groupby(["game_id", "posteam", "defteam"]):
            n_att = len(g)
            act = g.receiver_player_id.value_counts()
            for (pid, t), tot in pa.items():
                if t != team or tot < 8:
                    continue
                base = tot / team_all[team]
                adj = 0.0
                for b, share in dmix.get(opp, pd.Series(dtype=float)).items():
                    plays_b = team_plays.get((team, b), 0)
                    tg_b = pb.get((pid, team, b), 0)
                    adj += share * (tg_b + K * base) / (plays_b + K)
                if adj == 0:
                    continue
                rows.append(dict(week=w, pid=pid, base=base * n_att, adj=adj * n_att, act=act.get(pid, 0)))
    r = pd.DataFrame(rows)
    mae = lambda c: (r[c] - r.act).abs().mean()
    print("receiver-games %d (weeks 5+, 2025, point in time)" % len(r))
    print("  MAE targets: plain share %.3f | coverage-adjusted %.3f" % (mae("base"), mae("adj")))
    r["gap"] = (r.adj - r.base) / r.base
    for lo in (0.10, 0.20, 0.30):
        up, dn = r[r.gap >= lo], r[r.gap <= -lo]
        print("  adjusted %+d%%+ vs plain: beat plain %4.1f%% (n=%d) | adjusted -%d%%: fell short %4.1f%% (n=%d)"
              % (100 * lo, 100 * (up.act > up.base).mean() if len(up) else 0, len(up), 100 * lo,
                 100 * (dn.act < dn.base).mean() if len(dn) else 0, len(dn)))


def team(abbr):
    d = load()
    t = d[d.defteam == abbr]
    print("%s defense %d: %d charted pass plays" % (abbr, SEASON, len(t)))
    print(t.bucket.value_counts(normalize=True).round(3).to_string())


def player(name):
    d = load()
    last = name.split()[-1]
    g = d[d.receiver_player_name.fillna("").str.endswith(last) & d.receiver_player_name.fillna("").str.startswith(name[0])]
    if g.empty:
        print("no %d targets for %s" % (SEASON, name)); return
    tm = g.posteam.mode()[0]
    tp = d[d.posteam == tm].bucket.value_counts()
    tg = g.bucket.value_counts()
    print("%s (%s %d): target share by coverage" % (name, tm, SEASON))
    for b in tp.index:
        print("  %-12s %5.1f%%  (%d of %d)" % (b, 100 * tg.get(b, 0) / tp[b], tg.get(b, 0), tp[b]))


if __name__ == "__main__":
    a = sys.argv[1:]
    {"test": lambda: test(), "team": lambda: team(a[1]), "player": lambda: player(a[1])}[a[0]]()
