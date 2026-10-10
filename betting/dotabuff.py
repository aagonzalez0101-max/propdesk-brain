"""Dota per-player scoreboards from Dotabuff.

Why this exists: the project's Dota source was OpenDota, which has been
returning HTTP 522 on every request (their origin is down). The alternatives
were checked on 2026-09-03 --

    STRATZ api  403, needs a key        datdota /api  returns the SPA shell
    spectral.gg 403                     escorenews    403
    OpenDota    522 on every retry      Liquipedia    1 parse request / 30s

Dotabuff works, but ONLY with a full browser header set: a bare User-Agent gets
403 on /esports/matches and /matches/<id> while /esports/leagues succeeds, which
looks like a working site until you hit the pages you actually need.
"""
from __future__ import annotations

import gzip
import os
import re
import time
import urllib.request

BASE = "https://www.dotabuff.com"
CACHE = "dota_cache"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip",
    "Referer": "https://www.google.com/",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "cross-site",
    "sec-ch-ua": '"Chromium";v="126", "Not:A-Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}
_last = [0.0]
GAP = 2.5          # be polite; Dotabuff throttles bursts


def _get(path: str, name: str, ttl: int = 2592000) -> str:
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, re.sub(r"[^A-Za-z0-9_.-]", "_", name)[:120] + ".html")
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < ttl:
        return open(p, encoding="utf-8").read()
    for attempt in range(4):
        w = GAP - (time.time() - _last[0])
        if w > 0:
            time.sleep(w)
        try:
            r = urllib.request.urlopen(
                urllib.request.Request(BASE + path, headers=HEADERS), timeout=45)
            b = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                b = gzip.decompress(b)
            _last[0] = time.time()
            t = b.decode("utf-8", "replace")
            open(p, "w", encoding="utf-8").write(t)
            return t
        except Exception:
            _last[0] = time.time()
            time.sleep(5 * (attempt + 1))
    return ""


_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)


def _txt(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def match(match_id: str | int) -> list[dict]:
    """Per-player rows for one Dota match: player, hero, k, d, a, net.

    Rows are keyed off the player anchor (class "link-type-player"), not the
    cell order -- the name cell also carries the lane tooltip, so splitting on
    <td> alone merges player, role and hero into one string. Keying off the
    anchor also drops the per-team "Lane Outcome" summary rows, which otherwise
    look like a sixth player holding the team's total kills.
    """
    html = _get("/matches/%s" % match_id, "db_m_%s" % match_id)
    if not html:
        return []
    out = []
    for tbl in re.findall(r'<table class="match-team-table.*?</table>', html, re.S):
        for tr in re.findall(r"<tr[^>]*>.*?</tr>", tbl, re.S):
            who = re.search(r'link-type-player"[^>]*href="/players/(\d+)"[^>]*>(.*?)</a>', tr, re.S)
            if not who:
                continue                      # header, tab-button or team-total row
            hero = re.search(r'href="/heroes/([a-z0-9-]+)"', tr)
            side = "radiant" if "faction-radiant" in tr else "dire"
            cells = [_txt(c) for c in _CELL.findall(tr)]
            nums = []
            for c in cells[5:9]:
                c = c.replace(",", "")
                nums.append(float(c) if re.fullmatch(r"-?\d+(\.\d+)?", c) else None)
            if len(nums) < 3 or nums[0] is None or nums[1] is None:
                continue
            out.append({"player": _txt(who.group(2)), "player_id": who.group(1),
                        "hero": hero.group(1) if hero else "",
                        "side": side, "k": nums[0], "d": nums[1], "a": nums[2],
                        "net": nums[3] if len(nums) > 3 else None,
                        "match": str(match_id)})
    return out


def esports_matches() -> list[str]:
    """Recent professional match ids from the esports listing."""
    html = _get("/esports/matches", "db_esports_matches", ttl=1800)
    return sorted(set(re.findall(r"/matches/(\d+)", html)), reverse=True)
