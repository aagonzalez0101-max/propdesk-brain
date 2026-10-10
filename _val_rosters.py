"""Fetch career agent tables for every player on a list of teams (default: the 16 Champions 2026 teams).

    python _val_rosters.py            # Champions 2026 rosters -> val_career.json
    python _val_rosters.py "Paper Rex" "LOUD"

Team pages are found through vlr.gg's team search; the roster is the player links on the team page
(active players come first). Careers already fetched in the last 7 days are skipped.
"""
import re, sys, json, time, datetime, urllib.request, urllib.parse
import _val_career as C

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
CHAMPIONS_2026 = ["100 Thieves", "LOUD", "NRG", "G2 Esports", "Karmine Corp", "Team Liquid", "FUT Esports",
                  "Team Vitality", "Global Esports", "Nongshim RedForce", "Paper Rex", "T1", "TYLOO",
                  "JD Gaming", "EDward Gaming", "Xi Lai Gaming"]
KNOWN = {"Team Liquid": "474"}


def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40).read().decode("utf-8", "replace")


def event_teams(event="2766/valorant-champions-2026"):
    h = get("https://www.vlr.gg/event/%s" % event)
    return list(dict.fromkeys(re.findall(r'href="/team/(\d+)/([\w-]+)"', h)))


def team_id(name):
    if name in KNOWN:
        return KNOWN[name]
    h = get("https://www.vlr.gg/search/?q=%s&type=teams" % urllib.parse.quote(name))
    ids = re.findall(r'href="/team/(\d+)/([\w-]+)"', h)
    want = re.sub(r"[^a-z0-9]", "", name.lower())
    for tid, slug in ids:
        if re.sub(r"[^a-z0-9]", "", slug) == want:
            return tid
    return ids[0][0] if ids else None


def roster(tid):
    h = get("https://www.vlr.gg/team/%s" % tid)
    # active roster block comes before the staff block; take the first 5-7 player links
    cut = h.lower().find("staff")
    seen = list(dict.fromkeys(re.findall(r'href="/player/(\d+)/([\w-]+)"', h[:cut if cut > 0 else len(h)])))
    return seen[:8]


def main(teams):
    if not teams:
        teams = [(tid, slug) for tid, slug in event_teams()]
    else:
        teams = [(team_id(t), t) for t in teams]
    db = C.load_db()
    today = datetime.date.today()
    for tid, t in teams:
        if not tid:
            print(t, "not found"); continue
        try:
            players = roster(tid)
        except Exception as e:
            print(t, "roster failed", e); continue
        got = []
        for pid, slug in players:
            e = db.get(pid)
            if e and (today - datetime.date.fromisoformat(e["fetched"])).days < 7:
                got.append(slug); continue
            try:
                db[pid] = C.fetch_career(pid)
                db[pid]["team"] = db[pid].get("team") or t
                got.append(slug)
            except Exception as ex:
                print("  ", slug, ex)
            time.sleep(0.6)
        json.dump(db, open(C.DB, "w", encoding="utf-8"))
        print("%-18s team %-5s players: %s" % (t, tid, ", ".join(got)), flush=True)
    print("career DB now", len(db), "players")


if __name__ == "__main__":
    main(sys.argv[1:])
