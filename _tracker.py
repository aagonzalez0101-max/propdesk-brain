"""ROAD TO $500 TRACKER in Discord (2026-10-10, user: "the tracker is easy to see -- put it in Discord, but no extra channel").
ONE message in #card that is EDITED in place (webhooks can edit their own messages): he pins it once, it never spams.
    python _tracker.py          # create it the first time, then update it (message id kept in _tracker_msg.json)
Called after every logged bet and after grading (_daily.py grade). Same numbers as _road.py.
"""
import json, datetime, requests, io, contextlib
try:
    from zoneinfo import ZoneInfo
    CT = ZoneInfo("America/Chicago")
except Exception:
    CT = datetime.timezone(datetime.timedelta(hours=-5))
with contextlib.redirect_stdout(io.StringIO()):
    from _mission import tag, L

MSG_F = "_tracker_msg.json"
GREEN, TRACK, BG, WHITE, SILVER = (30, 215, 96), (62, 62, 62), (24, 24, 24), (255, 255, 255), (179, 179, 179)


def _font(size, bold=False):
    from PIL import ImageFont
    for f in (("seguisb.ttf" if bold else "segoeui.ttf"), ("arialbd.ttf" if bold else "arial.ttf"),
              "/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf" % ("-Bold" if bold else "")):
        try:
            return ImageFont.truetype(f, size)
        except Exception:
            pass
    return ImageFont.load_default()


