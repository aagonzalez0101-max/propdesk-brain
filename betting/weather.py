"""
Ballpark weather: the missing input that makes totals unbettable.

The totals model was disabled because it was under-dispersed -- its
game-to-game spread was sd 0.55 runs against the market's 0.79, so it
compressed toward the league average and screamed UNDER on every high-total
game. A large part of that missing spread is weather, which the market prices
and the model did not see at all.

Three effects, all real and all measurable:

  wind        A 10 mph wind blowing out is worth roughly half a run; blowing
              in, roughly the same the other way. This needs the park's
              ORIENTATION, not just wind direction -- a west wind is blowing
              out at one park and straight in at another. statsapi publishes
              `azimuthAngle` per venue, which is the bearing from home plate
              to centre field.
  temperature Warm air is less dense and the ball carries. Roughly 0.1 runs
              per 10F above a ~70F baseline.
  altitude    Already partly inside the park factors, so it is deliberately
              NOT re-applied here -- double counting Coors would be worse
              than ignoring it.

Domes and closed roofs get no weather adjustment at all.

Everything is free: Open-Meteo needs no key and serves both forecast and a
historical archive, so the same code prices tonight's game and backtests last
month's.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import requests

from . import mlbdata as D

FORECAST = "https://api.open-meteo.com/v1/forecast"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"

# Runs per game added by 10 mph of wind blowing straight out to centre.
# Deliberately conservative: the effect is real but park-specific, and an
# overstated wind term would just trade one dispersion error for another.
WIND_RUNS_PER_10MPH = 0.45

# Runs per game per 10F above the reference temperature. The baseline is the
# league's AVERAGE game temperature, not a round number -- anchoring at 70F
# during a summer slate made almost every game read positive, which would just
# shift every total up rather than discriminate between them. A weather term
# has to be centred on zero or it is a bias, not a signal.
TEMP_RUNS_PER_10F = 0.10
TEMP_BASELINE_F = 76.0

# A retractable roof is closed in extreme weather. Applying a 112F outside
# reading to a game played under a closed roof at 75F is simply wrong.
RETRACT_CLOSE_HOT = 95.0
RETRACT_CLOSE_COLD = 55.0

# Wind matters far less when the ball isn't in the air long. Capped so a
# freak 30 mph reading can't dominate the projection.
MAX_WIND_RUNS = 0.9


def venue_info(team_id: int) -> dict:
    """Coordinates, orientation, roof and elevation for a team's home park."""
    cached = D._cache_get(f"venue_{team_id}", 2592000)
    if cached is not None:
        return cached

    info = D._get(f"/teams/{team_id}", {"hydrate": "venue(location,fieldInfo)"},
                  ttl=2592000, cache_name=f"teamvenue_{team_id}")
    try:
        v = info["teams"][0]["venue"]
        loc = v.get("location", {}) or {}
        coord = loc.get("defaultCoordinates", {}) or {}
        field = v.get("fieldInfo", {}) or {}
        out = {
            "venue": v.get("name", "?"),
            "lat": coord.get("latitude"),
            "lon": coord.get("longitude"),
            # Bearing from home plate to centre field, in degrees.
            "azimuth": loc.get("azimuthAngle"),
            "roof": field.get("roofType", "Open"),
            "elevation": loc.get("elevation"),
        }
    except (KeyError, IndexError, TypeError):
        out = {"venue": "?", "lat": None, "lon": None, "azimuth": None,
               "roof": "Open", "elevation": None}
    D._cache_put(f"venue_{team_id}", out)
    return out


def _hourly(lat: float, lon: float, when: datetime, historical: bool) -> dict:
    """Weather for the hour nearest `when`."""
    day = when.strftime("%Y-%m-%d")
    url = ARCHIVE if historical else FORECAST
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": "temperature_2m,wind_speed_10m,wind_direction_10m",
        "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
    }
    if historical:
        params.update({"start_date": day, "end_date": day})
    else:
        params["forecast_days"] = 3

    key = f"wx_{lat:.2f}_{lon:.2f}_{day}_{'h' if historical else 'f'}"
    cached = D._cache_get(key, 10800 if not historical else 2592000)
    if cached is None:
        try:
            r = requests.get(url, params=params, timeout=25)
            r.raise_for_status()
            cached = r.json().get("hourly", {})
            D._cache_put(key, cached)
        except (requests.RequestException, ValueError):
            return {}
    if not cached or not cached.get("time"):
        return {}

    target = when.strftime("%Y-%m-%dT%H:00")
    times = cached["time"]
    idx = times.index(target) if target in times else None
    if idx is None:
        # Nearest available hour on that date.
        same_day = [i for i, t in enumerate(times) if t.startswith(day)]
        if not same_day:
            return {}
        idx = min(same_day, key=lambda i: abs(int(times[i][11:13]) - when.hour))
    try:
        return {"temp_f": cached["temperature_2m"][idx],
                "wind_mph": cached["wind_speed_10m"][idx],
                "wind_dir": cached["wind_direction_10m"][idx]}
    except (KeyError, IndexError, TypeError):
        return {}


