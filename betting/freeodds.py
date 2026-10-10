"""Moneyline prices from sources that cost nothing.

The Odds API is switched off (oddsapi.ENABLED = False) to hold spend at zero,
so the board needs prices from somewhere free. Two sources, both public:

  Pinnacle   guest.api.arcadia.pinnacle.com, the same feed the website uses.
             Sharpest book available and it posts lines the night before, which
             is what makes a next-day board possible at all.
  Kalshi     api.elections.kalshi.com, the public trade API. Lists every game
             but leaves bid/ask null until trading opens near first pitch, so
             it is a same-day source, not a next-day one.

Both emit events in the Odds API's shape so pp/board.py consumes them unchanged.

Two traps, both cost a debugging cycle:
  * Pinnacle's markets endpoint returns 204 EMPTY when you pass ?brandId=0 --
    the same parameter the matchups endpoint requires. Do not "fix" one by
    copying the other.
  * Kalshi ships BOTH a legacy integer-cent price block (yes_bid, yes_ask,
    last_price) and a newer string-dollar one (yes_ask_dollars, ...). The
    integer fields are dead -- they come back null on every market including
    actively traded ones, so reading them makes a live board look unpriced.
    Read the _dollars fields.
  * yes_ask is what you PAY to back that team, so that is the price to convert;
    yes_bid is what you would sell at. Using the midpoint understates the vig
    you actually face.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import urllib.request

PIN = "https://guest.api.arcadia.pinnacle.com"
PIN_KEY = "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R"      # public guest key the site ships
KAL = "https://api.elections.kalshi.com/trade-api/v2"
MLB_LEAGUE = 246
NFL_LEAGUE = 889

_HDR = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def _get(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers={**_HDR, **(headers or {})})
    body = urllib.request.urlopen(req, timeout=timeout).read()
    return json.loads(body) if body else None


def _dollars_to_american(s):
    """Kalshi quotes a $1 contract in dollars. "0.5300" = 53% = -113."""
    try:
        p = float(s)
    except (TypeError, ValueError):
        return None
    if not 0 < p < 1:
        return None
    return round(-100 * p / (1 - p)) if p > 0.5 else round(100 * (1 - p) / p)


def pinnacle_mlb() -> list[dict]:
    return pinnacle_league(MLB_LEAGUE)


def pinnacle_nfl() -> list[dict]:
    return pinnacle_league(NFL_LEAGUE)


def pinnacle_league(league) -> list[dict]:
    """Full-game moneylines, in the Odds API event shape."""
    matchups = _get("%s/0.1/leagues/%s/matchups?brandId=0" % (PIN, league))
    # NB: no brandId here -- with it the endpoint answers 204 with an empty body
    markets = _get("%s/0.1/leagues/%s/markets/straight" % (PIN, league))

    prices = {}
    for m in markets or []:
        # key "s;0;m" == straight, period 0 (full game), moneyline
        if m.get("key") != "s;0;m" or m.get("isAlternate"):
            continue
        prices[m["matchupId"]] = {p.get("designation"): p.get("price")
                                  for p in m.get("prices", [])}

    out = []
    for mu in matchups or []:
        if mu.get("parentId") or mu.get("type") != "matchup":
            continue
        px = prices.get(mu["id"])
        if not px or px.get("home") is None or px.get("away") is None:
            continue
        side = {p["alignment"]: p["name"] for p in mu.get("participants", [])}
        if not side.get("home") or not side.get("away"):
            continue
        # Pinnacle mixes league-wide specials into the same feed -- rows like
        # "Away Runs (15 Games) @ Home Runs (15 Games)". They price fine and
        # look like games, so filter on whether both names resolve to a club.
        resolve = nfl_code if league == NFL_LEAGUE else team_code
        if not (resolve(side["home"]) and resolve(side["away"])):
            continue
        out.append({
            "id": "pin-%s" % mu["id"],
            "commence_time": mu.get("startTime"),
            "home_team": side["home"], "away_team": side["away"],
            "bookmakers": [{"key": "pinnacle", "title": "Pinnacle",
                            "markets": [{"key": "h2h", "outcomes": [
                                {"name": side["home"], "price": float(px["home"])},
                                {"name": side["away"], "price": float(px["away"])}]}]}],
        })
    return out


def kalshi_mlb() -> list[dict]:
    """Same shape, from Kalshi. Empty prices until trading opens."""
    markets, cursor = [], None
    for _ in range(12):
        u = "%s/markets?series_ticker=KXMLBGAME&status=open&limit=200" % KAL
        if cursor:
            u += "&cursor=" + cursor
        d = _get(u)
        markets += d.get("markets", [])
        cursor = d.get("cursor")
        if not cursor:
            break

    ev = {}
    for m in markets:
        ev.setdefault(m["event_ticker"], []).append(m)

    out = []
    for tick, legs in ev.items():
        if len(legs) != 2:
            continue
        # yes_ask is what it costs to back that team -- the price you actually get
        priced = []
        for l in legs:
            am = _dollars_to_american(l.get("yes_ask_dollars"))
            code = team_code(l.get("yes_sub_title"))
            if am is None or code is None:
                priced = []
                break
            priced.append((code, float(am)))
        if len(priced) != 2:
            continue

        # The event ticker ends with AWAY+HOME concatenated -- 26SEP071305ATLPHI
        # is Atlanta at Philadelphia. Codes vary in length (KC, LAD, WSH), so
        # test both orderings against the suffix rather than trying to split it.
        # Guessing home/away instead would invert the model's home-field term.
        (ca, pa), (cb, pb) = priced
        # rsplit leaves the datetime on the front: "26SEP071305ATLPHI".
        # Strip the leading YYMMMDDHHMM (11 chars) to get just the team pair.
        suffix = re.sub(r"^\d{2}[A-Z]{3}\d{6}", "", tick.rsplit("-", 1)[-1].upper())
        aa, ab = TICKER_ALIAS.get(ca, [ca]), TICKER_ALIAS.get(cb, [cb])
        away = home = None
        for x in aa:
            for y in ab:
                if suffix == y + x:
                    away, home = (cb, pb), (ca, pa)
                elif suffix == x + y:
                    away, home = (ca, pa), (cb, pb)
        if away is None:
            continue

        out.append({
            "id": tick, "commence_time": _ticker_start(tick),
            "home_team": FULL[home[0]], "away_team": FULL[away[0]],
            "bookmakers": [{"key": "kalshi", "title": "Kalshi",
                            "markets": [{"key": "h2h", "outcomes": [
                                {"name": FULL[home[0]], "price": home[1]},
                                {"name": FULL[away[0]], "price": away[1]}]}]}],
        })
    return out


# Kalshi labels teams by CITY ("Philadelphia", "Los Angeles D"), Pinnacle by
# full name ("Philadelphia Phillies"). Matching on the last word silently fails
# on nine of eleven games and, worse, would collide Boston Red Sox with Chicago
# White Sox on "Sox". Resolve both to a code instead.
TEAM_CODES = {
    "ARI": ["arizona", "diamondbacks"],       "ATL": ["atlanta", "braves"],
    "BAL": ["baltimore", "orioles"],          "BOS": ["boston", "red sox"],
    "CHC": ["chicago c", "cubs"],             "CWS": ["chicago ws", "white sox"],
    "CIN": ["cincinnati", "reds"],            "CLE": ["cleveland", "guardians"],
    "COL": ["colorado", "rockies"],           "DET": ["detroit", "tigers"],
    "HOU": ["houston", "astros"],             "KC":  ["kansas city", "royals"],
    "LAA": ["los angeles a", "angels"],       "LAD": ["los angeles d", "dodgers"],
    "MIA": ["miami", "marlins"],              "MIL": ["milwaukee", "brewers"],
    "MIN": ["minnesota", "twins"],            "NYM": ["new york m", "mets"],
    "NYY": ["new york y", "yankees"],         "ATH": ["athletics", "a's", "oakland"],
    "PHI": ["philadelphia", "phillies"],      "PIT": ["pittsburgh", "pirates"],
    "SD":  ["san diego", "padres"],           "SF":  ["san francisco", "giants"],
    "SEA": ["seattle", "mariners"],           "STL": ["st. louis", "st louis", "cardinals"],
    "TB":  ["tampa bay", "rays"],             "TEX": ["texas", "rangers"],
    "TOR": ["toronto", "blue jays"],          "WSH": ["washington", "nationals"],
}

NAMES = {"ARI": "Diamondbacks", "ATL": "Braves", "BAL": "Orioles", "BOS": "Red Sox",
         "CHC": "Cubs", "CWS": "White Sox", "CIN": "Reds", "CLE": "Guardians",
         "COL": "Rockies", "DET": "Tigers", "HOU": "Astros", "KC": "Royals",
         "LAA": "Angels", "LAD": "Dodgers", "MIA": "Marlins", "MIL": "Brewers",
         "MIN": "Twins", "NYM": "Mets", "NYY": "Yankees", "ATH": "Athletics",
         "PHI": "Phillies", "PIT": "Pirates", "SD": "Padres", "SF": "Giants",
         "SEA": "Mariners", "STL": "Cardinals", "TB": "Rays", "TEX": "Rangers",
         "TOR": "Blue Jays", "WSH": "Nationals"}


def team_code(name):
    """Longest alias wins, so 'white sox' beats 'sox' and cannot collide."""
    s = str(name).lower().strip()
    best, blen = None, 0
    for code, aliases in TEAM_CODES.items():
        for a in aliases:
            if a in s and len(a) > blen:
                best, blen = code, len(a)
    return best


# Kalshi's own labels are cities; statsapi (and therefore board.py's schedule
# lookup) uses full club names. Emitting the city would fail every match.
FULL = {"ARI": "Arizona Diamondbacks", "ATL": "Atlanta Braves",
        "BAL": "Baltimore Orioles", "BOS": "Boston Red Sox",
        "CHC": "Chicago Cubs", "CWS": "Chicago White Sox",
        "CIN": "Cincinnati Reds", "CLE": "Cleveland Guardians",
        "COL": "Colorado Rockies", "DET": "Detroit Tigers",
        "HOU": "Houston Astros", "KC": "Kansas City Royals",
        "LAA": "Los Angeles Angels", "LAD": "Los Angeles Dodgers",
        "MIA": "Miami Marlins", "MIL": "Milwaukee Brewers",
        "MIN": "Minnesota Twins", "NYM": "New York Mets",
        "NYY": "New York Yankees", "ATH": "Athletics",
        "PHI": "Philadelphia Phillies", "PIT": "Pittsburgh Pirates",
        "SD": "San Diego Padres", "SF": "San Francisco Giants",
        "SEA": "Seattle Mariners", "STL": "St. Louis Cardinals",
        "TB": "Tampa Bay Rays", "TEX": "Texas Rangers",
        "TOR": "Toronto Blue Jays", "WSH": "Washington Nationals"}


# Kalshi's ticker abbreviations do not always equal our codes (AZ not ARI).
# Only the differing ones need listing; team_code's own value is tried first.
TICKER_ALIAS = {"ARI": ["ARI", "AZ"], "CWS": ["CWS", "CHW"], "WSH": ["WSH", "WAS"],
                "SD": ["SD", "SDP"], "SF": ["SF", "SFG"], "TB": ["TB", "TBR"],
                "KC": ["KC", "KCR"], "ATH": ["ATH", "OAK", "ATHL"],
                "CHC": ["CHC", "CUB"], "NYM": ["NYM"], "NYY": ["NYY"]}


_MON = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
     "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


def _ticker_start(tick):
    """First pitch in UTC, parsed out of the event ticker.

    Kalshi's close_time is when the MARKET closes, which sits about three days
    after the game so late-settling results still resolve. Using it as the
    start time pushed every game outside board.py's day window and produced a
    board with zero picks. The ticker carries the real time -- but in EASTERN
    local, so it needs converting: 26SEP071305ATLPHI is 1:05pm ET.
    """
    m = re.search(r"-(\d{2})([A-Z]{3})(\d{2})(\d{2})(\d{2})", tick)
    if not m:
        return None
    yy, mon, dd, hh, mi = m.groups()
    et = _dt.timezone(_dt.timedelta(hours=-4))      # EDT; MLB never runs in EST
    t = _dt.datetime(2000 + int(yy), _MON[mon], int(dd), int(hh), int(mi), tzinfo=et)
    return t.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# NFL needs its own map. Reusing TEAM_CODES silently "worked" for the six
# cities that field both an MLB and an NFL team (CIN, PHI, PIT, ATL, WSH, TB)
# and dropped every other game, including New England at Seattle. Worse, a
# shared city could resolve to the wrong sport's club entirely.
NFL_CODES = {
    "ARI": ["arizona", "cardinals"],      "ATL": ["atlanta", "falcons"],
    "BAL": ["baltimore", "ravens"],       "BUF": ["buffalo", "bills"],
    "CAR": ["carolina", "panthers"],      "CHI": ["chicago", "bears"],
    "CIN": ["cincinnati", "bengals"],     "CLE": ["cleveland", "browns"],
    "DAL": ["dallas", "cowboys"],         "DEN": ["denver", "broncos"],
    "DET": ["detroit", "lions"],          "GB": ["green bay", "packers"],
    "HOU": ["houston", "texans"],         "IND": ["indianapolis", "colts"],
    "JAX": ["jacksonville", "jaguars"],   "KC": ["kansas city", "chiefs"],
    "LV": ["las vegas", "raiders"],       "LAC": ["los angeles c", "chargers"],
    "LA": ["los angeles r", "rams"],      "MIA": ["miami", "dolphins"],
    "MIN": ["minnesota", "vikings"],      "NE": ["new england", "patriots"],
    "NO": ["new orleans", "saints"],      "NYG": ["new york g", "giants"],
    "NYJ": ["new york j", "jets"],        "PHI": ["philadelphia", "eagles"],
    "PIT": ["pittsburgh", "steelers"],    "SF": ["san francisco", "49ers"],
    "SEA": ["seattle", "seahawks"],       "TB": ["tampa bay", "buccaneers"],
    "TEN": ["tennessee", "titans"],       "WSH": ["washington", "commanders"],
}


def nfl_code(name):
    s = str(name).lower().strip()
    best, blen = None, 0
    for code, aliases in NFL_CODES.items():
        for a in aliases:
            if a in s and len(a) > blen:
                best, blen = code, len(a)
    return best
