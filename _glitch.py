"""GLITCH WATCH -- lines that look mispriced (2026-09-30). User: "see any more lines that could be too crazy, like Puka".
Puka Nacua's PrizePicks targets line sat at 6.5 against an 11-a-game norm and was pulled within hours.

    python _glitch.py               # rebuilds the boards first (python _site_players.py), then scans site/players.json
    python _glitch.py --no-refresh  # scan the last build

Two tells, ranked together:
  1. CROSS-APP GAP: the same stat posted at different numbers on Underdog and PrizePicks (>= 12% apart). One app is wrong.
  2. ROLE GAP: the line sits far from the player's current-role median (last 8 games on his current team / season):
     z = (median - line) / spread. |z| >= 1.25 flags it. Big z with a healthy, unchanged role = the app left a number stale.
Every flag shows injury status -- a low line on an injured player is usually the app pricing the injury (Puka was
questionable), so the flag is "check the news", not "bet".
"""
import sys, json, subprocess, statistics as st, re

norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())


def scan(D):
    out = []
    for sp, d in D.items():
        if not isinstance(d, dict) or "players" not in d:
            continue
        K = d.get("skeys") or []
        for P in d["players"].values():
            grp = d["groups"].get(P.get("pos")) or next(iter(d["groups"].values()))
            G = []
            for g in P["games"]:
                s = dict(zip(K, g["s"])) if isinstance(g["s"], list) else g["s"]
                G.append((g, s))
            # current role: this season, else the last 12 games
            cur = [x for x in G if x[0].get("cur")]
            if sp == "NFL":
                team_games = [x for x in G if x[0].get("y") in ("2025", "2026")]
                cur = cur if len(cur) >= 3 else team_games
            role = (cur or G)[-8:]
            if len(role) < 3:
                continue
            for sk, slot in P["lines"].items():
                if sk not in grp:
                    continue
                parts = grp[sk][2]
                vals = [sum((s.get(p) or 0) for p in parts) for g, s in role]
                med = st.median(vals)
                spread = max(st.pstdev(vals), 0.15 * max(med, 1), 0.5)
                ud, pp = slot.get("ud"), slot.get("pp")
                flags = []
                if ud and pp and max(ud["line"], pp["line"]) > 0:
                    gap = abs(ud["line"] - pp["line"]) / max(ud["line"], pp["line"])
                    if gap >= 0.12:
                        lo = "UD" if ud["line"] < pp["line"] else "PP"
                        flags.append(("CROSS-APP", gap * 4, "UD %s vs PP %s (%d%% apart) -> %s is the low number" % (ud["line"], pp["line"], round(100 * gap), lo)))
                for app, sl in (("UD", ud), ("PP", pp)):
                    if not sl:
                        continue
                    z = (med - sl["line"]) / spread
                    if abs(z) >= 1.25:
                        hit = sum((v > sl["line"]) if z > 0 else (v < sl["line"]) for v in vals) / len(vals)
                        flags.append(("ROLE", abs(z), "%s %s: recent median %s, %s in %d%% of last %d" % (
                            app, sl["line"], round(med, 1), "over" if z > 0 else "under", round(100 * hit), len(vals))))
                if flags:
                    score = max(f[1] for f in flags) + (1 if len(flags) > 1 else 0)
                    out.append(dict(score=round(score, 2), sport=sp, player=P["name"], team=P.get("team"), opp=P.get("opp"), stat=grp[sk][0],
                                    start=P.get("start"), flags=[f[2] for f in flags], kinds=sorted({f[0] for f in flags}),
                                    recent=vals, read=(slot.get("read") or {}).get("call")))
    out.sort(key=lambda r: -r["score"])
    return out


def injuries(rows):
    try:
        import _news
    except Exception:
        return
    sp_map = {"NFL": "nfl", "WNBA": "wnba", "MLB": "mlb", "NHL": "nhl", "NBA": "nba"}
    for r in rows:
        s = sp_map.get(r["sport"])
        if not s or not r["team"]:
            continue
        t = {"LA": "LAR", "WAS": "WSH"}.get(r["team"], r["team"]) if s == "nfl" else r["team"]
        try:
            for name, status, comment, pos in _news.team_rows(s, t):
                if norm(name) == norm(r["player"]):
                    r["injury"] = "%s: %s" % (status, (comment or "")[:110])
        except Exception:
            pass


if __name__ == "__main__":
    if "--no-refresh" not in sys.argv:
        subprocess.run(["python", "_site_players.py"], check=False)
    D = json.load(open("site/players.json", encoding="utf-8"))
    rows = scan(D)
    top = rows[:30]
    injuries(top)
    json.dump(rows, open("site/glitch.json", "w", encoding="utf-8"))
    for r in top:
        print("%5.2f %-6s %-24s %-4s vs %-5s %-20s %s" % (r["score"], r["sport"], r["player"][:24], r["team"], r["opp"], r["stat"][:20],
                                                       " | ".join(r["flags"])))
        print("        recent: %s%s" % (", ".join(str(int(v)) if v == int(v) else str(v) for v in r["recent"]),
                                     ("   ** " + r["injury"]) if r.get("injury") else ""))
