"""Fast CS2 grader -- one pass over the recent bo3 window, then settle every pending pick.

    python _cs2_grade.py [rows_to_scan]

Why this exists alongside `_cs2_live.py grade`:

  * the built-in grader re-walks the match feed FOR EVERY PICK. With 400+ pending rows that is
    hours. This fetches the window once and indexes it.
  * bo3 IGNORES `sort=`; the feed is oldest-first, so the newest matches are at the END. The
    old code asked for offsets 0/50/100 and was reading matches from years ago.
  * bo3 nicknames carry clan tags -- "Witch |-jambo", "ex-Zero |Cjoffo". Matching on the raw
    nickname silently fails and the pick sits pending forever. Split on tag separators and
    compare the trailing token.
"""
import json, os, re, sys, time, collections
import requests

OUT = "cs2_paper.jsonl"
H = {"User-Agent": "Mozilla/5.0"}
API = "https://api.bo3.gg/api/v1"

norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())


def base_nick(nk):
    """'Witch |-jambo' -> 'jambo'. bo3 prefixes clan tags with | - _ or spaces."""
    parts = [p for p in re.split(r"[|\-_/\s]+", nk or "") if p]
    return parts[-1] if parts else (nk or "")


def window(n=1500):
    tot = requests.get(API + "/matches?page[limit]=1", headers=H, timeout=30).json()["total"]["count"]
    out = []
    for off in range(max(0, tot - n), tot, 100):
        try:
            b = requests.get(API + "/matches?page[offset]=%d&page[limit]=100&with=games,teams" % off,
                             headers=H, timeout=30).json()
        except Exception:
            continue
        out += (b.get("results") or [])
        time.sleep(0.12)
    return out


def stats_for(game_id, cache):
    if game_id in cache:
        return cache[game_id]
    try:
        st = requests.get(API + "/games/%d/players_stats" % game_id, headers=H, timeout=30).json()
        st = st if isinstance(st, list) else (st.get("results") or st.get("data") or [])
    except Exception:
        st = []
    cache[game_id] = st
    return st


