"""Live price check + honest price capture. Run this BEFORE every bet.

    python _price.py                        # today's card: every pick, live price, clears or not
    python _price.py "Thomas Saggese" under # one player, all apps, right now
    python _price.py log "<pick>" -164      # write a placed bet's REAL price into the ledger

Why this exists (2026-09-22): the board stores the price as it was when the board was BUILT,
usually mid-morning. By first pitch those prices have moved a long way -- and on 18 of today's
rows the stored under price matched the live OVER. So every backtest priced off board rows was
measuring bets we could not have taken, including the "+16% per bet" HRR number, which is now
withdrawn.

Rule from here: a pick is only real at the price captured when we name it. This tool pulls the
live Underdog and PrizePicks numbers, compares them to the bar, and writes the number down.
"""
import json, sys, os, re, datetime, urllib.request

UA = {"User-Agent": "Mozilla/5.0 Chrome/124", "Accept": "application/json"}
PPUA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept": "application/json"}
g = lambda u, h=UA: json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=45).read())
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
BAR = 0.05                     # a pick needs this much value at the REAL price
be = lambda o: abs(o) / (abs(o) + 100) if o < 0 else 100 / (o + 100)
LEDGER = "price_checks.jsonl"


def worst_price(p, bar=BAR):
    """The worst American price that still clears the bar for a model probability p."""
    need = p / (1 + bar)
    if need >= 1:
        return None
    return -round(100 * need / (1 - need)) if need >= 0.5 else round(100 * (1 - need) / need)


def underdog(stat_filter=None):
    """Live Underdog board -> {(player, stat): {side: (american, multiplier, line)}}"""
    d = g("https://api.underdogfantasy.com/v1/over_under_lines")
    P = {p["id"]: p for p in d["players"]}
    A = {a["id"]: a for a in d["appearances"]}
    G = {gm["id"]: gm for gm in d.get("games", [])}
    out = {}
    for l in d["over_under_lines"]:
        ap = (l.get("over_under") or {}).get("appearance_stat") or {}
        a = A.get(ap.get("appearance_id"))
        if not a:
            continue
        pl = P.get(a.get("player_id")) or {}
        nm = ("%s %s" % (pl.get("first_name") or "", pl.get("last_name") or "")).strip()
        stat = ap.get("display_stat") or ""
        if stat_filter and stat_filter.lower() not in stat.lower():
            continue
        sides = {}
        for o in l.get("options", []):
            side = "under" if o.get("choice") == "lower" else "over"
            try:
                am = float(o.get("american_price"))
            except (TypeError, ValueError):
                am = None
            sides[side] = (am, o.get("payout_multiplier"), float(l["stat_value"]))
        gm = G.get(a.get("match_id")) or {}
        out[(norm(nm), stat, float(l["stat_value"]))] = dict(player=nm, stat=stat, sides=sides,
                                     game=gm.get("title"), start=gm.get("scheduled_at"))
    return out


def prizepicks(league_id=2):
    try:
        d = __import__("_ppcache").projections(league_id)
    except Exception as e:
        print("  (prizepicks unavailable: %s)" % e)
        return {}
    inc = {(x["type"], x["id"]): x for x in d.get("included", [])}
    out = {}
    for x in d["data"]:
        a = x["attributes"]
        pl = inc.get(("new_player", x["relationships"]["new_player"]["data"]["id"]), {}).get("attributes", {})
        out.setdefault((norm(pl.get("name")), (a.get("stat_type") or "")), {})[a.get("odds_type")] = a.get("line_score")
    return out


