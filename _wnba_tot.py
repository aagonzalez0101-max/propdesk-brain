"""WNBA closing totals -> wnba_tot.jsonl

    python _wnba_tot.py

ESPN's scoreboard DROPS the odds block once a game completes, so a season pull off the
scoreboard alone returns zero totals. The closing number survives on the per-game
`/summary` endpoint under `pickcenter`, which needs the event id -- so the scoreboard pass
has to keep the id, and the summary pass runs one call per game.

Writes as it goes; a timeout mid-run loses nothing.
"""
import json, os, sys, time, datetime
import requests

OUT = "wnba_tot.jsonl"
SB = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"
SUM = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/summary"
H = {"User-Agent": "Mozilla/5.0"}


def done():
    s = set()
    if os.path.exists(OUT):
        for l in open(OUT, encoding="utf-8"):
            try:
                s.add(json.loads(l)["id"])
            except Exception:
                pass
    return s


def pull(start="2026-05-01", end="2026-09-22"):
    have = done()
    print("have %d games" % len(have), flush=True)
    f = open(OUT, "a", encoding="utf-8")
    d = datetime.date.fromisoformat(start)
    e = datetime.date.fromisoformat(end)
    n = 0
    while d <= e:
        try:
            r = requests.get(SB, params=dict(dates=d.strftime("%Y%m%d")), headers=H, timeout=25).json()
        except Exception:
            d += datetime.timedelta(days=1)
            continue
        for ev in (r.get("events") or []):
            c = (ev.get("competitions") or [{}])[0]
            if not (c.get("status") or {}).get("type", {}).get("completed"):
                continue
            if ev["id"] in have:
                continue
            ts = c.get("competitors") or []
            if len(ts) != 2:
                continue
            try:
                sc = {t["homeAway"]: int(t["score"]) for t in ts}
                nm = {t["homeAway"]: t["team"]["abbreviation"] for t in ts}
            except Exception:
                continue
            ou = sp = prov = None
            try:
                s = requests.get(SUM, params=dict(event=ev["id"]), headers=H, timeout=25).json()
                pc = s.get("pickcenter") or []
                if pc:
                    ou = pc[0].get("overUnder")
                    sp = pc[0].get("spread")
                    prov = (pc[0].get("provider") or {}).get("name")
            except Exception:
                pass
            have.add(ev["id"])
            f.write(json.dumps(dict(id=ev["id"], date=d.isoformat(), home=nm.get("home"),
                                    away=nm.get("away"), hs=sc.get("home"), as_=sc.get("away"),
                                    total=ou, spread=sp, book=prov)) + "\n")
            n += 1
            if n % 25 == 0:
                f.flush()
                print("  %s  %d saved" % (d, n), flush=True)
            time.sleep(0.12)
        d += datetime.timedelta(days=1)
    f.close()
    tot = sum(1 for l in open(OUT, encoding="utf-8") if json.loads(l).get("total"))
    print("done: %d rows, %d with a closing total" % (len(have), tot))


if __name__ == "__main__":
    pull(*(sys.argv[1:3] or []))
