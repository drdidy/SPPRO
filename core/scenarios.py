"""Scenario, confirmation, and trade-plan logic for SPX Prophet."""

from __future__ import annotations

from typing import Any

from core.projections import round_price
from core.time_utils import current_central_time, to_central_time

NEARBY_BOUNDARY_THRESHOLD = 5.0

SCENARIO_COLORS = {
    "SCENARIO 1: BETWEEN CONES": "#00d4ff",
    "SCENARIO 2: INSIDE HIGH CONE": "#00e676",
    "SCENARIO 3: INSIDE LOW CONE": "#ff1744",
    "SCENARIO 4: ABOVE HIGH CONE": "#ffd740",
    "SCENARIO 5: BELOW LOW CONE": "#ffd740",
}


def get_scenario_reference_outputs() -> dict[str, dict[str, Any]]:
    """Return the final structured scenario definitions used by the engine."""

    return {
        "SCENARIO 1: BETWEEN CONES": {
            "primary": {"direction": "PUT", "entry": "high_cone_floor", "stop": "high_cone_ceiling"},
            "alternate": {"direction": "CALL", "entry": "low_cone_ceiling", "stop": "low_cone_floor"},
            "confidence": "MEDIUM",
        },
        "SCENARIO 2: INSIDE HIGH CONE": {
            "primary": {"direction": "CALL", "entry": "desc_ceiling", "stop": "desc_floor"},
            "alternate": {"direction": "PUT", "entry": "asc_ceiling", "stop": "hw"},
            "confidence": "HIGH with confirmation, otherwise MEDIUM",
        },
        "SCENARIO 3: INSIDE LOW CONE": {
            "primary": {"direction": "CALL", "entry": "desc_floor", "stop": "lw"},
            "alternate": {"direction": "PUT", "entry": "asc_floor", "stop": "asc_ceiling"},
            "confidence": "HIGH with confirmation, otherwise MEDIUM",
        },
        "SCENARIO 4: ABOVE HIGH CONE": {
            "primary": {"direction": "CALL", "entry": "asc_ceiling", "stop": "desc_ceiling"},
            "alternate": None,
            "confidence": "MEDIUM",
        },
        "SCENARIO 5: BELOW LOW CONE": {
            "primary": {"direction": "PUT", "entry": "desc_floor", "stop": "asc_floor"},
            "alternate": None,
            "confidence": "MEDIUM",
        },
    }


