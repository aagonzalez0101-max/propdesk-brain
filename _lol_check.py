"""LoL LEG CHECK -- every precaution we run on normal sports, for one esports leg (2026-10-04, user: "add all that to esports").

    python _lol_check.py "Quad" FLY NAVI 6.5 under [mid]

  1. OWN FORM   last 8 series, kills on maps 1+2, hit rate vs THIS line          (lolesports feed via _lol_games_cache.json)
  2. ROLE       top/mid ok; jungle out (47% on unders); support thin
  3. OPP vs ROLE kills the opponent allows to that role vs league avg           (_lol_matchup.py)
  4. HEAD-TO-HEAD this player's maps 1+2 kills in past series vs THIS opponent
  5. BLOWOUT    match win prob from Pinnacle esports (LoL leagues): the favourite's players run up kills in a stomp, the dog's dry up
  6. ROSTER     was the player in his team's most recent game? (absent = stand-in / benched -> leg out)
Verdict: a leg needs 1 + 3 + 4 not against it and no roster flag. Two disagreeing = not a leg (the bet-selection bar).
"""
import sys, json, re, collections, statistics as st
import requests
import _lol_grade as L
import _lol_matchup as MU
import _kbo as K                      # Pinnacle guest headers

norm = L.norm


def series_log(player, cache_only=True):
    """per-series maps 1+2 kills with opponent tag, newest first, from the cached graded games."""
    c = json.load(open(L.CACHE))
    games = []
    for gid, g in c.items():
        me = next(((nm, v) for nm, v in g.items() if norm(nm.split(" ", 1)[-1]) == norm(player)), None)
        if me:
            tag = me[0].split(" ", 1)[0]
            opp = next((nm.split(" ", 1)[0] for nm in g if nm.split(" ", 1)[0] != tag), "?")
            games.append((int(gid), tag, opp, me[1]["kills"], me[1]["role"]))
    games.sort(reverse=True)
    # pair consecutive games vs the same opponent into a series (game ids of one series are consecutive)
    out, i = [], 0
    while i < len(games):
        gid, tag, opp, k, role = games[i]
        if i + 1 < len(games) and games[i + 1][2] == opp and abs(games[i + 1][0] - gid) <= 5:
            out.append((opp, k + games[i + 1][3], role, tag)); i += 2
        else:
            out.append((opp, None, role, tag)); i += 1       # single game (Bo1 or game 2 missing) -> not a maps 1+2 sample
    return out


def win_prob(team, opp):
    best = None
    for lg in requests.get(K.PIN + "/0.1/sports/12/leagues?all=false", headers=K.PH, timeout=25).json():
        if "league of legends" not in lg.get("name", "").lower():
            continue
        mu = requests.get(K.PIN + "/0.1/leagues/%d/matchups?brandId=0" % lg["id"], headers=K.PH, timeout=25).json()
        mk = requests.get(K.PIN + "/0.1/leagues/%d/markets/straight" % lg["id"], headers=K.PH, timeout=25).json()
        if not isinstance(mu, list):
            continue
        for m in mu:
            if m.get("parent") or len(m.get("participants") or []) != 2:
                continue
            names = {p.get("alignment"): p["name"] for p in m["participants"]}
            if not any(norm(team) in norm(n) or norm(n) in norm(team) for n in names.values()):
                continue
            if not any(norm(opp) in norm(n) or norm(n) in norm(opp) for n in names.values()):
                continue
            pr = next((r for r in mk if r.get("matchupId") == m["id"] and r.get("type") == "moneyline" and r.get("period") == 0), None)
            if not pr:
                continue
            d = {p["designation"]: p["price"] for p in pr["prices"]}
            imp = lambda o: (-o) / ((-o) + 100) if o < 0 else 100 / (o + 100)
            ih, ia = imp(d["home"]), imp(d["away"])
            mine = "home" if any(norm(team) in norm(names.get("home", "")) or norm(names.get("home", "")) in norm(team) for _ in [0]) else "away"
            p = (ih if mine == "home" else ia) / (ih + ia)
            best = (p, names, d)
    return best


