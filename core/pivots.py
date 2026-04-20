"""Pivot, anchor, and session-extreme detection for SPX Prophet."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.time_utils import at_central, filter_time_range, to_central_time

if TYPE_CHECKING:
    import pandas as pd


def candle_color(row: Any) -> str:
    """Return the candle color for a row-like object."""

    open_price = float(row["open"])
    close_price = float(row["close"])

    if close_price > open_price:
        return "green"
    if close_price < open_price:
        return "red"
    return "neutral"


def row_to_candle_metadata(row: Any) -> dict[str, Any]:
    """Convert a candle row into a debug-friendly metadata payload."""

    return {
        "timestamp": to_central_time(row["timestamp"]),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "color": candle_color(row),
    }


def _normalize_candles(candles: "pd.DataFrame") -> "pd.DataFrame":
    """Return a clean, Central-Time-normalized candle frame."""

    import pandas as pd

    normalized = candles.copy()
    normalized["timestamp"] = pd.to_datetime(normalized["timestamp"]).map(to_central_time)
    normalized = normalized.sort_values("timestamp").reset_index(drop=True)
    return normalized


def select_pivot_context(
    previous_candle: dict[str, Any],
    pivot_candle: dict[str, Any],
    next_candle: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Resolve the pivot, green, and red candles around a pivot.

    This mirrors the working `drdidy/Spx-Prophet` repo behavior:
    search candles in the order {i-1, i, i+1} and take the first bullish
    candle as green and the first bearish candle as red. If a color is not
    found in that 3-candle window, fall back to the pivot candle itself.
    """

    previous_meta = row_to_candle_metadata(previous_candle)
    pivot_meta = row_to_candle_metadata(pivot_candle)
    next_meta = row_to_candle_metadata(next_candle)

    candidates = [previous_meta, pivot_meta, next_meta]

    green_meta = next((candle for candle in candidates if candle["color"] == "green"), pivot_meta)
    red_meta = next((candle for candle in candidates if candle["color"] == "red"), pivot_meta)

    return {
        "previous_candle": previous_meta,
        "pivot_candle": pivot_meta,
        "next_candle": next_meta,
        "green_candle": green_meta,
        "red_candle": red_meta,
    }


def _select_pivot_context_candles(window: "pd.DataFrame", pivot_index: int) -> dict[str, dict[str, Any]]:
    """Resolve the pivot, green, and red candles around a pivot index.

    Rules:
    - Green candle: whichever is bullish among the pivot candle or the candle
      before it. Use the pivot candle as fallback.
    - Red candle: whichever is bearish among the pivot candle or the candle
      after it. Use the pivot candle as fallback.
    """

    pivot_row = window.iloc[pivot_index]
    previous_row = window.iloc[pivot_index - 1]
    next_row = window.iloc[pivot_index + 1]
    return select_pivot_context(previous_row, pivot_row, next_row)


def _is_pivot_high(window: "pd.DataFrame", index: int) -> bool:
    """Return True when close[i] is a pivot high by the house rule."""

    return bool(
        float(window.iloc[index]["close"]) > float(window.iloc[index - 1]["close"])
        and float(window.iloc[index]["close"]) > float(window.iloc[index + 1]["close"])
    )


def _is_pivot_low(window: "pd.DataFrame", index: int) -> bool:
    """Return True when close[i] is a pivot low by the house rule."""

    return bool(
        float(window.iloc[index]["close"]) < float(window.iloc[index - 1]["close"])
        and float(window.iloc[index]["close"]) < float(window.iloc[index + 1]["close"])
    )


