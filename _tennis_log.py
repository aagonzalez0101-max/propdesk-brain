"""LOG EVERY PP TENNIS LINE (11/18, user: "its all tennis games, we have fantasy, games won, games played ... aces and break points ...
i want everything logged"). Every stat, every kind (standard / demon / goblin), which sides PP allows, opening line + every move.
One row per (projection id, line, kind) the first time it is seen, plus a new row whenever the line moves -> tennis_pp_all.jsonl.
Grading: games / sets / tiebreaks / fantasy (sans aces) come from set scores (_tennis_pp grade). Aces + break points need a serve-stat
source (ESPN has none, Sackmann's repo is gone) -- logged now so they can be graded the moment a source is found.
    python _tennis_log.py
"""
import json, os, datetime
import _ppcache as C

CT = __import__("zoneinfo").ZoneInfo("America/Chicago")
OUT = "tennis_pp_all.jsonl"


def main():
    seen = set()
    if os.path.exists(OUT):
        for l in open(OUT, encoding="utf-8"):
            if l.strip():
                r = json.loads(l); seen.add((r["pid"], r["line"], r["kind"]))
    d = C.projections(5, 300)
    P = {i["id"]: i["attributes"] for i in d.get("included", []) if i["type"] == "new_player"}
    now = datetime.datetime.now(CT).isoformat(timespec="minutes"); n = 0
    with open(OUT, "a", encoding="utf-8") as f:
        for x in d["data"]:
            a = x["attributes"]; k = (x["id"], float(a["line_score"]), a.get("odds_type"))
            if k in seen:
                continue
            p = P.get(x["relationships"]["new_player"]["data"]["id"], {})
            f.write(json.dumps(dict(ts=now, pid=x["id"], player=p.get("name"), opp=a.get("description"), league=p.get("league"),
                                    stat=a["stat_type"], line=k[1], kind=k[2], sides=a.get("allowed_wager_types"),
                                    start=a["start_time"], promo=a.get("is_promo")), ensure_ascii=False) + "\n")
            n += 1
    print("tennis log: %d new lines (board %d)" % (n, len(d["data"])))


if __name__ == "__main__":
    main()
