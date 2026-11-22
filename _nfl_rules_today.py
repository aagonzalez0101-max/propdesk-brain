"""NFL TESTED-RULE SCREEN for today's PP full-game lines (11/21). Rules from _nfl_research.py (walk-forward W04-W09, pregame prices):
  R1  last 3 all this side + opp allows most (top 8 vs pos+stat) + RB          48-15  76.2%
  R2  UNDER + volume falling (L3 <= 85% of season) + team underdog 3+         82-38  68.3%
  R3  UNDER + team favoured 3+ + market 52%+ this side                         44-20  68.8%  (needs sharp price; skipped when none)
  R4  UNDER + season 75%+ this side + team underdog 3+                        129-65  66.5%
  R5  UNDER + volume falling + opp allows most (top 8)                         42-22  65.6%
Game stats rebuilt from nflverse play-by-play (through the latest week), spreads from ESPN.
    python _nfl_rules_today.py 2026-11-22
"""
import sys, json, sqlite3, collections, datetime, urllib.request
import pandas as pd
import _nfl_period_fs as F

DAY = sys.argv[1] if len(sys.argv) > 1 else datetime.date.today().isoformat()
STAT = {"Receiving Yards": ("rec_yds", "tgt"), "Rec Targets": ("tgt", "tgt"), "Receptions": ("rec", "tgt"),
        "Rush Yards": ("rush_yds", "car"), "Rush Attempts": ("car", "car"), "Rush+Rec Yds": ("rush_yds+rec_yds", "car+tgt"),
        "Pass Yards": ("pass_yds", "att"), "Pass Attempts": ("att", "att"), "Pass Completions": ("cmp", "att")}
ev = lambda e, s: sum(s.get(k, 0) for k in e.split("+"))
FIX = {"JAC": "JAX", "LAR": "LA", "WSH": "WAS"}


def games():
    d = pd.read_parquet("data/nflverse/fresh/pbp_2026.parquet", columns=["game_id", "week", "posteam", "defteam", "passer_player_id", "passing_yards",
                        "complete_pass", "pass_attempt", "sack", "receiver_player_id", "receiving_yards", "rusher_player_id", "rushing_yards", "two_point_attempt"])
    d = d[d.two_point_attempt != 1]
    S = collections.defaultdict(lambda: collections.defaultdict(float)); META = {}
    for r in d.itertuples(index=False):
        if isinstance(r.passer_player_id, str) and r.pass_attempt == 1 and r.sack != 1:
            k = (r.passer_player_id, r.game_id); s = S[k]; s["att"] += 1; s["cmp"] += r.complete_pass == 1
            s["pass_yds"] += r.passing_yards if r.passing_yards == r.passing_yards else 0; META[k] = (r.week, r.posteam, r.defteam)
        if isinstance(r.receiver_player_id, str):
            k = (r.receiver_player_id, r.game_id); s = S[k]; s["tgt"] += 1
            if r.complete_pass == 1:
                s["rec"] += 1; s["rec_yds"] += r.receiving_yards if r.receiving_yards == r.receiving_yards else 0
            META[k] = (r.week, r.posteam, r.defteam)
        if isinstance(r.rusher_player_id, str):
            k = (r.rusher_player_id, r.game_id); s = S[k]; s["car"] += 1
            s["rush_yds"] += r.rushing_yards if r.rushing_yards == r.rushing_yards else 0; META[k] = (r.week, r.posteam, r.defteam)
    return S, META


def spreads():
    out = {}
    d = json.load(urllib.request.urlopen(urllib.request.Request(
        "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates=" + DAY.replace("-", ""), headers={"User-Agent": "Mozilla/5.0"}), timeout=30))
    for e in d["events"]:
        c = e["competitions"][0]; teams = {FIX.get(x["team"]["abbreviation"], x["team"]["abbreviation"]): x["homeAway"] for x in c["competitors"]}
        opp = {a: b for a in teams for b in teams if a != b}
        sp = None
        for o in c.get("odds") or []:
            det = o.get("details") or ""          # e.g. "KC -6.5"
            try:
                fav, num = det.split(" "); fav = FIX.get(fav, fav); num = abs(float(num))
                sp = {fav: -num, opp[fav]: num}
            except Exception:
                pass
        for t in teams:
            out[t] = (opp[t], (sp or {}).get(t))
    return out


