"""DATA BUNDLE (2026-10-10): the cloud brain (GitHub repo propdesk-brain) keeps CODE in git and DATA in one release asset,
so the laptop and the cloud run on the same ledgers/models/databases.

    python _bundle.py size              # what would go in, and how big
    python _bundle.py pack  out.tar.gz  # build the bundle
    python _bundle.py unpack in.tar.gz  # restore it over this folder
    python _bundle.py push              # laptop -> GitHub release 'data' (refuses if the cloud copy changed since your last pull)
    python _bundle.py pull              # GitHub release 'data' -> laptop

IN:  every data file in this folder + small data folders + TODAY's raw PP/sharp snapshots (lines.db holds the history).
OUT: code (git), secrets (.env, notify.json), logs, the old raw archive, legacy data/, backtest-only caches (_euro, _nbl), and the
     big refetchable caches (_fotmob, _img_cache, _site_cache) -- the cloud keeps those in its own Actions cache.
"""
import os, sys, json, tarfile, datetime, subprocess, urllib.request, urllib.error

REPO = "aagonzalez0101-max/propdesk-brain"
TAG, ASSET = "data", "bundle.tar.gz"
SKIP_DIRS = {"lines_archive", "data", "_fotmob", "_img_cache", "_site_cache", "_euro", "_nbl", "_archive_old", "_archive_2026-09",
             ".claude", "__pycache__", ".git", ".github", "betting", "_bundle_tmp", "graphify-out"}
SKIP_EXT = {".py", ".log", ".out", ".vtt", ".cmd", ".sh", ".md"}
SKIP_FILES = {".env", "notify.json", ".gitignore", "requirements.txt", ASSET, "_bundle_state.json"}
STATE = "_bundle_state.json"


def members():
    out = []
    for f in os.listdir("."):
        if os.path.isfile(f):
            if f in SKIP_FILES or os.path.splitext(f)[1] in SKIP_EXT or ".bak" in f:
                continue
            out.append(f)
        elif os.path.isdir(f) and f not in SKIP_DIRS:
            for r, ds, fs in os.walk(f):
                ds[:] = [d for d in ds if d != "__pycache__"]
                out += [os.path.join(r, x) for x in fs if os.path.splitext(x)[1] not in (".py", ".pyc")]
    today = datetime.date.today()
    for d in (today,):                     # older raw days live on in lines.db (pack() compacts first)
        p = os.path.join("lines_archive", d.isoformat())
        if os.path.isdir(p):
            out += [os.path.join(p, x) for x in os.listdir(p) if x.startswith(("pp_", "sharp_"))]
    return out


def pack(path):
    # fold every raw snapshot into lines.db first (incremental; 99 = gzip nothing), so dropping yesterday's raw files loses nothing
    subprocess.run([sys.executable, "_archive_compact.py", "99"], check=False)
    M = members()
    with tarfile.open(path, "w:gz", compresslevel=6) as t:
        for f in M:
            t.add(f)
    print("packed %d files -> %s (%.0f MB)" % (len(M), path, os.path.getsize(path) / 1e6))


def unpack(path):
    with tarfile.open(path, "r:gz") as t:
        bad = [m.name for m in t.getmembers() if m.name.startswith(("/", "..")) or ".." in m.name.split("/")]
        if bad:
            raise SystemExit("refusing: unsafe paths in bundle %s" % bad[:3])
        t.extractall(".", filter="data")
    print("unpacked", path)


def token():
    t = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if t:
        return t
    out = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n", capture_output=True, text=True).stdout
    return dict(l.split("=", 1) for l in out.splitlines() if "=" in l).get("password")


def api(url, method="GET", data=None, ctype="application/json", raw=False):
    h = {"Authorization": "Bearer " + token(), "Accept": "application/vnd.github+json", "User-Agent": "propdesk"}
    if data is not None:
        h["Content-Type"] = ctype
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=1800)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    b = r.read()
    return b if raw else (json.loads(b) if b else {})


