"""SHARP vs APP MISMATCHES (2026-10-02). User: "a -300 line for -119 on UD or PrizePicks".

    python _mismatch.py          # every UD / PP main line vs Pinnacle's price on the same player + stat (+ DraftKings when reachable)

For each app line we find the sharp line for the same player and stat. Same number -> the de-vigged probability directly. Different
number -> move along a normal with the stat's spread (sd ~ k * sqrt(line)) from the sharp median to the app line. A row is flagged when
the sharp probability of one side clears the app's per-leg break-even by 8+ points (UD: 53.5% / multiplier; PP 2-pick: 57.7%).
Output: site/mismatch.json + console. Main lines only; goblins and demons included only as ALT GLITCHES (separate tag).
"""
import json, re, os, math, time, datetime
from statistics import NormalDist

N = NormalDist()
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
PIN_LEAGUE = {"NFL": 889, "NHL": 1456, "WNBA": 578, "MLB": 246, "CFB": 880, "NBA": 487}
PP_LEAGUE = {"NFL": 9, "NHL": 8, "WNBA": 3, "MLB": 2, "CFB": 15, "NBA": 7}
UD_SPORT = {"NFL": "NFL", "NHL": "NHL", "WNBA": "WNBA", "MLB": "MLB", "CFB": "CFB", "NBA": "NBA"}
# app stat -> pinnacle stat name
STAT = {"passingyards": "passing yards", "passyards": "passing yards", "rushingyards": "rushing yards", "rushyards": "rushing yards",
        "receivingyards": "receiving yards", "receptions": "receptions", "rushattempts": "rush attempts", "passattempts": "pass attempts",
        "passcompletions": "pass completions", "completions": "pass completions", "passtds": "touchdown passes", "passingtds": "touchdown passes",
        "interceptions": "interceptions", "intsthrown": "interceptions", "int": "interceptions",
        "points": "points", "rebounds": "rebounds", "assists": "assists", "3pointersmade": "threes made", "3ptmade": "threes made",
        "ptsrebsasts": "pts & rebs & asts", "shotsongoal": "shots on goal", "saves": "saves", "goaliesaves": "saves", "goals": "goals",
        "pitcherstrikeouts": "strikeouts", "strikeouts": "strikeouts", "pitchingouts": "pitching outs", "pitchingoutsrecorded": "pitching outs",
        "hitsallowed": "hits allowed", "pitcherhitsallowed": "hits allowed", "earnedrunsallowed": "earned runs", "pitcherearnedrunsallowed": "earned runs"}
SDK = {"passing yards": 0.22, "rushing yards": 0.55, "receiving yards": 0.6, "receptions": 0.55, "rush attempts": 0.3, "pass attempts": 0.18,
       "pass completions": 0.2, "points": 0.33, "rebounds": 0.45, "assists": 0.5, "threes made": 0.7, "pts & rebs & asts": 0.25,
       "shots on goal": 0.6, "saves": 0.2, "strikeouts": 0.35, "pitching outs": 0.18, "hits allowed": 0.45}


def sd_for(stat, line):
    """realistic game-to-game spread (10/2 fix: the first version used ~1 carry on a 16.5 line and printed -800 'mismatches')."""
    L = max(line, 0.5)
    if stat in ("passing yards",):
        return 0.20 * L + 25
    if stat in ("rushing yards", "receiving yards"):
        return 0.45 * L + 12
    if stat in ("pass attempts", "pass completions"):
        return 0.15 * L + 3
    if stat in ("rush attempts",):
        return 0.25 * L + 2.5
    if stat in ("receptions", "rebounds", "assists", "strikeouts", "hits allowed", "shots on goal", "threes made"):
        return 1.0 * L ** 0.5 + 0.4
    if stat in ("points", "pts & rebs & asts"):
        return 0.25 * L + 3
    if stat in ("saves", "pitching outs"):
        return 0.18 * L + 2
    return None


