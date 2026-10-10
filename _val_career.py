"""Valorant CAREER agent database -- every player's lifetime stats on every agent (vlr.gg, free).

    python _val_career.py refresh [max_players]   # fetch/refresh career tables (stale > 7 days first)
    python _val_career.py show <player>           # print one player's career by agent
    python _val_career.py daily                   # what the scheduled task runs: new maps + refresh

Stored in val_career.json: {player_id: {name, team, fetched, agents: {agent: {maps, use_pct, rounds,
acs, kd, kpr, apr, k, d, a, fk, fd}}}}. Player ids come from val_maps.jsonl (the daily map pull records
them). Each daily run adds the newest results pages and refreshes the players who played most recently,
so the database grows every day and never re-downloads what it already has.
"""
import re, os, sys, json, time, datetime, html, urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
DB = "val_career.json"
STALE_DAYS = 7
num = lambda s: float(s) if re.fullmatch(r"-?\d+(\.\d+)?", s or "") else None


def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40).read().decode("utf-8", "replace")


def fetch_career(pid):
    h = get("https://www.vlr.gg/player/%s/?timespan=all" % pid)
    name = re.search(r'<h1[^>]*>(.*?)</h1>', h, re.S)
    team = re.search(r'class="wf-module-item mod-first[^"]*".*?<div style="font-weight: 500;[^>]*>\s*(.*?)\s*</div>', h, re.S)
    t = h.find('id="st-table"')
    tb = h[h.find("<tbody", t):h.find("</tbody>", t)]
    agents = {}
    for tr in re.findall(r"<tr>(.*?)</tr>", tb, re.S):
        ag = re.search(r'alt="(\w+)"', tr)
        c = [html.unescape(re.sub(r"<[^>]+>|\s+", " ", x)).strip() for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if not ag or len(c) < 16:
            continue
        use = re.match(r"\((\d+)\)\s*(\d+)%", c[1])
        agents[ag.group(1)] = dict(maps=int(use.group(1)) if use else None, use_pct=int(use.group(2)) if use else None,
                                   rounds=num(c[2]), rating=num(c[3]), acs=num(c[4]), kd=num(c[5]), adr=num(c[7]),
                                   kpr=num(c[8]), apr=num(c[9]), k=num(c[11]), d=num(c[12]), a=num(c[13]),
                                   fk=num(c[14]), fd=num(c[15]))
    return dict(name=re.sub(r"\s+", " ", html.unescape(name.group(1))).strip() if name else None,
                team=re.sub(r"\s+", " ", html.unescape(team.group(1))).strip() if team else None,
                fetched=datetime.date.today().isoformat(), agents=agents)


def load_db():
    return json.load(open(DB, encoding="utf-8")) if os.path.exists(DB) else {}


def player_ids():
    """player id -> (name, last date seen) from the map pull."""
    seen = {}
    if os.path.exists("val_maps.jsonl"):
        for l in open("val_maps.jsonl", encoding="utf-8"):
            r = json.loads(l)
            if r.get("pid"):
                if r["pid"] not in seen or r["date"] > seen[r["pid"]][1]:
                    seen[r["pid"]] = (r["name"], r["date"])
    return seen


def refresh(max_players=300):
    db = load_db()
    ids = player_ids()
    today = datetime.date.today()
    def stale(pid):
        e = db.get(pid)
        return (not e) or (today - datetime.date.fromisoformat(e["fetched"])).days >= STALE_DAYS
    todo = sorted((p for p in ids if stale(p)), key=lambda p: ids[p][1], reverse=True)[:max_players]
    n = 0
    for pid in todo:
        try:
            db[pid] = fetch_career(pid)
            n += 1
        except Exception as e:
            print("player", pid, e); time.sleep(3); continue
        time.sleep(0.6)
        if n % 25 == 0:
            json.dump(db, open(DB, "w", encoding="utf-8")); print("  %d careers saved" % n, flush=True)
    json.dump(db, open(DB, "w", encoding="utf-8"))
    print("refreshed %d players | database now %d players" % (n, len(db)))


def show(name):
    db = load_db()
    hits = [(pid, e) for pid, e in db.items() if e.get("name") and name.lower() in e["name"].lower()]
    if not hits:
        print("not in the career database yet:", name); return
    for pid, e in hits[:3]:
        tot = sum((a.get("maps") or 0) for a in e["agents"].values())
        print("\n%s (%s) -- %d career maps, fetched %s" % (e["name"], e.get("team"), tot, e["fetched"]))
        print("  %-10s %5s %5s %6s %5s %5s %5s %6s" % ("agent", "maps", "use", "rounds", "KPR", "ACS", "K:D", "FK:FD"))
        for ag, a in sorted(e["agents"].items(), key=lambda x: -(x[1].get("maps") or 0)):
            fkfd = "%d:%d" % (a["fk"] or 0, a["fd"] or 0)
            print("  %-10s %5s %4s%% %6s %5s %5s %5s %6s" % (ag, a.get("maps"), a.get("use_pct"), int(a["rounds"] or 0),
                                                           a["kpr"], a["acs"], a["kd"], fkfd))


def daily():
    import subprocess
    print("== daily Valorant update", datetime.datetime.now().isoformat(timespec="minutes"))
    subprocess.run([sys.executable, "_val_pull.py", "4", "0"], timeout=3600)     # newest ~200 matches
    refresh(150)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "daily"
    if cmd == "refresh":
        refresh(int(sys.argv[2]) if len(sys.argv) > 2 else 300)
    elif cmd == "show":
        show(" ".join(sys.argv[2:]))
    else:
        daily()
