"""NPB BOARD -- Pinnacle prices + both probable starters' season lines (2026-10-02).
User: "Japan is just pitcher oriented" -- 10/1 the starters flipped Giants -> Yakult and Yakult won 5-1.

    python _npb.py              # next NPB slate: fair prices, starters (ERA / WHIP / IP per start), ERA gap, opener flag

Sources (free): Pinnacle guest league 187703; npb.jp/announcement/starter/ (probables, links to player pages);
npb.jp/bis/<year>/stats/idp1_<team>.html (every pitcher's season line by team).
Read: a starter ERA gap of 2+ runs or an opener (under 3.5 IP per appearance) is the flag; the market weights standings and
team ERA more than the day's arms. Lean the better starter at fair price or better. NOT a measured edge yet -- log results.
"""
import re, html, datetime, requests

H = {"User-Agent": "Mozilla/5.0"}
CT = datetime.timezone(datetime.timedelta(hours=-5))
t = lambda s: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()
TEAM_CODE = {"巨人": "g", "読売": "g", "ヤクルト": "s", "DeNA": "db", "中日": "d", "阪神": "t", "広島": "c", "ソフトバンク": "h",
             "日本ハム": "f", "ロッテ": "m", "楽天": "e", "西武": "l", "オリックス": "b"}
EN = {"g": "Yomiuri Giants", "s": "Tokyo Yakult Swallows", "db": "Yokohama DeNA BayStars", "d": "Chunichi Dragons", "t": "Hanshin Tigers",
      "c": "Hiroshima Toyo Carp", "h": "Fukuoka Softbank Hawks", "f": "Hokkaido Nippon-Ham Fighters", "m": "Chiba Lotte Marines",
      "e": "Tohoku Rakuten Golden Eagles", "l": "Saitama Seibu Lions", "b": "Orix Buffaloes"}


def ipf(s):
    a = __import__("re").sub(r"[^0-9.]", "", s or "").split(".")      # 10/9: Yahoo started writing "12+" -> int('+') crashed the board
    return int(a[0] or 0) + (int(a[1]) / 3 if len(a) > 1 and a[1] else 0)


_tables = {}


