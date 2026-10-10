"""STANDARD + GOBLIN "2x" PAIRS (2026-10-09, user: "always choose the best MISPRICED standard with data from our model, then the
best goblin you decide -- that's how we get the 2x's").
  standard leg = our model's edge: today's direction-filter picks (direction_paper.jsonl, 3+ reasons, 0 against), the CS2 high-line
                 under filter, re-checked against the LIVE PrizePicks board (PP line first, then sharps; a sharp book that disagrees
                 by 5+ pts drops the leg)
  goblin leg   = the highest sharp-priced goblin (Pinnacle/FanDuel at PP's exact number) from a DIFFERENT game and team
  value        = p_std x p_gob x payout - 1; bet only if the app's payout >= 1 / (p_std x p_gob) + ~5% cushion.
    python _pair2x.py
"""
import json, datetime, os, subprocess, sys
import _props as P, _mismatch as M

try:                                                    # 10/10 user: everything in Texas time (Central, DST-aware)
    from zoneinfo import ZoneInfo
    CT = ZoneInfo("America/Chicago")
except Exception:
    CT = datetime.timezone(datetime.timedelta(hours=-5))
now = datetime.datetime.now(datetime.timezone.utc)
today = datetime.datetime.now(CT).date().isoformat()
LG = {"NHL": 8, "WNBA": 3, "NBA": 7, "NFL": 9, "CFB": 15, "CS2": 265}

# live PP standard board
live = {}
for sp, lg in LG.items():
    try:
        for l in P.prizepicks(lg, max_age=180):                      # 429s at max_age=0 -> a 3-minute-old board is fine
            if l.get("kind") == "standard" and "+" not in (l.get("player") or ""):
                live[(sp, M.norm(l["player"]), M.norm(l["stat"]))] = l
    except Exception as e:
        print(sp, "pp:", e)

# 10/9 user: "nobody that we've used" -> skip every player already in an OPEN bet in the ledger
USED = set()
for x in open("live_paper.jsonl", encoding="utf-8"):
    r = json.loads(x)
    if r.get("result") is None and r.get("kind") == "LIVE":
        for lg_ in r.get("legs") or []:
            if lg_.get("player"):
                USED.add(M.norm(lg_["player"]))
print("skipping players already in open bets:", len(USED))
std = []
if os.path.exists("direction_paper.jsonl"):
    for x in open("direction_paper.jsonl", encoding="utf-8"):
        r = json.loads(x)
        if r["date"] < today or r.get("result"):
            continue
        if M.norm(r["player"]) in USED:
            continue
        l = live.get((r["sport"], M.norm(r["player"]), M.norm(r["stat"])))
        if not l or l["line"] != r["line"] or datetime.datetime.fromisoformat(l["start"]).astimezone(datetime.timezone.utc) < now:
            continue                                                   # not on PP at this number right now -> not a leg
        fl = __import__("_arch").first_line(l["player"], l["stat"], l["start"][:10])
        raised = fl is not None and l["line"] > fl
        std.append(dict(sport=r["sport"], player=r["player"], team=r.get("team"), opp=r.get("opp"), stat=r["stat"], line=r["line"], side=r["side"],
                        p=r["p"], why="%d reasons: %s%s" % (r.get("agree", 3), r.get("why", ""), (" | PP RAISED %s->%s (paper: over 62%%)" % (fl, l["line"])) if raised else ""),
                        start=l["start"], img=l.get("img")))
# CS2: ONLY the measured rule (10/10 user: "I don't want off-the-books bets"). cs2_paper picks with model edge 3-9% (the band that hit
# 62% / 68.2% when the map is not a coin flip); bigger edges are the WORST legs (top-of-card 22-50%) and are never carded.
# The old "high-line under" shortcut (flat p=0.62, unmeasured) is gone -- it put 13-16% edge legs on the 10/10 card.
seen_cs = set()
if os.path.exists("cs2_paper.jsonl"):
    for x in open("cs2_paper.jsonl", encoding="utf-8"):
        r = json.loads(x)
        e = r.get("edge") or 0
        if not (0.03 <= e <= 0.09) or str(r.get("start", ""))[:10] < today or r.get("maps") != 2:
            continue
        if datetime.datetime.fromisoformat(r["start"].replace("Z", "+00:00")) < now or M.norm(r["player"]) in USED:
            continue
        stat = "MAPS 1-2 Headshots" if r.get("kind") == "hs" else "MAPS 1-2 Kills"
        l = live.get(("CS2", M.norm(r["player"]), M.norm(stat)))
        side = "over" if r.get("side") == "higher" else "under"
        if not l or (side == "over" and l["line"] > r["line"]) or (side == "under" and l["line"] < r["line"]):
            continue                                                   # PP number must be as good as the one the model priced
        k = (r["player"], stat)
        if k in seen_cs:
            continue
        seen_cs.add(k)
        coin = 0.45 <= (r.get("map_winp") or 0.5) <= 0.55
        std.append(dict(sport="CS2", player=r["player"], team=r.get("team"), opp=r.get("opp"), stat=stat, line=l["line"], side=side,
                        p=0.62 if coin else 0.68, why="CS2 rule: edge %.1f%%%s" % (100 * e, "" if coin else ", lopsided map (68% tier)"),
                        start=l["start"], img=l.get("img")))

