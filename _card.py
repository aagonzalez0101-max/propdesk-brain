"""THE DAY'S CARD -- slips built from today's legs files under the card rules (2026-10-01).

    python _card.py [YYYY-MM-DD]          # games not started yet, today
    python _card.py 2026-09-30 --all      # include started/finished games (replays)

Rules (memory feedback_card_building): one player per CARD; PP standard legs need p >= 62%; Underdog legs need
p x multiplier(for the side taken) >= break-even + 2pp; drop a player if ANY of his lines is flagged off Pinnacle;
one leg per game and per team on a slip; skip players already on a live ticket today; never force a slip.
Builds the best 3-pick, then 2-picks, from what's left. Writes cards/<date>.json for grading.
"""
import sys, os, json, glob, itertools, datetime

CT = datetime.timezone(datetime.timedelta(hours=-5))
BAR_PP, CUSH_UD = 0.62, 0.02
BE = {"UD": 1 / 3.5 ** 0.5, "PP": 1 / 3.0 ** 0.5}
BASE = {"UD": {2: 3.5, 3: 6.5}, "PP": {2: 3.0, 3: 5.0}}
MONEYISH = {"NHL", "WNBA", "NBA"}
RULES = json.load(open("rules.json")) if os.path.exists("rules.json") else {}      # the LIVE rule set (one change at a time)
CAL = json.load(open("calibration.json")) if os.path.exists("calibration.json") else {}          # MLB paused for the playoffs (user 2026-10-02)


def venue_alt(l):
    """UD lopsided lines (>=1.5x or <=0.7x) are its goblins/demons -- out (user 10/3)."""
    m = l.get("mult")
    ms = [v for v in (m.values() if isinstance(m, dict) else [m]) if isinstance(v, (int, float))]
    return l.get("venue") == "UD" and any(v >= 1.5 or v <= 0.7 for v in ms)


def live_players(day):
    out = set()
    if os.path.exists("live_paper.jsonl"):
        for l in open("live_paper.jsonl", encoding="utf-8"):
            r = json.loads(l)
            if r.get("kind") == "LIVE" and r.get("result") == "PENDING":
                for g in r.get("legs") or []:
                    if isinstance(g, dict) and g.get("player"):
                        out.add(g["player"])
    return out


def legs(day, include_started):
    now = datetime.datetime.now(datetime.timezone.utc)
    L, flagged = [], set()
    for f in glob.glob(os.path.join("legs", "%s_*.json" % day)):
        for l in json.load(open(f, encoding="utf-8")):
            if "MODEL OFF PINNACLE" in (l.get("flags") or []):
                flagged.add(l["player"])
            L.append(l)
    out = []
    for l in L:
        if (l.get("venue") or "PP") == "UD":
            continue          # 10/5 user: Underdog closed ($0) -- PrizePicks legs only
        if l["sport"] == "NBA" and day < "2026-10-20":
            continue          # 10/5: NBA PRESEASON -- stars play 15-20 min, the model uses reg-season minutes (card showed 90%+ PRA overs = bug)
        if l["sport"] not in MONEYISH or l["player"] in flagged or l.get("kind") not in ("standard", None) or (venue_alt(l)):
            continue
        k = "".join(ch for ch in l["stat"].lower() if ch.isalnum())
        c = l.get("call") or ""
        want = "over" if "OVER" in c else "under"          # 10/3 fix: was read BEFORE being set -> used the previous leg's side
        if l["sport"] == "NHL" and not ("saves" in k or (RULES.get("nhl_shots_over") and "shot" in k and want == "over")
                                        or (RULES.get("nhl_take_overs") and want == "over" and c.startswith("TAKE"))):
            continue          # NHL money markets: goalie saves (+ candidates: shots overs / every NHL TAKE over that clears its price)
        if l["sport"] in ("WNBA", "NBA") and want == "over" and RULES.get("wnba_overs", True) is False:
            continue
        if l["sport"] == "MLB" and k not in ("hits", "hitsrunsrbis", "totalbases"):
            continue          # MLB money markets: hits, H+R+RBI, total bases
        c = l.get("call") or ""
        if not c.startswith("TAKE"):
            continue
        want = "over" if "OVER" in c else "under"
        if l["side"] != want or (l["sport"] == "MLB" and want == "over"):
            continue
        if not include_started and l.get("start"):
            try:
                if datetime.datetime.fromisoformat(str(l["start"]).replace("Z", "+00:00")) <= now:
                    continue
            except ValueError:
                pass
        p = l.get("p_pin") if l.get("p_pin") is not None else l.get("p")
        if p is None:
            continue
        if l.get("p_pin") is None and RULES.get("calibration"):   # calibration only when the live rules switch it on
            import _calibrate as _C
            p = min(0.97, max(0.03, p + CAL.get("%s|%s" % (_C.market(l["sport"], l["stat"]), want), {}).get("adj", 0.0)))
        venue = l.get("venue") or "PP"
        m = l.get("mult") if venue == "UD" else 1.0
        if isinstance(m, dict):
            m = m.get(want)
        if not m:
            continue
        ok = (p >= RULES.get("bar_pp", BAR_PP)) if venue == "PP" else (p * m >= BE["UD"] + RULES.get("cush_ud", CUSH_UD))
        if ok:
            out.append(dict(l, _p=p, _m=m, _v=p * m, venue=venue))
    best = {}
    for l in out:
        k = (l["player"], l["venue"])
        if k not in best or l["_v"] > best[k]["_v"]:      # best VALUE per player, not best hit rate
            best[k] = l
    return list(best.values())


