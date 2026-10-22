"""NBA FULL-OVERVIEW SWEEP (10/21, user: "go through everyone again and overview each one... an overview would equal more of an edge
than just the price"). Every PrizePicks NBA standard line tonight gets the whole card, not just a price:

    price      FanDuel + Pinnacle fair % at PP's number (free; DraftKings only on finalists via _nba_finder.py)
    season     2025-26 rate on the side, 20+ min games (2024-25 when he missed last season); pushes dropped on whole lines
    last 20    same, last 20 games
    minutes    last-10 minutes + tonight's RotoWire role (bench overs = minutes bets)
    roster     teammates back/new tonight -> re-graded on shared 2024-25 games (Nembhard/Haliburton 75% -> 28%)
    h2h        his games vs this opponent, 2 seasons (measured 10/21: +3 to +6 pts, assists strongest) -- veto when strongly against
    projection L20 average vs the line

    python _nba_sweep.py              # tonight
    python _nba_sweep.py 2026-10-22

CLEAR = price >= 57.7% (real, not moved) or no price (niche) AND season >= 62% AND last 20 >= 60% AND role/roster/h2h not against.
"""
import sys, json, time, datetime, sqlite3, collections, statistics as st, urllib.request
import _nba_board as B, _nba_finder as NF, _props as PR

CT = datetime.timezone(datetime.timedelta(hours=-5))
norm = B.norm
ESPN = {"NYK": "NY", "GSW": "GS", "SAS": "SA", "NOP": "NO", "UTA": "UTAH", "WAS": "WSH"}


def pp_board():
    for w in (0, 30, 60, 90):
        time.sleep(w)
        try:
            d = json.load(urllib.request.urlopen(urllib.request.Request("https://partner-api.prizepicks.com/projections?league_id=7&per_page=1000",
                                                                        headers={"User-Agent": "Mozilla/5.0"}), timeout=40))
            json.dump(d, open("data/nba_finder/pp_nba_full.json", "w", encoding="utf-8"))
            return d
        except Exception as e:
            print("PrizePicks retry:", e)
    return json.load(open("data/nba_finder/pp_nba_full.json", encoding="utf-8"))     # last good pull