def calculate_option_strike(direction: str, entry_line_price: float) -> int:
    """Calculate the 20-point OTM SPX option strike from an entry line."""

    if direction == "PUT":
        raw_value = float(entry_line_price) - 20.0
        return int(raw_value // 5 * 5)
    if direction == "CALL":
        raw_value = float(entry_line_price) + 20.0
        return int(-(-raw_value // 5) * 5)
    raise ValueError("direction must be 'PUT' or 'CALL'")


def _build_target(label: str, price: float, note: str = "") -> dict[str, Any]:
    """Build a small target payload."""

    return {
        "label": label,
        "price": round_price(price),
        "note": note,
    }


def _build_play(
    direction: str,
    entry_label: str,
    entry_price: float,
    stop_label: str,
    stop_price: float,
    tp1_label: str,
    tp1_price: float,
    tp2_label: str,
    tp2_price: float,
    contracts: int,
    note: str,
) -> dict[str, Any]:
    """Build a trade card payload."""

    return {
        "direction": direction,
        "entry": _build_target(entry_label, entry_price),
        "stop": _build_target(stop_label, stop_price),
        "tp1": _build_target(tp1_label, tp1_price),
        "tp2": _build_target(tp2_label, tp2_price),
        "contracts": contracts,
        "strike": calculate_option_strike(direction, entry_price),
        "note": note,
    }


def build_profit_management_plan(contracts: int) -> dict[str, Any]:
    """Build a structured profit-management plan for the active position size."""

    total_contracts = max(int(contracts), 1)
    tp1_contracts = min(2, total_contracts)
    runner_contracts = max(total_contracts - tp1_contracts, 0)
    tp2_contracts = runner_contracts if runner_contracts else 0

    return {
        "starting_contracts": total_contracts,
        "tp1_contracts_to_close": tp1_contracts,
        "tp2_contracts_to_close": tp2_contracts,
        "move_stop_to_breakeven_after_tp1": runner_contracts > 0,
        "tp1_action": {
            "action": "close_partial",
            "contracts_to_close": tp1_contracts,
            "move_stop_to_breakeven": runner_contracts > 0,
        },
        "tp2_action": {
            "action": "close_remaining",
            "contracts_to_close": tp2_contracts,
        },
        "stop_action": {
            "action": "close_all",
            "contracts_to_close": total_contracts,
        },
        "time_stop": "10:30 AM CT",
        "time_stop_action": {
            "action": "close_all_if_tp1_not_hit",
            "contracts_to_close": total_contracts,
            "deadline": "10:30 AM CT",
        },
        "rules": [
            f"At TP1: close {tp1_contracts} contract(s).",
            "Move stop to breakeven on the remaining position." if runner_contracts > 0 else "No runner remains after TP1 for this position size.",
            f"At TP2: close {tp2_contracts} contract(s)." if tp2_contracts else "No TP2 runner remains for this position size.",
            "If stop is hit: close all contracts immediately.",
            "If TP1 is not reached by 10:30 AM CT: close the trade for a time stop.",
        ],
    }


def _sorted_boundaries(lines: dict[str, float]) -> list[tuple[str, float]]:
    """Return line boundaries sorted by price descending."""

    return sorted(lines.items(), key=lambda item: item[1], reverse=True)


def _next_lower_boundary(boundaries: list[tuple[str, float]], label: str, fallback: tuple[str, float]) -> tuple[str, float]:
    """Find the next lower line boundary after a named line."""

    for index, (name, price) in enumerate(boundaries):
        if name == label:
            return boundaries[index + 1] if index + 1 < len(boundaries) else fallback
    return fallback


def _next_higher_boundary(boundaries: list[tuple[str, float]], label: str, fallback: tuple[str, float]) -> tuple[str, float]:
    """Find the next higher line boundary before a named line."""

    for index, (name, price) in enumerate(boundaries):
        if name == label:
            return boundaries[index - 1] if index > 0 else fallback
    return fallback


def _scenario_confidence(scenario_name: str, confirmed: bool) -> tuple[str, int]:
    """Map a scenario to its confidence label and contract count."""

    if scenario_name in {"SCENARIO 2: INSIDE HIGH CONE", "SCENARIO 3: INSIDE LOW CONE"} and confirmed:
        return "HIGH", 3
    return "MEDIUM", 2


def _is_high_cone_floor_near_low_cone(high_floor: float, low_floor: float, low_ceiling: float) -> bool:
    """Return True when the high-cone floor overlaps or is near the low cone."""

    return low_floor <= high_floor <= low_ceiling or abs(high_floor - low_ceiling) <= NEARBY_BOUNDARY_THRESHOLD


def _is_low_cone_ceiling_near_high_cone(low_ceiling: float, high_floor: float, high_ceiling: float) -> bool:
    """Return True when the low-cone ceiling overlaps or is near the high cone."""

    return high_floor <= low_ceiling <= high_ceiling or abs(low_ceiling - high_floor) <= NEARBY_BOUNDARY_THRESHOLD


def evaluate_trading_scenario(
    current_price: float,
    line_values: dict[str, float],
    open_price: float | None = None,
    confirmation_confirmed: bool = False,
) -> dict[str, Any]:
    """Classify the active Asian high/low cone and build its trade plan.

    A high pivot emits an ascending ceiling and descending floor. A low pivot
    emits an ascending ceiling and descending floor. Support/resistance is not
    assumed here; execution still requires the downstream polarity confirmation
    layer to prove hold/rejection.
    """

    required = {"hw", "asc_ceiling", "asc_floor", "desc_ceiling", "desc_floor", "lw"}
    missing = required.difference(line_values)
    if missing:
        raise ValueError(f"Missing required line values: {sorted(missing)}")

    price = round_price(current_price)
    open_reference = round_price(open_price if open_price is not None else current_price)

    hw = float(line_values["hw"])
    asc_ceiling = float(line_values["asc_ceiling"])
    asc_floor = float(line_values["asc_floor"])
    desc_ceiling = float(line_values["desc_ceiling"])
    desc_floor = float(line_values["desc_floor"])
    lw = float(line_values["lw"])

    high_cone_ceiling = asc_ceiling
    high_cone_floor = desc_ceiling
    low_cone_ceiling = asc_floor
    low_cone_floor = desc_floor

    in_high_cone = high_cone_floor <= price <= high_cone_ceiling
    in_low_cone = low_cone_floor <= price <= low_cone_ceiling
    cones_overlap = in_high_cone and in_low_cone
    between_cones = low_cone_ceiling < price < high_cone_floor
    above_high_cone = price > high_cone_ceiling
    below_low_cone = price < low_cone_floor

    high_floor_near_low = _is_high_cone_floor_near_low_cone(high_cone_floor, low_cone_floor, low_cone_ceiling)
    low_ceiling_near_high = _is_low_cone_ceiling_near_high_cone(low_cone_ceiling, high_cone_floor, high_cone_ceiling)
    boundaries = _sorted_boundaries(line_values)

    scenario_name = ""
    description = ""
    primary_play: dict[str, Any] | None = None
    alternate_play: dict[str, Any] | None = None

    if cones_overlap or between_cones:
        scenario_name = "SCENARIO 1: BETWEEN CONES"
        description = (
            "Price is in the neutral cone band; use the closest confirmed polarity line above for sells "
            "and the closest confirmed polarity line below for buys."
            if cones_overlap
            else "Price is between the low-cone ceiling and high-cone floor; wait for one polarity line to confirm."
        )
        channel_lines = {
            "asc_ceiling": asc_ceiling,
            "asc_floor": asc_floor,
            "desc_ceiling": desc_ceiling,
            "desc_floor": desc_floor,
        }
        ordered = _sorted_boundaries(channel_lines)
        if cones_overlap:
            above_lines = [(name, value) for name, value in ordered if value >= price]
            below_lines = [(name, value) for name, value in ordered if value <= price]
            put_entry = above_lines[-1] if above_lines else ordered[-1]
            call_entry = below_lines[0] if below_lines else ordered[0]
        else:
            put_entry = ("desc_ceiling", high_cone_floor)
            call_entry = ("asc_floor", low_cone_ceiling)
        put_stop = _next_higher_boundary(ordered, put_entry[0], ("hw", hw))
        call_stop = _next_lower_boundary(ordered, call_entry[0], ("lw", lw))
        put_tp1 = call_entry
        put_tp2 = _next_lower_boundary(ordered, call_entry[0], ("lw", lw))
        call_tp1 = put_entry
        call_tp2 = _next_higher_boundary(ordered, put_entry[0], ("hw", hw))
        primary_play = _build_play(
            "PUT",
            put_entry[0],
            put_entry[1],
            put_stop[0],
            put_stop[1],
            put_tp1[0],
            put_tp1[1],
            put_tp2[0],
            put_tp2[1],
            2,
            "Neutral cone setup: sell only after the upper polarity line rejects.",
        )
        alternate_play = _build_play(
            "CALL",
            call_entry[0],
            call_entry[1],
            call_stop[0],
            call_stop[1],
            call_tp1[0],
            call_tp1[1],
            call_tp2[0],
            call_tp2[1],
            1,
            "Neutral cone setup: buy only after the lower polarity line holds.",
        )
    elif in_high_cone:
        scenario_name = "SCENARIO 2: INSIDE HIGH CONE"
        description = "Price is inside the Asian high cone; buy the floor if it holds, sell the ceiling if it rejects."
        primary_play = _build_play(
            "CALL",
            "desc_ceiling",
            high_cone_floor,
            "desc_floor" if high_floor_near_low else "lw",
            low_cone_floor if high_floor_near_low else lw,
            "asc_ceiling",
            high_cone_ceiling,
            "hw",
            hw,
            3 if confirmation_confirmed else 2,
            "High-cone floor buy if polarity confirms support.",
        )
        alternate_play = _build_play(
            "PUT",
            "asc_ceiling",
            high_cone_ceiling,
            "hw",
            hw,
            "desc_ceiling",
            high_cone_floor,
            "asc_floor",
            low_cone_ceiling,
            1,
            "High-cone ceiling sell if polarity confirms rejection.",
        )
    elif in_low_cone:
        scenario_name = "SCENARIO 3: INSIDE LOW CONE"
        description = "Price is inside the Asian low cone; buy the floor if it holds, sell the ceiling if it rejects."
        primary_play = _build_play(
            "CALL",
            "desc_floor",
            low_cone_floor,
            "lw",
            lw,
            "asc_floor",
            low_cone_ceiling,
            "desc_ceiling",
            high_cone_floor,
            3 if confirmation_confirmed else 2,
            "Low-cone floor buy if polarity confirms support.",
        )
        alternate_play = _build_play(
            "PUT",
            "asc_floor",
            low_cone_ceiling,
            "asc_ceiling" if low_ceiling_near_high else "hw",
            high_cone_ceiling if low_ceiling_near_high else hw,
            "desc_floor",
            low_cone_floor,
            "lw",
            lw,
            1,
            "Low-cone ceiling sell if polarity confirms rejection.",
        )
    elif above_high_cone:
        scenario_name = "SCENARIO 4: ABOVE HIGH CONE"
        description = "Price is completely above the high cone; only buy a retest of the high-cone ceiling."
        primary_play = _build_play(
            "CALL",
            "asc_ceiling",
            high_cone_ceiling,
            "desc_ceiling",
            high_cone_floor,
            "hw",
            hw,
            "hw + 10",
            hw + 10.0,
            2,
            "Buy only if the high-cone ceiling retests and holds as support.",
        )
    elif below_low_cone:
        scenario_name = "SCENARIO 5: BELOW LOW CONE"
        description = "Price is completely below the low cone; only sell a retest of the low-cone floor."
        primary_play = _build_play(
            "PUT",
            "desc_floor",
            low_cone_floor,
            "asc_floor",
            low_cone_ceiling,
            "lw",
            lw,
            "lw - 10",
            lw - 10.0,
            2,
            "Sell only if the low-cone floor retests and rejects as resistance.",
        )
    else:
        raise ValueError("Price could not be classified into the cone framework.")

    confidence_level, contract_count = _scenario_confidence(scenario_name, confirmation_confirmed)
    if primary_play is not None:
        primary_play["contracts"] = contract_count

    return {
        "scenario_name": scenario_name,
        "description": description,
        "color": SCENARIO_COLORS[scenario_name],
        "scenario_state": scenario_name.split(":")[0].strip(),
        "current_price": price,
        "primary_trade_direction": primary_play["direction"] if primary_play else None,
        "alternate_trade": alternate_play["direction"] if alternate_play else None,
        "confidence_level": confidence_level,
        "channel_widths": {
            "ascending": round_price(asc_ceiling - asc_floor),
            "descending": round_price(desc_ceiling - desc_floor),
        },
        "ordered_lines": boundaries,
        "primary_play": primary_play,
        "alternate_play": alternate_play,
        "inside_ascending": in_high_cone,
        "inside_descending": in_low_cone,
        "between_channels": between_cones,
        "inside_high_cone": in_high_cone,
        "inside_low_cone": in_low_cone,
        "between_cones": between_cones,
        "cone_overlap": cones_overlap,
        "above_high_cone": above_high_cone,
        "below_low_cone": below_low_cone,
        "cone_model": {
            "high_cone": {"floor": "desc_ceiling", "ceiling": "asc_ceiling"},
            "low_cone": {"floor": "desc_floor", "ceiling": "asc_floor"},
        },
    }


def evaluate_830_confirmation(candle: dict[str, Any] | None, entry_line_price: float, direction: str) -> dict[str, Any]:
    """Evaluate the 8:30 AM SPX candle against the entry line."""

    if candle is None:
        return {
            "available": False,
            "tested": False,
            "confirmed": False,
            "failed": False,
            "status": "No 8:30 AM SPX candle available",
            "entry_timing": "Wait for fresh retest",
        }

    open_price = float(candle["open"])
    high_price = float(candle["high"])
    low_price = float(candle["low"])
    close_price = float(candle["close"])
    line_price = float(entry_line_price)

    is_green = close_price > open_price
    is_red = close_price < open_price

    if direction == "PUT":
        # Resistance test: candle spiked up to the line; confirmed if close stayed below it
        tested = high_price >= line_price
        confirmed = tested and close_price < line_price
        failed = tested and close_price >= line_price
    elif direction == "CALL":
        # Support test: candle dipped down to the line; confirmed if close stayed above it
        tested = low_price <= line_price
        confirmed = tested and close_price > line_price
        failed = tested and close_price <= line_price
    else:
        raise ValueError("direction must be 'PUT' or 'CALL'")

    if confirmed:
        status = "8:30 confirmed"
        entry_timing = "Enter at 9:05 AM"
    elif failed:
        status = "8:30 test failed — line not holding"
        entry_timing = "Do not enter until properly retested"
    elif tested:
        status = "8:30 tested — candle closed at the line"
        entry_timing = "Wait for clean rejection before entry"
    else:
        status = "8:30 did not test the line"
        entry_timing = "Wait for the 9:00 candle to test; enter at 9:30 AM or 10:00 AM if confirmed"

    return {
        "available": True,
        "tested": tested,
        "confirmed": confirmed,
        "failed": failed,
        "status": status,
        "entry_timing": entry_timing,
        "candle": {
            "open": round_price(open_price),
            "high": round_price(high_price),
            "low": round_price(low_price),
            "close": round_price(close_price),
            "color": "green" if is_green else "red" if is_red else "neutral",
        },
    }


def evaluate_sit_out_conditions(
    scenario: dict[str, Any],
    confirmation: dict[str, Any],
    current_price: float,
    news_day: bool,
    current_time=None,
) -> dict[str, Any]:
    """Evaluate the global sit-out filters that suppress the trade card."""

    now_ct = to_central_time(current_time) if current_time is not None else current_central_time()
    reasons: list[str] = []

    narrowest_channel = min(
        float(scenario["channel_widths"]["ascending"]),
        float(scenario["channel_widths"]["descending"]),
    )
    if narrowest_channel < 3.0:
        reasons.append("Channel width is under 3 points.")

    primary_play = scenario.get("primary_play")
    if primary_play is not None:
        gap_distance = abs(float(current_price) - float(primary_play["entry"]["price"]))
        if gap_distance > 15.0:
            reasons.append("Price is more than 15 points from the nearest primary entry line.")
    else:
        gap_distance = 0.0

    if confirmation.get("failed") and scenario.get("between_cones"):
        reasons.append("8:30 confirmation failed while price is between cones.")

    if news_day:
        reasons.append("Fed/CPI/NFP day toggle is enabled.")

    time_cutoff = now_ct.replace(hour=10, minute=0, second=0, microsecond=0)
    if now_ct > time_cutoff:
        reasons.append("Past 10:00 AM CT.")

    return {
        "sit_out": bool(reasons),
        "reasons": reasons,
        "gap_distance": round_price(gap_distance),
        "narrowest_channel_width": round_price(narrowest_channel),
    }


def build_signal_package(
    current_price: float,
    line_values: dict[str, float],
    confirmation: dict[str, Any],
    news_day: bool = False,
    current_time=None,
    open_price: float | None = None,
) -> dict[str, Any]:
    """Build the final signal bundle used by the UI."""

    scenario = evaluate_trading_scenario(
        current_price=current_price,
        line_values=line_values,
        open_price=open_price,
        confirmation_confirmed=bool(confirmation.get("confirmed")),
    )
    sit_out = evaluate_sit_out_conditions(
        scenario=scenario,
        confirmation=confirmation,
        current_price=current_price,
        news_day=news_day,
        current_time=current_time,
    )

    primary_contracts = scenario["primary_play"]["contracts"] if scenario.get("primary_play") else 1

    return {
        "scenario": scenario,
        "confirmation": confirmation,
        "sit_out": sit_out,
        "profit_management": build_profit_management_plan(primary_contracts),
    }
