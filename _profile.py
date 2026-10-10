"""PLAYER PROFILES -- our own scouting file on every player (2026-09-30, user: "learn each player and their own
tendencies... so whenever you gotta learn shit you just pull up their profile, it's our info").

    python _profile.py nhl "Evgeni Malkin"
    python _profile.py nhl "Darcy Kuemper"          # goalies get a saves profile
    python _profile.py soccer "Roman Burki"
    python _profile.py build                         # rebuild every profile -> profiles/<sport>/<id>.json

Sources (already downloaded): _nhl_hist_rows.json (NHL box scores 2024-25 -> now), _soccer_hist_rows.json (FotMob,
top 5 leagues + MLS). Splits use opponent STRENGTH tiers computed point-in-time-free (season averages) -- a profile
is a description of the player, not a backtest.
"""
import sys, os, json, re, math, collections, statistics as st, unicodedata

norm = lambda s: re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())
OUT = "profiles"


def pct(xs, t):
    return 100.0 * sum(x > t for x in xs) / len(xs) if xs else 0


def summary(xs):
    return dict(n=len(xs), avg=round(st.mean(xs), 2), med=float(st.median(xs)), sd=round(st.pstdev(xs), 2)) if xs else None


def tiers(values):
    """team -> 'high' / 'mid' / 'low' by thirds"""
    s = sorted(values.items(), key=lambda kv: kv[1])
    k = len(s) // 3
    return {t: ("low" if i < k else "high" if i >= len(s) - k else "mid") for i, (t, _) in enumerate(s)}


# ------------------------------------------------------------------ NHL
def nhl_build():
    R = json.load(open("_nhl_hist_rows.json"))
    # team strength per season: shots for / against per game
    tg = {}
    for r in R:
        tg.setdefault((r["season"], r["team"]), {})[r["gid"]] = (r["team_sog"], r["opp_sog"])
    sf = collections.defaultdict(dict); sa = collections.defaultdict(dict)
    for (season, team), g in tg.items():
        v = [x for x in g.values() if None not in x]
        if v:
            sf[season][team] = st.mean(x[0] for x in v); sa[season][team] = st.mean(x[1] for x in v)
    tier_sa = {s: tiers(v) for s, v in sa.items()}          # how many shots a team ALLOWS
    tier_sf = {s: tiers(v) for s, v in sf.items()}          # how many shots a team TAKES
    dates = collections.defaultdict(set)
    for r in R:
        dates[r["team"]].add(r["date"])
    import datetime
    def b2b(r):
        y = (datetime.date.fromisoformat(r["date"]) - datetime.timedelta(days=1)).isoformat()
        return y in dates[r["team"]]
    by = collections.defaultdict(list)
    for r in R:
        by[r["pid"]].append(r)
    os.makedirs(os.path.join(OUT, "nhl"), exist_ok=True)
    n = 0
    for pid, G in by.items():
        G.sort(key=lambda r: r["date"])
        goalie = G[0]["pos"] == "G"
        if goalie:
            G = [g for g in G if g.get("starter")]
            key, lines = "saves", [19.5, 21.5, 23.5, 25.5, 27.5, 29.5]
            if len(G) < 8:
                continue
            tier = lambda g: tier_sf[g["season"]].get(g["opp"])
        else:
            key, lines = "sog", [0.5, 1.5, 2.5, 3.5, 4.5]
            if len(G) < 15:
                continue
            tier = lambda g: tier_sa[g["season"]].get(g["opp"])
        vals = [g[key] for g in G if g.get(key) is not None]
        p = dict(pid=pid, name=G[-1]["name"], team=G[-1]["team"], pos=G[-1]["pos"], goalie=goalie, stat=key,
                 last_game=G[-1]["date"], all=summary(vals), last10=summary(vals[-10:]),
                 clears={str(l): round(pct(vals, l)) for l in lines},
                 home=summary([g[key] for g in G if g["home"]]), away=summary([g[key] for g in G if not g["home"]]),
                 b2b=summary([g[key] for g in G if b2b(g)]),
                 by_opp_tier={t: summary([g[key] for g in G if tier(g) == t]) for t in ("high", "mid", "low")},
                 h2h={o: [g[key] for g in G if g["opp"] == o][-6:] for o in sorted({g["opp"] for g in G})})
        if goalie:
            sv = [g["saves"] / g["shots_against"] for g in G if g.get("shots_against")]
            p["save_pct"] = round(sum(sv) / len(sv), 3) if sv else None
            p["pulled_rate"] = round(100 * sum(g["toi"] < 50 for g in G) / len(G))
            p["shots_against"] = summary([g["shots_against"] for g in G if g.get("shots_against") is not None])
        else:
            p["toi"] = summary([round(g["toi"], 1) for g in G])
            p["toi_last10"] = round(st.mean(g["toi"] for g in G[-10:]), 1)
            p["points_per_game"] = round(st.mean(g["points"] or 0 for g in G), 2)
            p["hits"] = summary([g["hits"] for g in G if g.get("hits") is not None])
            p["blocks"] = summary([g["blocks"] for g in G if g.get("blocks") is not None])
        json.dump(p, open(os.path.join(OUT, "nhl", "%s.json" % pid), "w"), indent=1)
        n += 1
    print("NHL profiles:", n)