def _find_last_pivot(window: "pd.DataFrame", pivot_type: str) -> dict[str, Any]:
    """Find the last pivot high or low in the afternoon session."""

    if len(window) < 3:
        raise ValueError("At least three candles are required to detect session pivots")

    last_match: dict[str, Any] | None = None
    pivot_window_start = to_central_time(window.iloc[0]["timestamp"]).replace(hour=12, minute=0, second=0, microsecond=0)

    for index in range(1, len(window) - 1):
        if to_central_time(window.iloc[index]["timestamp"]) < pivot_window_start:
            continue
        is_match = _is_pivot_high(window, index) if pivot_type == "high" else _is_pivot_low(window, index)
        if not is_match:
            continue

        context = _select_pivot_context_candles(window, index)
        last_match = {
            "pivot_type": pivot_type,
            "pivot_index": index,
            "pivot_time": context["pivot_candle"]["timestamp"],
            "previous_candle": context["previous_candle"],
            "pivot_candle": context["pivot_candle"],
            "next_candle": context["next_candle"],
            "green_candle": context["green_candle"],
            "red_candle": context["red_candle"],
        }

    if last_match is None:
        # Match the working Spx-Prophet behavior: if no strict pivot exists in the
        # 12 PM-4 PM window, fall back to the strongest close in that same window.
        in_window = window.loc[
            window["timestamp"].map(to_central_time) >= pivot_window_start
        ].copy()
        if in_window.empty:
            raise ValueError(f"No pivot {pivot_type} found in the 12 PM to 4 PM session window")

        fallback_index = (
            int(in_window["close"].astype(float).idxmax())
            if pivot_type == "high"
            else int(in_window["close"].astype(float).idxmin())
        )
        context = _select_pivot_context_candles(window, fallback_index)
        return {
            "pivot_type": pivot_type,
            "pivot_index": fallback_index,
            "pivot_time": context["pivot_candle"]["timestamp"],
            "previous_candle": context["previous_candle"],
            "pivot_candle": context["pivot_candle"],
            "next_candle": context["next_candle"],
            "green_candle": context["green_candle"],
            "red_candle": context["red_candle"],
            "confirmed": False,
            "fallback_reason": "no_strict_pivot_in_window",
        }

    return last_match


def _find_session_extremes(window: "pd.DataFrame") -> dict[str, Any]:
    """Find the full-session red-high and green-low wick anchors."""

    red_candles = []
    green_candles = []

    for _, row in window.iterrows():
        metadata = row_to_candle_metadata(row)
        if metadata["color"] == "red":
            red_candles.append(metadata)
        elif metadata["color"] == "green":
            green_candles.append(metadata)

    # Match the working Spx-Prophet repo: if one color is absent, fall back to
    # the absolute session extreme rather than failing the whole anchor build.
    if red_candles:
        hw_source = max(red_candles, key=lambda candle: candle["high"])
    else:
        hw_source = max((row_to_candle_metadata(row) for _, row in window.iterrows()), key=lambda candle: candle["high"])

    if green_candles:
        lw_source = min(green_candles, key=lambda candle: candle["low"])
    else:
        lw_source = min((row_to_candle_metadata(row) for _, row in window.iterrows()), key=lambda candle: candle["low"])

    return {
        "hw_anchor": {
            "price": float(hw_source["high"]),
            "timestamp": hw_source["timestamp"],
            "projection_start_time": hw_source["timestamp"],
            "source": hw_source,
            "direction": "ascending",
            "label": "HW",
            "description": "Highest HIGH of a bearish candle in the 8:30 AM-3:00 PM NY session",
        },
        "lw_anchor": {
            "price": float(lw_source["low"]),
            "timestamp": lw_source["timestamp"],
            "projection_start_time": lw_source["timestamp"],
            "source": lw_source,
            "direction": "descending",
            "label": "LW",
            "description": "Lowest LOW of a bullish candle in the 8:30 AM-3:00 PM NY session",
        },
    }


