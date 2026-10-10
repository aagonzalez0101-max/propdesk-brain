"""Valorant per-map player stats from vlr.gg (free, HTML) -> val_maps.jsonl

    python _val_pull.py 60 [start_page]     # results pages, newest first (~50 matches per page)

One row per player per map: match id, date, event, map, team, opponent, rounds, won, agent,
role (duelist/initiator/controller/sentinel), kills, deaths, assists, acs. Resumable: skips
match ids already saved. Same row shape as cs2_maps.jsonl so the CS2 kill model can be reused
with an agent-role term on top.
"""
import re, os, sys, json, time, html, urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
OUT = "val_maps2.jsonl"   # v2: adds hsp/fb/fd/adr
ROLE = {a: "duelist" for a in ("jett", "raze", "reyna", "phoenix", "yoru", "neon", "iso", "waylay")}
ROLE.update({a: "initiator" for a in ("sova", "breach", "skye", "kayo", "fade", "gekko", "tejo")})
ROLE.update({a: "controller" for a in ("brimstone", "omen", "viper", "astra", "harbor", "clove", "miks")})
ROLE.update({a: "sentinel" for a in ("sage", "cypher", "killjoy", "chamber", "deadlock", "vyse", "veto")})


def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40).read().decode("utf-8", "replace")


def txt(s):
    return html.unescape(re.sub(r"<[^>]+>", " ", s)).strip()


def parse_match(mid):
    h = get("https://www.vlr.gg/%s" % mid)
    date = re.search(r'data-utc-ts="(\d{4}-\d{2}-\d{2})', h)
    date = date.group(1) if date else ""
    ev = re.search(r'class="match-header-event"[^>]*>(.*?)</a>', h, re.S)
    event = re.sub(r"\s+", " ", txt(ev.group(1))) if ev else ""
    rows = []
    blocks = re.split(r'class="vm-stats-game\s*[^"]*" data-game-id="', h)[1:]
    for b in blocks:
        gid = b.split('"', 1)[0]
        if gid == "all":
            continue
        head = b[:6000]
        teams = [re.sub(r"\s+", " ", txt(t)) for t in re.findall(r'class="team-name">(.*?)</div>', head, re.S)][:2]
        scores = [int(s) for s in re.findall(r'class="score[^"]*"[^>]*>\s*(\d+)\s*<', head)][:2]
        mp = re.search(r'<span style="position: relative;[^>]*>\s*([A-Za-z]+)', head)
        mapname = mp.group(1) if mp else ""
        if len(teams) != 2 or len(scores) != 2 or max(scores) < 13:
            continue
        prow = re.findall(r'<div class="ovw-row">(.*?)(?=<div class="ovw-row">|</div>\s*</div>\s*</div>\s*<div class="vm-stats|$)', b, re.S)
        players = []
        for r in prow:
            nm = re.search(r'class="ovw-player-name[^"]*">\s*(.*?)\s*<', r)
            pid = re.search(r'href="/player/(\d+)/', r)
            tag = re.search(r'class="ovw-player-tag[^"]*">\s*(.*?)\s*<', r)
            ag = re.search(r'/agents/(\w+)\.png', r)
            k = re.search(r'data-col="kills"><span class="side mod-both">\s*(-?\d+)', r)
            d = re.search(r'data-col="deaths"><span class="side mod-both">\s*(-?\d+)', r)
            a = re.search(r'data-col="assists"><span class="side mod-both">\s*(-?\d+)', r)
            acs = re.search(r'data-col="acs"><span class="stats-sq"><span class="side mod-both">\s*(\d+)', r)
            # hsp = headshot PERCENT (vlr gives no raw count), fb/fd = first blood / first death,
            # adr and kast round out what he reads off the site
            hsp = re.search(r'data-col="hsp"[^>]*>.*?mod-both">\s*(\d+)%', r, re.S)
            fb = re.search(r'data-col="fb"[^>]*>.*?mod-both">\s*(-?\d+)', r, re.S)
            fd = re.search(r'data-col="fd"[^>]*>.*?mod-both">\s*(-?\d+)', r, re.S)
            adr = re.search(r'data-col="adr"[^>]*>.*?mod-both">\s*(\d+)', r, re.S)
            if not (nm and k):
                continue
            players.append(dict(name=txt(nm.group(1)), pid=pid.group(1) if pid else None,
                                tag=txt(tag.group(1)) if tag else "",
                                agent=ag.group(1) if ag else "", kills=int(k.group(1)),
                                deaths=int(d.group(1)) if d else None, assists=int(a.group(1)) if a else None,
                                acs=int(acs.group(1)) if acs else None,
                                hsp=int(hsp.group(1)) if hsp else None,
                                fb=int(fb.group(1)) if fb else None,
                                fd=int(fd.group(1)) if fd else None,
                                adr=int(adr.group(1)) if adr else None))
            if len(players) == 10:
                break
        if len(players) != 10:
            continue
        rounds = sum(scores)
        for i, p in enumerate(players):
            side = 0 if i < 5 else 1
            rows.append(dict(match=mid, game_id=gid, date=date, event=event, map=mapname, team=teams[side],
                             opp=teams[1 - side], rounds=rounds, win=int(scores[side] > scores[1 - side]),
                             role=ROLE.get(p["agent"], "other"), **p))
    return rows


def main(pages, start=0):
    done = set()
    if os.path.exists(OUT):
        for l in open(OUT, encoding="utf-8"):
            done.add(json.loads(l)["match"])
    f = open(OUT, "a", encoding="utf-8")
    n = 0
    for pg in range(start + 1, start + pages + 1):
        try:
            h = get("https://www.vlr.gg/matches/results/?page=%d" % pg)
        except Exception as e:
            print("page", pg, e); time.sleep(10); continue
        ids = list(dict.fromkeys(re.findall(r'href="/(\d{5,7})/[^"]+"', h)))
        for mid in ids:
            if mid in done:
                continue
            try:
                rows = parse_match(mid)
            except Exception as e:
                print("match", mid, e); time.sleep(3); continue
            for r in rows:
                f.write(json.dumps(r) + "\n")
            done.add(mid)
            n += 1
            time.sleep(0.6)
        f.flush()
        print("page %d: %d matches saved this run" % (pg, n), flush=True)
    print("done", n)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 60, int(sys.argv[2]) if len(sys.argv) > 2 else 0)
