"""PROMO FINDER (2026-10-09). PROMO bets are +47.8% ROI since 9/29 (best category) but he only caught them by looking.
The PrizePicks feed marks them: attributes is_promo=True, discount_name (e.g. 'free_square'), discount_percentage (98),
flash_sale_line_score (the promo number, e.g. Dak 0.5 pass yds). Reads the newest raw snapshot per league (saved hourly by
_snap_lines.py -- no extra API calls), alerts on promos not seen before (desktop toast + promos.jsonl + daily_log/promos.txt), and
prices the promo leg with the sharp books when a price exists.

    python _promos.py          # new promos since last run (hourly in LineWatch)
    python _promos.py all      # every promo live right now
"""
import os, sys, json, glob, datetime, subprocess
import _arch

CT = datetime.timezone(datetime.timedelta(hours=-5))
LOG = "promos.jsonl"
LEAGUE = {2: "MLB", 3: "WNBA", 7: "NBA", 8: "NHL", 9: "NFL", 15: "CFB", 82: "SOCCER", 121: "LoL", 159: "VAL", 174: "Dota2", 265: "CS2",
          131: "GOLF", 237: "NBAP", 1: "PGA", 135: "KBO", 298: "NPB"}
now = datetime.datetime.now(datetime.timezone.utc)


def latest_snapshots():
    day = datetime.datetime.now(CT).date()
    best = {}
    for d in (day, day - datetime.timedelta(days=1)):
        for f in _arch.files(os.path.join("lines_archive", d.isoformat(), "pp_*_*.json")):
            lg = int(os.path.basename(f).split("_")[1])
            if lg not in best or f.replace(".gz", "") > best[lg].replace(".gz", ""):
                best[lg] = f
    return best


def promos():
    out = []
    for lg, f in latest_snapshots().items():
        try:
            d = _arch.load(f)
        except Exception:
            continue
        inc = {(x["type"], x["id"]): x.get("attributes", {}) for x in d.get("included", [])}
        for x in d.get("data", []):
            a = x.get("attributes", {})
            if not (a.get("is_promo") or a.get("discount_name") or a.get("flash_sale_line_score") is not None):
                continue
            try:
                if datetime.datetime.fromisoformat(a["start_time"]).astimezone(datetime.timezone.utc) < now:
                    continue
            except Exception:
                pass
            rel = ((x.get("relationships") or {}).get("new_player") or {}).get("data") or {}
            pl = inc.get(("new_player", rel.get("id")), {})
            out.append(dict(id=x["id"], league=LEAGUE.get(lg, lg), player=pl.get("name"), team=pl.get("team"), stat=a.get("stat_type"),
                            line=a.get("line_score"), promo_line=a.get("flash_sale_line_score"), kind=a.get("discount_name") or "promo",
                            pct=a.get("discount_percentage"), start=a.get("start_time"), opp=a.get("description")))
    return out


def taco_check(p):
    """10/14 user (taco traps): the player's own recent games vs the PROMO line (promos are overs). Returns a one-line verdict or ''."""
    import re, json as _j, urllib.request as _u
    g = lambda url: _j.loads(_u.urlopen(_u.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=25).read())
    ln, lg, st = p.get("promo_line"), str(p.get("league")), (p.get("stat") or "").lower()
    if ln is None:
        return ""
    vals = None
    try:
        if lg == "MLB" and "hitter fantasy" in st:
            pid = g("https://statsapi.mlb.com/api/v1/people/search?names=%s" % _u.quote(p["player"]))["people"][0]["id"]
            def fs(s_):
                single = s_["hits"] - s_["doubles"] - s_["triples"] - s_["homeRuns"]
                return 3 * single + 5 * s_["doubles"] + 8 * s_["triples"] + 10 * s_["homeRuns"] + 2 * (s_["baseOnBalls"] + s_["hitByPitch"] + s_["runs"] + s_["rbi"]) + 5 * s_["stolenBases"]
            sp = []
            for gt in ("R", "F,D,L,W"):
                d = g("https://statsapi.mlb.com/api/v1/people/%d/stats?stats=gameLog&season=%d&group=hitting&gameType=%s" % (pid, datetime.date.today().year, gt))
                sp += [x for x in (d.get("stats") or [{}])[0].get("splits", [])]
            sp.sort(key=lambda x: x["date"])
            vals = [fs(x["stat"]) for x in sp[-15:]]
        elif lg == "NHL":
            q = g("https://search.d3.nhle.com/api/v1/search/player?culture=en-us&limit=3&q=%s" % _u.quote(p["player"]))[0]["playerId"]
            L = g("https://api-web.nhle.com/v1/player/%s/game-log/20262027/2" % q).get("gameLog", [])
            if len(L) < 5:
                L += g("https://api-web.nhle.com/v1/player/%s/game-log/20252026/2" % q).get("gameLog", [])
            key = "saves" if "save" in st else "shots" if "shot" in st else "points" if "point" in st else "assists" if "assist" in st else None
            if key == "saves":
                vals = [(r.get("shotsAgainst") or 0) - (r.get("goalsAgainst") or 0) for r in L if r.get("gamesStarted")][:15]
            elif key:
                vals = [r.get(key) or 0 for r in L][:15]
        elif lg in ("NBA", "NBAP", "WNBA"):
            import _bball as BB
            a = BB.roster("wnba" if lg == "WNBA" else "nba").get(re.sub(r"[^a-z0-9]", "", p["player"].lower()))
            pp = BB.COMBO.get(re.sub(r"[^a-z0-9]", "", st))
            if a and pp:
                L = [x for x in BB.logs("wnba" if lg == "WNBA" else "nba", a[0]) if x["min"] > 0]
                vals = [sum(x[k] for k in pp) for x in L][-12:]
    except Exception as e:
        return "own-games check failed (%s)" % str(e)[:40]
    if not vals:
        return ""
    hit = sum(v > ln for v in vals); rate = hit / len(vals)
    flag = "strong" if rate >= 0.80 else "borderline" if rate >= 0.70 else "TRAP risk"
    return "his last %d: over %s in %d (%.0f%%) -- %s" % (len(vals), ln, hit, 100 * rate, flag)


