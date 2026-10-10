"""
Bet log, bankroll, and prediction archive.

Two things this schema does that the old one didn't, and that matter more
than anything else here:

1. Every bet records the MODEL PROBABILITY and the price at the time. Without
   that you can never tell a good bet from a lucky one, and you can never
   find out which market your edge actually lives in.

2. Every bet records closing line value. Over any sample you can realistically
   collect in a season, win/loss record is mostly noise -- CLV is not. If you
   are consistently beating the closing line you will make money eventually,
   even through a losing month. If you aren't, no hot streak means anything.

The predictions table archives what the model said BEFORE each game, so the
model can be scored honestly later without look-ahead bias.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "bets.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS bets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    placed_at     TEXT NOT NULL,
    event_date    TEXT NOT NULL,
    sport         TEXT NOT NULL,
    event         TEXT NOT NULL,
    market        TEXT NOT NULL,          -- 'F5 ML', 'K prop', 'Total', ...
    selection     TEXT NOT NULL,
    point         REAL,
    book          TEXT NOT NULL DEFAULT 'novig',
    odds          REAL NOT NULL,          -- price actually taken
    stake         REAL NOT NULL,
    model_prob    REAL,                   -- what we thought
    market_prob   REAL,                   -- de-vigged market at bet time
    ev_pct        REAL,
    edge_pp       REAL,
    closing_odds  REAL,                   -- filled in later
    clv_pp        REAL,
    result        TEXT DEFAULT 'pending', -- pending|win|loss|push|void
    payout        REAL DEFAULT 0.0,
    pnl           REAL DEFAULT 0.0,
    notes         TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS bankroll (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    at         TEXT NOT NULL,
    amount     REAL NOT NULL,             -- signed: deposits +, withdrawals -
    platform   TEXT DEFAULT 'novig',
    note       TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS predictions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    made_at     TEXT NOT NULL,
    event_date  TEXT NOT NULL,
    sport       TEXT NOT NULL,
    event       TEXT NOT NULL,
    market      TEXT NOT NULL,
    selection   TEXT NOT NULL,
    point       REAL,
    model_prob  REAL NOT NULL,
    market_prob REAL,
    best_price  REAL,
    result      TEXT DEFAULT 'pending',
    UNIQUE(event_date, event, market, selection, point)
);

CREATE TABLE IF NOT EXISTS line_snapshots (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    at         TEXT NOT NULL,
    sport      TEXT NOT NULL,
    event      TEXT NOT NULL,
    market     TEXT NOT NULL,
    selection  TEXT NOT NULL,
    point      REAL,
    book       TEXT NOT NULL,
    price      REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bets_date ON bets(event_date);
CREATE INDEX IF NOT EXISTS idx_snap ON line_snapshots(sport, event, market);
"""


def conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with conn() as c:
        c.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ bankroll

def deposit(amount: float, platform: str = "novig", note: str = "") -> None:
    with conn() as c:
        c.execute("INSERT INTO bankroll (at, amount, platform, note) VALUES (?,?,?,?)",
                  (_now(), amount, platform, note))


def bankroll() -> float:
    """Deposits/withdrawals plus realised P&L, minus money on pending bets."""
    with conn() as c:
        dep = c.execute("SELECT COALESCE(SUM(amount),0) FROM bankroll").fetchone()[0]
        pnl = c.execute(
            "SELECT COALESCE(SUM(pnl),0) FROM bets WHERE result IN ('win','loss','push','void')"
        ).fetchone()[0]
        pend = c.execute(
            "SELECT COALESCE(SUM(stake),0) FROM bets WHERE result='pending'"
        ).fetchone()[0]
    return dep + pnl - pend


def bankroll_total() -> float:
    """Bankroll including money currently at risk."""
    with conn() as c:
        pend = c.execute(
            "SELECT COALESCE(SUM(stake),0) FROM bets WHERE result='pending'"
        ).fetchone()[0]
    return bankroll() + pend


# ---------------------------------------------------------------------- bets

