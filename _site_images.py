"""PROP DESK -- player photos + Valorant agent art, shrunk and packed into site/img.json (2026-09-30).
The page can't load images from other sites (sandbox), so every image ships with it as a small WebP data URI.

    python _site_images.py          # players with lines tonight + every Valorant agent; cached in _img_cache/

Sources (free, no key): ESPN (WNBA/NBA), mlbstatic (MLB), NHL api landing headshot, nflverse headshot_url (NFL),
FotMob (soccer), vlr.gg player photo (Valorant), bo3.gg player image (CS2), valorant-api.com (agents).
"""
import os, io, re, json, base64, hashlib, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from PIL import Image

CACHE = "_img_cache"
os.makedirs(CACHE, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
      "Accept": "image/avif,image/webp,image/png,*/*"}


def fetch(url, referer=None):
    f = os.path.join(CACHE, hashlib.md5(url.encode()).hexdigest())
    if os.path.exists(f):
        b = open(f, "rb").read()
        return b or None
    h = dict(UA)
    if referer:
        h["Referer"] = referer
    try:
        b = urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=25).read()
    except Exception:
        b = b""
    open(f, "wb").write(b)
    return b or None


def getj(url):
    b = fetch(url)
    try:
        return json.loads(b) if b else None
    except ValueError:
        return None


def gettext(url):
    b = fetch(url)
    return b.decode("utf-8", "replace") if b else ""


def shrink(b, size=160, square=True, h=None, q=78):
    try:
        im = Image.open(io.BytesIO(b)).convert("RGBA")
    except Exception:
        return None
    if h:                                   # portrait art: fixed height
        w = round(im.width * h / im.height)
        im = im.resize((w, h), Image.LANCZOS)
    else:
        if square:                          # crop to a square from the top (faces sit high)
            s = min(im.width, im.height)
            left = (im.width - s) // 2
            im = im.crop((left, 0, left + s, s))
        im.thumbnail((size, size), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "WEBP", quality=q, method=5)
    return "data:image/webp;base64," + base64.b64encode(out.getvalue()).decode()


def url_for(sp, P):
    pid = P.get("pid")
    if sp == "WNBA":
        return "https://a.espncdn.com/i/headshots/wnba/players/full/%s.png" % pid, None
    if sp == "NBA":
        return "https://a.espncdn.com/i/headshots/nba/players/full/%s.png" % pid, None
    if sp == "MLB":
        return "https://img.mlbstatic.com/mlb-photos/image/upload/w_240,q_auto:best/v1/people/%s/headshot/67/current" % pid, None
    if sp == "NHL":
        d = getj("https://api-web.nhle.com/v1/player/%s/landing" % pid) or {}
        return d.get("headshot"), None
    if sp == "NFL":
        return P.get("img"), None
    if sp == "CFB":
        return "https://a.espncdn.com/i/headshots/college-football/players/full/%s.png" % pid, None
    if sp == "SOCCER":
        return "https://images.fotmob.com/image_resources/playerimages/%s.png" % pid, "https://www.fotmob.com/"
    if sp == "VAL":
        h = gettext("https://www.vlr.gg/player/%s" % pid)
        m = re.search(r'class="wf-avatar mod-player"[\s\S]{0,400}?<img src="([^"]+)"', h)
        if m and "sil.png" not in m.group(1):
            u = m.group(1)
            return ("https:" + u if u.startswith("//") else "https://www.vlr.gg" + u if u.startswith("/") else u), "https://www.vlr.gg/"
        return None, None
    if sp == "CS2":
        q = urllib.parse.quote(P["name"].lower())
        d = getj("https://api.bo3.gg/api/v1/players?filter[slug][eq]=%s" % q) or {}      # slug filter; nickname filter is ignored
        for r in d.get("results") or []:
            if (r.get("nickname") or "").lower() == P["name"].lower():
                v = r.get("image_versions") or {}
                return v.get("400x400") or v.get("webp") or r.get("image_url"), None
        return None, None
    return None, None


def one(job):
    sp, P = job
    try:
        u, ref = url_for(sp, P)
    except Exception:
        u, ref = None, None
    if not u:
        return sp, P["id"], None
    b = fetch(u, ref)
    return sp, P["id"], shrink(b) if b else None


def agents():
    d = getj("https://valorant-api.com/v1/agents?isPlayableCharacter=true") or {}
    out = {}
    for a in d.get("data") or []:
        name = a["displayName"].lower().replace("/", "")
        icon = fetch(a.get("displayIcon")) if a.get("displayIcon") else None
        art = fetch(a.get("fullPortrait")) if a.get("fullPortrait") else None
        out[name] = dict(name=a["displayName"], role=(a.get("role") or {}).get("displayName"),
                         colors=["#" + c[:6] for c in (a.get("backgroundGradientColors") or [])],
                         icon=shrink(icon, 112) if icon else None, art=shrink(art, h=420, q=72) if art else None)
    if "kayo" in out:
        out["kay/o"] = out["kayo"]
    return out


if __name__ == "__main__":
    D = json.load(open(os.path.join("site", "players.json"), encoding="utf-8"))
    jobs = [(sp, P) for sp in ("WNBA", "MLB", "NHL", "NFL", "CFB", "SOCCER", "VAL", "NBA") if sp in D and D[sp].get("players")
            for P in D[sp]["players"].values()]
    print("%d players" % len(jobs), flush=True)
    out = {"players": {}, "agents": {}}
    with ThreadPoolExecutor(8) as ex:
        for sp, pid, uri in ex.map(one, jobs):
            if uri:
                out["players"].setdefault(sp, {})[pid] = uri
    out["agents"] = agents()
    got = {sp: len(v) for sp, v in out["players"].items()}
    print("photos:", got, " agents:", len(out["agents"]))
    json.dump(out, open(os.path.join("site", "img.json"), "w", encoding="utf-8"), separators=(",", ":"))
    print("site/img.json %.0f KB" % (os.path.getsize(os.path.join("site", "img.json")) / 1e3))
