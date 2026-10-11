"""Valorant live card: price Underdog + PrizePicks kill lines with _val_model.

    python _val_live.py card [min_edge] [max_hours]
    python _val_live.py grade

Same shape as the CS2 card so the two can share the board page. Maps 1+2 only -- map 1 alone
is noise and the series lines carry veto risk. Every priced side goes to val_priced_all.jsonl;
picks over the edge floor go to val_paper.jsonl. Nothing here is live money until it has a
record: the model is calibrated on held-out maps, not on bets.
"""
import json, sys, os, re, math, datetime, urllib.request, collections
import _val_model as M

UA = {"User-Agent": "Mozilla/5.0 Chrome/124", "Accept": "application/json"}
PPUA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept": "application/json"}
g = lambda u, h=UA: json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=60).read())
CT = datetime.timezone(datetime.timedelta(hours=-5))
OUT = "val_paper.jsonl"
ALL = "val_priced_all.jsonl"
VERSION = "v1"
EDGE_FLOOR, EDGE_CAP = 0.03, 0.09     # same band as CS2 until Valorant has its own record
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
core = lambda s: norm(re.sub(r"(?i)(esports?|gaming|team|club|academy|gg)", "", s or "")) or norm(s)


def profiles_by_name(prof):
    idx = collections.defaultdict(list)
    for pid, p in prof["players"].items():
        idx[norm(p["name"])].append((p["maps"], pid, p))
    return {k: max(v)[1:] for k, v in idx.items()}


def pp_lines():
    """PrizePicks Valorant board -> {(player, stat): line}."""
    out = {}
    try:
        d = g("https://partner-api.prizepicks.com/projections?per_page=1000&league_id=159", PPUA)
    except Exception as e:
        print("prizepicks unavailable:", e)
        return out
    inc = {(x["type"], x["id"]): x for x in d.get("included", [])}
    for x in d["data"]:
        a = x["attributes"]
        if a.get("odds_type") != "standard":
            continue
        pl = inc.get(("new_player", x["relationships"]["new_player"]["data"]["id"]), {}).get("attributes", {})
        out[(norm(pl.get("name")), a["stat_type"].upper())] = a["line_score"]
    return out