def sweep(day=None):
    now = datetime.datetime.now(CT); day = day or now.date().isoformat()
    d = pp_board()
    P = {x["id"]: x["attributes"] for x in d["included"] if x["type"] == "new_player"}
    alt, main = B.fanduel(); pin = collections.defaultdict(list)
    try:
        for (pl, stt, ln), p in PR.pinnacle_props(487).items():
            if stt in B.PIN_STAT:
                pin[(norm(pl), B.PIN_STAT[stt])].append((ln, p))
    except Exception as e:
        print("pinnacle:", e)
    SD = B.spreads()
    db = sqlite3.connect("sports.db", timeout=60)
    names = {norm(r[0]): r[0] for r in db.execute("select distinct player from nba_box where date >= '2024-10-01'")}
    out = []; seen = 0
    for p in d["data"]:
        a = p["attributes"]
        if a.get("odds_type") != "standard" or a["stat_type"] not in NF.BOX:
            continue
        t = datetime.datetime.fromisoformat(a["start_time"]).astimezone(CT)
        if t < now or t.date().isoformat() != day:
            continue
        pl = P.get(p["relationships"]["new_player"]["data"]["id"], {}); pp_name = pl.get("name") or ""
        if "+" in pp_name:
            continue
        name = names.get(norm(pp_name))
        if not name:
            continue
        seen += 1
        stat, ln = a["stat_type"], float(a["line_score"]); opp = ESPN.get(a.get("description"), a.get("description"))
        R = NF.db_rows(db, name, stat)
        rows = [x for x in R["last"] if x[2] >= 20]; src_season = "25-26"
        if len(rows) < 15:
            rows = [x for x in R.get("prev", []) if x[2] >= 20]; src_season = "24-25"
        if len(rows) < 15:
            continue
        v = [x[3] for x in rows]
        fo = B.fair_over(norm(name), stat, ln, alt, main, pin, SD) if stat in B.KEYS else {}
        real = {k: x for k, x in fo.items() if not k.endswith("~")}
        po = st.mean(real.values()) if real else None
        for side in ("over", "under"):
            def rate(X):
                D = [x for x in X if x != ln]
                return sum((x > ln) if side == "over" else (x < ln) for x in D) / len(D) if len(D) >= 5 else None
            s, l20 = rate(v), rate(v[-20:])
            price = None if po is None else (po if side == "over" else 1 - po)
            if s is None or s < 0.62 or (l20 or 0) < 0.60:
                continue
            if price is not None and price < 0.577:
                continue
            mins = [m for m in R["mins_last"][-10:]] or [0]
            tn = R["tonight"]; role = "START" if tn and tn[0] else ("BENCH" if tn else "?")
            flags = []
            if role == "BENCH" and side == "over":
                flags.append("BENCH over")
            if role == "?":
                flags.append("not in tonight's lineup")
            h2h = [x[3] for x in rows if x[1] == opp] + [x[3] for x in R.get("prev", []) if x[1] == opp and x[2] >= 20 and src_season == "25-26"]
            hr = rate(h2h) if len(h2h) >= 2 else None
            if len(h2h) >= 2:
                D = [x for x in h2h if x != ln]
                hr = sum((x > ln) if side == "over" else (x < ln) for x in D) / len(D) if D else None
            if hr is not None and hr <= 0.35:
                flags.append("H2H against")
            last_team = db.execute("select team from nba_box where player=? and min>0 and date between '2025-10-01' and '2026-08-01' order by date desc limit 1", (name,)).fetchone()
            tonight_team = ESPN.get(pl.get("team"), pl.get("team"))
            if src_season == "25-26" and last_team and last_team[0] != tonight_team:
                flags.append("NEW TEAM (%s -> %s)" % (last_team[0], tonight_team))   # 10/21 Morant: own 84% vs FanDuel 38% on Portland
            rc = NF.roster_change(db, name, stat, ln, side)
            for m, n, r, avg in rc:
                if r is not None and r < 0.55:
                    flags.append("ROSTER: %s back (%.0f%% with him)" % (m, 100 * r))
                elif r is None:
                    flags.append("new mate: %s" % m)
            proj = st.mean(v[-20:])
            score = st.mean([x for x in (price, s, l20) if x is not None]) + (0.04 if hr is not None and hr >= 0.75 else 0) - (0.06 if hr is not None and hr <= 0.35 else 0)
            soft = [f for f in flags if f.startswith("new mate")]
            hard = [f for f in flags if f not in soft] + (["2+ new starters"] if len(soft) >= 2 else [])   # one new face = note, two = role unmeasured
            out.append(dict(tag="CLEAR" if not hard else "flag", name=name, team=pl.get("team"), opp=opp, stat=stat, line=ln, side=side, price=price,
                            src=",".join(real) or "no price", s=s, l20=l20, n=len(v), ss=src_season, mins=st.mean(mins), role=role, h2h=h2h[-4:], hr=hr,
                            proj=proj, flags=flags, score=score, t=t))
    out.sort(key=lambda r: (r["tag"] != "CLEAR", -r["score"]))
    print("NBA FULL-OVERVIEW SWEEP %s -- %d standard lines overviewed, %d pass price + season + last 20\n" % (day, seen, len(out)))
    print("  %-5s %-24s %-4s %-20s %-6s %5s | %-14s | season  last20 | min  role  | h2h            | proj  | flags" % ("", "player", "tm", "stat", "side", "line", "price"))
    for r in out[:40]:
        print("  %-5s %-24s %-4s %-20s %-6s %5g | %-14s | %3.0f%%%s  %3.0f%% | %4.0f %-5s | %-14s | %5.1f | %s" % (
            r["tag"], r["name"][:24], r["team"], r["stat"][:20], r["side"], r["line"],
            ("%.0f%% %s" % (100 * r["price"], r["src"][:7])) if r["price"] is not None else "no price", 100 * r["s"], "*" if r["ss"] == "24-25" else " ",
            100 * (r["l20"] or 0), r["mins"], r["role"], ",".join("%g" % x for x in r["h2h"]) or "--", r["proj"], "; ".join(r["flags"]) or "-"))
    print("\n  * = 2024-25 sample (missed 2025-26). Finalists -> python _nba_finder.py \"player\" \"stat\" line side --opp XXX (DraftKings check)")
    return out


if __name__ == "__main__":
    sweep(sys.argv[1] if len(sys.argv) > 1 else None)
