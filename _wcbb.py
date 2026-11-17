"""WCBB OVERS SCREENER (11/10, user: we are looking for wcbb overs, not unders).
Today's PP WCBB standard lines (league 176) vs each player's 2026-27 ESPN box scores + the opponent's points allowed.
Archives every screened line to wcbb_pp.jsonl so `python _wcbb.py grade` can settle them. NOT a measured rule yet.
    python _wcbb.py            # screen today's board
    python _wcbb.py grade      # grade archived lines vs ESPN box"""
import json, urllib.request, sys, datetime, re, unicodedata
from concurrent.futures import ThreadPoolExecutor

MEN = 'cbb' in sys.argv[1:]
B = 'https://site.api.espn.com/apis/site/v2/sports/basketball/%s/' % ('mens-college-basketball' if MEN else 'womens-college-basketball')
LEAGUE = 20 if MEN else 176
UA = {'User-Agent': 'Mozilla/5.0'}
CT = datetime.timezone(datetime.timedelta(hours=-6))
STAT = {'Points': ['PTS'], 'Rebounds': ['REB'], 'Assists': ['AST'], 'Pts+Rebs+Asts': ['PTS', 'REB', 'AST'],
        'Pts+Rebs': ['PTS', 'REB'], 'Pts+Asts': ['PTS', 'AST'], 'Rebs+Asts': ['REB', 'AST'], '3-PT Made': ['3PT'],
        'Fantasy Score': None}


def g(u):
    return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=25))


