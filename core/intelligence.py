"""Adaptive Intelligence Engine — SQLite-backed signal log and outcome learning."""

from __future__ import annotations

import os
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any, Optional

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "intelligence.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trading_date TEXT NOT NULL,
    prior_date TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    scenario_name TEXT,
    primary_direction TEXT,
    primary_entry_price REAL,
    primary_stop_price REAL,
    primary_tp1_price REAL,
    alternate_direction TEXT,
    alternate_entry_price REAL,
    confirmation_status TEXT,
    sit_out INTEGER DEFAULT 0,
    is_backfill INTEGER DEFAULT 0,
    UNIQUE(trading_date)
);

CREATE TABLE IF NOT EXISTS outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trading_date TEXT NOT NULL,
    resolved_at TEXT,
    primary_entry_triggered INTEGER DEFAULT 0,
    primary_stop_hit INTEGER DEFAULT 0,
    primary_tp1_hit INTEGER DEFAULT 0,
    primary_tp2_hit INTEGER DEFAULT 0,
    primary_result TEXT,
    primary_pnl REAL DEFAULT 0,
    alternate_entry_triggered INTEGER DEFAULT 0,
    alternate_stop_hit INTEGER DEFAULT 0,
    alternate_tp1_hit INTEGER DEFAULT 0,
    alternate_tp2_hit INTEGER DEFAULT 0,
    alternate_result TEXT,
    alternate_pnl REAL DEFAULT 0,
    chosen_path TEXT,
    result_classification TEXT,
    estimated_pnl REAL DEFAULT 0,
    UNIQUE(trading_date)
);

CREATE TABLE IF NOT EXISTS backfill_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def ensure_schema() -> None:
    """Create tables if they don't exist."""
    with _conn() as db:
        db.executescript(_SCHEMA)


def capture_signal(
    trading_date: date,
    prior_date: date,
    signal_package: dict[str, Any],
    is_backfill: bool = False,
) -> bool:
    """Insert or replace a signal record. Returns True on success."""
    scenario = signal_package.get("scenario") or {}
    primary = scenario.get("primary_play") or {}
    alternate = scenario.get("alternate_play") or {}
    confirmation = signal_package.get("confirmation") or {}
    sit_out_info = signal_package.get("sit_out") or {}

    try:
        with _conn() as db:
            db.execute(
                """INSERT OR REPLACE INTO signals
                   (trading_date, prior_date, captured_at, scenario_name,
                    primary_direction, primary_entry_price, primary_stop_price, primary_tp1_price,
                    alternate_direction, alternate_entry_price,
                    confirmation_status, sit_out, is_backfill)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    trading_date.isoformat(),
                    prior_date.isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                    scenario.get("scenario_name"),
                    primary.get("direction"),
                    _f(primary.get("entry", {}).get("price")),
                    _f(primary.get("stop", {}).get("price")),
                    _f(primary.get("tp1", {}).get("price")),
                    alternate.get("direction"),
                    _f(alternate.get("entry", {}).get("price")),
                    confirmation.get("status"),
                    int(bool(sit_out_info.get("sit_out"))),
                    int(is_backfill),
                ),
            )
        return True
    except Exception:
        return False


def record_outcome(
    trading_date: "date | str",
    *,
    primary_entry_triggered: bool = False,
    primary_stop_hit: bool = False,
    primary_tp1_hit: bool = False,
    primary_tp2_hit: bool = False,
    primary_result: str = "Not Triggered",
    primary_pnl: float = 0.0,
    alternate_entry_triggered: bool = False,
    alternate_stop_hit: bool = False,
    alternate_tp1_hit: bool = False,
    alternate_tp2_hit: bool = False,
    alternate_result: str = "Not Triggered",
    alternate_pnl: float = 0.0,
    chosen_path: str = "None",
    result_classification: str = "No Trade",
    estimated_pnl: float = 0.0,
) -> bool:
    """Insert or replace an outcome record. Returns True on success."""
    td = trading_date.isoformat() if isinstance(trading_date, date) else trading_date
    try:
        with _conn() as db:
            db.execute(
                """INSERT OR REPLACE INTO outcomes
                   (trading_date, resolved_at,
                    primary_entry_triggered, primary_stop_hit, primary_tp1_hit, primary_tp2_hit,
                    primary_result, primary_pnl,
                    alternate_entry_triggered, alternate_stop_hit, alternate_tp1_hit, alternate_tp2_hit,
                    alternate_result, alternate_pnl,
                    chosen_path, result_classification, estimated_pnl)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    td,
                    datetime.now(timezone.utc).isoformat(),
                    int(primary_entry_triggered),
                    int(primary_stop_hit),
                    int(primary_tp1_hit),
                    int(primary_tp2_hit),
                    primary_result,
                    float(primary_pnl),
                    int(alternate_entry_triggered),
                    int(alternate_stop_hit),
                    int(alternate_tp1_hit),
                    int(alternate_tp2_hit),
                    alternate_result,
                    float(alternate_pnl),
                    chosen_path,
                    result_classification,
                    float(estimated_pnl),
                ),
            )
        return True
    except Exception:
        return False


