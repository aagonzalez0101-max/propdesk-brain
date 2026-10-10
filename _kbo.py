"""KBO -- Korean baseball. Free data (Naver) + free prices (Pinnacle league 6227).

    python _kbo.py pull [first_year]     # season results -> kbo_games.jsonl
    python _kbo.py test                  # does a team model beat the closing line?
    python _kbo.py board                 # tonight's games, Pinnacle fair price, model price

Why KBO: the MLB ladder is the best thing in this project and MLB's regular season ends in
days. KBO runs to late October plus playoffs into November, and Pinnacle prices it, so the
ladder has somewhere to go. Games start about 4:30am CT -- this is an overnight market.

Data notes that cost time:
  * Naver answers in Korean and Windows consoles are cp1252, so anything that prints a team
    name needs PYTHONIOENCODING=utf-8 or it dies on an encode error, not a network error.
  * `reversedHomeAway` is a display hint only; home/away scores stay labelled correctly.
  * Only statusCode == "RESULT" rows are finished. Cancelled and suspended games carry 0-0
    and would otherwise read as real ties -- and a tie IS a genuine KBO outcome, unlike MLB,
    so the model scores it 0.5 instead of dropping it.
"""
import json, os, sys, math, time, collections, datetime
import requests

OUT = "kbo_games.jsonl"
NAVER = "https://api-gw.sports.naver.com/schedule/games"
PIN = "https://guest.api.arcadia.pinnacle.com"
H = {"User-Agent": "Mozilla/5.0"}
PH = {"User-Agent": "Mozilla/5.0", "X-API-Key": "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R"}
LEAGUE = 6227
CT = datetime.timezone(datetime.timedelta(hours=-5))

# Pinnacle spells them out in English, Naver uses two-letter codes
NAME = {"Doosan Bears": "OB", "LG Twins": "LG", "Kia Tigers": "HT", "KIA Tigers": "HT",
        "Samsung Lions": "SS", "Lotte Giants": "LT", "Hanwha Eagles": "HH",
        "NC Dinos": "NC", "KT Wiz": "KT", "SSG Landers": "SK", "Kiwoom Heroes": "WO"}


def pull(first=2023, last=None):
    last = last or datetime.date.today().year
    have = set()
    if os.path.exists(OUT):
        for l in open(OUT, encoding="utf-8"):
            try:
                have.add(json.loads(l)["gameId"])
            except Exception:
                pass
    print("have %d games; pulling %d..%d" % (len(have), first, last), flush=True)
    f = open(OUT, "a", encoding="utf-8")
    new = 0
    for yr in range(first, last + 1):
        for mo in range(3, 12):
            a = "%d-%02d-01" % (yr, mo)
            b = "%d-%02d-%02d" % (yr, mo, 31 if mo in (3, 5, 7, 8, 10, 12) else 30)
            try:
                # `size` is the ONLY page-size param Naver honours. `limit`, `pageSize` and
                # `count` are accepted and silently ignored, returning 10 rows with no error
                # -- which reads as "that month had 10 games" instead of as a truncation.
                r = requests.get(NAVER, params=dict(fromDate=a, toDate=b, categoryId="kbo",
                                                    size=500), headers=H, timeout=30).json()
            except Exception as e:
                print("  %s: %s" % (a, str(e)[:50]))
                time.sleep(3)
                continue
            gs = (r.get("result") or {}).get("games") or []
            add = 0
            for g in gs:
                if g.get("statusCode") != "RESULT" or g.get("cancel") or g.get("suspended"):
                    continue
                if g["gameId"] in have:
                    continue
                have.add(g["gameId"])
                add += 1
                f.write(json.dumps(dict(
                    gameId=g["gameId"], date=g["gameDate"], dt=g.get("gameDateTime"),
                    home=g["homeTeamCode"], away=g["awayTeamCode"],
                    hs=g.get("homeTeamScore"), as_=g.get("awayTeamScore"),
                    winner=g.get("winner")), ensure_ascii=False) + "\n")
            new += add
            if add:
                print("  %d-%02d  +%d  (total %d)" % (yr, mo, add, len(have)), flush=True)
            f.flush()
            time.sleep(0.4)
    f.close()
    print("done: %d new -> %s (%d total)" % (new, OUT, len(have)))


def load():
    rows = []
    for l in open(OUT, encoding="utf-8"):
        try:
            r = json.loads(l)
        except Exception:
            continue
        if r.get("hs") is None or r.get("as_") is None:
            continue
        rows.append(r)
    rows.sort(key=lambda r: (r["date"], r["gameId"]))
    return rows


