"""ESPORTS OVERNIGHT RUNNER (10/23, user: "run it overnight, all esports new plans, ready to push results by 9 AM, grade by 10-11 AM").

    python _esports_overnight.py            # runs until ~11:30 AM CT, then exits

Until 8:45 AM CT, every 2 hours: pull the CS2 / Valorant / Dota paper cards (new lines + model), rebuild the CS2 slips
(rule v2 line-gap + rule v3 underdog under). At ~8:45: final rebuild + Discord/phone push of the day's esports paper slips.
At ~10:30: grade everything (CS2 legs, Valorant, Dota, CS2 slips, esports calibration) and push the results.
All PAPER -- nothing here is a bet (esports = paper until a rule proves itself forward).
"""
import os, sys, json, glob, time, datetime, subprocess

CT = datetime.timezone(datetime.timedelta(hours=-5))
PY = sys.executable
ENV = dict(os.environ, PYTHONIOENCODING="utf-8")
LOG = os.path.join("daily_log", "esports_overnight.txt")


def now():
    return datetime.datetime.now(CT)


def run(args, to=900):
    t0 = time.time()
    try:
        p = subprocess.run([PY] + args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=to, env=ENV)
        out = (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        out = "TIMEOUT"
    with open(LOG, "a", encoding="utf-8") as f:
        f.write("\n===== %s  %s  (%ds)\n%s\n" % (now().strftime("%m/%d %H:%M"), " ".join(args), time.time() - t0, out[-4000:]))
    return out


def build():
    day = now().date().isoformat()
    run(["_cs2_live.py", "card"], 1200)
    run(["_cs2_card.py", day, "--force"], 300)
    run(["_val_live.py", "card"], 900)
    run(["_dota_proj.py"], 600)
    return day


def slips_text(day):
    lines = []
    for fn, label in ((os.path.join("cards", "%s__cs2u.json" % day), "CS2 v3 UNDERDOG UNDER (backtest 79-37)"),
                      (os.path.join("cards", "%s__cs2.json" % day), "CS2 v2 line-gap")):
        if not os.path.exists(fn):
            continue
        c = json.load(open(fn, encoding="utf-8"))
        lines.append("**%s** -- %d slips" % (label, len(c.get("slips", []))))
        for i, s in enumerate(c.get("slips", [])[:8], 1):
            legs = " / ".join("%s %s %s %s" % (g["player"], "UNDER" if g["side"] == "lower" else "OVER", g.get("pp_line") or g.get("line"), g["stat"]) for g in s["legs"])
            lines.append("  %d. %s" % (i, legs))
    return "\n".join(lines) or "no qualifying esports paper slips yet"


def push(title, body):
    try:
        import _push
        _push.push(title, body)
    except Exception as e:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("push failed: %s\n" % e)


def main():
    os.makedirs("daily_log", exist_ok=True)
    pushed_card = graded = False
    last_build = None
    while True:
        t = now()
        if t.hour >= 12:
            break
        if t.hour < 9 and (last_build is None or (t - last_build).total_seconds() >= 7200):
            build(); last_build = now()
        if not pushed_card and (t.hour, t.minute) >= (8, 45):
            day = build(); last_build = now()
            push("🎮 ESPORTS PAPER CARD %s (not bets)" % day, slips_text(day))
            pushed_card = True
        if not graded and (t.hour, t.minute) >= (10, 30):
            out = run(["_cs2_grade.py", "3000"], 1500)
            run(["_val_grade.py"], 900); run(["_dota_pull.py", "100"], 1200); run(["_dota_grade.py"], 300)
            card = run(["_cs2_card.py", "grade"], 300); run(["_calib_es.py"], 300)
            rec = [l for l in (out + "\n" + card).splitlines() if "overall" in l or "RULE live record" in l]
            push("🎮 ESPORTS GRADED %s" % now().strftime("%m/%d"), "\n".join(rec) or "graded (see daily_log/esports_overnight.txt)")
            graded = True
            break
        time.sleep(300)


if __name__ == "__main__":
    main()