def check(player, team, opp, line, side, role=None):
    flags, support = [], 0
    log = series_log(player)
    ser = [x for x in log if x[1] is not None][:8]
    role = role or (log[0][2] if log else None)
    print("%s (%s) %s %.1f vs %s   role: %s" % (player, team, side.upper(), line, opp, role))
    # 1 own form
    if ser:
        vals = [x[1] for x in ser]
        hit = sum((v < line) if side == "under" else (v > line) for v in vals)
        push = sum(v == line for v in vals)
        print("  1. OWN FORM   last %d series: %s  -> %s %d, push %d (avg %.1f)" % (len(vals), vals, side, hit, push, st.mean(vals)))
        dec = max(1, len(vals) - push)
        if hit / dec < 0.5:
            flags.append("own form against")
        elif hit / dec >= 0.6 and len(vals) >= 4:
            support += 1                                   # 10/5: support only at 60%+ on 4+ series (2-of-5 was passing as a LEG)
        else:
            flags.append("own form only %d/%d" % (hit, dec))
    else:
        print("  1. OWN FORM   no maps 1+2 series in our data (LPL or new)"); flags.append("no own data")
    # 2 role
    if role == "jungle":
        flags.append("jungle (47% on unders)")
    print("  2. ROLE       %s" % role)
    # 3 opponent vs role
    r, txt = MU.check(opp, role) if role else (None, "no role")
    print("  3. OPP vs ROLE %s" % txt)
    if "[small sample]" in txt:
        r = None                                          # < 6 games: report it, never let it decide a leg
    if r is not None:
        if (side == "under" and r > 1.1) or (side == "over" and r < 0.9):
            flags.append("opponent soft/tough against")
        elif (side == "under" and r < 0.9) or (side == "over" and r > 1.1):
            support += 1
    # 4 head-to-head
    h2h = [x[1] for x in ser if norm(x[0]) == norm(opp)]
    if h2h:
        hh = sum((v < line) if side == "under" else (v > line) for v in h2h)
        print("  4. H2H vs %s  %s -> %s %d/%d" % (opp, h2h, side, hh, len(h2h)))
        if hh < len(h2h) / 2:
            flags.append("H2H against")
        else:
            support += 1
    else:
        print("  4. H2H vs %s  no past series in our data" % opp)
    # 5 blowout risk
    try:
        wp = win_prob(team, opp)
    except Exception as e:
        wp = None; print("  5. BLOWOUT    pinnacle failed: %s" % e)
    if wp:
        p = wp[0]
        print("  5. BLOWOUT    %s win prob %.0f%% (Pinnacle %s)" % (team, 100 * p, wp[2]))
        if side == "under" and p >= 0.70:
            flags.append("heavy favourite -> stomp runs kills up")
        if side == "under" and p <= 0.30:
            support += 1
        if side == "over" and p <= 0.30:
            flags.append("heavy underdog -> kills dry up")
    elif wp is None:
        print("  5. BLOWOUT    no Pinnacle price for this match")
    # 6 roster
    if log and norm(log[0][3]) != norm(team):
        flags.append("ROSTER: last game was for %s, not %s" % (log[0][3], team))
    print("  6. ROSTER     last game tag %s" % (log[0][3] if log else "-"))
    verdict = "LEG" if not flags and support >= 1 else ("CUT" if len(flags) >= 2 or any(f.startswith("ROSTER") for f in flags) else "LEAN")
    print("  => %s   flags: %s   supports: %d" % (verdict, "; ".join(flags) or "none", support))
    return verdict, flags


if __name__ == "__main__":
    a = sys.argv[1:]
    check(a[0], a[1], a[2], float(a[3]), a[4].lower(), a[5].lower() if len(a) > 5 else None)
