"""
Team and player STYLE profiles, built from ESPN box scores.

The point of this module is the matchup read that raw efficiency ratings miss:
a dominant interior scorer against a team that cannot defend the paint is a
structural edge, and it persists. Recent form does not -- that was measured
and it failed.

stats.wnba.com carries true shot-location data but its shot-location endpoint
times out under any real request rate, so the zone read is reconstructed from
box scores instead:

    three-point rate = 3PA / FGA          how much a team lives at the arc
    free-throw rate  = FTA / FGA          proxy for rim pressure; you earn
                                          free throws by attacking inside
    two-point rate   = the remainder      paint and mid-range

Coarser than tracking data, but it separates a team that attacks the rim from
one that settles for threes, and it does the same for what a DEFENCE allows.
Players get the same treatment, which is what identifies the "insane big":
high rebound rate, high free-throw rate, few threes, efficient inside.
"""
from __future__ import annotations

import statistics as st
from dataclasses import dataclass, field

from . import wnbadata as W
from . import wnbamodel as M


@dataclass
class TeamProfile:
    team_id: str
    games: int
    # own offence
    three_rate: float          # 3PA / FGA
    ft_rate: float             # FTA / FGA -- rim pressure
    two_pct: float             # 2P%
    three_pct: float
    efg: float
    oreb_rate: float
    # what the defence ALLOWS
    opp_three_rate: float
    opp_ft_rate: float
    opp_two_pct: float         # the paint-defence number that matters most
    opp_three_pct: float
    opp_efg: float
    dreb_rate: float

    def paint_defence_z(self, league: "LeagueProfile") -> float:
        """
        How well this team defends inside, in standard deviations.

        Positive is GOOD defence. Built from two-point percentage allowed and
        how often opponents get to the line -- a team that surrenders a high
        2P% and fouls a lot cannot protect the rim.
        """
        z_two = (league.opp_two_pct - self.opp_two_pct) / max(league.sd_opp_two_pct, 1e-6)
        z_ft = (league.opp_ft_rate - self.opp_ft_rate) / max(league.sd_opp_ft_rate, 1e-6)
        return 0.7 * z_two + 0.3 * z_ft

    def perimeter_defence_z(self, league: "LeagueProfile") -> float:
        """Positive is good three-point defence: low rate allowed, low pct."""
        z_pct = (league.opp_three_pct - self.opp_three_pct) / max(league.sd_opp_three_pct, 1e-6)
        z_rate = (league.opp_three_rate - self.opp_three_rate) / max(league.sd_opp_three_rate, 1e-6)
        return 0.7 * z_pct + 0.3 * z_rate


@dataclass
class LeagueProfile:
    three_rate: float
    ft_rate: float
    two_pct: float
    three_pct: float
    opp_two_pct: float
    opp_ft_rate: float
    opp_three_pct: float
    opp_three_rate: float
    sd_opp_two_pct: float
    sd_opp_ft_rate: float
    sd_opp_three_pct: float
    sd_opp_three_rate: float


@dataclass
class PlayerProfile:
    player_id: str
    name: str
    team_id: str
    games: int
    mpg: float
    min_sd: float
    # per-36 production
    pts36: float
    reb36: float
    ast36: float
    # style
    three_rate: float          # 3PA / FGA -- low means an interior player
    ft_rate: float             # FTA / FGA -- high means he attacks the rim
    reb_rate: float            # rebounds per 36, relative to league
    usage: float               # (FGA + 0.44*FTA + TO) per 36
    interior_score: float = 0.0   # how much of his game happens inside

    @property
    def is_big(self) -> bool:
        return self.interior_score > 0.5


def _rate(num: float, den: float, default: float = 0.0) -> float:
    return num / den if den else default


