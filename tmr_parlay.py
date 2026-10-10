import sys, io, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from datetime import datetime, timedelta

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0"})
MLB = "https://statsapi.mlb.com/api/v1"
TOMORROW = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

def mlb(path, **params):
    r = S.get(f"{MLB}{path}", params=params, timeout=12)
    return r.json() if r.ok else {}

# ── Schedule + probable pitchers ────────────────────────────────────────────
sched = mlb("/schedule", sportId=1, date=TOMORROW,
            hydrate="probablePitcher,team,linescore,weather")
games = []
for d in sched.get("dates", []):
    games.extend(d.get("games", []))

# ── Team stats (hitting + pitching) ─────────────────────────────────────────
def team_stats():
    out = {}
    for grp in ("hitting", "pitching"):
        data = mlb("/teams/stats", stats="season", group=grp, sportId=1, season=2026)
        for e in data.get("stats",[{}])[0].get("splits",[]):
            tid = e["team"]["id"]
            if tid not in out: out[tid] = {}
            out[tid][grp] = e.get("stat", {})
    return out

# ── Pitcher last 5 starts ────────────────────────────────────────────────────
def last_starts(pid, n=5):
    if not pid: return []
    data = mlb(f"/people/{pid}/stats", stats="gameLog", group="pitching",
               sportId=1, season=2026)
    stat_list = data.get("stats",[])
    if not stat_list: return []
    splits = stat_list[0].get("splits",[])
    return splits[-n:]

# ── Standings ────────────────────────────────────────────────────────────────
def standings():
    data = mlb("/standings", leagueId="103,104", season=2026,
               standingsTypes="regularSeason")
    out = {}
    for rec in data.get("records", []):
        for e in rec.get("teamRecords", []):
            tid = e["team"]["id"]
            splits = e.get("records",{}).get("splitRecords",[])
            l10 = next((s for s in splits if s.get("type")=="lastTen"), {})
            out[tid] = {
                "w": e.get("wins",0), "l": e.get("losses",0),
                "pct": float(e.get("winningPercentage",0)),
                "rdiff": e.get("runDifferential",0),
                "streak": e.get("streak",{}).get("streakCode","-"),
                "l10w": int(l10.get("wins",5)),
                "l10": f"{l10.get('wins',0)}-{l10.get('losses',0)}",
                "rs": e.get("runsScored",0), "ra": e.get("runsAllowed",0),
            }
    return out

# ── Pitcher season line ───────────────────────────────────────────────────────
def sp_season(pid):
    if not pid: return {}
    data = mlb(f"/people/{pid}/stats", stats="season", group="pitching",
               sportId=1, season=2026)
    stat_list = data.get("stats",[])
    if not stat_list: return {}
    splits = stat_list[0].get("splits",[])
    return splits[0].get("stat",{}) if splits else {}

def sf(d, k, dv=99):
    try: return float(d.get(k) or dv)
    except: return float(dv)

def fmt_start(s):
    g    = s.get("game",{})
    date = g.get("officialDate","?")
    stat = s.get("stat",{})
    ip   = stat.get("inningsPitched","?")
    er   = stat.get("earnedRuns","?")
    h    = stat.get("hits","?")
    bb   = stat.get("baseOnBalls","?")
    k    = stat.get("strikeOuts","?")
    note = stat.get("note","")
    result = "W" if stat.get("wins",0) else ("L" if stat.get("losses",0) else "ND")
    return f"  {date}  {result}  {ip}IP  {er}ER  {h}H  {k}K  {bb}BB  {note}"

# ── Pull everything ───────────────────────────────────────────────────────────
tstats = team_stats()
stand  = standings()

print(f"=== MLB PARLAY BUILDER  {TOMORROW} ===")
print(f"Games: {len(games)}\n")

picks = []