def release():
    try:
        rel = api("https://api.github.com/repos/%s/releases/tags/%s" % (REPO, TAG))
    except Exception:
        rel = None
    if rel is None and not os.environ.get("GH_TOKEN"):   # no login available: read the public release anonymously
        rel = json.loads(urllib.request.urlopen(urllib.request.Request("https://api.github.com/repos/%s/releases/tags/%s" % (REPO, TAG),
                                                                       headers={"User-Agent": "propdesk"}), timeout=60).read())
        return rel
    if rel is None:
        rel = api("https://api.github.com/repos/%s/releases" % REPO, "POST",
                  json.dumps({"tag_name": TAG, "name": "data bundle", "body": "PropDesk data -- written by _bundle.py, do not edit by hand"}).encode())
    return rel


def remote_asset(rel):
    return next((a for a in rel.get("assets", []) if a["name"] == ASSET), None)


LAPTOP_OWNED = ("live_paper.jsonl", "road.json")   # bets are logged on the laptop (in chat); the cloud never writes these


def download(a, path):
    tok = None
    try:
        tok = token()
    except Exception:
        tok = None
    if tok:
        req = urllib.request.Request(a["url"], headers={"Authorization": "Bearer " + tok, "Accept": "application/octet-stream", "User-Agent": "propdesk"})
    else:                                                    # 10/10: public repo -> a cloud/phone session can pull without any login
        req = urllib.request.Request(a["browser_download_url"], headers={"User-Agent": "propdesk"})
    with urllib.request.urlopen(req, timeout=1800) as r, open(path, "wb") as f:
        while True:
            c = r.read(1 << 20)
            if not c:
                break
            f.write(c)


def merge_ledger(local_txt, remote_txt):
    """10/11: laptop and cloud both write live_paper.jsonl (laptop logs bets, cloud grades them). Union by (ts, selection); when both
    sides have a row, keep the one with the result filled (graded beats pending); else the local copy."""
    def rows(t):
        out = {}
        for l in t.splitlines():
            if l.strip():
                r = json.loads(l)
                out[(r.get("ts"), r.get("selection"))] = r
        return out
    L, R = rows(local_txt), rows(remote_txt)
    for k, r in R.items():
        if k not in L or (L[k].get("result") is None and r.get("result") is not None):
            L[k] = r
    NL = chr(10)
    return NL.join(json.dumps(r, ensure_ascii=False) for r in sorted(L.values(), key=lambda r: r.get("ts") or "")) + NL


# 10/11: paper files are written on BOTH sides too (laptop logs, cloud grades) -> row-merge them like the ledger, never overwrite.
# key = what makes a row unique; a graded row beats an ungraded one.
MERGE_KEYS = {
    "paper_slips.jsonl": lambda r: (r.get("sig"), (r.get("logged") or "")[:10]),
    "gate_drops.jsonl": lambda r: (r.get("date"), r.get("sport"), r.get("player"), r.get("stat"), r.get("line"), r.get("model_side")),
    "nfl_beta_paper.jsonl": lambda r: (r.get("date") or r.get("logged"), r.get("player"), r.get("stat"), r.get("line"), r.get("side")),
}


def merge_rows(local_txt, remote_txt, key):
    out = {}
    for t in (local_txt, remote_txt):
        for l in t.splitlines():
            if l.strip():
                r = json.loads(l); k = key(r)
                if k not in out or (out[k].get("result") is None and r.get("result") is not None):
                    out[k] = r
    NL = chr(10)
    return NL.join(json.dumps(r, ensure_ascii=False) for r in out.values()) + NL


