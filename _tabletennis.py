"""TABLE TENNIS MODEL (11/18, user: "build table tennis like badminton").

PP league 286 (TT) posts Total Points on WTT matches; Pinnacle lists table tennis but had 0 matchups -> the model stands alone, like badminton.
  DATA   WTT archived official results (free static JSON per event, brotli -> fetched with curl --compressed):
         .../websitearchivedresults/{eventId}/officialresult/officialresult.json  -- every match card with game scores + best-of-N.
  RATING Elo per gender (singles), as-of each match.
  POINTS best of 5 (or 7) games to 11, win by 2. Total = bimodal by number of games. P(over L) = share of SIMILAR past matches
         (same gender + best-of, favourite size +-5%) that went over L; a leg needs 57.7%+ AND both players' 2026 form on that side.
    python _tabletennis.py scrape [lo hi]   # event ids, default 2700..3500 -> tt_matches.json (cached per event)
    python _tabletennis.py test
    python _tabletennis.py price            # PP league 286 board, archives lines -> tt_pp.jsonl
"""
import sys, os, json, subprocess, collections, statistics, datetime, re
from concurrent.futures import ThreadPoolExecutor

URL = "https://wtt-web-frontdoor-cthahjeqhbh6aqe3.a01.azurefd.net/websitearchivedresults/%d/officialresult/officialresult.json"
CACHE = "_tt_wtt"
OUT = "tt_matches.json"


def get(eid):
    os.makedirs(CACHE, exist_ok=True)
    fn = os.path.join(CACHE, "%d.json" % eid)
    if os.path.exists(fn):
        try:
            return json.load(open(fn, encoding="utf-8"))
        except Exception:
            return []
    if os.environ.get("TT_CACHE_ONLY", "1") == "1":      # downloads happen in the shell (curl --compressed works there, not from Python)
        return []
    r = subprocess.run(["curl", "-s", "-m", "40", "--compressed", "-A", "Mozilla/5.0", URL % eid], capture_output=True)
    try:
        j = json.loads(r.stdout.decode("utf-8"))
    except Exception:
        j = None
    if isinstance(j, list):
        json.dump(j, open(fn, "w", encoding="utf-8"))
        return j
    if r.returncode == 0 and r.stdout[:1] in (b"<", b"{", b""):      # 404 page / not an event -> cache the miss
        json.dump([], open(fn, "w", encoding="utf-8"))
    return []


def canon(n):
    import unicodedata
    n = unicodedata.normalize("NFKD", n or "").encode("ascii", "ignore").decode().lower().replace("-", " ")
    return " ".join(sorted(n.split()))


def parse(j):
    out = []
    for x in j or []:
        mc = x.get("match_card") or {}
        sub = (x.get("subEventType") or mc.get("subEventName") or "")
        if "Singles" not in sub or len(mc.get("competitiors") or []) != 2:
            continue
        g = [tuple(int(v) for v in s.split("-")) for s in (mc.get("resultsGameScores") or mc.get("gameScores") or "").split(",") if s and s != "0-0"]
        bo = (mc.get("matchConfig") or {}).get("bestOfXGames")
        if not g or not bo:
            continue
        a, b = mc["competitiors"]
        wa = sum(p > q for p, q in g); wb = sum(q > p for p, q in g)
        if max(wa, wb) != bo // 2 + 1 or any(a.get("irm") or b.get("irm") for _ in [0]):
            continue
        dt = (mc.get("matchDateTime") or {}).get("startDateUTC") or ""
        try:
            d = datetime.datetime.strptime(dt, "%m/%d/%Y %H:%M:%S").date().isoformat()
        except Exception:
            d = (x.get("startDateLocal") or "")[:10]
        out.append(dict(eid=x.get("eventId"), date=d, sex="M" if sub.lower().startswith("men") else "W", bo=bo,
                        a=canon(a["competitiorName"]), b=canon(b["competitiorName"]), an=a["competitiorName"], bn=b["competitiorName"],
                        games=g, a_won=wa > wb))
    return out


def scrape(lo=2700, hi=3500):
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(get, range(lo, hi)))
    M = []
    for j in res:
        M += parse(j)
    M.sort(key=lambda m: m["date"])
    json.dump(M, open(OUT, "w", encoding="utf-8"))
    print("events with singles: %d   matches: %d  (%s..%s)" % (sum(1 for j in res if parse(j)), len(M), M[0]["date"] if M else "-", M[-1]["date"] if M else "-"))


def elo_rows(M):
    R = collections.defaultdict(lambda: 1500.0); N = collections.Counter(); rows = []
    for m in sorted(M, key=lambda m: m["date"]):
        ka, kb = (m["sex"], m["a"]), (m["sex"], m["b"])
        pa = 1 / (1 + 10 ** ((R[kb] - R[ka]) / 400))
        rows.append(dict(m, pa=pa, na=N[ka], nb=N[kb], tot=sum(p + q for p, q in m["games"]), ng=len(m["games"])))
        s = 1.0 if m["a_won"] else 0.0
        R[ka] += 32 * (s - pa); R[kb] -= 32 * (s - pa); N[ka] += 1; N[kb] += 1
    return rows, R


