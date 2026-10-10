import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import requests
from datetime import datetime, timedelta

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 SportsBettingResearch/1.0"})

MLB_API  = "https://statsapi.mlb.com/api/v1"
ODDS_KEY = __import__("os").getenv("ODDS_API_KEY", "")
ODDS_API = "https://api.the-odds-api.com/v4"

TOMORROW = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
print(f"Pulling MLB data for {TOMORROW}...\n")

def get_schedule(date):
    r = SESSION.get(f"{MLB_API}/schedule", params={
        "sportId": 1, "date": date,
        "hydrate": "probablePitcher(stats),team,linescore",
    }, timeout=15)
    r.raise_for_status()
    games = []
    for d in r.json().get("dates", []):
        games.extend(d.get("games", []))
    return games

def get_team_stats():
    stats = {}
    for group in ("hitting", "pitching"):
        r = SESSION.get(f"{MLB_API}/teams/stats", params={
            "stats": "season", "group": group, "sportId": 1, "season": 2026
        }, timeout=15)
        if r.status_code != 200:
            continue
        for entry in r.json().get("stats", [{}])[0].get("splits", []):
            tid  = entry.get("team", {}).get("id")
            name = entry.get("team", {}).get("name", "")
            s    = entry.get("stat", {})
            if tid not in stats:
                stats[tid] = {"name": name}
            stats[tid][group] = s
    return stats

def get_pitcher_stats(player_id):
    if not player_id:
        return {}
    r = SESSION.get(f"{MLB_API}/people/{player_id}/stats", params={
        "stats": "season", "group": "pitching", "sportId": 1, "season": 2026
    }, timeout=15)
    if r.status_code != 200:
        return {}
    stat_list = r.json().get("stats", [])
    if not stat_list:
        return {}
    splits = stat_list[0].get("splits", [])
    return splits[0].get("stat", {}) if splits else {}

def get_odds():
    r = SESSION.get(f"{ODDS_API}/sports/baseball_mlb/odds", params={
        "apiKey": ODDS_KEY, "regions": "us",
        "markets": "h2h,spreads,totals",
        "bookmakers": "draftkings,fanduel,betmgm,caesars,pinnacle",
        "oddsFormat": "american",
    }, timeout=15)
    r.raise_for_status()
    print(f"[Odds API] credits remaining: {r.headers.get('x-requests-remaining')}\n")
    return r.json()

def get_standings():
    r = SESSION.get(f"{MLB_API}/standings", params={
        "leagueId": "103,104", "season": 2026,
        "standingsTypes": "regularSeason"
    }, timeout=15)
    r.raise_for_status()
    records = {}
    for rec in r.json().get("records", []):
        for entry in rec.get("teamRecords", []):
            tid  = entry["team"]["id"]
            splits = entry.get("records", {}).get("splitRecords", [])
            last10 = next((s for s in splits if s.get("type") == "lastTen"), {})
            last25_wins = last10.get("wins", 5)  # approximate from last10
            records[tid] = {
                "name":     entry["team"]["name"],
                "wins":     entry.get("wins", 0),
                "losses":   entry.get("losses", 0),
                "pct":      float(entry.get("winningPercentage", 0)),
                "run_diff": entry.get("runDifferential", 0),
                "rs":       entry.get("runsScored", 0),
                "ra":       entry.get("runsAllowed", 0),
                "streak":   entry.get("streak", {}).get("streakCode", "-"),
                "last10":   last10,
            }
    return records

def fmt_ml(v):
    if v is None: return "N/A"
    return f"+{int(v)}" if v >= 0 else str(int(v))

def to_prob(ml):
    if ml is None: return 0.5
    return 100/(ml+100) if ml > 0 else -ml/(-ml+100)

def extract_ml(game_odds, team_name):
    by_book = {}
    for bk in game_odds.get("bookmakers", []):
        for mkt in bk.get("markets", []):
            if mkt["key"] != "h2h": continue
            for out in mkt["outcomes"]:
                if out["name"] == team_name:
                    by_book[bk["key"]] = out.get("price")
    return by_book

def extract_spread(game_odds, team_name):
    spreads = {}
    for bk in game_odds.get("bookmakers", []):
        for mkt in bk.get("markets", []):
            if mkt["key"] != "spreads": continue
            for out in mkt["outcomes"]:
                if out["name"] == team_name and out.get("point") is not None:
                    spreads[bk["key"]] = out["point"]
    return spreads