def build_profiles(cutoff: str | None = None, start: str = "2026-05-01"
                   ) -> tuple[dict[str, TeamProfile], LeagueProfile,
                              dict[str, PlayerProfile]]:
    """
    Team and player style profiles from every completed game before `cutoff`.

    Same point-in-time discipline as the ratings: a cutoff means the profile
    only sees games that had already been played.
    """
    end = cutoff or W.date.today().isoformat()
    games = [g for g in W.games_between(start, end)
             if g["final"] and g["date"] < end]

    team: dict[str, dict] = {}
    player: dict[str, dict] = {}

    for g in games:
        box = W.boxscore(g["id"])
        if len(box) != 2:
            continue
        hid, aid = str(g["home_id"]), str(g["away_id"])
        if hid not in box or aid not in box:
            continue
        sides = {hid: M.team_totals(box[hid]), aid: M.team_totals(box[aid])}
        if any(s["fga"] < 30 for s in sides.values()):
            continue

        for tid, opp_id in ((hid, aid), (aid, hid)):
            own, opp = sides[tid], sides[opp_id]
            d = team.setdefault(tid, {"g": 0, **{k: 0.0 for k in (
                "fga", "fgm", "tpa", "tpm", "fta", "ftm", "oreb", "dreb",
                "o_fga", "o_fgm", "o_tpa", "o_tpm", "o_fta", "o_oreb", "o_dreb")}})
            d["g"] += 1
            for k in ("fga", "fgm", "tpa", "tpm", "fta", "ftm", "oreb", "dreb"):
                d[k] += own[k]
            d["o_fga"] += opp["fga"]; d["o_fgm"] += opp["fgm"]
            d["o_tpa"] += opp["tpa"]; d["o_tpm"] += opp["tpm"]
            d["o_fta"] += opp["fta"]; d["o_oreb"] += opp["oreb"]
            d["o_dreb"] += opp["dreb"]

            for r in box[tid]:
                if r["min"] <= 0:
                    continue
                p = player.setdefault(str(r["id"]), {
                    "name": r["name"], "team": tid, "g": 0,
                    "min": 0.0, "mins": [], **{k: 0.0 for k in (
                        "pts", "reb", "ast", "fga", "fgm", "tpa", "tpm",
                        "fta", "to")}})
                p["g"] += 1
                p["min"] += r["min"]
                p["mins"].append(r["min"])
                p["team"] = tid
                for k in ("pts", "reb", "ast", "fga", "fgm", "tpa", "tpm", "fta", "to"):
                    p[k] += r[k]

    # ---- team profiles ----
    profiles: dict[str, TeamProfile] = {}
    for tid, d in team.items():
        two_a = d["fga"] - d["tpa"]
        two_m = d["fgm"] - d["tpm"]
        o_two_a = d["o_fga"] - d["o_tpa"]
        o_two_m = d["o_fgm"] - d["o_tpm"]
        profiles[tid] = TeamProfile(
            team_id=tid, games=d["g"],
            three_rate=_rate(d["tpa"], d["fga"]),
            ft_rate=_rate(d["fta"], d["fga"]),
            two_pct=_rate(two_m, two_a),
            three_pct=_rate(d["tpm"], d["tpa"]),
            efg=_rate(d["fgm"] + 0.5 * d["tpm"], d["fga"]),
            oreb_rate=_rate(d["oreb"], d["oreb"] + d["o_dreb"]),
            opp_three_rate=_rate(d["o_tpa"], d["o_fga"]),
            opp_ft_rate=_rate(d["o_fta"], d["o_fga"]),
            opp_two_pct=_rate(o_two_m, o_two_a),
            opp_three_pct=_rate(d["o_tpm"], d["o_tpa"]),
            opp_efg=_rate(d["o_fgm"] + 0.5 * d["o_tpm"], d["o_fga"]),
            dreb_rate=_rate(d["dreb"], d["dreb"] + d["o_oreb"]))

    vals = list(profiles.values())
    league = LeagueProfile(
        three_rate=st.mean([p.three_rate for p in vals]),
        ft_rate=st.mean([p.ft_rate for p in vals]),
        two_pct=st.mean([p.two_pct for p in vals]),
        three_pct=st.mean([p.three_pct for p in vals]),
        opp_two_pct=st.mean([p.opp_two_pct for p in vals]),
        opp_ft_rate=st.mean([p.opp_ft_rate for p in vals]),
        opp_three_pct=st.mean([p.opp_three_pct for p in vals]),
        opp_three_rate=st.mean([p.opp_three_rate for p in vals]),
        sd_opp_two_pct=st.pstdev([p.opp_two_pct for p in vals]) or 0.01,
        sd_opp_ft_rate=st.pstdev([p.opp_ft_rate for p in vals]) or 0.01,
        sd_opp_three_pct=st.pstdev([p.opp_three_pct for p in vals]) or 0.01,
        sd_opp_three_rate=st.pstdev([p.opp_three_rate for p in vals]) or 0.01)

    # ---- player profiles ----
    players: dict[str, PlayerProfile] = {}
    for pid, p in player.items():
        if p["g"] < 5 or p["min"] < 60:
            continue
        per36 = 36.0 / p["min"]
        three_rate = _rate(p["tpa"], p["fga"], 0.0)
        ft_rate = _rate(p["fta"], p["fga"], 0.0)
        reb36 = p["reb"] * per36
        players[pid] = PlayerProfile(
            player_id=pid, name=p["name"], team_id=p["team"], games=p["g"],
            mpg=p["min"] / p["g"], min_sd=st.pstdev(p["mins"]) if len(p["mins"]) > 1 else 0.0,
            pts36=p["pts"] * per36, reb36=reb36, ast36=p["ast"] * per36,
            three_rate=three_rate, ft_rate=ft_rate, reb_rate=reb36,
            usage=(p["fga"] + 0.44 * p["fta"] + p["to"]) * per36)

    # Interior score: a big shoots few threes, earns free throws, and rebounds.
    if players:
        rb = [p.reb36 for p in players.values()]
        mu_rb, sd_rb = st.mean(rb), st.pstdev(rb) or 1.0
        for p in players.values():
            z_rb = (p.reb36 - mu_rb) / sd_rb
            not_three = 1.0 - min(p.three_rate / 0.55, 1.0)
            p.interior_score = round(
                0.45 * not_three + 0.40 * _sigmoid(z_rb) + 0.15 * min(p.ft_rate / 0.35, 1.0), 3)

    return profiles, league, players


