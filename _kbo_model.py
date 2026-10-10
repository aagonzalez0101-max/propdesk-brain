"""KBO v2 = team Elo + STARTING PITCHER term (2026-10-03, user: "make KBO bettable").

    python _kbo_model.py test       # walk-forward: does the starter term beat Elo-only? (fit 2022-24, score 2025-26)
    python _kbo_model.py board      # tonight: starters, Pinnacle fair, v2 price, edge, OPENER flag -> kbo_board_log.jsonl
    python _kbo_model.py grade      # grade logged board rows (model side vs result, and vs the Pinnacle price we logged)

Measured first (_kbo_sp.py fit, 2,301 games): each 1.0 of starter ERA gap = +2.0 pts of win prob ON TOP of Elo.
The term: logit(p) = logit(p_elo) + B * gap, gap = shrunk away ERA - shrunk home ERA (ERA shrunk toward league 4.40 by
30 IP, so a 20-IP 1.80 isn't read as an ace), clipped to +-4. B is fit on 2022-24 only, scored on 2025-26.
Starter stats are AS OF the game (Naver preview innings grow through the season -- checked, no leak).

BET rule (forward-tested, not proven): v2 beats Pinnacle's de-vigged price by 4+ pts on a side AND a STARTER reason points
the same way -- an opener (< 3.5 IP/app) on the OTHER side only (the 6-for-6 signal), or a 1.0+ ERA gap for our side.
No historical KBO closing prices exist free, so the price test is forward: every board row is logged and graded.
"""
import sys, os, json, math, datetime, time, collections
import requests
import _kbo as K

SP = "kbo_starters.jsonl"
LOG = "kbo_board_log.jsonl"
LG_ERA, PRIOR_IP = 4.40, 30.0
CT = datetime.timezone(datetime.timedelta(hours=-5))
lg = lambda p: math.log(p / (1 - p))
sg = lambda x: 1 / (1 + math.exp(-x))


def shrunk(era, inn):
    return (era * inn + LG_ERA * PRIOR_IP) / (inn + PRIOR_IP)


def gap_of(r):
    if not (r.get("h_inn") or 0) >= 20 or not (r.get("a_inn") or 0) >= 20 or r.get("h_era") is None or r.get("a_era") is None:
        return 0.0                                        # unknown/new starter -> no starter term
    return max(-4, min(4, shrunk(r["a_era"], r["a_inn"]) - shrunk(r["h_era"], r["h_inn"])))


def walk(B, rows, sp, score_from):
    adv, _ = K.fit_home_adv(rows)
    e = K.Elo(12.0, adv, 0.60)
    n = ll0 = ll1 = 0.0
    for g in rows:
        if g["date"] >= score_from and g["hs"] != g["as_"]:
            p0 = e.p_home(g["home"], g["away"])
            p1 = sg(lg(p0) + B * gap_of(sp.get(g["gameId"], {})))
            won = g["hs"] > g["as_"]
            ll0 += -math.log(p0 if won else 1 - p0); ll1 += -math.log(p1 if won else 1 - p1); n += 1
        e.update(g)
    return ll0 / n, ll1 / n, int(n)


def test():
    rows = K.load()
    sp = {json.loads(l)["gameId"]: json.loads(l) for l in open(SP, encoding="utf-8")}
    train = [g for g in rows if g["date"] < "2025"]
    best = min(((walk(B, train, sp, "2023")[1], B) for B in [i / 100 for i in range(0, 31, 2)]))
    B = best[1]
    ll0, ll1, n = walk(B, rows, sp, "2025")
    print("fit on 2022-24 -> B = %.2f logit per ERA (~%.1f pts per ERA near 50%%)" % (B, 100 * B / 4))
    print("2025-26 out of sample, %d games:  Elo-only logloss %.4f   Elo+starter %.4f   (%s)" % (
        n, ll0, ll1, "STARTER TERM HELPS" if ll1 < ll0 else "no help"))
    json.dump(dict(B=B, fit="2022-24", oos_n=n, oos_ll_elo=ll0, oos_ll_v2=ll1), open("_kbo_v2.json", "w"))
    return B


