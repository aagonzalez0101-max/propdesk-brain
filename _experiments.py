"""ONE CHANGE AT A TIME (2026-10-02). User: "change one thing at a time and retest, then keep it or retest after making ONE change."

    python _experiments.py replay            # every graded day: BASELINE card vs each single change, same data, same scoring
    python _experiments.py log               # the decision log (experiments.jsonl)
    python _experiments.py decide NAME keep|revert "why"

How it scores: rebuild the day's card from calls_log (only calls logged BEFORE the games, graded from box scores) under a rule set,
grade every slip at the app's real payout, report slips / hit rate / ROI. A change is judged against the baseline on the SAME days.
Replay alone is in-sample for anything fitted to these days (calibration) -> the daily loop also builds every candidate's card
forward (cards/<date>__<name>.json) and grades it, and a change is only kept after its FORWARD record beats the baseline.
"""
import sys, os, json, copy, datetime, collections

LOG = "experiments.jsonl"
BASELINE = dict(bar_pp=0.62, cush_ud=0.02, calibration=False, nhl_shots_over=False, soccer=False, sizes=(3, 2, 2, 2, 2), rank="ev", wnba_overs=True, nhl_take_overs=False)
# ^ baseline == the LIVE rules (rules.json). nhl_shots_over promoted 2026-10-02 after its test; candidates below are ONE change from this.
CANDIDATES = {                       # each = ONE change from the baseline
    "calibration": dict(calibration=True),
    "bar_0.65": dict(bar_pp=0.65),
    "only_2picks": dict(sizes=(2, 2, 2, 2, 2)),
    "nhl_shots_over": dict(nhl_shots_over=True),   # reverted 10/2 (goblin-inflated evidence) -> back in forward test
    "rank_by_prob": dict(rank="prob"),
    "nhl_take_overs": dict(nhl_take_overs=True),   # 10/3: NHL TAKE overs that clear their real price went 8-4 (9/30-10/2) vs WNBA overs 15-22
    "wnba_unders_only": dict(wnba_overs=False),   # WNBA overs on real lines 22-24; unders 17-3 (10/2)        # card legs hit 57% vs ~80% for all TAKE calls: biggest-edge picks the overconfident ones
}
BASE_PAY = {"PP": {2: 3.0, 3: 5.0, 4: 10.0}, "UD": {2: 3.5, 3: 6.5, 4: 10.0}}
BE = {"UD": 1 / 3.5 ** 0.5, "PP": 1 / 3.0 ** 0.5}


def side(c):
    return "over" if "OVER" in c else "under"


def legs_for(day, cfg, rows):
    import _calibrate as C
    cal = json.load(open("calibration.json")) if (cfg["calibration"] and os.path.exists("calibration.json")) else {}
    out = {}
    for r in rows:
        if r.get("date") != day or not (r.get("call") or "").startswith("TAKE") or r.get("result") not in ("W", "L"):
            continue
        sd = side(r["call"]); mk = C.market(r["sport"], r["stat"])
        ok_mkt = (mk == "NHL saves") or (cfg.get("nhl_take_overs") and r["sport"] == "NHL" and sd == "over") or (cfg["nhl_shots_over"] and mk == "NHL shots" and sd == "over") or \
                 (r["sport"] in ("WNBA", "NBA") and (cfg.get("wnba_overs", True) or sd == "under")) or (cfg["soccer"] and r["sport"] == "SOCCER" and sd == "under")
        if not ok_mkt or r.get("kind") not in ("standard", None) or any("OFF PINNACLE" in f for f in (r.get("flags") or [])):
            continue
        p = C.prob(r)
        if p is None:
            continue
        if cal and r.get("p_pin") is None:
            p = min(0.97, max(0.03, p + cal.get("%s|%s" % (mk, sd), {}).get("adj", 0.0)))
        venue = r.get("venue") or "PP"
        m = 1.0
        if venue == "UD":
            m = r.get("mult")
            if isinstance(m, dict):
                m = m.get(sd)
            elif r.get("side") not in (None, sd):        # a float stored for the other side (the NHL goals bug) -> unusable
                m = None
            if not m:
                continue
        good = p >= cfg["bar_pp"] if venue == "PP" else p * m >= BE["UD"] + cfg["cush_ud"]
        if not good:
            continue
        leg = dict(r, _p=p, _m=m, _v=p * m, venue=venue, side=sd)
        k = (r["player"], venue)
        if k not in out or leg["_v"] > out[k]["_v"]:
            out[k] = leg
    return list(out.values())


