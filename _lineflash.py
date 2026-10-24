"""LINE FLASH (10/24, user: "whatever gets me there faster -- we need $500 soon"). The edge is seeing a good line FIRST: Maxey 33.5 -> 34.5
and Edey 22.5 -> 17.5 moved within hours. Every 10 minutes this re-screens the live PP board and pushes NEW legs that pass all three
checks of the bet bar (CLAUDE.md) to Discord/phone, so a 2-pick can be built minutes after the line posts.

    NBA     _nba_value.py projection (this season's minutes, measured context) on every STANDARD line, then:
              value    p >= 62% (2-pick 3x break-even 57.7% + room)
              role     every 2026-27 regular-season game on the side (>= 1 game), this season's minutes >= 80% of last season's
              h2h      vs tonight's opponent (2 seasons, 3+ games): on the side >= 50%
    SOCCER  club HIT passes from _soccer.py (money list 58-31), refreshed hourly

    python _lineflash.py            # one pass, prints what it would push (no push)
    python _lineflash.py loop 600   # every 10 min, pushes new legs (one push per new batch)

2-picks only (10/24: his PP 3-picks are 0-15, 2-picks 18-30 +16%). One leg per player; pair legs from different games.
"""
import sys, os, io, json, time, sqlite3, datetime, contextlib, subprocess, statistics as st
import _nba_finder as NF

CT = datetime.timezone(datetime.timedelta(hours=-5))
SEEN = os.path.join("data", "lineflash_seen.json")
P_MIN = 0.62
NEWS = []          # legs far off the line (PP likely priced news we don't have) -- printed for research, never pushed
LOG = "lineflash_paper.jsonl"


def stat_rows(db, player, stat, where, args=()):
    if stat == "Dunks":
        e = "(select coalesce(sum(dunks),0) from nba_qtr q where q.game_id=b.game_id and q.player_id=b.player_id)"
    elif stat in NF.BOX:
        e = NF.re.sub(r"\b([a-z]+)\b", r"b.\1", NF.BOX[stat])
    else:
        return []
    return db.execute("select b.min, %s from nba_box b join nba_games g using(game_id) where b.player=? and b.min > 0 and %s order by b.date"
                      % (e, where), (player,) + tuple(args)).fetchall()


def nba_legs(day):
    import _ppcache, _nba_value as V
    json.dump(_ppcache.projections(7), open(os.path.join("data", "nba_finder", "pp_nba_full.json"), "w", encoding="utf-8"))
    with contextlib.redirect_stdout(io.StringIO()):
        rows = V.run(day)
    db = sqlite3.connect("sports.db", timeout=60)
    now = datetime.datetime.now(CT)
    best = {}
    for r in rows:
        if r["kind"] != "standard" or r["p_ctx"] < P_MIN:
            continue
        if datetime.datetime.fromisoformat(r["start"]).astimezone(CT) < now:
            continue
        if abs(r["proj"] - r["line"]) / max(r["line"], 1) > 0.30:
            NEWS.append("%s %s %s %g (proj %.1f)" % (r["player"], r["stat"], r["side"], r["line"], r["proj"]))
            continue                                                  # 10/24 Maluach L19.5 proj 7.5 "100%": PP knows something -- check news, never push
        on = (lambda x: x > r["line"]) if r["side"] == "over" else (lambda x: x < r["line"])
        cur = stat_rows(db, r["player"], r["stat"], "g.season='2026-27' and g.stype='regular'")
        if not cur or not all(on(v) for _, v in cur):
            continue                                                  # role: every game this season on the side
        last_min = [m for m, _ in stat_rows(db, r["player"], r["stat"], "g.season='2025-26' and g.stype='regular'")]
        if last_min and st.mean(m for m, _ in cur[-3:]) < 0.8 * st.mean(last_min):
            continue                                                  # role shrank
        h = [v for _, v in stat_rows(db, r["player"], r["stat"], "g.stype in ('regular','post') and b.opp=? and b.date >= '2024-10-01'", (r["opp"],)) if v != r["line"]]
        hr = sum(on(v) for v in h) / len(h) if h else None
        if h and len(h) >= 3 and hr < 0.5:
            continue                                                  # head-to-head disagrees
        r["cur"] = [round(v, 1) for _, v in cur]; r["h2h"] = [round(v, 1) for v in h][-5:]; r["h2h_rate"] = hr
        k = r["player"]
        if k not in best or r["p_ctx"] > best[k]["p_ctx"]:
            best[k] = r                                               # one leg per player
    out = []
    for r in sorted(best.values(), key=lambda r: -r["p_ctx"]):
        t = datetime.datetime.fromisoformat(r["start"]).astimezone(CT).strftime("%I:%M%p").lstrip("0")
        out.append(dict(key="NBA|%s|%s|%s|%s|%s" % (day, r["player"], r["stat"], r["side"], r["line"]), game="%s-%s" % tuple(sorted((r["team"], r["opp"]))),
                        p=r["p_ctx"], strong=(r["tier"] == "VALUE" and r["p_ctx"] >= 0.70), text="**%s** %s **%s %g** (%s v %s %s) · %.0f%% · proj %.1f · this season %s · h2h %s%s"
                        % (r["player"], r["stat"], "HIGHER" if r["side"] == "over" else "LOWER", r["line"], r["team"], r["opp"], t, 100 * r["p_ctx"],
                           r["proj"], r["cur"], r["h2h"] or "--", (" · " + "; ".join(r["why"])) if r["why"] else "")))
    return out


