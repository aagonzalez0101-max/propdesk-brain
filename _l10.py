"""CURATED L10/L15 CHECK (11/14) -- the curated bar straight from ESPN gamelogs (regular season only, no preseason).
    python _l10.py nba "Cedric Coward|Rebounds|7|O" "Matas Buzelis|Pts+Asts|18.5|U"
    python _l10.py nhl "Martin Necas|SOG|2.5|U"
Prints last-10, last-15 and season hit counts at THIS line (a push on a whole number is counted separately)."""
import json, urllib.request, sys, re, unicodedata
from concurrent.futures import ThreadPoolExecutor

UA = {'User-Agent': 'Mozilla/5.0'}
g = lambda u: json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30))
LG = {'nba': 'basketball/nba', 'nhl': 'hockey/nhl'}
NBA = {'Points': ['PTS'], 'Rebounds': ['REB'], 'Assists': ['AST'], 'Pts+Rebs+Asts': ['PTS', 'REB', 'AST'], 'Pts+Rebs': ['PTS', 'REB'],
       'Pts+Asts': ['PTS', 'AST'], 'Rebs+Asts': ['REB', 'AST'], '3-PT Made': ['3PM'], '3-PT Attempted': ['3PA'], 'Blocked Shots': ['BLK'],
       'Steals': ['STL'], 'Blks+Stls': ['BLK', 'STL'], 'Turnovers': ['TO'], 'FG Made': ['FGM'], 'FG Attempted': ['FGA'],
       'Free Throws Made': ['FTM'], 'Offensive Rebounds': ['OR'], 'Defensive Rebounds': ['DR']}
NHL = {'SOG': ['shotsTotal'], 'Shots On Goal': ['shotsTotal'], 'Points': ['points'], 'Assists': ['assists'], 'Goals': ['goals'],
}   # ESPN NHL gamelog has NO hits/blocks -- use sports.db for those


def norm(s):
    return re.sub(r'[^a-z]', '', unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode().lower())


def roster_ids(sp):
    teams = g('https://site.api.espn.com/apis/site/v2/sports/%s/teams?limit=50' % LG[sp])['sports'][0]['leagues'][0]['teams']

    def r(t):
        try:
            a = g('https://site.api.espn.com/apis/site/v2/sports/%s/teams/%s/roster' % (LG[sp], t['team']['id']))['athletes']
        except Exception:
            return []
        if a and 'items' in a[0]:
            a = [x for grp in a for x in grp['items']]
        return [(norm(x['displayName']), x['id'], t['team']['abbreviation']) for x in a]
    with ThreadPoolExecutor(16) as ex:
        return {n: (i, ab) for rows in ex.map(r, teams) for n, i, ab in rows}


def games(sp, aid):
    d = g('https://site.web.api.espn.com/apis/common/v3/sports/%s/athletes/%s/gamelog?season=2027' % (LG[sp], aid))
    names = d.get('names') or []
    ev = d.get('events', {})
    out = []
    for stp in d.get('seasonTypes', []):
        if 'preseason' in (stp.get('displayName') or '').lower():
            continue
        for cat in stp.get('categories', []):
            for e in cat.get('events', []):
                st = dict(zip(names, e['stats']))
                meta = ev.get(e['eventId'], {})
                out.append((meta.get('gameDate', '')[:10], meta.get('opponent', {}).get('abbreviation', '?'), st))
    out.sort(key=lambda x: x[0], reverse=True)
    return out


def val(sp, st, stat):
    if sp == 'nhl':
        return sum(float(st.get(k) or 0) for k in NHL[stat])
    num = lambda k: float(str(st.get(k) or 0).split('-')[0] or 0)
    m = {'PTS': num('points'), 'REB': num('totalRebounds'), 'AST': num('assists'), 'BLK': num('blocks'), 'STL': num('steals'),
         'TO': num('turnovers'), 'OR': num('offensiveRebounds'), 'DR': num('defensiveRebounds')}
    fg = str(st.get('fieldGoalsMade-fieldGoalsAttempted') or '0-0').split('-')
    tp = str(st.get('threePointFieldGoalsMade-threePointFieldGoalsAttempted') or '0-0').split('-')
    ft = str(st.get('freeThrowsMade-freeThrowsAttempted') or '0-0').split('-')
    m.update(FGM=float(fg[0]), FGA=float(fg[1]), **{'3PM': float(tp[0]), '3PA': float(tp[1])}, FTM=float(ft[0]))
    return sum(m[k] for k in NBA[stat])


def main(sp, legs):
    ids = roster_ids(sp)
    for leg in legs:
        name, stat, line, side = leg.split('|')
        line = float(line)
        hit = ids.get(norm(name))
        if not hit:
            print('%-22s NOT FOUND on ESPN rosters' % name)
            continue
        gl = games(sp, hit[0])
        vs = [(d, o, val(sp, st, stat)) for d, o, st in gl]
        win = lambda v: v > line if side == 'O' else v < line

        def rec(xs):
            w = sum(win(v) for _, _, v in xs); p = sum(v == line for _, _, v in xs)
            return '%d/%d%s' % (w, len(xs), ' (%d push)' % p if p else '')
        print('%-22s %s %s%g %-14s L10 %-12s L15 %-12s season %-12s last game %s | L10: %s' % (
            name, hit[1], side, line, stat, rec(vs[:10]), rec(vs[:15]) if len(vs) >= 15 else '-', rec(vs),
            vs[0][0] if vs else '-', ' '.join('%g' % v for _, _, v in vs[:10])))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2:])
