"""FRESH-LINE ALERTS (2026-10-07, user: "speed up researching lines ... to beat lines before they change").

    python _fresh.py            # run inside the hourly LineWatch task, right after the snapshot

Every hour: re-run the NHL screen for today + tomorrow (it scores every PP/UD line with the role model and logs calls), then alert
on any PROVEN-market leg we have not alerted before. PROVEN markets come from the graded table (memory project_standard_pick_markets):
  * NHL BET-tier (TAKE) shots-on-goal OVERS on PrizePicks standard lines -- 31-10 (76%) since 9/30.
Promising markets (NHL TAKE points overs, soccer TAKE passes unders) alert as TRACK ($1). Nothing else alerts.
Alert = Windows desktop notification + site/fresh.json + daily_log/fresh.log. Already-alerted legs live in _fresh_seen.json.
"""
import os, sys, json, datetime, subprocess

CT = datetime.timezone(datetime.timedelta(hours=-5))
SEEN = "_fresh_seen.json"
PY = sys.executable


def proven(r):
    c, st = str(r.get("call", "")), (r.get("stat") or "").lower()
    if r.get("venue") != "PP" or r.get("kind") not in (None, "standard"):
        return None
    if r["sport"] == "NHL" and c.startswith("TAKE OVER") and "shot" in st:
        return "BET"
    if r["sport"] == "NHL" and c.startswith("TAKE OVER") and st in ("points", "pts"):
        return "TRACK"
    if r["sport"] == "SOCCER" and c.startswith("TAKE UNDER") and "pass" in st:
        return "TRACK"
    return None


def toast(title, body):
    ps = ("Add-Type -AssemblyName System.Windows.Forms; $n=New-Object System.Windows.Forms.NotifyIcon; "
          "$n.Icon=[System.Drawing.SystemIcons]::Information; $n.Visible=$true; "
          "$n.ShowBalloonTip(15000,'%s','%s',[System.Windows.Forms.ToolTipIcon]::Info); Start-Sleep -Seconds 16; $n.Dispose()"
          % (title.replace("'", ""), body.replace("'", "")[:240]))
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps])
    except Exception:
        pass


