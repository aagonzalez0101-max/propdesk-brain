"""GOBLIN PAIR FINDER (2026-10-09, user: "$45 full bankroll mode -- goblin 1.8x or 2x? you can see the board, search it").
Every PrizePicks GOBLIN line (more-only) priced at its exact number by the sharp books: Pinnacle props (NFL/NHL/WNBA/MLB/CFB/NBA)
+ FanDuel alt ladders (NFL/CFB), moved to PP's number with the same Poisson/normal step as _mismatch.py.
Rule (measured 10/7-10/9): a goblin pair at ~1.8x needs 74.5% per leg; average goblins hit 63% (-29%/slip); our own filter
~75% (break-even). Only sharp-priced >= 82% legs are bets -> pair them across different games.

    python _goblins.py            # every goblin >= 78% at the sharp books, BET tier >= 82%, plus suggested pairs
"""
import sys, datetime, itertools, json
import _props as P, _mismatch as M
KIND = sys.argv[1] if len(sys.argv) > 1 else "goblin"

CT = datetime.timezone(datetime.timedelta(hours=-5))
now = datetime.datetime.now(datetime.timezone.utc)
rows = []
for sp, pp_lg in M.PP_LEAGUE.items():
    srcs = {}
    try:
        for (pl, st, ln), p in P.pinnacle_props(M.PIN_LEAGUE[sp]).items():
            srcs.setdefault((pl, st), {}).setdefault("pinnacle", []).append((ln, p))
    except Exception as e:
        print(sp, "pinnacle:", e)
    if sp in ("NFL", "CFB"):
        try:
            import _fanduel
            for (pl, st, ln), p in _fanduel.props(sp.lower()).items():
                srcs.setdefault((pl, st), {}).setdefault("fanduel", []).append((ln, p))
        except Exception as e:
            print(sp, "fanduel:", e)
    if not srcs:
        continue
    try:
        board = P.prizepicks(pp_lg, max_age=900)
    except Exception as e:
        print(sp, "pp:", e); continue
    for l in board:
        if l.get("kind") != KIND or "+" in (l.get("player") or ""):
            continue
        try:
            if datetime.datetime.fromisoformat(l["start"].replace("Z", "+00:00")) < now:
                continue
        except Exception:
            pass
        st = M.STAT.get(M.norm(l["stat"])) if hasattr(M, "norm") else M.STAT.get(l["stat"].lower().replace(" ", ""))
        S = srcs.get((P.norm(l["player"]) if hasattr(P, "norm") else l["player"].lower().replace(" ", ""), st)) if st else None
        if not S:
            continue
        ps = {}
        for name, R in S.items():
            po = M.p_over_at(R, l["line"], st)
            if po is not None:
                ps[name] = po
        if not ps:
            continue
        p = min(ps.values())                                          # conservative: the LOWER sharp estimate
        rows.append(dict(sport=sp, player=l["player"], team=l.get("team"), opp=l.get("opp"), stat=l["stat"], line=l["line"], p=p, src=ps,
                         start=l["start"], game=frozenset((l.get("team"), (l.get("opp") or "").split()[0]))))
rows.sort(key=lambda r: -r["p"])
print("PRIZEPICKS GOBLINS priced by the sharp books (conservative = lower of Pinnacle/FanDuel)   BET >= 82%, pair needs 74.5%/leg at 1.8x")
for r in rows:
    if r["p"] >= .78:
        stt = datetime.datetime.fromisoformat(r["start"].replace("Z", "+00:00")).astimezone(CT).strftime("%a %I:%M%p")
        print("  %-4s %-4s %-24s %-4s %-22s O%-6s %5.1f%%  %-4s %s   %s" % (r["sport"], "BET" if r["p"] >= .82 else "", r["player"][:24], r["team"] or "",
              r["stat"][:22], r["line"], 100 * r["p"], "", " ".join("%s %.0f%%" % (k[:3], 100 * v) for k, v in r["src"].items()), stt))
bets = [r for r in rows if r["p"] >= .82]
pairs, used = [], set()
for a, b in itertools.combinations(bets, 2):
    if a["player"] in used or b["player"] in used or a["game"] & b["game"] or a["team"] == b["team"]:
        continue
    pairs.append((a, b)); used |= {a["player"], b["player"]}
print("\nSUGGESTED GOBLIN PAIRS (different games, highest first) -- value at 1.8x = p1*p2*1.8 - 1")
for a, b in pairs:
    print("  %s O%s %s  +  %s O%s %s   -> both %.0f%%, value %+.0f%% at 1.8x" % (a["player"], a["line"], a["stat"], b["player"], b["line"], b["stat"],
          100 * a["p"] * b["p"], 100 * (a["p"] * b["p"] * 1.8 - 1)))
json.dump([dict(r, game=list(r["game"])) for r in rows], open("_%s_today.json" % KIND, "w"), default=str)
