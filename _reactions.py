"""LOCK / SKIP BY REACTION (2026-10-10, user: "instead of typing locked, just click a reaction like self roles -- lock, skip").
Every slip the card posts (recorded in _slips_posted.jsonl by _cardpost.py) gets three reactions added by the bot:
    🔒  lock at 5% of the roll (cash)      🎁  lock with bonus cash      ⏭  skip
When HE taps one, this logs the bet in live_paper.jsonl, edits the slip to show LOCKED / SKIPPED, and updates the pinned tracker.
Polled every minute by the cloud loop (no always-on connection needed, so a tap never "fails" -- it is picked up next minute).
    python _reactions.py           # one pass
Needs DISCORD_BOT_TOKEN (env) -- a bot in his server with View Channel / Read History / Add Reactions.
"""
import os, json, time, datetime, urllib.parse, requests
try:
    from zoneinfo import ZoneInfo
    CT = ZoneInfo("America/Chicago")
except Exception:
    CT = datetime.timezone(datetime.timedelta(hours=-5))

API = "https://discord.com/api/v10"
POSTED, STATE = "_slips_posted.jsonl", "_reactions_state.json"
LOCK, BONUS, SKIP = "🔒", "🎁", "⏭️"


def H():
    return {"Authorization": "Bot " + os.environ["DISCORD_BOT_TOKEN"], "User-Agent": "PropDesk (github, 1.0)"}


def call(method, path, **kw):
    for _ in range(3):
        r = requests.request(method, API + path, headers=H(), timeout=20, **kw)
        if r.status_code == 429:
            time.sleep(float(r.json().get("retry_after", 1)) + 0.2); continue
        return r
    return r


def users(ch, mid, emoji):
    r = call("GET", "/channels/%s/messages/%s/reactions/%s" % (ch, mid, urllib.parse.quote(emoji)))
    return [u for u in (r.json() if r.status_code == 200 else []) if not u.get("bot")]


def roll():
    try:
        import _cardpost
        return _cardpost.roll() or 40.0
    except Exception:
        return 40.0


def log_bet(rec, bonus):
    stake = 5.0 if bonus else round(0.05 * roll(), 2)          # bonus = the $5 flex refund style; cash = 5% of the morning roll
    mult = rec.get("mult") or 6.0
    if bonus:
        mult = max(mult - 1, 1.0)                                 # his app pays bonus slips one rung lower (6x -> 5x, 10/10)
    legs = rec["legs"]
    row = {"ts": datetime.datetime.now(CT).isoformat(), "date": min(l["start"] for l in legs)[:10], "kind": "LIVE", "mode": "LIVE",
           "sport": "+".join(sorted({l["sport"] for l in legs})), "book": "PrizePicks",
           "market": "%d-pick power %gx (card slip, locked by reaction)" % (len(legs), mult),
           "selection": " / ".join("%s %s%g %s" % (l["player"], "O" if l["side"] == "over" else "U", l["line"], l["stat"]) for l in legs),
           "stake": stake, "to_return": round(stake * mult, 2), "payout_mult": mult, "funding": "bonus" if bonus else "cash",
           "result": None, "net": None, "system_tag": "SYSTEM", "fair_prob": rec.get("ph"), "ev": round((rec.get("ph") or 0) * mult - 1, 2),
           "legs": [dict(player=l["player"], stat=l["stat"], line=l["line"], side=l["side"], game="%s vs %s" % (l.get("team"), l.get("opp")),
                         p=l.get("p")) for l in legs],
           "note": "locked by Discord reaction, msg %s" % rec["msg_id"]}
    with open("live_paper.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def mark(rec, text, color):
    """edit the slip's header card (webhook-owned message -> edit through the webhook)"""
    hook = json.load(open("notify.json", encoding="utf-8")).get("discord_webhook")
    m = call("GET", "/channels/%s/messages/%s" % (rec["channel_id"], rec["msg_id"]))
    if m.status_code != 200 or not hook:
        return
    E = m.json().get("embeds", [])
    if E:
        E[0]["description"] = "## %s\n" % text + (E[0].get("description") or "").split("\n", 1)[-1]
        E[0]["color"] = color
        requests.patch("%s/messages/%s" % (hook, rec["msg_id"]), json={"embeds": E}, timeout=20)


def main():
    if not os.environ.get("DISCORD_BOT_TOKEN") or not os.path.exists(POSTED):
        return
    st = json.load(open(STATE)) if os.path.exists(STATE) else {"done": [], "seeded": []}
    cut = (datetime.datetime.now(CT) - datetime.timedelta(days=2)).isoformat()
    changed = False
    for l in open(POSTED, encoding="utf-8"):
        rec = json.loads(l)
        mid, ch = rec["msg_id"], rec["channel_id"]
        if rec["posted"] < cut or mid in st["done"]:
            continue
        if mid not in st["seeded"]:                               # add the three buttons-as-reactions once
            for e in (LOCK, BONUS, SKIP):
                call("PUT", "/channels/%s/messages/%s/reactions/%s/@me" % (ch, mid, urllib.parse.quote(e))); time.sleep(0.4)
            st["seeded"].append(mid); changed = True
            continue
        started = min(x["start"] for x in rec["legs"]) < datetime.datetime.now(datetime.timezone.utc).isoformat()
        if users(ch, mid, SKIP):
            mark(rec, "⏭ SKIPPED", 0x7C7C7C); st["done"].append(mid); changed = True
        elif users(ch, mid, LOCK) or users(ch, mid, BONUS):
            bonus = bool(users(ch, mid, BONUS))
            row = log_bet(rec, bonus)
            mark(rec, "🔒 LOCKED · $%g%s → $%g" % (row["stake"], " bonus" if bonus else "", row["to_return"]), 0x1ED760)
            st["done"].append(mid); changed = True
            print("locked:", row["selection"][:90])
        elif started:
            st["done"].append(mid); changed = True                # untouched slip whose first game started -> stop watching
        time.sleep(0.3)
    if changed:
        json.dump(st, open(STATE, "w"))
        try:
            import subprocess, sys
            subprocess.run([sys.executable, "_watchlist.py"], timeout=120)     # newly locked legs -> cloud alerts watch them
        except Exception as e:
            print("watchlist:", e)
        try:
            import _tracker
            _tracker.main()
        except Exception as e:
            print("tracker:", e)


if __name__ == "__main__":
    main()
