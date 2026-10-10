"""Idea tests on the same out-of-sample picks (2026-10-07, user: "keep thinking of things to add").
  A) slip size: 2-pick power 3x vs 3-pick power 5x vs 4-pick power 10x (PrizePicks power payouts)
  B) NHL capped at 4/day + WNBA 4+ reasons ranked first
  C) same-team legs: do they win/lose together (correlation) ?"""
import json, datetime, collections, itertools, random
import _dir_search as D
CT = datetime.timezone(datetime.timedelta(hours=-5))
lo = D.lodo_out(D.graded())


def pool(nhl_cap=6, wnba_first=False):
    P = []
    for r in lo:
        side = "over" if r["p"] >= .5 else "under"; conf = max(r["p"], 1 - r["p"]); sg = 1 if side == "over" else -1
        v = D.votes(r); ag = sum(1 for x in v if x == sg); an = sum(1 for x in v if x == -sg)
        if (r["sport"], side) in D.OFFER and conf >= .55 and ag >= 3 and an == 0:
            pri = conf + (0.2 if (wnba_first and r["sport"] == "WNBA" and ag >= 4) else 0)
            P.append(dict(day=r["date"], sport=r["sport"], team=r["team"], game=frozenset((r["team"], r["opp"])), who=r["player"], pri=pri,
                          win=r["over"] == (side == "over")))
    cs = {}
    for l in open("cs2_priced_all.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if r.get("result") in ("W", "L") and r.get("actual") is not None:
            cs[(r["match_id"], r["player"], r["stat"], r["maps"], r["line"])] = r
    for r in cs.values():
        if r["line"] >= (30.5 if r["kind"] == "k" else 16.5) and r["model_mu"] < .95 * r["line"] and r["actual"] != r["line"]:
            day = datetime.datetime.fromisoformat(r["start"].replace("Z", "+00:00")).astimezone(CT).date().isoformat()
            P.append(dict(day=day, sport="CS2", team=r["team"], game=frozenset((r["team"], r["opp"])), who=r["player"],
                          pri=.62 + (.05 if (r.get("map_winp") or 1) < .45 else 0), win=r["actual"] < r["line"]))
    out = []
    for day in sorted({p["day"] for p in P}):
        seen = set(); cnt = collections.Counter()
        for p in sorted([p for p in P if p["day"] == day], key=lambda p: -p["pri"]):
            cap = nhl_cap if p["sport"] == "NHL" else 6
            if p["who"] in seen or cnt[p["sport"]] >= cap:
                continue
            seen.add(p["who"]); cnt[p["sport"]] += 1; out.append(p)
    return out


PAY = {2: 3.0, 3: 6.0, 4: 10.0}          # 10/7 user: his PrizePicks 3-pick power pays 6x


def sim(P, k=2, start=10.0, pct=.05, frm="2026-09-17"):
    roll = start; lows = start
    for day in sorted({p["day"] for p in P if p["day"] >= frm}):
        S = [p for p in P if p["day"] == day]; used = set(); slips = []
        for i, a in enumerate(S):
            if i in used:
                continue
            grp = [i]
            for j in range(i + 1, len(S)):
                if j not in used and all(S[j]["game"] != S[g]["game"] for g in grp):
                    grp.append(j)
                if len(grp) == k:
                    break
            if len(grp) == k:
                slips.append([S[g] for g in grp]); used |= set(grp)
        stake = max(1.0, round(pct * roll, 2))
        for s in slips:
            if roll < stake:
                break
            roll += stake * (PAY[k] - 1) if all(x["win"] for x in s) else -stake
            lows = min(lows, roll)
    return roll, lows


P = pool()
print("A) SLIP SIZE (same picks, NHL+WNBA+CS2, 9/17-10/7, $10, 5%/slip min $1)")
for k in (2, 3, 4):
    end, low = sim(P, k); print("   %d-pick power %4.0fx: END $%6.2f   lowest $%.2f" % (k, PAY[k], end, low))
print("\nB) NHL CAP / WNBA FIRST (2-picks)")
for cap, wf in ((6, False), (4, False), (4, True), (3, True), (2, True)):
    Q = pool(cap, wf); w = sum(p["win"] for p in Q)
    end, low = sim(Q, 2); print("   NHL cap %d, WNBA 4+ first=%-5s legs %d-%d (%.1f%%)  END $%6.2f  low $%.2f" % (cap, wf, w, len(Q) - w, 100 * w / len(Q), end, low))
print("\nC) SAME-TEAM CORRELATION (pairs of legs from the same team, same day)")
same, diff = [], []
for day in {p["day"] for p in P}:
    S = [p for p in P if p["day"] == day]
    for a, b in itertools.combinations(S, 2):
        (same if a["team"] == b["team"] else diff).append(a["win"] == b["win"])
for lab, X in (("same team", same), ("different teams", diff)):
    print("   %-16s pairs %5d   both-same-result %.1f%%" % (lab, len(X), 100 * sum(X) / max(len(X), 1)))

print("\nD) PAIR SAME-TEAM LEGS ON PURPOSE (correlated power slips) vs never same game")
def sim_pairing(P, k=2, same=True, start=10.0, pct=.05, frm="2026-09-17"):
    roll = start; low = start; nw = ns = 0
    for day in sorted({p["day"] for p in P if p["day"] >= frm}):
        S = [p for p in P if p["day"] == day]; used = set(); slips = []
        if same:
            byteam = collections.defaultdict(list)
            for i, p in enumerate(S): byteam[(p["sport"], p["team"])].append(i)
            for t, idx in byteam.items():
                while len([i for i in idx if i not in used]) >= k:
                    g = [i for i in idx if i not in used][:k]; slips.append([S[i] for i in g]); used |= set(g)
        for i, a in enumerate(S):
            if i in used: continue
            grp = [i]
            for j in range(i + 1, len(S)):
                if j not in used and all(S[j]["game"] != S[g]["game"] for g in grp): grp.append(j)
                if len(grp) == k: break
            if len(grp) == k: slips.append([S[g] for g in grp]); used |= set(grp)
        stake = max(1.0, round(pct * roll, 2))
        for s in slips:
            if roll < stake: break
            win = all(x["win"] for x in s); nw += win; ns += 1
            roll += stake * (PAY[k] - 1) if win else -stake; low = min(low, roll)
    return roll, low, nw, ns
Q = pool(4, True)
for k in (2, 3):
    for same in (False, True):
        e, l, w, n = sim_pairing(Q, k, same)
        print("   %d-pick  same-team first=%-5s slips %d/%d (%.1f%%)  END $%6.2f  low $%.2f" % (k, same, w, n, 100 * w / n, e, l))

print("\nE) LEGAL CORRELATED 3-PICK: same-team pair + 1 leg from another game (PP needs 2+ teams)")
def sim_duo3(P, start=10.0, pct=.05, frm="2026-09-17"):
    roll = start; low = start; nw = ns = 0
    for day in sorted({p["day"] for p in P if p["day"] >= frm}):
        S = [p for p in P if p["day"] == day]; used = set(); slips = []
        byteam = collections.defaultdict(list)
        for i, p in enumerate(S): byteam[(p["sport"], p["team"])].append(i)
        duos = []
        for t, idx in byteam.items():
            while len([i for i in idx if i not in used]) >= 2:
                g = [i for i in idx if i not in used][:2]; duos.append(g); used |= set(g)
        for g in duos:
            third = next((j for j in range(len(S)) if j not in used and S[j]["game"] != S[g[0]]["game"]), None)
            if third is None: used -= set(g); continue
            slips.append([S[g[0]], S[g[1]], S[third]]); used.add(third)
        rest = [i for i in range(len(S)) if i not in used]
        while len(rest) >= 3:                                   # leftovers: normal 3-pick, all different games
            a = rest.pop(0); grp = [a]
            for j in list(rest):
                if all(S[j]["game"] != S[x]["game"] for x in grp): grp.append(j); rest.remove(j)
                if len(grp) == 3: break
            if len(grp) == 3: slips.append([S[x] for x in grp])
        stake = max(1.0, round(pct * roll, 2))
        for s in slips:
            if roll < stake: break
            win = all(x["win"] for x in s); nw += win; ns += 1
            roll += stake * (PAY[3] - 1) if win else -stake; low = min(low, roll)
    return roll, low, nw, ns
e, l, w, n = sim_duo3(Q)
print("   duo+1 3-pick (6x): slips %d/%d (%.1f%%)  END $%.2f  low $%.2f" % (w, n, 100 * w / n, e, l))
