"""PROP LINE-MOVE ALERTS (10/20, user: "add everything"). PickFinder's line-movement alerts for our props.

    python _prop_moves.py            # one pass: snapshot PrizePicks standard lines, alert on moves since the last pass
    python _prop_moves.py loop 300   # keep watching, a pass every 300 s

Alerts (console + daily_log/feed.txt + phone push on the ntfy topic in notify.json):
    * any line on one of HIS OPEN BETS (live_paper.jsonl, result still open) that moves at all, or gets pulled
    * any NBA/NHL/NFL/CFB/soccer standard line that moves 10%+ (news or a stale line being fixed -- the Sandro/Puka pattern)
Measured context: the result follows PP's line move 55% of the time, and a line PP raises after we bet is CLV for the over.
"""
import sys, os, json, time, datetime, re, urllib.request

CT = datetime.timezone(datetime.timedelta(hours=-5))
LEAGUES = {7: "NBA", 8: "NHL", 9: "NFL", 15: "CFB", 82: "SOCCER"}
SNAP = os.path.join("data", "prop_snap.json")
norm = lambda s: re.sub(r"[^a-z]", "", (s or "").lower())


def board(lg):
    for w in (0, 20, 45):
        time.sleep(w)
        try:
            d = json.load(urllib.request.urlopen(urllib.request.Request("https://partner-api.prizepicks.com/projections?league_id=%d&per_page=1000" % lg,
                                                                        headers={"User-Agent": "Mozilla/5.0"}), timeout=40))
            P = {x["id"]: x["attributes"] for x in d.get("included", []) if x["type"] == "new_player"}
            out = {}
            for p in d["data"]:
                a = p["attributes"]
                if a.get("odds_type") != "standard":
                    continue
                pl = P.get(p["relationships"]["new_player"]["data"]["id"], {})
                out["%s|%s|%s" % (LEAGUES[lg], pl.get("name"), a["stat_type"])] = float(a["line_score"])
            return out
        except Exception:
            continue
    return None                                                     # failed fetch -- never read as "pulled"


def open_legs():
    legs = set()
    for x in open("live_paper.jsonl", encoding="utf-8"):
        r = json.loads(x)
        if r.get("result") is None and r.get("book") == "PrizePicks":
            for part in (r.get("selection") or "").split("/"):
                m = re.match(r"\s*(.+?)\s+[OU]\d", part)
                if m:
                    legs.add(norm(m.group(1)))
    return legs


def push(msg):
    os.makedirs("daily_log", exist_ok=True)
    with open(os.path.join("daily_log", "feed.txt"), "a", encoding="utf-8") as f:
        f.write("%s %s\n" % (datetime.datetime.now(CT).strftime("%m/%d %H:%M"), msg))
    try:
        topic = json.load(open("notify.json", encoding="utf-8")).get("ntfy_topic")
        if topic:
            urllib.request.urlopen(urllib.request.Request("https://ntfy.sh/%s" % topic, data=msg.encode("utf-8"), headers={"Title": "PROP LINE MOVE"}), timeout=15)
    except Exception as e:
        print("push:", e)


def one_pass():
    old = json.load(open(SNAP, encoding="utf-8")) if os.path.exists(SNAP) else {}
    new, failed = {}, set()
    for lg in LEAGUES:
        b = board(lg)
        if b is None:
            failed.add(LEAGUES[lg]); continue
        new.update(b); time.sleep(6)
    mine = open_legs(); alerts = []
    for k, ln in new.items():
        if k in old and old[k] != ln:
            lgname, pl, stat = k.split("|")
            mv = ln - old[k]; pct = abs(mv) / max(old[k], 1)
            if norm(pl) in mine:
                alerts.append("YOUR LEG %s %s %s: %g -> %g (%+g)" % (lgname, pl, stat, old[k], ln, mv))
            elif pct >= 0.10:
                alerts.append("BIG MOVE %s %s %s: %g -> %g (%+.0f%%)" % (lgname, pl, stat, old[k], ln, 100 * mv / max(old[k], 1)))
    for k in old:
        lgname = k.split("|")[0]
        if k not in new and lgname not in failed and norm(k.split("|")[1]) in mine:
            alerts.append("YOUR LEG PULLED %s" % k.replace("|", " "))
    keep = {k: v for k, v in old.items() if k.split("|")[0] in failed}        # keep last known lines for leagues that failed to load
    keep.update(new)
    os.makedirs("data", exist_ok=True)
    json.dump(keep, open(SNAP, "w", encoding="utf-8"))
    for a in alerts:
        print(a); push(a)
    print("%s pass: %d lines, %d alerts%s" % (datetime.datetime.now(CT).strftime("%H:%M"), len(new), len(alerts), (" (failed: %s)" % ", ".join(sorted(failed))) if failed else ""))
    return alerts


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["loop"]:
        gap = int(a[1]) if len(a) > 1 else 300
        while True:
            one_pass(); time.sleep(gap)
    else:
        one_pass()