def extra_sources(seen, today):
    """10/7 user: same speed loop for NFL (cap EARLY in the week), LoL/CS2 esports and NBA. None of these markets is PROVEN yet,
    so they alert as TRACK ($1 / paper) until their graded record clears 57.7% -- then they get promoted to BET in proven()."""
    out = []
    now = datetime.datetime.now(CT).strftime("%H:%M")

    def push(key, **kw):
        if key in seen:
            return
        seen.add(key); out.append(dict(kw, found=now))

    # NFL: PP posts Sunday lines Mon-Wed; score them at release (2026 role logs + injuries) before Saturday's settle.
    try:
        subprocess.run([PY, "_nflscreen.py"], capture_output=True, timeout=1200, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        import re as _re, _props as P, _mismatch as M, _fanduel
        nm = lambda s: _re.sub(r"[^a-z0-9]", "", (s or "").lower())
        by = {}
        try:
            for (pl, st, ln), pr in list(P.pinnacle_props(M.PIN_LEAGUE["NFL"]).items()) + list(_fanduel.props("nfl").items()):
                by.setdefault((pl, st), []).append((ln, pr))
        except Exception as e:
            print("nfl sharp:", e)
        cand = []
        for r in json.load(open("_nfl_screen_out.json", encoding="utf-8")):
            if r.get("shrunk", 0) < 0.72 or r.get("n", 0) < 4 or r.get("status"):
                continue
            st = M.STAT.get(nm(r["stat"])); R = by.get((nm(r["player"]), st)) if st else None
            po = M.p_over_at(R, r["line"], st) if R else None
            sharp = None if po is None else (po if r["side"] == "higher" else 1 - po)
            if sharp is not None and sharp < 0.5:
                continue                                           # the sharp books disagree -> not a leg (bet-selection bar)
            r["sharp"] = sharp; cand.append(r)
        cand.sort(key=lambda r: -((r["sharp"] or 0) * 2 + r["shrunk"]))       # sharp-confirmed first, then own rate
        for r in cand[:5]:
            if True:
                push("NFL|%s|%s|%s" % (r["player"], r["stat"], r["line"]), tier="TRACK", sport="NFL-EARLY", player=r["player"], team=r.get("team26"),
                     stat=r["stat"], line=r["line"], side="OVER" if r["side"] == "higher" else "UNDER", p=round(r["shrunk"], 3),
                     h2h="own %d/%d, sharp %s" % (round(r["raw"] * r["n"]), r["n"], ("%.0f%%" % (100 * r["sharp"])) if r["sharp"] is not None else "-"), start=r.get("game"))
    except Exception as e:
        print("nfl:", e)
    # LoL: PP single kills lines; under when the player's FULL-SEASON maps 1+2 average sits well under the line (10/7 rule: never last-10).
    try:
        import _props as P, _lol_check as C
        lolc = []
        for l in P.prizepicks(121, max_age=900):
            if l.get("kind") != "standard" or "+" in l["player"] or l["stat"] != "MAPS 1-2 Kills":
                continue
            ser = [x[1] for x in C.series_log(l["player"]) if x[1] is not None]
            if len(ser) < 6:
                continue
            avg = sum(ser) / len(ser)
            if avg <= 0.75 * l["line"]:
                lolc.append((avg / l["line"], l, avg, len(ser)))
        for ratio, l, avg, nser in sorted(lolc, key=lambda x: x[0])[:5]:
            if True:
                ser = [0] * nser
                push("LOL|%s|%s|%s" % (l["player"], l["line"], l.get("start")), tier="TRACK", sport="LoL", player=l["player"], team=l.get("team"),
                     stat="Maps 1-2 kills", line=l["line"], side="UNDER", p=round(1 - avg / l["line"], 3), h2h="season avg %.1f over %d series" % (avg, len(ser)),
                     start=l.get("start"))
    except Exception as e:
        print("lol:", e)
    # CS2: the day's top-5 model edges (the BETS bucket beat the rest 3 days running)
    try:
        legs = []
        for l in open("cs2_paper.jsonl", encoding="utf-8"):
            r = json.loads(l)
            if r.get("result") is None and str(r.get("start", ""))[:10] in (today.isoformat(), (today + datetime.timedelta(days=1)).isoformat()):
                legs.append(r)
        legs.sort(key=lambda r: -(r.get("edge") or 0))
        names = set()
        for r in legs:
            if r["player"] in names or len(names) == 5:
                continue
            names.add(r["player"])
            push("CS2|%s|%s|%s" % (r["player"], r["stat"], r["line"]), tier="TRACK", sport="CS2", player=r["player"], team=r.get("team"), stat=r["stat"],
                 line=r["line"], side="OVER" if r["side"] == "higher" else "UNDER", p=round(r.get("model_p") or 0, 3), h2h="edge %+.0f%%" % (100 * (r.get("edge") or 0)),
                 start=r.get("start"))
    except Exception as e:
        print("cs2:", e)
    # NBA: regular season from 10/20 -> the basketball screen's TAKE legs (preseason minutes are a guess, so not before)
    if today.isoformat() >= "2026-10-20":
        try:
            subprocess.run([PY, "_bball.py", "screen", "nba", today.isoformat()], capture_output=True, timeout=900, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
            for l in open("calls_log.jsonl", encoding="utf-8"):
                r = json.loads(l)
                if r.get("date") == today.isoformat() and r["sport"] == "NBA" and r.get("venue") == "PP" and str(r.get("call", "")).startswith("TAKE"):
                    push("NBA|%s|%s|%s" % (r["player"], r["stat"], r["line"]), tier="TRACK", sport="NBA", player=r["player"], team=r.get("team"), stat=r["stat"],
                         line=r["line"], side="OVER" if "OVER" in r["call"] else "UNDER", p=round(r.get("value") or 0, 3), h2h=r.get("h2h"), start=r.get("start"))
        except Exception as e:
            print("nba:", e)
    return out


def main():
    today = datetime.datetime.now(CT).date()
    for d in (today, today + datetime.timedelta(days=1)):
        subprocess.run([PY, "_props.py", "nhl", d.isoformat()], capture_output=True, timeout=900,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    seen = set(json.load(open(SEEN))) if os.path.exists(SEEN) else set()
    days = {today.isoformat(), (today + datetime.timedelta(days=1)).isoformat()}
    new = []
    for l in open("calls_log.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if r.get("date") not in days:
            continue
        tier = proven(r)
        if not tier:
            continue
        if tier == "BET" and (r.get("value") or 0) < 0.577:
            continue
        key = "%s|%s|%s|%s" % (r["date"], r["player"], r["stat"], r["line"])
        if key in seen:
            continue
        seen.add(key)
        new.append(dict(tier=tier, player=r["player"], team=r.get("team"), stat=r["stat"], line=r["line"], side="OVER" if "OVER" in r["call"] else "UNDER",
                        p=round(r.get("value") or 0, 3), h2h=r.get("h2h"), start=r.get("start"), found=datetime.datetime.now(CT).strftime("%H:%M")))
    new += extra_sources(seen, today)
    json.dump(sorted(seen), open(SEEN, "w"))
    if new:
        os.makedirs("site", exist_ok=True)
        old = json.load(open("site/fresh.json", encoding="utf-8")) if os.path.exists("site/fresh.json") else []
        json.dump((new + old)[:200], open("site/fresh.json", "w", encoding="utf-8"), ensure_ascii=False)
        bets = [n for n in new if n["tier"] == "BET"]
        for n in new:
            print("%s %-5s %-22s %-4s %-14s %s %s  %.0f%%  h2h %s" % (n["found"], n["tier"], n["player"], n["team"] or "", n["stat"], n["side"], n["line"], 100 * n["p"], n["h2h"]))
        if bets:
            toast("PropDesk: %d new BET leg%s" % (len(bets), "s" if len(bets) > 1 else ""),
                  "; ".join("%s %s %s %s (%.0f%%)" % (b["player"], b["side"], b["line"], b["stat"], 100 * b["p"]) for b in bets[:4]))
    else:
        print("no new proven-market legs")


if __name__ == "__main__":
    main()