def extract_total(game_odds):
    totals = []
    for bk in game_odds.get("bookmakers", []):
        for mkt in bk.get("markets", []):
            if mkt["key"] != "totals": continue
            for out in mkt["outcomes"]:
                if out["name"] == "Over" and out.get("point"):
                    totals.append(out["point"])
    return round(sum(totals)/len(totals), 1) if totals else None

def sharp_analysis(home_ml_by_book, away_ml_by_book):
    signals = []
    pin_h = home_ml_by_book.get("pinnacle")
    pin_a = away_ml_by_book.get("pinnacle")
    sq_books = ["draftkings", "fanduel", "betmgm", "caesars"]

    sq_home = [home_ml_by_book[b] for b in sq_books if b in home_ml_by_book]
    sq_away = [away_ml_by_book[b] for b in sq_books if b in away_ml_by_book]

    avg_sq_home_prob = sum(to_prob(v) for v in sq_home) / len(sq_home) if sq_home else None
    avg_sq_away_prob = sum(to_prob(v) for v in sq_away) / len(sq_away) if sq_away else None

    if pin_h and avg_sq_home_prob:
        diff_h = (to_prob(pin_h) - avg_sq_home_prob) * 100
        if diff_h > 2.5:
            signals.append(f"SHARP ON HOME: Pinnacle has home {diff_h:+.1f}% higher than squares")
        elif diff_h < -2.5:
            signals.append(f"SHARP ON AWAY: Pinnacle has home {diff_h:+.1f}% vs squares (money on away)")

    # Book spread divergence
    return signals, pin_h, pin_a

# ============================================================
# PULL ALL DATA
# ============================================================
games_tmr  = get_schedule(TOMORROW)
team_stats = get_team_stats()
standings  = get_standings()
odds_data  = get_odds()

odds_lookup = {o["home_team"].lower(): o for o in odds_data}

print(f"Games tomorrow: {len(games_tmr)}")
print("="*70)
print(f"  MLB FULL SLATE ANALYSIS  {TOMORROW}")
print("="*70)

scored_games = []

