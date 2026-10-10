"""
Statcast pitch-arsenal matchups from Baseball Savant.

This is the factor that separates a real batter model from a rate-times-PA
toy. A hitter does not face "a pitcher" -- he faces a specific pitch mix. A
lefty who runs a .400 wOBA against four-seamers but .240 against sliders is a
completely different bet depending on whether tonight's starter throws 55%
sliders or 55% fastballs, and the season-long batting line hides that entirely.

Two free CSV leaderboards make it computable:

  batter  arsenal: each hitter's wOBA / whiff% BY pitch type
  pitcher arsenal: each pitcher's USAGE % and results BY pitch type

Weighting a hitter's per-pitch results by the usage the starter actually
throws gives a matchup-specific expectation, which is then expressed as a
multiplier on his baseline rates.

Both files are ~130KB and change daily, so they're cached to disk for 12h and
loaded once per run.
"""
from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "savant"
HEADERS = {"User-Agent": "Mozilla/5.0"}
BASE = "https://baseballsavant.mlb.com/leaderboard/pitch-arsenal-stats"

# Minimum pitches seen before a batter-vs-pitch-type line means anything.
MIN_PITCHES = 40
ARSENAL_REG = 150.0     # pitches of regression toward the batter's own baseline
MAX_ARSENAL_SWING = 0.18  # cap the multiplier at +/-18% -- this is one factor


def _fetch(kind: str, season: int, ttl: int = 43200) -> pd.DataFrame:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{kind}_{season}.csv"
    if path.exists() and (time.time() - path.stat().st_mtime) < ttl:
        try:
            return pd.read_csv(path)
        except Exception:
            pass
    url = (f"{BASE}?type={kind}&pitchType=&year={season}&team=&min=10&csv=true")
    try:
        r = requests.get(url, timeout=60, headers=HEADERS)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.content.decode("utf-8-sig")))
        df.to_csv(path, index=False)
        return df
    except Exception as e:
        print(f"  [savant] {kind} fetch failed: {e}")
        if path.exists():
            try:
                return pd.read_csv(path)
            except Exception:
                pass
        return pd.DataFrame()


_CACHE: dict[str, dict] = {}


def load(season: int) -> dict:
    """Load and index both leaderboards. Cached per process."""
    key = f"s{season}"
    if key in _CACHE:
        return _CACHE[key]

    bat = _fetch("batter", season)
    pit = _fetch("pitcher", season)

    batters: dict[int, dict[str, dict]] = {}
    if not bat.empty:
        for row in bat.itertuples(index=False):
            pid = int(getattr(row, "player_id"))
            batters.setdefault(pid, {})[getattr(row, "pitch_type")] = {
                "woba": _num(getattr(row, "woba", None)),
                "est_woba": _num(getattr(row, "est_woba", None)),
                "whiff": _num(getattr(row, "whiff_percent", None)),
                "k_pct": _num(getattr(row, "k_percent", None)),
                "slg": _num(getattr(row, "slg", None)),
                "pitches": _num(getattr(row, "pitches", None)) or 0,
                "pa": _num(getattr(row, "pa", None)) or 0,
            }

    pitchers: dict[int, dict[str, dict]] = {}
    if not pit.empty:
        for row in pit.itertuples(index=False):
            pid = int(getattr(row, "player_id"))
            pitchers.setdefault(pid, {})[getattr(row, "pitch_type")] = {
                "usage": _num(getattr(row, "pitch_usage", None)) or 0,
                "woba": _num(getattr(row, "woba", None)),
                "whiff": _num(getattr(row, "whiff_percent", None)),
                "k_pct": _num(getattr(row, "k_percent", None)),
                "pitches": _num(getattr(row, "pitches", None)) or 0,
            }

    # League baseline wOBA per pitch type, to judge a hitter against context.
    lg_by_pitch: dict[str, float] = {}
    if not bat.empty and "woba" in bat.columns:
        grp = bat.groupby("pitch_type")["woba"].mean()
        lg_by_pitch = {k: float(v) for k, v in grp.items() if pd.notna(v)}

    out = {"batters": batters, "pitchers": pitchers, "lg_by_pitch": lg_by_pitch,
           "n_bat": len(batters), "n_pit": len(pitchers)}
    _CACHE[key] = out
    return out


