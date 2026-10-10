import sys, io, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0"})
ODDS_KEY = __import__("os").getenv("ODDS_API_KEY", "")

def get_odds(sport):
    r = S.get(f"https://api.the-odds-api.com/v4/sports/{sport}/odds", params={
        "apiKey": ODDS_KEY, "regions": "us", "markets": "h2h",
        "bookmakers": "draftkings,fanduel,pinnacle,betmgm",
        "oddsFormat": "american",
    }, timeout=15)
    print(f"credits left: {r.headers.get('x-requests-remaining')}")
    return r.json() if r.ok else []

atp = get_odds("tennis_atp_french_open")
wta = get_odds("tennis_wta_french_open")

def get_ml(game, team, book):
    for bk in game.get("bookmakers",[]):
        if bk["key"] != book: continue
        for mkt in bk.get("markets",[]):
            if mkt["key"] != "h2h": continue
            for out in mkt["outcomes"]:
                if out["name"] == team: return out.get("price")
    return None

def best_price(game, team):
    prices = []
    for bk in game.get("bookmakers",[]):
        for mkt in bk.get("markets",[]):
            if mkt["key"] != "h2h": continue
            for out in mkt["outcomes"]:
                if out["name"] == team and out.get("price"):
                    prices.append((out["price"], bk["key"]))
    return max(prices, key=lambda x: x[0]) if prices else (None, "")

def fmt(v):
    if v is None: return "N/A"
    return f"+{int(v)}" if v >= 0 else str(int(v))

def to_prob(ml):
    if ml is None: return 0
    return 100/(ml+100) if ml > 0 else -ml/(-ml+100)

print("\n=== ALL -200 TO -700 FAVORITES (French Open) ===\n")
all_picks = []

for game in atp + wta:
    tour = "ATP" if game in atp else "WTA"
    p1, p2 = game["home_team"], game["away_team"]
    gtime = game.get("commence_time","")[:16].replace("T"," ")

    dk1 = get_ml(game, p1, "draftkings")
    dk2 = get_ml(game, p2, "draftkings")
    pin1 = get_ml(game, p1, "pinnacle")
    pin2 = get_ml(game, p2, "pinnacle")
    fd1 = get_ml(game, p1, "fanduel")
    fd2 = get_ml(game, p2, "fanduel")

    # figure out fav/dog
    for fav, dog, fav_dk, dog_dk, fav_pin, fav_fd, fav_name, dog_name in [
        (p1, p2, dk1, dk2, pin1, fd1, p1, p2),
        (p2, p1, dk2, dk1, pin2, fd2, p2, p1),
    ]:
        if fav_dk and fav_dk < -180:
            best_val, best_book = best_price(game, fav)
            # Sharp signal
            sharp = ""
            if fav_pin and fav_dk:
                diff = (to_prob(fav_pin) - to_prob(fav_dk)) * 100
                if diff > 2: sharp = f"SHARP +{diff:.1f}%"

            all_picks.append({
                "tour": tour, "gtime": gtime,
                "fav": fav, "dog": dog_name,
                "dk": fav_dk, "pin": fav_pin, "fd": fav_fd,
                "best": best_val, "best_book": best_book,
                "sharp": sharp,
            })
            break

# sort by DK odds (closest to -200 first = best parlay value)
all_picks.sort(key=lambda x: x["dk"] if x["dk"] else -9999)

# Group by range
print(f"{'Fav':30} {'Dog':25} {'DK':8} {'PIN':8} {'FD':8} {'Best':8} {'Note'}")
print("-"*100)

for p in all_picks:
    if p["dk"] and -500 <= p["dk"] <= -180:
        sharp_tag = p["sharp"] if p["sharp"] else ""
        print(f"[{p['tour']}] {p['fav'][:28]:28} vs {p['dog'][:22]:22} "
              f"{fmt(p['dk']):8} {fmt(p['pin']):8} {fmt(p['fd']):8} "
              f"{fmt(p['best'])}@{p['best_book'][:5]}  {sharp_tag}")

print("\n--- LOCKS (but heavy juice -500+) ---")
for p in all_picks:
    if p["dk"] and p["dk"] < -500:
        print(f"[{p['tour']}] {p['fav'][:28]:28} vs {p['dog'][:22]:22} "
              f"DK {fmt(p['dk'])}  PIN {fmt(p['pin'])}")

# Parlay combinations
print("\n\n=== PARLAY COMBOS FROM -200 TO -500 RANGE ===")

usable = [p for p in all_picks if p["dk"] and -500 < p["dk"] <= -180]

print(f"\nAll usable legs ({len(usable)}):")
for i, p in enumerate(usable, 1):
    print(f"  {i}. [{p['tour']}] {p['fav']:30} DK {fmt(p['dk'])}  {p['sharp']}")

# 3-leg combos payout estimate
print("\n3-LEG PARLAY PAYOUT ESTIMATES:")
from itertools import combinations
combos = list(combinations(usable[:8], 3))
results = []
for combo in combos:
    mult = 1.0
    for p in combo:
        ml = p["dk"]
        dec = (ml/100+1) if ml > 0 else (100/(-ml)+1)
        mult *= dec
    payout_ml = round((mult-1)*100)
    results.append((combo, mult, payout_ml))

results.sort(key=lambda x: x[1], reverse=True)
for combo, mult, pml in results[:8]:
    names = " + ".join(p["fav"].split()[-1] for p in combo)
    print(f"  {names:45}  ~+{pml}  ({mult:.2f}x)")