def soccer_legs(day, refresh):
    if refresh:
        subprocess.run([sys.executable, "_soccer.py", day], capture_output=True, timeout=1500, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    out, now = [], datetime.datetime.now(CT)
    if not os.path.exists("soccer_paper.jsonl"):
        return out
    for l in open("soccer_paper.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if r.get("date") != day or r.get("verdict") != "HIT" or r.get("stat") != "Passes Attempted" or r.get("result"):
            continue
        if datetime.datetime.fromisoformat(r["start"]).astimezone(CT) < now:
            continue
        t = datetime.datetime.fromisoformat(r["start"]).astimezone(CT).strftime("%I:%M%p").lstrip("0")
        out.append(dict(key="SOC|%s|%s|%s|%s" % (day, r["player"], r["side"], r["line"]), game="SOC-%s-%s" % (r["team"], r.get("opp")), p=r["p"],
                        text="**%s** Passes **%s %g** (%s v %s %s) · %.0f%% · %d/%d under · last 5 %s"
                        % (r["player"], "LOWER" if r["side"] == "under" else "HIGHER", r["line"], r["team"], r.get("opp"), t, 100 * r["p"],
                           r.get("hits", 0), r.get("n", 0), r.get("last5"))))
    return out


def one_pass(push=False, soccer_refresh=False):
    day = datetime.datetime.now(CT).date().isoformat()
    seen = json.load(open(SEEN, encoding="utf-8")) if os.path.exists(SEEN) else {}
    legs = []
    for f, a in ((nba_legs, (day,)), (soccer_legs, (day, soccer_refresh))):
        try:
            legs += f(*a)
        except Exception as e:
            print("lineflash %s: %s" % (f.__name__, e))
    new = [g for g in legs if g["key"] not in seen]
    stamp = datetime.datetime.now(CT).strftime("%H:%M")
    print("%s line flash: %d legs pass all three checks, %d new" % (stamp, len(legs), len(new)))
    for g in sorted(legs, key=lambda g: -g["p"]):
        print("  %s %s" % ("NEW" if g in new else "   ", g["text"]))
    if NEWS:
        print("  NEWS CHECK (30%%+ off the line -- research before betting): %s" % "; ".join(sorted(set(NEWS))[:12]))
    for g in new:
        seen[g["key"]] = stamp
    if push:
        json.dump(seen, open(SEEN, "w", encoding="utf-8"))
    if push and new:
        with open(LOG, "a", encoding="utf-8") as f:
            for g in new:
                f.write(json.dumps(dict(day=day, key=g["key"], p=g["p"], text=g["text"], pushed=stamp)) + chr(10))
        import _push
        if os.path.exists(os.path.join("data", "lineflash_quiet_%s.flag" % day)):
            new = [g for g in new if g.get("strong")]                 # 10/24 user: "only bets today, unless you found something" --
            if not new:                                               # quiet day pings only Edey-type finds (measured context moved it 8+ pts, 70%+)
                return legs
        body = "\n".join(g["text"] for g in sorted(new, key=lambda g: -g["p"])[:8])
        body += "\n_value + role + h2h all pass · 2-picks · one leg per player · pair legs from different games_"
        _push.push("⚡ NEW LINES -- pass all 3 checks (2-pick legs)", body)
    return legs


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["loop"]:
        n = 0
        while True:
            try:
                one_pass(push=True, soccer_refresh=(n % 6 == 0))
            except Exception as e:
                print("lineflash error:", e)
            n += 1
            time.sleep(int(a[1]) if len(a) > 1 else 600)
    else:
        one_pass()
