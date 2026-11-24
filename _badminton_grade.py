"""BADMINTON GRADER (11/24, user: "build the badminton grader").
Grades every archived PP badminton line (cloud lines.db league 285 = every hourly snapshot, + badminton_pp.jsonl for the opponent)
against Wikipedia game scores (same parser as _badminton.py; current-month event pages re-fetched fresh).
For each line it keeps the FIRST and LAST number PP posted -- the 11/24 finding is that PP steps lines DOWN overnight.
    python _badminton_grade.py              # grade -> badminton_graded.jsonl + summary
Needs a fresh lines.db (python _bundle.py lines).
"""
import os, re, json, sqlite3, collections, datetime
import _badminton as B

CT = __import__("zoneinfo").ZoneInfo("America/Chicago")
OUT = "badminton_graded.jsonl"


def results(months=("November", "December")):
    """fresh-parse every 2026 World Tour event page (current ones re-fetched, finished ones from cache)"""
    out = []
    for t in B.events(2026):
        fn = os.path.join(B.CACHE, re.sub(r"[^A-Za-z0-9]+", "_", t)[:150] + ".txt")
        w = B.wikitext(t)
        if any(m in (re.search(r"\|\s*dates\s*=\s*([^\n]+)", w) or [None, ""])[1] if w else False for m in months) and os.path.exists(fn):
            os.remove(fn)                                   # live event: the cached page is stale
        out += B.parse(t, 2026)
    return out


def lines():
    """(player, opp, stat, start) -> first/last standard line, from the cloud archive + the laptop log"""
    opp = {}
    for l in open("badminton_pp.jsonl", encoding="utf-8"):
        if l.strip():
            r = json.loads(l); opp[(r["player"], r["start"])] = r.get("opp") or ""
    G = collections.defaultdict(list)
    L = sqlite3.connect("lines.db")
    for p, st, ln, start, fs, ls in L.execute("select player,stat,line,start,first_seen,last_seen from pp where league=285 and kind='standard'"):
        G[(p, st, start)].append((fs or "", ls or "", ln))
    cloud = set(G)
    for l in open("badminton_pp.jsonl", encoding="utf-8"):     # laptop log only for lines the cloud never saw (timestamps aren't comparable)
        if l.strip():
            r = json.loads(l)
            k = (r["player"], r["stat"], r["start"])
            if r.get("kind") == "standard" and k not in cloud:
                G[k].append((r["ts"], r["ts"], r["line"]))
    out = []
    for (p, st, start), v in G.items():
        v.sort()
        out.append(dict(player=p, opp=opp.get((p, start), ""), stat=st, start=start, first=v[0][2], last=v[-1][2],
                        path=[x[2] for i, x in enumerate(v) if i == 0 or x[2] != v[i - 1][2]]))
    return out


def side_match(pp_side, names):
    toks = [z.strip() for z in pp_side.split("+") if z.strip()]
    return B.pair_match(toks, [B.canon(n) for n in names])


def grade():
    R = results(); LN = lines()
    done = []
    for x in LN:
        if not x["opp"]:
            continue
        ym = x["start"][:7]
        m = [r for r in R if r["ym"] == ym and ((side_match(x["player"], r["a"]) and side_match(x["opp"], r["b"])) or (side_match(x["player"], r["b"]) and side_match(x["opp"], r["a"])))]       # same month only (pairs meet at several events)
        if len(m) != 1:
            continue
        g = m[0]["games"]
        act = sum(a + b for a, b in g) if x["stat"] == "Total Points" else sum(g[0]) if x["stat"].startswith("1st Game") else None
        if act is None:
            continue
        x.update(disc=m[0]["disc"], event=m[0]["event"], games=g, actual=act,
                 over_first=act > x["first"], over_last=act > x["last"], push_last=act == x["last"])
        done.append(x)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in done))
    print("graded %d of %d archived lines (%d with an opponent)" % (len(done), len(LN), sum(1 for x in LN if x["opp"])))
    pct = lambda X: "%d-%d %.0f%%" % (sum(X), len(X) - sum(X), 100 * sum(X) / len(X)) if X else "-"
    for st in ("Total Points", "1st Game Total Points"):
        D = [r for r in done if r["stat"] == st and not r["push_last"]]
        mv = [r for r in D if r["last"] < r["first"]]; st_ = [r for r in D if r["last"] == r["first"]]
        print("\n%s  (n=%d)" % (st, len(D)))
        print("  OVER at last line : all %-12s | line DROPPED %-12s | unchanged %s" % (pct([r["over_last"] for r in D]), pct([r["over_last"] for r in mv]), pct([r["over_last"] for r in st_])))
        print("  OVER at first line: all %-12s | line DROPPED %-12s" % (pct([r["over_first"] for r in D]), pct([r["over_first"] for r in mv])))
        for d in ("MD", "XD", "WD", "MS", "WS"):
            X = [r["over_last"] for r in D if r["disc"] == d]
            if X:
                print("    %s over@last %s" % (d, pct(X)))
        if st.startswith("1st"):
            print("  1st game <=35.5 MD/XD OVER (the paper rule): %s" % pct([r["over_last"] for r in D if r["last"] <= 35.5 and r["disc"] in ("MD", "XD")]))
    return done


if __name__ == "__main__":
    grade()