def _sigmoid(x: float) -> float:
    import math
    return 1.0 / (1.0 + math.exp(-x))


def interior_mismatch(player: PlayerProfile, defence: TeamProfile,
                      league: LeagueProfile) -> dict:
    """
    The read you actually want: a dominant interior player against a team
    that cannot defend the paint.

    Returns an edge in standard deviations. Positive means the matchup favours
    the player -- he plays inside and they cannot guard inside.
    """
    d_z = defence.paint_defence_z(league)      # positive = good defence
    edge = player.interior_score * (-d_z)      # weak D + interior player = +
    return {
        "player": player.name,
        "interior_score": player.interior_score,
        "def_paint_z": round(d_z, 2),
        "edge_z": round(edge, 3),
        "opp_two_pct_allowed": round(defence.opp_two_pct, 4),
        "league_two_pct_allowed": round(league.opp_two_pct, 4),
    }


# ------------------------------------------------------- player prop projection

MIN_REG_GAMES = 6.0     # games before a player's own minutes outweigh the prior
RATE_REG_MIN = 220.0    # minutes before per-36 rates are trusted over league

# Measured over 1,241 point-in-time player-games: every projection came in
# slightly LOW. Minutes -0.40, points -0.51, rebounds -0.13, assists -0.20.
# The cause is regression toward a season mean that itself trails a player's
# current role -- rotations expand as the season goes on. Correcting the
# measured bias rather than leaving it to accumulate across every prop.
BIAS_MIN = 0.40
BIAS_PTS = 0.51
BIAS_REB = 0.13
BIAS_AST = 0.20


def project_player(log: list[dict], cutoff: str, opp: TeamProfile | None,
                   league: LeagueProfile | None, opp_pace: float = 1.0,
                   recent_n: int = 10) -> dict | None:
    """
    Project one player's line from games played BEFORE `cutoff`.

    Minutes get their own treatment because in basketball they are the stable
    part -- a starter's minutes have a standard deviation of 3-5 against a mean
    near 30, which is why props here are tractable where baseball's innings and
    football's snaps are not.

    Rates are regressed toward the player's own season rather than the league,
    since a rotation player's role is genuinely different from a starter's.
    """
    hist = [g for g in log if g["date"] and g["date"] < cutoff and g["min"] > 0]
    if len(hist) < 8:
        return None

    recent = hist[-recent_n:]
    mins = [g["min"] for g in hist]
    r_mins = [g["min"] for g in recent]

    # Minutes: recent form matters more than season for role, so weight it,
    # then regress by how many recent games there are.
    w = len(recent) / (len(recent) + MIN_REG_GAMES)
    exp_min = w * st.mean(r_mins) + (1 - w) * st.mean(mins)
    min_sd = st.pstdev(mins) if len(mins) > 1 else 4.0

    tot_min = sum(mins)
    per36 = 36.0 / tot_min if tot_min else 0.0
    rates = {k: sum(g[k] for g in hist) * per36
             for k in ("pts", "reb", "ast", "fga", "fta", "tpa", "to")}

    # Opponent adjustment. Pace moves every counting stat; the defensive
    # quality term is deliberately small because a single team's defence moves
    # one player's line far less than the market seems to think.
    pace_mult = opp_pace
    def_mult = 1.0
    if opp is not None and league is not None:
        # weaker interior defence -> more rebounds available off misses is NOT
        # the right read: a bad defence concedes makes, which REDUCES rebounds.
        def_mult = 1.0 + (opp.opp_two_pct - league.opp_two_pct) * -0.4

    exp_min += BIAS_MIN
    out = {"exp_min": exp_min, "min_sd": min_sd, "games": len(hist)}
    for k, v in rates.items():
        out[f"{k}36"] = v
    scale = exp_min / 36.0 * pace_mult
    out["pts"] = rates["pts"] * scale * def_mult + BIAS_PTS
    out["reb"] = rates["reb"] * scale * (2.0 - def_mult) + BIAS_REB
    out["ast"] = rates["ast"] * scale + BIAS_AST
    out["pra"] = out["pts"] + out["reb"] + out["ast"]

    # Empirical spread of each stat, for turning a projection into a probability.
    for k, key in (("pts", "pts"), ("reb", "reb"), ("ast", "ast")):
        vals = [g[key] for g in hist]
        out[f"{k}_sd"] = st.pstdev(vals) if len(vals) > 1 else 1.0
    pra_vals = [g["pts"] + g["reb"] + g["ast"] for g in hist]
    out["pra_sd"] = st.pstdev(pra_vals) if len(pra_vals) > 1 else 1.0
    return out


def over_prob(mean: float, sd: float, line: float) -> float:
    """P(stat > line) from a projected mean and empirical spread."""
    import math
    if sd <= 0:
        return 1.0 if mean > line else 0.0
    z = (mean - line) / sd
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
