"""NFL matchup context for props: defense vs position, run game, pass rush, pace. Free (nflverse).

    python _nflmatch.py CHI MIN          # both sides of one game
    python _nflmatch.py CHI              # one team's profile
    python _nflmatch.py --board          # every Week 2 game, ranked spots

For each DEFENSE, from weekly player stats:
  rush yds allowed to RBs, rec yds allowed to WR / TE / RB, QB rush yds allowed,
  sacks + QB hits generated (pass rush), and yards per carry allowed.
For each OFFENSE: sacks suffered (o-line pass protection), yards per carry, pass attempts
  per game (pace/volume), and share of yards to RB / WR / TE.
Current season is weighted 3x against last season so Week 1 shows without swamping the sample.
Ranks are 1 = most generous to that position (best spot for a prop OVER).
"""
import sys, csv, io, math, collections, urllib.request

H = {"User-Agent": "Mozilla/5.0"}
CUR, PREV, CUR_W = 2026, 2025, 3.0
POS_GROUP = {"RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE", "QB": "QB"}


def load(year):
    raw = urllib.request.urlopen(urllib.request.Request(
        "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_%d.csv" % year,
        headers=H), timeout=240).read().decode()
    return [r for r in csv.DictReader(io.StringIO(raw)) if r["season_type"] == "REG"]


def f(r, k):
    try:
        return float(r[k] or 0)
    except (KeyError, ValueError):
        return 0.0


def build():
    D = collections.defaultdict(lambda: collections.defaultdict(float))   # defense stats
    O = collections.defaultdict(lambda: collections.defaultdict(float))   # offense stats
    games = collections.defaultdict(lambda: collections.defaultdict(set))
    for year, w in ((PREV, 1.0), (CUR, CUR_W)):
        try:
            rows = load(year)
        except Exception as e:
            print("skip %d: %s" % (year, e))
            continue
        for r in rows:
            t, o, wk = r["team"], r["opponent_team"], (year, r["week"])
            pos = POS_GROUP.get(r["position"], "OTHER")
            games[t]["off"].add(wk)
            games[o]["def"].add(wk)
            games[t]["w"] = games[t].get("w", 0)
            # --- defense (o is the defense facing these players)
            d = D[o]
            d["w"] = w
            d["rush_" + pos] += w * f(r, "rushing_yards")
            d["rec_" + pos] += w * f(r, "receiving_yards")
            d["carries_" + pos] += w * f(r, "carries")
            d["tgt_" + pos] += w * f(r, "targets")
            d["pass_yds"] += w * f(r, "passing_yards")
            d["sacks"] += w * f(r, "def_sacks")
            d["qb_hits"] += w * f(r, "def_qb_hits")
            d["gw"] += 0
            # --- offense
            x = O[t]
            x["rush_" + pos] += w * f(r, "rushing_yards")
            x["rec_" + pos] += w * f(r, "receiving_yards")
            x["carries"] += w * f(r, "carries")
            x["att"] += w * f(r, "attempts")
            x["sacked"] += w * f(r, "sacks_suffered")
            x["pass_yds"] += w * f(r, "passing_yards")
    # weighted games played: one entry per (season, week) the team appeared, weighted like the stats
    gw = {}
    for t in games:
        weeks = games[t]["off"] | games[t]["def"]
        gw[t] = sum(CUR_W if yr == CUR else 1.0 for yr, wk in weeks) or 1
    return D, O, gw


def per_game(D, O, gw):
    prof = {}
    for t in set(D) | set(O):
        n = gw.get(t, 1)
        d, o = D[t], O[t]
        prof[t] = dict(
            d_rush_rb=d["rush_RB"] / n, d_rec_wr=d["rec_WR"] / n, d_rec_te=d["rec_TE"] / n,
            d_rec_rb=d["rec_RB"] / n, d_rush_qb=d["rush_QB"] / n, d_pass=d["pass_yds"] / n,
            d_ypc=d["rush_RB"] / max(1, d["carries_RB"]), d_sacks=d["sacks"] / n, d_hits=d["qb_hits"] / n,
            o_ypc=o["rush_RB"] / max(1, o["carries"]), o_att=o["att"] / n, o_sacked=o["sacked"] / n,
            o_rush=o["rush_RB"] / n, o_pass=o["pass_yds"] / n,
            o_wr_share=o["rec_WR"] / max(1, o["rec_WR"] + o["rec_TE"] + o["rec_RB"]),
            o_te_share=o["rec_TE"] / max(1, o["rec_WR"] + o["rec_TE"] + o["rec_RB"]),
            o_rb_share=o["rec_RB"] / max(1, o["rec_WR"] + o["rec_TE"] + o["rec_RB"]))
    return prof


def ranks(prof, key, high_is_generous=True):
    order = sorted(prof, key=lambda t: -prof[t][key] if high_is_generous else prof[t][key])
    return {t: i + 1 for i, t in enumerate(order)}


def show_team(prof, R, t, role="both"):
    p = prof[t]
    print("\n%s" % t)
    print("  DEFENSE allows per game")
    for lab, k in (("rush yds to RBs", "d_rush_rb"), ("rec yds to WRs", "d_rec_wr"),
                   ("rec yds to TEs", "d_rec_te"), ("rec yds to RBs", "d_rec_rb"),
                   ("rush yds to QBs", "d_rush_qb"), ("pass yds", "d_pass")):
        print("    %-18s %6.1f   rank %2d of 32 %s" % (lab, p[k], R[k][t],
              "(most generous)" if R[k][t] <= 5 else "(toughest)" if R[k][t] >= 28 else ""))
    print("    %-18s %6.2f   rank %2d" % ("yds per carry", p["d_ypc"], R["d_ypc"][t]))
    print("    %-18s %6.2f   rank %2d (pass rush: 1 = most sacks)" % ("sacks", p["d_sacks"], R["d_sacks"][t]))
    print("  OFFENSE per game")
    print("    %-18s %6.1f   pass attempts %.1f, sacks allowed %.2f (o-line)" % (
        "rush yds (RB)", p["o_rush"], p["o_att"], p["o_sacked"]))
    print("    %-18s %6.2f" % ("yds per carry", p["o_ypc"]))
    print("    target yards split   WR %.0f%%  TE %.0f%%  RB %.0f%%" % (
        100 * p["o_wr_share"], 100 * p["o_te_share"], 100 * p["o_rb_share"]))


def main():
    args = [a for a in sys.argv[1:]]
    D, O, gw = build()
    prof = per_game(D, O, gw)
    keys = ["d_rush_rb", "d_rec_wr", "d_rec_te", "d_rec_rb", "d_rush_qb", "d_pass", "d_ypc", "d_sacks"]
    R = {k: ranks(prof, k, high_is_generous=(k != "d_sacks")) for k in keys}
    if not args:
        print(__doc__)
        return
    if args[0] == "--board":
        for t in sorted(prof, key=lambda t: -prof[t]["d_rush_rb"])[:32]:
            p = prof[t]
            print("%-4s rushRB %5.1f (%2d)  recWR %5.1f (%2d)  recTE %4.1f (%2d)  recRB %4.1f (%2d)  sacks %.2f (%2d)" % (
                t, p["d_rush_rb"], R["d_rush_rb"][t], p["d_rec_wr"], R["d_rec_wr"][t],
                p["d_rec_te"], R["d_rec_te"][t], p["d_rec_rb"], R["d_rec_rb"][t], p["d_sacks"], R["d_sacks"][t]))
        return
    for t in args:
        if t.upper() in prof:
            show_team(prof, R, t.upper())
        else:
            print("unknown team", t)


if __name__ == "__main__":
    main()
