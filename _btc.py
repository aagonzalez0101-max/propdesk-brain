"""BTC odds from 1-minute history (Coinbase, free).

  python _btc.py pull              # fetch/extend 1 year of 1-min candles -> data/btc_1m.csv
  python _btc.py odds 81690 19:50  # P(BTC above/below 81,690 at 7:50 PM CT), from history

Odds = every h-minute move in the last year (h = minutes until the target time), with the moves scaled
to the CURRENT volatility (last 60 min vs its yearly norm, blended 50/50), centered on now's price.
Settlement indexes (CF BRTI) can sit $20-60 off Coinbase -- check Kalshi for the same strike.
"""
import bisect, csv, datetime, json, math, os, sys, time, urllib.request

F = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "btc_1m.csv")
URL = "https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=60&start=%s&end=%s"
g = lambda u: json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=30))
CT = datetime.timezone(datetime.timedelta(hours=-5))


def load():
    if not os.path.exists(F):
        return {}
    with open(F) as f:
        return {int(r[0]): float(r[1]) for r in csv.reader(f)}


def save(d):
    os.makedirs(os.path.dirname(F), exist_ok=True)
    with open(F, "w", newline="") as f:
        csv.writer(f).writerows(sorted(d.items()))


def fetch(d, start, end):
    t = start
    while t < end:
        e = min(t + 300 * 60, end)
        for _ in range(4):
            try:
                for c in g(URL % (datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat(),
                                  datetime.datetime.fromtimestamp(e, datetime.timezone.utc).isoformat())):
                    d[int(c[0])] = float(c[4])
                break
            except Exception:
                time.sleep(2)
        t = e
        time.sleep(0.11)


def pull(days=365):
    d = load()
    now = int(time.time()) // 60 * 60
    start = now - days * 86400
    if d:
        fetch(d, max(d) + 60, now)
        if min(d) > start + 3600:
            fetch(d, start, min(d))
    else:
        fetch(d, start, now)
    save(d)
    print("btc 1m: %d candles, %s -> %s" % (len(d), datetime.datetime.fromtimestamp(min(d), CT), datetime.datetime.fromtimestamp(max(d), CT)))


def board(hhmm=None, step=100, n=2):
    """Table for the next 5-minute mark (or HH:MM): strikes around spot, above/below odds, DK clear prices."""
    now = datetime.datetime.now(CT)
    if not hhmm:
        t = (now + datetime.timedelta(minutes=5 - now.minute % 5)).replace(second=0, microsecond=0)
        hhmm = t.strftime("%H:%M")
    spot, h, tgt, moves, vr = _moves(hhmm)
    dk = lambda p: next((c for c in range(99, 0, -1) if (c / 100) / (1.25 - 0.25 * c / 100) <= p), 0)
    print("BTC $%s at %s CT -> %s CT (%d min, vol x%.2f)" % (format(round(spot), ","), now.strftime("%I:%M %p").lstrip("0"),
          tgt.strftime("%I:%M %p").lstrip("0"), h, vr))
    print("  strike   | above | below | DK ABOVE <= | DK BELOW <=")
    base = round(spot / step) * step
    for k in range(base - n * step, base + (n + 1) * step, step):
        a = 1 - bisect.bisect_right(moves, math.log(k / spot)) / len(moves)
        print("  $%s |  %2d%%  |  %2d%%  |    %2dc     |    %2dc" % (format(k, ","), round(100 * a), round(100 * (1 - a)), dk(a), dk(1 - a)))


