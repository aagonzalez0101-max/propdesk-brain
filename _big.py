"""VALUE ALERTS + CLV TEST (2026-10-07; threshold changed same day to the VALUE tier: books >=60% at PP's number AND our model agrees). User: "I want 'holy shit this is big, PP has it lower/higher than what we project
AND what FanDuel and the sharps have it -- bet now'. Then by end of night / next few days the line moved in our favour = the real test.
Not logging lines we didn't bet."

    python _big.py            # scan -> alert only BIG legs (desktop + big_alerts.jsonl), then CLV-check every open alert
    python _big.py report     # the test: how often did PP's line move our way after an alert (and W/L once graded)

BIG = a PrizePicks STANDARD line where
  * the sharp CONSENSUS (Pinnacle props + FanDuel lines/alt ladders, moved to PP's number) gives our side >= 66%
    (PP 2-pick break-even is 57.7% -> 8+ pts of cushion), with >= 2 sharp sources, or one source >= 72%; AND
  * our own model agrees when we have one for that leg (role/own-rate calls today: same side, >= 55%); a model that
    DISAGREES kills the alert. No model -> the sharp consensus alone must be >= 70%.
CLV = after the alert, PP moves its line TOWARD our side (over: line goes UP; under: line goes DOWN) or pulls the line.
That is the proof we were early and right -- graded per alert, plus the actual result when the game is graded.
"""
import os, sys, re, json, glob, time, datetime, subprocess

CT = datetime.timezone(datetime.timedelta(hours=-5))
LOG = "big_alerts.jsonl"
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
SPORTS = {"NFL": (9, 889), "NHL": (8, 1456), "NBA": (7, 487), "WNBA": (3, 578), "MLB": (2, 246), "CFB": (15, 880)}


def toast(title, body):
    ps = ("Add-Type -AssemblyName System.Windows.Forms; $n=New-Object System.Windows.Forms.NotifyIcon; "
          "$n.Icon=[System.Drawing.SystemIcons]::Warning; $n.Visible=$true; "
          "$n.ShowBalloonTip(20000,'%s','%s',[System.Windows.Forms.ToolTipIcon]::Warning); Start-Sleep -Seconds 21; $n.Dispose()"
          % (title.replace("'", ""), body.replace("'", "")[:240]))
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps])
    except Exception:
        pass


def model_side(sport, player, stat):
    """today's/tomorrow's model call for this player+stat: (side, p) or None."""
    days = {datetime.datetime.now(CT).date().isoformat(), (datetime.datetime.now(CT).date() + datetime.timedelta(days=1)).isoformat()}
    best = None
    if os.path.exists("calls_log.jsonl"):
        for l in open("calls_log.jsonl", encoding="utf-8"):
            if player.split()[-1] not in l:
                continue
            r = json.loads(l)
            if r.get("sport") == sport and r.get("date") in days and norm(r.get("player")) == norm(player) and norm(r.get("stat")) == norm(stat):
                c = str(r.get("call", ""))
                if c.startswith(("TAKE", "LEAN")):
                    p = r.get("p_role") or r.get("p") or r.get("value")
                    best = ("over" if "OVER" in c else "under", p)
    if sport == "NFL" and os.path.exists("_nfl_screen_out.json"):
        for r in json.load(open("_nfl_screen_out.json", encoding="utf-8")):
            if norm(r["player"]) == norm(player) and norm(r["stat"]) in (norm(stat), norm(stat).replace("pass", "").replace("rec", "")):
                best = ("over" if r["side"] == "higher" else "under", r["shrunk"])
    return best


