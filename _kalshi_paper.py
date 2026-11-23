"""KALSHI PROPS PAPER TEST (11/22, user: "how can we set up a good and easy test rn").
Each day: take the prop model's top 10 legs (prop_model_paper.jsonl, kind=leg), find the matching Kalshi ladder rung
(PP over 9.5 = Kalshi "10+" YES; PP under 9.5 = Kalshi "10+" NO), record the real Kalshi ask, and PAPER-bet $1 when
    our hit chance  -  (price + Kalshi taker fee)  >=  3 points
Our hit chance = the model's walk-forward hit rate for that rank band (top-3 ~65%, top-10 ~60%) -- NOT the raw model p, which
runs hot. Results come from the model ledger's own grading (prop_model_paper.jsonl result W/L/P), so nothing is graded twice.
    python _kalshi_paper.py log  [YYYY-MM-DD]   # after the model card: match + price + paper-bet -> kalshi_paper.jsonl
    python _kalshi_paper.py grade                # settle from the model ledger; print record, ROI, avg price vs our chance
"""
import sys, json, re, datetime, unicodedata
import requests

H = {"User-Agent": "Mozilla/5.0"}
B = "https://api.elections.kalshi.com/trade-api/v2"
LEDGER = "kalshi_paper.jsonl"
SERIES = {"Rebounds": "KXNBAREB", "Assists": "KXNBAAST", "Pts+Rebs+Asts": "KXNBAPRA", "Points": "KXNBALADDERPTS",
          "3-PT Made": "KXNBALADDER3PT", "Rebs+Asts": "KXNBARA", "Pts+Rebs": "KXNBAPR"}
HIT = {1: .65, 2: .65, 3: .65}            # walk-forward: top-3 legs ~65%, ranks 4-10 ~60% (prop_model_bt)
nn = lambda s: re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())
fee = lambda c: 0.07 * c * (1 - c)


def rungs(series):
    out, cur = [], None
    for _ in range(10):
        p = {"series_ticker": series, "status": "open", "limit": 1000}
        if cur:
            p["cursor"] = cur
        r = requests.get(B + "/markets", params=p, headers=H, timeout=30).json()
        for m in r.get("markets", []):
            mm = re.match(r"(.+?):\s*(\d+)\+", m.get("title") or "")
            if mm:
                out.append(dict(ticker=m["ticker"], player=mm.group(1).strip(), k=int(mm.group(2)),
                                yes=float(m.get("yes_ask_dollars") or 0), no=float(m.get("no_ask_dollars") or 0)))
        cur = r.get("cursor")
        if not cur:
            break
    return out


def log(day):
    legs = [json.loads(l) for l in open("prop_model_paper.jsonl", encoding="utf-8") if l.strip()]
    legs = [r for r in legs if r.get("kind") == "leg" and r.get("day") == day and r.get("sp") == "nba"]
    seen = {(json.loads(l)["day"], json.loads(l)["player"], json.loads(l)["stat"]) for l in open(LEDGER, encoding="utf-8")} if __import__("os").path.exists(LEDGER) else set()
    cache, n = {}, 0
    for r in legs:
        if (day, r["player"], r["stat"]) in seen or r["stat"] not in SERIES:
            continue
        s = SERIES[r["stat"]]
        if s not in cache:
            try:
                cache[s] = rungs(s)
            except Exception as e:
                print("kalshi", s, e); cache[s] = []
        k = int(r["line"] // 1) + 1                   # 9.5 -> 10+, 11 (whole) -> 12+ (11 would push on PP)
        m = next((x for x in cache[s] if nn(x["player"]) == nn(r["player"]) and x["k"] == k), None)
        chance = HIT.get(r["rank"], .60)
        row = dict(day=day, player=r["player"], stat=r["stat"], pp_line=r["line"], side=r["side"], rank=r["rank"], model_p=r["p"],
                   our_chance=chance, kalshi=None, price=None, edge=None, bet=False, result=None, net=None,
                   logged=datetime.datetime.now().isoformat(timespec="seconds"))
        if m:
            price = m["yes"] if r["side"] == "over" else m["no"]
            if 0 < price < 1:
                edge = chance - (price + fee(price))
                row.update(kalshi=m["ticker"], price=price, edge=round(edge, 4), bet=edge >= .03)
        with open(LEDGER, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        n += 1
        print("%-22s %-14s %s%-5g rank %d -> %s" % (r["player"][:22], r["stat"][:14], r["side"][0].upper(), r["line"], r["rank"],
              ("kalshi %.0fc, edge %+.0f pts -> %s" % (100 * row["price"], 100 * row["edge"], "PAPER BET $1" if row["bet"] else "pass"))
              if row["price"] else "no Kalshi rung"))
    print("logged %d legs for %s" % (n, day))


def grade():
    res = {(r["day"], r["player"], r["stat"]): r.get("result") for r in
           (json.loads(l) for l in open("prop_model_paper.jsonl", encoding="utf-8") if l.strip()) if r.get("kind") == "leg"}
    rows = [json.loads(l) for l in open(LEDGER, encoding="utf-8") if l.strip()]
    for r in rows:
        if r["result"] is None:
            x = res.get((r["day"], r["player"], r["stat"]))
            if x in ("W", "L", "P"):
                r["result"] = x
                if r["bet"]:
                    r["net"] = 0.0 if x == "P" else (round((1 - r["price"] - fee(r["price"])) / (r["price"] + fee(r["price"])), 4) if x == "W" else -1.0)
    open(LEDGER, "w", encoding="utf-8").write("".join(json.dumps(r) + "\n" for r in rows))
    priced = [r for r in rows if r["price"]]
    bets = [r for r in rows if r["bet"] and r["net"] is not None]
    print("KALSHI PROPS PAPER: %d model legs logged, %d had a Kalshi rung, %d paper bets settled" % (len(rows), len(priced), len(bets)))
    if bets:
        w = sum(r["result"] == "W" for r in bets)
        print("  bets %d-%d, net %+.2f units on $1 each (%+.1f%%), avg price %.0fc" % (w, len(bets) - w, sum(r["net"] for r in bets),
              100 * sum(r["net"] for r in bets) / len(bets), 100 * sum(r["price"] for r in bets) / len(bets)))
    g = [r for r in priced if r["result"] in ("W", "L")]
    if g:
        print("  all priced legs: hit %.0f%% vs Kalshi's avg price %.0fc -- the gap is the edge" % (
            100 * sum(r["result"] == "W" for r in g) / len(g), 100 * sum(r["price"] for r in g) / len(g)))


if __name__ == "__main__":
    if sys.argv[1:2] == ["log"]:
        log(sys.argv[2] if len(sys.argv) > 2 else datetime.date.today().isoformat())
    else:
        grade()