def build(L, sizes, rank="ev"):
    import itertools
    card, used = [], set()
    for n in sizes:
        best = None
        for venue in ("PP", "UD"):
            pool = sorted([l for l in L if l["venue"] == venue and l["player"] not in used], key=lambda l: -(l["_p"] if rank == "prob" else l["_v"]))[:16]
            for combo in itertools.combinations(pool, n):
                if len({c.get("team") for c in combo}) < n or len({"|".join(sorted([str(c.get("team")), str(c.get("opp"))])) for c in combo}) < n:
                    continue
                pr, pay = 1.0, BASE_PAY[venue][n]
                for c in combo:
                    pr *= c["_p"]; pay *= c["_m"]
                score = pr if rank == "prob" else pr * pay - 1
                if pr * pay - 1 > 0 and (not best or score > best[3]):
                    best = (pr * pay - 1, pay, combo, score)
        if best:
            card.append(best[:3]); used |= {c["player"] for c in best[2]}
    return card


def score(cfg, days, rows):
    s = dict(slips=0, wins=0, staked=0.0, back=0.0, legs=0, legw=0)
    for d in days:
        for ev, pay, combo in build(legs_for(d, cfg, rows), cfg["sizes"], cfg.get("rank", "ev")):
            hit = all(c["result"] == "W" for c in combo)
            s["slips"] += 1; s["wins"] += hit; s["staked"] += 1; s["back"] += pay if hit else 0
            s["legs"] += len(combo); s["legw"] += sum(c["result"] == "W" for c in combo)
    s["roi"] = (s["back"] - s["staked"]) / s["staked"] if s["staked"] else 0.0
    return s


def replay():
    rows = [json.loads(l) for l in open("calls_log.jsonl", encoding="utf-8")]
    days = sorted({r["date"] for r in rows if r.get("result") in ("W", "L")})
    base = score(BASELINE, days, rows)
    fmt = lambda n, s: "%-16s slips %-3d won %-3d (%3.0f%%)  legs %3.0f%%  $1/slip net %+6.2f  ROI %+5.0f%%" % (
        n, s["slips"], s["wins"], 100 * s["wins"] / max(1, s["slips"]), 100 * s["legw"] / max(1, s["legs"]), s["back"] - s["staked"], 100 * s["roi"])
    print("graded days: %s\n" % ", ".join(days))
    print(fmt("BASELINE", base))
    res = {}
    for name, ch in CANDIDATES.items():
        cfg = dict(BASELINE, **ch); s = score(cfg, days, rows); res[name] = s
        print(fmt("+ " + name, s) + "   (vs baseline %+.2f)" % ((s["back"] - s["staked"]) - (base["back"] - base["staked"])))
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(ts=datetime.datetime.now().isoformat(timespec="minutes"), kind="replay", days=days, baseline=base,
                                candidates=res)) + "\n")


def forward(day):
    """build tonight's card under the baseline and under each single change -> cards/<day>__<name>.json (graded later)."""
    import _card
    os.makedirs("cards", exist_ok=True)
    # forward cards use the live legs files, so they share the card builder's leg filter; the rule switches map onto it
    for name, ch in [("baseline", {})] + list(CANDIDATES.items()):
        cfg = dict(BASELINE, **ch)
        json.dump(dict(cfg=cfg), open(os.path.join("cards", "%s__%s.json" % (day, name)), "w"))
    print("forward configs written for", day)


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] == "replay":
        replay()
    elif a[0] == "log":
        for l in open(LOG, encoding="utf-8"):
            r = json.loads(l)
            print(r["ts"], r["kind"], r.get("name", ""), r.get("decision", ""), r.get("why", ""))
    elif a[0] == "decide":
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(ts=datetime.datetime.now().isoformat(timespec="minutes"), kind="decision", name=a[1], decision=a[2],
                                    why=" ".join(a[3:]))) + "\n")
        print("logged:", a[1], a[2])
