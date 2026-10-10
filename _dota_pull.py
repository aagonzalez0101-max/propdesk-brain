"""Dota 2 pro match history from OpenDota (free, no key) -> dota_matches.jsonl

    python _dota_pull.py 800        # pull this many pro matches, newest first, resumable

One row per player per match: match id, date, league, duration, team, opponent, win, the
player's kills / deaths / assists, gold and xp per minute, hero, and his GPM RANK inside his own
team -- which is the practical stand-in for draft position (rank 1 = the farm priority core,
rank 5 = the hard support). He named position as a main filter and OpenDota does not label it
directly for pro games, but GPM order recovers it cleanly.

Rate limit on the free tier is about 2,000 calls a day and each match detail is one call, so a
few thousand matches takes a couple of unattended runs. Already-saved matches are skipped.
"""
import json, os, sys, time, requests

OUT = "dota_matches.jsonl"
API = "https://api.opendota.com/api"
H = {"User-Agent": "Mozilla/5.0"}


def done_ids():
    seen = set()
    if os.path.exists(OUT):
        for l in open(OUT, encoding="utf-8"):
            try:
                seen.add(json.loads(l)["match_id"])
            except Exception:
                pass
    return seen


def pro_match_ids(n, seen):
    """Walk backwards through the pro match feed collecting ids we do not have."""
    ids, less_than = [], None
    while len(ids) < n:
        u = API + "/proMatches" + ("?less_than_match_id=%d" % less_than if less_than else "")
        try:
            batch = requests.get(u, headers=H, timeout=30).json()
        except Exception as e:
            print("  feed error:", e); time.sleep(5); continue
        if not batch:
            break
        for m in batch:
            if m["match_id"] not in seen:
                ids.append(m["match_id"])
        less_than = batch[-1]["match_id"]
        time.sleep(1.2)
    return ids[:n]


def pull(n=800):
    seen = done_ids()
    print("already have %d matches; finding %d more" % (len(seen), n), flush=True)
    ids = pro_match_ids(n, seen)
    print("got %d match ids to fetch" % len(ids), flush=True)
    f = open(OUT, "a", encoding="utf-8")
    saved = 0
    for i, mid in enumerate(ids, 1):
        try:
            m = requests.get("%s/matches/%d" % (API, mid), headers=H, timeout=45).json()
        except Exception as e:
            print("  match %s: %s" % (mid, e)); time.sleep(3); continue
        ps = m.get("players") or []
        if len(ps) != 10 or not m.get("duration"):
            time.sleep(1.1); continue
        rad = m.get("radiant_name") or (m.get("radiant_team") or {}).get("name")
        dire = m.get("dire_name") or (m.get("dire_team") or {}).get("name")
        # GPM rank within each side = draft position stand-in
        for side in (True, False):
            mates = [p for p in ps if bool(p.get("isRadiant")) == side]
            mates.sort(key=lambda p: -(p.get("gold_per_min") or 0))
            for rank, p in enumerate(mates, 1):
                p["_pos"] = rank
        for p in ps:
            is_rad = bool(p.get("isRadiant"))
            f.write(json.dumps(dict(
                match_id=mid, date=time.strftime("%Y-%m-%d", time.gmtime(m.get("start_time", 0))),
                league=(m.get("league") or {}).get("name") or m.get("league_name"),
                duration=m["duration"], minutes=round(m["duration"] / 60.0, 1),
                team=rad if is_rad else dire, opp=dire if is_rad else rad,
                win=int(bool(m.get("radiant_win")) == is_rad),
                account_id=p.get("account_id"), name=p.get("name") or p.get("personaname"),
                hero_id=p.get("hero_id"), pos=p.get("_pos"),
                kills=p.get("kills"), deaths=p.get("deaths"), assists=p.get("assists"),
                gpm=p.get("gold_per_min"), xpm=p.get("xp_per_min"),
                last_hits=p.get("last_hits"), hero_damage=p.get("hero_damage"))) + "\n")
        saved += 1
        if saved % 25 == 0:
            f.flush(); print("  %d/%d matches saved" % (saved, len(ids)), flush=True)
        time.sleep(1.1)          # free tier is ~60 calls a minute
    f.close()
    print("done: %d new matches -> %s" % (saved, OUT))


if __name__ == "__main__":
    pull(int(sys.argv[1]) if len(sys.argv) > 1 else 800)
