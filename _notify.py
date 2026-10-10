"""PHONE ALERTS + FEED (2026-10-09, user: "auto-add updates on promos or line moves somewhere I can see in class, e.g. 4:01 someone
has a promo or someone's line changed").

Every alert goes to (1) daily_log/feed.txt (timestamped, CT) and (2) the phone, through whichever free channel is configured in
notify.json -- no accounts, no cards:
    {"ntfy_topic": "propdesk-...."}            # free ntfy app -> subscribe to this topic (no signup)
    {"discord_webhook": "https://discord.com/api/webhooks/..."}   # optional: a channel in his own server
Usage from any tool:  import _notify; _notify.send("PROMO", "Arch Manning pass yds 210.5 -> 149.5 (sharp 80%)", priority="high")
Test:  python _notify.py test
"""
import os, sys, json, datetime, requests

try:                                                    # 10/10 user: everything in Texas time (Central, DST-aware)
    from zoneinfo import ZoneInfo
    CT = ZoneInfo("America/Chicago")
except Exception:
    CT = datetime.timezone(datetime.timedelta(hours=-5))
CFG = "notify.json"
FEED = os.path.join("daily_log", "feed.txt")
ICON = {"PROMO": "🟢", "MOVE": "📈", "PULLED": "⛔", "VALUE": "💰", "CARD": "🧾", "RESULT": "✅", "TEST": "🔔"}


def cfg():
    try:
        return json.load(open(CFG, encoding="utf-8"))
    except Exception:
        return {}


def send(kind, text, priority="default"):
    now = datetime.datetime.now(CT)
    line = "%s %s %s: %s" % (now.strftime("%m-%d %I:%M %p"), ICON.get(kind, "•"), kind, text)
    os.makedirs("daily_log", exist_ok=True)
    with open(FEED, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    c = cfg()
    if c.get("ntfy_topic"):
        try:
            requests.post("https://ntfy.sh/%s" % c["ntfy_topic"], data=text.encode("utf-8"), timeout=15,
                          headers={"Title": ("%s %s" % (ICON.get(kind, ""), kind)).encode("utf-8"), "Priority": priority, "Tags": kind.lower()})
        except Exception as e:
            print("ntfy:", e)
    # 10/9: the CLOUD (propdesk-cloud) posts promos/moves/value; the laptop posts only the card + results to #card, as embed cards
    if c.get("discord_webhook") and kind in c.get("discord_kinds", ["CARD", "RESULT", "TEST", "PULLED", "MOVE"]):
        try:
            col = {"CARD": 0x1DB954, "RESULT": 0x1ED760, "TEST": 0x7C7C7C, "PULLED": 0xF3727F, "MOVE": 0xFFA42B}.get(kind, 0x7C7C7C)
            requests.post(c["discord_webhook"], timeout=15, json={"username": "PropDesk", "embeds": [{
                "title": "%s %s" % (ICON.get(kind, ""), {"CARD": "TODAY'S CARD", "RESULT": "RESULTS", "PULLED": "CARD LEG PULLED", "MOVE": "CARD LEG MOVED"}.get(kind, kind)),
                "description": text[:4000], "color": col, "footer": {"text": "PropDesk · " + now.strftime("%a %m/%d %I:%M %p TX")}}]})
        except Exception as e:
            print("discord:", e)
    print(line)


if __name__ == "__main__" and sys.argv[1:] == ["test"]:
    send("TEST", "PropDesk alerts are connected -- promos, line moves, value alerts and the morning card will land here.", "high")