def _moves(hhmm):
    d = load()
    n0 = len(d)
    fetch(d, max(d) + 60, int(time.time()) // 60 * 60 + 60)
    if len(d) > n0:
        save(d)
    ts = sorted(d)
    px = [d[t] for t in ts]
    spot = float(g("https://api.coinbase.com/v2/prices/BTC-USD/spot")["data"]["amount"])
    now = datetime.datetime.now(CT)
    hh, mm = map(int, hhmm.split(":"))
    tgt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if tgt <= now:
        tgt += datetime.timedelta(days=1)
    h = max(1, round((tgt - now).total_seconds() / 60))
    r1 = [math.log(px[i] / px[i - 1]) for i in range(1, len(px)) if ts[i] - ts[i - 1] == 60]
    sd_year = (sum(x * x for x in r1) / len(r1)) ** 0.5
    rec = r1[-60:]
    sd_now = (sum(x * x for x in rec) / len(rec)) ** 0.5
    scale = 0.5 + 0.5 * sd_now / sd_year
    step = max(1, h // 5)
    idx = {t: i for i, t in enumerate(ts)}
    moves = sorted(math.log(px[j] / px[i]) * scale for i in range(0, len(ts), step)
                   for j in [idx.get(ts[i] + h * 60)] if j is not None)
    return spot, h, tgt, moves, sd_now / sd_year


def odds(strike, hhmm):
    d = load()
    fetch(d, max(d) + 60, int(time.time()) // 60 * 60 + 60)  # top up to now
    ts = sorted(d)
    px = [d[t] for t in ts]
    spot = float(g("https://api.coinbase.com/v2/prices/BTC-USD/spot")["data"]["amount"])
    now = datetime.datetime.now(CT)
    hh, mm = map(int, hhmm.split(":"))
    tgt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if tgt <= now:
        tgt += datetime.timedelta(days=1)
    h = max(1, round((tgt - now).total_seconds() / 60))
    # yearly 1-min vol vs the last 60 minutes -> scale factor
    r1 = [math.log(px[i] / px[i - 1]) for i in range(1, len(px)) if ts[i] - ts[i - 1] == 60]
    sd_year = (sum(x * x for x in r1) / len(r1)) ** 0.5
    rec = r1[-60:]
    sd_now = (sum(x * x for x in rec) / len(rec)) ** 0.5
    scale = 0.5 + 0.5 * sd_now / sd_year
    # every h-minute move over the year (non-overlapping when h is large, to keep it fast)
    step = max(1, h // 5)
    idx = {t: i for i, t in enumerate(ts)}
    moves = []
    for i in range(0, len(ts), step):
        j = idx.get(ts[i] + h * 60)
        if j is not None:
            moves.append(math.log(px[j] / px[i]) * scale)
    moves.sort()
    need = math.log(strike / spot)
    above = 1 - bisect.bisect_right(moves, need) / len(moves)
    q = lambda p: spot * math.exp(moves[int(p * (len(moves) - 1))])
    print("BTC $%s now (%s CT) -> %s CT, %d min | %d historical %d-min moves, vol now x%.2f of normal"
          % (format(round(spot), ","), now.strftime("%I:%M %p").lstrip("0"), tgt.strftime("%I:%M %p").lstrip("0"),
             h, len(moves), h, sd_now / sd_year))
    print("  ABOVE $%s: %.0f%%   BELOW: %.0f%%" % (format(round(strike), ","), 100 * above, 100 * (1 - above)))
    print("  80%% range: $%s - $%s   50%% range: $%s - $%s" % tuple(format(round(q(p)), ",") for p in (0.1, 0.9, 0.25, 0.75)))
    dk = lambda p: next((c for c in range(99, 0, -1) if (c / 100) / (1.25 - 0.25 * c / 100) <= p), 0)
    print("  with the 25%% boost: DK ABOVE clears at <= %dc, DK BELOW at <= %dc" % (dk(above), dk(1 - above)))


if __name__ == "__main__":
    if sys.argv[1] == "board":
        board(sys.argv[2] if len(sys.argv) > 2 else None)
    elif sys.argv[1] == "pull":
        pull(int(sys.argv[2]) if len(sys.argv) > 2 else 365)
    else:
        odds(float(sys.argv[2].replace(",", "")), sys.argv[3])
