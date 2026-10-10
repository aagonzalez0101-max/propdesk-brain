"""
The Odds API client with disk caching and a hard credit budget.

The free tier is 500 credits/month. Costs are NOT one-per-call:

    /sports                       -> 0 credits (free)
    /odds                         -> 1 x (markets) x (regions)
    /events                       -> 0 credits (free)
    /events/{id}/odds  (props)    -> 1 x (markets) x (regions)

So one careless props pull across 3 regions and 5 markets costs 15 credits.
Fifteen of those and the month is gone. Every call here is cached to disk and
logged against a budget that refuses to overspend.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "cache"
LEDGER = ROOT / "data" / "credits.json"

load_dotenv(ROOT / ".env")
API_KEY = os.getenv("ODDS_API_KEY", "")

# Multiple free keys rotate: ODDS_API_KEY, then ODDS_API_KEY2, KEY3, ... Each
# free key carries its own 500/month, so N keys is N x 500 with no card and no
# new provider. Rotation is by exhaustion, not round-robin, so the ledger for
# key 1 stays meaningful until it actually runs dry.
API_KEYS = [k for k in [os.getenv("ODDS_API_KEY", "")] +
            [os.getenv("ODDS_API_KEY%d" % i, "") for i in range(2, 11)] if k]


def keys_available() -> int:
    return len(API_KEYS)
BASE = "https://api.the-odds-api.com/v4"

# Monthly credit ceiling we hold ourselves to. Set below the true 500 so a
# miscount never actually exhausts the key.
MONTHLY_BUDGET = 460

# Hard per-day ceiling. On 2026-08-26 a day of exploration burned 282 credits
# -- full-board reruns while debugging, probing markets that turned out not to
# exist, and pulling F5 for every game in a market we had already decided not
# to bet. The actual betting that day needed about 15.
#
# Steady-state operation is: shortlist on FREE data, then buy props for three
# or four games only. That is 6-12 credits. This cap makes an exploration day
# impossible without deliberately raising it.
DAILY_CAP = 25

# API OFF. Every projection in this system runs on FREE data -- statsapi for
# schedules, stats, lineups and game logs; Baseball Savant for pitch arsenals;
# Open-Meteo for weather; ESPN for historical closing odds. The paid API only
# ever supplied PRICES, which is the one thing a human can read off the book
# in five seconds.
#
# So the workflow is: build the board free, output fair values, and have the
# user read back the actual Novig numbers. Set ENABLED = True to resume
# automated price pulls.
ENABLED = False

# ...with ONE narrow exception. CLV needs the recreational books (DraftKings,
# FanDuel) that no free feed carries, and a closing snapshot is exactly one
# h2h/us call = 1 credit for the whole slate, every book. That is ~30 credits a
# month against 500 per key, so it cannot recreate the 282-credit day the cap
# above exists to prevent. Anything beyond this stays off.
CLV_ENABLED = False      # user's call 2026-09-08: stay free, ask before spending
CLV_DAILY_CAP = 4

SPORT_KEYS = {
    "NFL": "americanfootball_nfl",
    "NFLPRE": "americanfootball_nfl_preseason",
    "MLB": "baseball_mlb",
    "WNBA": "basketball_wnba",
    "NBA": "basketball_nba",
    "NCAAF": "americanfootball_ncaaf",
}

# Books that price sharp and/or at very low hold. Novig is the one being bet,
# but Kalshi / Polymarket / ProphetX are exchanges and prediction markets whose
# consensus is the best free proxy for true probability that exists.
EXCHANGE_BOOKS = {"novig", "kalshi", "polymarket", "prophetx", "betopenly"}
SHARP_BOOKS = EXCHANGE_BOOKS | {"pinnacle", "lowvig", "betonlineag"}

# Retail books. Useful for measuring how far the soft market has drifted from
# the exchanges, which is itself a signal.
RETAIL_BOOKS = {
    "draftkings", "fanduel", "betmgm", "espnbet", "betrivers", "ballybet",
    "betparx", "hardrockbet", "bovada", "fliff", "betus", "mybookieag",
    "betanysports",
}


class BudgetExceeded(RuntimeError):
    """Raised instead of spending credits we don't have."""


# ------------------------------------------------------------------- ledger

def _load_ledger() -> dict:
    if LEDGER.exists():
        try:
            return json.loads(LEDGER.read_text())
        except json.JSONDecodeError:
            pass
    return {"month": _this_month(), "used": 0, "calls": [], "remaining_reported": None}


def _this_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _save_ledger(led: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(led, indent=2))


def credits_used_today() -> int:
    """Credits spent so far today, for the daily cap."""
    led = _load_ledger()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return sum(c.get("cost", 0) for c in led.get("calls", [])
               if str(c.get("at", "")).startswith(today))


