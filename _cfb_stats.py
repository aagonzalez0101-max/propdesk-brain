"""CFB STATS SCREEN (11/14, user: "stats wise -- that trumps anything else").
The raw own-rate rule went 48-50% on 1,757 graded CFB lines because cupcake games inflate a player's history.
This screen keeps the stats but fixes that mechanism:
  - hit rate at PP's CURRENT line counted vs FBS opponents only (an opponent with <5 games in the DB = FCS cupcake, dropped)
  - opponent defense vs THAT stat this season (yards allowed to the position group, ranked among FBS teams)
  - role: last-3 volume (carries / receptions / pass attempts) >= 85% of season volume
  - h2h: last season's game vs this opponent if there was one
Both sides. Archives every screened line to cfb_stats.jsonl so it can be graded.
    python _cfb_stats.py [YYYY-MM-DD]
"""
import json, sqlite3, urllib.request, collections, datetime, statistics, sys, re, unicodedata

CT = datetime.timezone(datetime.timedelta(hours=-6))
UA = {'User-Agent': 'Mozilla/5.0'}
g = lambda u: json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30))
STAT = {'Rush Yards': ('rush_yds', 'carries'), 'Receiving Yards': ('rec_yds', 'rec'), 'Receptions': ('rec', 'rec'),
        'Pass Yards': ('pass_yds', 'att'), 'Pass Attempts': ('att', 'att'), 'Pass Completions': ('cmp', 'att'),
        'Rush Attempts': ('carries', 'carries'), 'Rush+Rec Yds': ('rush_yds+rec_yds', 'carries+rec')}
norm = lambda s: re.sub(r'[^a-z]', '', unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode().lower().replace(' jr.', '').replace(' iii', '').replace(' ii', ''))


def ev(e, s):
    return sum(float(s.get(k) or 0) for k in e.split('+'))


