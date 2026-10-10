import sys, requests
sys.path.insert(0, '.')

API_KEY = __import__("os").getenv("ODDS_API_KEY", "")
BASE = "https://api.the-odds-api.com/v4"

def get_odds(sport, markets="h2h,spreads,totals"):
    params = {
        "apiKey": API_KEY,
        "regions": "us",
        "markets": markets,
        "bookmakers": "draftkings,fanduel,betmgm,caesars,pinnacle",
        "oddsFormat": "american",
    }
    r = requests.get(f"{BASE}/sports/{sport}/odds", params=params, timeout=15)
    r.raise_for_status()
    return r.json(), r.headers

def fmt_ml(v):
    if v is None: return "N/A"
    return f"+{int(v)}" if v >= 0 else str(int(v))

def show_sport(label, sport):
    data, h = get_odds(sport)
    if not data:
        print(f"\n{label}: no games up")
        return
    print(f"\n{'='*60}")
    print(f"  {label}  ({len(data)} games)   credits left: {h.get('x-requests-remaining')}")
    print(f"{'='*60}")
    for g in data[:10]:
        home = g["home_team"]
        away = g["away_team"]
        time_str = g["commence_time"][5:16].replace("T"," ")

        # grab draftkings or first available
        bk_data = {b["key"]: b for b in g.get("bookmakers", [])}
        bk = bk_data.get("draftkings") or (list(bk_data.values())[0] if bk_data else None)

        home_ml = away_ml = spread = total = "—"
        if bk:
            for mkt in bk.get("markets", []):
                outs = {o["name"]: o for o in mkt["outcomes"]}
                if mkt["key"] == "h2h":
                    home_ml = fmt_ml(outs.get(home, {}).get("price"))
                    away_ml = fmt_ml(outs.get(away, {}).get("price"))
                elif mkt["key"] == "spreads":
                    sp = outs.get(home, {}).get("point")
                    spread = f"{'+' if sp and sp>0 else ''}{sp}" if sp is not None else "—"
                elif mkt["key"] == "totals":
                    tot = outs.get("Over", {}).get("point")
                    total = f"O/U {tot}" if tot else "—"

        print(f"  {time_str}  {away:25} @ {home:25}  ML {away_ml}/{home_ml}  Spd {spread}  {total}")

# Pull the big 3 right now
show_sport("NBA PLAYOFFS", "basketball_nba")
show_sport("MLB",          "baseball_mlb")
show_sport("NHL PLAYOFFS", "icehockey_nhl")
