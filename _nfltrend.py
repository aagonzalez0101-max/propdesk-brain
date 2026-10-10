"""Defense vs position across THREE windows -- season, last 10, last 5 -- and a test of which one wins.

    python _nfltrend.py LAR NYG        # both defenses, all three windows, with the trend
    python _nfltrend.py --test         # which window actually predicted prop results
    python _nfltrend.py --board        # every upcoming game's soft spots

The tool everyone sells shows season / L10 / L5 ranks side by side and lets you assume the
short window is the truth. We measured the same idea in baseball and it was FALSE there --
season ratings beat recent form, and reweighting on streaks made it worse
([[feedback_form_vs_structure]]). Football might differ: rosters actually change mid-season.

So `--test` answers it with our own data instead of trusting the pretty column: for every
player-game, rank the opposing defense in each window BEFORE that game, then see which
window's rank best predicts whether the player went over his own season average.
"""
import sys, csv, io, collections, urllib.request

H = {"User-Agent": "Mozilla/5.0"}
YEARS = (2025, 2026)
POS = {"RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE", "QB": "QB"}
# nflverse spells a few teams differently to every betting app
ALIAS = {"LAR": "LA", "RAMS": "LA", "WSH": "WAS", "JAC": "JAX", "OAK": "LV", "SD": "LAC", "STL": "LA"}
WINDOWS = (("season", None), ("L10", 10), ("L5", 5))
# what each defense allows, by position, per game
CATS = [("rush yds to RBs", "RB", "rushing_yards"),
        ("rec yds to RBs", "RB", "receiving_yards"),
        ("rec yds to WRs", "WR", "receiving_yards"),
        ("rec yds to TEs", "TE", "receiving_yards"),
        ("pass yds", None, "passing_yards")]


def load():
    rows = []
    for y in YEARS:
        raw = urllib.request.urlopen(urllib.request.Request(
            "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_%d.csv" % y,
            headers=H), timeout=240).read().decode("utf-8", "replace")
        for r in csv.DictReader(io.StringIO(raw)):
            if r.get("season_type") != "REG":
                continue
            r["_key"] = (int(r["season"]), int(r["week"]))
            rows.append(r)
    rows.sort(key=lambda r: r["_key"])
    return rows


def f(r, k):
    try:
        return float(r[k] or 0)
    except (KeyError, ValueError, TypeError):
        return 0.0


def game_totals(rows):
    """(season, week, defense) -> {category: yards allowed that game}"""
    tot = collections.defaultdict(lambda: collections.defaultdict(float))
    for r in rows:
        d = r.get("opponent_team")
        if not d:
            continue
        pos = POS.get(r.get("position_group") or r.get("position") or "")
        key = (int(r["season"]), int(r["week"]), d)
        for label, want_pos, stat in CATS:
            if want_pos and pos != want_pos:
                continue
            tot[key][label] += f(r, stat)
    return tot


def window_avgs(tot, upto, n):
    """Average allowed per game for every defense, over the n games before `upto`."""
    by_def = collections.defaultdict(list)
    for (s, w, d), cats in tot.items():
        if (s, w) < upto:
            by_def[d].append(((s, w), cats))
    out = {}
    for d, games in by_def.items():
        games.sort()
        use = games[-n:] if n else games
        if not use:
            continue
        agg = collections.defaultdict(float)
        for _, cats in use:
            for label, v in cats.items():
                agg[label] += v
        out[d] = {k: v / len(use) for k, v in agg.items()}
    return out


def ranks(avgs, label):
    have = [(d, v.get(label, 0.0)) for d, v in avgs.items() if label in v]
    have.sort(key=lambda x: -x[1])              # 1 = most generous
    return {d: i + 1 for i, (d, _) in enumerate(have)}


def show(teams):
    rows = load()
    tot = game_totals(rows)
    upto = (10 ** 9, 10 ** 9)
    W = {name: window_avgs(tot, upto, n) for name, n in WINDOWS}
    R = {name: {label: ranks(W[name], label) for label, _, _ in CATS} for name, _ in WINDOWS}
    for t0 in teams:
        t = ALIAS.get(t0.upper(), t0.upper())
        print("\n%s DEFENSE allows per game    (rank 1 = most generous)" % t)
        print("  %-16s %14s %14s %14s   trend" % ("", "SEASON", "LAST 10", "LAST 5"))
        for label, _, _ in CATS:
            cells = []
            rk = {}
            for name, _ in WINDOWS:
                v = W[name].get(t, {}).get(label)
                r = R[name][label].get(t)
                rk[name] = r
                cells.append("%6.1f (%2s)" % (v, r) if v is not None else "     -    ")
            if rk.get("season") and rk.get("L5"):
                d = rk["season"] - rk["L5"]
                trend = "getting WEAKER" if d > 4 else "getting tougher" if d < -4 else "steady"
            else:
                trend = ""
            print("  %-16s %14s %14s %14s   %s" % (label, cells[0], cells[1], cells[2], trend))


def test():
    """Which window predicts best? Did the player beat his own season average?"""
    rows = load()
    tot = game_totals(rows)
    weeks = sorted({r["_key"] for r in rows})
    hist = collections.defaultdict(list)          # player -> prior values
    score = {name: [0, 0] for name, _ in WINDOWS}   # right, wrong
    per_cat = collections.defaultdict(lambda: {n: [0, 0] for n, _ in WINDOWS})
    cache = {}
    for wk in weeks:
        if wk not in cache:
            cache[wk] = {name: {label: ranks(window_avgs(tot, wk, n), label) for label, _, _ in CATS}
                         for name, n in WINDOWS}
        R = cache[wk]
        for r in rows:
            if r["_key"] != wk:
                continue
            pos = POS.get(r.get("position_group") or r.get("position") or "")
            d = r.get("opponent_team")
            pid = r.get("player_id")
            if not (pos and d and pid):
                continue
            for label, want_pos, stat in CATS:
                if want_pos and pos != want_pos:
                    continue
                if not want_pos and pos != "QB":
                    continue
                prior = hist[(pid, label)]
                v = f(r, stat)
                if len(prior) >= 5:
                    avg = sum(prior) / len(prior)
                    over = v > avg
                    n_teams = max(len(R["season"][label]), 1)
                    for name, _ in WINDOWS:
                        rk = R[name][label].get(d)
                        if not rk:
                            continue
                        soft = rk <= n_teams / 2          # generous half = predict OVER
                        ok = (soft == over)
                        score[name][0 if ok else 1] += 1
                        per_cat[label][name][0 if ok else 1] += 1
                prior.append(v)
    print("Does a generous defense actually mean the player beats his own average?\n")
    print("  %-10s %8s %8s" % ("window", "right", "rate"))
    for name, _ in WINDOWS:
        r, w = score[name]
        print("  %-10s %8d %7.1f%%" % (name, r, 100 * r / max(1, r + w)))
    print("\nby category:")
    print("  %-18s %10s %10s %10s" % ("", "season", "L10", "L5"))
    for label, _, _ in CATS:
        cells = []
        for name, _ in WINDOWS:
            r, w = per_cat[label][name]
            cells.append("%.1f%% (%d)" % (100 * r / max(1, r + w), r + w))
        print("  %-18s %10s %10s %10s" % (label, *cells))


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    if "--test" in sys.argv:
        test()
    elif a:
        show(a)
    else:
        print(__doc__)
