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
    previous_row = window.iloc[max(pivot_index - 1, 0)]
    next_row = window.iloc[min(pivot_index + 1, len(window) - 1)]
    return select_pivot_context(previous_row, pivot_row, next_row)


def _resolve_pivot_extreme(context: dict[str, dict[str, Any]], pivot_type: str) -> dict[str, Any]:
    """Resolve the true pivot extreme across the full three-candle context."""

    candidates = [
        context["previous_candle"],
        context["pivot_candle"],
        context["next_candle"],
    ]
    if pivot_type == "high":
        return max(candidates, key=lambda candle: float(candle["high"]))
    return min(candidates, key=lambda candle: float(candle["low"]))


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
            "pivot_extreme": _resolve_pivot_extreme(context, pivot_type),
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
            "pivot_extreme": _resolve_pivot_extreme(context, pivot_type),
            "confirmed": False,
            "fallback_reason": "no_strict_pivot_in_window",
        }

    return last_match


def _find_session_extremes(window: "pd.DataFrame") -> dict[str, Any]:
    """Find the full-session highest and lowest wick anchors."""

    all_candles = [row_to_candle_metadata(row) for _, row in window.iterrows()]
    if not all_candles:
        raise ValueError("At least one candle is required to detect session wick extremes")

    hw_source = max(all_candles, key=lambda candle: candle["high"])
    lw_source = min(all_candles, key=lambda candle: candle["low"])

    return {
        "hw_anchor": {
            "price": float(hw_source["high"]),
            "timestamp": hw_source["timestamp"],
            "projection_start_time": hw_source["timestamp"],
            "source": hw_source,
            "direction": "ascending",
            "label": "HW",
            "description": "Highest wick of the 8:30 AM-4:00 PM NY session",
            "anchor_basis": "session_high",
        },
        "lw_anchor": {
            "price": float(lw_source["low"]),
            "timestamp": lw_source["timestamp"],
            "projection_start_time": lw_source["timestamp"],
            "source": lw_source,
            "direction": "descending",
            "label": "LW",
            "description": "Lowest wick of the 8:30 AM-4:00 PM NY session",
            "anchor_basis": "session_low",
        },
    }