def wind_out_component(wind_dir_from: float, azimuth: float) -> float:
    """
    How much of the wind is blowing OUT toward centre field.

    Meteorological wind direction is the direction the wind blows FROM, so a
    wind reported at 180 degrees is blowing toward 0. It helps carry the ball
    out when it blows in the same direction the field faces.

    Returns a factor in [-1, 1]: +1 straight out, -1 straight in, 0 crosswind.
    """
    blowing_toward = (wind_dir_from + 180.0) % 360.0
    delta = math.radians(blowing_toward - azimuth)
    return math.cos(delta)


def game_weather(ctx: dict, historical: bool | None = None) -> dict:
    """
    Weather-driven run adjustment for one game.

    Returns `runs` -- the number of runs to add to the projected TOTAL (split
    evenly between the sides) -- plus the detail behind it so a pick can
    explain itself.
    """
    none = {"runs": 0.0, "reason": "no data", "roof": None,
            "temp_f": None, "wind_mph": None, "out_component": None}
    v = venue_info(ctx.get("home_id")) if ctx.get("home_id") else None
    if not v or v["lat"] is None:
        return none

    roof = (v.get("roof") or "Open").lower()
    if roof in ("dome", "fixed", "closed", "indoor"):
        return {**none, "runs": 0.0, "reason": f"{v['venue']} is a dome",
                "roof": v.get("roof")}

    try:
        when = datetime.fromisoformat(str(ctx["start"]).replace("Z", "+00:00"))
    except (KeyError, ValueError, TypeError):
        return none
    if historical is None:
        historical = when < datetime.now(timezone.utc)

    wx = _hourly(v["lat"], v["lon"], when, historical)
    if not wx or wx.get("temp_f") is None:
        return none

    # Retractable roofs shut in extreme heat or cold, which makes the outside
    # reading irrelevant -- Chase Field at 112F is played indoors at ~75F.
    if roof.startswith("retract") and (
            wx["temp_f"] >= RETRACT_CLOSE_HOT or wx["temp_f"] <= RETRACT_CLOSE_COLD):
        return {**none, "runs": 0.0, "roof": v.get("roof"),
                "temp_f": wx["temp_f"], "wind_mph": wx.get("wind_mph"),
                "venue": v["venue"],
                "reason": (f"{wx['temp_f']:.0f}F outside -- retractable roof "
                           f"almost certainly closed, weather ignored")}

    temp_runs = ((wx["temp_f"] - TEMP_BASELINE_F) / 10.0) * TEMP_RUNS_PER_10F

    wind_runs = 0.0
    out_comp = None
    az = v.get("azimuth")
    if az is not None and wx.get("wind_mph") is not None:
        out_comp = wind_out_component(wx["wind_dir"], float(az))
        wind_runs = (wx["wind_mph"] / 10.0) * WIND_RUNS_PER_10MPH * out_comp
        wind_runs = max(min(wind_runs, MAX_WIND_RUNS), -MAX_WIND_RUNS)
        # A retractable roof is closed in bad weather often enough that the
        # wind term deserves to be halved rather than trusted outright.
        if roof.startswith("retract"):
            wind_runs *= 0.5

    total = temp_runs + wind_runs
    dirn = ("out" if (out_comp or 0) > 0.25 else
            "in" if (out_comp or 0) < -0.25 else "cross")
    return {
        "runs": total, "temp_runs": temp_runs, "wind_runs": wind_runs,
        "temp_f": wx["temp_f"], "wind_mph": wx["wind_mph"],
        "wind_dir": wx.get("wind_dir"), "out_component": out_comp,
        "roof": v.get("roof"), "venue": v["venue"],
        "reason": (f"{wx['temp_f']:.0f}F, {wx['wind_mph']:.0f}mph {dirn}"
                   f" -> {total:+.2f} runs"),
    }
