"""
Elo-style NFL ratings, scored against the closing moneyline.

Elo is used here rather than a regression because it is sequential by
construction: a game is always rated from games that came before it, so there
is no way to leak future information. That mattered enough in the MLB work --
where a partially-swapped provider let the model read end-of-season batter
lines for the games it was scoring -- to be worth the structural guarantee.

Three NFL-specific pieces:

  margin-of-victory multiplier
      A 3-point win and a 30-point win are different evidence. The log
      multiplier is damped by rating difference so blowouts by heavy favourites
      do not inflate ratings.
  season regression
      Rosters turn over. Ratings pull a third of the way back to the mean
      between seasons; without it a 2015 rating still contaminates 2026.
  home field
      Fitted rather than assumed, and it has genuinely declined over the
      period covered.

The test is not accuracy. It is whether this adds anything to the closing
number, which prices at a 2.72% hold -- tighter than the MLB market where the
game model turned out to be actively harmful.
"""
from __future__ import annotations

import math
from collections import defaultdict

BASE = 1500.0
K = 20.0
SEASON_REGRESS = 0.33     # fraction pulled back to the mean each new season
POINTS_PER_ELO = 25.0     # elo points per point of spread
HOME_FIELD = 55.0         # elo points, fitted below


def win_prob(diff_elo):
    return 1.0 / (1.0 + 10 ** (-diff_elo / 400.0))


def mov_multiplier(margin, diff_elo):
    """Dampened margin-of-victory, the standard 538 form."""
    return math.log(abs(margin) + 1.0) * (2.2 / ((diff_elo * 0.001) + 2.2))


class Elo:
    def __init__(self, k=K, home_field=HOME_FIELD, regress=SEASON_REGRESS):
        self.r = defaultdict(lambda: BASE)
        self.k = k
        self.home_field = home_field
        self.regress = regress
        self._season = None

    def _roll_season(self, season):
        if self._season is None:
            self._season = season
            return
        if season != self._season:
            for t in list(self.r):
                self.r[t] = BASE + (self.r[t] - BASE) * (1.0 - self.regress)
            self._season = season

    def pregame(self, g):
        """(home win prob, expected margin) from ratings BEFORE this game."""
        self._roll_season(g["season"])
        diff = self.r[g["home"]] - self.r[g["away"]] + self.home_field
        return win_prob(diff), diff / POINTS_PER_ELO

    def update(self, g):
        diff = self.r[g["home"]] - self.r[g["away"]] + self.home_field
        exp = win_prob(diff)
        margin = g["margin"]
        actual = 1.0 if margin > 0 else (0.5 if margin == 0 else 0.0)
        mult = mov_multiplier(margin if margin != 0 else 1, diff if margin > 0 else -diff)
        shift = self.k * mult * (actual - exp)
        self.r[g["home"]] += shift
        self.r[g["away"]] -= shift


def walk_forward(rows, warmup_seasons=2):
    """Rate every game from prior games only. Returns (row, p_home, exp_margin)."""
    rows = sorted(rows, key=lambda g: (g["season"], g["week"], g["date"] or ""))
    first = min(g["season"] for g in rows)
    e = Elo()
    out = []
    for g in rows:
        p, m = e.pregame(g)
        if g["season"] >= first + warmup_seasons:
            out.append((g, p, m))
        e.update(g)
    return out


def tune(rows, ks=(12, 16, 20, 24, 28), hfs=(35, 45, 55, 65), regs=(0.20, 0.33, 0.45)):
    """Pick k / home field / regression by Brier score on walk-forward output."""
    best = None
    ordered = sorted(rows, key=lambda g: (g["season"], g["week"], g["date"] or ""))
    first = min(g["season"] for g in ordered)
    for k in ks:
        for hf in hfs:
            for rg in regs:
                e = Elo(k=k, home_field=hf, regress=rg)
                se = n = 0
                for g in ordered:
                    p, _ = e.pregame(g)
                    if g["season"] >= first + 2:
                        y = 1.0 if g["margin"] > 0 else (0.5 if g["margin"] == 0 else 0.0)
                        se += (p - y) ** 2
                        n += 1
                    e.update(g)
                br = se / n
                if best is None or br < best[0]:
                    best = (br, k, hf, rg)
    return best
