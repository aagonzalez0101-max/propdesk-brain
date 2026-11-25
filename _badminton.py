"""BADMINTON MODEL (11/18, user: "i want a badminton model if they play hella often here ... create a model pls and lmk if anything works").

PP posts badminton TOTAL POINTS (and 1st-game totals) overnight. Pinnacle lists badminton but had 0 matchups (11/18), so there is no sharp
price -- the model has to stand on its own:
  DATA   every BWF World Tour / World Champs bracket on Wikipedia (free; game scores in {{nTeamBracket-Tennis3}} templates), 2022+.
  RATING Elo per discipline (MS/WS/MD/WD/XD), player or PAIR keyed by linked names, K=32, as-of each event (no look-ahead).
  POINTS a match is 2 or 3 games to 21 (win by 2, cap 30). Total points = bimodal: ~70-82 in 2 games, ~105-120 in 3. So
         P(over L) = P(3 games) * P(3-game total > L) + P(2 games) * P(2-game total > L). P(3 games) and the per-game margin come from
         the Elo win probability, fitted on history (logistic in |p-.5|). Walk-forward: fitted on events before 2025, graded on 2025+.
    python _badminton.py scrape     # -> badminton_matches.json (cached per page)
    python _badminton.py test       # fit + walk-forward calibration + rule search at PP-style lines
    python _badminton.py today      # price today's PP badminton board (needs the PP league id)
"""
import sys, os, re, json, math, collections, itertools, statistics, datetime
import requests

H = {"User-Agent": "research-script/1.0 (personal stats project)"}
API = "https://en.wikipedia.org/w/api.php"
CACHE = "_badminton_wiki"
OUT = "badminton_matches.json"
DISC = {"men's singles": "MS", "women's singles": "WS", "men's doubles": "MD", "women's doubles": "WD", "mixed doubles": "XD"}


def wikitext(title):
    os.makedirs(CACHE, exist_ok=True)
    fn = os.path.join(CACHE, re.sub(r"[^A-Za-z0-9]+", "_", title)[:150] + ".txt")
    if os.path.exists(fn):
        return open(fn, encoding="utf-8").read()
    if os.environ.get("BADM_CACHE_ONLY"):
        return ""
    import time
    for wait in (0, 5, 20, 60):                       # Wikipedia sometimes answers non-JSON under load -> back off, never cache a failure
        time.sleep(wait + 0.3)
        try:
            r = requests.get(API, params={"action": "parse", "page": title, "prop": "wikitext", "format": "json", "formatversion": 2, "redirects": 1},
                             headers=H, timeout=40).json()
            break
        except Exception:
            r = None
    if r is None:
        return ""
    w = r.get("parse", {}).get("wikitext", "")
    open(fn, "w", encoding="utf-8").write(w)
    return w


def events(year):
    w = wikitext("%d BWF World Tour" % year)
    out = []
    for t in re.findall(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]", w):
        if t.startswith(str(year)) and "badminton" not in t.lower().split("(")[0] and "World Tour" not in t:
            out.append(t)
        elif t.startswith(str(year)) and ("Open" in t or "Masters" in t or "Finals" in t):
            out.append(t)
    for t in ("%d BWF World Championships" % year,):
        out.append(t)
    return sorted(set(out))


