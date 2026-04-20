"""Projection math for SPX Prophet lines."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from core.time_utils import get_valid_candle_count, to_central_time

RATE_PER_CANDLE = Decimal("1.04")
TWOPLACES = Decimal("0.01")

LINE_DISPLAY_ORDER = ["hw", "asc_ceiling", "asc_floor", "desc_ceiling", "desc_floor", "lw"]


def round_price(value: float) -> float:
    """Round a numeric price to two decimal places using market-friendly rules."""

    return float(Decimal(str(value)).quantize(TWOPLACES, rounding=ROUND_HALF_UP))


def project_price(anchor_price: float, candle_count: int, direction: str) -> float:
    """Project a price using the fixed 1.04-point hourly rate."""

    if candle_count < 0:
        raise ValueError("candle_count must be non-negative")

    normalized_direction = direction.strip().lower()
    if normalized_direction not in {"ascending", "descending"}:
        raise ValueError("direction must be 'ascending' or 'descending'")

    multiplier = Decimal("1") if normalized_direction == "ascending" else Decimal("-1")
    anchor_value = Decimal(str(anchor_price))
    offset = RATE_PER_CANDLE * Decimal(candle_count) * multiplier
    projected = (anchor_value + offset).quantize(TWOPLACES, rounding=ROUND_HALF_UP)

    return float(projected)


def project_anchor_line(line_name: str, anchor: dict[str, Any], target_time) -> dict[str, Any]:
    """Project a single anchor line to a target timestamp."""

    anchor_timestamp = to_central_time(anchor["timestamp"])
    start_time = to_central_time(anchor.get("projection_start_time", anchor_timestamp))
    target_ct = to_central_time(target_time)
    candle_count = get_valid_candle_count(start_time, target_ct)
    raw_anchor_price = round_price(float(anchor["price"]))
    projected_price = project_price(raw_anchor_price, candle_count, str(anchor["direction"]))

    return {
        "name": line_name,
        "label": anchor.get("label", line_name.upper()),
        "direction": anchor["direction"],
        "raw_anchor_price": raw_anchor_price,
        "raw_anchor_timestamp": anchor_timestamp,
        "anchor_price": raw_anchor_price,
        "anchor_timestamp": anchor_timestamp,
        "projection_start_time": start_time,
        "source": anchor.get("source"),
        "line_type": anchor.get("line_type", "channel"),
        "candle_count": candle_count,
        "target_time": target_ct,
        "projected_price": projected_price,
        "description": anchor.get("description", ""),
    }


def project_six_lines(anchors: dict[str, dict[str, Any]], target_time) -> dict[str, dict[str, Any]]:
    """Project the full six-line structure to a target timestamp."""

    return {
        line_name: project_anchor_line(line_name, anchors[line_name], target_time)
        for line_name in LINE_DISPLAY_ORDER
    }


def project_session_lines(
    anchors: dict[str, float | dict[str, Any]],
    high_candle_count: int,
    low_candle_count: int,
) -> dict[str, dict[str, Any]]:
    """Backward-compatible helper for the original four-line validation test."""

    def _extract(anchor_key: str) -> float:
        raw = anchors[anchor_key]
        if isinstance(raw, dict):
            return float(raw["price"])
        return float(raw)

    return {
        "asc_ceiling": {
            "anchor_price": _extract("asc_ceiling_anchor"),
            "candle_count": high_candle_count,
            "direction": "ascending",
            "projected_price": project_price(_extract("asc_ceiling_anchor"), high_candle_count, "ascending"),
        },
        "asc_floor": {
            "anchor_price": _extract("asc_floor_anchor"),
            "candle_count": low_candle_count,
            "direction": "ascending",
            "projected_price": project_price(_extract("asc_floor_anchor"), low_candle_count, "ascending"),
        },
        "desc_ceiling": {
            "anchor_price": _extract("desc_ceiling_anchor"),
            "candle_count": high_candle_count,
            "direction": "descending",
            "projected_price": project_price(_extract("desc_ceiling_anchor"), high_candle_count, "descending"),
        },
        "desc_floor": {
            "anchor_price": _extract("desc_floor_anchor"),
            "candle_count": low_candle_count,
            "direction": "descending",
            "projected_price": project_price(_extract("desc_floor_anchor"), low_candle_count, "descending"),
        },
    }


def extract_projected_values(lines: dict[str, dict[str, Any]]) -> dict[str, float]:
    """Flatten a projection bundle into a name-to-price mapping."""

    return {name: details["projected_price"] for name, details in lines.items()}


def convert_price_space(value: float, offset: float, to_space: str) -> float:
    """Convert between ES and SPX price spaces using a manual offset."""

    if to_space == "spx":
        return round_price(float(value) - float(offset))
    if to_space == "es":
        return round_price(float(value) + float(offset))
    raise ValueError("to_space must be either 'spx' or 'es'")


def convert_projected_lines(lines: dict[str, dict[str, Any]], offset: float, to_space: str) -> dict[str, dict[str, Any]]:
    """Convert projected line values between ES and SPX terms."""

    converted: dict[str, dict[str, Any]] = {}

    for line_name, details in lines.items():
        payload = dict(details)
        raw_anchor_price = details.get("raw_anchor_price", details["anchor_price"])
        payload["raw_anchor_price"] = convert_price_space(raw_anchor_price, offset, to_space)
        payload["anchor_price"] = payload["raw_anchor_price"]
        payload["projected_price"] = convert_price_space(details["projected_price"], offset, to_space)
        payload["raw_anchor_timestamp"] = details.get("raw_anchor_timestamp", details.get("anchor_timestamp"))
        payload["anchor_timestamp"] = payload["raw_anchor_timestamp"]
        if details.get("source"):
            source = dict(details["source"])
            source["high"] = convert_price_space(source["high"], offset, to_space)
            source["low"] = convert_price_space(source["low"], offset, to_space)
            source["open"] = convert_price_space(source["open"], offset, to_space)
            source["close"] = convert_price_space(source["close"], offset, to_space)
            payload["source"] = source
        converted[line_name] = payload

    return converted


def apply_overnight_pivot_overrides(
    projected_lines: dict[str, dict[str, Any]],
    *,
    overnight_high: dict[str, dict[str, Any]] | None = None,
    overnight_low: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Apply outward-only overnight pivot overrides to projected lines.

    Rules:
    - Overnight pivot high may only extend the channel ceilings outward.
    - Overnight pivot low may only extend the channel floors outward.
    - If the overnight candidate lands inside the existing channel boundary, it
      is ignored.
    """

    updated = {name: dict(details) for name, details in projected_lines.items()}
    decisions: dict[str, dict[str, Any]] = {}

    def _apply(line_name: str, candidate: dict[str, Any], direction: str) -> None:
        current_value = float(updated[line_name]["projected_price"])
        candidate_value = float(candidate["projected_price"])
        should_override = candidate_value > current_value if direction == "ceiling" else candidate_value < current_value
        decisions[line_name] = {
            "applied": should_override,
            "current_value": round_price(current_value),
            "candidate_value": round_price(candidate_value),
            "reason": "outward_extension" if should_override else "inside_or_less_extreme",
        }
        if should_override:
            merged = dict(updated[line_name])
            merged.update(candidate)
            merged["override_source"] = "overnight_pivot"
            updated[line_name] = merged

    if overnight_high is not None:
        if "asc_ceiling" in overnight_high:
            _apply("asc_ceiling", overnight_high["asc_ceiling"], "ceiling")
        if "desc_ceiling" in overnight_high:
            _apply("desc_ceiling", overnight_high["desc_ceiling"], "ceiling")

    if overnight_low is not None:
        if "asc_floor" in overnight_low:
            _apply("asc_floor", overnight_low["asc_floor"], "floor")
        if "desc_floor" in overnight_low:
            _apply("desc_floor", overnight_low["desc_floor"], "floor")

    return {
        "projected_lines": updated,
        "decisions": decisions,
    }
