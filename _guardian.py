"""SLIP GUARDIAN (11/20, user: "do the slip guardian"). Watches every OPEN slip leg from the ledger until tip and pings the phone (ntfy) +
Discord (as a PULLED alert, which the quiet-Discord rule allows) when something breaks a leg:
  * the player is now OUT / doubtful / questionable / day-to-day        (NBA, ESPN injuries)
  * a teammate who played the team's last game (25+ mpg) is now OUT  -> breaks an UNDER (usage spikes)
  * PrizePicks pulled the leg's line, or the standard line moved off our number
Each problem alerts once (state in daily_log/guardian_seen.json). Legs whose game has started are skipped.
    python _guardian.py          # one sweep (run every 15-20 min pre-tip: laptop session cron + cloud hourly)
"""
import json, os, datetime, collections, urllib.request
import _stack as S

CT = S.CT
H = {"User-Agent": "Mozilla/5.0"}
SEEN = os.path.join("daily_log", "guardian_seen.json")
LEAGUE = {"NBA": 7, "NHL": 8}


def open_legs(today):
    out = []
    for l in open("live_paper.jsonl", encoding="utf-8"):
        if not l.strip():
            continue
        r = json.loads(l)
        if r.get("kind") != "LIVE" or r.get("result") not in (None, "PENDING") or (r.get("game_date") or r.get("date")) < today:
            continue
        for x in r.get("legs") or []:
            if x.get("result") in ("W", "L"):
                continue
            sp = next((s for s in ("NBA", "NHL") if s in (r.get("sport") or "").upper()), None)
            if sp and x.get("player") and x.get("line") is not None:
                out.append(dict(sp=sp, player=x["player"], stat=x.get("stat"), line=float(x["line"]), side=(x.get("side") or "").lower(),
                                slip="%s %s" % (r.get("market", "")[:20], r.get("stake"))))
    return out


def nba_injuries():
    try:
        d = json.load(urllib.request.urlopen(urllib.request.Request("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries", headers=H), timeout=30))
    except Exception:
        return {}, {}
    st = {}; out = collections.defaultdict(list)
    for t in d.get("injuries", []):
        for i in t.get("injuries", []):
            n = i["athlete"]["displayName"]; s = (i.get("status") or "")
            st[S.nn(n)] = (s, (i.get("shortComment") or "")[:120])
            if s.lower() == "out":
                out[t.get("displayName")].append(n)
    return st, out


def main():
    now = datetime.datetime.now(CT); today = now.date().isoformat()
    legs = open_legs(today)
    if not legs:
        print("guardian: no open legs"); return
    seen = set(json.load(open(SEEN))) if os.path.exists(SEEN) else set()
    st, outs = nba_injuries()
    boards = {}
    alerts = []
    D = None
    for g in legs:
        lg = LEAGUE[g["sp"]]
        if lg not in boards:
            import _ppcache as C
            try:
                d = C.projections(lg, 300)
                pl = {i["id"]: i["attributes"] for i in d.get("included", []) if i["type"] == "new_player"}
                boards[lg] = [(S.nn(pl.get(x["relationships"]["new_player"]["data"]["id"], {}).get("name", "")), x["attributes"]) for x in d["data"]]
            except Exception:
                boards[lg] = None
        rows = [a for n, a in (boards[lg] or []) if n == S.nn(g["player"]) and a["stat_type"] == g["stat"]]
        start = None
        if rows:
            start = datetime.datetime.fromisoformat(rows[0]["start_time"]).astimezone(CT)
            if start <= now:
                continue                                           # game started: nothing left to guard
        tag = "%s %s%g %s" % (g["player"], g["side"][:1].upper(), g["line"], g["stat"])
        if boards[lg] is not None and not rows and now.hour < 18:            # PP drops lines at tip-off: after 6 PM CT a missing line is usually just a started game
            alerts.append(("pulled|" + tag, "LINE PULLED: %s -- PrizePicks no longer lists it (injury/scratch news likely)" % tag))
        else:
            std = [float(a["line_score"]) for a in rows if a.get("odds_type") == "standard"]
            if std and g["line"] not in std:
                good = (std[0] > g["line"]) == (g["side"] == "over")          # over: line went up = you hold the better number
                alerts.append(("move|%s|%s" % (tag, std[0]), "LINE MOVED %s: %s -- standard now %g (you hold %g)" % (
                    "IN YOUR FAVOR" if good else "AGAINST YOU", tag, std[0], g["line"])))
        if g["sp"] == "NBA":
            s, note = st.get(S.nn(g["player"]), ("", ""))
            if s.lower() in ("out", "doubtful", "questionable", "day-to-day"):
                alerts.append(("status|%s|%s" % (tag, s), "STATUS: %s is %s -- %s" % (g["player"], s.upper(), note or "check before tip")))
            if g["side"] == "under":
                if D is None:
                    D = S.Data(today, "nba")
                k = S.pkey("nba", g["player"]); gs = D.G.get(k, [])
                team = gs[-1]["team"] if gs else None
                if team:
                    lastg = max((x["date"] for x in gs), default="")
                    for tname, names in outs.items():
                        for n in names:
                            tk = S.pkey("nba", n); tg = D.G.get(tk, [])
                            if tg and tg[-1]["team"] == team and tg[-1]["date"] >= lastg and sum(x["min"] for x in tg[-5:]) / max(len(tg[-5:]), 1) >= 25:
                                alerts.append(("newabs|%s|%s" % (tag, n), "NEW ABSENCE: %s (OUT) played %s's last game -- breaks the UNDER on %s" % (n, team, tag)))
    alerts = list(dict(alerts).items())                                  # same leg on two slips = one alert
    fresh = [(k, m) for k, m in alerts if k not in seen]
    for k, m in fresh:
        import _notify
        _notify.send("PULLED", m, "high")
        seen.add(k)
    os.makedirs("daily_log", exist_ok=True)
    json.dump(sorted(seen), open(SEEN, "w"))
    print("guardian %s: %d open legs, %d problems, %d new alerts" % (now.strftime("%H:%M"), len(legs), len(alerts), len(fresh)))
    for k, m in alerts:
        print("  " + m)


if __name__ == "__main__":
    main()