# ------------------------------------------------------------------ SOCCER
def soccer_build():
    R = json.load(open("_soccer_hist_rows.json"))
    # opponent strength: passes allowed / shots conceded / SOT created, per league-season
    TM = {}
    for r in R:
        TM.setdefault((r["lg"], r["season"], r["team"]), {})[r["mid"]] = (r.get("o_passes"), r.get("o_shots"), r.get("t_sot"))
    pa, sc, sotf = collections.defaultdict(dict), collections.defaultdict(dict), collections.defaultdict(dict)
    for (lg, s, t), g in TM.items():
        v = [x for x in g.values() if None not in x]
        if len(v) >= 5:
            pa[(lg, s)][t] = st.mean(x[0] for x in v); sc[(lg, s)][t] = st.mean(x[1] for x in v); sotf[(lg, s)][t] = st.mean(x[2] for x in v)
    T = {"passes": {k: tiers(v) for k, v in pa.items()}, "shots": {k: tiers(v) for k, v in sc.items()},
         "sot": {k: tiers(v) for k, v in sc.items()}, "saves": {k: tiers(v) for k, v in sotf.items()}}
    by = collections.defaultdict(list)
    seen = set()
    for r in R:
        if (r["mid"], r["pid"]) in seen:
            continue
        seen.add((r["mid"], r["pid"])); by[r["pid"]].append(r)
    os.makedirs(os.path.join(OUT, "soccer"), exist_ok=True)
    n = 0
    for pid, G in by.items():
        G.sort(key=lambda r: r["date"])
        starts = [g for g in G if (g.get("mins") or 0) >= 60]
        if len(starts) < 8:
            continue
        gk = sum(g["gk"] for g in G) > len(G) / 2
        p = dict(pid=pid, name=G[-1]["name"], gk=gk, last_game=G[-1]["date"], leagues=sorted({g["lg"] for g in G}),
                 apps=len(G), starts=len(starts), start_rate=round(100 * len(starts) / len(G)),
                 avg_mins=round(st.mean(g["mins"] for g in G), 1),
                 subbed_before_60=round(100 * sum(45 <= (g["mins"] or 0) < 60 for g in G) / len(G)), markets={})
        for m in (["saves", "passes"] if gk else ["passes", "shots", "sot"]):
            vals = [g[m] for g in starts if g.get(m) is not None]
            if len(vals) < 8:
                continue
            lines = {"passes": None, "shots": [0.5, 1.5, 2.5, 3.5], "sot": [0.5, 1.5], "saves": [1.5, 2.5, 3.5, 4.5]}[m]
            if lines is None:
                a = st.mean(vals); lines = [math.floor(a) - 9.5, math.floor(a) - 4.5, math.floor(a) + 0.5, math.floor(a) + 5.5]
            tk = T[m]
            p["markets"][m] = dict(all=summary(vals), last10=summary(vals[-10:]), clears={str(l): round(pct(vals, l)) for l in lines},
                                   home=summary([g[m] for g in starts if g["home"] and g.get(m) is not None]),
                                   away=summary([g[m] for g in starts if not g["home"] and g.get(m) is not None]),
                                   by_opp_tier={t: summary([g[m] for g in starts if g.get(m) is not None and
                                                            tk.get((g["lg"], g["season"]), {}).get(g["opp"]) == t]) for t in ("high", "mid", "low")},
                                   all_apps_incl_subs=summary([g[m] for g in G if g.get(m) is not None]))
        json.dump(p, open(os.path.join(OUT, "soccer", "%s.json" % pid), "w"), indent=1)
        n += 1
    print("soccer profiles:", n)


