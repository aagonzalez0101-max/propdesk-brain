"""ASK THE BOT (10/16, user: "I want it to be crazy"). He types a leg in #ask, the bot answers within a minute with the same checks
I run by hand: projection vs line, last 10 / season / last season / vs this opponent, the sharp price where one exists, and a call.

    Bateman 20.5 over          Bloomer 38.5 under          Naone over 16.5          Tatum pts+asts 32.5 under
Polled every minute by the cloud loop (no always-on connection). Needs DISCORD_BOT_TOKEN and the bot's Message Content Intent ON.
    python _ask.py              # one pass: answer every new question in #ask
    python _ask.py setup        # create the #ask channel (bot has admin) and remember its id
"""
import os, re, json, time, datetime, requests

API = "https://discord.com/api/v10"
STATE = "_ask_state.json"
LG = {9: "NFL", 15: "CFB", 8: "NHL", 7: "NBA", 82: "SOCCER", 3: "WNBA", 265: "CS2", 2: "MLB"}
CT = datetime.timezone(datetime.timedelta(hours=-5))
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())


def tok():
    t = os.environ.get("DISCORD_BOT_TOKEN")
    if not t and os.path.exists(".env"):
        for l in open(".env", encoding="utf-8"):
            if l.startswith("DISCORD_BOT_TOKEN="):
                t = l.split("=", 1)[1].strip()
    return t


def call(method, path, **kw):
    H = {"Authorization": "Bot " + tok(), "User-Agent": "PropDesk (github, 1.0)"}
    for _ in range(3):
        r = requests.request(method, API + path, headers=H, timeout=20, **kw)
        if r.status_code == 429:
            time.sleep(float(r.json().get("retry_after", 1)) + 0.2); continue
        return r
    return r


def load():
    return json.load(open(STATE)) if os.path.exists(STATE) else {}


def setup():
    st = load()
    card = "1558324637845295164"
    gid = call("GET", "/channels/%s" % card).json().get("guild_id")
    chans = call("GET", "/guilds/%s/channels" % gid).json()
    ask = next((c for c in chans if c.get("name") == "ask" and c.get("type") == 0), None)
    if not ask:
        parent = next((c.get("parent_id") for c in chans if c.get("id") == card), None)
        ask = call("POST", "/guilds/%s/channels" % gid, json={"name": "ask", "type": 0, "parent_id": parent,
                                                               "topic": "Type a leg: 'Bateman 20.5 over'. The bot answers within a minute."}).json()
    st["channel"] = ask["id"]
    json.dump(st, open(STATE, "w"))
    print("#ask channel:", ask["id"])
    return ask["id"]


_boards, _failed = {}, set()


