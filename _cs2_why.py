"""Why each CS2 pick exists -- the full working, per pick, plus a slip audit.

    python _cs2_why.py              # explain every pick from the latest card
    python _cs2_why.py <player>     # one pick in detail

For each pick it shows the chain that produced the number, so a pick can be argued with:

  his own rate (raw, and after shrinking)      -> how much of this is HIM vs the league
  history size                                 -> how much to trust that rate
  series-state probabilities                   -> P(0-2), P(1-1), P(2-0) from the map win prob
  expected rounds in each state                -> a 2-0 is short, a 1-1 is long
  the resulting mean, and the posted line       -> the gap being bet
  head-to-head sample                          -> present on only ~15% of series
  which guards it passed                       -> role-change, coin-flip map, edge band

The slip audit checks the things that have actually cost us money: two legs in the same match,
two legs on the same team, and whether the joint probability really clears the payout.
"""
import json, sys, collections, itertools
import _cs2_series as SER

PAY = {2: 3.5, 3: 6.5, 4: 12.0}


def latest_picks():
    rows = [json.loads(l) for l in open("cs2_paper.jsonl", encoding="utf-8")]
    if not rows:
        return []
    last = max(r["ts"] for r in rows)
    return [r for r in rows if r["ts"] == last]


def build():
    rows = SER.load()
    sr = SER.series_rows(rows)
    S = SER.State(sr)
    raw = collections.defaultdict(lambda: [0, 0])
    for r in sr:
        e = raw[r["player"]]; e[0] += r["kills"]; e[1] += r["rounds"]
    return S, raw


def explain(p, S, raw):
    pid = p["pid"]
    kind = p["kind"]
    winp = p["map_winp"]
    side = "UNDER" if p["side"] == "lower" else "OVER"
    stat = "headshots" if kind == "hs" else "kills"
    rk, rr = raw.get(pid, [0, 0])
    own = rk / rr if rr else 0
    shrunk = S.kpr.get(pid, S.lg_k)
    anchor = S.tier_k.get(S.player_tier.get(pid), S.lg_k)
    states = {2: winp * winp, 1: 2 * winp * (1 - winp), 0: (1 - winp) ** 2}
    h2h_rate, h2h_n = S.h2h_rate(pid, p.get("opp_clan") or p.get("opp"))
    print("\n" + "=" * 74)
    print("%s  %s %s %s   (%s, %s)" % (p["player"], side, p["line"], stat, p["match"], p["start_ct"]))
    print("  model says %.0f%%   line implies %.0f%%   edge %+.1f points" %
          (100 * p["model_p"], 100 * p["breakeven"], 100 * p["edge"]))
    print("\n  WHERE THE NUMBER COMES FROM")
    print("    his own kill rate      %.3f per round over %d rounds (%d maps of history)" %
          (own, rr, p["n_maps_hist"]))
    print("    after shrinking        %.3f   (pulled toward %.3f, his tier's rate)" % (shrunk, anchor))
    if rr < 800:
        print("      ^ thin history, so the shrink is doing a lot of the work here")
    if kind == "hs":
        print("    headshots per kill     %.0f%%  (league %.0f%%)" %
              (100 * S.hspk.get(pid, S.lg_hs), 100 * S.lg_hs))
    print("    team is %.0f%% to win a map, so the series lands:" % (100 * winp))
    for st, nm in ((2, "2-0"), (1, "1-1"), (0, "0-2")):
        rds = S.rounds.get(st) or []
        avg = sum(rds) / len(rds) if rds else 0
        print("      %s  %4.0f%% of the time   %.1f rounds   kill rate x%.2f" %
              (nm, 100 * states[st], avg, S.state_mult.get(st, 1)))
    print("    -> expected %s: %.1f     posted line: %.1f     gap %+.0f%%" %
          (stat, p["model_mu"], p["line"], 100 * (p["model_mu"] / p["line"] - 1)))
    print("\n  CHECKS")
    print("    head-to-head vs %-18s %s" % (
        (p.get("opp") or "?")[:18],
        "%d rounds of history, rate %.3f" % (h2h_n, h2h_rate) if h2h_n else "no usable history (normal -- only 15% of series have any)"))
    print("    role-change guard      %s" % ("FLAGGED: " + p["suspect"] if p.get("suspect") else "passed (model within 25% of the line)"))
    print("    coin-flip map guard    %s" % ("FAILED -- map is %.0f/%.0f" % (100 * winp, 100 * (1 - winp))
                                             if 0.45 <= winp <= 0.55 else "passed (map is lopsided enough to read)"))
    print("    edge band              %s" % ("in the 6-9%% zone" if 0.06 <= p["edge"] < 0.09
                                             else "outside the zone (%.1f%%)" % (100 * p["edge"])))
    if p.get("pp_line") is not None and p["pp_line"] != p["line"]:
        better = "PrizePicks" if ((p["pp_line"] > p["line"]) == (p["side"] == "lower")) else "Underdog"
        print("    price shop             Underdog %.1f vs PrizePicks %.1f -> take %s" %
              (p["line"], p["pp_line"], better))


def slip_audit(picks):
    print("\n" + "=" * 74)
    print("SLIP AUDIT")
    zone = [p for p in picks if 0.06 <= p["edge"] < 0.09 and not (0.45 <= p["map_winp"] <= 0.55)]
    if len(zone) < 2:
        print("  fewer than two qualifying picks -- no slip")
        return
    best = None
    for n in (2, 3):
        for combo in itertools.combinations(zone, n):
            matches = {c["match_id"] for c in combo}
            teams = {c["team"] for c in combo}
            players = {c["player"] for c in combo}
            if len(players) < n:
                continue
            joint = 1.0
            for c in combo:
                joint *= c["model_p"]
            need = 1.0 / PAY[n]
            ok_match = len(matches) == n
            ok_team = len(teams) >= 2
            row = (n, combo, joint, need, ok_match, ok_team)
            if joint > need and ok_match and ok_team and (best is None or joint / need > best[2] / best[3]):
                best = row
        if best and best[0] == n:
            n_, combo, joint, need, ok_match, ok_team = best
            print("\n  %d-PICK (pays %.1fx)" % (n_, PAY[n_]))
            for c in combo:
                print("    %-13s %-5s %-5.1f %-9s  %4.0f%%   %s" %
                      (c["player"], "UNDER" if c["side"] == "lower" else "OVER", c["line"],
                       "headshots" if c["kind"] == "hs" else "kills", 100 * c["model_p"], c["match"][:26]))
            print("    all hit %.0f%%   need %.0f%%   value %+.0f%%" %
                  (100 * joint, 100 * need, 100 * (joint / need - 1)))
            print("    different matches: %s    two or more teams: %s" %
                  ("yes" if ok_match else "NO -- correlated", "yes" if ok_team else "NO"))
            best = None


if __name__ == "__main__":
    picks = latest_picks()
    if not picks:
        sys.exit("no picks logged yet -- run: python _cs2_live.py card")
    S, raw = build()
    want = sys.argv[1].lower() if len(sys.argv) > 1 else None
    sel = [p for p in picks if not want or p["player"].lower() == want]
    zone = [p for p in sel if 0.06 <= p["edge"] < 0.09 and not (0.45 <= p["map_winp"] <= 0.55)]
    for p in (zone or sel)[:8]:
        explain(p, S, raw)
    if not want:
        slip_audit(picks)