def main(day):
    c = sqlite3.connect('sports.db')
    rows = c.execute("select season,date,game_id,player,team,opp,stats from player_games where sport='CFB' and season in ('2025','2026') and player not like '% Team'").fetchall()
    P = collections.defaultdict(list); tg = collections.defaultdict(set); allowed = collections.defaultdict(lambda: collections.defaultdict(float))
    for season, d, gid, pl, tm, opp, st in rows:
        s = json.loads(st)
        P[norm(pl)].append(dict(season=season, date=d, gid=gid, team=tm, opp=opp, s=s))
        if season == '2026':
            tg[tm].add(gid)
            pos = s.get('pos')
            for e in set(v[0] for v in STAT.values()):
                if pos == 'QB' and e == 'rush_yds':
                    continue
                allowed[(opp, e, pos if e in ('rush_yds', 'carries') else 'ALL')][gid] += ev(e, s)
    fbs = {t for t, gs in tg.items() if len(gs) >= 5}

    def dfac(opp, e, pos):
        key = pos if e in ('rush_yds', 'carries') else 'ALL'
        per = {t: statistics.mean(allowed[(t, e, key)].values()) for t in fbs if allowed[(t, e, key)]}
        if opp not in per:
            return None, None
        rk = sorted(per, key=lambda t: per[t]).index(opp) + 1          # 1 = allows the least
        return rk, len(per)

    d = g('https://partner-api.prizepicks.com/projections?league_id=15&per_page=1000')
    PL = {i['id']: i['attributes'] for i in d.get('included', []) if i['type'] == 'new_player'}
    out = []
    for x in d['data']:
        a = x['attributes']
        if a.get('odds_type') != 'standard' or a['stat_type'] not in STAT:
            continue
        if datetime.datetime.fromisoformat(a['start_time']).astimezone(CT).date().isoformat() != day:
            continue
        pl = PL.get(x['relationships']['new_player']['data']['id'], {})
        gl = sorted(P.get(norm(pl.get('name')), []), key=lambda r: r['date'], reverse=True)
        cur = [r for r in gl if r['season'] == '2026']
        if len(cur) < 5:
            continue
        e, vol = STAT[a['stat_type']]
        pos = cur[0]['s'].get('pos')
        if pos == 'QB' and a['stat_type'] in ('Rush Yards', 'Rush+Rec Yds'):
            continue
        line = float(a['line_score'])
        team = cur[0]['team']
        opp_full = [r['opp'] for r in cur]          # PP's opponent text is an abbreviation; find the opponent from the schedule below
        vs_fbs = [r for r in cur if r['opp'] in fbs]
        if len(vs_fbs) < 4:
            continue
        v_all = [ev(e, r['s']) for r in cur]; v_f = [ev(e, r['s']) for r in vs_fbs]
        vv = [ev(vol, r['s']) for r in cur]
        role = statistics.mean(vv[:3]) / statistics.mean(vv) if statistics.mean(vv) else 0
        out.append(dict(player=pl.get('name'), team=team, desc=a.get('description'), stat=a['stat_type'], line=line, pos=pos,
                        start=a['start_time'], e=e, n=len(cur), nf=len(vs_fbs), vals=v_all[:8], vf=v_f,
                        o_f=sum(v > line for v in v_f), u_f=sum(v < line for v in v_f), avg_f=statistics.mean(v_f), role=role))
    # opponent: match PP description (abbr) via ESPN scoreboard for the day
    sb = g('https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?dates=%s&groups=80&limit=300' % day.replace('-', ''))
    opp_of = {}
    for evn in sb['events']:
        cs = evn['competitions'][0]['competitors']
        for cc in cs:
            o = [y for y in cs if y is not cc][0]
            opp_of[cc['team']['displayName']] = (o['team']['displayName'], (evn['competitions'][0].get('odds') or [{}])[0].get('details'))
    res = []
    for r in out:
        o, spread = opp_of.get(r['team'], (None, None))
        if not o:
            continue
        rk, N = dfac(o, r['e'], r['pos'])
        h = [ev(r['e'], q['s']) for q in P[norm(r['player'])] if q['season'] == '2025' and q['opp'] == o]
        r.update(opp=o, rk=rk, N=N, h2h=h, spread=spread)
        res.append(r)
    with open('cfb_stats.jsonl', 'a', encoding='utf-8') as f:
        for r in res:
            f.write(json.dumps(dict(r, day=day, logged=datetime.datetime.now(CT).isoformat()), ensure_ascii=False) + '\n')

    def show(r, side):
        st = datetime.datetime.fromisoformat(r['start']).astimezone(CT).strftime('%I:%M%p')
        hit = r['o_f'] if side == 'O' else r['u_f']
        print('  %-22s %-4s %s%-6g %-16s vs-FBS %d/%d avg %.0f | all: %s | role %.2f | opp D rank %s/%s | h2h %s | %s | %s CT' % (
            r['player'][:22], r['pos'], side, r['line'], r['stat'], hit, r['nf'], r['avg_f'], ' '.join('%g' % v for v in r['vals']),
            r['role'], r['rk'], r['N'], ' '.join('%g' % v for v in r['h2h']) or '-', (r['opp'] or '')[:22], st))
    print('CFB STATS %s: %d lines screened (5+ games, 4+ vs FBS)' % (day, len(res)))
    print('\nOVERS -- 80%%+ over vs FBS, role held, opp D in the bottom 2/3 for this stat, h2h not under')
    for r in sorted(res, key=lambda r: -r['o_f'] / r['nf']):
        if r['o_f'] / r['nf'] >= .8 and r['role'] >= .85 and r['rk'] and r['rk'] > r['N'] / 3 and not (r['h2h'] and max(r['h2h']) < r['line']):
            show(r, 'O')
    print('\nUNDERS -- 80%%+ under vs FBS, role not rising, opp D in the top 2/3 for this stat, h2h not over')
    for r in sorted(res, key=lambda r: -r['u_f'] / r['nf']):
        if r['u_f'] / r['nf'] >= .8 and r['role'] <= 1.15 and r['rk'] and r['rk'] <= 2 * r['N'] / 3 and not (r['h2h'] and min(r['h2h']) > r['line']):
            show(r, 'U')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else datetime.datetime.now(CT).date().isoformat())