def _num(v):
    try:
        if v is None or pd.isna(v):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def arsenal_matchup(batter_id: int, pitcher_id: int, season: int,
                    baseline_woba: float | None = None) -> dict:
    """
    How this hitter fares against THIS pitcher's specific pitch mix.

    Returns a multiplier on the hitter's offensive rates plus the detail
    behind it, so a recommendation can explain itself. A multiplier of 1.08
    means this arsenal is an ~8% better matchup for him than his season line
    implies.

    Regressed by how many pitches of each type he has actually seen, and
    capped: pitch-type wOBA on a few hundred pitches is informative, not
    gospel, and it is one input among several.
    """
    data = load(season)
    bat = data["batters"].get(batter_id)
    pit = data["pitchers"].get(pitcher_id)
    empty = {"mult": 1.0, "coverage": 0.0, "detail": [], "matchup_woba": None,
             "baseline_woba": baseline_woba, "n_pitch_types": 0}
    if not bat or not pit:
        return empty

    # Weight the hitter's per-pitch results by how often this starter throws it.
    num = den = 0.0
    weighted_pitches = 0.0
    detail = []
    for ptype, pinfo in pit.items():
        usage = pinfo.get("usage") or 0.0
        if usage <= 0:
            continue
        binfo = bat.get(ptype)
        if not binfo:
            continue
        woba = binfo.get("est_woba") or binfo.get("woba")
        seen = binfo.get("pitches") or 0
        if woba is None or seen < MIN_PITCHES:
            continue
        w = usage / 100.0
        num += woba * w
        den += w
        weighted_pitches += seen * w
        detail.append({"pitch": ptype, "usage": usage, "batter_woba": woba,
                       "pitches_seen": seen,
                       "whiff": binfo.get("whiff"),
                       "lg": data["lg_by_pitch"].get(ptype)})

    if den <= 0:
        return empty

    matchup_woba = num / den
    if baseline_woba is None or baseline_woba <= 0:
        # Fall back to the hitter's own overall arsenal-weighted average.
        allw = [(v.get("est_woba") or v.get("woba"), v.get("pitches") or 0)
                for v in bat.values()]
        allw = [(w, p) for w, p in allw if w is not None and p > 0]
        baseline_woba = (sum(w * p for w, p in allw) / sum(p for _, p in allw)
                         if allw else matchup_woba)
    if not baseline_woba:
        return empty

    raw_mult = matchup_woba / baseline_woba
    # Regress toward 1.0 by how much of this arsenal he has actually seen.
    shrink = weighted_pitches / (weighted_pitches + ARSENAL_REG)
    mult = 1.0 + (raw_mult - 1.0) * shrink
    mult = min(max(mult, 1 - MAX_ARSENAL_SWING), 1 + MAX_ARSENAL_SWING)

    detail.sort(key=lambda d: -d["usage"])
    return {"mult": mult, "raw_mult": raw_mult, "coverage": den,
            "matchup_woba": matchup_woba, "baseline_woba": baseline_woba,
            "weighted_pitches": weighted_pitches, "detail": detail,
            "n_pitch_types": len(detail)}


def whiff_matchup(batter_id: int, pitcher_id: int, season: int) -> float:
    """
    Strikeout-rate multiplier from the pitch-mix matchup.

    Feeds the pitcher strikeout prop as well as the batter model: a starter
    who leans on the exact pitch a hitter chases is worth more strikeouts than
    his season K-rate suggests.
    """
    data = load(season)
    bat = data["batters"].get(batter_id)
    pit = data["pitchers"].get(pitcher_id)
    if not bat or not pit:
        return 1.0

    num = den = seen_tot = 0.0
    for ptype, pinfo in pit.items():
        usage = (pinfo.get("usage") or 0.0) / 100.0
        if usage <= 0:
            continue
        binfo = bat.get(ptype)
        if not binfo or (binfo.get("whiff") is None):
            continue
        seen = binfo.get("pitches") or 0
        if seen < MIN_PITCHES:
            continue
        num += binfo["whiff"] * usage
        den += usage
        seen_tot += seen * usage
    if den <= 0:
        return 1.0

    matchup_whiff = num / den
    all_wh = [(v.get("whiff"), v.get("pitches") or 0) for v in bat.values()]
    all_wh = [(w, p) for w, p in all_wh if w is not None and p > 0]
    if not all_wh:
        return 1.0
    base = sum(w * p for w, p in all_wh) / sum(p for _, p in all_wh)
    if base <= 0:
        return 1.0

    raw = matchup_whiff / base
    shrink = seen_tot / (seen_tot + ARSENAL_REG)
    mult = 1.0 + (raw - 1.0) * shrink
    return min(max(mult, 0.85), 1.15)


def describe(matchup: dict, top: int = 3) -> str:
    """One-line explanation of an arsenal edge, for the pick writeup."""
    if not matchup.get("detail"):
        return "no arsenal data"
    parts = []
    for d in matchup["detail"][:top]:
        lg = f" vs lg {d['lg']:.3f}" if d.get("lg") else ""
        parts.append(f"{d['pitch']} {d['usage']:.0f}% -> .{int(d['batter_woba']*1000):03d} wOBA{lg}")
    return "; ".join(parts)


def lineup_whiff_mult(pitcher_id: int, lineup: list[int], season: int,
                      pa_weights: list[float] | None = None) -> dict:
    """
    Whiff multiplier for a WHOLE LINEUP against one pitcher's arsenal.

    A team's season strikeout rate says how whiff-prone the lineup is in
    general. It says nothing about whether these particular hitters flail at
    the pitches THIS starter actually throws. Those are different questions
    and both matter: the White Sox strike out 8.6% more than league average
    overall, and separately whiff 7.2% more than their own norm against
    deGrom's slider-heavy mix. Stacking them is not double counting -- the
    first is a level, the second is a deviation from that hitter's baseline.

    Weighted by expected plate appearances so the leadoff hitter counts more
    than the nine-hole. Falls back to 1.0 for anyone Savant doesn't cover,
    which keeps a partial lineup from skewing the result.
    """
    if not lineup:
        return {"mult": 1.0, "covered": 0, "n": 0, "detail": []}

    if pa_weights is None:
        # Same shape as the batting-order PA curve: ~4.6 down to ~3.8.
        pa_weights = [4.62 - 0.105 * i for i in range(len(lineup))]

    num = den = 0.0
    covered = 0
    detail = []
    for i, bid in enumerate(lineup[:9]):
        w = pa_weights[i] if i < len(pa_weights) else 4.2
        m = whiff_matchup(int(bid), pitcher_id, season)
        if m != 1.0:
            covered += 1
        num += m * w
        den += w
        detail.append({"batter_id": int(bid), "slot": i + 1, "whiff_mult": m})

    mult = (num / den) if den else 1.0
    return {"mult": mult, "covered": covered, "n": len(lineup[:9]),
            "detail": detail}