# ------------------------------------------------------------------ lookup
def show(sport, name):
    d = os.path.join(OUT, sport)
    hits = []
    for fn in os.listdir(d):
        p = json.load(open(os.path.join(d, fn), encoding="utf-8"))
        pn = p["name"].replace(".", " ").split()
        qn = name.split()
        # NHL box scores store "E. Malkin": match first initial + last name too
        if norm(name) in norm(p["name"]) or norm(p["name"]) in norm(name) or                 (len(pn) >= 2 and len(qn) >= 2 and norm(pn[-1]) == norm(qn[-1]) and norm(pn[0])[:1] == norm(qn[0])[:1]):
            hits.append(p)
    if not hits:
        print("no profile for", name); return
    p = max(hits, key=lambda p: p.get("last_game", ""))
    f = lambda s: "-" if not s else "%.1f avg / %.0f med (sd %.1f, n=%d)" % (s["avg"], s["med"], s["sd"], s["n"])
    if sport == "nhl":
        print("\n%s  (%s, %s)  last game %s" % (p["name"], p["team"], "GOALIE" if p["goalie"] else p["pos"], p["last_game"]))
        print("  %-22s %s" % ("%s, all games" % p["stat"], f(p["all"])))
        print("  %-22s %s" % ("last 10", f(p["last10"])))
        print("  %-22s %s" % ("clears line", "  ".join("%s: %d%%" % kv for kv in p["clears"].items())))
        print("  %-22s home %s | away %s" % ("home / away", f(p["home"]), f(p["away"])))
        print("  %-22s %s" % ("back-to-backs", f(p["b2b"])))
        lbl = "vs high/mid/low SHOT-TAKING teams" if p["goalie"] else "vs teams allowing high/mid/low shots"
        print("  %s:" % lbl)
        for t in ("high", "mid", "low"):
            print("     %-5s %s" % (t, f(p["by_opp_tier"][t])))
        if p["goalie"]:
            print("  save %% %.3f | pulled in %d%% of starts | shots faced %s" % (p["save_pct"] or 0, p["pulled_rate"], f(p["shots_against"])))
        else:
            print("  ice time %s (last 10: %.1f) | points/game %.2f | hits %s | blocks %s" % (
                f(p["toi"]), p["toi_last10"], p["points_per_game"], f(p["hits"]), f(p["blocks"])))
        print("  head-to-head (last 6 each): " + "  ".join("%s %s" % (o, v) for o, v in p["h2h"].items() if v))
    else:
        print("\n%s  (%s)  last game %s  %s" % (p["name"], "GK" if p["gk"] else "outfield", p["last_game"], "/".join(p["leagues"])))
        print("  start rate %d%% | avg minutes %.1f | subbed off 45-59' in %d%% of apps" % (p["start_rate"], p["avg_mins"], p["subbed_before_60"]))
        for m, x in p["markets"].items():
            print("  %s (starts): %s | last 10: %s" % (m.upper(), f(x["all"]), f(x["last10"])))
            print("     clears: " + "  ".join("%s: %d%%" % kv for kv in x["clears"].items()))
            print("     home %s | away %s" % (f(x["home"]), f(x["away"])))
            print("     vs opponents %s high/mid/low: " % ("creating shots on target" if m == "saves" else "conceding") + " | ".join("%s %s" % (t, f(x["by_opp_tier"][t])) for t in ("high", "mid", "low")))
            print("     every appearance incl. subs: %s" % f(x["all_apps_incl_subs"]))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "build":
        nhl_build(); soccer_build()
    else:
        show(a[0], " ".join(a[1:]))
