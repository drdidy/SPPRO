"""Asian cone polarity engine for SPX Prophet.

Every projected line from the Asian high and Asian low is treated as a polarity
line. A line is support or resistance only after price touches it and the candle
close confirms which side controls.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from core.projections import round_price


DEFAULT_TOUCH_TOLERANCE_POINTS = 1.0
DEFAULT_MAX_VALID_CLOSE_DISTANCE_POINTS = 3.0
DEFAULT_RETEST_ZONE_POINTS = 2.0


@dataclass(frozen=True)
class ConeLine:
    """A projected polarity line from an Asian pivot."""

    name: str
    cone: str
    pivot_type: str
    slope_direction: str
    projected_price: float
    source_price: float | None = None
    source_time: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["projected_price"] = round_price(float(self.projected_price))
        if self.source_price is not None:
            payload["source_price"] = round_price(float(self.source_price))
        return payload


def classify_polarity_touch(
    *,
    line_price: float,
    candle_high: float,
    candle_low: float,
    candle_close: float,
    prior_close: float | None = None,
    touch_tolerance: float = DEFAULT_TOUCH_TOLERANCE_POINTS,
    max_valid_close_distance: float = DEFAULT_MAX_VALID_CLOSE_DISTANCE_POINTS,
    retest_zone_points: float = DEFAULT_RETEST_ZONE_POINTS,
) -> dict[str, Any]:
    """Classify how price interacted with one polarity line.

    Entry-quality rule:
    - Wick touch alone is not enough.
    - Touch + close on the correct side but too far from the line is marked as
      extended confirmation, not immediate confirmation.
    - A valid actionable touch requires the candle to close on the controlling
      side AND within max_valid_close_distance points of the line.

    This avoids entering the next candle after a large rejection close, only to
    watch price retest and break the line.
    """

    line = float(line_price)
    high = float(candle_high)
    low = float(candle_low)
    close = float(candle_close)
    touched = low - touch_tolerance <= line <= high + touch_tolerance
    close_above = close > line
    close_below = close < line
    signed_close_distance = close - line
    abs_close_distance = abs(signed_close_distance)
    close_near_line = abs_close_distance <= float(max_valid_close_distance)
    in_retest_zone = abs_close_distance <= float(retest_zone_points)

    if prior_close is None:
        approach_side = "unknown"
    elif float(prior_close) > line:
        approach_side = "from_above"
    elif float(prior_close) < line:
        approach_side = "from_below"
    else:
        approach_side = "from_line"

    actionable = False
    wait_for_retest = False
    risk_note = ""

    if not touched:
        state = "above_line" if close_above else "below_line" if close_below else "at_line"
        action_bias = "monitor"
        label = "No touch yet"
    elif close_above and close_near_line:
        state = "support_hold"
        action_bias = "bullish"
        actionable = True
        label = "Polarity support confirmed near line"
    elif close_below and close_near_line:
        state = "resistance_rejection"
        action_bias = "bearish"
        actionable = True
        label = "Polarity resistance confirmed near line"
    elif close_above:
        state = "extended_support_rejection_wait_for_retest"
        action_bias = "bullish_but_extended"
        wait_for_retest = True
        risk_note = "Wick touched and closed above, but close is too far from the line. Do not chase. Wait for a controlled retest or continuation confirmation."
        label = "Support reaction extended; wait for retest"
    elif close_below:
        state = "extended_resistance_rejection_wait_for_retest"
        action_bias = "bearish_but_extended"
        wait_for_retest = True
        risk_note = "Wick touched and closed below, but close is too far from the line. Do not chase. Wait for a controlled retest or continuation confirmation."
        label = "Resistance reaction extended; wait for retest"
    else:
        state = "line_balance"
        action_bias = "wait"
        label = "Closed on the polarity line"

    return {
        "line_price": round_price(line),
        "touched": touched,
        "close_above": close_above,
        "close_below": close_below,
        "close_distance_points": round_price(signed_close_distance),
        "abs_close_distance_points": round_price(abs_close_distance),
        "close_near_line": close_near_line,
        "in_retest_zone": in_retest_zone,
        "approach_side": approach_side,
        "state": state,
        "action_bias": action_bias,
        "actionable": actionable,
        "wait_for_retest": wait_for_retest,
        "label": label,
        "risk_note": risk_note,
        "validation_rule": {
            "touch_tolerance_points": touch_tolerance,
            "max_valid_close_distance_points": max_valid_close_distance,
            "retest_zone_points": retest_zone_points,
            "rule": "Touch plus close on controlling side within max_valid_close_distance is actionable. Extended closes require patience, not chase entries.",
        },
    }


def locate_price_in_asian_cones(
    *,
    current_price: float,
    asian_high_ascending: float,
    asian_high_descending: float,
    asian_low_ascending: float,
    asian_low_descending: float,
) -> dict[str, Any]:
    """Locate price relative to the Asian high and Asian low cones."""

    price = float(current_price)
    high_cone_upper = max(float(asian_high_ascending), float(asian_high_descending))
    high_cone_lower = min(float(asian_high_ascending), float(asian_high_descending))
    low_cone_upper = max(float(asian_low_ascending), float(asian_low_descending))
    low_cone_lower = min(float(asian_low_ascending), float(asian_low_descending))

    in_high_cone = high_cone_lower <= price <= high_cone_upper
    in_low_cone = low_cone_lower <= price <= low_cone_upper
    above_both = price > max(high_cone_upper, low_cone_upper)
    below_both = price < min(high_cone_lower, low_cone_lower)

    if in_high_cone and in_low_cone:
        regime = "overlapping_asian_cones"
    elif in_high_cone:
        regime = "inside_asian_high_cone"
    elif in_low_cone:
        regime = "inside_asian_low_cone"
    elif above_both:
        regime = "above_both_asian_cones"
    elif below_both:
        regime = "below_both_asian_cones"
    else:
        regime = "between_asian_cones"

    return {
        "current_price": round_price(price),
        "regime": regime,
        "inside_asian_high_cone": in_high_cone,
        "inside_asian_low_cone": in_low_cone,
        "above_both_asian_cones": above_both,
        "below_both_asian_cones": below_both,
        "asian_high_cone": {"upper": round_price(high_cone_upper), "lower": round_price(high_cone_lower)},
        "asian_low_cone": {"upper": round_price(low_cone_upper), "lower": round_price(low_cone_lower)},
    }


def nearest_polarity_lines(*, current_price: float, lines: list[dict[str, Any]], limit: int = 4) -> list[dict[str, Any]]:
    """Return nearest projected polarity lines to current price."""

    price = float(current_price)
    ranked: list[dict[str, Any]] = []
    for line in lines:
        projected = float(line.get("projected_price", line.get("price", 0.0)))
        enriched = dict(line)
        enriched["distance_points"] = round_price(abs(price - projected))
        enriched["price_side"] = "above" if price > projected else "below" if price < projected else "at_line"
        ranked.append(enriched)
    return sorted(ranked, key=lambda item: float(item["distance_points"]))[:limit]


def build_polarity_line_table(
    *,
    current_price: float,
    candle: dict[str, Any] | None,
    lines: list[dict[str, Any]],
    prior_close: float | None = None,
    touch_tolerance: float = DEFAULT_TOUCH_TOLERANCE_POINTS,
    max_valid_close_distance: float = DEFAULT_MAX_VALID_CLOSE_DISTANCE_POINTS,
    retest_zone_points: float = DEFAULT_RETEST_ZONE_POINTS,
) -> list[dict[str, Any]]:
    """Create a line-by-line polarity table for UI and scoring."""

    output: list[dict[str, Any]] = []
    for line in nearest_polarity_lines(current_price=current_price, lines=lines, limit=len(lines)):
        projected = float(line.get("projected_price", line.get("price", 0.0)))
        if candle:
            polarity = classify_polarity_touch(
                line_price=projected,
                candle_high=float(candle["high"]),
                candle_low=float(candle["low"]),
                candle_close=float(candle["close"]),
                prior_close=prior_close,
                touch_tolerance=touch_tolerance,
                max_valid_close_distance=max_valid_close_distance,
                retest_zone_points=retest_zone_points,
            )
        else:
            polarity = {
                "line_price": round_price(projected),
                "touched": False,
                "state": "pending_no_candle",
                "action_bias": "monitor",
                "actionable": False,
                "wait_for_retest": False,
                "label": "Waiting for candle confirmation",
            }
        output.append({**line, **polarity, "distance_points": line["distance_points"], "price_side": line["price_side"]})
    return output