def build(L, taken):
    card, used = [], set(taken)
    for n in RULES.get("sizes", (3, 2, 2, 2, 2)):
        cands = []
        for venue in ("PP", "UD"):
            pool = sorted([l for l in L if l["venue"] == venue and l["player"] not in used],
                          key=lambda l: -(l["_p"] if RULES.get("rank") == "prob" else l["_v"]))[:18]
            for combo in itertools.combinations(pool, n):
                teams = {c.get("team") for c in combo}
                games = {"|".join(sorted([str(c.get("team")), str(c.get("opp"))])) for c in combo}
                if len(teams) < n or len(games) < n:
                    continue
                pr, pay = 1.0, BASE[venue][n]
                for c in combo:
                    pr *= c["_p"]; pay *= c["_m"]
                cands.append((pr * pay - 1, pr, pay, venue, combo))
        if not cands:
            continue
        ev, pr, pay, venue, combo = max(cands, key=lambda x: x[1] if RULES.get("rank") == "prob" and x[0] > 0 else (x[0] if RULES.get("rank") != "prob" else -1))
        if ev <= 0:
            continue
        card.append(dict(venue=venue, n=n, pay=round(pay, 2), p=round(pr, 3), ev=round(ev, 3),
                         legs=[dict(sport=c["sport"], player=c["player"], team=c.get("team"), opp=c.get("opp"), stat=c["stat"],
                                    line=c["line"], side=c["side"], mult=c["_m"], p=round(c["_p"], 3), start=c.get("start")) for c in combo]))
        used |= {c["player"] for c in combo}
    return card


def grade(day):
    """grade cards/<day>.json slips from calls_log results (same player / stat / line)."""
    import glob as _g
    for f in sorted(_g.glob(os.path.join("cards", "%s*.json" % day))):
        _grade_file(f)