def scan():
    import _props as P, _mismatch as M
    seen = set()
    if os.path.exists(LOG):
        seen = {json.loads(l)["key"] for l in open(LOG, encoding="utf-8")}
    now = datetime.datetime.now(datetime.timezone.utc)
    alerts = []
    for sp, (pp_lg, pin_lg) in SPORTS.items():
        srcs = {}
        try:
            for (pl, st, ln), p in P.pinnacle_props(pin_lg).items():
                srcs.setdefault((pl, st), {}).setdefault("pinnacle", []).append((ln, p))
        except Exception as e:
            print(sp, "pinnacle:", e)
        if sp in ("NFL", "CFB"):
            try:
                import _fanduel
                for (pl, st, ln), p in _fanduel.props(sp.lower()).items():
                    srcs.setdefault((pl, st), {}).setdefault("fanduel", []).append((ln, p))
            except Exception as e:
                print(sp, "fanduel:", e)
        if not srcs:
            continue
        try:
            pp = [l for l in P.prizepicks(pp_lg, max_age=1200) if l.get("kind") == "standard"]
        except Exception as e:
            print(sp, "pp:", e); continue
        for l in pp:
            try:
                if datetime.datetime.fromisoformat(l["start"].replace("Z", "+00:00")) < now:
                    continue
            except Exception:
                pass
            st = M.STAT.get(norm(l["stat"]))
            S = srcs.get((norm(l["player"]), st)) if st else None
            if not S:
                continue
            ps = {}
            for name, rows in S.items():
                po = M.p_over_at(rows, l["line"], st)
                if po is not None:
                    ps[name] = po
            if not ps:
                continue
            po = sum(ps.values()) / len(ps)
            side, p = ("over", po) if po >= 0.5 else ("under", 1 - po)
            if p < 0.60:                                           # 10/7 user: VALUE tier -- sharp says >=60% at PP's number (b/e 57.7%)
                continue
            m = model_side(sp, l["player"], l["stat"])
            if not m or m[0] != side or (m[1] or 0) < 0.55:
                continue                                           # our model must AGREE (same side, >=55%) -- no model, no alert
            near = {}
            for name, rows_ in S.items():
                ln0, p0 = min(rows_, key=lambda r: abs(r[0] - l["line"]))
                p_side = p0 if side == "over" else 1 - p0
                amer = ("-%d" % round(100 * p_side / (1 - p_side))) if p_side >= 0.5 else ("+%d" % round(100 * (1 - p_side) / p_side))
                near[name] = (ln0, amer)
            key = "%s|%s|%s|%s|%s" % (sp, l["player"], l["stat"], l["line"], (l.get("start") or "")[:10])
            if key in seen:
                continue
            seen.add(key)
            a = dict(key=key, sport=sp, player=l["player"], team=l.get("team"), stat=l["stat"], line=l["line"], side=side, sharp=round(p, 3),
                     sources={k: round(v if side == "over" else 1 - v, 3) for k, v in ps.items()}, sharp_lines=near, model=m, start=l.get("start"),
                     alerted=datetime.datetime.now(CT).isoformat(timespec="minutes"), checks=[], clv=None, result=None)
            alerts.append(a)
        time.sleep(1)
    if alerts:
        with open(LOG, "a", encoding="utf-8") as f:
            for a in alerts:
                f.write(json.dumps(a, ensure_ascii=False) + "\n")
        def line_msg(a):
            nm_, (ln0, am) = next(iter(a["sharp_lines"].items()))
            return "%s %s %s %s on PP; %s has %s at %s -> ~%.0f%% at PP's number; model %s %.0f%%. Take it now." % (
                a["player"], a["side"].upper(), a["line"], a["stat"], nm_.title(), ln0, am, 100 * a["sharp"], a["model"][0], 100 * (a["model"][1] or 0))
        try:
            import _notify
            for a in alerts:
                _notify.send("VALUE", line_msg(a), "high")
        except Exception as e:
            print("notify:", e)
        toast("VALUE: %d PrizePicks leg%s beat the books" % (len(alerts), "s" if len(alerts) > 1 else ""), " | ".join(line_msg(a) for a in alerts[:2]))
        with open(os.path.join("daily_log", "value_alerts.txt"), "a", encoding="utf-8") as f:
            for a in alerts:
                f.write(datetime.datetime.now(CT).strftime("%m-%d %H:%M  ") + line_msg(a) + chr(10))
    for a in alerts:
        print("VALUE %-4s %-22s %-18s %-5s %-6s at PP %2.0f%%  books %s  model %s" % (a["sport"], a["player"][:22], a["stat"][:18], a["side"].upper(), a["line"],
              100 * a["sharp"], a["sharp_lines"], a["model"]))
    if not alerts:
        print("no VALUE legs right now (books + model must both clear)")


def clv():
    """compare each open alert's entry line with PP's newest line for that player/stat."""
    if not os.path.exists(LOG):
        return
    rows = [json.loads(l) for l in open(LOG, encoding="utf-8")]
    latest = {}
    for sp, (pp_lg, _) in SPORTS.items():
        fs = __import__("_arch").files(os.path.join("lines_archive", "*", "pp_%d_*.json" % pp_lg))
        fs = [f for f in fs if os.path.getsize(f) > 500]
        if not fs:
            continue
        try:
            d = __import__("_arch").load(fs[-1])
        except Exception:
            continue
        inc = {(x["type"], x["id"]): x for x in d.get("included", [])}
        for x in d.get("data", []):
            at = x["attributes"]
            if at.get("odds_type") != "standard":
                continue
            pl = inc.get(("new_player", x["relationships"]["new_player"]["data"]["id"]), {}).get("attributes", {})
            latest[(sp, norm(pl.get("name")), norm(at.get("stat_type")))] = float(at["line_score"])
    for a in rows:
        if a.get("clv") in ("WITH", "AGAINST", "PULLED") and a.get("final"):
            continue
        now_line = latest.get((a["sport"], norm(a["player"]), norm(a["stat"])))
        started = a.get("start") and datetime.datetime.fromisoformat(a["start"].replace("Z", "+00:00")) < datetime.datetime.now(datetime.timezone.utc)
        if now_line is None:
            a["clv"] = a.get("clv") or ("PULLED" if not started else a.get("clv"))
        else:
            d = now_line - a["line"]
            a["clv"] = "WITH" if (d > 0 and a["side"] == "over") or (d < 0 and a["side"] == "under") else ("AGAINST" if d != 0 else "FLAT")
            a["now_line"] = now_line
        if started:
            a["final"] = True
    with open(LOG, "w", encoding="utf-8") as f:
        for a in rows:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")


def report():
    rows = [json.loads(l) for l in open(LOG, encoding="utf-8")] if os.path.exists(LOG) else []
    import collections
    c = collections.Counter(a.get("clv") for a in rows)
    print("BIG alerts: %d | line moved WITH us %d, AGAINST %d, flat %d, pulled %d, open %d" % (len(rows), c["WITH"], c["AGAINST"], c["FLAT"], c["PULLED"], c[None]))
    for a in rows[-15:]:
        print("  %s %-4s %-22s %-5s %-6s -> now %-6s  %s" % (a["alerted"][5:16], a["sport"], a["player"][:22], a["side"].upper(), a["line"], a.get("now_line", "-"), a.get("clv")))


if __name__ == "__main__":
    if sys.argv[1:] == ["report"]:
        report()
    else:
        scan(); clv()
