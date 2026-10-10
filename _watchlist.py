"""WATCH LIST for the cloud alerts (2026-10-10, user: "alerts only for legs we are considering, not everything -- it logs it anyways").
Players in OPEN bets + today's/tomorrow's card legs (direction TOP picks listed on the card + posted slips) -> watch.json, uploaded as an
asset on the propdesk-brain 'data' release. propdesk-cloud/run.py downloads it each run and only pings line moves/pulls for these.
    python _watchlist.py          # rebuild + upload (called after the card is built and after a bet is logged)
"""
import os, json, datetime
try:
    from zoneinfo import ZoneInfo
    CT = ZoneInfo("America/Chicago")
except Exception:
    CT = datetime.timezone(datetime.timedelta(hours=-5))


def build():
    today = datetime.datetime.now(CT).date().isoformat()
    names = set()
    for l in open("live_paper.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if r.get("kind") == "LIVE" and r.get("result") in (None, "PENDING"):
            names |= {g.get("player") for g in r.get("legs") or [] if g.get("player")}
    if os.path.exists("direction_paper.jsonl"):
        for l in open("direction_paper.jsonl", encoding="utf-8"):
            r = json.loads(l)
            if r.get("date", "") >= today and r.get("tier") == "TOP":
                names.add(r["player"])
    if os.path.exists("_slips_posted.jsonl"):
        for l in open("_slips_posted.jsonl", encoding="utf-8"):
            if l.strip():
                names |= {g.get("player") for g in json.loads(l).get("legs") or []}
    return sorted(n for n in names if n)


def upload(names):
    import _bundle as B
    body = json.dumps({"updated": datetime.datetime.now(CT).isoformat(timespec="minutes"), "players": names}).encode()
    rel = B.release()
    a = next((x for x in rel.get("assets", []) if x["name"] == "watch.json"), None)
    if a:
        B.api("https://api.github.com/repos/%s/releases/assets/%d" % (B.REPO, a["id"]), "DELETE")
    B.api(rel["upload_url"].split("{")[0] + "?name=watch.json", "POST", body, "application/json")


if __name__ == "__main__":
    n = build()
    upload(n)
    print("watch list: %d players uploaded" % len(n))
