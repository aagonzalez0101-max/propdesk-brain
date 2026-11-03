"""NBA WINNERS (11/2-11/3, user: "idc about price, just stats and tell me who is gonna win").
Team model: rating = (n*this-season net + 5*last-season net)/(n+5) + 2 home - 0.6*ppg of players OUT who played for the team
this season. Each day the 3 biggest predicted margins among teams PLAYING. Walk-forward 10/20-11/2: top-3 30-11.
DROP RULE (11/3, keeps a pick only if it improves the record -- user rule): drop a pick when OUR top 2 scorers both average
below their season ppg against this opponent (2+ meetings each). Flagged picks 8-12 vs 62-25 unflagged, permutation p=0.011;
top-3 30-11 -> 32-8. Team h2h, rest, back-to-back, form, road and a cap on the injury term were all tested and REVERTED.
Bet type (DK closing lines backtest): ML when the pick is a 7.5+ favorite (win, don't cover), spread when -1.5 to -6.5.

    python _nba_winners.py [YYYY-MM-DD]     # -> data/nba_winners_<date>.json + printed board
"""
import sqlite3, statistics as st, collections, datetime, requests, json, sys
sys.path.insert(0, '.')
import _sides as S
DAY = sys.argv[1] if len(sys.argv) > 1 else datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-6))).date().isoformat()
OUTF = 'data/nba_winners_%s.json' % DAY
c = sqlite3.connect('sports.db'); H = {'User-Agent': 'Mozilla/5.0'}
K = 5; HOME = 2.0; INJ = 0.6
NAMES = {'ATL': 'hawks', 'BOS': 'celtics', 'BKN': 'nets', 'CHA': 'hornets', 'CHI': 'bulls', 'CLE': 'cavaliers', 'DAL': 'mavericks',
         'DEN': 'nuggets', 'DET': 'pistons', 'GS': 'warriors', 'HOU': 'rockets', 'IND': 'pacers', 'LAC': 'clippers', 'LAL': 'lakers',
         'MEM': 'grizzlies', 'MIA': 'heat', 'MIL': 'bucks', 'MIN': 'timberwolv', 'NO': 'pelicans', 'NY': 'knicks', 'OKC': 'thunder',
         'ORL': 'magic', 'PHI': '76ers', 'PHX': 'suns', 'POR': 'blazers', 'SA': 'spurs', 'SAC': 'kings', 'TOR': 'raptors',
         'UTAH': 'jazz', 'WSH': 'wizards'}

G = c.execute("select game_id,date,home,away,home_pts,away_pts from nba_games where stype='regular' and season='2026-27' "
              "and home_pts is not null and date<? order by date", (DAY,)).fetchall()
teams = set([g[2] for g in G] + [g[3] for g in G])
prior = {}
for t in teams:
    r = c.execute("select home,home_pts,away_pts from nba_games where season='2025-26' and stype='regular' and (home=? or away=?) "
                  "and home_pts is not null", (t, t)).fetchall()
    if r:
        prior[t] = st.mean((hp - ap) if h == t else (ap - hp) for h, hp, ap in r)
hist = collections.defaultdict(list); rec = collections.defaultdict(lambda: [0, 0]); last = {}
for gid, d, h, a, hp, ap in G:
    hist[h].append(hp - ap); hist[a].append(ap - hp); last[h] = d; last[a] = d
    rec[h][0 if hp > ap else 1] += 1; rec[a][0 if ap > hp else 1] += 1


def rating(t):
    n = len(hist[t])
    return (n * (st.mean(hist[t]) if n else 0) + K * prior.get(t, 0)) / (n + K)


pl = collections.defaultdict(dict)
for team, p, ppg, n in c.execute(
        "select b.team,b.player,avg(b.pts),count(*) from nba_box b join nba_games g on g.game_id=b.game_id where g.season='2026-27' "
        "and g.stype='regular' and (b.dnp=0 or b.dnp is null) and b.min>0 group by b.team,b.player"):
    pl[team][p] = (ppg, n)

sb = requests.get('https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=%s' % DAY.replace('-', ''), headers=H, timeout=20).json()
slate = []; abbr = {}
for e in sb['events']:
    comp = e['competitions'][0]
    side = {x['homeAway']: x['team']['abbreviation'] for x in comp['competitors']}
    for x in comp['competitors']:
        abbr[x['team']['displayName']] = x['team']['abbreviation']
    t = datetime.datetime.fromisoformat(e['date'].replace('Z', '+00:00')).astimezone(datetime.timezone(datetime.timedelta(hours=-6)))
    slate.append(dict(home=side['home'], away=side['away'], time=t.strftime('%I:%M %p').lstrip('0'), name=e['shortName']))
inj = requests.get('https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries', headers=H, timeout=20).json()
OUT = collections.defaultdict(list)
for t in inj.get('injuries', []):
    a = abbr.get(t['displayName'])
    if a:
        for p in t['injuries']:
            OUT[a].append((p['athlete']['displayName'], p['status']))


def penalty(t):
    return sum(INJ * pl[t][p][0] for p, s in OUT[t] if s == 'Out' and p in pl[t])


pin = S.board('nba', hours=40)