for g in games_tmr:
    ht  = g["teams"]["home"]["team"]
    at  = g["teams"]["away"]["team"]
    hid = ht["id"]
    aid = at["id"]
    hname = ht["name"]
    aname = at["name"]
    gtime = g.get("gameDate","")[:16].replace("T"," ") + " UTC"
    venue = g.get("venue", {}).get("name", "")

    # Probable pitchers
    h_sp      = g["teams"]["home"].get("probablePitcher", {})
    a_sp      = g["teams"]["away"].get("probablePitcher", {})
    h_sp_name = h_sp.get("fullName", "TBD")
    a_sp_name = a_sp.get("fullName", "TBD")

    # Pitcher stats
    hps = get_pitcher_stats(h_sp.get("id"))
    aps = get_pitcher_stats(a_sp.get("id"))

    def safe_float(d, key, default=99):
        try: return float(d.get(key) or default)
        except: return float(default)

    h_era  = safe_float(hps, "era")
    a_era  = safe_float(aps, "era")
    h_whip = safe_float(hps, "whip")
    a_whip = safe_float(aps, "whip")
    h_kbb  = safe_float(hps, "strikeoutWalkRatio", 0)
    a_kbb  = safe_float(aps, "strikeoutWalkRatio", 0)
    h_k9   = safe_float(hps, "strikeoutsPer9Inn", 0)
    a_k9   = safe_float(aps, "strikeoutsPer9Inn", 0)
    h_hr9  = safe_float(hps, "homeRunsPer9", 0)
    a_hr9  = safe_float(aps, "homeRunsPer9", 0)
    h_fip  = safe_float(hps, "fielding", 0)

    # Team batting
    h_hit = team_stats.get(hid, {}).get("hitting", {})
    a_hit = team_stats.get(aid, {}).get("hitting", {})
    h_pit = team_stats.get(hid, {}).get("pitching", {})
    a_pit = team_stats.get(aid, {}).get("pitching", {})

    h_ops  = safe_float(h_hit, "ops", 0.700)
    a_ops  = safe_float(a_hit, "ops", 0.700)
    h_avg  = h_hit.get("avg", ".000")
    a_avg  = a_hit.get("avg", ".000")
    h_obp  = h_hit.get("obp", ".000")
    a_obp  = a_hit.get("obp", ".000")
    h_slg  = h_hit.get("slg", ".000")
    a_slg  = a_hit.get("slg", ".000")
    h_hr   = h_hit.get("homeRuns", 0)
    a_hr   = a_hit.get("homeRuns", 0)
    h_rbi  = h_hit.get("rbi", 0)
    a_rbi  = a_hit.get("rbi", 0)
    h_sb   = h_hit.get("stolenBases", 0)
    a_sb   = a_hit.get("stolenBases", 0)

    h_team_era  = safe_float(h_pit, "era", 4.50)
    a_team_era  = safe_float(a_pit, "era", 4.50)
    h_team_whip = safe_float(h_pit, "whip", 1.30)
    a_team_whip = safe_float(a_pit, "whip", 1.30)

    # Standings
    h_std = standings.get(hid, {})
    a_std = standings.get(aid, {})
    h_w   = h_std.get("wins", 0)
    h_l   = h_std.get("losses", 0)
    a_w   = a_std.get("wins", 0)
    a_l   = a_std.get("losses", 0)
    h_pct = h_std.get("pct", 0.5)
    a_pct = a_std.get("pct", 0.5)
    h_rdiff = h_std.get("run_diff", 0)
    a_rdiff = a_std.get("run_diff", 0)
    h_rs    = h_std.get("rs", 0)
    a_rs    = a_std.get("rs", 0)
    h_ra    = h_std.get("ra", 0)
    a_ra    = a_std.get("ra", 0)
    h_str   = h_std.get("streak", "-")
    a_str   = a_std.get("streak", "-")

    h_l10   = h_std.get("last10", {})
    a_l10   = a_std.get("last10", {})
    h_l10_s = f"{h_l10.get('wins',0)}-{h_l10.get('losses',0)}"
    a_l10_s = f"{a_l10.get('wins',0)}-{a_l10.get('losses',0)}"
    h_l10_w = int(h_l10.get("wins", 5))
    a_l10_w = int(a_l10.get("wins", 5))

    # Odds
    odds_game = odds_lookup.get(hname.lower())
    h_ml_bk = extract_ml(odds_game, hname) if odds_game else {}
    a_ml_bk = extract_ml(odds_game, aname) if odds_game else {}
    h_spd_bk = extract_spread(odds_game, hname) if odds_game else {}
    o_u = extract_total(odds_game) if odds_game else None

    best_h_ml = max(h_ml_bk.values()) if h_ml_bk else None
    best_a_ml = max(a_ml_bk.values()) if a_ml_bk else None
    best_h_book = max(h_ml_bk, key=h_ml_bk.get) if h_ml_bk else ""
    best_a_book = max(a_ml_bk, key=a_ml_bk.get) if a_ml_bk else ""

    sharp_sigs, pin_h, pin_a = sharp_analysis(h_ml_bk, a_ml_bk)

    # ============================================================
    # SCORE THE GAME
    # ============================================================
    score = 0
    notes = []

    # SP ERA matchup
    if h_era < 99 and a_era < 99:
        if h_era < 3.20 and a_era > 4.20:
            score += 3; notes.append(f"Home SP dominant ERA {h_era:.2f} vs away {a_era:.2f}")
        elif a_era < 3.20 and h_era > 4.20:
            score -= 3; notes.append(f"Away SP dominant ERA {a_era:.2f} vs home {h_era:.2f}")
        elif h_era < a_era - 0.80:
            score += 2; notes.append(f"Home SP ERA edge {h_era:.2f} vs {a_era:.2f}")
        elif a_era < h_era - 0.80:
            score -= 2; notes.append(f"Away SP ERA edge {a_era:.2f} vs {h_era:.2f}")
        elif h_era < a_era - 0.30:
            score += 1; notes.append(f"Home SP slight ERA edge {h_era:.2f} vs {a_era:.2f}")
        elif a_era < h_era - 0.30:
            score -= 1; notes.append(f"Away SP slight ERA edge {a_era:.2f} vs {h_era:.2f}")

    # WHIP
    if h_whip < 99 and a_whip < 99:
        if h_whip < a_whip - 0.15:
            score += 1; notes.append(f"Home SP WHIP {h_whip:.2f} vs {a_whip:.2f}")
        elif a_whip < h_whip - 0.15:
            score -= 1; notes.append(f"Away SP WHIP {a_whip:.2f} vs {h_whip:.2f}")

    # K/9
    if h_k9 > a_k9 + 1.5:
        score += 1; notes.append(f"Home SP strikeout rate {h_k9:.1f} K/9 vs {a_k9:.1f}")
    elif a_k9 > h_k9 + 1.5:
        score -= 1; notes.append(f"Away SP strikeout rate {a_k9:.1f} K/9 vs {h_k9:.1f}")

    # HR/9 (bad for pitcher = good for opposing offense)
    if h_hr9 > a_hr9 + 0.5 and a_hr9 < 1.2:
        score -= 1; notes.append(f"Home SP HR-prone ({h_hr9:.2f} HR/9)")
    elif a_hr9 > h_hr9 + 0.5 and h_hr9 < 1.2:
        score += 1; notes.append(f"Away SP HR-prone ({a_hr9:.2f} HR/9)")

    # Team OPS (offensive strength)
    if h_ops > a_ops + 0.025:
        score += 1; notes.append(f"Home offense OPS {h_ops:.3f} vs {a_ops:.3f}")
    elif a_ops > h_ops + 0.025:
        score -= 1; notes.append(f"Away offense OPS {a_ops:.3f} vs {h_ops:.3f}")

    # Team ERA (full pen + rotation)
    if h_team_era < a_team_era - 0.35:
        score += 1; notes.append(f"Home team ERA {h_team_era:.2f} vs {a_team_era:.2f} (pen+rotation)")
    elif a_team_era < h_team_era - 0.35:
        score -= 1; notes.append(f"Away team ERA {a_team_era:.2f} vs {h_team_era:.2f} (pen+rotation)")

    # Win% overall
    if h_pct > a_pct + 0.060:
        score += 1; notes.append(f"Home win% {h_pct:.3f} vs {a_pct:.3f}")
    elif a_pct > h_pct + 0.060:
        score -= 1; notes.append(f"Away win% {a_pct:.3f} vs {h_pct:.3f}")

    # Run differential
    if h_rdiff > a_rdiff + 20:
        score += 1; notes.append(f"Home run diff {h_rdiff:+d} vs {a_rdiff:+d}")
    elif a_rdiff > h_rdiff + 20:
        score -= 1; notes.append(f"Away run diff {a_rdiff:+d} vs {h_rdiff:+d}")

    # Last-10 hot/cold
    if h_l10_w >= 7 and a_l10_w <= 3:
        score += 3; notes.append(f"Home HOT ({h_l10_s} L10) AWAY COLD ({a_l10_s} L10)")
    elif a_l10_w >= 7 and h_l10_w <= 3:
        score -= 3; notes.append(f"Away HOT ({a_l10_s} L10) HOME COLD ({h_l10_s} L10)")
    elif h_l10_w >= 7:
        score += 2; notes.append(f"Home HOT last-10: {h_l10_s}")
    elif a_l10_w >= 7:
        score -= 2; notes.append(f"Away HOT last-10: {a_l10_s}")
    elif h_l10_w >= 6:
        score += 1; notes.append(f"Home solid last-10: {h_l10_s}")
    elif a_l10_w >= 6:
        score -= 1; notes.append(f"Away solid last-10: {a_l10_s}")

    # Sharp signals
    for sig in sharp_sigs:
        if "HOME" in sig:
            score += 2; notes.append(f"*** SHARP SIGNAL: {sig}")
        else:
            score -= 2; notes.append(f"*** SHARP SIGNAL: {sig}")

    # Determine recommendation
    if score >= 5:    lean = "STRONG BET HOME"
    elif score >= 3:  lean = "LEAN HOME"
    elif score >= 1:  lean = "SLIGHT HOME"
    elif score <= -5: lean = "STRONG BET AWAY"
    elif score <= -3: lean = "LEAN AWAY"
    elif score <= -1: lean = "SLIGHT AWAY"
    else:             lean = "SKIP / NEUTRAL"

    scored_games.append(dict(
        gtime=gtime, venue=venue,
        hname=hname, aname=aname,
        h_sp_name=h_sp_name, a_sp_name=a_sp_name,
        h_era=h_era, a_era=a_era,
        h_whip=h_whip, a_whip=a_whip,
        h_k9=h_k9, a_k9=a_k9,
        h_kbb=h_kbb, a_kbb=a_kbb,
        h_hr9=h_hr9, a_hr9=a_hr9,
        h_ip=hps.get("inningsPitched","?"), a_ip=aps.get("inningsPitched","?"),
        h_gs=hps.get("gamesStarted","?"), a_gs=aps.get("gamesStarted","?"),
        h_k=hps.get("strikeOuts","?"), a_k=aps.get("strikeOuts","?"),
        h_bb=hps.get("baseOnBalls","?"), a_bb=aps.get("baseOnBalls","?"),
        h_avg=h_avg, a_avg=a_avg,
        h_obp=h_obp, a_obp=a_obp,
        h_slg=h_slg, a_slg=a_slg,
        h_ops=h_ops, a_ops=a_ops,
        h_hr=h_hr, a_hr=a_hr,
        h_rbi=h_rbi, a_rbi=a_rbi,
        h_sb=h_sb, a_sb=a_sb,
        h_team_era=h_team_era, a_team_era=a_team_era,
        h_team_whip=h_team_whip, a_team_whip=a_team_whip,
        h_w=h_w, h_l=h_l, a_w=a_w, a_l=a_l,
        h_pct=h_pct, a_pct=a_pct,
        h_rdiff=h_rdiff, a_rdiff=a_rdiff,
        h_rs=h_rs, a_rs=a_rs, h_ra=h_ra, a_ra=a_ra,
        h_str=h_str, a_str=a_str,
        h_l10_s=h_l10_s, a_l10_s=a_l10_s,
        h_l10_w=h_l10_w, a_l10_w=a_l10_w,
        best_h_ml=best_h_ml, best_a_ml=best_a_ml,
        best_h_book=best_h_book, best_a_book=best_a_book,
        h_ml_bk=h_ml_bk, a_ml_bk=a_ml_bk,
        h_spd_bk=h_spd_bk,
        pin_h=pin_h, pin_a=pin_a,
        o_u=o_u,
        score=score, lean=lean, notes=notes,
        sharp_sigs=sharp_sigs,
    ))