def credits_used() -> int:
    led = _load_ledger()
    if led.get("month") != _this_month():
        return 0
    return led.get("used", 0)


def credits_left() -> int:
    """Budget remaining. Prefers the API's own reported figure when we have it."""
    led = _load_ledger()
    if led.get("month") != _this_month():
        return MONTHLY_BUDGET
    reported = led.get("remaining_reported")
    if reported is not None:
        return min(int(reported), MONTHLY_BUDGET - led.get("used", 0))
    return MONTHLY_BUDGET - led.get("used", 0)


def _charge(cost: int, endpoint: str, remaining_reported: str | None) -> None:
    led = _load_ledger()
    if led.get("month") != _this_month():
        led = {"month": _this_month(), "used": 0, "calls": [], "remaining_reported": None}
    led["used"] = led.get("used", 0) + cost
    if remaining_reported is not None:
        try:
            led["remaining_reported"] = int(remaining_reported)
        except (TypeError, ValueError):
            pass
    led.setdefault("calls", []).append({
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "endpoint": endpoint,
        "cost": cost,
    })
    led["calls"] = led["calls"][-300:]
    _save_ledger(led)


def budget_report() -> str:
    led = _load_ledger()
    used = credits_used()
    left = credits_left()
    api_says = led.get("remaining_reported")
    bar_len = 24
    filled = int(bar_len * used / MONTHLY_BUDGET) if MONTHLY_BUDGET else 0
    bar = "#" * min(filled, bar_len) + "." * max(0, bar_len - filled)
    extra = f"  (API reports {api_says} left on key)" if api_says is not None else ""
    return f"Credits [{bar}] {used}/{MONTHLY_BUDGET} used, {left} left this month{extra}"


# -------------------------------------------------------------------- cache

def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def _cache_key(path: str, params: dict) -> str:
    safe = {k: v for k, v in params.items() if k != "apiKey"}
    blob = path + "|" + json.dumps(safe, sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:20]


def _cache_get(key: str, ttl: int):
    p = _cache_path(key)
    if not p.exists():
        return None
    age = time.time() - p.stat().st_mtime
    if age > ttl:
        return None
    try:
        return json.loads(p.read_text()), age
    except json.JSONDecodeError:
        return None


def _cache_put(key: str, data) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(key).write_text(json.dumps(data))


# --------------------------------------------------------------------- core

def _request(path: str, params: dict, cost: int, ttl: int,
             force: bool = False, verbose: bool = True):
    """
    Fetch with cache + budget enforcement.

    `cost` is what we expect to be charged; the ledger reconciles against the
    API's own x-requests-remaining header afterwards.
    """
    if not ENABLED:
        raise BudgetExceeded(
            "Odds API is OFF (oddsapi.ENABLED = False). The board builds on "
            "free data; read prices off the book instead. Set ENABLED = True "
            "to resume automated pulls."
        )
    if not API_KEYS:
        raise RuntimeError("ODDS_API_KEY missing from .env")

    key = _cache_key(path, params)
    if not force:
        hit = _cache_get(key, ttl)
        if hit is not None:
            data, age = hit
            if verbose:
                print(f"  [cache {int(age)}s old, 0 credits] {path}")
            return data

    if cost > 0:
        left = credits_left()
        if cost > left:
            raise BudgetExceeded(
                f"Call needs {cost} credits, only {left} left this month. "
                f"Use cached data, cut markets/regions, or raise MONTHLY_BUDGET."
            )
        today = credits_used_today()
        if today + cost > DAILY_CAP:
            raise BudgetExceeded(
                f"Daily cap: {today} used today, this call needs {cost}, "
                f"cap is {DAILY_CAP}. Shortlist on free data first, then buy "
                f"props for 3-4 games. Raise oddsapi.DAILY_CAP to override."
            )

    r = None
    for key in API_KEYS:
        r = requests.get(f"{BASE}{path}", params={**params, "apiKey": key}, timeout=30)
        # 401/429 here means that key is spent -- move to the next one rather
        # than failing the whole call
        if r.status_code not in (401, 429):
            break
    if r.status_code != 200:
        raise RuntimeError(f"Odds API {r.status_code} on {path}: {r.text[:250]}")

    remaining = r.headers.get("x-requests-remaining")
    last_cost = r.headers.get("x-requests-last")
    actual = int(last_cost) if last_cost and last_cost.isdigit() else cost
    if actual:
        _charge(actual, path, remaining)
    if verbose and actual:
        print(f"  [-{actual} credits, {remaining} left on key] {path}")

    data = r.json()
    # Never cache an empty board. Books post props only a few hours before
    # first pitch, so an early pull legitimately returns zero bookmakers at
    # zero credits -- caching that would poison every later run for the game
    # and silently hide every prop on it once the lines actually go up.
    if not _is_empty_board(data):
        _cache_put(key, data)
    return data


