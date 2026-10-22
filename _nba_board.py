"""NBA +EV / DISCREPANCY BOARD (10/20, user: "proceed into building the pickfinder model"). PickFinder's +EV and discrepancy boards,
built on FREE sharp feeds so it can run all day: FanDuel's public JSON (main O/U + every "X+" alt ladder) and Pinnacle's guest props.
No Odds API credits -- DraftKings stays for final checks (_nba_finder.py).

    python _nba_board.py            # every PrizePicks NBA standard + goblin line, priced, best first
    python _nba_board.py 2026-10-21 # one date only

Fair % at PP's exact number: an alt rung that IS the number ("25+" for a 24.5 line) beats a main line; a main O/U at the same number is
de-vigged; otherwise the nearest main is moved with the player's own game-to-game spread (short moves only). Consensus = mean of
FanDuel and Pinnacle where both price it. Flags: BET >= 57.7% (2-pick), STREAK goblin >= 90%, GAP = PP line differs from FanDuel's main.
"""
import sys, re, json, math, datetime, collections, sqlite3, statistics as st
from statistics import NormalDist
from concurrent.futures import ThreadPoolExecutor
import _fanduel as F, _props as PR

N = NormalDist()
CT = datetime.timezone(datetime.timedelta(hours=-5))
norm = lambda s: re.sub(r"[^a-z]", "", __import__("unicodedata").normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())   # 10/21: "Dončić" was "doni"
FD_STAT = {"points": "Points", "rebounds": "Rebounds", "assists": "Assists", "made threes": "3-PT Made", "pts + reb + ast": "Pts+Rebs+Asts",
           "pts + reb": "Pts+Rebs", "pts + ast": "Pts+Asts", "reb + ast": "Rebs+Asts", "steals": "Steals", "blocks": "Blocked Shots"}
PIN_STAT = {"points": "Points", "rebounds": "Rebounds", "assists": "Assists", "threes made": "3-PT Made", "pts & rebs & asts": "Pts+Rebs+Asts"}
TABS = ("player-points", "player-rebounds", "player-assists", "player-combos", "player-threes", "player-defense")
imp = lambda a: 100 / (a + 100) if a > 0 else -a / (-a + 100)
KEYS = {"Points": ("pts",), "Rebounds": ("reb",), "Assists": ("ast",), "3-PT Made": ("tpm",), "Pts+Rebs+Asts": ("pts", "reb", "ast"),
        "Pts+Rebs": ("pts", "reb"), "Pts+Asts": ("pts", "ast"), "Rebs+Asts": ("reb", "ast"), "Blocked Shots": ("blk",), "Steals": ("stl",)}


def fd_event(eid):
    alt, main = {}, {}
    for tab in TABS:
        x = F.g("%s/event-page?_ak=%s&eventId=%s&tab=%s" % (F.BASE, F.AK, eid, tab))
        for m in (x.get("attachments") or {}).get("markets", {}).values():
            nm = m.get("marketName", ""); R = m.get("runners") or []
            if nm.lower().startswith(("1st", "2nd", "3rd", "4th", "first")) or "qtr" in nm.lower() or "half" in nm.lower():
                continue
            mm = re.match(r"^(?:To (?:Score|Record) )?(\d+)\+ (.+)$", nm)
            if mm:                                               # alt ladder: "To Score 25+ Points", "3+ Made Threes"
                stat = FD_STAT.get(mm.group(2).lower().replace("made threes", "made threes"))
                if not stat:
                    continue
                for r in R:
                    a = ((r.get("winRunnerOdds") or {}).get("americanDisplayOdds") or {}).get("americanOdds")
                    if a is not None:
                        p = imp(a); alt[(norm(r.get("runnerName")), stat, int(mm.group(1)) - 0.5)] = p - 0.045 * p * (1 - p) * 2
                continue
            if " - " in nm:
                pl, kind = nm.split(" - ", 1); stat = FD_STAT.get(kind.lower())
                ov = next((r for r in R if r.get("runnerName", "").endswith("Over")), None)
                un = next((r for r in R if r.get("runnerName", "").endswith("Under")), None)
                if stat and ov and un:
                    po = imp(ov["winRunnerOdds"]["americanDisplayOdds"]["americanOdds"]); pu = imp(un["winRunnerOdds"]["americanDisplayOdds"]["americanOdds"])
                    main[(norm(pl), stat)] = (float(ov.get("handicap") or 0), po / (po + pu))
    return alt, main