for g in games:
    ht   = g["teams"]["home"]["team"]
    at   = g["teams"]["away"]["team"]
    hid, aid = ht["id"], at["id"]
    hname, aname = ht["name"], at["name"]
    gtime = g.get("gameDate","")[:16].replace("T"," ")

    h_sp = g["teams"]["home"].get("probablePitcher",{})
    a_sp = g["teams"]["away"].get("probablePitcher",{})
    h_sp_name = h_sp.get("fullName","TBD")
    a_sp_name = a_sp.get("fullName","TBD")
    h_pid = h_sp.get("id"); a_pid = a_sp.get("id")

    # Season stats
    hss = sp_season(h_pid); ass_ = sp_season(a_pid)
    h_era = sf(hss,"era"); a_era = sf(ass_,"era")
    h_whip = sf(hss,"whip"); a_whip = sf(ass_,"whip")
    h_k9 = sf(hss,"strikeoutsPer9Inn",0)
    a_k9 = sf(ass_,"strikeoutsPer9Inn",0)

    # Last 5 starts
    h_starts = last_starts(h_pid)
    a_starts = last_starts(a_pid)

    # Recent form: ERA over last 3 starts
    def recent_era(starts):
        if not starts: return 99.0
        recent = starts[-3:]
        total_er = sum(float(s["stat"].get("earnedRuns",0)) for s in recent)
        total_ip = sum(float(s["stat"].get("inningsPitched",0) or 0) for s in recent)
        return round((total_er / total_ip * 9), 2) if total_ip > 0 else 99.0

    h_recent_era = recent_era(h_starts)
    a_recent_era = recent_era(a_starts)

    # Team stats
    h_hit = tstats.get(hid,{}).get("hitting",{})
    a_hit = tstats.get(aid,{}).get("hitting",{})
    h_pit = tstats.get(hid,{}).get("pitching",{})
    a_pit = tstats.get(aid,{}).get("pitching",{})
    h_ops = sf(h_hit,"ops",0.700); a_ops = sf(a_hit,"ops",0.700)
    h_team_era = sf(h_pit,"era",4.5); a_team_era = sf(a_pit,"era",4.5)

    # Standings
    hs = stand.get(hid,{}); as_ = stand.get(aid,{})
    h_l10w = hs.get("l10w",5); a_l10w = as_.get("l10w",5)

    # SCORE
    score = 0
    reasons = []

    # SP ERA (season)
    if h_era < 99 and a_era < 99:
        if h_era < a_era - 1.5: score += 3; reasons.append(f"H SP era dominance {h_era:.2f} vs {a_era:.2f}")
        elif a_era < h_era - 1.5: score -= 3; reasons.append(f"A SP era dominance {a_era:.2f} vs {h_era:.2f}")
        elif h_era < a_era - 0.6: score += 2; reasons.append(f"H SP era edge {h_era:.2f} vs {a_era:.2f}")
        elif a_era < h_era - 0.6: score -= 2; reasons.append(f"A SP era edge {a_era:.2f} vs {h_era:.2f}")

    # SP recent form (last 3 starts ERA)
    if h_recent_era < 99 and a_recent_era < 99:
        if h_recent_era < a_recent_era - 1.5: score += 2; reasons.append(f"H SP HOT last 3 starts ERA {h_recent_era:.2f} vs {a_recent_era:.2f}")
        elif a_recent_era < h_recent_era - 1.5: score -= 2; reasons.append(f"A SP HOT last 3 starts ERA {a_recent_era:.2f} vs {h_recent_era:.2f}")

    # WHIP
    if h_whip < 99 and a_whip < 99:
        if h_whip < a_whip - 0.20: score += 1; reasons.append(f"H SP WHIP {h_whip:.2f} vs {a_whip:.2f}")
        elif a_whip < h_whip - 0.20: score -= 1; reasons.append(f"A SP WHIP {a_whip:.2f} vs {h_whip:.2f}")

    # Team OPS
    if h_ops > a_ops + 0.030: score += 1; reasons.append(f"H offense OPS {h_ops:.3f}")
    elif a_ops > h_ops + 0.030: score -= 1; reasons.append(f"A offense OPS {a_ops:.3f}")

    # Team ERA
    if h_team_era < a_team_era - 0.40: score += 1; reasons.append(f"H team ERA {h_team_era:.2f} vs {a_team_era:.2f}")
    elif a_team_era < h_team_era - 0.40: score -= 1; reasons.append(f"A team ERA {a_team_era:.2f} vs {h_team_era:.2f}")

    # Win%
    hp = hs.get("pct",0.5); ap = as_.get("pct",0.5)
    if hp > ap + 0.08: score += 1; reasons.append(f"H win% {hp:.3f}")
    elif ap > hp + 0.08: score -= 1; reasons.append(f"A win% {ap:.3f}")

    # L10 streak
    if h_l10w >= 7 and a_l10w <= 4: score += 2; reasons.append(f"H HOT {hs.get('l10','?')} L10 vs A COLD {as_.get('l10','?')}")
    elif a_l10w >= 7 and h_l10w <= 4: score -= 2; reasons.append(f"A HOT {as_.get('l10','?')} L10 vs H COLD {hs.get('l10','?')}")
    elif h_l10w >= 7: score += 1; reasons.append(f"H HOT {hs.get('l10','?')} L10")
    elif a_l10w >= 7: score -= 1; reasons.append(f"A HOT {as_.get('l10','?')} L10")

    # Run diff
    hr = hs.get("rdiff",0); ar = as_.get("rdiff",0)
    if hr > ar + 30: score += 1; reasons.append(f"H run diff {hr:+d} vs {ar:+d}")
    elif ar > hr + 30: score -= 1; reasons.append(f"A run diff {ar:+d} vs {hr:+d}")

    lean = "HOME" if score > 0 else ("AWAY" if score < 0 else "SKIP")
    pick_team = hname if score > 0 else (aname if score < 0 else "SKIP")

    picks.append({
        "gtime": gtime, "hname": hname, "aname": aname,
        "pick": pick_team, "lean": lean, "score": abs(score),
        "raw_score": score,
        "h_sp": h_sp_name, "a_sp": a_sp_name,
        "h_era": h_era, "a_era": a_era,
        "h_recent_era": h_recent_era, "a_recent_era": a_recent_era,
        "h_whip": h_whip, "a_whip": a_whip,
        "h_k9": h_k9, "a_k9": a_k9,
        "h_ops": h_ops, "a_ops": a_ops,
        "h_l10": hs.get("l10","?"), "a_l10": as_.get("l10","?"),
        "h_l10w": h_l10w, "a_l10w": a_l10w,
        "h_streak": hs.get("streak","-"), "a_streak": as_.get("streak","-"),
        "h_rdiff": hs.get("rdiff",0), "a_rdiff": as_.get("rdiff",0),
        "h_pct": hp, "a_pct": ap,
        "h_w": hs.get("w",0), "h_l": hs.get("l",0),
        "a_w": as_.get("w",0), "a_l": as_.get("l",0),
        "h_starts": h_starts, "a_starts": a_starts,
        "reasons": reasons,
    })

