"""PUSH (10/20, user: "push it out here if the laptop is on, if not I'm on Discord -- push them to my laptop and my Discord").
One call sends a pick or alert everywhere he looks:
    laptop   Windows pop-up (same toast as _promos.py) + daily_log/feed.txt
    Discord  the #card webhook in notify.json (rich embed)
    phone    the ntfy topic in notify.json

    python _push.py "TITLE" "body line 1\\nbody line 2" [color-hex]
    import _push; _push.push("TITLE", "body")
"""
import sys, os, json, datetime, urllib.request

CT = datetime.timezone(datetime.timedelta(hours=-5))


def push(title, body, color=0x1DB954):
    sent = []
    os.makedirs("daily_log", exist_ok=True)
    with open(os.path.join("daily_log", "feed.txt"), "a", encoding="utf-8") as f:
        f.write("%s %s | %s\n" % (datetime.datetime.now(CT).strftime("%m/%d %H:%M"), title, body.replace("\n", " / ")))
    sent.append("feed")
    if not os.environ.get("GITHUB_ACTIONS"):
        try:
            import _promos
            _promos.toast(title, body.replace("\n", " | ")); sent.append("laptop")
        except Exception as e:
            print("toast:", e)
    try:
        cfg = json.load(open("notify.json", encoding="utf-8"))
    except Exception:
        cfg = {}
    hook = cfg.get("discord_webhook")
    if hook:
        try:
            req = urllib.request.Request(hook, data=json.dumps({"username": "PropDesk", "embeds": [{"title": title[:250], "description": body[:4000], "color": color}]}).encode("utf-8"),
                                         headers={"Content-Type": "application/json", "User-Agent": "PropDesk"})
            urllib.request.urlopen(req, timeout=20); sent.append("discord")
        except Exception as e:
            print("discord:", e)
    if cfg.get("ntfy_topic"):
        try:
            urllib.request.urlopen(urllib.request.Request("https://ntfy.sh/%s" % cfg["ntfy_topic"], data=body.encode("utf-8"),
                                                          headers={"Title": title.encode("ascii", "ignore").decode()[:120] or "PropDesk"}), timeout=15)
            sent.append("phone")
        except Exception as e:
            print("ntfy:", e)
    print("pushed to:", ", ".join(sent))
    return sent


if __name__ == "__main__":
    a = sys.argv[1:]
    push(a[0], a[1].replace("\\n", "\n") if len(a) > 1 else "", int(a[2], 16) if len(a) > 2 else 0x1DB954)