def norm(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower()
    for suf in (' jr.', ' jr', ' iii', ' ii'):
        s = s.replace(suf, '')
    return re.sub(r"[^a-z]", "", s)


def board():
    d = g('https://partner-api.prizepicks.com/projections?league_id=%d&per_page=1000' % LEAGUE)
    P = {i['id']: i['attributes'] for i in d.get('included', []) if i['type'] == 'new_player'}
    out = []
    for p in d['data']:
        a = p['attributes']
        if a.get('odds_type') != 'standard' or a.get('stat_type') not in STAT:
            continue
        pl = P.get(p['relationships']['new_player']['data']['id'], {})
        out.append(dict(pid=p['id'], player=pl.get('name'), team=pl.get('team'), stat=a['stat_type'], line=a['line_score'],
                        start=a.get('start_time'), desc=a.get('description')))
    return out


def val(d, stat):
    f = lambda k: float((d.get(k) or '0').split('-')[0] or 0)
    if stat == 'Fantasy Score':
        return f('PTS') + 1.2 * f('REB') + 1.5 * f('AST') + 3 * f('BLK') + 3 * f('STL') - f('TO')
    return sum(f(k) for k in STAT[stat])


def logs(day):
    sb = g(B + 'scoreboard?dates=%s&limit=900&groups=50' % day.replace('-', ''))
    teams = {}
    for e in sb['events']:
        cs = e['competitions'][0]['competitors']
        for c in cs:
            o = [x for x in cs if x is not c][0]
            teams[c['team']['id']] = dict(abbr=c['team']['abbreviation'], opp_id=o['team']['id'], opp=o['team']['abbreviation'])

    def sched(tid):
        try:
            return tid, g(B + 'teams/%s/schedule?season=2027' % tid).get('events', [])
        except Exception:
            return tid, []

    def prior(tid):                 # last season's full points allowed = the real defense baseline (11/10 user: early games
        try:                        # vs D3 schools like Hiram 99-26 made YSU look like a 44-allowed defense)
            pa = []
            for ev in g(B + 'teams/%s/schedule?season=2026' % tid).get('events', []):
                c = ev['competitions'][0]
                if c.get('status', {}).get('type', {}).get('completed'):
                    op = [x for x in c['competitors'] if x['team']['id'] != tid]
                    if op: pa.append(float(op[0]['score']['value']))
            return tid, (sum(pa), len(pa))
        except Exception:
            return tid, (0, 0)
    with ThreadPoolExecutor(16) as ex:
        S = dict(ex.map(sched, list(teams)))
        PR = dict(ex.map(prior, list(teams)))
    allowed, evs = {}, set()
    for tid, es in S.items():
        pa = []
        for ev in es:
            c = ev['competitions'][0]
            if not c.get('status', {}).get('type', {}).get('completed'):
                continue
            evs.add(ev['id'])
            try:
                op = [x for x in c['competitors'] if x['team']['id'] != tid][0]
                pa.append(float(op['score']['value']))
            except Exception:
                pass
        ps, pn = PR.get(tid, (0, 0))
        w = 10 if pn else 0         # last season counts as 10 games of weight; this year's 2-3 games barely move it
        num = (ps / pn * w if pn else 0) + sum(pa)
        allowed[tid] = num / (w + len(pa)) if (w + len(pa)) else None

    def summ(eid):
        try:
            return eid, g(B + 'summary?event=%s' % eid)
        except Exception:
            return eid, None
    with ThreadPoolExecutor(24) as ex:
        SM = dict(ex.map(summ, list(evs)))
    L = {}
    for eid, s in SM.items():
        if not s:
            continue
        date = s.get('header', {}).get('competitions', [{}])[0].get('date', '')[:10]
        for t in s.get('boxscore', {}).get('players', []):
            tid = t['team']['id']
            for st in t['statistics']:
                lab = st.get('labels') or st.get('keys')
                for a in st['athletes']:
                    if not a.get('stats'):
                        continue
                    L.setdefault((norm(a['athlete']['displayName']), tid), []).append((date, dict(zip(lab, a['stats']))))
    return teams, allowed, L


def screen(day):
    bd = board()
    teams, allowed, L = logs(day)
    la = [v for v in allowed.values() if v]
    lg = sum(la) / len(la)
    byname = {}
    for (n, tid), v in L.items():
        byname.setdefault(n, []).append((tid, v))
    rows = []
    for b in bd:
        c = [x for x in byname.get(norm(b['player'] or ''), []) if x[0] in teams]
        if not c:
            continue
        tid, gl = max(c, key=lambda x: len(x[1]))
        gl = sorted(gl, key=lambda x: x[0])
        vals = [val(d, b['stat']) for _, d in gl]
        mins = [float(d.get('MIN') or 0) for _, d in gl]
        if not vals:
            continue
        oa = allowed.get(teams[tid]['opp_id'])
        r = dict(b, n=len(vals), vals=vals, mins=mins, avg=sum(vals) / len(vals), over=sum(v > b['line'] for v in vals),
                 minlast=mins[-1], minavg=sum(mins) / len(mins), opp=teams[tid]['opp'], opp_allowed=oa, lg=lg)
        r['cush'] = r['avg'] / b['line'] - 1
        r['soft'] = oa is not None and oa > lg + 3
        r['tough'] = oa is not None and oa < lg - 5
        rows.append(r)
    with open('cbb_scr.jsonl' if MEN else 'wcbb_pp.jsonl', 'a') as f:
        for r in rows:
            f.write(json.dumps(dict(r, logged=datetime.datetime.now(CT).isoformat(), day=day)) + '\n')
    q = [r for r in rows if r['over'] == r['n'] and r['n'] >= 2 and r['cush'] >= .10
         and r['minlast'] >= .85 * r['minavg'] and not r['tough']]
    q.sort(key=lambda r: (-r['soft'], -r['cush']))
    print(('CBB' if MEN else 'WCBB') + ' %s: %d PP standard lines, %d matched to ESPN logs, avg pts allowed %.1f' % (day, len(bd), len(rows), lg))
    print('\nOVERS -- cleared EVERY game, avg 10%+ above line, minutes held, opp not tough (SOFT = allows 3+ above avg)')
    for r in q:
        st = datetime.datetime.fromisoformat(r['start']).astimezone(CT).strftime('%I:%M %p') if r['start'] else ''
        print('  %-22s %-5s vs %-5s O%-5g %-14s avg %5.1f (+%2.0f%%) | %d/%d | %s | min %s | opp allows %s%s | %s CT' % (
            r['player'][:22], r['team'], r['opp'], r['line'], r['stat'], r['avg'], 100 * r['cush'], r['over'], r['n'],
            '/'.join('%g' % v for v in r['vals'][-5:]), '/'.join('%.0f' % m for m in r['mins'][-5:]),
            '%.0f' % r['opp_allowed'] if r['opp_allowed'] else '?', ' SOFT' if r['soft'] else '', st))
    u = [r for r in rows if r['over'] == 0 and r['n'] >= 2 and r['cush'] <= -.10 and not r['soft']]
    u.sort(key=lambda r: (-r['tough'], r['cush']))
    print('\nUNDERS -- under EVERY game, avg 10%+ below line, opp not soft (TOUGH = allows 5+ below avg)')
    for r in u:
        st = datetime.datetime.fromisoformat(r['start']).astimezone(CT).strftime('%I:%M %p') if r['start'] else ''
        print('  %-22s %-5s vs %-5s U%-5g %-14s avg %5.1f (%3.0f%%) | %d/%d over | %s | min %s | opp allows %s%s | %s CT' % (
            r['player'][:22], r['team'], r['opp'], r['line'], r['stat'], r['avg'], 100 * r['cush'], r['over'], r['n'],
            '/'.join('%g' % v for v in r['vals'][-5:]), '/'.join('%.0f' % m for m in r['mins'][-5:]),
            '%.0f' % r['opp_allowed'] if r['opp_allowed'] else '?', ' TOUGH' if r['tough'] else '', st))


if __name__ == '__main__':
    screen(datetime.datetime.now(CT).date().isoformat())