def names(cell):
    ls = re.findall(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", cell)
    ls = [re.sub(r"\s*\(badminton\)", "", x).strip() for x in ls if not x.startswith(("File:", "Image:"))]
    return tuple(sorted(ls))


def score(v):
    v = re.sub(r"[^0-9]", "", v or "")
    return int(v) if v else None


def parse(title, year):
    w = wikitext(title)
    if not w:
        return []
    # dates: "dates = 11-16 November" -> use the last day as the event date
    m = re.search(r"\|\s*dates\s*=\s*([^\n]+)", w)
    month = None
    if m:
        mm = re.findall(r"(January|February|March|April|May|June|July|August|September|October|November|December)", m.group(1))
        month = mm[-1] if mm else None
    day = "%d-%02d" % (year, (datetime.datetime.strptime(month, "%B").month if month else 6))
    out = []
    # split into discipline sections by headings
    parts = re.split(r"\n==+\s*([^=\n]+?)\s*==+\n", w)
    disc = None
    for i, chunk in enumerate(parts):
        if i % 2 == 1:
            h = chunk.lower().strip()
            for k, v in DISC.items():
                if h.startswith(k):
                    disc = v
            continue
        if disc is None:
            continue
        for br in re.findall(r"\{\{\d+TeamBracket[^\n]*Tennis3(.*?)\n\}\}", chunk, flags=re.S):
            F = dict(re.findall(r"\|[ \t]*(RD\d+-(?:team|score)\d+(?:-\d)?)[ \t]*=[ \t]*([^\n]*)", br))
            rd = sorted({int(k[2:k.index("-")]) for k in F})
            for r_ in rd:
                n = 1
                while "RD%d-team%d" % (r_, n) in F:
                    a, b = F.get("RD%d-team%d" % (r_, n), ""), F.get("RD%d-team%d" % (r_, n + 1), "")
                    ga = [score(F.get("RD%d-score%d-%d" % (r_, n, g))) for g in (1, 2, 3)]
                    gb = [score(F.get("RD%d-score%d-%d" % (r_, n + 1, g))) for g in (1, 2, 3)]
                    games = [(x, y) for x, y in zip(ga, gb) if x is not None and y is not None]
                    na, nb = names(a), names(b)
                    ok = na and nb and len(games) >= 2 and all(21 <= max(x, y) <= 30 and (abs(x - y) >= 2 or max(x, y) == 30) for x, y in games) and "retired" not in (a + b).lower() \
                        and "w/o" not in (a + b).lower() and "walkover" not in (a + b).lower()
                    if ok:
                        wa = sum(x > y for x, y in games); wb = sum(y > x for x, y in games)
                        if max(wa, wb) == 2:
                            out.append(dict(event=title, ym=day, disc=disc, rnd=r_, a=na, b=nb, games=games, a_won=wa == 2))
                    n += 2
    return out


def scrape():
    allm = []
    for y in [int(x) for x in os.environ.get("BADM_YEARS", "2022,2023,2024,2025,2026").split(",")]:
        ev = events(y)
        print(y, len(ev), "event pages", flush=True)
        for t in ev:
            try:
                ms = parse(t, y)
            except Exception as e:
                print("  skip", t, e); ms = []
            # some events keep each discipline on its own page
            if not ms:
                for k in DISC:
                    try:
                        sub = parse("%s – %s" % (t, k[0].upper() + k[1:]), y)
                        for x in sub:
                            x["disc"] = DISC[k]
                        ms += sub
                    except Exception:
                        pass
            if ms:
                print("  %-50s %d matches" % (t[:50], len(ms)), flush=True)
            allm += ms
    json.dump(allm, open(OUT, "w", encoding="utf-8"))
    print("saved %d matches -> %s" % (len(allm), OUT))


# ------------------------------------------------------------------ model
def canon(n):
    """one key per person: 'Kidambi Srikanth' == 'Srikanth Kidambi', 'Chou Tien-Chen' == 'Chou Tien-chen'"""
    import unicodedata
    n = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode().lower().replace("-", " ").replace(".", " ")
    n = ALIAS.get(n.strip(), n)
    return " ".join(sorted(n.split()))


ALIAS = {"angus ng ka long": "ng ka long", "ng ka long angus": "ng ka long", "ka long angus ng": "ng ka long",
         "moh zaki ubaidillah": "zaki ubaidillah", "rakshitha sree santhosh ramraj": "rakshitha ramraj"}   # same player listed two ways on Wikipedia


def elo_rows(M):
    R = collections.defaultdict(lambda: 1500.0); N = collections.Counter()
    M = sorted([dict(m, a=tuple(sorted(canon(x) for x in m["a"])), b=tuple(sorted(canon(x) for x in m["b"]))) for m in M],
               key=lambda m: (m["ym"], m["event"], m["rnd"]))
    rows = []
    for m in M:
        ka, kb = (m["disc"], m["a"]), (m["disc"], m["b"])
        pa = 1 / (1 + 10 ** ((R[kb] - R[ka]) / 400))
        tot = sum(x + y for x, y in m["games"]); three = len(m["games"]) == 3
        rows.append(dict(m, pa=pa, na=N[ka], nb=N[kb], tot=tot, three=three, g1=sum(m["games"][0])))
        s = 1.0 if m["a_won"] else 0.0
        R[ka] += 32 * (s - pa); R[kb] -= 32 * (s - pa); N[ka] += 1; N[kb] += 1
    return rows, R


def test():
    M = json.load(open(OUT, encoding="utf-8"))
    rows, _ = elo_rows(M)
    rows = [r for r in rows if r["na"] >= 5 and r["nb"] >= 5]            # both rated
    print("BADMINTON: %d rated matches (%s..%s)" % (len(rows), rows[0]["ym"], rows[-1]["ym"]))
    fav = [max(r["pa"], 1 - r["pa"]) for r in rows]
    print("  Elo favourite won %.1f%%  (mean fav p %.1f%%)" % (100 * statistics.mean([(r["pa"] > .5) == r["a_won"] for r in rows]), 100 * statistics.mean(fav)))
    print("\n  by discipline: matches, 3-game %, median total, median 2-game total")
    for d in ("MS", "WS", "MD", "WD", "XD"):
        X = [r for r in rows if r["disc"] == d]
        if X:
            print("   %s %5d  3g %4.1f%%  median %5.1f  2g median %5.1f" % (d, len(X), 100 * statistics.mean(r["three"] for r in X),
                  statistics.median(r["tot"] for r in X), statistics.median([r["tot"] for r in X if not r["three"]])))
    print("\n  favourite size -> 3-game rate and median total (does the gap shrink the total?)")
    for lo, hi in ((.5, .6), (.6, .7), (.7, .8), (.8, .9), (.9, 1.01)):
        X = [r for r in rows if lo <= max(r["pa"], 1 - r["pa"]) < hi]
        if X:
            print("   fav %.0f-%.0f%%  n=%5d  3g %4.1f%%  median total %5.1f  over 77.5 %4.1f%%" % (100 * lo, 100 * hi, len(X),
                  100 * statistics.mean(r["three"] for r in X), statistics.median(r["tot"] for r in X), 100 * statistics.mean(r["tot"] > 77.5 for r in X)))
    # walk-forward: for each discipline x favourite bucket, the 'fair line' = median total in the TRAIN years; grade over/under in TEST years.
    tr = [r for r in rows if r["ym"] < "2025"]; te = [r for r in rows if r["ym"] >= "2025"]
    print("\n  WALK-FORWARD: fair line = train-years median for (discipline, fav bucket); P(over) in 2025+ at that line")
    bk = lambda r: (r["disc"], min(4, int((max(r["pa"], 1 - r["pa"]) - .5) / .1)))
    med = {k: statistics.median([r["tot"] for r in tr if bk(r) == k]) for k in {bk(r) for r in tr}}
    for k in sorted(med):
        X = [r for r in te if bk(r) == k]
        if len(X) >= 30:
            L = math.floor(med[k]) + .5
            o = statistics.mean(r["tot"] > L for r in X)
            print("   %s fav %d0-%d0%%  line %5.1f  over %4.1f%%  under %4.1f%%  n=%d" % (k[0], 5 + k[1], 6 + k[1], L, 100 * o, 100 * (1 - o), len(X)))
    json.dump(med and {"%s|%d" % k: v for k, v in med.items()}, open("badminton_lines.json", "w"))


# ------------------------------------------------------------------ price a board (11/18 trial; PP league id pending -> lines typed in)
BOARD = [  # (disc, side A surnames, side B surnames, PP line, CT start)
    ("MS", ["Vitidsarn"], ["Ogawa"], 69.5, "6:40 AM"),
    ("MS", ["Yoo"], ["Johannesen"], 77.5, "4:00 AM"),
    ("MS", ["Koki Watanabe"], ["Srikanth"], 79.5, "6:40 AM"),
    ("MS", ["Ubaidillah"], ["Chou Tien-chen"], 78.5, "4:50 AM"),
    ("MS", ["Ng Ka Long"], ["Jason Teh"], 77.5, "4:00 AM"),
    ("MS", ["Teeraratsakul"], ["Gunawan"], 78.5, "2:20 AM"),
    ("MD", ["Man", "Tee"], ["Sukphun", "Teeraratsakul"], 78.5, "1:30 AM"),
    ("XD", ["Chan Yin", "Ng Tsz"], ["Hemming", "Leeuwen"], 78.5, "5:50 AM"),
]


def _match(q, name):
    """every token of the query is a prefix of a token of the name ('Man W' matches 'chong man wei')"""
    toks = name.split()
    if all(any(t.startswith(x) for t in toks) for x in canon(q).split()):
        return True
    import itertools                                  # 'Yu Fei Chen' == 'Chen Yufei', 'Ka Long Angus Ng' == 'Angus Ng Ka Long'
    qt = [t for t in canon(q).split() if t != "angus"]; nm = name.replace(" ", "").replace("angus", "")
    return len(qt) <= 4 and any("".join(pp) == nm for pp in itertools.permutations(qt))


def _loose(q, name):
    """11/24: PP 'Krishnamurthy Roy P' = Wikipedia 'Pruthvi Roy'; 'Pratheek.K S' = 'Sai Pratheek K.' -- one surname token + every initial"""
    toks = name.split(); qt = canon(q).split()
    longs = [x for x in qt if len(x) >= 3]; ini = [x for x in qt if len(x) < 3]
    return any(any(t == x or t.startswith(x) for t in toks) for x in longs) and all(any(t.startswith(i) for t in toks) for i in ini)


def _initial(q, name):
    qt = canon(q).split(); ini = [x for x in qt if len(x) < 3] or [x[0] for x in qt]
    return all(any(t.startswith(i) for t in name.split()) for i in ini)


def pair_match(sur, names):
    """strict first; doubles fallback: one partner matches by surname, the other at least by initial (PP 'Rethinasabapathi R' = Wiki 'Ruban Kumar')"""
    if len(sur) != len(names):
        return False
    if all(any(_match(s_, n) for n in names) for s_ in sur) and all(any(_match(s_, n) for s_ in sur) for n in names):
        return True
    import itertools
    for perm in itertools.permutations(names):
        ok = [_match(s_, n) or _loose(s_, n) for s_, n in zip(sur, perm)]
        if len(sur) == 2 and any(ok) and all(o or _initial(s_, n) for o, s_, n in zip(ok, sur, perm)):
            return True
        if len(sur) == 1 and ok[0]:
            return True
    return False


def find(R, disc, sur):
    hit = [(k, v) for k, v in R.items() if k[0] == disc and len(k[1]) == len(sur)
           and all(any(_match(s_, n) for n in k[1]) for s_ in sur)
           and all(any(_match(s_, n) for s_ in sur) for n in k[1])]
    if not hit:                                          # 11/24 fallback: PP and Wikipedia spell Indian/doubles names differently
        hit = [(k, v) for k, v in R.items() if k[0] == disc and pair_match(sur, k[1])]
    return hit


def pp_board():
    """PP league 285 (BAD): Total Points standard lines -> BOARD rows; discipline inferred later. Archives every line."""
    import _ppcache as C, zoneinfo
    CT = zoneinfo.ZoneInfo("America/Chicago")
    d = C.projections(285, 300)
    P = {i["id"]: i["attributes"] for i in d.get("included", []) if i["type"] == "new_player"}
    out = []
    with open("badminton_pp.jsonl", "a", encoding="utf-8") as f:
        for x in d["data"]:
            a = x["attributes"]; nm = P.get(x["relationships"]["new_player"]["data"]["id"], {}).get("name", "")
            f.write(json.dumps(dict(ts=datetime.datetime.now(CT).isoformat(timespec="minutes"), pid=x["id"], player=nm, opp=a.get("description"),
                                    stat=a["stat_type"], kind=a.get("odds_type"), sides=a.get("allowed_wager_types"), line=float(a["line_score"]), start=a["start_time"]), ensure_ascii=False) + "\n")
            if a["stat_type"] not in ("Total Points", "1st Game Total Points") or a.get("odds_type") != "standard":
                continue
            A = [z.strip() for z in nm.split("+")]; B = [z.strip() for z in (a.get("description") or "").split("+")]
            t = datetime.datetime.fromisoformat(a["start_time"]).astimezone(CT).strftime("%a %I:%M %p")
            out.append((None, A, B, float(a["line_score"]), t, a["stat_type"], nm, a["start_time"]))
    return out


def first_lines():
    """11/24: the FIRST standard number PP posted per (player, stat, start) -- laptop hourly log + cloud lines.db (league 285)"""
    F = {}
    if os.path.exists("badminton_pp.jsonl"):
        for l in open("badminton_pp.jsonl", encoding="utf-8"):
            if l.strip():
                r = json.loads(l)
                k = (r["player"], r["stat"], r["start"])
                if r.get("kind") == "standard" and (k not in F or r["ts"] < F[k][0]):
                    F[k] = (r["ts"], r["line"])
    out = {k: v[1] for k, v in F.items()}
    try:
        import sqlite3
        for p_, st, ln, start, fs in sqlite3.connect("lines.db").execute(
                "select player,stat,line,start,min(first_seen) from pp where league=285 and kind='standard' group by player,stat,start"):
            out[(p_, st, start)] = max(out.get((p_, st, start), ln), ln)   # opening number = the highest seen (PP only steps DOWN)
    except Exception:
        pass
    return out


def price():
    M = json.load(open(OUT, encoding="utf-8"))
    rows, R = elo_rows(M)
    N = collections.Counter()
    for r in rows:
        N[(r["disc"], r["a"])] += 1; N[(r["disc"], r["b"])] += 1
    board = BOARD if os.environ.get("BADM_TYPED") else pp_board()
    print("PP badminton board: %d standard Total Points lines" % len(board))
    print("%-34s %-6s %5s  %-28s %s" % ("match", "line", "fav%", "similar matches: over / under (n)", "call"))
    G1 = collections.defaultdict(list)                     # 11/24: game-1 totals by discipline (walk-forward: matchup adds nothing, 61.2% vs 61.1%)
    for r in rows:
        if r["ym"] >= "2024":
            G1[r["disc"]].append(r["g1"])
    FIRST = first_lines()
    for row in board:
        disc, A, B, L, t = row[:5]; stat = row[5] if len(row) > 5 else "Total Points"
        opened = FIRST.get((row[6], stat, row[7])) if len(row) > 7 else None
        if stat == "Total Points" and opened is not None:
            # 11/25 (164 graded PP totals) -- the line move only means something BY DISCIPLINE:
            #   SINGLES, line not dropped -> UNDER 20-9 (69%)   (the tailed $1,000 6-pick 11/24-25 = six of these, all hit)
            #   DOUBLES, line dropped     -> OVER 12-4 (75%)
            #   singles dropped 6-7, doubles unchanged 12-12 -> pass.  PAPER until the Monday review.
            single, dropped = len(A) == 1, L < opened
            tag = None
            if single and not dropped:
                tag = "SINGLES-UNDER (graded 20-9; take the OPENING number early -- lines only step down, an under wants the high one)"
            elif not single and dropped:
                tag = "DOUBLES DROP-OVER (opened %.1f; graded 12-4)" % opened
            if tag:
                print("%-34s %5.1f  %s -- paper | %s" % ((" + ".join(A) + " v " + " + ".join(B))[:34], L, tag, t))
        if disc is None:                                   # PP doesn't say the discipline: the one where both sides resolve uniquely
            opts = (("MS", "WS") if len(A) == 1 else ("MD", "WD", "XD"))
            ok = [d_ for d_ in opts if find(R, d_, A) and find(R, d_, B)]
            disc = ok[0] if len(ok) == 1 else opts[0]
        ha, hb = find(R, disc, A), find(R, disc, B)
        ha = [max(ha, key=lambda h: N[h[0]])] if ha else ha   # same person spelled two ways -> the record with the history
        hb = [max(hb, key=lambda h: N[h[0]])] if hb else hb
        if len(ha) != 1 or len(hb) != 1:
            print("%-34s %5.1f  ?     not found / ambiguous (%d, %d)" % (" + ".join(A) + " v " + " + ".join(B), L, len(ha), len(hb)), [h[0][1] for h in ha + hb][:4]); continue
        (ka, ra), (kb, rb) = ha[0], hb[0]
        if stat.startswith("1st Game"):
            o = statistics.mean(x > L for x in G1[disc])
            call = "paper-O" if o >= .577 else "paper-U" if 1 - o >= .577 else "pass"   # 11/24: these calls went 13-15 on graded PP lines -> paper only
            print("%-34s %5.1f  1ST GAME %s  over %4.1f%% / under %4.1f%% (n=%d, %s 2024+)  %-5s | %s" % (
                (" + ".join(A) + " v " + " + ".join(B))[:34], L, disc, 100 * o, 100 * (1 - o), len(G1[disc]), disc, call, t))
            continue
        pa = 1 / (1 + 10 ** ((rb - ra) / 400)); f = max(pa, 1 - pa)
        sim = [r for r in rows if r["disc"] == disc and abs(max(r["pa"], 1 - r["pa"]) - f) <= .05 and r["na"] >= 5 and r["nb"] >= 5]
        o = statistics.mean(r["tot"] > L for r in sim) if sim else float("nan")
        h2 = [r for r in rows if {r["a"], r["b"]} == {ka[1], kb[1]}]
        fa = [r["tot"] > L for r in rows if r["ym"] >= "2026" and ka[1] in (r["a"], r["b"]) and r["disc"] == disc]
        fb = [r["tot"] > L for r in rows if r["ym"] >= "2026" and kb[1] in (r["a"], r["b"]) and r["disc"] == disc]
        call = "OVER" if o >= .577 else "UNDER" if 1 - o >= .577 else "pass"
        if call != "pass" and fa and fb:                   # both sides' 2026 form must agree with the side, or it is not a leg
            agree = lambda X: (statistics.mean(X) >= .5) if call == "OVER" else (statistics.mean(X) <= .5)
            if not (agree(fa) and agree(fb)):
                call = "pass(form)"
        t = "%s | 2026 over: A %d/%d B %d/%d" % (t, sum(fa), len(fa), sum(fb), len(fb))
        print("%-34s %5.1f  %4.0f%%  over %4.1f%% / under %4.1f%% (n=%d)  %-5s | games A %d B %d | h2h totals %s | %s" % (
            (" + ".join(A) + " v " + " + ".join(B))[:34], L, 100 * f, 100 * o, 100 * (1 - o), len(sim), call, N[ka], N[kb],
            [r["tot"] for r in h2][-4:], t))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "test"
    if cmd == "scrape":
        scrape()
    elif cmd == "test":
        test()
    elif cmd == "price":
        price()
