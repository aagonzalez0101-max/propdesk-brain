"""Load tennis-data.co.uk match files into a neutral, model-ready frame.

THE LABELLING TRAP: every row is stored as Winner/Loser, so a naive frame has
the answer baked into the column names -- any model trained on "player A" would
score 100% by learning that column A always wins. Every match here is therefore
re-keyed to a NEUTRAL ordering (alphabetical by name), with `y` = 1 when p1 won
and the odds swapped to match. Nothing downstream ever sees Winner/Loser.

Odds priority is Pinnacle -> market average -> Bet365. Pinnacle is the sharpest
of the three and is the right benchmark for an encompassing test; the others
fill gaps in the older files.
"""
from __future__ import annotations

import glob
import os

import pandas as pd

DIR = "tennis"


def _num(x):
    try:
        v = float(x)
        return v if v > 1.0 else None
    except (TypeError, ValueError):
        return None


def load(tour: str | None = None) -> pd.DataFrame:
    rows = []
    for fn in sorted(glob.glob(os.path.join(DIR, "*.xls*"))):
        base = os.path.basename(fn)
        t = base.split("_")[0]
        if tour and t != tour:
            continue
        try:
            d = pd.read_excel(fn)
        except Exception as exc:
            print("  skip %s (%s)" % (base, str(exc)[:40]))
            continue
        d.columns = [str(c).strip() for c in d.columns]
        d["tour"] = t
        rows.append(d)
    if not rows:
        return pd.DataFrame()
    df = pd.concat(rows, ignore_index=True, sort=False)

    keep = ["Date", "Location", "Tournament", "Series", "Court", "Surface",
            "Round", "Best of", "Winner", "Loser", "WRank", "LRank",
            "WPts", "LPts", "Wsets", "Lsets", "Comment", "tour"]
    for c in keep:
        if c not in df.columns:
            df[c] = None
    for c in ["W1", "L1", "W2", "L2", "W3", "L3", "W4", "L4", "W5", "L5"]:
        if c not in df.columns:
            df[c] = None

    df = df[df["Winner"].notna() & df["Loser"].notna()].copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df[df["Date"].notna()].sort_values("Date").reset_index(drop=True)

    # ---- odds: prefer Pinnacle, then market average, then Bet365 ----
    def pick(row, w_cols, l_cols):
        for wc, lc in zip(w_cols, l_cols):
            a, b = _num(row.get(wc)), _num(row.get(lc))
            if a and b:
                return a, b
        return None, None

    ow, ol, src = [], [], []
    for _, r in df.iterrows():
        a, b = pick(r, ["PSW", "AvgW", "B365W", "MaxW"], ["PSL", "AvgL", "B365L", "MaxL"])
        ow.append(a)
        ol.append(b)
        src.append("PS" if _num(r.get("PSW")) and _num(r.get("PSL")) else
                   ("Avg" if _num(r.get("AvgW")) and _num(r.get("AvgL")) else
                    ("B365" if _num(r.get("B365W")) and _num(r.get("B365L")) else None)))
    df["odds_w"], df["odds_l"], df["odds_src"] = ow, ol, src

    # ---- total games, from the set scores ----
    gcols = [("W1", "L1"), ("W2", "L2"), ("W3", "L3"), ("W4", "L4"), ("W5", "L5")]
    tot = []
    for _, r in df.iterrows():
        s = 0
        okay = True
        for a, b in gcols:
            x, y = r.get(a), r.get(b)
            if pd.isna(x) or pd.isna(y):
                continue
            try:
                s += int(x) + int(y)
            except (TypeError, ValueError):
                okay = False
        tot.append(s if okay and s > 0 else None)
    df["total_games"] = tot

    # ---- NEUTRAL re-key: p1 is simply the alphabetically first name ----
    out = pd.DataFrame({
        "date": df["Date"], "tour": df["tour"], "surface": df["Surface"],
        "court": df["Court"], "series": df["Series"], "round": df["Round"],
        "best_of": pd.to_numeric(df["Best of"], errors="coerce"),
        "tournament": df["Tournament"], "comment": df["Comment"],
        "total_games": df["total_games"], "odds_src": df["odds_src"],
    })
    # --- first set and sets played, the two other markets we care about ---
    # W1/L1 are games won in set ONE by the match winner / loser, so the set-1
    # winner has to be resolved BEFORE the neutral re-key, then swapped with it.
    w1 = pd.to_numeric(df["W1"], errors="coerce")
    l1 = pd.to_numeric(df["L1"], errors="coerce")
    ws = pd.to_numeric(df["Wsets"], errors="coerce")
    ls = pd.to_numeric(df["Lsets"], errors="coerce")
    out["total_sets"] = ws + ls
    # did the eventual match winner take the opening set?
    # keep this as a NULLABLE BOOLEAN, never object dtype -- see the note below
    out["_winner_took_s1"] = (w1 > l1).astype("boolean").mask(
        w1.isna() | l1.isna(), pd.NA)
    w = df["Winner"].astype(str).str.strip()
    l = df["Loser"].astype(str).str.strip()
    p1_is_winner = w < l                      # alphabetical, independent of outcome
    out["p1"] = w.where(p1_is_winner, l)
    out["p2"] = l.where(p1_is_winner, w)
    out["y"] = p1_is_winner.astype(int)
    wr = pd.to_numeric(df["WRank"], errors="coerce")
    lr = pd.to_numeric(df["LRank"], errors="coerce")
    out["rank1"] = wr.where(p1_is_winner, lr)
    out["rank2"] = lr.where(p1_is_winner, wr)
    wp = pd.to_numeric(df["WPts"], errors="coerce")
    lp = pd.to_numeric(df["LPts"], errors="coerce")
    out["pts1"] = wp.where(p1_is_winner, lp)
    out["pts2"] = lp.where(p1_is_winner, wp)
    # set-1 winner in NEUTRAL terms: p1 took set 1 if (p1 won and won set 1)
    # or (p1 lost but still took the opener)
    # p1 took set 1 exactly when "p1 won the match" agrees with "the winner took
    # set 1" -- i.e. XNOR, which is just equality on two booleans.
    #
    # Do NOT write this with `~` unless both sides are real booleans. An
    # object-dtype series negates BITWISE: ~True is -2 and ~False is -1, and
    # both are truthy, so the expression silently collapses to always-true. That
    # produced p1_takes_set1 = 0.906 instead of ~0.50 and would have handed the
    # model a column that already knew the answer.
    s1 = out["_winner_took_s1"]
    p1w = pd.Series(p1_is_winner, index=out.index).astype("boolean")
    out["set1_p1"] = (p1w == s1).astype("boolean").mask(s1.isna(), pd.NA)
    out = out.drop(columns=["_winner_took_s1"])
    ow_s = pd.to_numeric(df["odds_w"], errors="coerce")
    ol_s = pd.to_numeric(df["odds_l"], errors="coerce")
    out["odds1"] = ow_s.where(p1_is_winner, ol_s)
    out["odds2"] = ol_s.where(p1_is_winner, ow_s)
    # de-vigged market probability for p1
    inv1, inv2 = 1.0 / out["odds1"], 1.0 / out["odds2"]
    out["mktp"] = inv1 / (inv1 + inv2)
    # Guard against the same match arriving twice -- an earlier manual download
    # left 2026m.xls alongside atp_2026.xls and silently duplicated 9,120 rows,
    # which would have inflated every sample count and double-weighted recent
    # seasons in any walk-forward fit.
    before = len(out)
    out = out.drop_duplicates(subset=["date", "p1", "p2", "tour"])
    if before != len(out):
        print("  dropped %d duplicate matches" % (before - len(out)))
    return out.reset_index(drop=True)


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", write_through=True)
    d = load()
    print("%d matches  %s .. %s" % (len(d), d["date"].min().date(), d["date"].max().date()))
    print("tours:", d["tour"].value_counts().to_dict())
    print("with market odds: %d (%.1f%%)" % (d["mktp"].notna().sum(),
                                             100 * d["mktp"].notna().mean()))
    print("odds source:", d["odds_src"].value_counts().to_dict())
    print("surfaces:", d["surface"].value_counts().to_dict())
    print("p1 win rate: %.4f  (must be ~0.50 -- if not, the re-key leaked)"
          % d["y"].mean())
    print("total_games present: %d (%.1f%%)" % (d["total_games"].notna().sum(),
                                                100 * d["total_games"].notna().mean()))
    print("total_sets present : %d  distribution %s"
          % (d["total_sets"].notna().sum(),
             d["total_sets"].value_counts().sort_index().to_dict()))
    s1 = d["set1_p1"].dropna().astype(bool)
    print("set1 present       : %d  p1 takes set1 %.4f (must be ~0.50)"
          % (len(s1), s1.mean()))
    bo3 = d[(d["best_of"] == 3) & d["total_sets"].notna()]
    print("Bo3 straight sets  : %.1f%% of %d"
          % (100 * (bo3["total_sets"] == 2).mean(), len(bo3)))
    d.to_pickle("tennis_all.pkl")
    print("saved tennis_all.pkl")
