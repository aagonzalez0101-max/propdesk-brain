"""Pull today's 2eZ + Fantasy Aces videos every day (user 10/3: "why haven't you checked 2eZ or Fantasy Aces?").

    python _cappers.py [YYYY-MM-DD]   # RSS -> today's video ids -> transcripts -> capper_<name>_<date>.txt

Every sport, paused or not. The claims still get verified by hand against statsapi/nflverse + priced vs Pinnacle
(memory: reference_capper_channels). Free: YouTube RSS + youtube-transcript-api.
"""
import sys, re, datetime, urllib.request
CT = datetime.timezone(datetime.timedelta(hours=-5))
CH = {"2ez": "UCSffCjZtU0bmws1QspHs74Q", "aces": "UCRmEURDsXteG8V-LG_fG_Fg"}

day = next((a for a in sys.argv[1:] if len(a) == 10), datetime.datetime.now(CT).date().isoformat())
from youtube_transcript_api import YouTubeTranscriptApi
api = YouTubeTranscriptApi()
for name, cid in CH.items():
    x = ""
    for k in range(4):                                     # YouTube RSS 404s intermittently (10/3 21:00) -> retry
        try:
            x = urllib.request.urlopen("https://www.youtube.com/feeds/videos.xml?channel_id=" + cid, timeout=30).read().decode("utf-8"); break
        except Exception as e:
            print(name, "rss try", k + 1, e); __import__("time").sleep(10 * (k + 1))
    vids = [(v, t) for v, t, p in re.findall(r"<yt:videoId>(.*?)</yt:videoId>.*?<title>(.*?)</title>.*?<published>(.*?)</published>", x, re.S)
            if datetime.datetime.fromisoformat(p).astimezone(CT).date().isoformat() == day]
    for i, (v, t) in enumerate(vids):
        try:
            txt = " ".join(s.text for s in api.fetch(v, languages=["en"]))
        except Exception as e:
            print(name, v, "no transcript yet:", e); continue
        fn = "capper_%s_%s%s.txt" % (name, day.replace("-", ""), "" if i == 0 else "_%d" % i)
        open(fn, "w", encoding="utf-8").write(t + "\n\n" + txt)
        print(name, v, len(txt), "chars ->", fn, "|", t.encode("ascii", "ignore").decode())
    if not vids:
        print(name, "no video yet for", day)