def log_bet(event_date: str, sport: str, event: str, market: str,
            selection: str, odds: float, stake: float,
            point: float | None = None, book: str = "novig",
            model_prob: float | None = None, market_prob: float | None = None,
            ev_pct: float | None = None, edge_pp: float | None = None,
            notes: str = "") -> int:
    with conn() as c:
        cur = c.execute(
            """INSERT INTO bets (placed_at, event_date, sport, event, market,
               selection, point, book, odds, stake, model_prob, market_prob,
               ev_pct, edge_pp, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (_now(), event_date, sport, event, market, selection, point, book,
             odds, stake, model_prob, market_prob, ev_pct, edge_pp, notes))
        return cur.lastrowid


def settle(bet_id: int, result: str) -> float:
    """Settle a bet and return the P&L."""
    from .oddsmath import american_to_decimal

    with conn() as c:
        row = c.execute("SELECT * FROM bets WHERE id=?", (bet_id,)).fetchone()
        if row is None:
            raise ValueError(f"No bet with id {bet_id}")
        stake, odds = row["stake"], row["odds"]
        if result == "win":
            payout = stake * american_to_decimal(odds)
            pnl = payout - stake
        elif result == "loss":
            payout, pnl = 0.0, -stake
        elif result in ("push", "void"):
            payout, pnl = stake, 0.0
        else:
            raise ValueError(f"Bad result: {result}")
        c.execute("UPDATE bets SET result=?, payout=?, pnl=? WHERE id=?",
                  (result, payout, pnl, bet_id))
    return pnl


def record_closing(bet_id: int, closing_odds: float) -> float:
    """Attach the closing line to a bet and compute CLV."""
    from .oddsmath import clv as clv_calc

    with conn() as c:
        row = c.execute("SELECT odds FROM bets WHERE id=?", (bet_id,)).fetchone()
        if row is None:
            raise ValueError(f"No bet with id {bet_id}")
        v = clv_calc(row["odds"], closing_odds)
        c.execute("UPDATE bets SET closing_odds=?, clv_pp=? WHERE id=?",
                  (closing_odds, v, bet_id))
    return v


def pending() -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute(
            "SELECT * FROM bets WHERE result='pending' ORDER BY event_date, id"
        ).fetchall()


def recent(n: int = 25) -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute("SELECT * FROM bets ORDER BY id DESC LIMIT ?", (n,)).fetchall()


# --------------------------------------------------------------- predictions

def log_prediction(event_date: str, sport: str, event: str, market: str,
                   selection: str, model_prob: float,
                   point: float | None = None,
                   market_prob: float | None = None,
                   best_price: float | None = None) -> None:
    """Archive a pre-game prediction. Idempotent per (date, event, market, sel)."""
    with conn() as c:
        c.execute(
            """INSERT OR REPLACE INTO predictions
               (made_at, event_date, sport, event, market, selection, point,
                model_prob, market_prob, best_price)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (_now(), event_date, sport, event, market, selection, point,
             model_prob, market_prob, best_price))


def snapshot_line(sport: str, event: str, market: str, selection: str,
                  book: str, price: float, point: float | None = None) -> None:
    """
    Archive one quoted price.

    Run daily, this builds the historical line database that does not exist
    publicly for player props -- which is the only way to ever backtest a
    prop model against real closing prices.
    """
    with conn() as c:
        c.execute(
            """INSERT INTO line_snapshots (at, sport, event, market, selection, point, book, price)
               VALUES (?,?,?,?,?,?,?,?)""",
            (_now(), sport, event, market, selection, point, book, price))


# ------------------------------------------------------------------ analysis

def summary() -> dict:
    with conn() as c:
        r = c.execute("""
            SELECT COUNT(*) n,
                   SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) w,
                   SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) l,
                   SUM(CASE WHEN result='push' THEN 1 ELSE 0 END) p,
                   COALESCE(SUM(stake),0) staked,
                   COALESCE(SUM(pnl),0) pnl,
                   AVG(clv_pp) avg_clv,
                   COUNT(clv_pp) n_clv
            FROM bets WHERE result IN ('win','loss','push','void')
        """).fetchone()
    n, staked = r["n"] or 0, r["staked"] or 0.0
    return {
        "n": n, "wins": r["w"] or 0, "losses": r["l"] or 0, "pushes": r["p"] or 0,
        "staked": staked, "pnl": r["pnl"] or 0.0,
        "roi": (r["pnl"] / staked * 100) if staked else 0.0,
        "avg_clv": r["avg_clv"], "n_clv": r["n_clv"] or 0,
    }


def by_market() -> list[sqlite3.Row]:
    with conn() as c:
        return c.execute("""
            SELECT market,
                   COUNT(*) n,
                   SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) w,
                   COALESCE(SUM(stake),0) staked,
                   COALESCE(SUM(pnl),0) pnl,
                   AVG(clv_pp) avg_clv
            FROM bets WHERE result IN ('win','loss','push','void')
            GROUP BY market ORDER BY pnl DESC
        """).fetchall()