def near(a, b, hours=36):
    """True when two ISO timestamps are within `hours`. Missing timestamps fail -- no date, no grade."""
    import datetime
    try:
        pa = datetime.datetime.fromisoformat(a.replace("Z", "+00:00"))
        pb = datetime.datetime.fromisoformat(b.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return False
    return abs((pa - pb).total_seconds()) <= hours * 3600


def main(n=1500, OUT=OUT):
    rows = [json.loads(l) for l in open(OUT, encoding="utf-8")]
    import datetime as _dt
    _recent = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=4)).isoformat()
    # 10/9: also re-open RECENT graded rows that lack round counts, so the post-mortem can separate overtime/long maps from model error
    pend = [r for r in rows if r.get("match") and r.get("line") is not None and
            (r.get("result") not in ("W", "L") or (r.get("rounds") is None and str(r.get("start", "")) >= _recent))]
    print("%d rows, %d pending" % (len(rows), len(pend)), flush=True)
    ms = window(n)
    print("indexed %d matches from bo3" % len(ms), flush=True)
    # 10/3 rewrite: candidates = series within 36h of the pick FIRST, then team similarity on bo3's real team names/slugs
    # (old: one slug-token bucket chosen before the date check -> 'Made in Brazil vs FURIA' never matched 'mibr-vs-furia',
    # and a pair's older series won over the right one). One side matching is enough: the player check below confirms it.
    GENERIC = {"esports", "esport", "team", "gaming", "club", "academy", "the", "and"}
    ALIAS = {"madeinbrazil": "mibr", "natusvincere": "navi", "natusvincerejunior": "navijunior", "ninjasinpyjamas": "nip",
             "teamliquid": "liquid", "faze": "faze", "virtuspro": "vp", "gamerlegion": "gl"}

    def toks(name):
        return {t for t in re.split(r"[^a-z0-9]+", (name or "").lower()) if len(t) > 2 and t not in GENERIC}

    def side_hit(pname, team):
        if not team:
            return False
        pn, tn, ts = norm(pname), norm(team.get("name")), norm(team.get("slug"))
        if not pn:
            return False
        if pn in (tn, ts) or ALIAS.get(pn) in (tn, ts) or (len(tn) > 2 and (tn in pn or pn in tn)):
            return True
        return bool(toks(pname) & (toks(team.get("name")) | toks((team.get("slug") or "").replace("-", " "))))

    import datetime as _dtm
    byday = collections.defaultdict(list)
    for m in ms:
        byday[(m.get("start_date") or "")[:10]].append(m)
    _prev = lambda d: (_dtm.date.fromisoformat(d) - _dtm.timedelta(days=1)).isoformat()
    _next = lambda d: (_dtm.date.fromisoformat(d) + _dtm.timedelta(days=1)).isoformat()
    cache = {}
    settled = 0
    for r in pend:
        title = r.get("match") or ""
        parts = [p.strip() for p in re.split(r"\s+vs\.?\s+", title, flags=re.I)]
        if len(parts) != 2 or not r.get("start"):
            continue
        best = []
        _d = r["start"][:10]
        for m in byday.get(_d, []) + byday.get(_prev(_d), []) + byday.get(_next(_d), []):
            if not near(m.get("start_date"), r.get("start")):
                continue
            t1, t2 = m.get("team1") or {}, m.get("team2") or {}
            sc = max(side_hit(parts[0], t1) + side_hit(parts[1], t2), side_hit(parts[0], t2) + side_hit(parts[1], t1))
            if sc >= 1:
                best.append((sc, m))
        import datetime as _dt
        _ps = _dt.datetime.fromisoformat(r["start"].replace("Z", "+00:00"))
        _gap = lambda m: abs((_dt.datetime.fromisoformat(m["start_date"].replace("Z", "+00:00")) - _ps).total_seconds())
        best = [m for sc, m in sorted(best, key=lambda x: (-x[0], _gap(x[1])))]      # same-day series: closest start wins
        if not best:
            continue
        maps = int(r.get("maps") or 2)
        for m in best:
            if m.get("status") != "finished":
                continue
            # SAME TEAMS PLAY MORE THAN ONCE. Without a date check the first finished series between the
            # pair was used -- djay was graded W at 7:40pm off an OLDER Marsborne-LAG series while the
            # 8pm one had not started (2026-09-29). Require the series to start within 36h of the pick.
            if not near(m.get("start_date"), r.get("start")):
                continue
            gs = sorted(m.get("games") or [], key=lambda x: x.get("number") or 0)
            if len(gs) < maps or any(g.get("status") != "finished" for g in gs[:maps]):
                continue
            agg = {}
            ok = True
            for gm in gs[:maps]:
                st = stats_for(gm["id"], cache)
                if len(st) < 10:
                    ok = False
                    break
                for p in st:
                    sp = p.get("steam_profile") or {}
                    # 10/3: steam display names are junk ('★ ⑳ nqzjre' for nqz) -> key on the PRO nickname first, steam name as backup
                    keys = {norm((sp.get("player") or {}).get("nickname")), norm((sp.get("player") or {}).get("slug")),
                            norm(base_nick(sp.get("nickname") or ""))} - {""}
                    # rounds played on this map = damage / ADR (bo3 player stats); >30 rounds = overtime
                    rnd = int(round((p.get("damage") or 0) / p["adr"])) if p.get("adr") else 0
                    for kk in keys:
                        e = agg.setdefault(kk, {"kills": 0, "hs": 0, "rounds": 0, "maps_r": []})
                        e["kills"] += p.get("kills") or 0
                        e["hs"] += p.get("headshots") or p.get("hs") or 0
                        e["rounds"] += rnd; e["maps_r"].append(rnd)
            if not ok:
                continue
            hit = agg.get(norm(r.get("player"))) or agg.get(norm(base_nick(r.get("player"))))
            if not hit:
                continue
            val = hit["hs"] if r.get("kind") == "hs" else hit["kills"]
            line = float(r["line"])
            lower = r.get("side") == "lower"
            r["actual"] = val
            r["result"] = "W" if ((val < line) if lower else (val > line)) else "L"
            r["rounds"] = hit.get("rounds") or None; r["maps_rounds"] = hit.get("maps_r")
            r["per_round"] = round(val / hit["rounds"], 3) if hit.get("rounds") else None
            settled += 1
            break
    with open(OUT, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    g = [r for r in rows if r.get("result") in ("W", "L")]
    w = sum(1 for r in g if r["result"] == "W")
    print("settled %d new | overall %d-%d of %d graded" % (settled, w, len(g) - w, len(g)))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1500, sys.argv[2] if len(sys.argv) > 2 else OUT)