picks.sort(key=lambda x: x["score"], reverse=True)

# Print full breakdown
for p in picks:
    h_era_s = f"{p['h_era']:.2f}" if p['h_era'] < 99 else "TBD"
    a_era_s = f"{p['a_era']:.2f}" if p['a_era'] < 99 else "TBD"
    h_re = f"{p['h_recent_era']:.2f}" if p['h_recent_era'] < 99 else "-"
    a_re = f"{p['a_recent_era']:.2f}" if p['a_recent_era'] < 99 else "-"
    score_bar = "*" * p["score"]

    print(f"\n{'='*65}")
    print(f"  {p['aname']} @ {p['hname']}  |  {p['gtime']} UTC")
    print(f"  PICK: {p['pick']}  [{score_bar}] score {p['raw_score']:+d}")
    print()
    print(f"  PITCHER         ERA(season)  ERA(L3 starts)  WHIP   K/9")
    h_wh = f"{p['h_whip']:.2f}" if p['h_whip'] < 99 else "TBD"
    a_wh = f"{p['a_whip']:.2f}" if p['a_whip'] < 99 else "TBD"
    print(f"  H {p['h_sp'][:20]:20}  {h_era_s:5}        {h_re:5}           {h_wh:5}  {p['h_k9']:.1f}")
    print(f"  A {p['a_sp'][:20]:20}  {a_era_s:5}        {a_re:5}           {a_wh:5}  {p['a_k9']:.1f}")

    print(f"\n  RECORDS  W-L        PCT    L10      Streak  RunDiff  OPS")
    print(f"  H {p['hname'][:22]:22}  {p['h_w']}-{p['h_l']}  {p['h_pct']:.3f}  {p['h_l10']:5}  {p['h_streak']:>5}  {p['h_rdiff']:+4d}   {p['h_ops']:.3f}")
    print(f"  A {p['aname'][:22]:22}  {p['a_w']}-{p['a_l']}  {p['a_pct']:.3f}  {p['a_l10']:5}  {p['a_streak']:>5}  {p['a_rdiff']:+4d}   {p['a_ops']:.3f}")

    print(f"\n  WHY: {' / '.join(p['reasons'][:3]) if p['reasons'] else 'No edge'}")

    # Last 5 starts for the pitcher we like
    if p["lean"] == "HOME" and p["h_starts"]:
        print(f"\n  {p['h_sp']} last {len(p['h_starts'])} starts:")
        for s in p["h_starts"]: print(fmt_start(s))
    elif p["lean"] == "AWAY" and p["a_starts"]:
        print(f"\n  {p['a_sp']} last {len(p['a_starts'])} starts:")
        for s in p["a_starts"]: print(fmt_start(s))

