"""FANDUEL PROPS (public sportsbook JSON, no account) -> {(player, stat, line): P(over)} for the mismatch scanner (2026-10-02).

    python _fanduel.py nfl|cfb      # prints how many priced lines; used by _mismatch.py

Over/under markets: de-vig the pair. Alt ladders ("X 4+ Receptions -150"): one-sided, so remove ~4.5% of overround from the
implied probability (a ladder's typical hold). "N+" = over N-0.5.
"""
import sys, re, json, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Accept": "application/json"}
AK = "FhMFpcPWXMeyZxOx"
BASE = "https://sbapi.nj.sportsbook.fanduel.com/api"
PAGES = {"nfl": "nfl", "cfb": "ncaaf"}
TABS = ("receiving-props", "rushing-props", "passing-props")
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
STATMAP = {"receptions": "receptions", "receivingyds": "receiving yards", "receivingyards": "receiving yards", "rushingyds": "rushing yards",
           "rushingyards": "rushing yards", "passingyds": "passing yards", "passingyards": "passing yards", "passingtds": "touchdown passes",
           "passattempts": "pass attempts", "passcompletions": "pass completions", "rushingattempts": "rush attempts", "rushattempts": "rush attempts"}


def g(u):
    for k in range(3):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=30).read())
        except Exception:
            time.sleep(1 + 2 * k)
    return {}


def imp(a):
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def event_props(eid):
    out = {}
    for tab in TABS:
        x = g("%s/event-page?_ak=%s&eventId=%s&tab=%s" % (BASE, AK, eid, tab))
        for m in (x.get("attachments") or {}).get("markets", {}).values():
            name = m.get("marketName", "")
            if " - " not in name:
                continue
            player, mt = name.split(" - ", 1)
            alt = mt.lower().startswith("alt ")
            stat = STATMAP.get(norm(re.sub(r"(?i)^(alt|total)\s+", "", mt)))
            if not stat:
                continue
            R = m.get("runners") or []
            if alt:
                for r in R:
                    mm = re.search(r"(\d+)\+", r.get("runnerName", ""))
                    am = (((r.get("winRunnerOdds") or {}).get("americanDisplayOdds") or {}).get("americanOdds"))
                    if mm and am is not None:
                        out[(norm(player), stat, int(mm.group(1)) - 0.5)] = max(0.01, imp(am) - 0.045 * imp(am))
            else:
                ov = next((r for r in R if "over" in r.get("runnerName", "").lower()), None)
                un = next((r for r in R if "under" in r.get("runnerName", "").lower()), None)
                if ov and un:
                    po = imp(ov["winRunnerOdds"]["americanDisplayOdds"]["americanOdds"]); pu = imp(un["winRunnerOdds"]["americanDisplayOdds"]["americanOdds"])
                    out[(norm(player), stat, float(ov.get("handicap") or 0))] = po / (po + pu)
    return out


def props(league):
    d = g("%s/content-managed-page?page=CUSTOM&customPageId=%s&_ak=%s&timezone=America%%2FChicago" % (BASE, PAGES[league], AK))
    ev = [e for e in ((d.get("attachments") or {}).get("events") or {}).values() if " @ " in e.get("name", "")]
    out = {}
    with ThreadPoolExecutor(6) as ex:
        for p in ex.map(lambda e: event_props(e["eventId"]), ev):
            out.update(p)
    return out


if __name__ == "__main__":
    lg = sys.argv[1] if len(sys.argv) > 1 else "nfl"
    P = props(lg)
    print("%s: %d FanDuel prices" % (lg, len(P)))
    for k, v in list(P.items())[:8]:
        print(" ", k, round(v, 3))