scored_games.sort(key=lambda x: abs(x["score"]), reverse=True)

# ============================================================
# PRINT
# ============================================================
for i, g in enumerate(scored_games, 1):
    h_era_s  = f"{g['h_era']:.2f}" if g['h_era'] < 99 else "TBD"
    a_era_s  = f"{g['a_era']:.2f}" if g['a_era'] < 99 else "TBD"
    h_whip_s = f"{g['h_whip']:.2f}" if g['h_whip'] < 99 else "TBD"
    a_whip_s = f"{g['a_whip']:.2f}" if g['a_whip'] < 99 else "TBD"

    print()
    print("-"*70)
    print(f" #{i}  {g['aname']}  @  {g['hname']}")
    print(f"     {g['gtime']}  |  {g['venue']}")
    print(f"     VERDICT: {g['lean']}  (score: {g['score']:+d})")
    print()

    # Odds
    dkh = fmt_ml(g['h_ml_bk'].get('draftkings'))
    dka = fmt_ml(g['a_ml_bk'].get('draftkings'))
    fdh = fmt_ml(g['h_ml_bk'].get('fanduel'))
    fda = fmt_ml(g['a_ml_bk'].get('fanduel'))
    pinh = fmt_ml(g['pin_h'])
    pina = fmt_ml(g['pin_a'])
    spd  = list(g['h_spd_bk'].values())[0] if g['h_spd_bk'] else "N/A"

    print(f"  ODDS      Home {g['hname'][:20]}   Away {g['aname'][:20]}")
    print(f"  DraftKings   {dkh:>7}               {dka:>7}")
    print(f"  FanDuel      {fdh:>7}               {fda:>7}")
    print(f"  Pinnacle     {pinh:>7}               {pina:>7}   <-- sharp book")
    print(f"  Best avail   {fmt_ml(g['best_h_ml']):>7} ({g['best_h_book']})      {fmt_ml(g['best_a_ml']):>7} ({g['best_a_book']})")
    print(f"  Spread (home): {spd}   |   O/U: {g['o_u']}")

    print()
    print(f"  RECORDS   W    L    PCT    L10      Streak  RunDiff  RS/RA")
    print(f"  Home  {g['hname'][:22]}  {g['h_w']}-{g['h_l']}  {g['h_pct']:.3f}  {g['h_l10_s']}  {g['h_str']:>5}  {g['h_rdiff']:+4d}  {g['h_rs']}/{g['h_ra']}")
    print(f"  Away  {g['aname'][:22]}  {g['a_w']}-{g['a_l']}  {g['a_pct']:.3f}  {g['a_l10_s']}  {g['a_str']:>5}  {g['a_rdiff']:+4d}  {g['a_rs']}/{g['a_ra']}")

    print()
    print(f"  PITCHING MATCHUP")
    print(f"  {'':6}  {'Pitcher':22}  ERA    WHIP   K/9   K/BB  HR/9  GS   IP    K    BB")
    print(f"  Home   {g['h_sp_name']:22}  {h_era_s:5}  {h_whip_s:5}  {g['h_k9']:.1f}   {g['h_kbb']:.2f}  {g['h_hr9']:.2f}  {g['h_gs']:<4} {g['h_ip']:<5} {g['h_k']:<4} {g['h_bb']}")
    print(f"  Away   {g['a_sp_name']:22}  {a_era_s:5}  {a_whip_s:5}  {g['a_k9']:.1f}   {g['a_kbb']:.2f}  {g['a_hr9']:.2f}  {g['a_gs']:<4} {g['a_ip']:<5} {g['a_k']:<4} {g['a_bb']}")
    print(f"  Pen+Rotation ERA:  Home {g['h_team_era']:.2f}  /  Away {g['a_team_era']:.2f}")
    print(f"  Pen+Rotation WHIP: Home {g['h_team_whip']:.2f}  /  Away {g['a_team_whip']:.2f}")

    print()
    print(f"  BATTING   {'Team':25}  AVG    OBP    SLG    OPS    HR   RBI  SB")
    print(f"  Home  {g['hname'][:25]}  {g['h_avg']}  {g['h_obp']}  {g['h_slg']}  {g['h_ops']:.3f}  {g['h_hr']:<4} {g['h_rbi']:<4} {g['h_sb']}")
    print(f"  Away  {g['aname'][:25]}  {g['a_avg']}  {g['a_obp']}  {g['a_slg']}  {g['a_ops']:.3f}  {g['a_hr']:<4} {g['a_rbi']:<4} {g['a_sb']}")

    print()
    print(f"  ANALYSIS BREAKDOWN:")
    for n in g["notes"]:
        flag = ">>>" if "SHARP" in n else "  -"
        print(f"    {flag} {n}")
    if not g["notes"]:
        print("    - No strong edges. Skip.")