def p_over_at(pin_rows, line, stat):
    """pin_rows: [(pin_line, p_over)]. Probability of OVER at the app line."""
    exact = [p for l, p in pin_rows if l == line]
    if exact:
        return exact[0]
    l0, p0 = min(pin_rows, key=lambda r: abs(r[0] - line))
    if max(l0, line) < 4.5 and stat in ("points", "goals", "assists", "shots on goal", "threes made", "touchdown passes", "interceptions", "receptions"):
        # low counts (10/3 fix: NHL Crosby 0.5 pts -> 1.5 used a basketball sd and printed 51% for a ~33% line): Poisson, fit lambda to Pinnacle
        def pov(lam, L):
            k, term, cdf = 0, math.exp(-lam), 0.0
            while k <= L:
                cdf += term; k += 1; term *= lam / k
            return 1 - cdf
        lo, hi = 0.01, 15.0
        for _ in range(60):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if pov(mid, l0) < p0 else (lo, mid)
        lam = (lo + hi) / 2
        if float(line).is_integer():                      # 10/3: whole-number line -> exactly-L is a PUSH, not an under win
            po, pu = pov(lam, line), 1 - pov(lam, line - 1)   # (Herbert U1.0 TDs read 70%; really ~29% once the push is removed)
            return po / (po + pu)
        return pov(lam, line)
    sd = sd_for(stat, l0)
    if sd is None or abs(l0 - line) > 0.75 * sd:          # only short moves between lines are trustworthy
        return None
    med = l0 + N.inv_cdf(min(0.98, max(0.02, p0))) * sd
    return 1 - N.cdf((line - med) / sd)


def main():
    import _props as P
    out = []
    for sp in ("NFL", "CFB", "NHL", "WNBA", "MLB", "NBA"):
        try:
            pin = P.pinnacle_props(PIN_LEAGUE[sp])
        except Exception as e:
            print(sp, "pinnacle fail:", e); continue
        by = {}
        for (pl, st, ln), p in pin.items():
            by.setdefault((pl, st), []).append((ln, p))
        if sp in ("NFL", "CFB"):                              # FanDuel alt ladders + totals (public JSON) fill lines Pinnacle doesn't post
            try:
                import _fanduel
                for (pl, st, ln), p in _fanduel.props(sp.lower()).items():
                    rows_ = by.setdefault((pl, st), [])
                    if not any(l == ln for l, _ in rows_):
                        rows_.append((ln, p))
            except Exception as e:
                print(sp, "fanduel fail:", e)
        apps = []
        try:
            apps += [dict(l, app="UD") for l in P.underdog(UD_SPORT[sp])]
        except Exception as e:
            print(sp, "UD fail:", e)
        try:
            apps += [dict(l, app="PP") for l in P.prizepicks(PP_LEAGUE[sp], max_age=1200)]
        except Exception as e:
            print(sp, "PP fail:", e)
        time.sleep(2)
        for l in apps:
            st = STAT.get(norm(l["stat"]))
            rows = by.get((norm(l["player"]), st)) if st else None
            if not rows:
                continue
            po = p_over_at(rows, l["line"], st)
            if po is None:
                continue
            kind = l.get("kind") or "standard"
            for side, p in (("over", po), ("under", 1 - po)):
                if l["app"] == "UD":
                    m = (l.get("mult") or {}).get(side)
                    if not m:
                        continue
                    be = (1 / 3.5 ** 0.5) / m
                else:
                    if kind in ("goblin", "demon") and side == "under":
                        continue
                    m = 1.0
                    be = 1 / 3.0 ** 0.5 if kind == "standard" else (0.75 if kind == "goblin" else 0.40)
                edge = p - be
                if edge >= 0.08:
                    fair = ("-%d" % round(100 * p / (1 - p))) if p >= 0.5 else "+%d" % round(100 * (1 - p) / p)
                    out.append(dict(sport=sp, app=l["app"], kind=kind, player=l["player"], stat=l["stat"], line=l["line"], side=side, p=round(p, 3),
                                    be=round(be, 3), edge=round(edge, 3), fair=fair, mult=m, start=l.get("start"),
                                    pin=sorted(rows)[:4], tag="MAIN" if kind == "standard" else "ALT GLITCH"))
    out.sort(key=lambda r: -r["edge"])
    json.dump(out, open(os.path.join("site", "mismatch.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print("%d mismatches (sharp side clears the app break-even by 8+ pts)" % len(out))
    for r in out[:40]:
        print("%-10s %-5s %-3s %-22s %-20s %-5s %-6s sharp %4.0f%% (fair %-5s) vs needs %3.0f%%  %s" % (
            r["tag"], r["sport"], r["app"], r["player"][:22], r["stat"][:20], r["side"], r["line"], 100 * r["p"], r["fair"], 100 * r["be"],
            (r["start"] or "")[:16]))


if __name__ == "__main__":
    main()