def _grade_file(f):
    card = json.load(open(f, encoding="utf-8"))
    if isinstance(card, dict):
        return _grade_five(f, card)
    res = {}
    for l in open("calls_log.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if r.get("result") in ("W", "L", "PUSH", "VOID") or str(r.get("result", "")).startswith("CLOSE"):
            res[(r["player"], r["stat"], r["line"])] = r
    staked = back = 0.0
    for s in card:
        legs = []
        for g in s["legs"]:
            r = res.get((g["player"], g["stat"], g["line"]))
            if not r or r.get("actual") is None:
                legs.append(None); continue
            v = r["actual"]
            legs.append(None if r.get("result") == "VOID" else ((v > g["line"]) if g["side"] == "over" else (v < g["line"])))
        if None in legs:
            s["result"] = "PENDING"
        else:
            s["result"] = "W" if all(legs) else "L"
            staked += 1; back += s["pay"] if all(legs) else 0
        print("  %s %d-pick %.2fx: %s" % (s["venue"], s["n"], s["pay"], s["result"]))
    json.dump(card, open(f, "w", encoding="utf-8"), indent=1)
    print("%s: $1/slip -> staked $%.0f, back $%.2f, net %+.2f" % (os.path.basename(f), staked, back, back - staked))


def _grade_five(f, card):
    """the daily five (cards/<day>__five.json, 10/3): each leg is a STRAIGHT 1-unit pick at its UD multiplier.
    Actuals: calls_log first; NFL/CFB legs (not always screened) straight from sports.db."""
    import sqlite3, re
    import _five as F
    nm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
    res = {}
    for l in open("calls_log.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if r.get("actual") is not None:
            res[(nm(r["player"]), nm(r["stat"]), r["line"])] = r["actual"]
    c = sqlite3.connect("sports.db", timeout=60)
    w = n = 0
    for g in card.get("legs", []) + card.get("extra", []):
        v = res.get((nm(g["player"]), nm(g["stat"]), g["line"]))
        st_ = F.__dict__.get("KEY_DB" if g["sport"] == "CFB" else "KEY_NFL", {}).get(
            __import__("_mismatch").STAT.get(nm(g["stat"]), ""))
        gday = None
        if g.get("start"):
            t0 = datetime.datetime.fromisoformat(str(g["start"]).replace("Z", "+00:00"))
            gday = None if t0 > datetime.datetime.now(datetime.timezone.utc) else t0.astimezone(datetime.timezone(datetime.timedelta(hours=-5))).date().isoformat()
        if v is None and st_ and gday and g["sport"] in ("NFL", "CFB"):          # only after kickoff, only THAT game's date (10/3: matched a wrong row)
            ses = [json.loads(s) for (s,) in c.execute("SELECT stats FROM player_games WHERE sport=? AND player=? AND date IN (?, ?)",
                                                       (g["sport"], g["player"], gday,
                                                        (datetime.date.fromisoformat(gday) + datetime.timedelta(days=1)).isoformat()))]
            if ses:
                v = float(ses[0].get(st_) or 0)
        g["actual"] = v
        g["result"] = "PENDING" if v is None else ("W" if (v > g["line"] if g["side"] == "over" else v < g["line"]) else "L")
        if g in card.get("legs", []) and v is not None:
            n += 1; w += g["result"] == "W"
        print("  five: %-22s %-5s %-6s %-16s -> %s %s" % (g["player"], g["side"], g["line"], g["stat"], v, g["result"]))
    json.dump(card, open(f, "w", encoding="utf-8"), indent=1)
    print("%s: %d-%d graded (straights)" % (os.path.basename(f), w, n - w))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "grade":
        for d in a[1:] or [(datetime.datetime.now(CT).date() - datetime.timedelta(days=1)).isoformat()]:
            grade(d)
        raise SystemExit
    day = next((x for x in a if len(x) == 10 and x[4] == "-"), datetime.datetime.now(CT).date().isoformat())
    tag = ""
    if "--config" in a:                                       # forward A/B: baseline or baseline + ONE candidate change
        import _experiments as X
        name = a[a.index("--config") + 1]
        RULES.clear(); RULES.update(dict(X.BASELINE, **X.CANDIDATES.get(name, {})))
        tag = "__" + name
    L = legs(day, "--all" in a)
    taken = live_players(day) if "--all" not in a else set()
    card = build(L, taken)
    print("CARD %s: %d qualifying legs (%d players already on live tickets skipped)" % (day, len(L), len(taken)))
    if not card:
        print("  nothing passes -- no card today")
    for s in card:
        print("\n  %s %d-pick  pays %.2fx  hits %.0f%%  EV %+.0f%%" % (s["venue"], s["n"], s["pay"], 100 * s["p"], 100 * s["ev"]))
        for g in s["legs"]:
            print("     %-5s %-22s %-4s v %-4s %-18s %-5s %-5s x%.2f  %.0f%%" % (g["sport"], g["player"][:22], g["team"], g["opp"], g["stat"][:18],
                                                                           g["side"], g["line"], g["mult"], 100 * g["p"]))
    os.makedirs("cards", exist_ok=True)
    fn = os.path.join("cards", "%s%s.json" % (day, tag))
    if os.path.exists(fn) and "--force" not in a:
        try:
            prev = json.load(open(fn, encoding="utf-8"))
        except Exception:
            prev = []
        started = [g for s_ in (prev if isinstance(prev, list) else []) for g in s_.get("legs", []) if g.get("start")
                   and datetime.datetime.fromisoformat(str(g["start"]).replace("Z", "+00:00")) <= datetime.datetime.now(datetime.timezone.utc)]
        if started:                                   # 10/3: the 21:00 rerun blanked the morning card after kickoff -> it lost its grade
            print("card %s is locked: %d of its legs already started -- not overwriting" % (fn, len(started))); sys.exit(0)
    json.dump(card, open(fn, "w", encoding="utf-8"), indent=1)