def resolve_anchor_prices(pivot_high: dict[str, Any], pivot_low: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Resolve the four channel anchors from the detected pivots."""

    pivot_high_time = to_central_time(pivot_high["pivot_time"])
    pivot_low_time = to_central_time(pivot_low["pivot_time"])
    pivot_high_extreme = pivot_high["pivot_extreme"]
    pivot_low_extreme = pivot_low["pivot_extreme"]
    pivot_high_extreme_price = float(pivot_high_extreme["high"])
    pivot_low_extreme_price = float(pivot_low_extreme["low"])

    return {
        "asc_ceiling_anchor": {
            "price": pivot_high_extreme_price,
            "timestamp": to_central_time(pivot_high_extreme["timestamp"]),
            "projection_start_time": pivot_high_time,
            "source": pivot_high_extreme,
            "associated_context_candle": pivot_high["red_candle"],
            "pivot_extreme": pivot_high_extreme,
            "anchor_basis": "pivot_high_extreme",
            "direction": "ascending",
            "label": "ASC Ceiling",
        },
        "desc_ceiling_anchor": {
            "price": pivot_high_extreme_price,
            "timestamp": to_central_time(pivot_high_extreme["timestamp"]),
            "projection_start_time": pivot_high_time,
            "source": pivot_high_extreme,
            "associated_context_candle": pivot_high["green_candle"],
            "pivot_extreme": pivot_high_extreme,
            "anchor_basis": "pivot_high_extreme",
            "direction": "descending",
            "label": "DESC Ceiling",
        },
        "asc_floor_anchor": {
            "price": pivot_low_extreme_price,
            "timestamp": to_central_time(pivot_low_extreme["timestamp"]),
            "projection_start_time": pivot_low_time,
            "source": pivot_low_extreme,
            "associated_context_candle": pivot_low["red_candle"],
            "pivot_extreme": pivot_low_extreme,
            "anchor_basis": "pivot_low_extreme",
            "direction": "ascending",
            "label": "ASC Floor",
        },
        "desc_floor_anchor": {
            "price": pivot_low_extreme_price,
            "timestamp": to_central_time(pivot_low_extreme["timestamp"]),
            "projection_start_time": pivot_low_time,
            "source": pivot_low_extreme,
            "associated_context_candle": pivot_low["green_candle"],
            "pivot_extreme": pivot_low_extreme,
            "anchor_basis": "pivot_low_extreme",
            "direction": "descending",
            "label": "DESC Floor",
        },
    }


def build_six_line_anchors(
    candles: "pd.DataFrame",
    session_date: Any,
    next_trading_date: Any = None,
    anchor_source_override: "str | None" = None,
    reference_price: "float | None" = None,
) -> dict[str, Any]:
    """Build the full six-anchor structure from a prior NY session.

    Parameters
    ----------
    candles : pd.DataFrame
        ES hourly candle frame covering the prior session and overnight.
    session_date : date
        The prior NY session date.
    next_trading_date : date | None
        The next trading date. When provided, enables multi-session anchor
        selection (Asian, London, Pre-NY windows). Defaults to session_date + 1 day.
    anchor_source_override : str | None
        Force a specific session source: "PM_WINDOW" | "ASIAN" | "LONDON" | "PRE_NY".
        None means Auto (all windows evaluated by the anchor engine).
    reference_price : float | None
        Optional 9 AM reference price (ES) for proximity-based scoring.
    """
    import datetime as _dt
    from core.anchor_engine import run_anchor_selection, SESSION_SOURCES

    normalized = _normalize_candles(candles)

    # Resolve next_trading_date — required for multi-session windows
    if next_trading_date is None:
        next_trading_date = session_date + _dt.timedelta(days=1)

    # --- Multi-session anchor selection ---
    engine_result = run_anchor_selection(
        candles=candles,
        prior_session_date=session_date,
        next_trading_date=next_trading_date,
        reference_price=reference_price,
        anchor_source_override=anchor_source_override,
    )
    pivot_high = engine_result["pivot_high"]
    pivot_low = engine_result["pivot_low"]

    # --- Session-extreme detection (full NY session, unchanged) ---
    ny_session_window = filter_time_range(
        normalized,
        start_time=at_central(session_date, 8, 0),
        end_time=at_central(session_date, 16, 0),
    )

    # Keep afternoon_window for candle metadata / afternoon_candles output
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

    # Fall back to legacy _find_last_pivot if anchor engine returned nothing
    if pivot_high is None or pivot_low is None:
        _ph = _find_last_pivot(afternoon_window, "high")
        _pl = _find_last_pivot(afternoon_window, "low")
        pivot_high = pivot_high or _ph
        pivot_low = pivot_low or _pl

    session_extremes = _find_session_extremes(ny_session_window)
    pivot_anchors = resolve_anchor_prices(pivot_high, pivot_low)

    # Derive search_window label from the selected session source
    def _src_window_label(candidate: dict) -> str:
        src = candidate.get("session_source", "PM_WINDOW")
        info = SESSION_SOURCES.get(src, {})
        return info.get("description", "12:00 PM CT to 3:00 PM CT")

    def _session_source_tag(candidate: dict) -> str:
        src = candidate.get("session_source", "PM_WINDOW")
        return SESSION_SOURCES.get(src, {}).get("label", "PM Window")

    anchors = {
        "hw": {
            **session_extremes["hw_anchor"],
            "line_type": "session_extreme",
            "session_source": "SESSION_HIGH",
            "session_source_label": "Session High",
        },
        "asc_ceiling": {
            **pivot_anchors["asc_ceiling_anchor"],
            "line_type": "channel",
            "session_source": pivot_high.get("session_source", "PM_WINDOW"),
            "session_source_label": _session_source_tag(pivot_high),
        },
        "asc_floor": {
            **pivot_anchors["asc_floor_anchor"],
            "line_type": "channel",
            "session_source": pivot_low.get("session_source", "PM_WINDOW"),
            "session_source_label": _session_source_tag(pivot_low),
        },
        "desc_ceiling": {
            **pivot_anchors["desc_ceiling_anchor"],
            "line_type": "channel",
            "session_source": pivot_high.get("session_source", "PM_WINDOW"),
            "session_source_label": _session_source_tag(pivot_high),
        },
        "desc_floor": {
            **pivot_anchors["desc_floor_anchor"],
            "line_type": "channel",
            "session_source": pivot_low.get("session_source", "PM_WINDOW"),
            "session_source_label": _session_source_tag(pivot_low),
        },
        "lw": {
            **session_extremes["lw_anchor"],
            "line_type": "session_extreme",
            "session_source": "SESSION_LOW",
            "session_source_label": "Session Low",
        },
    }

    return {
        "session_date": session_date,
        "afternoon_window_rows": len(afternoon_window),
        "ny_session_rows": len(ny_session_window),
        "source_points": {
            "pivot_high": {
                "timestamp": pivot_high["pivot_extreme"]["timestamp"],
                "price": float(pivot_high["pivot_extreme"]["high"]),
                "source": pivot_high["pivot_extreme"],
                "search_window": _src_window_label(pivot_high),
                "session_source": pivot_high.get("session_source", "PM_WINDOW"),
            },
            "pivot_highest_wick": {
                "timestamp": session_extremes["hw_anchor"]["timestamp"],
                "price": float(session_extremes["hw_anchor"]["price"]),
                "source": session_extremes["hw_anchor"]["source"],
                "search_window": "8:30 AM CT to 4:00 PM CT",
            },
            "pivot_low": {
                "timestamp": pivot_low["pivot_extreme"]["timestamp"],
                "price": float(pivot_low["pivot_extreme"]["low"]),
                "source": pivot_low["pivot_extreme"],
                "search_window": _src_window_label(pivot_low),
                "session_source": pivot_low.get("session_source", "PM_WINDOW"),
            },
            "pivot_lowest_wick": {
                "timestamp": session_extremes["lw_anchor"]["timestamp"],
                "price": float(session_extremes["lw_anchor"]["price"]),
                "source": session_extremes["lw_anchor"]["source"],
                "search_window": "8:30 AM CT to 4:00 PM CT",
            },
        },
        "pivot_high": pivot_high,
        "pivot_low": pivot_low,
        "session_extremes": session_extremes,
        "anchors": anchors,
        "afternoon_candles": [row_to_candle_metadata(row) for _, row in afternoon_window.iterrows()],
        "anchor_engine": engine_result,
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
