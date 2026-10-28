"""ESPORTS H2H CARDS -- PAPER (10/26, user: "anything from NBA/NFL we can implement into esports?" + "wake and cash slips").

Built the night before from the live PrizePicks boards; the matches play overnight (Asia/EU); graded the next morning.

    python _es_h2h.py [YYYY-MM-DD]     # build -> es_h2h_paper.jsonl + cards/<date>__es_h2h.json
    python _es_h2h.py grade            # grade legs from the map history (run after the CS2/VAL/Dota pulls)

RULES (backtests 10/26, memory project_cs2_sports_rules):
  CS2 v4  (Maps 1+2 kills or headshots): the side where his own last-30 series hit the line 60%+ AND he hit it in 50%+ of 2+
          meetings with this opponent (NBA "role + h2h", NFL own-rate floor) = 147-97 (60.2%) on 2,757 graded legs, 57/58/66%
          by half-month.  VETO: overs where he hit it in < 4 of his last 10 = 54-82 (40%).
  VAL / DOTA h2h-under (Maps 1+2 kills): his h2h average vs this opponent is 3+ kills below his own last-30 median (and below
          the line) -> UNDER. Full map history: VAL 59.5% (n=4,728), Dota 59.4% (n=973). Archived PP lines too few to confirm.
  Slips: 2-picks (PP 3x, b/e 57.7%/leg), one leg per player and one per match, paired by start time. PAPER until forward > 57.7%.
"""
import sys, os, re, json, glob, datetime, collections, statistics as st, unicodedata

CT = datetime.timezone(datetime.timedelta(hours=-5))
LOG = "es_h2h_paper.jsonl"
LEAGUES = {"cs2": 265, "val": 159, "dota": 174}


def nm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\b(team|gaming|esports|esport|club|gg|academy)\b|[^a-z0-9]", "", s)


def pn(s):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower())


def same_team(raw, b):
    """raw = PP's team name ('Inner Circle'), b = nm() of the map source's name, which is sometimes initials ('ic', 10/27)."""
    a = nm(raw)
    words = [w for w in re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", str(raw or "")).encode("ascii", "ignore").decode().lower())
             if w not in ("team", "gaming", "esports", "esport", "club", "gg", "academy")]
    ini = "".join(w[0] for w in words) if len(words) > 1 else None
    return bool(a and b) and (a == b or b == ini or (len(a) > 3 and len(b) > 3 and (a[:4] in b or b[:4] in a)))


def history(game):
    """player key -> [dict(date, opp, k=[map kills...], h=[map hs...])] oldest first, one row per series."""
    H = collections.defaultdict(dict)
    if game == "cs2":
        for f in ("cs2_maps_old.jsonl", "cs2_maps.jsonl"):
            if not os.path.exists(f):
                continue
            for l in open(f, encoding="utf-8"):
                r = json.loads(l)
                if r.get("kills") is None:
                    continue
                s = H[str(r["player"])].setdefault((r["date"], r["match"]), dict(date=r["date"], opp=nm(r["opp"]), g={}))
                s["g"][r["map_no"]] = (r["kills"], r.get("hs"))
    elif game == "val":
        seen = set()
        for f in ("val_maps.jsonl", "val_maps2.jsonl"):
            if not os.path.exists(f):
                continue
            for l in open(f, encoding="utf-8"):
                r = json.loads(l)
                if (r["game_id"], r["pid"]) in seen or r.get("kills") is None:
                    continue
                seen.add((r["game_id"], r["pid"]))
                s = H[pn(r["name"])].setdefault(r["match"], dict(date=r["date"], opp=nm(r["opp"]), g={}))
                s["g"][int(r["game_id"])] = (r["kills"], None)
    elif game == "dota":
        for l in open("dota_matches.jsonl", encoding="utf-8"):
            r = json.loads(l)
            key = (r["date"], tuple(sorted((nm(r["team"]), nm(r["opp"])))))
            for n in {pn(r["name"].split(".", 1)[-1]), pn(r["name"])}:
                s = H[n].setdefault(key, dict(date=r["date"], opp=nm(r["opp"]), g={}))
                s["g"][r["match_id"]] = (r["kills"], None)
    out = {}
    for p, ss in H.items():
        L = []
        for s in ss.values():
            g = [s["g"][k] for k in sorted(s["g"])]
            L.append(dict(date=s["date"], opp=s["opp"], k=[x[0] for x in g], h=[x[1] for x in g]))
        out[p] = sorted(L, key=lambda x: x["date"])
    return out