# ------------------------------------------------------------------- ladder

LADDER_SCHEMA = """
CREATE TABLE IF NOT EXISTS ladder (
    rung        INTEGER PRIMARY KEY,
    bet_id      INTEGER,
    placed_at   TEXT NOT NULL,
    event_date  TEXT NOT NULL,
    selection   TEXT NOT NULL,
    odds        REAL NOT NULL,
    stake       REAL NOT NULL,
    model_prob  REAL,
    ev_pct      REAL,
    result      TEXT DEFAULT 'pending',
    balance     REAL,
    notes       TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS ladder_meta (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    start   REAL NOT NULL,
    target  REAL NOT NULL,
    started TEXT NOT NULL
);
"""


def ladder_init(start: float = 1.0, target: float = 1000.0) -> None:
    with conn() as c:
        c.executescript(LADDER_SCHEMA)
        c.execute("INSERT OR IGNORE INTO ladder_meta (id, start, target, started) "
                  "VALUES (1, ?, ?, ?)", (start, target, _now()))


def ladder_meta() -> dict:
    ladder_init()
    with conn() as c:
        r = c.execute("SELECT * FROM ladder_meta WHERE id=1").fetchone()
    return dict(r) if r else {"start": 1.0, "target": 1000.0}


def ladder_balance() -> float:
    """Current ladder stake: the start, compounded through settled rungs."""
    meta = ladder_meta()
    bal = meta["start"]
    with conn() as c:
        rows = c.execute("SELECT * FROM ladder WHERE result IN ('win','loss','push') "
                         "ORDER BY rung").fetchall()
    from .oddsmath import american_to_decimal
    for r in rows:
        if r["result"] == "win":
            bal = r["stake"] * american_to_decimal(r["odds"])
        elif r["result"] == "loss":
            bal = 0.0
        # push leaves the balance untouched
    return bal


# Preferred price band for ladder rungs: -200 to -120.
#
# Favourites compound the edge over more rungs, and that beats fewer rungs at
# longer odds. At a constant +12% EV the completion probability runs 0.270% at
# -120, 0.395% at -140, and 0.522% at -180.
#
# The band stops at -200 for a practical reason rather than a mathematical
# one. A fixed edge in PROBABILITY POINTS buys less EV as the favourite grows,
# because you risk more to win the same: rung 1's +4.6pp edge is worth +7.7%
# EV at -147 but only +6.9% at -200. And to hold that edge at -200 the model
# must say 71.3%, which it seldom does -- most EV-positive props land between
# 51% and 66%. Past -200 the band would be empty most nights.
LADDER_ODDS_MIN = -200
LADDER_ODDS_MAX = -120


def in_ladder_band(odds: float) -> bool:
    """True when a price sits in the preferred ladder range."""
    return LADDER_ODDS_MIN <= odds <= LADDER_ODDS_MAX


def ladder_add(event_date: str, selection: str, odds: float, stake: float,
               model_prob: float | None = None, ev_pct: float | None = None,
               bet_id: int | None = None, notes: str = "") -> int:
    ladder_init()
    with conn() as c:
        nxt = (c.execute("SELECT COALESCE(MAX(rung),0)+1 FROM ladder").fetchone()[0])
        c.execute("""INSERT INTO ladder (rung, bet_id, placed_at, event_date,
                     selection, odds, stake, model_prob, ev_pct, notes)
                     VALUES (?,?,?,?,?,?,?,?,?,?)""",
                  (nxt, bet_id, _now(), event_date, selection, odds, stake,
                   model_prob, ev_pct, notes))
    return nxt


def ladder_settle(rung: int, result: str) -> float:
    from .oddsmath import american_to_decimal
    with conn() as c:
        r = c.execute("SELECT * FROM ladder WHERE rung=?", (rung,)).fetchone()
        if r is None:
            raise ValueError(f"No ladder rung {rung}")
        if result == "win":
            bal = r["stake"] * american_to_decimal(r["odds"])
        elif result == "loss":
            bal = 0.0
        else:
            bal = r["stake"]
        c.execute("UPDATE ladder SET result=?, balance=? WHERE rung=?",
                  (result, bal, rung))
    return bal


def ladder_rows() -> list:
    ladder_init()
    with conn() as c:
        return c.execute("SELECT * FROM ladder ORDER BY rung").fetchall()
