"""Grade player props for a date from ESPN box scores. python _grade_box.py 2026-11-10 -> prints lookups for live_paper pending + screen files."""
import json, urllib.request, sys, re, unicodedata
from concurrent.futures import ThreadPoolExecutor
UA = {'User-Agent': 'Mozilla/5.0'}
g = lambda u: json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=25))
def norm(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower()
    for suf in (' jr.', ' jr', ' iii', ' ii'): s = s.replace(suf, '')
    return re.sub(r"[^a-z]", "", s)
def box(sport, day):
    B = 'https://site.api.espn.com/apis/site/v2/sports/basketball/%s/' % sport
    ex = '&groups=50&limit=900' if 'college' in sport else ''
    evs = [e['id'] for e in g(B + 'scoreboard?dates=%s%s' % (day.replace('-', ''), ex))['events']]
    def s(eid):
        try: return g(B + 'summary?event=%s' % eid)
        except Exception: return None
    with ThreadPoolExecutor(24) as x: SM = list(x.map(s, evs))
    P = {}
    for sm in SM:
        if not sm: continue
        for t in sm.get('boxscore', {}).get('players', []):
            for st in t['statistics']:
                lab = st.get('labels') or st.get('keys')
                for a in st['athletes']:
                    if a.get('stats'): P[norm(a['athlete']['displayName'])] = dict(zip(lab, a['stats']))
    return P
def val(d, stat):
    f = lambda k: float((d.get(k) or '0').split('-')[0] or 0)
    M = {'Points': ['PTS'], 'Rebounds': ['REB'], 'Assists': ['AST'], 'Pts+Rebs+Asts': ['PTS', 'REB', 'AST'], 'Pts+Rebs': ['PTS', 'REB'],
         'Pts+Asts': ['PTS', 'AST'], 'Rebs+Asts': ['REB', 'AST'], '3-PT Made': ['3PT'], 'Turnovers': ['TO']}
    if stat == 'Fantasy Score': return f('PTS') + 1.2 * f('REB') + 1.5 * f('AST') + 3 * f('BLK') + 3 * f('STL') - f('TO')
    return sum(f(k) for k in M[stat])
if __name__ == '__main__':
    day = sys.argv[1]
    for sp, fn in (('womens-college-basketball', 'wcbb_pp.jsonl'), ('mens-college-basketball', 'cbb_scr.jsonl')):
        P = box(sp, day); seen = {}; res = {'over': [], 'under': []}
        for l in open(fn, encoding='utf-8'):
            r = json.loads(l)
            if r.get('day') != day: continue
            seen[r['pid']] = r
        for r in seen.values():
            d = P.get(norm(r['player']))
            if not d or not d.get('MIN') or d.get('MIN') in ('0', '--'): continue
            v = val(d, r['stat']); r['actual'] = v
            o_rule = r['over'] == r['n'] and r['n'] >= 2 and r['cush'] >= .10 and r['minlast'] >= .85 * r['minavg'] and not r['tough']
            u_rule = r['over'] == 0 and r['n'] >= 2 and r['cush'] <= -.10 and not r['soft']
            if o_rule: res['over'].append((r['player'], r['stat'], r['line'], v, v > r['line']))
            if u_rule: res['under'].append((r['player'], r['stat'], r['line'], v, v < r['line']))
            r['hit_over'] = v > r['line']
        allv = [r for r in seen.values() if 'actual' in r]
        print('\n%s %s: %d lines graded, all-lines overs %d/%d' % (sp, day, len(allv), sum(r['hit_over'] for r in allv), len(allv)))
        for side in ('over', 'under'):
            L = res[side]; print('  SCREEN %s: %d-%d' % (side.upper(), sum(x[4] for x in L), len(L) - sum(x[4] for x in L)))
            for x in L: print('    %-22s %-14s %s%-5g actual %-5g %s' % (x[0][:22], x[1], side[0].upper(), x[2], x[3], 'W' if x[4] else 'L'))
        json.dump([dict(r) for r in allv], open('%s_graded_%s.json' % (fn.split('.')[0], day), 'w'))