def m12(s, kind):
    v = s["k"] if kind == "k" else s["h"]
    return v[0] + v[1] if len(v) >= 2 and v[0] is not None and v[1] is not None else None


def cs2_pids():
    ids = {}
    for f in ("cs2_paper.jsonl", "cs2_priced_all.jsonl"):
        if os.path.exists(f):
            for l in open(f, encoding="utf-8"):
                r = json.loads(l)
                if r.get("pid") is not None and r.get("player"):
                    ids[pn(r["player"])] = str(r["pid"])
    return ids


def board(game, day):
    import _ppcache
    d = _ppcache.projections(LEAGUES[game], 900)
    P = {i["id"]: i["attributes"] for i in d.get("included", []) if i["type"] == "new_player"}
    lo = datetime.datetime.fromisoformat(day + "T00:00:00-05:00"); hi = lo + datetime.timedelta(hours=30)
    now = datetime.datetime.now(datetime.timezone.utc)
    for x in d.get("data", []):
        a = x["attributes"]
        if a.get("odds_type") != "standard" or a["stat_type"] not in ("MAPS 1-2 Kills", "MAPS 1-2 Headshots"):
            continue
        t = datetime.datetime.fromisoformat(a["start_time"])
        if not (max(lo, now) <= t < hi):
            continue
        p = P.get(x["relationships"]["new_player"]["data"]["id"], {})
        if not p.get("name") or "+" in p["name"]:                 # 10/28: a nameless/combo entry matched pn("None") history
            continue
        yield dict(game=game, player=p.get("name"), team=p.get("team"), opp=re.sub(r"\s*MAPS?\s.*$", "", a.get("description") or ""),
                   match=a.get("game_id"), start=t.astimezone(datetime.timezone.utc).isoformat(), stat=a["stat_type"],
                   kind="hs" if "Headshots" in a["stat_type"] else "k", line=float(a["line_score"]))


def judge(g, H, key):
    hist = H.get(key) or []
    d = g["start"][:10]
    prior = [v for s in hist if s["date"] < d for v in [m12(s, g["kind"])] if v is not None]
    if len(prior) < 10:
        return None
    o = g["opp"]
    hh = [v for s in hist if s["date"] < d and same_team(o, s["opp"]) for v in [m12(s, g["kind"])] if v is not None]
    ln = g["line"]; L30, L10 = prior[-30:], prior[-10:]
    o30 = sum(v > ln for v in L30) / len(L30); u30 = sum(v < ln for v in L30) / len(L30)
    o10 = sum(v > ln for v in L10) / 10
    info = dict(o30=round(o30, 2), u30=round(u30, 2), o10=round(o10, 2), med30=st.median(L30), h2h=hh[-6:], nh=len(hh))
    if g["game"] == "cs2":
        if len(hh) >= 2:
            ho = sum(v > ln for v in hh) / len(hh); hu = sum(v < ln for v in hh) / len(hh)
            if o30 >= .6 and ho >= .5 and o10 >= .4:
                return dict(info, side="higher", rule="cs2 v4 own+h2h")
            if u30 >= .6 and hu >= .5:
                return dict(info, side="lower", rule="cs2 v4 own+h2h")
        return None
    if len(hh) >= 2 and st.mean(hh) <= st.median(L30) - 3 and st.mean(hh) < ln:
        return dict(info, side="lower", rule="%s h2h-under" % g["game"])
    return None


