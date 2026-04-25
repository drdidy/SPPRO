"""Pivot, anchor, and session-extreme detection for SPX Prophet."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.time_utils import at_central, filter_time_range, to_central_time

try:
    from core.pivot_intelligence import summarize_pivot_intelligence
except Exception:  # pragma: no cover - defensive fallback during partial deploys
    summarize_pivot_intelligence = None

if TYPE_CHECKING:
    import pandas as pd


def candle_color(row: Any) -> str:
    open_price = float(row["open"])
    close_price = float(row["close"])
    if close_price > open_price:
        return "green"
    if close_price < open_price:
        return "red"
    return "neutral"


def row_to_candle_metadata(row: Any) -> dict[str, Any]:
    return {
        "timestamp": to_central_time(row["timestamp"]),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "color": candle_color(row),
    }


def _normalize_candles(candles: "pd.DataFrame") -> "pd.DataFrame":
    import pandas as pd

    normalized = candles.copy()
    normalized["timestamp"] = pd.to_datetime(normalized["timestamp"]).map(to_central_time)
    return normalized.sort_values("timestamp").reset_index(drop=True)


def select_pivot_context(previous_candle: dict[str, Any], pivot_candle: dict[str, Any], next_candle: dict[str, Any]) -> dict[str, dict[str, Any]]:
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
    pivot_row = window.iloc[pivot_index]
    previous_row = window.iloc[max(pivot_index - 1, 0)]
    next_row = window.iloc[min(pivot_index + 1, len(window) - 1)]
    return select_pivot_context(previous_row, pivot_row, next_row)


def _resolve_pivot_extreme(context: dict[str, dict[str, Any]], pivot_type: str) -> dict[str, Any]:
    candidates = [context["previous_candle"], context["pivot_candle"], context["next_candle"]]
    return max(candidates, key=lambda candle: float(candle["high"])) if pivot_type == "high" else min(candidates, key=lambda candle: float(candle["low"]))


def _is_pivot_high(window: "pd.DataFrame", index: int) -> bool:
    return bool(float(window.iloc[index]["close"]) > float(window.iloc[index - 1]["close"]) and float(window.iloc[index]["close"]) > float(window.iloc[index + 1]["close"]))


def _is_pivot_low(window: "pd.DataFrame", index: int) -> bool:
    return bool(float(window.iloc[index]["close"]) < float(window.iloc[index - 1]["close"]) and float(window.iloc[index]["close"]) < float(window.iloc[index + 1]["close"]))


def _find_last_pivot(window: "pd.DataFrame", pivot_type: str) -> dict[str, Any]:
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
            "selection_reason": "legacy_last_ny_afternoon_pivot",
            "window_name": "ny_afternoon",
        }

    if last_match is not None:
        return last_match

    in_window = window.loc[window["timestamp"].map(to_central_time) >= pivot_window_start].copy()
    if in_window.empty:
        raise ValueError(f"No pivot {pivot_type} found in the 12 PM to 4 PM session window")
    fallback_index = int(in_window["close"].astype(float).idxmax()) if pivot_type == "high" else int(in_window["close"].astype(float).idxmin())
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
        "selection_reason": "legacy_ny_afternoon_fallback_close_extreme",
        "window_name": "ny_afternoon",
    }


def _find_session_extremes(window: "pd.DataFrame") -> dict[str, Any]:
    all_candles = [row_to_candle_metadata(row) for _, row in window.iterrows()]
    if not all_candles:
        raise ValueError("At least one candle is required to detect session wick extremes")
    hw_source = max(all_candles, key=lambda candle: candle["high"])
    lw_source = min(all_candles, key=lambda candle: candle["low"])
    return {
        "hw_anchor": {"price": float(hw_source["high"]), "timestamp": hw_source["timestamp"], "projection_start_time": hw_source["timestamp"], "source": hw_source, "direction": "ascending", "label": "HW", "description": "Highest wick of the 8:30 AM-4:00 PM NY session", "anchor_basis": "session_high"},
        "lw_anchor": {"price": float(lw_source["low"]), "timestamp": lw_source["timestamp"], "projection_start_time": lw_source["timestamp"], "source": lw_source, "direction": "descending", "label": "LW", "description": "Lowest wick of the 8:30 AM-4:00 PM NY session", "anchor_basis": "session_low"},
    }


def _candidate_to_legacy_pivot(candidate: dict[str, Any], pivot_type: str) -> dict[str, Any]:
    """Convert adaptive pivot candidate into the legacy pivot payload."""

    context = candidate.get("context") or []
    if len(context) < 3:
        raise ValueError("Adaptive pivot candidate requires a three-candle context")
    previous_candle, pivot_candle, next_candle = context[0], context[1], context[2]
    green_candle = next((candle for candle in context if candle.get("color") == "green"), pivot_candle)
    red_candle = next((candle for candle in context if candle.get("color") == "red"), pivot_candle)
    if pivot_type == "high":
        extreme = max(context, key=lambda candle: float(candle["high"]))
    else:
        extreme = min(context, key=lambda candle: float(candle["low"]))
    return {
        "pivot_type": pivot_type,
        "pivot_index": None,
        "pivot_time": candidate.get("pivot_time", pivot_candle["timestamp"]),
        "previous_candle": previous_candle,
        "pivot_candle": pivot_candle,
        "next_candle": next_candle,
        "green_candle": green_candle,
        "red_candle": red_candle,
        "pivot_extreme": extreme,
        "confirmed": bool(candidate.get("confirmed", True)),
        "window_name": candidate.get("window_name"),
        "score": candidate.get("score"),
        "selection_reason": candidate.get("selection_reason"),
        "score_notes": candidate.get("score_notes", []),
    }


def resolve_anchor_prices(pivot_high: dict[str, Any], pivot_low: dict[str, Any]) -> dict[str, dict[str, Any]]:
    pivot_high_time = to_central_time(pivot_high["pivot_time"])
    pivot_low_time = to_central_time(pivot_low["pivot_time"])
    pivot_high_extreme = pivot_high["pivot_extreme"]
    pivot_low_extreme = pivot_low["pivot_extreme"]
    pivot_high_extreme_price = float(pivot_high_extreme["high"])
    pivot_low_extreme_price = float(pivot_low_extreme["low"])
    common_high_meta = {"adaptive_window": pivot_high.get("window_name"), "adaptive_score": pivot_high.get("score"), "selection_reason": pivot_high.get("selection_reason")}
    common_low_meta = {"adaptive_window": pivot_low.get("window_name"), "adaptive_score": pivot_low.get("score"), "selection_reason": pivot_low.get("selection_reason")}
    return {
        "asc_ceiling_anchor": {"price": pivot_high_extreme_price, "timestamp": to_central_time(pivot_high_extreme["timestamp"]), "projection_start_time": pivot_high_time, "source": pivot_high_extreme, "associated_context_candle": pivot_high["red_candle"], "pivot_extreme": pivot_high_extreme, "anchor_basis": "pivot_high_extreme", "direction": "ascending", "label": "ASC Ceiling", **common_high_meta},
        "desc_ceiling_anchor": {"price": pivot_high_extreme_price, "timestamp": to_central_time(pivot_high_extreme["timestamp"]), "projection_start_time": pivot_high_time, "source": pivot_high_extreme, "associated_context_candle": pivot_high["green_candle"], "pivot_extreme": pivot_high_extreme, "anchor_basis": "pivot_high_extreme", "direction": "descending", "label": "DESC Ceiling", **common_high_meta},
        "asc_floor_anchor": {"price": pivot_low_extreme_price, "timestamp": to_central_time(pivot_low_extreme["timestamp"]), "projection_start_time": pivot_low_time, "source": pivot_low_extreme, "associated_context_candle": pivot_low["red_candle"], "pivot_extreme": pivot_low_extreme, "anchor_basis": "pivot_low_extreme", "direction": "ascending", "label": "ASC Floor", **common_low_meta},
        "desc_floor_anchor": {"price": pivot_low_extreme_price, "timestamp": to_central_time(pivot_low_extreme["timestamp"]), "projection_start_time": pivot_low_time, "source": pivot_low_extreme, "associated_context_candle": pivot_low["green_candle"], "pivot_extreme": pivot_low_extreme, "anchor_basis": "pivot_low_extreme", "direction": "descending", "label": "DESC Floor", **common_low_meta},
    }


def build_six_line_anchors(candles: "pd.DataFrame", session_date: Any, reference_price: float | None = None, adaptive_pivots: bool = True) -> dict[str, Any]:
    """Build the full six-anchor structure.

    When reference_price is supplied, adaptive mode can select Asian-session
    pivots over NY afternoon pivots when Asian structure is closer to price.
    """

    normalized = _normalize_candles(candles)
    afternoon_window = filter_time_range(normalized, start_time=at_central(session_date, 11, 0), end_time=at_central(session_date, 16, 0))
    if len(afternoon_window) < 3:
        afternoon_window = filter_time_range(normalized, start_time=at_central(session_date, 8, 30), end_time=at_central(session_date, 20, 0))
    ny_session_window = filter_time_range(normalized, start_time=at_central(session_date, 8, 0), end_time=at_central(session_date, 16, 0))

    pivot_intelligence = None
    if adaptive_pivots and reference_price is not None and summarize_pivot_intelligence is not None:
        try:
            pivot_intelligence = summarize_pivot_intelligence(normalized, session_date, reference_price=float(reference_price))
        except Exception as exc:  # pragma: no cover - fallback must never break trading view
            pivot_intelligence = {"error": f"adaptive_pivot_error: {exc}"}

    if pivot_intelligence and pivot_intelligence.get("best_high") and pivot_intelligence.get("best_low"):
        pivot_high = _candidate_to_legacy_pivot(pivot_intelligence["best_high"], "high")
        pivot_low = _candidate_to_legacy_pivot(pivot_intelligence["best_low"], "low")
        pivot_mode = "adaptive"
    else:
        pivot_high = _find_last_pivot(afternoon_window, "high")
        pivot_low = _find_last_pivot(afternoon_window, "low")
        pivot_mode = "legacy"

    pivot_anchors = resolve_anchor_prices(pivot_high, pivot_low)
    session_extremes = _find_session_extremes(ny_session_window)
    anchors = {
        "hw": {**session_extremes["hw_anchor"], "line_type": "session_extreme"},
        "asc_ceiling": {**pivot_anchors["asc_ceiling_anchor"], "line_type": "channel"},
        "asc_floor": {**pivot_anchors["asc_floor_anchor"], "line_type": "channel"},
        "desc_ceiling": {**pivot_anchors["desc_ceiling_anchor"], "line_type": "channel"},
        "desc_floor": {**pivot_anchors["desc_floor_anchor"], "line_type": "channel"},
        "lw": {**session_extremes["lw_anchor"], "line_type": "session_extreme"},
    }

    return {
        "session_date": session_date,
        "pivot_mode": pivot_mode,
        "reference_price": reference_price,
        "adaptive_pivot_intelligence": pivot_intelligence,
        "afternoon_window_rows": len(afternoon_window),
        "ny_session_rows": len(ny_session_window),
        "source_points": {
            "pivot_high": {"timestamp": pivot_high["pivot_extreme"]["timestamp"], "price": float(pivot_high["pivot_extreme"]["high"]), "source": pivot_high["pivot_extreme"], "search_window": pivot_high.get("window_name", "12:00 PM CT to 4:00 PM CT"), "selection_reason": pivot_high.get("selection_reason"), "score": pivot_high.get("score")},
            "pivot_highest_wick": {"timestamp": session_extremes["hw_anchor"]["timestamp"], "price": float(session_extremes["hw_anchor"]["price"]), "source": session_extremes["hw_anchor"]["source"], "search_window": "8:30 AM CT to 4:00 PM CT"},
            "pivot_low": {"timestamp": pivot_low["pivot_extreme"]["timestamp"], "price": float(pivot_low["pivot_extreme"]["low"]), "source": pivot_low["pivot_extreme"], "search_window": pivot_low.get("window_name", "12:00 PM CT to 4:00 PM CT"), "selection_reason": pivot_low.get("selection_reason"), "score": pivot_low.get("score")},
            "pivot_lowest_wick": {"timestamp": session_extremes["lw_anchor"]["timestamp"], "price": float(session_extremes["lw_anchor"]["price"]), "source": session_extremes["lw_anchor"]["source"], "search_window": "8:30 AM CT to 4:00 PM CT"},
        },
        "pivot_high": pivot_high,
        "pivot_low": pivot_low,
        "session_extremes": session_extremes,
        "anchors": anchors,
        "afternoon_candles": [row_to_candle_metadata(row) for _, row in afternoon_window.iterrows()],
    }


def detect_session_pivots(candles: "pd.DataFrame", session_date: Any) -> dict[str, Any]:
    result = build_six_line_anchors(candles, session_date, adaptive_pivots=False)
    return {
        "pivot_high": result["pivot_high"],
        "pivot_low": result["pivot_low"],
        "anchors": {"asc_ceiling_anchor": result["anchors"]["asc_ceiling"], "desc_ceiling_anchor": result["anchors"]["desc_ceiling"], "asc_floor_anchor": result["anchors"]["asc_floor"], "desc_floor_anchor": result["anchors"]["desc_floor"]},
        "session_extremes": result["session_extremes"],
        "afternoon_candles": result["afternoon_candles"],
    }
