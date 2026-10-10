import os

# ─── The Odds API ───────────────────────────────────────────────────────────
# Free tier: 500 requests/month  →  https://the-odds-api.com/
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")

# ─── Sports to track ────────────────────────────────────────────────────────
TRACKED_SPORTS = [
    "americanfootball_nfl",
    "basketball_nba",
    "baseball_mlb",
    "icehockey_nhl",
    "americanfootball_ncaaf",
    "basketball_ncaab",
]

SPORT_LABELS = {
    "americanfootball_nfl":  "NFL",
    "basketball_nba":        "NBA",
    "baseball_mlb":          "MLB",
    "icehockey_nhl":         "NHL",
    "americanfootball_ncaaf":"NCAAF",
    "basketball_ncaab":      "NCAAB",
}

# ─── Bookmakers to compare ──────────────────────────────────────────────────
BOOKMAKERS = ["draftkings", "fanduel", "betmgm", "caesars", "pinnacle",
              "bet365", "pointsbetus", "williamhill_us"]

# ─── Sharp money thresholds ─────────────────────────────────────────────────
SHARP_LINE_MOVE_THRESHOLD = 0.5   # points of spread movement to flag
SHARP_ML_MOVE_THRESHOLD   = 5     # cents of moneyline move (American odds)
REVERSE_LINE_MOVE_PCT     = 60    # public bet % opposite direction of move

# ─── DB path ────────────────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "sports_betting.db")

# ─── Refresh interval (seconds) ─────────────────────────────────────────────
REFRESH_INTERVAL = 300   # 5 min — keeps free-tier credits alive
