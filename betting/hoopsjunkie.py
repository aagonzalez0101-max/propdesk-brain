"""
hoopsjunkie.io -- play-type splits and team ratings the ESPN feed cannot give.

Two gotchas that make the obvious approach fail:

  1. A plain request gets 403. It needs a browser User-Agent AND a Referer;
     without the Referer the site refuses.
  2. The page looks client-rendered -- no <script src>, no __NEXT_DATA__, no
     JSON blob -- but the numbers ARE server-rendered into absolutely-positioned
     tooltip divs. The label sits in one <span> and "freq% - eff - rank" in the
     next, separated by HTML comments (<!-- -->) that must be stripped first.

What this unlocks: transition / early offense / putbacks / half court /
mid clock / late clock, for offence and defence, with frequency, points per 100
and league rank. That is the "what a team actually DOES" layer -- the thing that
showed Golden State's defence was top-3 in all six categories while New York's
only weak spots were actions Golden State never runs.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "hoopsjunkie"
BASE = "https://hoopsjunkie.io/wnba/team"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",     # without this the site 403s
}
MIN_INTERVAL = 1.5
_last = 0.0

# hoopsjunkie slug per ESPN team name
SLUG = {
    "Atlanta Dream": "atl", "Chicago Sky": "chi", "Connecticut Sun": "con",
    "Dallas Wings": "dal", "Golden State Valkyries": "gsv", "Indiana Fever": "ind",
    "Las Vegas Aces": "lva", "Los Angeles Sparks": "las", "Minnesota Lynx": "min",
    "New York Liberty": "nyl", "Phoenix Mercury": "phx", "Seattle Storm": "sea",
    "Washington Mystics": "was", "Portland Fire": "pdx", "Toronto Tempo": "tor",
}


def _get(slug: str, ttl: int = 21600) -> str:
    global _last
    p = CACHE / f"{slug}.html"
    if p.exists() and (time.time() - p.stat().st_mtime) < ttl:
        return p.read_text(encoding="utf-8", errors="replace")
    wait = MIN_INTERVAL - (time.time() - _last)
    if wait > 0:
        time.sleep(wait)
    r = requests.get(f"{BASE}/{slug}", headers=HEADERS, timeout=30)
    _last = time.time()
    r.raise_for_status()
    # the server sends no charset, so requests guesses latin-1 and the
    # middot separator arrives as two bytes (0xC2 0xB7) instead of one char
    r.encoding = "utf-8"
    CACHE.mkdir(parents=True, exist_ok=True)
    p.write_text(r.text, encoding="utf-8")
    return r.text


def _clean(s: str) -> str:
    return re.sub(r"<!--.*?-->", "", s)


def play_types(team_name: str) -> list[dict]:
    """
    Every play-type tooltip on the page, in document order.

    The page renders offence first then defence, so the first occurrence of a
    label is the team's own offence and the second is what it allows.
    """
    slug = SLUG.get(team_name)
    if not slug:
        return []
    h = _clean(_get(slug))
    out = []
    pat = (r'uppercase[^>]*>([^<]+)</span>\s*<span[^>]*>\s*<span[^>]*>'
           r'([\d.]+)\s*%\s*</span>\s*·\s*([\d.]+)\s*·\s*(\d+)(?:st|nd|rd|th)')
    for m in re.finditer(pat, h):
        out.append({"action": m.group(1).strip(), "freq": float(m.group(2)),
                    "per100": float(m.group(3)), "rank": int(m.group(4))})
    half = len(out) // 2
    for i, d in enumerate(out):
        d["side"] = "OFF" if i < half else "DEF"
    return out


def summary(team_name: str) -> dict:
    """Offence and defence keyed by action name."""
    rows = play_types(team_name)
    return {"OFF": {r["action"]: r for r in rows if r["side"] == "OFF"},
            "DEF": {r["action"]: r for r in rows if r["side"] == "DEF"}}


def ratings(team_name: str) -> dict:
    """
    The header stat block: Pace, Off Rtg, Def Rtg, Net Rtg with league ranks.

    Labels are mixed case ("Net Rtg", not "NET RTG"), the rank sits in its own
    div after a middot span, and the value lives in a later font-black div. A
    search for uppercase labels finds nothing, which is why this looked absent.
    """
    slug = SLUG.get(team_name)
    if not slug:
        return {}
    h = _clean(_get(slug))
    pat = (r'uppercase[^>]*>([A-Za-z][A-Za-z. ]{2,14})</div>'
           r'.{0,400}?tracking-tighter[^>]*>(\d+)(?:st|nd|rd|th)</div>'
           r'.{0,320}?font-black[^>]*>\s*<span[^>]*>([+\-]?[\d.]+)</span>')
    out = {}
    for m in re.finditer(pat, h, re.S):
        out[m.group(1).strip()] = {"rank": int(m.group(2)),
                                   "value": float(m.group(3))}
    return out