def fanduel():
    d = F.g("%s/content-managed-page?page=CUSTOM&customPageId=nba&_ak=%s&timezone=America%%2FChicago" % (F.BASE, F.AK))
    ev = [e for e in ((d.get("attachments") or {}).get("events") or {}).values() if " @ " in e.get("name", "")]
    alt, main = {}, {}
    with ThreadPoolExecutor(6) as ex:
        for a, m in ex.map(lambda e: fd_event(e["eventId"]), ev):
            alt.update(a); main.update(m)
    return alt, main


def spreads():
    """each player's game-to-game sd per stat, 2025-26 (15+ min games)"""
    db = sqlite3.connect("sports.db"); f = lambda s, k: float(s.get(k) or 0)
    V = collections.defaultdict(list)
    for pl, s in db.execute("select player, stats from player_games where sport='NBA' and season='2025-26' and minutes>=15"):
        s = json.loads(s)
        for stat, ks in KEYS.items():
            V[(norm(pl), stat)].append(sum(f(s, k) for k in ks))
    return {k: (st.pstdev(v), v) for k, v in V.items() if len(v) >= 10}


def fair_over(pn, stat, line, alt, main, pin, SD):
    out = {}
    rung = math.floor(line) + 0.5 if line != int(line) else line + 0.5
    if (pn, stat, rung) in alt and (line != int(line) or (pn, stat, line - 0.5) in alt):
        out["fanduel"] = alt[(pn, stat, rung)] if line != int(line) else alt[(pn, stat, rung)] / (alt[(pn, stat, rung)] + 1 - alt[(pn, stat, line - 0.5)])
    elif (pn, stat) in main:
        pt, p0 = main[(pn, stat)]; sd = SD.get((pn, stat), (max(1.0, 0.25 * line), []))[0] or 1
        if pt == line:
            out["fanduel"] = p0
        elif abs(pt - line) <= 0.75 * sd:
            mu = pt + sd * N.inv_cdf(min(.98, max(.02, p0))); out["fanduel~"] = 1 - N.cdf((line - mu) / sd)   # ~ = moved, not a real price
    P = pin.get((pn, stat))
    if P:
        l0, p0 = min(P, key=lambda r: abs(r[0] - line)); sd = SD.get((pn, stat), (max(1.0, 0.25 * line), []))[0] or 1
        if l0 == line:
            out["pinnacle"] = p0
        elif abs(l0 - line) <= 0.75 * sd:
            mu = l0 + sd * N.inv_cdf(min(.98, max(.02, p0))); out["pinnacle~"] = 1 - N.cdf((line - mu) / sd)
    return out


