"""PP LINE-MOVE WATCHER (2026-10-06, user: "Rodri was 102.5 passes yesterday, now way lower -- we really gotta catch these").

    python _linewatch.py [league ...]     # compare the two newest PP snapshots per league -> every big standard-line move

A big move means NEWS hit the line (benching, minutes limit, injury, role change). Two ways it pays:
  1. CATCH IT EARLY: run this every snapshot; a line that has NOT moved yet on one prop of a player whose other props
     just moved (or a teammate's) is the stale one -> bet it before it catches up.
  2. TEAMMATES: a starter's line collapsing (Rodri 102.5 -> 81.5) means his share goes to someone -> check teammates'
     lines that did not move.
Flags: >= 12% change (and >= 1.0 absolute), or any new/pulled line for a player who had one. Leagues default to the money set.
Output: console + site/linewatch.json.
"""
import sys, os, json, glob, re

norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
LEAGUES = {"82": "SOCCER", "9": "NFL", "8": "NHL", "7": "NBA", "237": "NBAP", "3": "WNBA", "2": "MLB", "121": "LoL", "265": "CS2",
           "159": "VAL", "174": "Dota2", "135": "KBO", "298": "NPB", "15": "CFB"}


def load(f):
    try:
        d = __import__("_arch").load(f)
    except Exception:
        return {}
    inc = {(x["type"], x["id"]): x for x in d.get("included", [])}
    out = {}
    for x in d.get("data", []):
        a = x["attributes"]
        if a.get("odds_type") != "standard":
            continue
        pl = inc.get(("new_player", x["relationships"]["new_player"]["data"]["id"]), {}).get("attributes", {})
        k = (pl.get("name"), a.get("stat_type"), a.get("description"))
        out[k] = dict(line=float(a["line_score"]), team=pl.get("team"), start=a.get("start_time"))
    return out


STATE_F = "_linewatch_state.json"
try:
    STATE = json.load(open(STATE_F, encoding="utf-8"))
except Exception:
    STATE = {}


def main(leagues):
    moves = []
    for lid in leagues:
        files = sorted(__import__("_arch").files(os.path.join("lines_archive", "*", "pp_%s_*.json" % lid)),
                       key=lambda f: (os.path.basename(os.path.dirname(f)), f.replace(".gz", "")))
        files = [f for f in files if os.path.getsize(f) > (120 if f.endswith(".gz") else 500)]
        if len(files) < 2:
            continue
        # 10/9: compare against the snapshot seen at the LAST run, not just the previous file -- Hall SOG was pulled between two
        # snapshots inside one hour and the newest-two comparison missed it
        prev = STATE.get(lid)
        base = prev if prev in files and prev != files[-1] else files[-2]
        STATE[lid] = files[-1]
        old, new = load(base), load(files[-1])
        files = [base, files[-1]]
        for k, n in new.items():
            o = old.get(k)
            if not o:
                continue
            d = n["line"] - o["line"]
            if abs(d) >= 1.0 and abs(d) / max(o["line"], 0.5) >= 0.12:
                moves.append(dict(league=LEAGUES.get(lid, lid), player=k[0], stat=k[1], vs=k[2], team=n["team"], old=o["line"], new=n["line"],
                                  pct=round(100 * d / max(o["line"], 0.5)), start=n["start"], frm=files[-2][-11:-5], to=files[-1][-11:-5]))
        for k, o in old.items():
            if k not in new and any(kk[0] == k[0] for kk in new):
                moves.append(dict(league=LEAGUES.get(lid, lid), player=k[0], stat=k[1], vs=k[2], team=o["team"], old=o["line"], new=None, pct=None,
                                  start=o["start"], frm=files[-2][-11:-5], to=files[-1][-11:-5]))
    moves.sort(key=lambda m: -(abs(m["pct"]) if m["pct"] is not None else 0))
    print("PP LINE MOVES (>=12%% and >=1.0, standard lines): %d" % len(moves))
    # 10/9: phone alert only for players he has money on or that are on today's card/paper picks; the rest -> feed count
    try:
        import _notify, datetime as _d
        mine = set()
        today = _d.datetime.now(_d.timezone(_d.timedelta(hours=-5))).date().isoformat()
        for fn_ in ("live_paper.jsonl",):
            for l_ in open(fn_, encoding="utf-8"):
                r_ = json.loads(l_)
                if r_.get("kind") == "LIVE" and r_.get("result") is None:
                    mine |= {(g_.get("player") or "").lower() for g_ in r_.get("legs") or []}
        if os.path.exists("direction_paper.jsonl"):
            for l_ in open("direction_paper.jsonl", encoding="utf-8"):
                r_ = json.loads(l_)
                if r_.get("date", "") >= today:
                    mine.add(r_["player"].lower())
        hot = [m for m in moves if (m["player"] or "").lower() in mine]
        for m in hot:
            # these are HIS legs (open bets / card picks) -> Discord #card too (_notify routes PULLED/MOVE there)
            _notify.send("PULLED" if m["new"] is None else "MOVE", "**%s** %s %s: %s -> %s%s" % (m["player"], m["league"], m["stat"], m["old"],
                         m["new"] if m["new"] is not None else "PULLED",
                         "  -- drop him from any slip you haven't locked" if m["new"] is None else "  -- re-check the call before locking"), "high")
        if moves and len(moves) > len(hot):
            with open(os.path.join("daily_log", "feed.txt"), "a", encoding="utf-8") as f_:
                f_.write("%s   (+%d other PP line moves/pulls this hour -- not on your bets/card)\n" % (
                    _d.datetime.now(_d.timezone(_d.timedelta(hours=-5))).strftime("%m-%d %I:%M %p"), len(moves) - len(hot)))
    except Exception as e:
        print("notify:", e)
    for m in moves[:60]:
        print("  %-6s %-22s %-4s %-22s %-14s %6s -> %-6s %s  (%s -> %s)" % (m["league"], (m["player"] or "")[:22], m["team"] or "", (m["stat"] or "")[:22],
              (m["vs"] or "")[:14], m["old"], m["new"] if m["new"] is not None else "PULLED", ("%+d%%" % m["pct"]) if m["pct"] is not None else "", m["frm"], m["to"]))
    json.dump(STATE, open(STATE_F, "w", encoding="utf-8"))
    os.makedirs("site", exist_ok=True)
    json.dump(moves, open(os.path.join("site", "linewatch.json"), "w", encoding="utf-8"), ensure_ascii=False)


if __name__ == "__main__":
    main(sys.argv[1:] or list(LEAGUES))
