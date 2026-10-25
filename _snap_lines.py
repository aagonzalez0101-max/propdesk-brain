"""Snapshot every PrizePicks + Underdog board we might bet into lines_archive/ (2026-09-30).
    python _snap_lines.py     # run 2-3x a day (morning, afternoon, just before lock)
PP leagues: NHL 8, SOCCER 82, WNBA 3, NBA 7, NFL 9, MLB 2, CS2 265, VAL 159.
PP's partner-api 429s under ~25s spacing: 30s between calls, failed leagues retried once after 60s."""
import time, _props as P
P.underdog("NHL")
todo = [8, 82, 3, 7, 9, 2, 265, 159, 121, 174, 237, 192, 84, 245, 35, 80]   # 10/24: + NBA2H 80   # + LoL 121, Dota2 174; 10/12: NBAP 237, NBA1Q 192, NBA1H 84, NFL1Q 245, NFL1H 35 (user: preseason 1Q/1H)
for attempt in range(2):
    failed = []
    for lid in todo:
        try:
            P.prizepicks(lid, max_age=0); print("pp", lid, "ok")
        except Exception as e:
            print("pp", lid, "failed:", e); failed.append(lid)
        time.sleep(30)
    if not failed:
        break
    todo = failed; time.sleep(60)
