"""Confluence scoring logic for SPX Prophet."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.projections import round_price
from core.time_utils import build_session_windows, filter_time_range

if TYPE_CHECKING:
    import pandas as pd


def _movement_alignment(start_price: float, end_price: float, direction: str) -> bool:
    """Return True when a move aligns with the trade direction."""

    if direction == "CALL":
        return end_price > start_price
    if direction == "PUT":
        return end_price < start_price
    return False


def _asian_factor(es_candles: "pd.DataFrame", prior_session_date, next_trading_date, direction: str) -> dict[str, Any]:
    """Score Asian session alignment."""

    start_time, end_time = build_session_windows(prior_session_date, next_trading_date)["asian_session"]
    asian = filter_time_range(es_candles, start_time, end_time)
    if asian.empty:
        return {"score": 0, "title": "Asian Session", "detail": "No Asian session candles available."}

    start_price = float(asian.iloc[0]["open"])
    end_price = float(asian.iloc[-1]["close"])
    aligned = _movement_alignment(start_price, end_price, direction)

    return {
        "score": 1 if aligned else 0,
        "title": "Asian Session",
        "detail": (
            f"Asian move {round_price(start_price)} -> {round_price(end_price)} "
            f"{'aligned' if aligned else 'did not align'} with the {direction} bias."
        ),
        "range_high": round_price(float(asian["high"].max())),
        "range_low": round_price(float(asian["low"].min())),
    }


def _london_sweep_factor(es_candles: "pd.DataFrame", prior_session_date, next_trading_date, direction: str) -> dict[str, Any]:
    """Score London sweep behavior versus the Asian range."""

    windows = build_session_windows(prior_session_date, next_trading_date)
    asian = filter_time_range(es_candles, *windows["asian_session"])
    london = filter_time_range(es_candles, *windows["london_session"])

    if asian.empty or london.empty:
        return {"score": 0, "title": "London Sweep", "detail": "Missing Asian or London candles."}

    asian_high = float(asian["high"].max())
    asian_low = float(asian["low"].min())
    london_high = float(london["high"].max())
    london_low = float(london["low"].min())
    london_close = float(london.iloc[-1]["close"])

    overshoot_above = london_high - asian_high
    overshoot_below = asian_low - london_low
    retraced_after_high = london_close < asian_high
    retraced_after_low = london_close > asian_low

    score = 0
    detail = "London stayed inside the Asian range."

    if direction == "PUT" and overshoot_above >= 6.0:
        if overshoot_above <= 10.0 and retraced_after_high:
            score = 1
            detail = f"Classic London sweep above Asian high by {round_price(overshoot_above)} points, then retraced back inside."
        elif overshoot_above > 10.0:
            score = 1
            detail = f"Extended London push above Asian high by {round_price(overshoot_above)} points."
    elif direction == "CALL" and overshoot_below >= 6.0:
        if overshoot_below <= 10.0 and retraced_after_low:
            score = 1
            detail = f"Classic London sweep below Asian low by {round_price(overshoot_below)} points, then retraced back inside."
        elif overshoot_below > 10.0:
            score = 1
            detail = f"Extended London push below Asian low by {round_price(overshoot_below)} points."
    elif direction == "PUT" and 0.0 < overshoot_above < 6.0:
        detail = f"London poked only {round_price(overshoot_above)} points above Asian high, which is too shallow."
    elif direction == "CALL" and 0.0 < overshoot_below < 6.0:
        detail = f"London poked only {round_price(overshoot_below)} points below Asian low, which is too shallow."
    else:
        detail = "London did not sweep the relevant Asian boundary; NY may still do the first fake break."

    return {"score": score, "title": "London Sweep", "detail": detail}


def _reaction_factor(spx_candles: "pd.DataFrame" | None, prior_session_date, next_trading_date, direction: str) -> dict[str, Any]:
    """Score the 7:30 AM data-reaction window."""

    if spx_candles is None or spx_candles.empty:
        return {"score": 0, "title": "7:30 Reaction", "detail": "No 30-minute SPX candles available."}

    start_time, end_time = build_session_windows(prior_session_date, next_trading_date)["reaction_730"]
    window = filter_time_range(spx_candles, start_time, end_time)
    if window.empty:
        return {"score": 0, "title": "7:30 Reaction", "detail": "No 7:30-8:30 AM candles available."}

    start_price = float(window.iloc[0]["open"])
    end_price = float(window.iloc[-1]["close"])
    aligned = _movement_alignment(start_price, end_price, direction)

    return {
        "score": 1 if aligned else 0,
        "title": "7:30 Reaction",
        "detail": f"Data reaction moved {'with' if aligned else 'against'} the {direction} bias.",
    }


def _opening_drive_factor(spx_candles: "pd.DataFrame" | None, prior_session_date, next_trading_date, direction: str) -> dict[str, Any]:
    """Score the 8:30-9:00 AM opening drive."""

    if spx_candles is None or spx_candles.empty:
        return {"score": 0, "title": "Opening Drive", "detail": "No 8:30-9:00 SPX candle available."}

    start_time, end_time = build_session_windows(prior_session_date, next_trading_date)["opening_drive"]
    window = filter_time_range(spx_candles, start_time, end_time)
    if window.empty:
        return {"score": 0, "title": "Opening Drive", "detail": "No opening-drive candle available."}

    candle = window.iloc[-1]
    aligned = _movement_alignment(float(candle["open"]), float(candle["close"]), direction)

    return {
        "score": 1 if aligned else 0,
        "title": "Opening Drive",
        "detail": f"Opening drive closed {'with' if aligned else 'against'} the {direction} bias.",
    }


def _line_cluster_factor(projected_lines: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Score whether three or more lines cluster inside five points."""

    prices = sorted(float(details["projected_price"]) for details in projected_lines.values())
    best_cluster = 1

    for start_index in range(len(prices)):
        cluster_size = 1
        for end_index in range(start_index + 1, len(prices)):
            if prices[end_index] - prices[start_index] <= 5.0:
                cluster_size += 1
        best_cluster = max(best_cluster, cluster_size)

    return {
        "score": 1 if best_cluster >= 3 else 0,
        "title": "Line Cluster",
        "detail": (
            f"{best_cluster} lines are inside a five-point band."
            if best_cluster >= 3
            else "No three-line cluster inside five points."
        ),
    }


def score_confluence(
    es_candles: "pd.DataFrame",
    spx_candles: "pd.DataFrame" | None,
    prior_session_date,
    next_trading_date,
    direction: str,
    projected_lines: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Score the five confluence factors on a 0-5 scale."""

    factors = [
        _asian_factor(es_candles, prior_session_date, next_trading_date, direction),
        _london_sweep_factor(es_candles, prior_session_date, next_trading_date, direction),
        _reaction_factor(spx_candles, prior_session_date, next_trading_date, direction),
        _opening_drive_factor(spx_candles, prior_session_date, next_trading_date, direction),
        _line_cluster_factor(projected_lines),
    ]
    total_score = int(sum(item["score"] for item in factors))

    return {
        "total_score": total_score,
        "max_score": 5,
        "confidence_band": "full" if total_score >= 4 else "reduced" if total_score == 3 else "caution",
        "factors": factors,
    }
