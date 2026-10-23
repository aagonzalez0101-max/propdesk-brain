"""SHARED PRIZEPICKS FETCH (10/23, user: "yes" to the efficiency list -- PP 429s all day: the watcher, sweep, dig, board, soccer,
esports and fast-clear each pulled PrizePicks on their own; the 8:45 esports card came out empty because of it).

Every tool reads PrizePicks through here:
    one fetch per league per MAX_AGE seconds, saved to data/ppcache/league_<id>.json -- every other caller reads the saved copy
    one request at a time across ALL processes (lock file), GAP seconds apart
    a 429 sets a shared cooldown -- nobody hammers PP while it is angry; callers get the last good board instead
    a failed fetch returns the last good board (<= STALE_OK old) and never an empty one -- an empty board reads as "pulled"

    import _ppcache
    d = _ppcache.projections(7)              # same JSON as the partner-api projections endpoint
    _ppcache.age(7)                          # seconds since that board was fetched (None = never)
    python _ppcache.py                       # status of every cached league
"""
import os, sys, json, time, glob, urllib.request, urllib.error

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ppcache")
URL = "https://partner-api.prizepicks.com/projections?league_id=%s&per_page=1000"
UA = {"User-Agent": "Mozilla/5.0"}
MAX_AGE = 180          # a board younger than this is served from disk
STALE_OK = 6 * 3600    # on failure, serve a board up to this old
GAP = 4                # seconds between any two PP requests, all processes
COOLDOWN = 90          # after a 429, nobody calls PP for this long
os.makedirs(DIR, exist_ok=True)


def _path(name):
    return os.path.join(DIR, name)


def _lock(name, wait=240):
    p = _path(name + ".lock"); t0 = time.time()
    while True:
        try:
            os.close(os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)); return p
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(p) > 150:      # holder died
                    os.remove(p); continue
            except OSError:
                pass
            if time.time() - t0 > wait:
                return None
            time.sleep(0.5)


def _unlock(p):
    try:
        if p:
            os.remove(p)
    except OSError:
        pass


def _mtime(name):
    try:
        return os.path.getmtime(_path(name))
    except OSError:
        return None


def _cooling():
    try:
        return float(open(_path("_cooldown")).read()) > time.time()
    except Exception:
        return False


def _request(url):
    """one HTTP call, spaced GAP seconds from every other PP call on this machine"""
    g = _lock("_global")
    try:
        last = _mtime("_last")
        if last and time.time() - last < GAP:
            time.sleep(GAP - (time.time() - last))
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40))
        finally:
            open(_path("_last"), "w").close()
    finally:
        _unlock(g)


def fetch(url, name, max_age=MAX_AGE, tries=(0, 30, 60)):
    f = name + ".json"
    m = _mtime(f)
    if m and time.time() - m < max_age:
        return json.load(open(_path(f), encoding="utf-8"))
    lk = _lock("board_" + name)                           # one process fetches, the rest wait and read its result
    try:
        m = _mtime(f)
        if m and time.time() - m < max_age:
            return json.load(open(_path(f), encoding="utf-8"))
        err = None
        for w in tries:
            if w:
                time.sleep(w)
            if _cooling():
                err = "cooldown after a 429"
                if m:
                    break                                     # have a board: don't wait out the cooldown
                continue
            try:
                d = _request(url)
                tmp = _path(f + ".tmp")
                json.dump(d, open(tmp, "w", encoding="utf-8")); os.replace(tmp, _path(f))
                return d
            except urllib.error.HTTPError as e:
                err = e
                if e.code == 429:
                    open(_path("_cooldown"), "w").write(str(time.time() + COOLDOWN))
            except Exception as e:
                err = e
        if m and time.time() - m < STALE_OK:
            print("  (PrizePicks %s: %s -- using the board from %d min ago)" % (name, err, (time.time() - m) / 60), file=sys.stderr)
            return json.load(open(_path(f), encoding="utf-8"))
        raise RuntimeError("PrizePicks %s unavailable: %s (no saved board)" % (name, err))
    finally:
        _unlock(lk)


def projections(league_id, max_age=MAX_AGE):
    return fetch(URL % league_id, "league_%s" % league_id, max_age)


def leagues():
    return fetch("https://partner-api.prizepicks.com/leagues", "leagues", 24 * 3600)


def league_id(name):
    return next((x["id"] for x in leagues()["data"] if x["attributes"]["name"].upper() == name.upper()), None)


def age(league_id):
    m = _mtime("league_%s.json" % league_id)
    return None if m is None else time.time() - m


if __name__ == "__main__":
    for f in sorted(glob.glob(_path("*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        print("%-20s %5.0f min old  %5d lines" % (os.path.basename(f), (time.time() - os.path.getmtime(f)) / 60, len(d.get("data", []))))
    print("cooldown active" if _cooling() else "no cooldown")
