"""FAST-CLEAR ALERTS (10/22, user: "that was a leg on PP, now it ain't -- we're missing out on value").
PrizePicks moves/pulls the soft lines within an hour (Edgecombe 2PM O2.5, Jalen Green FGA, Sandro FGM). A full overview by hand is too slow,
so this re-grades every NBA standard line in the watcher's snapshot (data/prop_snap.json -- no extra PrizePicks calls) on each pass and
pushes NEW clears to Discord + phone immediately.

    python _fastclear.py            # one pass
    python _fastclear.py loop 300   # every 5 min (alongside _prop_moves.py)

CLEAR = the cushion group that has hit (10/20-21: projection 40%+ past the line on a non-tiny line went 11-0):
        starter (or 25+ min), same team as last season, last-20 rate >= 80% AND season rate >= 70% on the side, L20 projection 40%+ past
        the line, this season's games (preseason + regular) all on the side, line >= 1.5 (no 0.5 coin flips).
Still a lead, not a lock -- the alert says so; book price gets checked before money.
"""
import sys, os, json, time, sqlite3, datetime, statistics as st
import _nba_finder as NF, _nba_board as B

SNAP = os.path.join("data", "prop_snap.json")
SEEN = os.path.join("data", "fastclear_seen.json")
CT = datetime.timezone(datetime.timedelta(hours=-5))


def one_pass():
    if not os.path.exists(SNAP):
        return
    snap = json.load(open(SNAP, encoding="utf-8"))
    seen = json.load(open(SEEN, encoding="utf-8")) if os.path.exists(SEEN) else {}
    db = sqlite3.connect("sports.db", timeout=60)
    names = {B.norm(r[0]): r[0] for r in db.execute("select distinct player from nba_box where date >= '2025-10-01'")}
    hits = []
    for key, ln in snap.items():
        if not key.startswith("NBA|"):
            continue
        _, ppn, stat = key.split("|", 2)
        if "+" in ppn or stat not in NF.BOX or ln is None or float(ln) < 1.5:
            continue
        ln = float(ln); name = names.get(B.norm(ppn))
        if not name:
            continue
        R = NF.db_rows(db, name, stat)
        rows = [x for x in R["last"] if x[2] >= 20]
        if len(rows) < 20:
            continue
        v = [x[3] for x in rows]; proj = st.mean(v[-20:])
        side = "over" if proj > ln else "under"
        if abs(proj - ln) / ln < 0.40:
            continue
        rate = lambda X: (lambda D: sum((x > ln) if side == "over" else (x < ln) for x in D) / len(D) if D else 0)([x for x in X if x != ln])
        s, l20 = rate(v), rate(v[-20:])
        if s < .70 or l20 < .80:
            continue
        cur = [r[0] for r in db.execute("select %s from nba_box where player=? and date >= '2026-10-01' and min >= 15 order by date"
                                        % NF.BOX[stat], (name,))]
        if cur and not all((x > ln) if side == "over" else (x < ln) for x in cur):
            continue
        last_team = db.execute("select team from nba_box where player=? and min>0 and date between '2025-10-01' and '2026-08-01' order by date desc limit 1", (name,)).fetchone()
        now_team = db.execute("select team from nba_box where player=? and min>0 and date >= '2026-10-01' order by date desc limit 1", (name,)).fetchone()
        if last_team and now_team and last_team[0] != now_team[0]:
            continue
        tn = R["tonight"]
        if st.mean(R["mins_last"] or [0]) < 25 or (tn is not None and not tn[0]):
            continue                                         # bench / low-minute players = minutes bets (Holland, Barnes, McCain 10/22: 90% was 20+ min games only)
        k = "%s|%s|%s|%s" % (name, stat, side, ln)
        if k in seen:
            continue
        seen[k] = datetime.datetime.now(CT).isoformat(timespec="minutes")
        hits.append((name, stat, side, ln, proj, s, l20, cur))
    json.dump(seen, open(SEEN, "w", encoding="utf-8"))
    if hits:
        import _push
        body = "\n".join("**%s** %s **%s %g** · proj %.1f · season %.0f%% · L20 %.0f%% · 2026 %s" % (n, st_, "HIGHER" if sd == "over" else "LOWER", ln, pj, 100 * s, 100 * l, c)
                         for n, st_, sd, ln, pj, s, l, c in hits)
        _push.push("⚡ FAST CLEAR -- lock before it moves (check the book price)", body + "\n_cushion 40%+, starter, same team, every 2026 game on the side_")
        print(body)
    print("%s fast-clear pass: %d new" % (datetime.datetime.now(CT).strftime("%H:%M"), len(hits)))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["loop"]:
        while True:
            try:
                one_pass()
            except Exception as e:
                print("fastclear error:", e)
            time.sleep(int(a[1]) if len(a) > 1 else 300)
    one_pass()
