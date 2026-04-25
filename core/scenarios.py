"""Scenario, confirmation, and trade-plan logic for SPX Prophet."""

from __future__ import annotations

from typing import Any

from core.projections import round_price
from core.time_utils import current_central_time, to_central_time

NEARBY_BOUNDARY_THRESHOLD = 5.0

SCENARIO_COLORS = {
    "SCENARIO 1: BETWEEN CHANNELS": "#00d4ff",
    "SCENARIO 2: INSIDE ASCENDING CHANNEL": "#00e676",
    "SCENARIO 3: INSIDE DESCENDING CHANNEL": "#ff1744",
    "SCENARIO 4: ABOVE ASCENDING CHANNEL": "#ffd740",
    "SCENARIO 5: BELOW DESCENDING CHANNEL": "#ffd740",
    "SCENARIO 6a: EXTREME GAP UP": "#ffd740",
    "SCENARIO 6b: EXTREME GAP DOWN": "#ffd740",
    "SCENARIO 7: CHANNEL OVERLAP (COMPRESSION)": "#b388ff",
}


def get_scenario_reference_outputs() -> dict[str, dict[str, Any]]:
    """Return the final structured scenario definitions used by the engine."""

    return {
        "SCENARIO 1: BETWEEN CHANNELS": {
            "primary": {"direction": "PUT", "entry": "asc_floor", "stop": "asc_ceiling"},
            "alternate": {"direction": "CALL", "entry": "desc_ceiling", "stop": "desc_floor"},
            "confidence": "MEDIUM",
        },
        "SCENARIO 2: INSIDE ASCENDING CHANNEL": {
            "primary": {"direction": "CALL", "entry": "asc_floor", "stop": "desc_floor"},
            "alternate": {"direction": "PUT", "entry": "asc_ceiling", "stop": "hw"},
            "confidence": "HIGH with confirmation, otherwise MEDIUM",
        },
        "SCENARIO 3: INSIDE DESCENDING CHANNEL": {
            "primary": {"direction": "PUT", "entry": "desc_ceiling", "stop": "asc_ceiling"},
            "alternate": {"direction": "CALL", "entry": "desc_floor", "stop": "lw"},
            "confidence": "HIGH with confirmation, otherwise MEDIUM",
        },
        "SCENARIO 4: ABOVE ASCENDING CHANNEL": {
            "primary": {"direction": "PUT", "entry": "hw", "stop": "hw_plus_3"},
            "alternate": {"direction": "CALL", "entry": "asc_ceiling", "stop": "asc_floor"},
            "confidence": "MEDIUM",
        },
        "SCENARIO 5: BELOW DESCENDING CHANNEL": {
            "primary": {"direction": "CALL", "entry": "lw", "stop": "lw_minus_3"},
            "alternate": {"direction": "PUT", "entry": "desc_floor", "stop": "desc_ceiling"},
            "confidence": "MEDIUM",
        },
        "SCENARIO 6a: EXTREME GAP UP": {
            "primary": {"direction": "CALL", "entry": "hw", "stop": "asc_ceiling"},
            "alternate": None,
            "confidence": "LOW",
        },
        "SCENARIO 6b: EXTREME GAP DOWN": {
            "primary": {"direction": "PUT", "entry": "lw", "stop": "desc_floor"},
            "alternate": None,
            "confidence": "LOW",
        },
        "SCENARIO 7: CHANNEL OVERLAP (COMPRESSION)": {
            "primary": {"direction": "PUT", "entry": "nearest_boundary_above", "stop": "next_boundary_out_above"},
            "alternate": {"direction": "CALL", "entry": "nearest_boundary_below", "stop": "next_boundary_out_below"},
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

    if scenario_name in {"SCENARIO 2: INSIDE ASCENDING CHANNEL", "SCENARIO 3: INSIDE DESCENDING CHANNEL"} and confirmed:
        return "HIGH", 3
    if scenario_name in {"SCENARIO 6a: EXTREME GAP UP", "SCENARIO 6b: EXTREME GAP DOWN"}:
        return "LOW", 1
    return "MEDIUM", 2


def _is_descending_boundary_near_ascending_channel(desc_ceiling: float, asc_floor: float, asc_ceiling: float) -> bool:
    """Return True when the descending ceiling is inside or near the ascending channel."""

    return asc_floor <= desc_ceiling <= asc_ceiling or abs(desc_ceiling - asc_floor) <= NEARBY_BOUNDARY_THRESHOLD


def _is_ascending_boundary_near_descending_channel(asc_floor: float, desc_floor: float, desc_ceiling: float) -> bool:
    """Return True when the ascending floor is inside or near the descending channel."""

    return desc_floor <= asc_floor <= desc_ceiling or abs(asc_floor - desc_ceiling) <= NEARBY_BOUNDARY_THRESHOLD


def evaluate_trading_scenario(
    current_price: float,
    line_values: dict[str, float],
    open_price: float | None = None,
    confirmation_confirmed: bool = False,
) -> dict[str, Any]:
    """Implement the seven trading scenarios exactly from the spec."""

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

    in_ascending = asc_floor <= price <= asc_ceiling
    in_descending = desc_floor <= price <= desc_ceiling
    between_channels = desc_ceiling < price < asc_floor
    above_ascending = asc_ceiling < price < hw
    below_descending = lw < price < desc_floor

    descending_near_asc = _is_descending_boundary_near_ascending_channel(desc_ceiling, asc_floor, asc_ceiling)
    ascending_near_desc = _is_ascending_boundary_near_descending_channel(asc_floor, desc_floor, desc_ceiling)
    boundaries = _sorted_boundaries(line_values)

    scenario_name = ""
    description = ""
    primary_play: dict[str, Any] | None = None
    alternate_play: dict[str, Any] | None = None

    if in_ascending and in_descending:
        scenario_name = "SCENARIO 7: CHANNEL OVERLAP (COMPRESSION)"
        description = "Price is inside both channels, so the closest boundary above is the put line and the closest boundary below is the call line."
        channel_lines = {
            "asc_ceiling": asc_ceiling,
            "asc_floor": asc_floor,
            "desc_ceiling": desc_ceiling,
            "desc_floor": desc_floor,
        }
        ordered = _sorted_boundaries(channel_lines)
        above_lines = [(name, value) for name, value in ordered if value >= price]
        below_lines = [(name, value) for name, value in ordered if value <= price]
        put_entry = above_lines[-1] if above_lines else ordered[-1]
        call_entry = below_lines[0] if below_lines else ordered[0]
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
            "Compression setup: fade the nearest resistance above price.",
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
            "Compression setup: buy the nearest support below price.",
        )
    elif between_channels:
        scenario_name = "SCENARIO 1: BETWEEN CHANNELS"
        description = "Price is below the ascending floor and above the descending ceiling."
        primary_play = _build_play(
            "PUT",
            "asc_floor",
            asc_floor,
            "asc_ceiling",
            asc_ceiling,
            "desc_ceiling",
            desc_ceiling,
            "desc_floor",
            desc_floor,
            2,
            "Primary fade back into the descending channel from ascending resistance.",
        )
        alternate_play = _build_play(
            "CALL",
            "desc_ceiling",
            desc_ceiling,
            "desc_floor",
            desc_floor,
            "asc_floor",
            asc_floor,
            "asc_ceiling",
            asc_ceiling,
            1,
            "Alternate bounce from descending support if price flushes first.",
        )
    elif in_ascending:
        scenario_name = "SCENARIO 2: INSIDE ASCENDING CHANNEL"
        description = "Price is inside the ascending channel but not inside the descending channel."
        primary_play = _build_play(
            "CALL",
            "asc_floor",
            asc_floor,
            "desc_floor" if descending_near_asc else "lw",
            desc_floor if descending_near_asc else lw,
            "asc_ceiling",
            asc_ceiling,
            "hw",
            hw,
            3 if confirmation_confirmed else 2,
            "Bullish continuation from ascending support.",
        )
        alternate_play = _build_play(
            "PUT",
            "asc_ceiling",
            asc_ceiling,
            "hw",
            hw,
            "asc_floor",
            asc_floor,
            "desc_ceiling",
            desc_ceiling,
            1,
            "Countertrend fade only if ascending ceiling rejects as resistance.",
        )
    elif in_descending:
        scenario_name = "SCENARIO 3: INSIDE DESCENDING CHANNEL"
        description = "Price is inside the descending channel but not inside the ascending channel."
        primary_play = _build_play(
            "PUT",
            "desc_ceiling",
            desc_ceiling,
            "asc_ceiling" if ascending_near_desc else "hw",
            asc_ceiling if ascending_near_desc else hw,
            "desc_floor",
            desc_floor,
            "lw",
            lw,
            3 if confirmation_confirmed else 2,
            "Bearish continuation from descending resistance.",
        )
        alternate_play = _build_play(
            "CALL",
            "desc_floor",
            desc_floor,
            "lw",
            lw,
            "desc_ceiling",
            desc_ceiling,
            "asc_floor",
            asc_floor,
            1,
            "Countertrend bounce only if descending floor holds as support.",
        )
    elif above_ascending:
        scenario_name = "SCENARIO 4: ABOVE ASCENDING CHANNEL"
        description = "Price is above the ascending channel but below the HW line."
        primary_play = _build_play(
            "PUT",
            "hw",
            hw,
            "hw + 3",
            hw + 3.0,
            "asc_ceiling",
            asc_ceiling,
            "asc_floor",
            asc_floor,
            2,
            "Use the highest wick line as the final resistance zone.",
        )
        alternate_play = _build_play(
            "CALL",
            "asc_ceiling",
            asc_ceiling,
            "asc_floor",
            asc_floor,
            "hw",
            hw,
            "hw + 10",
            hw + 10.0,
            1,
            "If the ascending ceiling flips to support, trade the pullback bounce.",
        )
    elif below_descending:
        scenario_name = "SCENARIO 5: BELOW DESCENDING CHANNEL"
        description = "Price is below the descending channel but above the LW line."
        primary_play = _build_play(
            "CALL",
            "lw",
            lw,
            "lw - 3",
            lw - 3.0,
            "desc_floor",
            desc_floor,
            "desc_ceiling",
            desc_ceiling,
            2,
            "Use the lowest wick line as the last support zone.",
        )
        alternate_play = _build_play(
            "PUT",
            "desc_floor",
            desc_floor,
            "desc_ceiling",
            desc_ceiling,
            "lw",
            lw,
            "lw - 10",
            lw - 10.0,
            1,
            "If descending floor flips to resistance, fade the bounce.",
        )
    elif price >= hw:
        scenario_name = "SCENARIO 6a: EXTREME GAP UP"
        description = "Price is above HW. Treat it as a trend day up with HW now acting as support."
        primary_play = _build_play(
            "CALL",
            "hw",
            hw,
            "asc_ceiling",
            asc_ceiling,
            "open + 10",
            open_reference + 10.0,
            "open + 20",
            open_reference + 20.0,
            1,
            "All structure is broken to the upside. Buy the HW pullback if it holds.",
        )
    else:
        scenario_name = "SCENARIO 6b: EXTREME GAP DOWN"
        description = "Price is below LW. Treat it as a trend day down with LW now acting as resistance."
        primary_play = _build_play(
            "PUT",
            "lw",
            lw,
            "desc_floor",
            desc_floor,
            "open - 10",
            open_reference - 10.0,
            "open - 20",
            open_reference - 20.0,
            1,
            "All structure is broken to the downside. Fade the LW bounce if it fails.",
        )

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
        "inside_ascending": in_ascending,
        "inside_descending": in_descending,
        "between_channels": between_channels,
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

    if confirmation.get("failed") and scenario.get("between_channels"):
        reasons.append("8:30 confirmation failed while price is between channels.")

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