def card(min_edge=EDGE_FLOOR, max_hours=None):
    prof = M.load_profiles()
    rows_hist = M.load_maps()
    S = M.State(rows_hist)
    NAME = profiles_by_name(prof)
    PP = pp_lines()
    d = g("https://api.underdogfantasy.com/v1/over_under_lines")
    P = {p["id"]: p for p in d["players"]}
    A = {a["id"]: a for a in d["appearances"]}
    G = {gm["id"]: gm for gm in d.get("games", []) if gm.get("sport_id") == "VAL"}
    now = datetime.datetime.now(datetime.timezone.utc)
    rows, miss = [], collections.Counter()

    for l in d["over_under_lines"]:
        o = l.get("over_under", {})
        ap = o.get("appearance_stat", {})
        stat = (ap.get("display_stat") or "")
        if "Maps 1+2" not in stat or "Kills" not in stat:
            continue
        a = A.get(ap.get("appearance_id"))
        if not a or a.get("match_id") not in G:
            continue
        gm = G[a["match_id"]]
        start = datetime.datetime.fromisoformat(gm["scheduled_at"].replace("Z", "+00:00"))
        hrs = (start - now).total_seconds() / 3600
        if hrs < -2 or (max_hours is not None and hrs > max_hours):
            continue
        pl = P.get(a.get("player_id"))
        if not pl:
            continue
        nm = norm((pl.get("first_name") or "") + (pl.get("last_name") or "")) or norm(pl.get("username"))
        hit = NAME.get(nm) or NAME.get(norm(pl.get("username")))
        if not hit:
            miss["no history for this player"] += 1
            continue
        pid, p = hit
        if p["maps"] < 8:
            miss["under 8 maps of history"] += 1
            continue
        teams = [t.strip() for t in re.split(r"\s+vs\.?\s+", gm.get("title", ""), flags=re.I)]
        if len(teams) != 2:
            miss["could not read the match title"] += 1
            continue
        mine = teams[0] if core(p["team"]) and (core(p["team"]) in core(teams[0]) or core(teams[0]) in core(p["team"])) else (
            teams[1] if core(p["team"]) and (core(p["team"]) in core(teams[1]) or core(teams[1]) in core(p["team"])) else None)
        if not mine:
            miss["roster move -- his team is not in this match"] += 1
            continue
        opp = teams[1] if mine == teams[0] else teams[0]
        winp = S.winp(p["team"], opp)
        line = float(l["stat_value"])
        mu = M.mean_kills(prof, S, pid, opp, winp, maps=2)
        if mu is None:
            continue
        po = M.over(mu, line)
        ppl = PP.get((nm, "MAPS 1-2 KILLS")) or PP.get((nm, "MAP 1-2 KILLS"))
        for side, pr in (("higher", po), ("lower", 1 - po)):
            rows.append(dict(ts=now.isoformat(), version=VERSION, game="val", match_id=a["match_id"],
                             match=gm["title"], start=gm["scheduled_at"],
                             start_ct=start.astimezone(CT).strftime("%a %H:%M"),
                             player=p["name"], pid=pid, team=mine, opp=opp, stat="Kills on Maps 1+2",
                             kind="k", maps=2, line=line, pp_line=ppl, side=side,
                             model_p=round(pr, 4), model_mu=round(mu, 2), breakeven=0.535,
                             edge=round(pr - 0.535, 4), map_winp=round(winp, 3),
                             n_maps_hist=p["maps"], flex=p.get("flex"), role=p.get("role")))

    rows.sort(key=lambda r: -r["edge"])
    print("history maps %d | priced sides %d | skipped %s | prizepicks lines %d"
          % (len(rows_hist), len(rows), dict(miss), len(PP)))
    print("%-6s %-6s %-14s %6s %6s %6s %5s %7s %5s  %s" %
          ("edge", "side", "player", "line", "PP", "chance", "real", "mean", "winp", "match (CT)"))
    print("  (real = what this model's calls actually hit on graded lines -- 10/10: ~50%, no edge yet)")
    for r in rows[:30]:
        print("%+5.1f%% %-6s %-14s %6.1f %6s %5.0f%% %4.0f%% %7.1f %5.2f  %s %s" % (
            100 * r["edge"], "under" if r["side"] == "lower" else "over", r["player"][:14], r["line"],
            r["pp_line"] if r["pp_line"] is not None else "-", 100 * r["model_p"], 100 * __import__("_calib_es").cal("val", r["model_p"]), r["model_mu"],
            r["map_winp"], r["match"][:28], r["start_ct"]))

    picks = [r for r in rows if min_edge <= r["edge"] < EDGE_CAP and not (0.45 <= r["map_winp"] <= 0.55)]
    print("\n" + "=" * 70)
    if picks:
        print("WORTH A LOOK  (%d lines) -- Valorant has NO record yet, these are paper only" % len(picks))
        for r in picks[:10]:
            shop = ""
            if r["pp_line"] is not None and r["pp_line"] != r["line"]:
                better = "PrizePicks" if ((r["pp_line"] > r["line"]) == (r["side"] == "lower")) else "Underdog"
                shop = "   better on %s (UD %.1f, PP %.1f)" % (better, r["line"], r["pp_line"])
            print("  %-13s %-5s %-5.1f kills   %s vs %s   %s%s" % (
                r["player"], "UNDER" if r["side"] == "lower" else "OVER", r["line"],
                r["team"][:16], r["opp"][:16], r["start_ct"], shop))
    else:
        print("NOTHING WORTH A LOOK. Everything is either a coin-flip map or priced right.")

    with open(ALL, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    done = set()
    if os.path.exists(OUT):
        for l in open(OUT, encoding="utf-8"):
            r = json.loads(l)
            done.add((r["match_id"], r["player"], r["side"], r["line"]))
    new = 0
    with open(OUT, "a", encoding="utf-8") as f:
        for r in picks:
            k = (r["match_id"], r["player"], r["side"], r["line"])
            if k in done:
                continue
            done.add(k); f.write(json.dumps(r) + "\n"); new += 1
    print("\nlogged %d new paper picks -> %s" % (new, OUT))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "card"
    if cmd == "card":
        card(float(sys.argv[2]) if len(sys.argv) > 2 else EDGE_FLOOR,
             float(sys.argv[3]) if len(sys.argv) > 3 else None)
    else:
        print(__doc__)