def check(player, side=None, stat="Hits + Runs + RBIs", model=None):
    ud = underdog(stat)
    pp = prizepicks()
    key = next((k for k in ud if k[0] == norm(player)), None)   # any line for a lookup
    if not key:
        cand = sorted({ud[k]["player"] for k in ud if norm(player)[:5] in k[0]})
        print("not on the Underdog board: %s%s" % (player, ("  did you mean: " + ", ".join(cand[:5])) if cand else ""))
        return None
    row = ud[key]
    print("\n%s -- %s   line %s   (%s)" % (row["player"], row["stat"],
                                           list(row["sides"].values())[0][2], row["game"]))
    for s, (am, mult, line) in sorted(row["sides"].items()):
        mark = ""
        if model is not None and (side is None or s == side):
            v = model / be(am) - 1 if am else None
            mark = "   value %+.1f%%  %s" % (100 * v, "CLEARS" if v >= BAR else "does NOT clear") if v is not None else ""
        print("   Underdog  %-6s %+6s   payout %-5s%s" % (s, int(am) if am else "?", mult, mark))
    ppk = next((k for k in pp if k[0] == norm(player)), None)
    if ppk:
        print("   PrizePicks lines: %s" % ", ".join("%s %s" % (k, v) for k, v in pp[ppk].items()))
    if model is not None:
        w = worst_price(model)
        print("   model %.0f%%  ->  take at %+d or better" % (100 * model, w))
    return row


def card(day=None):
    """Every HRR pick on today's board, re-priced live."""
    import glob
    day = day or datetime.date.today().isoformat()
    files = sorted(glob.glob("pp/boards/%s_*.json" % day), key=os.path.getmtime)
    if not files:
        print("no board for", day); return
    b = json.load(open(files[-1], encoding="utf-8"))
    ud = underdog("Hits + Runs + RBIs")
    print("Live price check -- %s   (board built %s)\n" % (day, b.get("built_at", "?")[:16]))
    print("%-22s %-6s %7s %9s %9s  %s" % ("player", "side", "model", "board", "LIVE", "verdict"))
    live_rows = []
    for p in sorted(b["picks"], key=lambda x: -x.get("raw", 0)):
        if p["market"] != "HRR" or not p.get("odds"):
            continue
        # match the LINE too -- Underdog posts several lines per player and comparing a
        # 1.5 pick against a live 0.5 line was the first version's bug
        key = next((k for k in ud if k[0] == norm(p["selection"]) and abs(k[2] - p["line"]) < 0.01), None)
        if not key:
            continue
        side = "under" if p["side"] == "UNDER" else "over"
        am = (ud[key]["sides"].get(side) or (None,))[0]
        if am is None:
            continue
        v = p["raw"] / be(am) - 1
        own = p.get("season_rate") or 0
        ok = v >= BAR and p["raw"] <= own + 0.02
        why = "CLEARS" if ok else ("value %+.0f%%" % (100 * v) if v < BAR else "model above own rate")
        if ok or v >= BAR:
            print("%-22s %-6s %6.0f%% %9d %9d  %s" % (p["selection"][:22], p["side"], 100 * p["raw"],
                                                      p["odds"], am, why))
        live_rows.append(dict(player=p["selection"], side=p["side"], model=p["raw"],
                              board_odds=p["odds"], live_odds=am, value=round(v, 4), clears=ok))
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(ts=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                day=day, rows=live_rows)) + "\n")
    good = [r for r in live_rows if r["clears"]]
    print("\n%d of %d picks still clear at the live price" % (len(good), len(live_rows)))
    moved = [r for r in live_rows if abs(r["board_odds"] - r["live_odds"]) >= 25]
    print("%d picks moved 25+ points from the board price" % len(moved))
    print("(captured to %s -- the forward record prices off THIS, not the board)" % LEDGER)


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        card()
    elif a[0] == "log":
        rec = dict(ts=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   pick=a[1], taken_odds=float(a[2]), note=" ".join(a[3:]))
        open(LEDGER, "a", encoding="utf-8").write(json.dumps(rec) + "\n")
        print("logged:", rec["pick"], "at", rec["taken_odds"])
    else:
        check(a[0], a[1] if len(a) > 1 else None,
              model=float(a[2]) if len(a) > 2 else None)
