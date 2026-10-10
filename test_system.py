import sys
sys.path.insert(0, '.')

from data.db import init_db
init_db()
print("DB OK")

from collectors.odds_api import generate_demo_odds
events = generate_demo_odds()
print(f"Generated {len(events)} demo events")

from data.db import get_upcoming_games
games = get_upcoming_games()
print(f"Games in DB: {len(games)}")

from engine.models import get_predictions
preds = get_predictions(games[:3])
print(f"Predictions: {len(preds)}")
for p in preds[:2]:
    home = p["home_team"]
    away = p["away_team"]
    pick = p["pick_team"]
    conf = p["confidence"]
    print(f"  {home} vs {away} -> PICK: {pick} ({conf}% conf)")

from engine.sharp_money import run_sharp_scan
alerts = run_sharp_scan(games[:5])
print(f"Sharp alerts: {len(alerts)}")

print("\nALL SYSTEMS GO")
