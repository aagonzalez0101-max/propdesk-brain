"""Projected MLB batting orders from Rotowire.

Why: the HRR model needs a batting-order SLOT (the slot term swings from 49.6%
leading off to 63.5% batting ninth), and MLB's own StatsAPI only exposes a
lineup once a club posts it -- typically 2-3 hours before first pitch. On an
all-evening slate that means a board built at midday prices almost no batters:
on 2026-09-04, 1 of 16 games had a posted order and 250 Underdog HRR lines went
unpriced.

Rotowire publishes PROJECTED orders well ahead of that, flagged confirmed vs
expected. Projected slots are not free -- a guess that puts a hitter in the
wrong third of the order mis-prices him -- so the source is recorded on every
row and confirmed orders always win when both exist.
"""
from __future__ import annotations

import gzip
import html as _html
import re
import urllib.request

URL = "https://www.rotowire.com/baseball/daily-lineups.php"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

TEAM = {
    "Diamondbacks": "Arizona Diamondbacks", "Braves": "Atlanta Braves",
    "Orioles": "Baltimore Orioles", "Red Sox": "Boston Red Sox",
    "Cubs": "Chicago Cubs", "White Sox": "Chicago White Sox",
    "Reds": "Cincinnati Reds", "Guardians": "Cleveland Guardians",
    "Rockies": "Colorado Rockies", "Tigers": "Detroit Tigers",
    "Astros": "Houston Astros", "Royals": "Kansas City Royals",
    "Angels": "Los Angeles Angels", "Dodgers": "Los Angeles Dodgers",
    "Marlins": "Miami Marlins", "Brewers": "Milwaukee Brewers",
    "Twins": "Minnesota Twins", "Mets": "New York Mets",
    "Yankees": "New York Yankees", "Athletics": "Athletics",
    "Phillies": "Philadelphia Phillies", "Pirates": "Pittsburgh Pirates",
    "Padres": "San Diego Padres", "Giants": "San Francisco Giants",
    "Mariners": "Seattle Mariners", "Cardinals": "St. Louis Cardinals",
    "Rays": "Tampa Bay Rays", "Rangers": "Texas Rangers",
    "Blue Jays": "Toronto Blue Jays", "Nationals": "Washington Nationals",
}

_BOX = re.compile(r'<div class="lineup__box">(.*?)</ul>\s*</div>', re.S)
_MTEAM = re.compile(r'lineup__mteam is-(visit|home)">\s*([A-Za-z .]+?)\s*<span', re.S)
_LIST = re.compile(r'<ul class="lineup__list is-(visit|home)">(.*?)</ul>', re.S)
_STATUS = re.compile(r'lineup__status([^"]*)"', re.S)
_PLAYER = re.compile(r'<li class="lineup__player">.*?<a title="([^"]+)"', re.S)


def _fetch():
    req = urllib.request.Request(URL, headers={
        "User-Agent": UA, "Accept": "text/html,*/*", "Accept-Encoding": "gzip",
        "Referer": "https://www.google.com/"})
    r = urllib.request.urlopen(req, timeout=45)
    b = r.read()
    if r.headers.get("Content-Encoding") == "gzip":
        b = gzip.decompress(b)
    return b.decode("utf-8", "replace")


def projected(html_text=None):
    """{team name: {"slots": [9 player names in order], "status": str}}"""
    h = html_text if html_text is not None else _fetch()
    out = {}
    # split on the per-game container; the box regex above can over-match, so
    # anchor on the matchup header instead and slice to the next one
    starts = [m.start() for m in re.finditer(r'lineup__mteam is-visit', h)]
    starts.append(len(h))
    for i in range(len(starts) - 1):
        blk = h[starts[i]:starts[i + 1]]
        teams = dict((side, name.strip()) for side, name in _MTEAM.findall(blk))
        vis = re.search(r'lineup__mteam is-visit">\s*([A-Za-z .]+?)\s*<span', blk)
        hom = re.search(r'lineup__mteam is-home">\s*([A-Za-z .]+?)\s*<span', blk)
        names = {"visit": vis.group(1).strip() if vis else None,
                 "home": hom.group(1).strip() if hom else None}
        st = _STATUS.search(blk)
        status = (st.group(1) or "").replace("is-", "").strip() if st else "unknown"
        for side, body in _LIST.findall(blk):
            team = TEAM.get(names.get(side) or "")
            if not team:
                continue
            players = [_html.unescape(x) for x in _PLAYER.findall(body)][:9]
            if len(players) == 9:
                out[team] = {"slots": players, "status": status}
    return out


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", write_through=True)
    d = projected()
    print("teams with a 9-man order: %d" % len(d))
    for t, v in sorted(d.items())[:6]:
        print("  %-24s %-10s %s" % (t, v["status"], ", ".join(v["slots"][:4]) + " ..."))