def preview(gid):
    try:
        p = (requests.get("https://api-gw.sports.naver.com/schedule/games/%s/preview" % gid, headers=K.H, timeout=25).json()
             .get("result") or {}).get("previewData") or {}
    except Exception:
        return {}
    out = {}
    for side, tag in (("homeStarter", "h"), ("awayStarter", "a")):
        s = p.get(side) or {}
        cs = s.get("currentSeasonStats") or {}
        out[tag + "_sp"] = (s.get("playerInfo") or {}).get("name")
        out[tag + "_era"] = K_f(cs.get("era")); out[tag + "_inn"] = ip(cs.get("inn"))
        out[tag + "_g"] = K_f(cs.get("gameCount") or cs.get("game") or cs.get("g"))
    return out


def ip(v):
    """Naver innings "32.1" = 32 1/3, not 32.1."""
    try:
        w, _, f = str(v).partition(".")
        return int(w) + (int(f or 0) / 3)
    except (TypeError, ValueError):
        return None


def K_f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def board():
    cfg = json.load(open("_kbo_v2.json")) if os.path.exists("_kbo_v2.json") else {"B": test()}
    B = cfg["B"]
    rows = K.load()
    adv, _ = K.fit_home_adv(rows)
    e = K.Elo(12.0, adv, 0.60)
    for g in rows:
        e.update(g)
    today = datetime.datetime.now(CT).date()
    sch = requests.get(K.NAVER, params=dict(fromDate=today.isoformat(), toDate=(today + datetime.timedelta(days=2)).isoformat(),
                                            categoryId="kbo", size=500), headers=K.H, timeout=30).json()
    nav = {}
    for g in sorted((sch.get("result") or {}).get("games") or [], key=lambda g: g["gameDate"]):
        if g.get("statusCode") != "RESULT" and not g.get("cancel"):
            nav.setdefault((g["homeTeamCode"], g["awayTeamCode"]), g)   # NEXT game of the pair (10/5 was overwriting 10/4)
    mu = requests.get(K.PIN + "/0.1/leagues/%d/matchups?brandId=0" % K.LEAGUE, headers=K.PH, timeout=25).json()
    mk = requests.get(K.PIN + "/0.1/leagues/%d/markets/straight" % K.LEAGUE, headers=K.PH, timeout=25).json()
    games = {}
    for m in mu:
        if m.get("parent") or len(m.get("participants") or []) != 2:
            continue
        ps = m["participants"]
        games[m["id"]] = dict(home=next((p["name"] for p in ps if p.get("alignment") == "home"), ps[0]["name"]),
                              away=next((p["name"] for p in ps if p.get("alignment") == "away"), ps[1]["name"]), start=m.get("startTime"))
    imp = lambda o: (-o) / ((-o) + 100) if o < 0 else 100 / (o + 100)
    seen, out = set(), []
    for r in mk:
        if r.get("type") != "moneyline" or r.get("period") != 0 or r.get("matchupId") in seen:
            continue
        g = games.get(r.get("matchupId")); pr = {p.get("designation"): p["price"] for p in (r.get("prices") or [])}
        if not g or "home" not in pr or "away" not in pr:
            continue
        seen.add(r["matchupId"])
        h, a = K.NAME.get(g["home"], g["home"]), K.NAME.get(g["away"], g["away"])
        fh = imp(pr["home"]) / (imp(pr["home"]) + imp(pr["away"]))
        ng = nav.get((h, a)); s = preview(ng["gameId"]) if ng else {}
        p0 = e.p_home(h, a); gap = gap_of(s); p1 = sg(lg(p0) + B * gap)
        flags = []
        for tag, nm in (("h", g["home"]), ("a", g["away"])):
            if s.get(tag + "_inn") and s.get(tag + "_g") and s[tag + "_inn"] / s[tag + "_g"] < 3.5:
                flags.append("OPENER %s (%.1f IP/app) -> lean %s" % (nm, s[tag + "_inn"] / s[tag + "_g"], g["away"] if tag == "h" else g["home"]))
            if not s.get(tag + "_sp"):
                flags.append("%s starter not announced" % nm)
        eh, ea = p1 - fh, (1 - p1) - (1 - fh)
        side = None
        cand = g["home"] if eh > ea else g["away"]
        lean_op = [f for f in flags if f.startswith("OPENER")]
        op_for = {f.split("-> lean ")[1] for f in lean_op}
        gap_for = g["home"] if gap >= 1 else (g["away"] if gap <= -1 else None)
        # 10/3: an Elo-only disagreement is NOT a bet (Elo never beat Pinnacle). Need a STARTER reason pointing the same way:
        # an opener on the other side (and not on ours), or a real ERA gap (1.0+) for our side.
        reason = (cand in op_for and len(op_for) == 1) or (gap_for == cand and not lean_op)
        if max(eh, ea) >= 0.04 and reason and not any("not announced" in f for f in flags):
            side = cand
        row = dict(day=today.isoformat(), gameId=(ng or {}).get("gameId"), home=g["home"], away=g["away"], start=g["start"],
                   pin_home=pr["home"], pin_away=pr["away"], fair_home=round(fh, 3), elo_home=round(p0, 3), v2_home=round(p1, 3), gap=round(gap, 2),
                   h_sp=s.get("h_sp"), a_sp=s.get("a_sp"), h_era=s.get("h_era"), a_era=s.get("a_era"), h_inn=s.get("h_inn"), a_inn=s.get("a_inn"),
                   flags=flags, bet=side, edge=round(max(eh, ea), 3))
        out.append(row)
        time.sleep(0.3)
    have = set()
    if os.path.exists(LOG):
        have = {(json.loads(l)["gameId"], json.loads(l)["day"]) for l in open(LOG, encoding="utf-8")}
    with open(LOG, "a", encoding="utf-8") as f:
        for r in out:
            if (r["gameId"], r["day"]) not in have:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("KBO v2 (Elo + starter, B=%.2f)   bet = v2 beats Pinnacle fair by 4+ pts" % B)
    print("  %-14s %-14s %-11s %-9s %-9s %-6s  %s" % ("away", "home", "pinnacle", "fair(H)", "v2(H)", "gap", "start CT / call"))
    for r in out:
        st = datetime.datetime.fromisoformat(r["start"].replace("Z", "+00:00")).astimezone(CT).strftime("%a %I:%M%p")
        fair_side = r["fair_home"] if r["bet"] == r["home"] else 1 - r["fair_home"]
        call = ("BET %s (v2 %+.0f pts, fair %s)" % (r["bet"], 100 * r["edge"], ("-%d" % round(100 * fair_side / (1 - fair_side))) if fair_side > .5
                else "+%d" % round(100 * (1 - fair_side) / fair_side))) if r["bet"] else "pass"
        print("  %-14s %-14s %+5d/%+5d  %4.0f%%     %4.0f%%     %+5.2f  %s  %s" % (r["away"][:14], r["home"][:14], r["pin_away"], r["pin_home"],
              100 * r["fair_home"], 100 * r["v2_home"], r["gap"], st, call))
        print("      SP: %s %s ERA/%s IP  @  %s %s ERA/%s IP   %s" % (r["a_sp"], r["a_era"], r["a_inn"], r["h_sp"], r["h_era"], r["h_inn"], "; ".join(r["flags"])))


def grade():
    rows = [json.loads(l) for l in open(LOG, encoding="utf-8")] if os.path.exists(LOG) else []
    res = {g["gameId"]: g for g in K.load()}
    w = l = 0; units = 0.0
    for r in rows:
        g = res.get(r.get("gameId"))
        if not g or not r.get("bet") or g["hs"] == g["as_"]:
            continue
        home_won = g["hs"] > g["as_"]
        won = (r["bet"] == r["home"]) == home_won
        price = r["pin_home"] if r["bet"] == r["home"] else r["pin_away"]
        units += (price / 100 if price > 0 else 100 / -price) if won else -1
        w += won; l += not won
    print("KBO v2 BET calls graded at Pinnacle's logged price: %d-%d, %+.2f units" % (w, l, units))


if __name__ == "__main__":
    {"test": test, "board": board, "grade": grade}.get((sys.argv[1:] or ["board"])[0], board)()