def toast(title, body):
    ps = ("Add-Type -AssemblyName System.Windows.Forms; $n=New-Object System.Windows.Forms.NotifyIcon; $n.Icon=[System.Drawing.SystemIcons]::Information;"
          " $n.Visible=$true; $n.ShowBalloonTip(20000,'%s','%s',[System.Windows.Forms.ToolTipIcon]::Info); Start-Sleep -Seconds 21; $n.Dispose()"
          % (title.replace("'", ""), body.replace("'", "")[:240]))
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps])
    except Exception:
        pass


def main(show_all=False):
    seen = set()
    if os.path.exists(LOG):
        seen = {json.loads(l)["id"] for l in open(LOG, encoding="utf-8")}
    P = promos()
    new = [p for p in P if p["id"] not in seen]
    for p in (P if show_all else new):
        st = datetime.datetime.fromisoformat(p["start"]).astimezone(CT).strftime("%a %I:%M%p") if p.get("start") else "?"
        print("PROMO %-6s %-24s %-5s %-18s %s -> %s  (%s %s%%)  vs %s  %s" % (p["league"], (p["player"] or "")[:24], p["team"] or "", (p["stat"] or "")[:18],
              p["line"], p["promo_line"], p["kind"], p["pct"], p.get("opp"), st))
    if new:
        with open(LOG, "a", encoding="utf-8") as f:
            for p in new:
                f.write(json.dumps(dict(p, found=datetime.datetime.now(CT).isoformat(timespec="minutes")), ensure_ascii=False) + "\n")
        os.makedirs("daily_log", exist_ok=True)
        with open(os.path.join("daily_log", "promos.txt"), "a", encoding="utf-8") as f:
            for p in new:
                f.write("%s  %s %s %s %s -> %s (%s)\n" % (datetime.datetime.now(CT).strftime("%m-%d %H:%M"), p["league"], p["player"], p["stat"],
                                                          p["line"], p["promo_line"], p["kind"]))
        try:                                                    # 10/13: promo alerts in Discord too (cloud has no desktop toast)
            import _cardpost as _C
            NL = chr(10)
            _C.post_embed("🎁 NEW PROMO%s on PrizePicks" % ("S" if len(new) > 1 else ""), NL.join(
                "**%s** %s %s: ~~%s~~ → **%s** (%s) · %s" % (p["player"], p["league"], p["stat"], p["line"], p["promo_line"], p["kind"],
                datetime.datetime.fromisoformat(p["start"]).astimezone(CT).strftime("%a %I:%M %p TX") if p.get("start") else "")
                + ((NL + "   -> " + taco_check(p)) if taco_check(p) else "")
                for p in new) + NL + NL + "Tacos can be traps -- check his own games vs the PROMO line before locking.", 0xFF4FD8)
        except Exception as e:
            print("discord promo post:", e)
        try:
            import _notify
            for p in new:
                st = datetime.datetime.fromisoformat(p["start"]).astimezone(CT).strftime("%a %I:%M %p") if p.get("start") else ""
                _notify.send("PROMO", "%s %s %s: %s -> %s (%s) %s" % (p["league"], p["player"], p["stat"], p["line"], p["promo_line"], p["kind"], st), "high")
        except Exception as e:
            print("notify:", e)
        toast("PROMO on PrizePicks: %d new" % len(new), " | ".join("%s %s %s->%s" % (p["player"], p["stat"], p["line"], p["promo_line"]) for p in new[:3]))
    if not P:
        print("no promo lines on the PrizePicks board right now")
    elif not new and not show_all:
        print("%d promo line(s) live, none new" % len(P))


if __name__ == "__main__":
    main(show_all=sys.argv[1:] == ["all"])
