import sys, io, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0"})
ODDS_KEY = __import__("os").getenv("ODDS_API_KEY", "")
ODDS_API = "https://api.the-odds-api.com/v4"

def get_odds(sport):
    params = {
        "apiKey": ODDS_KEY, "regions": "us",
        "markets": "h2h",
        "bookmakers": "draftkings,fanduel,betmgm,pinnacle",
        "oddsFormat": "american",
    }
    r = S.get(f"{ODDS_API}/sports/{sport}/odds", params=params, timeout=15)
    print(f"[{sport}] credits remaining: {r.headers.get('x-requests-remaining')}")
    return r.json() if r.ok else []

def fmt(v):
    if v is None: return "N/A"
    return f"+{int(v)}" if v >= 0 else str(int(v))

def get_book_ml(game, team, book):
    for bk in game.get("bookmakers", []):
        if bk["key"] != book: continue
        for mkt in bk.get("markets", []):
            if mkt["key"] != "h2h": continue
            for out in mkt["outcomes"]:
                if out["name"] == team:
                    return out.get("price")
    return None

def to_prob(ml):
    if ml is None: return 0.5
    return 100/(ml+100) if ml > 0 else -ml/(-ml+100)

# Pull both ATP and WTA
atp = get_odds("tennis_atp_french_open")
wta = get_odds("tennis_wta_french_open")
all_games = [(g, "ATP") for g in atp] + [(g, "WTA") for g in wta]

print(f"\nATP matches: {len(atp)}")
print(f"WTA matches: {len(wta)}")
print(f"Total: {len(all_games)}\n")

print("="*70)
print("  FRENCH OPEN MATCHES + ODDS")
print("="*70)

picks = []

for game, tour in all_games:
    p1 = game["home_team"]
    p2 = game["away_team"]
    gtime = game.get("commence_time","")[:16].replace("T"," ")

    dk_p1   = get_book_ml(game, p1, "draftkings")
    dk_p2   = get_book_ml(game, p2, "draftkings")
    pin_p1  = get_book_ml(game, p1, "pinnacle")
    pin_p2  = get_book_ml(game, p2, "pinnacle")
    fd_p1   = get_book_ml(game, p1, "fanduel")
    fd_p2   = get_book_ml(game, p2, "fanduel")

    # best available price for each player
    all_p1 = [get_book_ml(game, p1, b) for b in ["draftkings","fanduel","betmgm","pinnacle"]]
    all_p2 = [get_book_ml(game, p2, b) for b in ["draftkings","fanduel","betmgm","pinnacle"]]
    best_p1 = max((v for v in all_p1 if v is not None), default=None)
    best_p2 = max((v for v in all_p2 if v is not None), default=None)

    # Sharp signal: Pinnacle vs DK
    sharp_note = ""
    if pin_p1 and dk_p1:
        diff = (to_prob(pin_p1) - to_prob(dk_p1)) * 100
        if diff > 2.5:
            sharp_note = f"SHARP on {p1} (Pinnacle {diff:+.1f}% vs DK)"
        elif diff < -2.5:
            sharp_note = f"SHARP on {p2} (Pinnacle {-diff:+.1f}% vs DK)"

    # Determine favorite
    fav = p1 if (dk_p1 or 0) < (dk_p2 or 0) else p2
    fav_ml = dk_p1 if fav == p1 else dk_p2
    dog_ml = dk_p2 if fav == p1 else dk_p1

    print(f"\n  [{tour}] {gtime}")
    print(f"  {p1:30} vs  {p2}")
    print(f"  DK:      {fmt(dk_p1):8}  {fmt(dk_p2)}")
    print(f"  FanDuel: {fmt(fd_p1):8}  {fmt(fd_p2)}")
    print(f"  Pinnacle:{fmt(pin_p1):8}  {fmt(pin_p2)}  <-- sharp")
    print(f"  Best:    {fmt(best_p1):8}  {fmt(best_p2)}")
    if sharp_note:
        print(f"  *** {sharp_note}")

    # Score for parlay selection
    # Heavy favorites on clay = reliable legs
    score = 0
    pick = None
    reason = ""

    if fav_ml and fav_ml < -200:
        score = 5; pick = fav; reason = f"Heavy fav {fmt(fav_ml)}"
    elif fav_ml and fav_ml < -150:
        score = 4; pick = fav; reason = f"Strong fav {fmt(fav_ml)}"
    elif fav_ml and fav_ml < -120:
        score = 3; pick = fav; reason = f"Moderate fav {fmt(fav_ml)}"
    elif fav_ml and fav_ml < -105:
        score = 2; pick = fav; reason = f"Slight fav {fmt(fav_ml)}"

    if sharp_note and pick and pick in sharp_note:
        score += 1; reason += " + SHARP"

    if pick:
        picks.append({
            "tour": tour, "gtime": gtime,
            "p1": p1, "p2": p2,
            "pick": pick,
            "dk_ml": fav_ml if pick == fav else dog_ml,
            "pin_ml": pin_p1 if pick == p1 else pin_p2,
            "best_ml": best_p1 if pick == p1 else best_p2,
            "score": score, "reason": reason,
            "sharp": sharp_note,
        })

picks.sort(key=lambda x: x["score"], reverse=True)

print(f"\n\n{'='*70}")
print("  PARLAY BUILDER — FRENCH OPEN")
print(f"{'='*70}")

print("\n  TOP PICKS BY CONFIDENCE:")
for i, p in enumerate(picks[:10], 1):
    sharp_tag = "  <<< SHARP" if p["sharp"] else ""
    print(f"  {i}. [{p['tour']}] {p['pick']:30} {fmt(p['dk_ml']):7} DK  |  {fmt(p['pin_ml']):7} Pinnacle  ({p['reason']}){sharp_tag}")

print(f"\n{'='*70}")
print("  SUGGESTED 6-LEG PARLAY (top 6 most reliable)")
print(f"{'='*70}")
top6 = picks[:6]
for p in top6:
    print(f"  - {p['pick']:30}  DK: {fmt(p['dk_ml'])}")

# Rough payout estimate
if top6:
    from functools import reduce
    def parlay_mult(ml_list):
        mults = []
        for ml in ml_list:
            if ml is None: continue
            dec = (ml/100 + 1) if ml > 0 else (100/(-ml) + 1)
            mults.append(dec)
        combined = reduce(lambda a,b: a*b, mults, 1.0)
        return combined

    mls = [p["dk_ml"] for p in top6 if p["dk_ml"]]
    mult = parlay_mult(mls)
    profit_10 = round((mult - 1) * 10, 2)
    profit_15 = round((mult - 1) * 15, 2)
    profit_25 = round((mult - 1) * 25, 2)
    combined_ml = round((mult - 1) * 100) if mult <= 2 else round((mult - 1) * 100)

    print(f"\n  Est. parlay multiplier: {mult:.1f}x  (~+{int((mult-1)*100)})")
    print(f"  $10 wins: ~${profit_10}")
    print(f"  $15 wins: ~${profit_15}")
    print(f"  $25 wins: ~${profit_25}")

print(f"\n{'='*70}")
print("  VALUE DOGS (plus-money worth considering)")
print(f"{'='*70}")
dogs = [p for p in picks if p.get("best_ml") and p["best_ml"] > 0 and p["score"] >= 2]
for p in dogs[:5]:
    print(f"  {p['pick']:30}  Best: {fmt(p['best_ml'])}  ({p['reason']})")
