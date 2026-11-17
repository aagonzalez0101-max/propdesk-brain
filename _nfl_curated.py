"""NFL CURATED SCREEN (11/15). The NFL 'agree' model went 426-428 forward, so NFL now gets the same curated bar as NBA:
  - this season's hit rate at PP's CURRENT line >= 80% (5+ games), both sides
  - role: last-3 volume (targets / carries / attempts) >= 85% of season (overs) / not rising (unders)
  - opponent defense vs that stat AND position this season (rank of 32; 1 = allows least)
  - h2h vs this opponent (2024-25), market side from site/xcheck.json (must be >= 52% when priced)
    python _nfl_curated.py
Archives every screened line to nfl_curated.jsonl."""
import json, sqlite3, urllib.request, collections, statistics, datetime, re, unicodedata

CT = datetime.timezone(datetime.timedelta(hours=-6))
g = lambda u: json.load(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30))
norm = lambda s: re.sub(r'[^a-z]', '', unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode().lower().replace(' jr.', '').replace(' iii', '').replace(' ii', ''))
STAT = {'Receiving Yards': ('receiving_yards', 'targets'), 'Rec Targets': ('targets', 'targets'), 'Receptions': ('receptions', 'targets'),
        'Rush Yards': ('rushing_yards', 'carries'), 'Rush Attempts': ('carries', 'carries'), 'Rush+Rec Yds': ('rushing_yards+receiving_yards', 'carries+targets'),
        'Pass Yards': ('passing_yards', 'attempts'), 'Pass Attempts': ('attempts', 'attempts'), 'Pass Completions': ('completions', 'attempts')}
TEAM = {'LAR': 'LA', 'JAC': 'JAX', 'WSH': 'WAS'}
ev = lambda e, s: sum(float(s.get(k) or 0) for k in e.split('+'))


def main():
    c = sqlite3.connect('sports.db')
    P = collections.defaultdict(list); allowed = collections.defaultdict(lambda: collections.defaultdict(float))
    for season, wk, pl, tm, opp, st in c.execute("select season,date,player,team,opp,stats from player_games where sport='NFL' and season in ('2024','2025','2026')"):
        s = json.loads(st)
        P[norm(pl)].append(dict(season=season, wk=wk, team=tm, opp=opp, s=s))
        if season == '2026':
            for e in set(v[0] for v in STAT.values()):
                allowed[(opp, e, s.get('position'))][wk] += ev(e, s)

    def rank(opp, e, pos):
        per = {t: statistics.mean(v.values()) for (t, ee, pp), v in allowed.items() if ee == e and pp == pos and v}
        if opp not in per:
            return None
        return sorted(per, key=lambda t: per[t]).index(opp) + 1

    mk = {}
    try:
        for r in json.load(open('site/xcheck.json', encoding='utf-8')):
            if r['sport'] == 'NFL':
                mk[(r['player'], r['stat'])] = (r['side'], r['p'], r['line'])
    except Exception:
        pass
    d = g('https://partner-api.prizepicks.com/projections?league_id=9&per_page=1000')
    PL = {i['id']: i['attributes'] for i in d.get('included', []) if i['type'] == 'new_player'}
    res = []
    for x in d['data']:
        a = x['attributes']
        if a.get('odds_type') != 'standard' or a['stat_type'] not in STAT:
            continue
        pl = PL.get(x['relationships']['new_player']['data']['id'], {})
        gl = sorted(P.get(norm(pl.get('name')), []), key=lambda r: (r['season'], r['wk']), reverse=True)
        cur = [r for r in gl if r['season'] == '2026']
        e, vol = STAT[a['stat_type']]
        cur = [r for r in cur if ev(vol, r['s']) > 0 or e.startswith('pass')]
        if len(cur) < 5:
            continue
        line = float(a['line_score']); pos = cur[0]['s'].get('position')
        opp = (a.get('description') or '').split()[0] if a.get('description') else ''
        opp = TEAM.get(opp, opp)
        v = [ev(e, r['s']) for r in cur]; vv = [ev(vol, r['s']) for r in cur]
        role = statistics.mean(vv[:3]) / statistics.mean(vv) if statistics.mean(vv) else 0
        h = [ev(e, r['s']) for r in gl if r['season'] != '2026' and r['opp'] == opp]
        rk = rank(opp, e, pos)
        m = mk.get((pl.get('name'), a['stat_type']))
        res.append(dict(player=pl.get('name'), team=cur[0]['team'], pos=pos, opp=opp, stat=a['stat_type'], line=line, start=a['start_time'],
                        n=len(v), vals=v, o=sum(x > line for x in v), u=sum(x < line for x in v), avg=statistics.mean(v), role=role, rk=rk, h2h=h[:4], mk=m))
    with open('nfl_curated.jsonl', 'a', encoding='utf-8') as f:
        for r in res:
            f.write(json.dumps(dict(r, logged=datetime.datetime.now(CT).isoformat()), ensure_ascii=False) + '\n')

    def mp(r, side):
        if not r['mk']:
            return None
        s, p, ln = r['mk']
        return p if s == side else 1 - p

    def show(r, side):
        st = datetime.datetime.fromisoformat(r['start']).astimezone(CT).strftime('%a %I:%M%p')
        hit = r['o'] if side == 'over' else r['u']; p = mp(r, side)
        print('  %-22s %-3s %-4s v %-4s %s%-6g %-16s %d/%d avg %.1f | %s | role %.2f | opp rank %s/32 | h2h %s | mkt %s | %s' % (
            r['player'][:22], r['pos'], r['team'], r['opp'], side[0].upper(), r['line'], r['stat'], hit, r['n'], r['avg'],
            ' '.join('%g' % x for x in r['vals'][:8]), r['role'], r['rk'], ' '.join('%g' % x for x in r['h2h']) or '-',
            '%.1f%%' % (100 * p) if p is not None else '-', st))
    print('NFL CURATED: %d lines screened (5+ games this season)' % len(res))
    print('\nOVERS -- 80%+ this season, role held, opp not top-third vs the stat, market >= 52% when priced')
    for r in sorted(res, key=lambda r: -r['o'] / r['n']):
        p = mp(r, 'over')
        if r['o'] / r['n'] >= .8 and r['role'] >= .85 and (r['rk'] is None or r['rk'] > 10) and (p is None or p >= .52):
            show(r, 'over')
    print('\nUNDERS -- 80%+ this season, role not rising, opp not bottom-third vs the stat, market >= 52% when priced')
    for r in sorted(res, key=lambda r: -r['u'] / r['n']):
        p = mp(r, 'under')
        if r['u'] / r['n'] >= .8 and r['role'] <= 1.15 and (r['rk'] is None or r['rk'] <= 22) and (p is None or p >= .52):
            show(r, 'under')


if __name__ == '__main__':
    main()