def push(force=False, cloud=False, _retry=True):
    rel = release(); a = remote_asset(rel)
    st = json.load(open(STATE)) if os.path.exists(STATE) else {}
    changed = a and st.get("pulled_updated") and a["updated_at"] != st["pulled_updated"]
    if changed and not force:
        # someone else uploaded since our last sync -> merge instead of refusing or overwriting
        download(a, "_remote.tar.gz")
        with tarfile.open("_remote.tar.gz", "r:gz") as t:
            for m in t.getmembers():
                if m.name == "live_paper.jsonl":
                    remote = t.extractfile(m).read().decode("utf-8")
                    local = open("live_paper.jsonl", encoding="utf-8").read() if os.path.exists("live_paper.jsonl") else ""
                    open("live_paper.jsonl", "w", encoding="utf-8").write(merge_ledger(local, remote))
                elif m.name in MERGE_KEYS:
                    remote = t.extractfile(m).read().decode("utf-8")
                    local = open(m.name, encoding="utf-8").read() if os.path.exists(m.name) else ""
                    open(m.name, "w", encoding="utf-8").write(merge_rows(local, remote, MERGE_KEYS[m.name]))
                elif m.name == "road.json":
                    if cloud:                                       # the laptop owns road.json
                        t.extract(m, ".", filter="data")
                elif not cloud:                                     # laptop push: everything else = the cloud's newer copy
                    t.extract(m, ".", filter="data")
        os.remove("_remote.tar.gz")
        print("merged with the newer remote bundle (%s): bet ledger row-merged" % a["updated_at"])
    pack(ASSET)
    if a:
        api("https://api.github.com/repos/%s/releases/assets/%d" % (REPO, a["id"]), "DELETE")
    up = rel["upload_url"].split("{")[0] + "?name=" + ASSET
    try:
        res = api(up, "POST", open(ASSET, "rb").read(), "application/gzip")
    except urllib.error.HTTPError as e:                          # 422 = the other side re-uploaded the asset in the same moment
        print("upload rejected (%s)" % e.code); res = None
    os.remove(ASSET)
    if not res and _retry:                                       # the other side uploaded at the same moment -> merge again once
        print("upload collided -- retrying with a fresh merge")
        return push(force, cloud, _retry=False)
    json.dump({"pulled_updated": res["updated_at"]}, open(STATE, "w"))
    print("pushed bundle (%s)" % res["updated_at"])


def pull():
    rel = release(); a = remote_asset(rel)
    if not a:
        raise SystemExit("no bundle in the release yet")
    download(a, ASSET)
    # 10/11: a pull overwrote a paper slip logged locally minutes earlier -> keep local rows, merge them back in after unpacking
    keep = {f: open(f, encoding="utf-8").read() for f in ["live_paper.jsonl"] + list(MERGE_KEYS) if os.path.exists(f)}
    unpack(ASSET); os.remove(ASSET)
    for f, local in keep.items():
        remote = open(f, encoding="utf-8").read() if os.path.exists(f) else ""
        open(f, "w", encoding="utf-8").write(merge_ledger(local, remote) if f == "live_paper.jsonl" else merge_rows(local, remote, MERGE_KEYS[f]))
    json.dump({"pulled_updated": a["updated_at"]}, open(STATE, "w"))
    print("pulled bundle (%s), ledger + paper files row-merged" % a["updated_at"])


COLD = ("_fotmob", "_img_cache", "_site_cache")      # big refetchable caches: seeded once, then kept in the cloud's Actions cache


def cold_push():
    rel = release()
    with tarfile.open("cold.tar.gz", "w:gz", compresslevel=6) as t:
        for d in COLD:
            if os.path.isdir(d):
                t.add(d)
    a = next((x for x in rel.get("assets", []) if x["name"] == "cold.tar.gz"), None)
    if a:
        api("https://api.github.com/repos/%s/releases/assets/%d" % (REPO, a["id"]), "DELETE")
    api(rel["upload_url"].split("{")[0] + "?name=cold.tar.gz", "POST", open("cold.tar.gz", "rb").read(), "application/gzip")
    print("cold caches pushed (%.0f MB)" % (os.path.getsize("cold.tar.gz") / 1e6)); os.remove("cold.tar.gz")


def cold_pull():
    a = next((x for x in release().get("assets", []) if x["name"] == "cold.tar.gz"), None)
    if not a:
        print("no cold caches in the release"); return
    download(a, "cold.tar.gz"); unpack("cold.tar.gz"); os.remove("cold.tar.gz")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "size"
    if cmd == "size":
        M = members(); tot = sum(os.path.getsize(f) for f in M)
        big = sorted(((os.path.getsize(f), f) for f in M), reverse=True)[:12]
        print("%d files, %.0f MB raw" % (len(M), tot / 1e6))
        for s, f in big:
            print("  %6.0f MB  %s" % (s / 1e6, f))
    elif cmd == "pack":
        pack(sys.argv[2] if len(sys.argv) > 2 else ASSET)
    elif cmd == "unpack":
        unpack(sys.argv[2] if len(sys.argv) > 2 else ASSET)
    elif cmd == "push":
        push(force="--force" in sys.argv, cloud="--cloud" in sys.argv)
    elif cmd == "pull":
        pull()
    elif cmd == "cold-push":
        cold_push()
    elif cmd == "cold-pull":
        cold_pull()
