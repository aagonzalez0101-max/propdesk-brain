"""PROP DESK v2 page: python _site_players.py (data) then python _site_build2.py -> site/prop_desk.html (same artifact URL)."""
import json, os, subprocess as _sp
_sp.run(["python", "_site_meta.py"])
d = json.load(open("site/players.json", encoding="utf-8"))
if os.path.exists("site/meta.json"):
    d["_meta"] = json.load(open("site/meta.json", encoding="utf-8"))
PAUSED = {"MLB"}                 # sports off the board (user 2026-10-02: MLB paused for the playoffs)
for k in PAUSED:
    d.pop(k, None)
t = open("site/desk_template.html", encoding="utf-8").read()
js = json.dumps(d, separators=(",", ":"), ensure_ascii=False).replace("</", r"<\/")
open("site/prop_desk.html", "w", encoding="utf-8").write(t.replace("/*PLAYERS*/", js, 1))
print("site/prop_desk.html %.0f KB" % (len(js) / 1e3))
import subprocess
subprocess.run(["python", "_site_grade.py", "log"])          # every Bet / Lean the page shows gets logged for grading