# ── PARLAY BUILDER ────────────────────────────────────────────────────────────
print(f"\n{'='*65}")
print("  PARLAY BUILDER")
print(f"{'='*65}")

strong = [p for p in picks if p["score"] >= 4 and p["lean"] != "SKIP"]
medium = [p for p in picks if p["score"] == 3 and p["lean"] != "SKIP"]
soft   = [p for p in picks if p["score"] == 2 and p["lean"] != "SKIP"]

def approx_parlay(odds_list):
    # rough estimate assuming avg juice
    import math
    probs = []
    for o in odds_list:
        if o > 0: probs.append(100/(o+100))
        else: probs.append(-o/(-o+100))
    combined = 1
    for p in probs: combined *= p
    fair_ml = round(-combined/(1-combined)*100) if combined > 0.5 else round((1-combined)/combined*100)
    return combined, fair_ml

print("\n  FIRE PARLAY (4-leg, strongest plays):")
fire = (strong + medium)[:4]
for p in fire:
    print(f"    - {p['pick']} (score {p['raw_score']:+d})")

print("\n  SAFE PARLAY (3-leg):")
safe = (strong + medium)[:3]
for p in safe:
    print(f"    - {p['pick']} (score {p['raw_score']:+d})")

print("\n  SWING PARLAY (6-leg, all top plays):")
swing = (strong + medium + soft)[:6]
for p in swing:
    print(f"    - {p['pick']} (score {p['raw_score']:+d})")

print("\n  NOTE: Overs — look at high total games where both SPs have ERA > 4.5")
high_total = [p for p in picks if p['h_era'] > 4.5 and p['a_era'] > 4.5 and p['h_era'] < 99 and p['a_era'] < 99]
for p in high_total:
    print(f"    OVER candidate: {p['aname']} @ {p['hname']}  (H ERA {p['h_era']:.2f} / A ERA {p['a_era']:.2f})")