def board(lg):
    if lg in _boards:
        return _boards[lg]
    rows = []
    for wait in (0, 15, 30):
        time.sleep(wait)
        r = requests.get("https://partner-api.prizepicks.com/projections?league_id=%d&per_page=1000" % lg, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            d = r.json()
            P = {x["id"]: x["attributes"] for x in d.get("included", []) if x["type"] == "new_player"}
            for p in d.get("data", []):
                a = p["attributes"]
                if a.get("odds_type") != "standard":
                    continue
                pl = P.get(p["relationships"]["new_player"]["data"]["id"], {})
                rows.append(dict(sport=LG[lg], player=pl.get("name"), team=pl.get("team"), opp=a.get("description"), stat=a.get("stat_type"),
                                 line=float(a["line_score"]), start=a.get("start_time"), img=pl.get("image_url")))
            break
    else:
        _failed.add(lg)
    _boards[lg] = rows
    return rows


def parse(q):
    q = q.strip()
    side = "over" if re.search(r"\b(over|more|higher|o)\b", q, re.I) else "under" if re.search(r"\b(under|less|lower|u)\b", q, re.I) else None
    m = re.search(r"(\d+(?:\.\d+)?)", q)
    line = float(m.group(1)) if m else None
    words = re.sub(r"\b(over|under|more|less|higher|lower|o|u)\b|\d+(\.\d+)?", " ", q, flags=re.I).strip()
    return words, line, side


def find(words, line):
    """best PP standard row: the player whose name matches the words, the stat the rest of the words point at, the line closest to his"""
    toks = [t for t in re.split(r"\s+", words.lower()) if t]
    best, bs = None, -1
    for lg in LG:
        for r in board(lg):
            nm = (r["player"] or "").lower()
            ns = sum(1 for t in toks if len(t) >= 3 and t in nm)
            if not ns:
                continue
            st = (r["stat"] or "").lower()
            ss = sum(1 for t in toks if t not in nm and (t in st or t.replace("+", "") in st.replace("+", "")))
            sc = ns * 10 + ss * 3 - (abs(r["line"] - line) if line is not None else 0)
            if sc > bs:
                best, bs = r, sc
        if best and bs >= 10 and line is not None and abs(best["line"] - line) < 0.01:
            break
    return best


def answer(q):
    import _cardpost as C
    words, line, side = parse(q)
    if not words:
        return "Ask like: `Bateman 20.5 over`"
    r = find(words, line)
    if not r:
        if _failed:
            return "PrizePicks is rate-limiting me right now (%s board). Ask again in a minute." % ", ".join(LG[x] for x in _failed)
        return "Couldn't find **%s** on the PrizePicks board right now (pulled, or not posted yet)." % words
    side = side or "over"
    leg = dict(r, side=side, p=0.6)
    out = ["## %s %s %g %s" % ("HIGHER" if side == "over" else "LOWER", r["player"], r["line"], r["stat"]),
           "%s · %s vs %s" % (r["sport"], r.get("team") or "", (r.get("opp") or "")[:18])]
    if line is not None and abs(r["line"] - line) > 0.01:
        out.append("⚠️ PP's line is **%g**, not %g -- answering for %g" % (r["line"], line, r["line"]))
    S = None
    try:
        S = C.stats_for(leg)
    except Exception as e:
        print("stats:", e)
    sharp = None
    if r["sport"] == "CFB":
        try:
            src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_pair2x.py"), encoding="utf-8").read()
            import sqlite3, bisect
            SM = {"Receiving Yards": "receiving yards", "Rush Yards": "rushing yards", "Pass Yards": "passing yards", "Receptions": "receptions"}
            R_ = [(t, float(l), float(p)) for t, l, p in sqlite3.connect("lines.db", timeout=60).execute(
                "select ts, line, p_over from sharp where sport='CFB' and player=? and stat=?", (r["player"], SM.get(r["stat"], "-")))]
            if R_:
                last = max(x[0] for x in R_)[:13]; pts = sorted({(l, p) for t, l, p in R_ if t[:13] == last}); xs = [l for l, _ in pts]
                if xs and xs[0] <= r["line"] <= xs[-1]:
                    i = bisect.bisect_left(xs, r["line"])
                    po = pts[i][1] if xs[i] == r["line"] else pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * (r["line"] - xs[i - 1]) / (xs[i] - xs[i - 1])
                    sharp = po if side == "over" else 1 - po
        except Exception as e:
            print("cfb sharp:", e)
    if S:
        out.append(C.why_text(leg, S).split("🤖")[0].strip())
    else:
        out.append("_No game history for this market._")
    hits, n = (S["l10_hit"], len(S["l10"])) if S else (0, 0)
    seas = (S["seas_hit"] / S["seas_n"]) if S and S["seas_n"] else None
    good = []
    if n >= 5 and hits / n >= 0.7: good.append("last 10")
    if seas is not None and S["seas_n"] >= 3 and seas >= 0.65: good.append("this season")
    if S and S.get("vs_n") and S["vs_hit"] / S["vs_n"] >= 0.5: good.append("vs this opponent")
    bad = []
    if n >= 5 and hits / n < 0.5: bad.append("last 10")
    if seas is not None and S["seas_n"] >= 3 and seas < 0.5: bad.append("this season")
    if S and S.get("vs_n", 0) >= 2 and S["vs_hit"] / S["vs_n"] < 0.5: bad.append("head-to-head")
    if sharp is not None:
        out.append("🎯 Sharp books (FanDuel/Pinnacle): **%.0f%%** on this side%s" % (100 * sharp, " (backtest: 58%+ hit 69%)" if sharp >= 0.58 else ""))
        (good if sharp >= 0.58 else bad if sharp < 0.5 else []).append("sharp price")
    call_ = "✅ **BET**" if len(good) >= 2 and not bad else "⛔ **PASS**" if len(bad) >= 2 or (bad and not good) else "🟡 **LEAN**"
    out.append("")
    out.append("%s · for: %s · against: %s" % (call_, ", ".join(good) or "--", ", ".join(bad) or "--"))
    out.append("_Same checks as the card. A BET still needs a slip partner that clears._")
    return "\n".join(out)[:3900]


def main():
    if not tok():
        return
    st = load()
    ch = st.get("channel")
    if not ch:                                                # he creates #ask (the bot can't make channels) -> find it by name
        gid = call("GET", "/channels/1558324637845295164").json().get("guild_id")
        ch = next((c["id"] for c in call("GET", "/guilds/%s/channels" % gid).json() if c.get("name") == "ask" and c.get("type") == 0), None)
        if not ch:
            return
        st["channel"] = ch
    after = st.get("after")
    r = call("GET", "/channels/%s/messages?limit=20%s" % (ch, ("&after=%s" % after) if after else ""))
    if r.status_code != 200:
        print("ask read:", r.status_code, r.text[:200]); return
    msgs = sorted(r.json(), key=lambda m: int(m["id"]))
    for m in msgs:
        st["after"] = m["id"]
        if m["author"].get("bot"):
            continue
        q = (m.get("content") or "").strip()
        if not q:
            if not st.get("warned"):
                call("POST", "/channels/%s/messages" % ch, json={"content": "I can't read messages yet -- turn ON **Message Content Intent** in the Developer Portal (Bot tab)."})
                st["warned"] = True
            continue
        try:
            text = answer(q)
        except Exception as e:
            text = "Error answering: %s" % e
        call("POST", "/channels/%s/messages" % ch, json={"embeds": [{"description": text, "color": 0x5865F2}],
                                                         "message_reference": {"message_id": m["id"]}})
        print("answered:", q[:60])
    json.dump(st, open(STATE, "w"))


if __name__ == "__main__":
    import sys
    (setup if sys.argv[1:] == ["setup"] else main)()