def get_pending_outcome_dates() -> list[str]:
    """Return trading_date strings that have a signal but no resolved outcome."""
    with _conn() as db:
        rows = db.execute(
            """SELECT s.trading_date FROM signals s
               LEFT JOIN outcomes o ON s.trading_date = o.trading_date
               WHERE o.trading_date IS NULL
               ORDER BY s.trading_date""",
        ).fetchall()
    return [r["trading_date"] for r in rows]


def get_backfill_meta(key: str) -> Optional[str]:
    with _conn() as db:
        row = db.execute("SELECT value FROM backfill_meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_backfill_meta(key: str, value: str) -> None:
    with _conn() as db:
        db.execute("INSERT OR REPLACE INTO backfill_meta (key,value) VALUES (?,?)", (key, value))


def get_signal_count() -> int:
    with _conn() as db:
        return db.execute("SELECT COUNT(*) FROM signals").fetchone()[0]


def get_outcome_count() -> int:
    with _conn() as db:
        return db.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]


def get_all_records() -> list[dict]:
    """Return all signals joined with outcomes, newest first."""
    with _conn() as db:
        rows = db.execute(
            """SELECT s.trading_date, s.prior_date, s.scenario_name,
                      s.primary_direction, s.primary_entry_price, s.primary_tp1_price,
                      s.alternate_direction, s.confirmation_status, s.sit_out, s.is_backfill,
                      o.primary_entry_triggered, o.primary_stop_hit,
                      o.primary_tp1_hit, o.primary_tp2_hit, o.primary_result, o.primary_pnl,
                      o.alternate_entry_triggered, o.alternate_result, o.alternate_pnl,
                      o.chosen_path, o.result_classification, o.estimated_pnl
               FROM signals s
               LEFT JOIN outcomes o ON s.trading_date = o.trading_date
               ORDER BY s.trading_date DESC""",
        ).fetchall()
    return [dict(r) for r in rows]


def get_edge_stats() -> dict[str, Any]:
    """Compute aggregate win-rate and P&L stats across all resolved signals."""
    records = get_all_records()
    resolved = [r for r in records if r.get("result_classification") is not None]

    def _grp(items: list[dict]) -> dict[str, Any]:
        n = len(items)
        if not n:
            return {"n": 0, "win_rate": None, "avg_pnl": None, "total_pnl": None}
        wins = sum(1 for r in items if r.get("primary_tp1_hit") or r.get("primary_tp2_hit"))
        pnls = [float(r["primary_pnl"]) for r in items if r.get("primary_pnl") is not None]
        return {
            "n": n,
            "win_rate": round(wins / n, 4),
            "avg_pnl": round(sum(pnls) / len(pnls), 2) if pnls else None,
            "total_pnl": round(sum(pnls), 2) if pnls else None,
        }

    by_scenario: dict[str, list] = defaultdict(list)
    by_direction: dict[str, list] = defaultdict(list)
    by_confirmation: dict[str, list] = defaultdict(list)

    for r in resolved:
        if r.get("scenario_name"):
            by_scenario[r["scenario_name"]].append(r)
        if r.get("primary_direction"):
            by_direction[r["primary_direction"]].append(r)
        if r.get("confirmation_status"):
            by_confirmation[r["confirmation_status"]].append(r)

    return {
        "total_signals": len(records),
        "total_resolved": len(resolved),
        "overall": _grp(resolved),
        "by_scenario": {k: _grp(v) for k, v in sorted(by_scenario.items())},
        "by_direction": {k: _grp(v) for k, v in sorted(by_direction.items())},
        "by_confirmation": {k: _grp(v) for k, v in sorted(by_confirmation.items())},
    }


def _f(val: Any) -> Optional[float]:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