def pin_for(h, a):
    for g in pin:
        if NAMES.get(h, '#') in g['home'].lower() and NAMES.get(a, '#') in g['away'].lower():
            return g


def h2h_players(t, opp):
    top = sorted(pl[t].items(), key=lambda x: -x[1][0])[:3]; out = []
    for p, (ppg, n) in top:
        if any(p == q and s == 'Out' for q, s in OUT[t]):
            continue
        v = [r[0] for r in c.execute(
            "select b.pts from nba_box b join nba_games g on g.game_id=b.game_id where b.player=? and b.opp=? and g.stype='regular' "
            "and (b.dnp=0 or b.dnp is null) and b.min>0", (p, opp))]
        out.append(dict(player=p, ppg=round(ppg, 1), h2h=round(st.mean(v), 1) if v else None, n=len(v)))
    return out


rows = []
for g in slate:
    h, a = g['home'], g['away']
    m = (rating(h) - penalty(h) + HOME) - (rating(a) - penalty(a))
    w, l = (h, a) if m > 0 else (a, h)
    lh2h = [(hp - ap) if hh == w else (ap - hp) for hh, aa, hp, ap in c.execute(
        "select home,away,home_pts,away_pts from nba_games where stype='regular' and season in ('2025-26','2026-27') and home_pts is not null "
        "and ((home=? and away=?) or (home=? and away=?)) and date<?", (w, l, l, w, DAY))]
    pg = pin_for(h, a); spread = ml = fair_w = None
    if pg and 'sp' in pg:
        hs = float(pg['sp'][0]); spread = hs if w == h else -hs
    if pg and 'ml' in pg:
        ml = pg['ml'][0] if w == h else pg['ml'][1]
        f = S.devig(*pg['ml']); fair_w = f[0] if w == h else f[1]
    rest = lambda t: (datetime.date.fromisoformat(DAY) - datetime.date.fromisoformat(last[t])).days if t in last else None
    l5 = lambda t: round(st.mean(hist[t][-5:]), 1) if hist[t] else None
    newout = lambda t: [(p, round(pl[t][p][0], 1)) for p, s in OUT[t] if s == 'Out' and p in pl[t]]
    dtd = lambda t: [p for p, s in OUT[t] if s != 'Out' and p in pl[t]]
    if spread is None:
        bet = 'n/a'
    elif spread <= -7.5:
        bet = 'ML'
    elif spread < 0:
        bet = 'SPREAD %+.1f' % spread
    else:
        bet = 'ML (dog)'
    rows.append(dict(game=g['name'], time=g['time'], pick=w, opp=l, margin=round(abs(m), 1), home=(w == h),
                     rec_w='%d-%d' % tuple(rec[w]), rec_l='%d-%d' % tuple(rec[l]),
                     net_w=round(st.mean(hist[w]), 1) if hist[w] else None, net_l=round(st.mean(hist[l]), 1) if hist[l] else None,
                     rating_w=round(rating(w), 1), rating_l=round(rating(l), 1), l5_w=l5(w), l5_l=l5(l),
                     rest_w=rest(w), rest_l=rest(l), out_w=newout(w), out_l=newout(l), dtd_w=dtd(w), dtd_l=dtd(l),
                     pen_w=round(penalty(w), 1), pen_l=round(penalty(l), 1),
                     team_h2h='%d-%d' % (sum(x > 0 for x in lh2h), sum(x < 0 for x in lh2h)), team_h2h_m=[int(x) for x in lh2h],
                     players_w=h2h_players(w, l), players_l=h2h_players(l, w), spread=spread, ml=ml,
                     fair=round(100 * fair_w, 1) if fair_w else None, bet=bet))
def top2_under(r):
    rs = [p['h2h'] / p['ppg'] for p in r['players_w'][:2] if p['h2h'] is not None and p['n'] >= 2 and p['ppg']]
    return len(rs) == 2 and all(x < 1 for x in rs)


for r in rows:
    r['drop'] = top2_under(r)
rows.sort(key=lambda r: -r['margin'])
picks = [r for r in rows if not r['drop']][:3]
print('TOP 3 (drop rule applied): ' + ', '.join('%s over %s (%s)' % (r['pick'], r['opp'], r['bet']) for r in picks))
print('dropped by player h2h: ' + (', '.join('%s over %s' % (r['pick'], r['opp']) for r in rows if r['drop']) or 'none'))
print()
json.dump(rows, open(OUTF, 'w'), indent=1)
for r in rows:
    print('%s%-12s %-8s %-4s over %-4s %+5.1f | %s vs %s | sp %s ml %s fair %s | %s | out us %s | out them %s | h2h %s %s' % (
        'DROP ' if r['drop'] else '     ', r['game'], r['time'], r['pick'], r['opp'], r['margin'], r['rec_w'], r['rec_l'], r['spread'], r['ml'], r['fair'], r['bet'],
        r['out_w'], r['out_l'], r['team_h2h'], r['team_h2h_m']))
    print('      us:', [(x['player'], x['ppg'], x['h2h'], x['n']) for x in r['players_w']], ' them:', [(x['player'], x['ppg'], x['h2h'], x['n']) for x in r['players_l']])
