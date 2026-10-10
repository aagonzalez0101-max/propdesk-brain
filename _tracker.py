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


def build():
    R = json.load(open("road.json", encoding="utf-8"))
    S, G, start = R["start_date"], R["goal"], R["start_roll"]
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
    desc = ["## $%.2f  ➜  $%d" % (bal, G),
            "Day **%d** · record **%d-%d** · net **%+.2f** · next stake **$%.2f**" % (day, w, l, bal - start, 0.05 * bal), ""]
    if op:
        desc.append("**⏳ Open (%d)** · $%.2f cash at risk%s · cash on hand **$%.2f**" % (len(op), cash_risk, (" + $%.2f bonus" % bonus) if bonus else "", bal - cash_risk))
        for r in op:
            desc.append("**%s · $%s → $%s%s**" % (r.get("sport"), ("%g" % r["stake"]) if r.get("stake") else "?",
                        ("%g" % r["to_return"]) if r.get("to_return") else "?", " · bonus" if r.get("funding") == "bonus" else ""))
            for g in r.get("legs") or []:                      # 10/10 user: one readable line per leg, no shorthand
                promo = " (promo)" if g.get("kind") == "promo" else ""
                desc.append("　%s %s %s %g %s%s" % ("🔺" if g.get("side") == "over" else "🔻", g.get("player"),
                            "HIGHER" if g.get("side") == "over" else "LOWER", g.get("line") or 0,
                            (g.get("stat") or "").replace("MAPS 1-2 ", "").replace("Shots On Goal", "SOG"), promo))
        desc.append("")
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
            "image": {"url": "attachment://road.png"}, "_png": render_bar(bal, start, G),
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
