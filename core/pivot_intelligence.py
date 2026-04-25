"""Adaptive pivot intelligence for SPX Prophet.

The original engine treated the 12 PM-4 PM CT pivot as the primary source.
This module expands the candidate universe so Asian-session pivots can compete
with afternoon pivots when they produce the structure that NY actually respects.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Iterable

import pandas as pd

from core.projections import round_price
from core.time_utils import at_central, filter_time_range, to_central_time


@dataclass(frozen=True)
class PivotWindowSpec:
    """Named session window used for pivot candidate discovery."""

    name: str
    start_hour: int
    start_minute: int
    end_hour: int
    end_minute: int
    weight: float
    description: str


PIVOT_WINDOWS: tuple[PivotWindowSpec, ...] = (
    PivotWindowSpec(
        name="ny_afternoon",
        start_hour=12,
        start_minute=0,
        end_hour=16,
        end_minute=0,
        weight=1.00,
        description="Original 12 PM-4 PM CT pivot window.",
    ),
    PivotWindowSpec(
        name="asian_evening",
        start_hour=17,
        start_minute=0,
        end_hour=23,
        end_minute=59,
        weight=1.15,
        description="Asian session structure window. Often sets the higher-relevance overnight pivot.",
    ),
    PivotWindowSpec(
        name="overnight_continuation",
        start_hour=0,
        start_minute=0,
        end_hour=7,
        end_minute=30,
        weight=1.05,
        description="Post-midnight continuation window before NY premarket structure hardens.",
    ),
)


def _normalize_candles(candles: pd.DataFrame) -> pd.DataFrame:
    if candles is None or candles.empty:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])
    df = candles.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"]).map(to_central_time)
    return df.sort_values("timestamp").reset_index(drop=True)


def _candle_color(row: Any) -> str:
    open_price = float(row["open"])
    close_price = float(row["close"])
    if close_price > open_price:
        return "green"
    if close_price < open_price:
        return "red"
    return "neutral"


def _row_meta(row: Any) -> dict[str, Any]:
    return {
        "timestamp": to_central_time(row["timestamp"]),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "color": _candle_color(row),
    }


def _is_pivot_high(window: pd.DataFrame, index: int) -> bool:
    return bool(
        float(window.iloc[index]["close"]) > float(window.iloc[index - 1]["close"])
        and float(window.iloc[index]["close"]) > float(window.iloc[index + 1]["close"])
    )


def _is_pivot_low(window: pd.DataFrame, index: int) -> bool:
    return bool(
        float(window.iloc[index]["close"]) < float(window.iloc[index - 1]["close"])
        and float(window.iloc[index]["close"]) < float(window.iloc[index + 1]["close"])
    )


def _window_bounds(session_date: Any, spec: PivotWindowSpec):
    start = at_central(session_date, spec.start_hour, spec.start_minute)
    end = at_central(session_date, spec.end_hour, spec.end_minute)
    if spec.name in {"asian_evening"}:
        start = start
        end = end
    return start, end


def discover_pivot_candidates(
    candles: pd.DataFrame,
    session_date: Any,
    *,
    windows: Iterable[PivotWindowSpec] = PIVOT_WINDOWS,
) -> list[dict[str, Any]]:
    """Return high and low pivot candidates from multiple structural windows."""

    normalized = _normalize_candles(candles)
    candidates: list[dict[str, Any]] = []
    if normalized.empty:
        return candidates

    for spec in windows:
        start, end = _window_bounds(session_date, spec)
        window = filter_time_range(normalized, start_time=start, end_time=end)
        if len(window) < 3:
            continue

        for index in range(1, len(window) - 1):
            prev_row = window.iloc[index - 1]
            row = window.iloc[index]
            next_row = window.iloc[index + 1]
            context = [_row_meta(prev_row), _row_meta(row), _row_meta(next_row)]

            if _is_pivot_high(window, index):
                extreme = max(context, key=lambda candle: float(candle["high"]))
                candidates.append(
                    {
                        "pivot_type": "high",
                        "window_name": spec.name,
                        "window_description": spec.description,
                        "window_weight": spec.weight,
                        "pivot_time": to_central_time(row["timestamp"]),
                        "extreme_time": extreme["timestamp"],
                        "price": round_price(float(extreme["high"])),
                        "context": context,
                        "confirmed": True,
                    }
                )

            if _is_pivot_low(window, index):
                extreme = min(context, key=lambda candle: float(candle["low"]))
                candidates.append(
                    {
                        "pivot_type": "low",
                        "window_name": spec.name,
                        "window_description": spec.description,
                        "window_weight": spec.weight,
                        "pivot_time": to_central_time(row["timestamp"]),
                        "extreme_time": extreme["timestamp"],
                        "price": round_price(float(extreme["low"])),
                        "context": context,
                        "confirmed": True,
                    }
                )

    return candidates


def score_pivot_candidate(candidate: dict[str, Any], *, reference_price: float | None = None) -> dict[str, Any]:
    """Score a pivot candidate for structural relevance.

    This is deliberately transparent rather than overfit. The score favors:
    - Asian-session pivots when they are structurally clean
    - Extremes that are closer to the current NY decision area
    - Later pivots inside the same window
    """

    score = 50.0 * float(candidate.get("window_weight", 1.0))
    notes: list[str] = [f"Window: {candidate.get('window_name')}"]

    context = candidate.get("context") or []
    if len(context) == 3:
        wick_range = max(float(c["high"]) for c in context) - min(float(c["low"]) for c in context)
        body_sizes = [abs(float(c["close"]) - float(c["open"])) for c in context]
        reaction_body = max(body_sizes) if body_sizes else 0.0
        if reaction_body >= 0.25 * wick_range:
            score += 10.0
            notes.append("Context shows a meaningful reaction body.")

    if reference_price is not None and reference_price > 0:
        distance = abs(float(candidate["price"]) - float(reference_price))
        if distance <= 10:
            score += 20.0
            notes.append("Pivot is close to the NY decision area.")
        elif distance <= 25:
            score += 10.0
            notes.append("Pivot is within practical striking distance.")
        else:
            score -= 5.0
            notes.append("Pivot is far from the current decision area.")

    final_score = max(0, min(100, int(round(score))))
    enriched = dict(candidate)
    enriched["score"] = final_score
    enriched["score_notes"] = notes
    return enriched


def rank_pivot_candidates(
    candidates: list[dict[str, Any]],
    *,
    pivot_type: str,
    reference_price: float | None = None,
) -> list[dict[str, Any]]:
    """Rank candidates of one pivot type from strongest to weakest."""

    selected = [candidate for candidate in candidates if candidate.get("pivot_type") == pivot_type]
    scored = [score_pivot_candidate(candidate, reference_price=reference_price) for candidate in selected]
    return sorted(scored, key=lambda candidate: (candidate["score"], candidate["price"]), reverse=pivot_type == "high")


def summarize_pivot_intelligence(candles: pd.DataFrame, session_date: Any, *, reference_price: float | None = None) -> dict[str, Any]:
    """Return a debug/UI friendly adaptive pivot summary."""

    candidates = discover_pivot_candidates(candles, session_date)
    highs = rank_pivot_candidates(candidates, pivot_type="high", reference_price=reference_price)
    lows = rank_pivot_candidates(candidates, pivot_type="low", reference_price=reference_price)
    return {
        "session_date": str(session_date),
        "reference_price": reference_price,
        "candidate_count": len(candidates),
        "best_high": highs[0] if highs else None,
        "best_low": lows[0] if lows else None,
        "high_candidates": highs,
        "low_candidates": lows,
        "windows": [asdict(window) for window in PIVOT_WINDOWS],
    }
