"""PRE-TIP LEG CHECK (11/11, user: Avdija TO was pulled from PP 2 hours before tip -- research who is playing).
For each leg: is the exact line still on the live PP board, and what does ESPN's injury report say about the player AND
his teammates (a teammate ruled out changes usage). Run ~90 min before the first tip and again right before placing.
    python _legcheck.py "Ja'Kobe Walter|Pts+Asts|15.5|U" "Ziaire Williams|FG Made|2.5|O" ...
"""
import json, urllib.request, sys, unicodedata, re

UA = {'User-Agent': 'Mozilla/5.0'}
g = lambda u: json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30))


def norm(s):
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode().lower()
    return re.sub(r"[^a-z]", "", s)


def main(legs, league=7, sport='nba'):
    d = g('https://partner-api.prizepicks.com/projections?league_id=%d&per_page=1000' % league)
    P = {i['id']: i['attributes'] for i in d.get('included', []) if i['type'] == 'new_player'}
    board = {}
    for p in d['data']:
        a = p['attributes']
        pl = P.get(p['relationships']['new_player']['data']['id'], {})
        board.setdefault(norm(pl.get('name')), []).append((a.get('stat_type'), a.get('line_score'), a.get('odds_type'), pl.get('team')))
    inj = {}
    for t in g('https://site.api.espn.com/apis/site/v2/sports/basketball/%s/injuries' % sport).get('injuries', []):
        for i in t.get('injuries', []):
            inj[norm(i['athlete']['displayName'])] = (t.get('displayName'), i.get('status'), (i.get('shortComment') or '')[:110])
    for leg in legs:
        name, stat, line, side = leg.split('|')
        rows = board.get(norm(name), [])
        std = [r for r in rows if r[0] == stat and r[2] == 'standard']
        same = [r for r in std if float(r[1]) == float(line)]
        team = rows[0][3] if rows else '?'
        if same:
            status = 'ON BOARD %s %s' % (stat, line)
        elif std:
            status = 'LINE MOVED -> %s %s (was %s)' % (stat, std[0][1], line)
        elif rows:
            status = 'PROP PULLED (player still has other props)'
        else:
            status = 'PLAYER OFF THE BOARD'
        me = inj.get(norm(name))
        print('%-22s %s%-5s %-14s | %-40s | ESPN: %s' % (name, side, line, stat, status, '%s - %s' % (me[1], me[2]) if me else 'not on injury report'))
        if me is None and team != '?':
            pass
    print('\nTEAMMATES ON THE INJURY REPORT (usage changes):')
    teams = {}
    for leg in legs:
        rows = board.get(norm(leg.split('|')[0]), [])
        if rows: teams[rows[0][3]] = 1
    for k, (tn, st, c) in inj.items():
        abbr = [t for t in teams if t and t.lower() in (tn or '').lower().replace(' ', '')]
        if any(t and (t in (tn or '') or t[:3].lower() in (tn or '').lower()) for t in teams):
            print('  %-24s %-10s %s' % (tn, st, c))


if __name__ == '__main__':
    main(sys.argv[1:])