def _is_empty_board(data) -> bool:
    """True when a response carries no priced markets at all."""
    if isinstance(data, dict):
        return not data.get("bookmakers")
    if isinstance(data, list):
        return len(data) == 0
    return False


# ---------------------------------------------------------------- endpoints

def list_sports(force: bool = False) -> list[dict]:
    """Free call - costs nothing."""
    return _request("/sports", {}, cost=0, ttl=86400, force=force, verbose=False)


def get_events(sport: str, force: bool = False) -> list[dict]:
    """Free call. Gives event IDs needed for props."""
    sk = SPORT_KEYS.get(sport.upper(), sport)
    return _request(f"/sports/{sk}/events", {}, cost=0, ttl=900,
                    force=force, verbose=False)


def get_odds(sport: str, markets: str = "h2h", regions: str = "us,us_ex",
             ttl: int = 600, force: bool = False) -> list[dict]:
    """
    Main-line odds for a whole slate.

    Cost = markets x regions. 'us_ex' is the exchange region that carries
    Novig/Kalshi/ProphetX, so it is almost always worth including -- those
    are both the prices being bet and the best fair-value benchmark.
    """
    sk = SPORT_KEYS.get(sport.upper(), sport)
    n_mkt = len([m for m in markets.split(",") if m])
    n_reg = len([r for r in regions.split(",") if r])
    return _request(
        f"/sports/{sk}/odds",
        {"regions": regions, "markets": markets, "oddsFormat": "american"},
        cost=n_mkt * n_reg, ttl=ttl, force=force,
    )


def get_event_odds(sport: str, event_id: str, markets: str,
                   regions: str = "us", ttl: int = 900,
                   force: bool = False) -> dict:
    """
    Player props / alternate markets for ONE event.

    Deliberately defaults to a single region: props across 3 regions cost 3x
    for books that mostly don't quote props anyway. Novig props are not
    returned by this API at all, which is why the model outputs a minimum
    acceptable price rather than naming a book.
    """
    sk = SPORT_KEYS.get(sport.upper(), sport)
    n_mkt = len([m for m in markets.split(",") if m])
    n_reg = len([r for r in regions.split(",") if r])
    return _request(
        f"/sports/{sk}/events/{event_id}/odds",
        {"regions": regions, "markets": markets, "oddsFormat": "american"},
        cost=n_mkt * n_reg, ttl=ttl, force=force,
    )


def estimate_cost(markets: str, regions: str, n_events: int = 1) -> int:
    n_mkt = len([m for m in markets.split(",") if m])
    n_reg = len([r for r in regions.split(",") if r])
    return n_mkt * n_reg * n_events


def burn_forecast(daily_cost: int) -> str:
    """
    Project a daily spend across the rest of the month.

    Worth printing on every run: the difference between a 10-credit and a
    22-credit daily routine is the difference between finishing the month with
    room to spare and going dark in week three.
    """
    from calendar import monthrange
    now = datetime.now(timezone.utc)
    days_left = monthrange(now.year, now.month)[1] - now.day + 1
    projected = daily_cost * days_left
    left = credits_left()
    verdict = "OK" if projected <= left else "OVER BUDGET"
    note = ""
    if projected > left and daily_cost > 0:
        affordable = left // daily_cost
        note = f" -- only {affordable} more days at this rate"
    return (f"Burn: {daily_cost}/run x {days_left} days left = {projected} "
            f"vs {left} available [{verdict}]{note}")


def match_event(events: list[dict], away: str, home: str,
                start_iso: str | None = None) -> str | None:
    """
    Find the event id for a specific game.

    Keying by (away, home) alone is wrong and fails silently: the events feed
    covers several days, so two teams in a three-game series appear two or
    three times and a plain dict lookup keeps whichever came last -- usually
    TOMORROW. The result is pricing today's projection against a game that
    has not been posted yet, finding nothing, and never knowing why.

    Matching on teams plus the closest start time fixes that, and handles
    doubleheaders as a bonus.
    """
    cands = [e for e in events
             if e.get("away_team") == away and e.get("home_team") == home]
    if not cands:
        return None
    if len(cands) == 1 or not start_iso:
        return cands[0]["id"]

    def parse(ts: str):
        try:
            return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    target = parse(start_iso)
    if target is None:
        return cands[0]["id"]
    scored = []
    for e in cands:
        ct = parse(e.get("commence_time", ""))
        if ct is None:
            continue
        scored.append((abs((ct - target).total_seconds()), e["id"]))
    if not scored:
        return cands[0]["id"]
    return min(scored)[1]
