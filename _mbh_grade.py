"""Grade MBH Bets' posted parlays leg by leg from FotMob results (2026-09-30)."""
import _soccer as S, datetime, json
def game(a, b, lo, hi):
    tid = S.find_team(a)
    t = S.get("%s/teams?id=%s" % (S.FM, tid))
    for x in ((t.get("fixtures") or {}).get("allFixtures") or {}).get("fixtures") or []:
        d = ((x.get("status") or {}).get("utcTime") or "")[:10]
        if lo <= d <= hi and S.norm(b)[:5] in S.norm((x.get("opponent") or {}).get("name")):
            m = S.match(x["id"], need_team=True)
            ids = [tm["id"] for tm in m["teams"]]; g = m["teamStats"].get("goals")
            i = ids.index(tid)
            return dict(me=g[i], opp=g[1 - i], mid=x["id"], ps=m.get("playerStats", {}), fin=m.get("finished"))
    return None
def sot(res, name):
    for pid, p in res["ps"].items():
        if S.norm(p.get("name")) == S.norm(name) or S.norm(name.split()[-1]) in S.norm(p.get("name")):
            v = S.fval(p.get("stats") or [], "Shots on target"); return 0 if v is None else v
    return None
def leg(kind, a, b, lo, hi, extra=None):
    r = game(a, b, lo, hi)
    if not r or not r["fin"]: return None, "no result"
    me, op = r["me"], r["opp"]; tot = me + op
    ok = {"ml": me > op, "dc": me >= op, "btts": me > 0 and op > 0, "o15": tot > 1.5, "o25": tot > 2.5,
          "team_o15": me > 1.5, "sot": (sot(r, extra) or 0) >= 1 if extra else None}[kind]
    return ok, "%s %d-%d %s" % (a, me, op, b) + (" | %s SOT %s" % (extra, sot(r, extra)) if extra else "")
P = {
 "Tony 12-leg 115x ($500 -> $57,618) 9/24": [("btts","Netherlands","Germany"),("ml","Norway","Denmark"),("o15","Serbia","Greece"),
   ("dc","Spain","England"),("o15","Spain","England"),("ml","France","Turkiye"),("dc","Croatia","Czech"),("sot","Croatia","Czech","Martin Baturina"),
   ("team_o15","Netherlands","Serbia"),("ml","Germany","Greece"),("o25","Germany","Greece"),("btts","Norway","Portugal")],
 "Cesar 8-leg 20x ($1,000 -> $20,376) 9/24": [("btts","Netherlands","Germany"),("dc","Norway","Denmark"),("btts","Italy","Belgium"),
   ("ml","France","Turkiye"),("dc","Croatia","Czech"),("ml","Netherlands","Serbia"),("btts","Norway","Portugal"),("o25","Germany","Greece")],
}
out = {}
for name, legs in P.items():
    print("\n" + name); hits = 0; n = 0
    for L in legs:
        ok, txt = leg(L[0], L[1], L[2], "2026-09-24", "2026-09-30", L[3] if len(L) > 3 else None)
        n += ok is not None; hits += bool(ok)
        print("   %-4s %-9s %s" % ({True: "WIN", False: "LOSS", None: "?"}[ok], L[0], txt))
    print("   -> %d of %d legs hit" % (hits, n))