def team_pitchers(code, year):
    if code in _tables:
        return _tables[code]
    r = requests.get("https://npb.jp/bis/%d/stats/idp1_%s.html" % (year, code), headers=H, timeout=30); r.encoding = "utf-8"
    out, ip_t, er_t = {}, 0.0, 0
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, re.S):
        c = [t(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(c) < 24:
            continue
        name = c[0].replace("*", "").replace(" ", "").replace("　", "").strip()
        ip, g = ipf(c[12]), int(c[1] or 0)
        out[name] = dict(g=g, w=c[2], l=c[3], ip=ip, h=int(c[13] or 0), bb=int(c[15] or 0), k=int(c[18] or 0), era=c[23])
        ip_t += ip; er_t += int(c[22] or 0)
    _tables[code] = (out, 9 * er_t / ip_t if ip_t else None)
    return _tables[code]


def starters():
    r = requests.get("https://npb.jp/announcement/starter/", headers=H, timeout=30); r.encoding = "utf-8"
    out = []
    for pid in dict.fromkeys(re.findall(r'href="/bis/players/(\d+)\.html"', r.text)):
        p = requests.get("https://npb.jp/bis/players/%s.html" % pid, headers=H, timeout=30); p.encoding = "utf-8"
        name = t(re.search(r'<li id="pc_v_name">(.*?)</li>', p.text, re.S).group(1))
        team = t((re.search(r'<li id="pc_v_team">(.*?)</li>', p.text, re.S) or re.search(r"(x)", "x")).group(1))
        code = next((v for k, v in TEAM_CODE.items() if k in team), None)
        out.append(dict(name=name, team=team, code=code))
    return out


def pinnacle():
    import _kbo as K
    mu = requests.get(K.PIN + "/0.1/leagues/187703/matchups", headers=K.PH, timeout=25).json()
    mk = requests.get(K.PIN + "/0.1/leagues/187703/markets/straight", headers=K.PH, timeout=25).json()
    names = {m["id"]: ({p["alignment"]: p["name"] for p in m["participants"]}, m["startTime"]) for m in mu if m.get("type") == "matchup" and not m.get("parentId")}
    imp = lambda p: 100 / (p + 100) if p > 0 else -p / (-p + 100)
    games = []
    for x in mk:
        if x["matchupId"] in names and x.get("period") == 0 and not x.get("isAlternate") and x["type"] == "moneyline":
            n, st = names[x["matchupId"]]; d = {p["designation"]: p["price"] for p in x["prices"]}
            a, h = imp(d["away"]), imp(d["home"])
            games.append(dict(away=n["away"], home=n["home"], pa=a / (a + h), ml=d, start=st))
    return games


def fair(q):
    return ("-%d" % round(100 * q / (1 - q))) if q >= 0.5 else "+%d" % round(100 * (1 - q) / q)


if __name__ == "__main__":
    year = datetime.date.today().year
    S = starters()
    by_team = {}
    for s in S:
        if not s["code"]:
            continue
        tab, tera = team_pitchers(s["code"], year)
        line = tab.get(s["name"].replace(" ", "").replace("　", ""))
        by_team[EN[s["code"]]] = dict(s, line=line, team_era=tera)
    site = []
    for gm in pinnacle():
        st = datetime.datetime.fromisoformat(gm["start"].replace("Z", "+00:00")).astimezone(CT).strftime("%a %m/%d %I:%M %p CT")
        print("\n%s @ %s   %s" % (gm["away"], gm["home"], st))
        print("   Pinnacle fair: %s %.1f%% (%s) / %s %.1f%% (%s)" % (gm["away"].split()[-1], 100 * gm["pa"], fair(gm["pa"]),
                                                                    gm["home"].split()[-1], 100 * (1 - gm["pa"]), fair(1 - gm["pa"])))
        eras = {}
        for side in ("away", "home"):
            b = by_team.get(gm[side])
            if not b or not b["line"]:
                print("   %-5s starter: not announced / not matched" % side); continue
            L = b["line"]; ipg = L["ip"] / max(L["g"], 1)
            whip = (L["h"] + L["bb"]) / max(L["ip"], 1)
            eras[side] = float(L["era"]) if L["era"] not in ("", "-") and L["ip"] >= 30 else None   # <30 IP = noise, no gap flag
            print("   %-5s %-10s %s-%s  ERA %-5s WHIP %.2f  IP %.0f over %d (%.1f/app)%s  | team ERA %.2f" % (
                side, b["name"], L["w"], L["l"], L["era"], whip, L["ip"], L["g"], ipg, "  <-- OPENER / bullpen game" if ipg < 3.5 else ("  (small sample: <30 IP)" if L["ip"] < 30 else ""), b["team_era"] or 0))
        row = dict(away=gm["away"], home=gm["home"], start=gm["start"], p_away=round(gm["pa"], 3), fair_away=fair(gm["pa"]),
                   fair_home=fair(1 - gm["pa"]), starters={})
        for side in ("away", "home"):
            b = by_team.get(gm[side])
            if b and b["line"]:
                L = b["line"]
                row["starters"][side] = dict(name=b["name"], w=L["w"], l=L["l"], era=L["era"], ip=round(L["ip"], 1), g=L["g"],
                                             whip=round((L["h"] + L["bb"]) / max(L["ip"], 1), 2), k=L["k"], team_era=round(b["team_era"] or 0, 2))
        site.append(row)
        if len(eras) == 2 and None not in eras.values():
            gap = eras["away"] - eras["home"]
            better = "home" if gap > 0 else "away"
            if abs(gap) >= 2:
                row["flag"] = dict(side=better, team=gm[better], gap=round(abs(gap), 2))
                print("   FLAG: starter ERA gap %.2f -> lean %s (take at %s or better)" % (abs(gap), gm[better], fair(1 - gm["pa"] if better == "home" else gm["pa"])))

    import json, os
    json.dump(site, open(os.path.join("site", "npb.json"), "w", encoding="utf-8"), ensure_ascii=False)
