"""Persistent trade-log helpers for SPX Prophet."""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from core.time_utils import CENTRAL_TZ


def _default_state() -> dict[str, Any]:
    """Return the empty persistent app state."""

    return {"trades": [], "journals": {}}


def ensure_storage_path(storage_path: Path) -> None:
    """Ensure the storage folder exists."""

    storage_path.parent.mkdir(parents=True, exist_ok=True)


def load_trade_state(storage_path: Path) -> dict[str, Any]:
    """Load trade-log state from JSON."""

    ensure_storage_path(storage_path)
    if not storage_path.exists():
        return _default_state()

    with storage_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_trade_state(storage_path: Path, state: dict[str, Any]) -> None:
    """Persist trade-log state to JSON."""

    ensure_storage_path(storage_path)
    with storage_path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)


def add_trade(storage_path: Path, trade: dict[str, Any]) -> dict[str, Any]:
    """Append a trade record and persist it."""

    state = load_trade_state(storage_path)
    record = {
        "id": str(uuid.uuid4()),
        "created_at": datetime.now(tz=CENTRAL_TZ).isoformat(),
        **trade,
    }
    state["trades"].append(record)
    save_trade_state(storage_path, state)
    return record


def delete_trade(storage_path: Path, trade_id: str) -> None:
    """Delete a trade by id and persist the change."""

    state = load_trade_state(storage_path)
    state["trades"] = [trade for trade in state["trades"] if trade.get("id") != trade_id]
    save_trade_state(storage_path, state)


def upsert_journal_entry(storage_path: Path, journal_date: str, text: str, tags: list[str]) -> None:
    """Save or update a daily journal entry."""

    state = load_trade_state(storage_path)
    state["journals"][journal_date] = {"text": text, "tags": tags}
    save_trade_state(storage_path, state)


def calculate_trade_pnl(entry_premium: float, exit_premium: float, contracts: int) -> float:
    """Calculate option P&L using standard SPX contract sizing."""

    return round((float(exit_premium) - float(entry_premium)) * 100.0 * int(contracts), 2)


def compute_performance_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute total P&L, win rate, profit factor, and max drawdown."""

    pnl_values = [float(trade.get("pnl", 0.0)) for trade in trades]
    total_pnl = round(sum(pnl_values), 2)
    wins = [value for value in pnl_values if value > 0]
    losses = [value for value in pnl_values if value < 0]
    win_rate = round((len(wins) / len(pnl_values) * 100.0), 2) if pnl_values else 0.0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = round((gross_profit / gross_loss), 2) if gross_loss else None

    equity_curve = []
    running = 0.0
    peak = 0.0
    max_drawdown = 0.0

    for trade in trades:
        running += float(trade.get("pnl", 0.0))
        peak = max(peak, running)
        max_drawdown = min(max_drawdown, running - peak)
        equity_curve.append({"date": trade.get("date"), "equity": round(running, 2)})

    return {
        "total_pnl": total_pnl,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "max_drawdown": round(abs(max_drawdown), 2),
        "equity_curve": equity_curve,
    }


def summarize_win_rate_by_confluence(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate win rate by confluence score."""

    buckets: dict[int, dict[str, int]] = {}

    for trade in trades:
        score = int(trade.get("confluence_score", 0))
        bucket = buckets.setdefault(score, {"wins": 0, "total": 0})
        bucket["total"] += 1
        if float(trade.get("pnl", 0.0)) > 0:
            bucket["wins"] += 1

    return [
        {
            "confluence_score": score,
            "win_rate": round(bucket["wins"] / bucket["total"] * 100.0, 2) if bucket["total"] else 0.0,
            "trades": bucket["total"],
        }
        for score, bucket in sorted(buckets.items())
    ]


def export_trades_csv(trades: list[dict[str, Any]]) -> str:
    """Export trades to CSV text."""

    if not trades:
        return ""

    fieldnames = sorted({key for trade in trades for key in trade.keys()})
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(trades)
    return buffer.getvalue()


def export_trades_json(trades: list[dict[str, Any]]) -> str:
    """Export trades to JSON text."""

    return json.dumps(trades, indent=2)
