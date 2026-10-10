"""Keep lines_archive/ from filling the disk (2026-10-06, hourly LineWatch snapshots ~1-3 GB/day, 59 GB free).

    python _prune_archive.py [keep_days]     # default 3

Days newer than keep_days: untouched (every hourly snapshot, for the line-move watcher).
Older days: per file prefix (pp_<league>, ud_all, ...) keep only the FIRST and LAST snapshot of the day -- enough for
backtests and opening-vs-closing line moves. Everything else in that day is deleted.
"""
import os, sys, glob, re, datetime, collections

keep = int(sys.argv[1]) if len(sys.argv) > 1 else 3
cut = (datetime.date.today() - datetime.timedelta(days=keep)).isoformat()
freed = n = 0
for day in sorted(os.listdir("lines_archive")):
    if not re.match(r"\d{4}-\d{2}-\d{2}$", day) or day >= cut:
        continue
    by = collections.defaultdict(list)
    for f in glob.glob(os.path.join("lines_archive", day, "*.json")):
        by[re.sub(r"_\d{6}\.json$", "", os.path.basename(f))].append(f)
    for prefix, fs in by.items():
        if prefix == "sharp":
            continue                      # 10/9: hourly sharp snapshots are small (~0.65 MB) and are the CLV record -> keep every one
        fs.sort()
        for f in fs[1:-1]:
            freed += os.path.getsize(f); n += 1
            os.remove(f)
print("pruned %d snapshots, freed %.1f GB (days before %s keep first+last per board)" % (n, freed / 1e9, cut))