def resolve_anchor_prices(pivot_high: dict[str, Any], pivot_low: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Resolve the four channel anchors from the detected pivots.

    Candle counting begins from the pivot timestamp, not the neighboring candle
    timestamp that supplied the green or red wick.
    """

    pivot_high_time = to_central_time(pivot_high["pivot_time"])
    pivot_low_time = to_central_time(pivot_low["pivot_time"])

    return {
        "asc_ceiling_anchor": {
            "price": float(pivot_high["red_candle"]["high"]),
            "timestamp": to_central_time(pivot_high["red_candle"]["timestamp"]),
            "projection_start_time": pivot_high_time,
            "source": pivot_high["red_candle"],
            "direction": "ascending",
            "label": "ASC Ceiling",
        },
        "desc_ceiling_anchor": {
            "price": float(pivot_high["green_candle"]["high"]),
            "timestamp": to_central_time(pivot_high["green_candle"]["timestamp"]),
            "projection_start_time": pivot_high_time,
            "source": pivot_high["green_candle"],
            "direction": "descending",
            "label": "DESC Ceiling",
        },
        "asc_floor_anchor": {
            "price": float(pivot_low["red_candle"]["low"]),
            "timestamp": to_central_time(pivot_low["red_candle"]["timestamp"]),
            "projection_start_time": pivot_low_time,
            "source": pivot_low["red_candle"],
            "direction": "ascending",
            "label": "ASC Floor",
        },
        "desc_floor_anchor": {
            "price": float(pivot_low["green_candle"]["low"]),
            "timestamp": to_central_time(pivot_low["green_candle"]["timestamp"]),
            "projection_start_time": pivot_low_time,
            "source": pivot_low["green_candle"],
            "direction": "descending",
            "label": "DESC Floor",
        },
    }


def build_six_line_anchors(candles: "pd.DataFrame", session_date: Any) -> dict[str, Any]:
    """Build the full six-anchor structure from a prior NY session."""

    normalized = _normalize_candles(candles)

    # Include the 11 AM candle as context so a 12 PM pivot can evaluate i-1.
    afternoon_window = filter_time_range(
        normalized,
        start_time=at_central(session_date, 11, 0),
        end_time=at_central(session_date, 16, 0),
    )
    if len(afternoon_window) < 3:
        afternoon_window = filter_time_range(
            normalized,
            start_time=at_central(session_date, 8, 30),
            end_time=at_central(session_date, 20, 0),
        )
    ny_session_window = filter_time_range(
        normalized,
        start_time=at_central(session_date, 8, 30),
        end_time=at_central(session_date, 15, 0),
    )

    pivot_high = _find_last_pivot(afternoon_window, "high")
    pivot_low = _find_last_pivot(afternoon_window, "low")
    pivot_anchors = resolve_anchor_prices(pivot_high, pivot_low)
    session_extremes = _find_session_extremes(ny_session_window)

    anchors = {
        "hw": {
            **session_extremes["hw_anchor"],
            "line_type": "session_extreme",
        },
        "asc_ceiling": {
            **pivot_anchors["asc_ceiling_anchor"],
            "line_type": "channel",
        },
        "asc_floor": {
            **pivot_anchors["asc_floor_anchor"],
            "line_type": "channel",
        },
        "desc_ceiling": {
            **pivot_anchors["desc_ceiling_anchor"],
            "line_type": "channel",
        },
        "desc_floor": {
            **pivot_anchors["desc_floor_anchor"],
            "line_type": "channel",
        },
        "lw": {
            **session_extremes["lw_anchor"],
            "line_type": "session_extreme",
        },
    }

    return {
        "session_date": session_date,
        "afternoon_window_rows": len(afternoon_window),
        "ny_session_rows": len(ny_session_window),
        "pivot_high": pivot_high,
        "pivot_low": pivot_low,
        "session_extremes": session_extremes,
        "anchors": anchors,
        "afternoon_candles": [row_to_candle_metadata(row) for _, row in afternoon_window.iterrows()],
    }


def detect_session_pivots(candles: "pd.DataFrame", session_date: Any) -> dict[str, Any]:
    """Backward-compatible wrapper for the original session pivot API."""

    result = build_six_line_anchors(candles, session_date)
    return {
        "pivot_high": result["pivot_high"],
        "pivot_low": result["pivot_low"],
        "anchors": {
            "asc_ceiling_anchor": result["anchors"]["asc_ceiling"],
            "desc_ceiling_anchor": result["anchors"]["desc_ceiling"],
            "asc_floor_anchor": result["anchors"]["asc_floor"],
            "desc_floor_anchor": result["anchors"]["desc_floor"],
        },
        "session_extremes": result["session_extremes"],
        "afternoon_candles": result["afternoon_candles"],
    }