# sharp check on the STANDARD leg: a Pinnacle/FanDuel price that disagrees with our side by 5+ pts drops it (Gauthier 10/9: 51%)
PINS = {}
for sp in ("NHL", "WNBA", "NBA", "NFL", "CFB"):
    try:
        for (pl, st, ln), pr in P.pinnacle_props(M.PIN_LEAGUE[sp]).items():
            PINS.setdefault((sp, pl, st), []).append((ln, pr))
    except Exception:
        pass
keep = []
for s_ in std:
    st = M.STAT.get(M.norm(s_["stat"])); R = PINS.get((s_["sport"], M.norm(s_["player"]), st)) if st else None
    po = M.p_over_at(R, s_["line"], st) if R else None
    if po is not None:
        sharp = po if s_["side"] == "over" else 1 - po
        s_["sharp"] = sharp
        if sharp < s_["p"] - 0.05 and sharp < 0.55:
            print("  dropped (sharp disagrees %.0f%%): %s %s %s" % (100 * sharp, s_["player"], s_["side"], s_["line"])); continue
    keep.append(s_)
std = keep
# goblins (fresh scan). 10/9 user: the goblin must be the tier ONE BELOW the standard line (the shallowest goblin) -- the deep tiers
# pay 1.2-1.3x and kill the 2x. Questionable/Doubtful NFL players are out.
if not os.environ.get("SKIP_GOBLINS"):                                  # goblins are promo-only now; skip the 10-25 min scan when in a hurry
    subprocess.run([sys.executable, "_goblins.py"], capture_output=True, timeout=1500, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
G = json.load(open("_goblins_today.json"))
top = {}
for g in G:
    k = (g["sport"], g["player"], g["stat"])
    if k not in top or g["line"] > top[k]["line"]:
        top[k] = g
try:
    import _nflscreen as N
    inj, _ = N.injuries()
except Exception:
    inj = {}
gob = [g for g in top.values() if M.norm(g["player"]) not in USED and g["p"] >= 0.72 and inj.get(g["player"]) not in ("Questionable", "Doubtful", "Out", "Injured Reserve")]
gob.sort(key=lambda g: -g["p"])

# 10/9 user rule: "our plays are OVERS and UNDERS" -- show both sides of the qualifying standard pool, never only one by default
_ov = sorted([x for x in std if x["side"] == "over"], key=lambda x: -x["p"]); _un = sorted([x for x in std if x["side"] == "under"], key=lambda x: -x["p"])
print("BOTH SIDES -- qualifying standard legs: %d OVER, %d UNDER" % (len(_ov), len(_un)))
for lab, X in (("OVERS", _ov), ("UNDERS", _un)):
    print("  %s:" % lab)
    for x in X[:8]:
        print("    PP: %-22s %-5s %-18s %-5s %-5s %.0f%%  (%s)" % (x["player"], x["team"] or "", x["stat"][:18], x["side"].upper(), x["line"], 100 * x["p"], x["why"][:55]))
    if not X:
        print("    none qualified today")
# sharp-priced standard OVERS (Pinnacle/FanDuel >= 58% at PP's number) -- the over hunt beyond our filter
try:
    _sb = json.load(open("_standard_today.json")) if os.path.exists("_standard_today.json") else []
    _so = sorted([r for r in _sb if min(r["src"].values()) >= .58], key=lambda r: -min(r["src"].values()))
    print("  sharp-priced standard OVERS >= 58%%: %d" % len(_so))
    for r in _so[:6]:
        print("    PP: %-22s %-5s %-18s OVER  %-5s sharp %.0f%%" % (r["player"], r["team"] or "", r["stat"][:18], r["line"], 100 * min(r["src"].values())))
except Exception as e:
    print("  sharp overs:", e)
print()
print("STANDARD (our model) + GOBLIN (sharp-priced) pairs -- the payout must clear the 'needs' column on your screen")
used = set(); n = 0; teams_used = set()
for s in sorted(std, key=lambda s: -s["p"]):
    if s["team"] in teams_used:
        continue                                # 10/8 lesson: 3 Carolina legs across 3 slips died in one 7-2 blowout -> 1 leg per team, all slips
    teams_used.add(s["team"])
    g = next((g for g in gob if g["player"] not in used and g["team"] not in (s["team"], s["opp"])
              and (g.get("opp") or "")[:3] not in ((s["team"] or "")[:3], (s["opp"] or "")[:3])), None)
    if not g:
        continue
    used.add(g["player"]); n += 1
    both = s["p"] * g["p"]
    ts = lambda x: datetime.datetime.fromisoformat(x.replace("Z", "+00:00")).astimezone(CT).strftime("%a %I:%M%p")
    print("\n  PAIR %d   both hit ~%.0f%%   needs >= %.2fx   value at 2.0x %+.0f%% / 2.2x %+.0f%%" % (n, 100 * both, 1.05 / both, 100 * (both * 2 - 1), 100 * (both * 2.2 - 1)))
    print("    STANDARD  PP: %-22s %-5s %-18s %-5s %-5s  model %.0f%%  (%s)  %s" % (s["player"], s["team"] or "", s["stat"][:18], s["side"].upper(),
          s["line"], 100 * s["p"], s["why"][:60], ts(s["start"])))
    print("    GOBLIN    PP: %-22s %-5s %-18s MORE  %-5s  sharp %.0f%%  (tier right below standard)  %s" % (g["player"], g["team"] or "", g["stat"][:18], g["line"], 100 * g["p"], ts(g["start"])))
    if float(s["line"]).is_integer():
        print("    !! standard line %s is a whole number in the feed -- your app may show %s; confirm" % (s["line"], s["line"] - 0.5))
if not n:
    print("  no standard leg from our filters is live on PP right now")

# 3-PICK POWER (6x) from the same standard pool: 1 leg per team across ALL slips, legs from 3 different games
pool, seen_t = [], set()
for s in sorted(std, key=lambda s: -s["p"]):
    if s["team"] not in seen_t:
        seen_t.add(s["team"]); pool.append(s)
print("\n3-PICK POWER 6x (needs 55%%/leg; 1 leg per team across all slips) -- %d eligible legs" % len(pool))
k = 0; slips_txt = []; slips = []
while len(pool) >= 3:
    a = pool.pop(0); grp = [a]
    for x in list(pool):
        if all({x["team"], x.get("opp")} != {g["team"], g.get("opp")} for g in grp):
            grp.append(x); pool.remove(x)
        if len(grp) == 3:
            break
    if len(grp) < 3:
        break
    k += 1; ph = grp[0]["p"] * grp[1]["p"] * grp[2]["p"]
    print("  SLIP %d   all three ~%.0f%%   value at 6x %+.0f%%" % (k, 100 * ph, 100 * (ph * 6 - 1)))
    for g in grp:
        print("    PP: %-22s %-5s %-18s %-5s %-5s  %.0f%%  (%s)" % (g["player"], g["team"] or "", g["stat"][:18], g["side"].upper(), g["line"], 100 * g["p"], g["why"][:50]))
    slips.append((k, grp, ph))
    slips_txt.append("**SLIP %d** · 3-pick 6x · all three ~%.0f%%\n" % (k, 100 * ph) + "\n".join(
        "%s **%s** %s %s · %.0f%% · %s" % ("🔺 HIGHER" if g["side"] == "over" else "🔻 LOWER", g["player"], g["stat"], g["line"], 100 * g["p"],
                                          datetime.datetime.fromisoformat(g["start"].replace("Z", "+00:00")).astimezone(CT).strftime("%a %I:%M %p"))
        for g in grp))

try:
    # 10/9: the card goes to Discord #card as rich cards (_cardpost.py): a header, then one message per slip with a card per leg
    import _cardpost as C
    feed = " || ".join(x.replace("\n", " | ") for x in slips_txt) or "no slip"
    with open(os.path.join("daily_log", "feed.txt"), "a", encoding="utf-8") as f_:
        f_.write("%s CARD: %s\n" % (datetime.datetime.now(CT).strftime("%m-%d %I:%M %p"), feed))
    side = lambda X: "\n".join("%s **%s** %s %g · %.0f%%" % ("🔺" if x["side"] == "over" else "🔻", x["player"], x["stat"], x["line"], 100 * x["p"])
                               for x in X[:6]) or "none qualified"
    rl = C.roll()
    C.post_embed("🧾 TODAY'S CARD · %s" % datetime.datetime.now(CT).strftime("%a %m/%d"),
                 "**%d slip%s** below%s.\n\n**🔺 OVERS that qualify (%d)**\n%s\n\n**🔻 UNDERS that qualify (%d)**\n%s"
                 % (len(slips), "" if len(slips) == 1 else "s", (" · roll $%.2f · stake $%.2f each" % (rl, 0.05 * rl)) if rl else "",
                    len(_ov), side(_ov), len(_un), side(_un)))
    for k_, grp_, ph_ in slips:
        C.post_slip(k_, grp_, ph_, stake=0.05 * rl if rl else None)
    if not slips:
        C.post_embed("🧾 No slip today", "No 3 legs from different teams pass the filter on the live board yet -- wait for more lines, never force a slip.")
except Exception as e:
    print("card post:", e)


# 10/10: refresh the cloud alert watch list (open bets + card legs) after every card build
try:
    subprocess.run([sys.executable, "_watchlist.py"], timeout=120)
except Exception as e:
    print("watchlist:", e)
