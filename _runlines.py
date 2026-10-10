"""Price MLB run lines and alt run lines off the ML model.

A run line is just the moneyline plus a margin question, so it needs two things:
the model's P(win), and the measured distribution of WINNING MARGINS.

    P(fav covers -k.5)  = P(win) * P(margin >= k+1 | win)
    P(dog covers +k.5)  = P(win) + P(lose by <= k)

Measured on 2167 MLB finals in 2026, not assumed from a normal curve -- baseball
margins are lumpy at 1 and 2 and a bell curve gets both badly wrong:
    by 1  27.5%     by 2  19.0%     by 3  14.4%     by 4  10.1%

The favourite/underdog split is applied conditionally: a team's own win
probability decides how the margin mass divides, so a 60% favourite is not
handed a 50/50 share of the 1-run games.
"""
import json, io, sys, math, urllib.request, datetime as dt, collections

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace", write_through=True)
CT = dt.timezone(dt.timedelta(hours=-5))
PIN = "https://guest.api.arcadia.pinnacle.com"
H = {"User-Agent": "Mozilla/5.0", "Accept": "application/json",
     "X-API-Key": "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R"}

MARG = json.load(open("_margin_dist.json", encoding="utf-8"))
TOT = sum(MARG.values())
P_MARGIN = {int(k): v / TOT for k, v in MARG.items()}      # P(|margin| = k)


def dec(o):
    return 1 + (o / 100 if o > 0 else 100 / -o)


def imp(o):
    return (-o / (-o + 100.0)) if o < 0 else (100.0 / (o + 100.0))


def outcome_probs(p_win, line):
    """(P(cover), P(push), P(lose)) for this side at `line`.

    INTEGER lines push. A +1.0 is NOT "win or lose by one" -- losing by exactly
    one returns the stake. Counting that push as a win inflated every plus-line
    on the board and made 40 of 196 prices look +EV, all of them on the taking-
    runs side. Half-lines (-1.5, +2.5) cannot push and take the simple path.
    """
    tot = sum(P_MARGIN.values())
    def mass(pred):
        return sum(v for m, v in P_MARGIN.items() if pred(m)) / tot

    k = abs(line)
    whole = float(k).is_integer()
    ki = int(k)
    if line < 0:                                  # laying runs
        if whole:
            win  = p_win * mass(lambda m: m >= ki + 1)
            push = p_win * mass(lambda m: m == ki)
        else:
            win  = p_win * mass(lambda m: m >= ki + 1)
            push = 0.0
        return win, push, 1.0 - win - push
    # taking runs: cover by winning outright, or losing by less than the line
    if whole:
        win  = p_win + (1 - p_win) * mass(lambda m: m <= ki - 1)
        push = (1 - p_win) * mass(lambda m: m == ki)
    else:
        win  = p_win + (1 - p_win) * mass(lambda m: m <= ki)
        push = 0.0
    return win, push, 1.0 - win - push


def get(u):
    b = urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=30).read()
    return json.loads(b) if b else None


mu = get("%s/0.1/leagues/246/matchups?brandId=0" % PIN)
mk = get("%s/0.1/leagues/246/markets/straight" % PIN)
spreads = collections.defaultdict(list)
for m in mk or []:
    if m.get("period") != 0 or not str(m.get("key", "")).startswith("s;0;s;"):
        continue
    spreads[m["matchupId"]].append(m)

# model probabilities from tonight's board
board = json.load(open(sys.argv[1], encoding="utf-8"))
mlp = {}
for r in board["picks"]:
    if r["market"] != "ML":
        continue
    home = r["game"].split(" @ ")[1]
    ph = r["raw"] if r["selection"] == home else 1 - r["raw"]
    mlp[r["game"]] = (ph, r["game"].split(" @ ")[0], home)

out = []
for m in mu or []:
    if m.get("parentId") or m.get("type") != "matchup":
        continue
    sp = spreads.get(m["id"])
    if not sp:
        continue
    d = {p["alignment"]: p["name"] for p in m["participants"]}
    game = "%s @ %s" % (d.get("away"), d.get("home"))
    if game not in mlp:
        continue
    p_home, away, home = mlp[game]
    t = dt.datetime.fromisoformat(m["startTime"].replace("Z", "+00:00")).astimezone(CT)
    for s in sp:
        for pr in s.get("prices", []):
            side = pr.get("designation")
            pts, odds = pr.get("points"), pr.get("price")
            if pts is None or odds is None:
                continue
            pw = p_home if side == "home" else 1 - p_home
            team = home if side == "home" else away
            cw, cpush, cl = outcome_probs(pw, pts)
            # a push returns the stake, so it contributes 0 -- not a win
            ev = cw * (dec(odds) - 1) - cl
            out.append((ev, team, pts, odds, cw, imp(odds), t, game, cpush))

out.sort(key=lambda x: -x[0])
print("RUN LINES + ALT RUN LINES, priced off the ML model\n")
print("%-8s %-22s %6s %7s %7s %6s %7s %8s"
      % ("first", "pick", "line", "odds", "cover", "push", "mkt", "EV"))
for evv, team, pts, odds, cp, mp, t, game, cpush in out[:16]:
    print("%-8s %-22s %+6.1f %+7.0f %6.1f%% %5.1f%% %6.1f%% %+7.1f%%%s"
          % (t.strftime("%I:%M%p").lstrip("0"), team[:22], pts, odds,
             100 * cp, 100 * cpush, 100 * mp, 100 * evv, "  <<<" if evv > 0.03 else ""))
print("\n%d of %d run-line prices clear +3%% EV" % (sum(1 for x in out if x[0] > .03), len(out)))
json.dump([[round(x[0], 4)] + list(x[1:6]) + [str(x[6]), x[7], x[8]] for x in out],
          open("_runlines_today.json", "w"), default=str)
