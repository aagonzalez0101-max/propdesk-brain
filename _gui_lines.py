"""Today's CS2 board, both apps side by side -> gui_lines.json (for the Kill Rate Desk page).

    python _gui_lines.py            # price the live board, write gui_lines.json
    python _gui_lines.py --fresh    # re-run the card first so the prices are current

Reads the rows `_cs2_live.py card` already writes to cs2_priced_all.jsonl (every priced side,
not just the picks), keeps the newest run, and pairs each player/stat with BOTH app lines:

  ud   Underdog's line          pp   PrizePicks' line
  mu   our model's mean         p    our chance the UNDER hits at each app's line

Where the two apps post different numbers, "better" says which side of the line is friendlier
and by how much. That is the only free money in this market: same bet, two prices.
The page cannot call the apps itself (the artifact sandbox blocks outside requests), so this
file is the feed -- regenerate it and republish when you want fresh lines.
"""
import json, sys, os, subprocess, collections
import _cs2_live as L

OUT = "gui_lines.json"


def rows_from_last_run(path="cs2_priced_all.jsonl", game="cs2"):
    if not os.path.exists(path):
        return []
    rows = [json.loads(l) for l in open(path, encoding="utf-8")]
    if not rows:
        return []
    last = max(r["ts"] for r in rows)
    out = [r for r in rows if r["ts"] == last]
    for r in out:
        r.setdefault("game", game)
    return out


def build():
    rows = rows_from_last_run() + rows_from_last_run("val_priced_all.jsonl", "val")
    # one entry per player+stat; keep the "lower" side, the page flips it for the over
    best = {}
    for r in rows:
        if r["side"] != "lower":
            continue
        k = (r.get("game", "cs2"), r["match_id"], r["player"], r["kind"], r["maps"])
        if k not in best or r["edge"] > best[k]["edge"]:
            best[k] = r
    out = []
    for r in best.values():
        ud, pp, mu = r["line"], r["pp_line"], r["model_mu"]
        item = dict(game=r.get("game", "cs2"), player=r["player"], team=r["team"], opp=r["opp"], match=r["match"],
                    start=r["start_ct"], kind=r["kind"], maps=r["maps"], mu=round(mu, 2),
                    ud=ud, pp=pp, p_ud=round(r["model_p"], 4), edge=round(r["edge"], 4),
                    winp=round(r["map_winp"], 3), hist=r["n_maps_hist"],
                    zone=bool(L.potd_ok(r)) if r.get("game", "cs2") == "cs2"
                         else bool(0.06 <= r["edge"] < 0.09 and not (0.45 <= r["map_winp"] <= 0.55)),
                    suspect=r.get("suspect"))
        if pp is not None and pp != ud:
            # same model, the other app's number: under is easier on the HIGHER line
            if r.get("game") == "val":
                import _val_model as VM
                item["p_pp"] = round(1 - VM.over(mu, pp), 4)
            else:
                item["p_pp"] = round(1 - L.M.poisson_over(mu, pp), 4)
            item["better"] = "PrizePicks" if pp > ud else "Underdog"
            item["gap"] = round(abs(pp - ud), 1)
        out.append(item)
    out.sort(key=lambda x: (x["start"], -x["edge"]))
    meta = dict(built=max((r["ts"] for r in rows), default=None),
                version=rows[0]["version"] if rows else None, n=len(out),
                cs2=sum(1 for x in out if x["game"] == "cs2"), val=sum(1 for x in out if x["game"] == "val"), zone=sum(1 for x in out if x["zone"]),
                both_apps=sum(1 for x in out if x.get("pp") is not None),
                disagree=sum(1 for x in out if x.get("gap")))
    json.dump(dict(meta=meta, lines=out), open(OUT, "w", encoding="utf-8"), separators=(",", ":"))
    print("%s: %d lines, %d in the good zone, %d posted on both apps, %d where the apps disagree"
          % (OUT, meta["n"], meta["zone"], meta["both_apps"], meta["disagree"]))
    if meta["disagree"]:
        print("\napps disagree on:")
        for x in out:
            if x.get("gap"):
                print("  %-13s %-9s  UD %-5.1f  PP %-5.1f  -> under is better on %s by %.1f"
                      % (x["player"], "headshots" if x["kind"] == "hs" else "kills",
                         x["ud"], x["pp"], x["better"], x["gap"]))


if __name__ == "__main__":
    if "--fresh" in sys.argv:
        subprocess.run([sys.executable, "_cs2_live.py", "card", "0.03", "24"], timeout=2400)
    build()