class Elo:
    """Team strength with a home edge, walked forward in date order.

    A tie scores 0.5 rather than being dropped, because KBO stops at the 12th inning.
    Ratings regress toward 1500 between seasons by `carry`.
    """

    def __init__(self, k=18.0, home_adv=0.0, carry=0.72):
        self.k = k
        self.home_adv = home_adv
        self.carry = carry
        self.r = collections.defaultdict(lambda: 1500.0)
        self.season = None

    def p_home(self, h, a):
        return 1 / (1 + 10 ** ((self.r[a] - self.r[h] - self.home_adv) / 400))

    def update(self, g):
        yr = g["date"][:4]
        if self.season and yr != self.season:
            for t in list(self.r):
                self.r[t] = 1500 + self.carry * (self.r[t] - 1500)
        self.season = yr
        h, a = g["home"], g["away"]
        p = self.p_home(h, a)
        s = 0.5 if g["hs"] == g["as_"] else (1.0 if g["hs"] > g["as_"] else 0.0)
        self.r[h] += self.k * (s - p)
        self.r[a] += self.k * ((1 - s) - (1 - p))


def fit_home_adv(rows):
    hw = sum(1 for g in rows if g["hs"] > g["as_"])
    dec = sum(1 for g in rows if g["hs"] != g["as_"])
    p = hw / dec
    return 400 * math.log10(p / (1 - p)), p


def test():
    rows = load()
    if len(rows) < 500:
        print("only %d games -- run: python _kbo.py pull" % len(rows))
        return
    adv, hwp = fit_home_adv(rows)
    ties = sum(1 for g in rows if g["hs"] == g["as_"])
    print("%d games, %s .. %s" % (len(rows), rows[0]["date"], rows[-1]["date"]))
    print("home team wins %.1f%% of decided games -> home edge %.0f Elo points" % (100 * hwp, adv))
    print("ties: %d (%.1f%%)\n" % (ties, 100 * ties / len(rows)))
    cut = int(len(rows) * 0.6)
    best = None
    for k in (12.0, 16.0, 20.0, 24.0):
        for carry in (0.6, 0.72, 0.85):
            e = Elo(k, adv, carry)
            for g in rows[:cut]:
                e.update(g)
            n = hit = 0
            ll = 0.0
            for g in rows[cut:]:
                if g["hs"] == g["as_"]:
                    e.update(g)
                    continue
                p = e.p_home(g["home"], g["away"])
                won = g["hs"] > g["as_"]
                ll += -math.log(max(1e-9, p if won else 1 - p))
                hit += 1 if (p > .5) == won else 0
                n += 1
                e.update(g)
            if best is None or ll / n < best[0]:
                best = (ll / n, hit / n, k, carry, n)
    ll, acc, k, carry, n = best
    print("best walk-forward Elo: k=%g carry=%.2f  ->  %.1f%% of %d games, logloss %.4f" %
          (k, carry, 100 * acc, n, ll))
    print("a coin flip is logloss 0.693; always taking the home team is %.1f%%" % (100 * hwp))
    return k, carry, adv


def board():
    rows = load()
    adv, _ = fit_home_adv(rows)
    e = Elo(20.0, adv, 0.72)
    for g in rows:
        e.update(g)
    mu = requests.get(PIN + "/0.1/leagues/%d/matchups?brandId=0" % LEAGUE, headers=PH, timeout=25).json()
    mk = requests.get(PIN + "/0.1/leagues/%d/markets/straight" % LEAGUE, headers=PH, timeout=25).json()
    games = {}
    for m in mu:
        if m.get("parent") or len(m.get("participants") or []) != 2:
            continue
        ps = m["participants"]
        games[m["id"]] = dict(
            home=next((p["name"] for p in ps if p.get("alignment") == "home"), ps[0]["name"]),
            away=next((p["name"] for p in ps if p.get("alignment") == "away"), ps[1]["name"]),
            start=m.get("startTime"))

    def imp(o):
        return (-o) / ((-o) + 100) if o < 0 else 100 / (o + 100)

    print("  %-17s %-17s %-13s %-12s %-12s %s" %
          ("away", "home", "pinnacle", "market fair", "our model", "start (CT)"))
    seen = set()
    for r in mk:
        if r.get("type") != "moneyline" or r.get("period") != 0:
            continue
        g = games.get(r.get("matchupId"))
        pr = r.get("prices") or []
        if not g or len(pr) != 2 or r.get("matchupId") in seen:
            continue
        d = {p.get("designation"): p["price"] for p in pr}
        if "home" not in d or "away" not in d:
            continue
        seen.add(r.get("matchupId"))
        ih, ia = imp(d["home"]), imp(d["away"])
        fh = ih / (ih + ia)
        mh = e.p_home(NAME.get(g["home"], g["home"]), NAME.get(g["away"], g["away"]))
        try:
            st = datetime.datetime.fromisoformat(
                g["start"].replace("Z", "+00:00")).astimezone(CT).strftime("%a %I:%M%p")
        except Exception:
            st = (g.get("start") or "")[:16]
        print("  %-17s %-17s %+5d/%+5d  %3.0f%%/%-3.0f%%   %3.0f%%/%-3.0f%%   %s" %
              (g["away"][:17], g["home"][:17], d["away"], d["home"],
               100 * (1 - fh), 100 * fh, 100 * (1 - mh), 100 * mh, st))


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] == "pull":
        pull(int(a[1]) if len(a) > 1 else 2023)
    elif a[0] == "test":
        test()
    elif a[0] == "board":
        board()
    else:
        print(__doc__)
