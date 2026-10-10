"""Soccer history for the prop backtest (2026-09-30). Downloads every finished match of the top 5 leagues
(2024/25, 2025/26, 2026/27 so far) + MLS (2025, 2026) from FotMob into the per-match cache (_fotmob/m<id>.json),
and writes _soccer_hist_index.json = [match id, league, season, utc date, home id, away id].

    python _soccer_hist.py fetch      # resumable: cached matches are skipped
    python _soccer_hist.py build      # -> _soccer_hist_rows.json, one row per player-match for the 4 markets
"""
import sys, os, json, time
from concurrent.futures import ThreadPoolExecutor
import _soccer as S

LEAGUES = [(47, "EPL"), (87, "LaLiga"), (55, "SerieA"), (54, "Bundesliga"), (53, "Ligue1")]
SEASONS = ["2024/2025", "2025/2026", "2026/2027"]
MLS = [(130, "MLS", "2025"), (130, "MLS", "2026")]
IDX = "_soccer_hist_index.json"


def index():
    out = []
    for lid, name in LEAGUES:
        for s in SEASONS:
            out += [(m, name, s) for m in fixtures(lid, s)]
    for lid, name, s in MLS:
        out += [(m, name, s) for m in fixtures(lid, s)]
    rows = [[m["id"], name, s, (m.get("status") or {}).get("utcTime", "")[:10], (m.get("home") or {}).get("id"),
             (m.get("away") or {}).get("id")] for m, name, s in out]
    json.dump(rows, open(IDX, "w"))
    return rows


def fixtures(lid, season):
    d = S.get("%s/leagues?id=%d&season=%s" % (S.FM, lid, season))
    return [m for m in ((d.get("fixtures") or {}).get("allMatches") or []) if (m.get("status") or {}).get("finished")]


def fetch():
    rows = index()
    todo = [r[0] for r in rows if not os.path.exists(os.path.join(S.CACHE, "m%s.json" % r[0]))]
    print("%d matches indexed, %d to download" % (len(rows), len(todo)), flush=True)
    done = [0]

    def one(mid):
        for attempt in range(3):
            try:
                S.match(mid, need_team=True); break
            except Exception:
                time.sleep(2 + 3 * attempt)
        done[0] += 1
        if done[0] % 200 == 0:
            print("  %d / %d" % (done[0], len(todo)), flush=True)

    with ThreadPoolExecutor(6) as ex:
        list(ex.map(one, todo))
    print("fetch complete", flush=True)


MARKET = {"passes": lambda s: S.fval(s, "Accurate passes", "total"), "shots": lambda s: S.fval(s, "Total shots"),
          "sot": lambda s: S.fval(s, "Shots on target"), "saves": lambda s: S.fval(s, "Saves")}


def build():
    idx = json.load(open(IDX))
    out = []
    for mid, lg, season, date, hid, aid in idx:
        f = os.path.join(S.CACHE, "m%s.json" % mid)
        if not os.path.exists(f):
            continue
        m = json.load(open(f, encoding="utf-8"))
        ts = m.get("teamStats") or {}
        teams = [t.get("id") for t in m.get("teams", [])]
        if len(teams) != 2:
            continue
        for pid, p in (m.get("playerStats") or {}).items():
            st = p.get("stats") or []
            mins = S.fval(st, "Minutes played")
            if not mins:
                continue
            gk = S.fval(st, "Saves") is not None or S.fval(st, "Goals conceded") is not None and S.fval(st, "Total shots") is None
            tid = p.get("teamId")
            side = teams.index(tid) if tid in teams else None
            row = dict(mid=mid, lg=lg, season=season, date=date, pid=int(pid), name=p.get("name"), team=tid,
                       opp=teams[1 - side] if side is not None else None, home=(side == 0), mins=mins, gk=bool(gk))
            for k, fn in MARKET.items():
                v = fn(st)
                row[k] = v if v is not None else (0 if k in ("shots", "sot") and not gk else (0 if k == "saves" and gk else None))
            if side is not None:
                for k, v in ts.items():
                    row["t_" + k] = v[side]; row["o_" + k] = v[1 - side]
            out.append(row)
    json.dump(out, open("_soccer_hist_rows.json", "w"))
    print("%d player-match rows from %d matches" % (len(out), len({r['mid'] for r in out})))


if __name__ == "__main__":
    {"fetch": fetch, "build": build}[sys.argv[1]]()