def board(day=None):
    now = datetime.datetime.now(CT)
    alt, main = fanduel()
    pin = collections.defaultdict(list)
    try:
        for (pl, stt, ln), p in PR.pinnacle_props(487).items():
            if stt in PIN_STAT:
                pin[(norm(pl), PIN_STAT[stt])].append((ln, p))
    except Exception as e:
        print("pinnacle:", e)
    SD = spreads()
    import urllib.request, time
    d = None
    for w in (0, 20, 45, 90):                                    # PP 429s when the watchers poll too -- back off, never fake an empty board
        time.sleep(w)
        try:
            d = json.load(urllib.request.urlopen(urllib.request.Request("https://partner-api.prizepicks.com/projections?league_id=7&per_page=1000",
                                                                        headers={"User-Agent": "Mozilla/5.0"}), timeout=40)); break
        except Exception as e:
            print("PrizePicks retry:", e)
    if d is None:
        print("PrizePicks board unavailable -- try again in a few minutes"); return []
    PL = {x["id"]: x["attributes"] for x in d.get("included", []) if x["type"] == "new_player"}
    std = {}; rows = []
    for p in d["data"]:
        a = p["attributes"]; t = datetime.datetime.fromisoformat(a["start_time"]).astimezone(CT)
        if t < now or (day and t.date().isoformat() != day) or a["stat_type"] not in KEYS:
            continue
        pl = PL.get(p["relationships"]["new_player"]["data"]["id"], {}); kind = a.get("odds_type")
        if kind not in ("standard", "goblin"):
            continue
        ln = float(a["line_score"]); pn = norm(pl.get("name"))
        if kind == "standard":
            std[(pn, a["stat_type"])] = ln
        src = fair_over(pn, a["stat_type"], ln, alt, main, pin, SD)
        if not src:
            continue
        po = st.mean(src.values())
        own = SD.get((pn, a["stat_type"]), (None, []))[1]
        rows.append(dict(kind=kind, player=pl.get("name"), team=pl.get("team"), opp=a.get("description"), stat=a["stat_type"], line=ln, po=po,
                         src=src, own=own, t=t, pn=pn, promo=bool(a.get("is_promo"))))
    print("NBA board %s -- %d PP lines priced (FanDuel %d alt rungs / %d mains, Pinnacle %d)" % (day or "all dates", len(rows), len(alt), len(main), sum(len(v) for v in pin.values())))
    rate = lambda own, ln, side: (sum((x > ln) if side == "over" else (x < ln) for x in own) / len(own)) if own else None
    std_rows = []
    for r in rows:
        if r["kind"] != "standard":
            continue
        side = "over" if r["po"] >= 0.5 else "under"; f_ = r["po"] if side == "over" else 1 - r["po"]
        std_rows.append((f_, side, r))
    std_rows.sort(key=lambda x: -x[0])
    print("\nSTANDARD lines, best side (BET >= 57.7%):")
    import _nba_finder as NF
    rdb = sqlite3.connect("sports.db", timeout=60)
    for f_, side, r in std_rows[:20]:
        o = rate(r["own"], r["line"], side)
        real = [k for k in r["src"] if not k.endswith("~")]                  # 10/21: Beringer "70/70" was two MOVED estimates -- BET needs a real price
        # 10/21: Nembhard 75% last season = Haliburton out all year (27% with him) -> every priced leg gets the roster check
        rc = NF.roster_change(rdb, r["player"], r["stat"], r["line"], side) if f_ >= 0.577 else []
        bad = [m for m, n, x, a in rc if x is not None and x < 0.55]
        if bad:
            real = []; r["player"] = r["player"] + " [ROSTER: %s back]" % ", ".join(bad)
        print("  %s %3.0f%% %-5s %-24s %-4s %-14s %5g | %s | last season %s | %s %s" % ("BET " if f_ >= 0.577 and real else ("est " if f_ >= 0.577 else "    "), 100 * f_, side, r["player"], r["team"], r["stat"], r["line"],
              " ".join("%s %.0f" % (k[:3], 100 * (v if side == "over" else 1 - v)) for k, v in r["src"].items()), ("%.0f%%" % (100 * o)) if o is not None else "--",
              r["t"].strftime("%a %I:%M%p"), "PROMO" if r["promo"] else ""))
    gob = sorted([r for r in rows if r["kind"] == "goblin"], key=lambda r: -r["po"])
    print("\nGOBLINS (more only; STREAK >= 90%, one tier below standard marked *):")
    for r in gob[:15]:
        s_ = std.get((r["pn"], r["stat"])); o = rate(r["own"], r["line"], "over")
        print("  %s %3.0f%% %-24s %-4s %-14s MORE %-5g%s (std %s) | last season %s | %s" % ("STRK" if r["po"] >= 0.9 else "    ", 100 * r["po"], r["player"], r["team"], r["stat"], r["line"],
              "*" if s_ and r["line"] == max([g["line"] for g in gob if g["pn"] == r["pn"] and g["stat"] == r["stat"] and g["line"] < s_] or [None]) else " ", s_,
              ("%.0f%%" % (100 * o)) if o is not None else "--", r["t"].strftime("%a %I:%M%p")))
    print("\nGAPS (PP standard vs FanDuel main line, 1.5+ apart -- a stale line on one side):")
    for (pn, stat), ln in std.items():
        if (pn, stat) in main and abs(main[(pn, stat)][0] - ln) >= 1.5:
            r = next(x for x in rows if x["pn"] == pn and x["stat"] == stat)
            print("  %-24s %-14s PP %-5g FanDuel %-5g (FD over %.0f%% at its line)" % (r["player"], stat, ln, main[(pn, stat)][0], 100 * main[(pn, stat)][1]))
    return rows


if __name__ == "__main__":
    board(sys.argv[1] if len(sys.argv) > 1 else None)
