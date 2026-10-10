"""Understat player xG -> team and player profiles for a fixture.

  python _soccerxg.py La_liga 2026 "Atletico Madrid" Osasuna
  python _soccerxg.py Bundesliga 2026 "Bayer Leverkusen"

Free, no key: understat.com/main/getPlayersStats/ (POST league=..&season=..).
Team xG-for is the sum of its players' xG; xG-against is NOT exposed, so pair it
with goals-against from soccer_rows.json where the league is covered.
"""
import urllib.request, gzip, json, sys, io, os

H = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest", "Accept-Encoding": "gzip"}
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def players(league, season):
    cache = f"_understat_{league}_{season}.json"
    if os.path.exists(cache):
        return json.load(open(cache, encoding="utf-8"))
    r = urllib.request.urlopen(urllib.request.Request(
        "https://understat.com/main/getPlayersStats/",
        data=f"league={league}&season={season}".encode(), headers=H), timeout=45)
    raw = r.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    rows = json.loads(raw.decode("utf-8", "replace"))["players"]
    json.dump(rows, open(cache, "w"))
    return rows


def team_profile(rows, team):
    t = [p for p in rows if p["team_title"] == team]
    if not t:
        return None
    mins = max(int(p["time"]) for p in t)
    gms = max(int(p["games"]) for p in t)
    f = lambda k: sum(float(p[k]) for p in t)
    return dict(games=gms, xG=f("xG"), npxG=f("npxG"), xA=f("xA"), goals=f("goals"),
                shots=f("shots"), kp=f("key_passes"), squad=t)


def show(rows, team):
    tp = team_profile(rows, team)
    if not tp:
        print(f"  {team}: not in Understat for this league/season"); return
    g = tp["games"]
    print(f"\n{team}  ({g} games)")
    print(f"  team xG {tp['xG']/g:.2f}/g   npxG {tp['npxG']/g:.2f}/g   goals {tp['goals']/g:.2f}/g"
          f"   shots {tp['shots']/g:.1f}/g   key passes {tp['kp']/g:.1f}/g")
    over = tp["goals"] - tp["xG"]
    print(f"  finishing: {over:+.1f} goals vs xG  ({'running hot' if over>1.5 else 'running cold' if over<-1.5 else 'in line'})")
    sq = sorted(tp["squad"], key=lambda p: -float(p["xG"]) - float(p["xA"]))[:6]
    print(f"  {'player':22s} {'min':>4} {'G':>2} {'xG':>5} {'A':>2} {'xA':>5} {'xG90':>5} {'sh90':>5}")
    for p in sq:
        mn = int(p["time"]) or 1
        print(f"  {p['player_name'][:22]:22s} {mn:4d} {int(p['goals']):2d} {float(p['xG']):5.2f} "
              f"{int(p['assists']):2d} {float(p['xA']):5.2f} {90*float(p['xG'])/mn:5.2f} {90*float(p['shots'])/mn:5.2f}")


if __name__ == "__main__":
    lg, season = sys.argv[1], sys.argv[2]
    rows = players(lg, season)
    print(f"{lg} {season}: {len(rows)} players, {len({p['team_title'] for p in rows})} teams")
    for team in sys.argv[3:]:
        show(rows, team)