print()
print("="*70)
print("  BEST BETS SUMMARY  (score >= 3)")
print("="*70)
top = [g for g in scored_games if abs(g["score"]) >= 3]
if top:
    for g in top:
        is_home  = g["score"] > 0
        team     = g["hname"] if is_home else g["aname"]
        ml       = fmt_ml(g["best_h_ml"] if is_home else g["best_a_ml"])
        book     = g["best_h_book"] if is_home else g["best_a_book"]
        has_sharp = any("SHARP" in n for n in g["notes"])
        s_tag    = "  <<< SHARP MONEY" if has_sharp else ""
        print(f"  BET: {team:30}  {ml:>7} @ {book}{s_tag}")
        print(f"       Score: {g['score']:+d}  |  {g['aname']} @ {g['hname']}")
        print()
else:
    print("  No games hit 3+ score. Soft leans only today.")
    for g in scored_games[:4]:
        is_home = g["score"] >= 0
        team = g["hname"] if is_home else g["aname"]
        ml = fmt_ml(g["best_h_ml"] if is_home else g["best_a_ml"])
        print(f"  LEAN: {team:30}  {ml}  (score {g['score']:+d})")

print()
print("  HOT TEAMS (L10 >= 7 wins):")
seen = set()
for g in scored_games:
    if g["h_l10_w"] >= 7 and g["hname"] not in seen:
        print(f"    HOT HOME: {g['hname']} ({g['h_l10_s']} L10, streak {g['h_str']})")
        seen.add(g["hname"])
    if g["a_l10_w"] >= 7 and g["aname"] not in seen:
        print(f"    HOT AWAY: {g['aname']} ({g['a_l10_s']} L10, streak {g['a_str']})")
        seen.add(g["aname"])

print()
print("  COLD TEAMS (L10 <= 3 wins):")
seen = set()
for g in scored_games:
    if g["h_l10_w"] <= 3 and g["hname"] not in seen:
        print(f"    COLD: {g['hname']} ({g['h_l10_s']} L10, streak {g['h_str']})")
        seen.add(g["hname"])
    if g["a_l10_w"] <= 3 and g["aname"] not in seen:
        print(f"    COLD: {g['aname']} ({g['a_l10_s']} L10, streak {g['a_str']})")
        seen.add(g["aname"])