def render_bar(bal, start, goal):
    """10/10 user: the emoji bar looked bad at 0% -> a drawn Spotify-style progress bar (track, green fill, playhead, milestones)."""
    from PIL import Image, ImageDraw
    import io
    S = 2                                                     # draw at 2x, downsample = smooth edges
    W, H = 1000 * S, 210 * S
    im = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(im)
    x0, x1, y, th = 40 * S, 960 * S, 118 * S, 14 * S
    frac = max(0.0, min(1.0, (bal - start) / (goal - start)))
    d.text((x0, 22 * S), "$%.2f" % bal, font=_font(46 * S, True), fill=WHITE)
    right = "$%.0f to go" % max(goal - bal, 0)
    f2 = _font(30 * S, True); w2 = d.textlength(right, font=f2)
    d.text((x1 - w2, 34 * S), right, font=f2, fill=GREEN if frac > 0 else SILVER)
    d.rounded_rectangle((x0, y - th // 2, x1, y + th // 2), radius=th // 2, fill=TRACK)
    px = x0 + (x1 - x0) * frac
    if frac > 0:
        d.rounded_rectangle((x0, y - th // 2, max(px, x0 + th), y + th // 2), radius=th // 2, fill=GREEN)
    fs = _font(22 * S)
    for m in (100, 250, goal):                                # milestones on the way to the goal
        if start < m <= goal:
            mx = x0 + (x1 - x0) * (m - start) / (goal - start)
            hit = bal >= m
            d.ellipse((mx - 6 * S, y - 6 * S, mx + 6 * S, y + 6 * S), fill=GREEN if hit else (110, 110, 110))
            lab = "$%d" % m; lw = d.textlength(lab, font=fs)
            d.text((min(mx - lw / 2, x1 - lw), y + 22 * S), lab, font=fs, fill=WHITE if hit else SILVER)
    d.text((x0, y + 22 * S), "$%.0f" % start, font=fs, fill=SILVER)
    r = 15 * S                                                # the playhead knob
    d.ellipse((px - r, y - r, px + r, y + r), fill=WHITE)
    pct = "%.0f%%" % (100 * frac)
    d.text((x0, 172 * S), pct + " of the way", font=_font(22 * S), fill=SILVER)
    im = im.resize((W // S, H // S), Image.LANCZOS)
    b = io.BytesIO(); im.save(b, "PNG"); return b.getvalue()


RED, ORANGE, BLUE, PURPLE, CARD, TEAL = (243, 114, 127), (255, 164, 43), (83, 157, 245), (175, 125, 255), (36, 36, 36), (30, 185, 160)


def render_dashboard(bal, start, goal, day, w, l, stake, op, cash_risk, bonus):
    """10/10 user: "make it nice and colorful with the props under it" -- one drawn dashboard: stat tiles, gradient bar, open bets."""
    from PIL import Image, ImageDraw
    import io
    S = 2
    legs_n = sum(max(len(r.get("legs") or []), 1) for r in op)
    W = 1000
    H = 430 + (70 if op else 0) + sum(64 + 44 * max(len(r.get("legs") or []), 1) + 14 for r in op) + 20
    im = Image.new("RGB", (W * S, H * S), BG); d = ImageDraw.Draw(im)
    f = lambda z, b=False: _font(z * S, b)
    P = lambda *v: tuple(int(x * S) for x in v)
    # header
    d.text(P(40, 26), "ROAD TO $%d" % goal, font=f(20, True), fill=GREEN)
    d.text(P(40, 52), "$%.2f" % bal, font=f(52, True), fill=WHITE)
    right = "$%.0f to go" % max(goal - bal, 0); fr = f(30, True)
    d.text(((960 * S) - d.textlength(right, font=fr), 70 * S), right, font=fr, fill=GREEN if bal > start else SILVER)
    # gradient progress bar
    x0, x1, y, th = 40, 960, 160, 16
    frac = max(0.0, min(1.0, (bal - start) / (goal - start)))
    d.rounded_rectangle(P(x0, y - th / 2, x1, y + th / 2), radius=th // 2 * S, fill=TRACK)
    px = x0 + (x1 - x0) * frac
    if frac > 0:
        for i in range(int((px - x0) * S)):
            t = i / max((x1 - x0) * S, 1)
            col = tuple(int(GREEN[k] + (TEAL[k] - GREEN[k]) * t) for k in range(3))
            d.line([(x0 * S + i, (y - th / 2 + 2) * S), (x0 * S + i, (y + th / 2 - 2) * S)], fill=col)
    for m, col in ((100, BLUE), (250, PURPLE), (goal, ORANGE)):
        if start < m <= goal:
            mx = x0 + (x1 - x0) * (m - start) / (goal - start); hit = bal >= m
            d.ellipse(P(mx - 7, y - 7, mx + 7, y + 7), fill=col if hit else (95, 95, 95), outline=col, width=2 * S)
            lab = "$%d" % m; fs = f(20, True); lw = d.textlength(lab, font=fs) / S
            d.text(P(min(mx - lw / 2, x1 - lw), y + 20), lab, font=fs, fill=col)
    d.text(P(x0, y + 20), "$%.0f" % start, font=f(20), fill=SILVER)
    d.ellipse(P(px - 16, y - 16, px + 16, y + 16), fill=WHITE)
    # stat tiles
    net = bal - start
    tiles = [("DAY", "%d" % day, PURPLE), ("RECORD", "%d-%d" % (w, l), BLUE),
             ("NET", "%s$%.2f" % ("+" if net >= 0 else "-", abs(net)), GREEN if net >= 0 else RED), ("NEXT STAKE", "$%.2f" % stake, ORANGE)]
    tw, gap, ty = (920 - 3 * 16) / 4, 16, 232
    for i, (lab, val, col) in enumerate(tiles):
        tx = 40 + i * (tw + gap)
        d.rounded_rectangle(P(tx, ty, tx + tw, ty + 96), radius=14 * S, fill=CARD)
        d.rounded_rectangle(P(tx, ty, tx + tw, ty + 6), radius=3 * S, fill=col)
        d.text(P(tx + 18, ty + 18), lab, font=f(17, True), fill=SILVER)
        d.text(P(tx + 18, ty + 42), val, font=f(34, True), fill=col if lab in ("NET",) else WHITE)
    yy = 360
    if op:
        d.text(P(40, yy), "OPEN BETS (%d)" % len(op), font=f(22, True), fill=WHITE)
        sub = "$%.2f cash at risk%s  ·  cash on hand $%.2f" % (cash_risk, ("  ·  $%.2f bonus" % bonus) if bonus else "", bal - cash_risk)
        d.text(P(40, yy + 32), sub, font=f(18), fill=SILVER)
        yy += 74
        for r in op:
            legs = r.get("legs") or []
            hgt = 64 + 44 * max(len(legs), 1)
            isb = r.get("funding") == "bonus"
            d.rounded_rectangle(P(40, yy, 960, yy + hgt), radius=16 * S, fill=CARD)
            d.rounded_rectangle(P(40, yy, 48, yy + hgt), radius=4 * S, fill=ORANGE if isb else GREEN)
            head = "%s  ·  $%s → $%s" % (r.get("sport"), ("%g" % r["stake"]) if r.get("stake") else "?", ("%g" % r["to_return"]) if r.get("to_return") else "?")
            d.text(P(68, yy + 16), head, font=f(24, True), fill=WHITE)
            tags = (["OFF-BOOK"] if r.get("system_tag") == "OFF" else []) + (["BONUS"] if isb else []) +                    (["PROMO"] if any(g.get("kind") == "promo" for g in legs) else [])
            tx = 940
            for tg in reversed(tags):
                tf = f(16, True); tl = d.textlength(tg, font=tf) / S
                col = ORANGE if tg == "BONUS" else (125, 125, 125) if tg == "OFF-BOOK" else GREEN
                d.rounded_rectangle(P(tx - tl - 24, yy + 18, tx, yy + 46), radius=14 * S, fill=col)
                d.text(P(tx - tl - 12, yy + 21), tg, font=tf, fill=BG)
                tx -= tl + 36
            ly = yy + 60
            for g in legs:
                hi = g.get("side") == "over"
                pill = "HIGHER" if hi else "LOWER"; pf = f(16, True); pl = d.textlength(pill, font=pf) / S
                d.rounded_rectangle(P(68, ly, 68 + pl + 24, ly + 30), radius=15 * S, fill=GREEN if hi else RED)
                d.text(P(80, ly + 4), pill, font=pf, fill=BG)
                stat = (g.get("stat") or "").replace("MAPS 1-2 ", "").replace("Shots On Goal", "SOG").replace("Pass Yards", "pass yds")
                d.text(P(68 + pl + 40, ly + 1), g.get("player") or "", font=f(22, True), fill=WHITE)
                nx = 68 + pl + 40 + d.textlength(g.get("player") or "", font=f(22, True)) / S + 14
                d.text(P(nx, ly + 3), "%g %s" % (g.get("line") or 0, stat), font=f(20), fill=SILVER)
                ly += 44
            yy += hgt + 14
    H = int(yy + 8)                                           # trim to the content
    im = im.crop((0, 0, W * S, H * S)).resize((W, H), Image.LANCZOS)
    b = io.BytesIO(); im.save(b, "PNG"); return b.getvalue()


def build():
    R = json.load(open("road.json", encoding="utf-8"))
    S, G, start = R["start_date"], R["goal"], R["start_roll"] + sum(d["amount"] for d in R.get("deposits", []))   # 10/14: + DraftKings cash
    live = [r for r in L if r.get("kind") == "LIVE" and r.get("date", "") >= S and not r.get("exclude")]
    done = [r for r in live if r.get("result") in ("WIN", "LOSS", "PUSH", "VOID")]
    op = [r for r in live if r.get("result") in (None, "PENDING")]
    bal = start + sum(r.get("net") or 0 for r in done)
    cash_risk = sum(r.get("stake") or 0 for r in op if r.get("funding") != "bonus")
    bonus = sum(r.get("stake") or 0 for r in op if r.get("funding") == "bonus")
    frac = max(0.0, min(1.0, (bal - start) / (G - start)))
    k = int(frac * 12) + (1 if 0 < frac * 12 - int(frac * 12) else 0) if frac > 0 else 0   # any progress shows at least one green block
    bar = "🟩" * k + "⬛" * (12 - k)
    day = (datetime.datetime.now(CT).date() - datetime.date.fromisoformat(S)).days + 1
    w = sum(r["result"] == "WIN" for r in done); l = sum(r["result"] == "LOSS" for r in done)
    desc = ["**$%.2f** · day %d · %d-%d · %d open" % (bal, day, w, l, len(op)), ""]
    by = {}
    for r in done:
        by.setdefault(r["date"], []).append(r)
    if by:
        desc.append("**📅 By day**")
        run = start
        for d in sorted(by):
            n = sum(r.get("net") or 0 for r in by[d]); run += n
            desc.append("`%s`  %d-%d  %+.2f  → $%.2f" % (d[5:], sum(r["result"] == "WIN" for r in by[d]), sum(r["result"] == "LOSS" for r in by[d]), n, run))
        desc.append("")
    rows = []
    for t in ("SYSTEM", "PROMO", "OFF"):
        g = [r for r in done if tag(r) == t]
        if g:
            st = sum(r.get("stake") or 0 for r in g if r.get("funding") != "bonus"); n = sum(r.get("net") or 0 for r in g)
            rows.append("%s %d-%d %+.2f" % (t, sum(r["result"] == "WIN" for r in g), sum(r["result"] == "LOSS" for r in g), n))
    if rows:
        desc.append("**By type:** " + " · ".join(rows))
    return {"title": "🛣️ ROAD TO $%d" % G, "description": "\n".join(desc)[:4000], "color": 0x1ED760 if bal >= start else 0xF3727F,
            "image": {"url": "attachment://road.png"},
            "_png": render_dashboard(bal, start, G, day, w, l, 0.05 * (start + sum(r.get("net") or 0 for r in done if r["date"] < datetime.datetime.now(CT).date().isoformat())), op, cash_risk, bonus),
            "footer": {"text": "PropDesk · updated %s TX · pin this message" % datetime.datetime.now(CT).strftime("%a %m/%d %I:%M %p")}}


def main():
    c = json.load(open("notify.json", encoding="utf-8"))
    hook = c.get("tracker_webhook") or c.get("discord_webhook")      # 10/10: its own channel
    if not hook:
        print("no webhook"); return
    emb = build()
    png = emb.pop("_png")
    files = {"files[0]": ("road.png", png, "image/png")}
    try:
        mid = json.load(open(MSG_F))["id"]
    except Exception:
        mid = None
    if mid:
        r = requests.patch("%s/messages/%s" % (hook, mid), timeout=30, files=files,
                           data={"payload_json": json.dumps({"embeds": [emb], "attachments": [{"id": 0, "filename": "road.png"}]})})
        if r.status_code == 200:
            print("tracker updated"); return
        print("edit failed (%s %s) -- posting a new one" % (r.status_code, r.text[:150]))
    r = requests.post(hook + "?wait=true", timeout=30, files=files,
                      data={"payload_json": json.dumps({"username": "PropDesk", "embeds": [emb], "attachments": [{"id": 0, "filename": "road.png"}]})})
    json.dump({"id": r.json()["id"]}, open(MSG_F, "w"))
    print("tracker posted -- pin it in Discord")


if __name__ == "__main__":
    main()
