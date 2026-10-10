"""
Valorant data layer -- vlr.gg. Free, no key, no auth.

Why vlr.gg and not an API: every Valorant "API" is either paid (vlrggapi returns
402), down (vlr.orlandomm.net 503), or nonexistent. vlr.gg serves the full
scoreboard in server-rendered HTML, so it is the only free source that actually
works. HLTV, the CS2 equivalent, blocks every request with a 403 -- Valorant is
the esport we can actually get history for.

The markup is not the old table layout most scrapers assume. vlr.gg now renders
`ovw-row` / `ovw-cell` divs keyed by `data-col`, and the kills/deaths/assists
triple is nested one level deeper inside `ovw-cell mod-kda` as
`ovw-kda-stat[data-col=kills]`. A parser looking for <td> finds nothing, which
is why the obvious approach returns zero rows.

Every stat carries three values -- `mod-both`, `mod-t`, `mod-ct` -- for overall,
attack and defence. We take `mod-both`; the side splits are kept available
because attack/defence imbalance is a real source of prop edge.

Underdog prices "Kills on Maps 1+2", so per-map rows are what matter: the series
total is the sum of the first two maps regardless of whether a third is played.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "valorant"
BASE = "https://www.vlr.gg"
HEADERS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/126.0 Safari/537.36")}

MIN_INTERVAL = 1.2          # be a good citizen; vlr.gg is a free community site
_last = 0.0


def _get(url: str, name: str | None = None, ttl: int = 2592000) -> str:
    """Rate-limited fetch with disk cache. A finished match never changes."""
    global _last
    if name:
        p = CACHE / f"{name}.html"
        if p.exists() and (time.time() - p.stat().st_mtime) < ttl:
            return p.read_text(encoding="utf-8", errors="replace")
    wait = MIN_INTERVAL - (time.time() - _last)
    if wait > 0:
        time.sleep(wait)
    r = requests.get(url, headers=HEADERS, timeout=30)
    _last = time.time()
    r.raise_for_status()
    if name:
        CACHE.mkdir(parents=True, exist_ok=True)
        (CACHE / f"{name}.html").write_text(r.text, encoding="utf-8")
    return r.text


def _both(blk: str) -> str:
    """The overall value of a stat cell, ignoring the attack/defence split."""
    m = re.search(r'side mod-both[^>]*>\s*([^<]*?)\s*<', blk)
    return m.group(1) if m else ""


def _num(s: str, default: float = 0.0) -> float:
    s = (s or "").replace("%", "").replace("+", "")
    try:
        return float(s)
    except ValueError:
        return default


def results_page(page: int = 1) -> list[dict]:
    """Finished matches, newest first. Each page holds ~50."""
    html = _get(f"{BASE}/matches/results/?page={page}", name=f"results_{page}", ttl=3600)
    out, seen = [], set()
    for mid, slug in re.findall(r'href="/(\d{5,8})/([a-z0-9\-]+)"', html):
        if mid in seen:
            continue
        seen.add(mid)
        out.append({"id": mid, "slug": slug})
    return out


def match(match_id: str, slug: str) -> dict:
    """
    One series: metadata plus per-player, per-map stat lines.

    Returns {"id", "event", "final", "maps": [{"map", "rows": [...]}]}.
    The all-maps summary table is skipped -- per-map rows are the unit Underdog
    actually prices, and summing them recovers any series total we want.
    """
    html = _get(f"{BASE}/{match_id}/{slug}/?game=all&tab=overview",
                name=f"m_{match_id}")
    event = re.search(r'match-header-event-series[^>]*>\s*([^<]+)', html)
    status = re.search(r'match-header-vs-note[^>]*>\s*([^<]+)', html)

    # Each map is its own vm-stats-game block; the "all" block has data-game-id="all"
    blocks = re.findall(r'<div class="vm-stats-game[^"]*" data-game-id="([^"]+)">(.*?)'
                        r'(?=<div class="vm-stats-game[^"]*" data-game-id=|$)', html, re.S)
    maps = []
    for gid, blk in blocks:
        if gid == "all":
            continue
        mp = re.search(r'class="map"[^>]*>\s*<div[^>]*>\s*<span[^>]*>\s*([A-Za-z]+)', blk)
        rows = [r for r in (_row(x) for x in
                            re.split(r'<div class="ovw-row">', blk)[1:]) if r]
        # Rounds is THE variable. A 13-3 map is 16 rounds of opportunity; a
        # 13-11 is 24. Kills per map silently confounds a player's skill with
        # how lopsided his team's games happened to be, so every rate here is
        # per ROUND and gets multiplied back by expected rounds at projection
        # time -- the same shape as innings pitched or minutes played.
        sc = re.findall(r'class="score[^"]*"[^>]*>\s*(\d+)\s*<', blk)
        rounds = sum(int(x) for x in sc[:2]) if len(sc) >= 2 else 0
        if rows and rounds:
            for r in rows:
                r["rounds"] = rounds
                r["kpr"] = r["k"] / rounds
            maps.append({"map": mp.group(1).strip() if mp else "?",
                         "rounds": rounds, "score": [int(x) for x in sc[:2]],
                         "rows": rows})
    return {"id": match_id, "slug": slug,
            "event": event.group(1).strip() if event else "",
            "final": bool(status and "final" in status.group(1).lower()),
            "maps": maps}


def _row(row: str) -> dict | None:
    nick = re.search(r'ovw-player-name text-of">([^<]+)<', row)
    if not nick:
        return None
    team = re.search(r'ovw-player-tag ge-text-light">\s*([^<]+?)\s*<', row)
    agents = re.findall(r'/agents/([a-z0-9\-]+)\.png', row)

    d = {"player": nick.group(1).strip(),
         "team": team.group(1).strip() if team else "",
         "agents": agents}
    # kills/deaths/assists live inside the mod-kda cell, not as top-level data-col
    for col in ("kills", "deaths", "assists"):
        m = re.search(rf'ovw-kda-stat" data-col="{col}">(.*?)</span></span>', row, re.S)
        d[col[0] if col != "assists" else "a"] = _num(_both(m.group(1))) if m else 0.0
    for col in ("rating2", "acs", "adr", "kast", "hsp", "fb", "fd"):
        m = re.search(rf'ovw-cell" data-col="{col}">(.*?)</div>', row, re.S)
        d[col] = _num(_both(m.group(1))) if m else 0.0
    return d
