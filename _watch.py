"""LIVE-TICKET WATCHER -- re-checks every leg on an open ticket for late scratches and lineup news (2026-10-02).
Talbot was ruled out an hour before tip on 10/1 after we'd built slips around her; Kim was left out of ATL's lineup.

    python _watch.py          # print alerts for every pending LIVE leg (injury status, MLB lineup, ruled-out notes)
"""
import json, datetime, re
import _news

norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
SPORT_GUESS = {"Pts": "wnba", "Points": "wnba", "Reb": "wnba", "Saves": "nhl", "Hits": "mlb", "Passes": None, "Rec": "nfl", "Rush": "nfl",
               "Pass": "nfl", "Targets": "nfl"}


def sport_of(leg, ticket_sport):
    st = leg.get("stat", "")
    for k, v in SPORT_GUESS.items():
        if k.lower() in st.lower():
            return v
    return None


if __name__ == "__main__":
    alerts = 0
    for l in open("live_paper.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if r.get("kind") != "LIVE" or r.get("result") != "PENDING":
            continue
        for g in r.get("legs") or []:
            if not isinstance(g, dict) or not g.get("player"):
                continue
            sp = sport_of(g, r.get("sport", ""))
            if not sp:
                continue
            found = None
            for team_rows in _news.injuries(sp).values():
                for name, status, comment, pos in team_rows:
                    if norm(name) == norm(g["player"]):
                        found = (status, comment)
            msg = None
            if found and (found[0] or "").lower() not in ("active", ""):
                msg = "%s: %s" % (found[0], (found[1] or "")[:120])
            elif found and "ruled out" in (found[1] or "").lower():
                msg = "RULED OUT note: %s" % found[1][:120]
            if msg:
                alerts += 1
                print("ALERT  %-22s %-18s %s  (ticket: %s $%s)" % (g["player"], g.get("stat", "")[:18], msg, r.get("book"), r.get("stake")))
    print("%d alert(s) on open tickets" % alerts)