def test():
    rows, _ = elo_rows(json.load(open(OUT, encoding="utf-8")))
    rows = [r for r in rows if r["na"] >= 5 and r["nb"] >= 5]
    print("TT: %d rated singles matches (%s..%s); Elo fav won %.1f%%" % (len(rows), rows[0]["date"], rows[-1]["date"],
          100 * statistics.mean((r["pa"] > .5) == r["a_won"] for r in rows)))
    for bo in (5, 7):
        X = [r for r in rows if r["bo"] == bo]
        if not X:
            continue
        print("\n best of %d: n=%d  median total %.0f  games: %s" % (bo, len(X), statistics.median(r["tot"] for r in X),
              dict(sorted(collections.Counter(r["ng"] for r in X).items()))))
        for lo, hi in ((.5, .6), (.6, .7), (.7, .8), (.8, .9), (.9, 1.01)):
            Y = [r for r in X if lo <= max(r["pa"], 1 - r["pa"]) < hi]
            if len(Y) >= 20:
                print("   fav %2.0f-%3.0f%% n=%4d  median %3.0f  over 72.5 %4.1f%%  over 75.5 %4.1f%%  sweep %4.1f%%" % (100 * lo, 100 * hi, len(Y),
                      statistics.median(r["tot"] for r in Y), 100 * statistics.mean(r["tot"] > 72.5 for r in Y),
                      100 * statistics.mean(r["tot"] > 75.5 for r in Y), 100 * statistics.mean(r["ng"] == bo // 2 + 1 for r in Y)))


def find(R, sex, name):
    q = canon(name).split()
    return [(k, v) for k, v in R.items() if k[0] == sex and all(any(t.startswith(x) for t in k[1].split()) for x in q)
            and len(k[1].split()) <= len(q) + 1]


def price():
    import _ppcache as C, zoneinfo
    CT = zoneinfo.ZoneInfo("America/Chicago")
    rows, R = elo_rows(json.load(open(OUT, encoding="utf-8")))
    d = C.projections(286, 300)
    P = {i["id"]: i["attributes"] for i in d.get("included", []) if i["type"] == "new_player"}
    print("PP table tennis: %d lines" % len(d["data"]))
    with open("tt_pp.jsonl", "a", encoding="utf-8") as f:
        for x in d["data"]:
            a = x["attributes"]; nm = P.get(x["relationships"]["new_player"]["data"]["id"], {}).get("name", ""); op = a.get("description") or ""
            f.write(json.dumps(dict(ts=datetime.datetime.now(CT).isoformat(timespec="minutes"), pid=x["id"], player=nm, opp=op, stat=a["stat_type"],
                                    kind=a.get("odds_type"), sides=a.get("allowed_wager_types"), line=float(a["line_score"]), start=a["start_time"]), ensure_ascii=False) + "\n")
            if a["stat_type"] != "Total Points" or a.get("odds_type") != "standard":
                continue
            L = float(a["line_score"]); t = datetime.datetime.fromisoformat(a["start_time"]).astimezone(CT).strftime("%a %I:%M %p")
            sex = next((s for s in ("M", "W") if len(find(R, s, nm)) == 1 and len(find(R, s, op)) == 1), None)
            if not sex:
                print("  %-22s v %-22s %5.1f  ? not found (%s)" % (nm, op, L, t)); continue
            (ka, ra), (kb, rb) = find(R, sex, nm)[0], find(R, sex, op)[0]
            pa = 1 / (1 + 10 ** ((rb - ra) / 400)); fv = max(pa, 1 - pa)
            bo = 5                                           # PP lines in the 70s = best of 5 (best of 7 totals run ~90+)
            sim = [r for r in rows if r["sex"] == sex and r["bo"] == bo and abs(max(r["pa"], 1 - r["pa"]) - fv) <= .05 and r["na"] >= 5 and r["nb"] >= 5]
            o = statistics.mean(r["tot"] > L for r in sim) if sim else float("nan")
            fa = [r["tot"] > L for r in rows if r["date"] >= "2026" and r["bo"] == bo and ka[1] in (r["a"], r["b"])]
            fb = [r["tot"] > L for r in rows if r["date"] >= "2026" and r["bo"] == bo and kb[1] in (r["a"], r["b"])]
            call = "OVER" if o >= .577 else "UNDER" if 1 - o >= .577 else "pass"
            if call != "pass" and fa and fb and not all((statistics.mean(X) >= .5) == (call == "OVER") for X in (fa, fb)):
                call = "pass(form)"
            print("  %-22s v %-22s %5.1f  fav %3.0f%%  over %4.1f%% / under %4.1f%% (n=%d)  %-10s | 2026 over: %d/%d, %d/%d | %s" % (
                nm, op, L, 100 * fv, 100 * o, 100 * (1 - o), len(sim), call, sum(fa), len(fa), sum(fb), len(fb), t))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "test"
    if cmd == "scrape":
        scrape(*[int(v) for v in sys.argv[2:4]])
    elif cmd == "test":
        test()
    elif cmd == "price":
        price()