def main():
    N = F.names(); S, META = games(); SP = spreads()
    P = collections.defaultdict(list)
    for (pid, gid), s in S.items():
        wk, tm, opp = META[(pid, gid)]
        P[F.nn(N.get(pid, (pid,))[0])].append(dict(wk=wk, team=tm, opp=opp, pos=N.get(pid, ("", "?"))[1], s=s))
    for k in P:
        P[k].sort(key=lambda x: x["wk"])
    allowed = collections.defaultdict(lambda: collections.defaultdict(float))     # (opp, stat, pos) -> wk -> total
    for k, gs in P.items():
        for g in gs:
            for st, (e, _) in STAT.items():
                allowed[(g["opp"], e, g["pos"])][g["wk"]] += ev(e, g["s"])

    def top8(opp, e, pos):
        teams = {o for (o, ee, pp) in allowed if ee == e and pp == pos}
        avg = {t: sum(allowed[(t, e, pos)].values()) / max(len(allowed[(t, e, pos)]), 1) for t in teams}
        rk = sorted(avg, key=lambda t: -avg[t])
        return opp in rk[:8], (rk.index(opp) + 1 if opp in rk else None)

    L = sqlite3.connect("lines.db")
    rows = L.execute("""select player, team, stat, line, start, max(last_seen) from pp where league=9 and kind='standard'
                        and start >= ? and start < ? group by player, stat""", (DAY, DAY + "T23:59")).fetchall()
    hits = []
    for pl, tm, stat, line, start, ls in rows:
        if stat not in STAT:
            continue
        e, vol = STAT[stat]; tm = FIX.get(tm, tm)
        gs = [g for g in P.get(F.nn(pl), []) if g["team"] == tm] or P.get(F.nn(pl), [])
        if len(gs) < 4:
            continue
        vals = [ev(e, g["s"]) for g in gs]; vols = [ev(vol, g["s"]) for g in gs]
        opp, spread = SP.get(tm, (None, None))
        pos = gs[-1]["pos"]
        t8, rk = top8(opp, e, pos) if opp else (False, None)
        volfall = (sum(vols[-3:]) / 3) <= .85 * (sum(vols) / len(vols))
        for side in ("over", "under"):
            hit = [(v > line) if side == "over" else (v < line) for v in vals]
            season = sum(hit) / len(hit); l3 = all(hit[-3:])
            fired = []
            if l3 and t8 and pos == "RB":
                fired.append("R1 L3 + soft opp + RB (76%)")
            if side == "under" and volfall and spread is not None and spread >= 3:
                fired.append("R2 vol falling + dog 3+ (68%)")
            if side == "under" and season >= .75 and spread is not None and spread >= 3:
                fired.append("R4 season 75% + dog 3+ (67%)")
            if side == "under" and volfall and t8:
                fired.append("R5 vol falling + opp top-8 (66%)")
            if fired:
                h2h = [ev(e, g["s"]) for g in gs if g["opp"] == opp]
                hits.append(dict(player=pl, team=tm, pos=pos, opp=opp, spread=spread, stat=stat, line=line, side=side, season="%d/%d" % (sum(hit), len(hit)),
                                 last=[round(v) for v in vals[-6:]], vol_l3=round(sum(vols[-3:]) / 3, 1), vol_season=round(sum(vols) / len(vols), 1),
                                 opp_rank=rk, rules=fired, h2h=h2h, start=start[11:16], last_wk=gs[-1]["wk"], seen=ls))
    hits.sort(key=lambda h: (-len(h["rules"]), h["start"]))
    json.dump(hits, open("nfl_rules_today.json", "w"), indent=1)
    print("NFL tested-rule screen %s: %d PP lines, %d rule hits" % (DAY, len(rows), len(hits)))
    for h in hits:
        print("%-22s %-3s %-2s v %-3s %+5s %-16s %s%-6g season %-5s last %s vol %s/%s rk %s h2h %s | %s | wk%s %s" % (
            h["player"][:22], h["team"], h["pos"], h["opp"], h["spread"], h["stat"][:16], h["side"][0].upper(), h["line"], h["season"], h["last"],
            h["vol_l3"], h["vol_season"], h["opp_rank"], [round(x) for x in h["h2h"]], "; ".join(h["rules"]), h["last_wk"], h["start"]))


if __name__ == "__main__":
    main()
