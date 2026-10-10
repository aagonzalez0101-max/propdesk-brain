"""PROP DESK SITE -- page builder. python _site_data.py (data) then python _site_build.py -> site/prop_desk.html"""
import json
d = json.load(open("site/data.json", encoding="utf-8"))
t = open("site/template.html", encoding="utf-8").read()
js = json.dumps(d, separators=(",", ":"), ensure_ascii=False).replace("</", r"<\/")
open("site/prop_desk.html", "w", encoding="utf-8").write(t.replace("/*DATA*/", js, 1))
print("site/prop_desk.html %.0f KB" % (len(js) / 1e3))