def build(day):
    old = {}
    if os.path.exists(LOG):
        for l in open(LOG, encoding="utf-8"):
            r = json.loads(l); old[r["key"]] = r
    ids = cs2_pids(); legs = []
    for game in LEAGUES:
        try:
            B = list(board(game, day))
        except Exception as e:
            print("%s board: %s" % (game, e)); continue
        if not B:
            print("%s: no Maps 1-2 lines on the board for %s" % (game.upper(), day)); continue
        H = history(game)
        for g in B:
            key = ids.get(pn(g["player"])) if game == "cs2" else pn(g["player"])
            j = judge(g, H, key) if key else None
            if j:
                g.update(j, hkey=key, day=day, key="%s|%s|%s|%s" % (game, g["player"], g["stat"], g["start"][:10]))
                legs.append(g)
    new = [g for g in legs if g["key"] not in old]
    with open(LOG, "a", encoding="utf-8") as f:
        for g in new:
            f.write(json.dumps(dict(g, logged=datetime.datetime.now(CT).isoformat(timespec="minutes"), result=None)) + "\n")
    # one leg per MATCH across the card (10/25 FUT-Liquid 0-5, 10/26 Brooks/Giannis on 2 slips each): strongest own rate wins
    best = {}
    for g in legs:
        s = g["o30"] if g["side"] == "higher" else g["u30"]
        if g["match"] not in best or s > best[g["match"]][0]:
            best[g["match"]] = (s, g)
    legs = sorted([old.get(g["key"], g) for _, g in best.values()], key=lambda g: g["start"])
    slips, used = [], set()
    for rule in sorted(set(g["rule"] for g in legs)):
        pool = [g for g in legs if g["rule"] == rule]
        while pool:
            a = pool.pop(0)
            if a["player"] in used:
                continue
            b = next((x for x in pool if x["match"] != a["match"] and x["player"] not in used and x["player"] != a["player"]), None)
            if not b:
                break
            pool.remove(b); used |= {a["player"], b["player"]}
            slips.append(dict(rule=rule, pay=3.0, legs=[x["key"] for x in (a, b)]))
    os.makedirs("cards", exist_ok=True)
    json.dump(dict(day=day, slips=slips), open(os.path.join("cards", "%s__es_h2h.json" % day), "w", encoding="utf-8"), indent=1)
    print("ESPORTS H2H CARDS (PAPER) %s: %d legs, %d slips" % (day, len(legs), len(slips)))
    for g in legs:
        t = datetime.datetime.fromisoformat(g["start"]).astimezone(CT).strftime("%a %I:%M%p")
        print("  %-17s %-14s %-6s %5s %-18s own L30 o%.0f%%/u%.0f%% med %s | h2h %s | %s v %s %s" % (
            g["rule"], g["player"], "OVER" if g["side"] == "higher" else "UNDER", g["line"], g["stat"], 100 * g["o30"], 100 * g["u30"],
            g["med30"], g["h2h"], g["team"], g["opp"], t))
    for i, s in enumerate(slips, 1):
        print("  slip %d (%s): %s" % (i, s["rule"], " + ".join(k.split("|")[1] for k in s["legs"])))


def grade():
    R = [json.loads(l) for l in open(LOG, encoding="utf-8")] if os.path.exists(LOG) else []
    now = datetime.datetime.now(datetime.timezone.utc); Hs = {}
    for r in R:
        if r.get("result") or datetime.datetime.fromisoformat(r["start"]) > now - datetime.timedelta(hours=2):
            continue
        H = Hs.setdefault(r["game"], history(r["game"]))
        d0 = datetime.date.fromisoformat(r["start"][:10]); o = r["opp"]
        ss = [s for s in H.get(r["hkey"], []) if abs((datetime.date.fromisoformat(s["date"]) - d0).days) <= 1 and same_team(o, s["opp"])]
        a = m12(ss[0], r["kind"]) if ss else None
        if a is None:
            continue
        r["actual"] = a
        r["result"] = "PUSH" if a == r["line"] else ("W" if (a > r["line"]) == (r["side"] == "higher") else "L")
    with open(LOG, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r) + "\n" for r in R)
    res = {r["key"]: r.get("result") for r in R}
    legs = collections.defaultdict(lambda: [0, 0]); sl = collections.defaultdict(lambda: [0, 0, 0.0])
    for r in R:
        if r.get("result") in ("W", "L"):
            legs[r["rule"]][r["result"] == "L"] += 1
    for fn in sorted(glob.glob(os.path.join("cards", "*__es_h2h.json"))):
        c = json.load(open(fn, encoding="utf-8"))
        for s in c["slips"]:
            rs = [res.get(k) for k in s["legs"]]
            if None in rs or "PUSH" in rs:
                s["result"] = "PENDING" if None in rs else "PUSH"; continue
            s["result"] = "W" if all(x == "W" for x in rs) else "L"
            v = sl[s["rule"]]; v[s["result"] == "L"] += 1; v[2] += s["pay"] - 1 if s["result"] == "W" else -1
        json.dump(c, open(fn, "w", encoding="utf-8"), indent=1)
    for rule in sorted(set(legs) | set(sl)):
        w, l = legs[rule]; sw, sl_, net = sl[rule]
        print("%-18s legs %d-%d (%s)   slips %d-%d  flat $1 %+.2f" % (rule, w, l, "%.0f%%" % (100 * w / (w + l)) if w + l else "-", sw, sl_, net))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["grade"]:
        grade()
    else:
        build(a[0] if a else datetime.datetime.now(CT).date().isoformat())
