"""Focused hardening tests for the SPX Prophet core engine."""

from __future__ import annotations

import unittest
from datetime import datetime

import pandas as pd

from core.pivots import build_six_line_anchors, resolve_anchor_prices, select_pivot_context
from core.projections import apply_overnight_pivot_overrides, convert_projected_lines, project_anchor_line, project_six_lines
from core.scenarios import (
    build_profit_management_plan,
    calculate_option_strike,
    evaluate_830_confirmation,
    evaluate_sit_out_conditions,
    evaluate_trading_scenario,
    get_scenario_reference_outputs,
)
from core.time_utils import CENTRAL_TZ, EASTERN_TZ, get_valid_candle_count, market_time_to_central


class EngineRuleTests(unittest.TestCase):
    """Validate high-risk rule behavior directly."""

    def setUp(self) -> None:
        self.base_lines = {
            "hw": 110.0,
            "asc_ceiling": 108.0,
            "asc_floor": 104.0,
            "desc_ceiling": 100.0,
            "desc_floor": 96.0,
            "lw": 92.0,
        }

    def _projected_line(self, name: str, value: float) -> dict[str, float | str]:
        return {
            "name": name,
            "label": name.upper(),
            "projected_price": value,
        }

    def test_candle_count_excludes_maintenance_and_weekend(self) -> None:
        monday_four_pm = datetime(2020, 4, 6, 16, 0, tzinfo=CENTRAL_TZ)
        monday_six_pm = datetime(2020, 4, 6, 18, 0, tzinfo=CENTRAL_TZ)
        self.assertEqual(get_valid_candle_count(monday_four_pm, monday_six_pm), 1)

        friday_noon = datetime(2020, 4, 10, 12, 0, tzinfo=CENTRAL_TZ)
        monday_nine_am = datetime(2020, 4, 13, 9, 0, tzinfo=CENTRAL_TZ)
        self.assertEqual(get_valid_candle_count(friday_noon, monday_nine_am), 20)

    def test_market_time_conversion_uses_eastern_for_market_timestamps(self) -> None:
        eastern_open = datetime(2026, 4, 13, 9, 30, tzinfo=EASTERN_TZ)
        converted = market_time_to_central(eastern_open)
        self.assertEqual(converted.hour, 8)
        self.assertEqual(converted.minute, 30)
        self.assertEqual(converted.tzinfo, CENTRAL_TZ)

    def test_pivot_context_follows_green_and_red_selection_rules(self) -> None:
        previous = {
            "timestamp": datetime(2026, 4, 10, 12, 0, tzinfo=CENTRAL_TZ),
            "open": 100.0,
            "high": 104.0,
            "low": 99.0,
            "close": 103.0,
        }
        pivot = {
            "timestamp": datetime(2026, 4, 10, 13, 0, tzinfo=CENTRAL_TZ),
            "open": 103.0,
            "high": 106.0,
            "low": 102.0,
            "close": 102.5,
        }
        following = {
            "timestamp": datetime(2026, 4, 10, 14, 0, tzinfo=CENTRAL_TZ),
            "open": 102.5,
            "high": 103.0,
            "low": 99.5,
            "close": 100.0,
        }

        context = select_pivot_context(previous, pivot, following)
        self.assertEqual(context["green_candle"]["timestamp"], previous["timestamp"])
        self.assertEqual(context["red_candle"]["timestamp"], pivot["timestamp"])

    def test_projection_uses_projection_start_time_not_source_timestamp(self) -> None:
        target = datetime(2020, 4, 13, 9, 0, tzinfo=CENTRAL_TZ)
        line = project_anchor_line(
            "asc_ceiling",
            {
                "price": 6859.50,
                "timestamp": datetime(2020, 4, 10, 14, 0, tzinfo=CENTRAL_TZ),
                "projection_start_time": datetime(2020, 4, 10, 12, 0, tzinfo=CENTRAL_TZ),
                "direction": "ascending",
                "label": "ASC Ceiling",
            },
            target,
        )
        self.assertEqual(line["candle_count"], 20)
        self.assertEqual(f"{line['projected_price']:.2f}", "6880.30")
        self.assertEqual(line["anchor_timestamp"].hour, 14)
        self.assertEqual(line["projection_start_time"].hour, 12)
        self.assertEqual(line["raw_anchor_timestamp"].hour, 14)
        self.assertEqual(f"{line['raw_anchor_price']:.2f}", "6859.50")

    def test_pivot_derived_anchors_use_true_pivot_extremes(self) -> None:
        pivot_high = {
            "pivot_time": datetime(2020, 4, 10, 12, 0, tzinfo=CENTRAL_TZ),
            "pivot_extreme": {
                "timestamp": datetime(2020, 4, 10, 13, 0, tzinfo=CENTRAL_TZ),
                "high": 110.0,
                "low": 101.0,
                "open": 103.0,
                "close": 102.0,
                "color": "red",
            },
            "green_candle": {
                "timestamp": datetime(2020, 4, 10, 12, 0, tzinfo=CENTRAL_TZ),
                "high": 108.0,
                "low": 100.0,
                "open": 100.5,
                "close": 105.0,
                "color": "green",
            },
            "red_candle": {
                "timestamp": datetime(2020, 4, 10, 13, 0, tzinfo=CENTRAL_TZ),
                "high": 109.0,
                "low": 101.0,
                "open": 108.5,
                "close": 102.0,
                "color": "red",
            },
        }
        pivot_low = {
            "pivot_time": datetime(2020, 4, 10, 14, 0, tzinfo=CENTRAL_TZ),
            "pivot_extreme": {
                "timestamp": datetime(2020, 4, 10, 15, 0, tzinfo=CENTRAL_TZ),
                "high": 103.0,
                "low": 94.0,
                "open": 96.0,
                "close": 97.0,
                "color": "green",
            },
            "red_candle": {
                "timestamp": datetime(2020, 4, 10, 14, 0, tzinfo=CENTRAL_TZ),
                "high": 101.0,
                "low": 95.0,
                "open": 100.0,
                "close": 96.0,
                "color": "red",
            },
            "green_candle": {
                "timestamp": datetime(2020, 4, 10, 15, 0, tzinfo=CENTRAL_TZ),
                "high": 103.0,
                "low": 96.0,
                "open": 96.0,
                "close": 97.0,
                "color": "green",
            },
        }

        anchors = resolve_anchor_prices(pivot_high, pivot_low)

        self.assertEqual(anchors["asc_ceiling_anchor"]["price"], 110.0)
        self.assertEqual(anchors["desc_ceiling_anchor"]["price"], 110.0)
        self.assertEqual(anchors["asc_floor_anchor"]["price"], 94.0)
        self.assertEqual(anchors["desc_floor_anchor"]["price"], 94.0)
        self.assertEqual(anchors["asc_floor_anchor"]["timestamp"], datetime(2020, 4, 10, 15, 0, tzinfo=CENTRAL_TZ))
        self.assertEqual(anchors["desc_floor_anchor"]["timestamp"], datetime(2020, 4, 10, 15, 0, tzinfo=CENTRAL_TZ))
        self.assertEqual(anchors["asc_floor_anchor"]["anchor_basis"], "pivot_low_extreme")
        self.assertEqual(anchors["desc_ceiling_anchor"]["anchor_basis"], "pivot_high_extreme")

    def test_build_six_line_anchors_uses_true_pivot_extremes(self) -> None:
        candles = pd.DataFrame(
            [
                {"timestamp": datetime(2020, 4, 10, 11, 0, tzinfo=CENTRAL_TZ), "open": 100.0, "high": 104.0, "low": 99.0, "close": 103.0},
                {"timestamp": datetime(2020, 4, 10, 12, 0, tzinfo=CENTRAL_TZ), "open": 103.0, "high": 108.0, "low": 102.0, "close": 107.0},
                {"timestamp": datetime(2020, 4, 10, 13, 0, tzinfo=CENTRAL_TZ), "open": 107.0, "high": 109.0, "low": 103.0, "close": 108.0},
                {"timestamp": datetime(2020, 4, 10, 14, 0, tzinfo=CENTRAL_TZ), "open": 108.0, "high": 110.0, "low": 101.0, "close": 104.0},
                {"timestamp": datetime(2020, 4, 10, 15, 0, tzinfo=CENTRAL_TZ), "open": 101.0, "high": 103.0, "low": 94.0, "close": 95.0},
                {"timestamp": datetime(2020, 4, 10, 16, 0, tzinfo=CENTRAL_TZ), "open": 95.0, "high": 99.0, "low": 96.0, "close": 98.0},
                {"timestamp": datetime(2020, 4, 10, 8, 30, tzinfo=CENTRAL_TZ), "open": 99.0, "high": 100.0, "low": 98.0, "close": 99.5},
                {"timestamp": datetime(2020, 4, 10, 9, 30, tzinfo=CENTRAL_TZ), "open": 99.5, "high": 101.0, "low": 97.5, "close": 100.0},
                {"timestamp": datetime(2020, 4, 10, 10, 30, tzinfo=CENTRAL_TZ), "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0},
            ]
        )

        result = build_six_line_anchors(candles, datetime(2020, 4, 10, 0, 0, tzinfo=CENTRAL_TZ).date())

        self.assertEqual(result["pivot_high"]["pivot_extreme"]["timestamp"], datetime(2020, 4, 10, 14, 0, tzinfo=CENTRAL_TZ))
        self.assertEqual(result["pivot_low"]["pivot_extreme"]["timestamp"], datetime(2020, 4, 10, 15, 0, tzinfo=CENTRAL_TZ))
        self.assertEqual(result["anchors"]["asc_ceiling"]["price"], 110.0)
        self.assertEqual(result["anchors"]["desc_ceiling"]["price"], 110.0)
        self.assertEqual(result["anchors"]["asc_floor"]["price"], 94.0)
        self.assertEqual(result["anchors"]["desc_floor"]["price"], 94.0)
        self.assertEqual(result["source_points"]["pivot_high"]["price"], 110.0)
        self.assertEqual(result["source_points"]["pivot_low"]["price"], 94.0)

    def test_hw_projects_upward_across_friday_to_monday(self) -> None:
        target = datetime(2020, 4, 13, 9, 0, tzinfo=CENTRAL_TZ)
        line = project_anchor_line(
            "hw",
            {
                "price": 6864.50,
                "timestamp": datetime(2020, 4, 10, 13, 0, tzinfo=CENTRAL_TZ),
                "projection_start_time": datetime(2020, 4, 10, 13, 0, tzinfo=CENTRAL_TZ),
                "direction": "ascending",
                "label": "HW",
                "line_type": "session_extreme",
            },
            target,
        )
        self.assertEqual(line["candle_count"], 19)
        self.assertEqual(f"{line['projected_price']:.2f}", "6884.26")
        self.assertEqual(f"{line['raw_anchor_price']:.2f}", "6864.50")

    def test_lw_projects_downward_across_friday_to_monday(self) -> None:
        target = datetime(2020, 4, 13, 9, 0, tzinfo=CENTRAL_TZ)
        line = project_anchor_line(
            "lw",
            {
                "price": 6840.25,
                "timestamp": datetime(2020, 4, 10, 10, 0, tzinfo=CENTRAL_TZ),
                "projection_start_time": datetime(2020, 4, 10, 10, 0, tzinfo=CENTRAL_TZ),
                "direction": "descending",
                "label": "LW",
                "line_type": "session_extreme",
            },
            target,
        )
        self.assertEqual(line["candle_count"], 22)
        self.assertEqual(f"{line['projected_price']:.2f}", "6817.37")
        self.assertEqual(f"{line['raw_anchor_price']:.2f}", "6840.25")
        self.assertLess(line["projected_price"], line["raw_anchor_price"])

    def test_session_wick_extremes_use_830_am_to_400_pm_window(self) -> None:
        candles = pd.DataFrame(
            [
                {"timestamp": datetime(2020, 4, 10, 8, 30, tzinfo=CENTRAL_TZ), "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0},
                {"timestamp": datetime(2020, 4, 10, 9, 30, tzinfo=CENTRAL_TZ), "open": 101.0, "high": 103.0, "low": 100.5, "close": 102.0},
                {"timestamp": datetime(2020, 4, 10, 10, 30, tzinfo=CENTRAL_TZ), "open": 102.0, "high": 104.0, "low": 100.0, "close": 103.0},
                {"timestamp": datetime(2020, 4, 10, 11, 0, tzinfo=CENTRAL_TZ), "open": 103.0, "high": 104.0, "low": 100.0, "close": 101.0},
                {"timestamp": datetime(2020, 4, 10, 12, 0, tzinfo=CENTRAL_TZ), "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
                {"timestamp": datetime(2020, 4, 10, 13, 0, tzinfo=CENTRAL_TZ), "open": 100.0, "high": 103.0, "low": 99.5, "close": 102.0},
                {"timestamp": datetime(2020, 4, 10, 14, 0, tzinfo=CENTRAL_TZ), "open": 99.0, "high": 102.5, "low": 98.0, "close": 101.0},
                {"timestamp": datetime(2020, 4, 10, 14, 30, tzinfo=CENTRAL_TZ), "open": 99.0, "high": 106.0, "low": 98.5, "close": 98.0},
                {"timestamp": datetime(2020, 4, 10, 15, 30, tzinfo=CENTRAL_TZ), "open": 98.0, "high": 107.0, "low": 90.0, "close": 101.0},
            ]
        )

        result = build_six_line_anchors(candles, datetime(2020, 4, 10, 0, 0, tzinfo=CENTRAL_TZ).date())

        self.assertEqual(result["session_extremes"]["hw_anchor"]["timestamp"], datetime(2020, 4, 10, 15, 30, tzinfo=CENTRAL_TZ))
        self.assertEqual(result["session_extremes"]["lw_anchor"]["timestamp"], datetime(2020, 4, 10, 15, 30, tzinfo=CENTRAL_TZ))
        self.assertEqual(f"{result['session_extremes']['hw_anchor']['price']:.2f}", "107.00")
        self.assertEqual(f"{result['session_extremes']['lw_anchor']['price']:.2f}", "90.00")
        self.assertEqual(result["ny_session_rows"], 9)
        self.assertEqual(result["source_points"]["pivot_highest_wick"]["price"], 107.00)
        self.assertEqual(result["source_points"]["pivot_lowest_wick"]["price"], 90.00)

    def test_hw_and_lw_projection_metadata_from_session_extremes(self) -> None:
        target = datetime(2020, 4, 13, 9, 0, tzinfo=CENTRAL_TZ)
        hw_line = project_anchor_line(
            "hw",
            {
                "price": 6864.50,
                "timestamp": datetime(2020, 4, 10, 14, 30, tzinfo=CENTRAL_TZ),
                "projection_start_time": datetime(2020, 4, 10, 14, 30, tzinfo=CENTRAL_TZ),
                "direction": "ascending",
                "label": "HW",
                "line_type": "session_extreme",
            },
            target,
        )
        lw_line = project_anchor_line(
            "lw",
            {
                "price": 6840.25,
                "timestamp": datetime(2020, 4, 10, 14, 0, tzinfo=CENTRAL_TZ),
                "projection_start_time": datetime(2020, 4, 10, 14, 0, tzinfo=CENTRAL_TZ),
                "direction": "descending",
                "label": "LW",
                "line_type": "session_extreme",
            },
            target,
        )

        self.assertEqual(hw_line["direction"], "ascending")
        self.assertEqual(lw_line["direction"], "descending")
        self.assertGreater(hw_line["projected_price"], hw_line["raw_anchor_price"])
        self.assertLess(lw_line["projected_price"], lw_line["raw_anchor_price"])

    def test_projected_hw_stays_at_or_above_projected_ac(self) -> None:
        target = datetime(2020, 4, 13, 9, 0, tzinfo=CENTRAL_TZ)
        projected = project_six_lines(
            {
                "hw": {
                    "price": 7185.75,
                    "timestamp": datetime(2020, 4, 10, 11, 0, tzinfo=CENTRAL_TZ),
                    "projection_start_time": datetime(2020, 4, 10, 11, 0, tzinfo=CENTRAL_TZ),
                    "direction": "ascending",
                    "label": "HW",
                    "line_type": "session_extreme",
                },
                "asc_ceiling": {
                    "price": 7185.75,
                    "timestamp": datetime(2020, 4, 10, 11, 0, tzinfo=CENTRAL_TZ),
                    "projection_start_time": datetime(2020, 4, 10, 12, 0, tzinfo=CENTRAL_TZ),
                    "direction": "ascending",
                    "label": "ASC Ceiling",
                    "line_type": "channel",
                },
                "asc_floor": {
                    "price": 7151.00,
                    "timestamp": datetime(2020, 4, 10, 14, 0, tzinfo=CENTRAL_TZ),
                    "projection_start_time": datetime(2020, 4, 10, 13, 0, tzinfo=CENTRAL_TZ),
                    "direction": "ascending",
                    "label": "ASC Floor",
                    "line_type": "channel",
                },
                "desc_ceiling": {
                    "price": 7185.75,
                    "timestamp": datetime(2020, 4, 10, 11, 0, tzinfo=CENTRAL_TZ),
                    "projection_start_time": datetime(2020, 4, 10, 12, 0, tzinfo=CENTRAL_TZ),
                    "direction": "descending",
                    "label": "DESC Ceiling",
                    "line_type": "channel",
                },
                "desc_floor": {
                    "price": 7151.00,
                    "timestamp": datetime(2020, 4, 10, 14, 0, tzinfo=CENTRAL_TZ),
                    "projection_start_time": datetime(2020, 4, 10, 13, 0, tzinfo=CENTRAL_TZ),
                    "direction": "descending",
                    "label": "DESC Floor",
                    "line_type": "channel",
                },
                "lw": {
                    "price": 7141.50,
                    "timestamp": datetime(2020, 4, 10, 9, 0, tzinfo=CENTRAL_TZ),
                    "projection_start_time": datetime(2020, 4, 10, 9, 0, tzinfo=CENTRAL_TZ),
                    "direction": "descending",
                    "label": "LW",
                    "line_type": "session_extreme",
                },
            },
            target,
        )

        self.assertGreaterEqual(projected["hw"]["projected_price"], projected["asc_ceiling"]["projected_price"])
        self.assertLessEqual(projected["lw"]["projected_price"], projected["asc_floor"]["projected_price"])
        self.assertLessEqual(projected["lw"]["projected_price"], projected["desc_floor"]["projected_price"])

    def test_converted_lines_preserve_raw_anchor_fields(self) -> None:
        converted = convert_projected_lines(
            {
                "hw": {
                    "name": "hw",
                    "label": "HW",
                    "direction": "ascending",
                    "raw_anchor_price": 6864.50,
                    "raw_anchor_timestamp": datetime(2020, 4, 10, 13, 0, tzinfo=CENTRAL_TZ),
                    "anchor_price": 6864.50,
                    "anchor_timestamp": datetime(2020, 4, 10, 13, 0, tzinfo=CENTRAL_TZ),
                    "projection_start_time": datetime(2020, 4, 10, 13, 0, tzinfo=CENTRAL_TZ),
                    "source": None,
                    "line_type": "session_extreme",
                    "candle_count": 19,
                    "target_time": datetime(2020, 4, 13, 9, 0, tzinfo=CENTRAL_TZ),
                    "projected_price": 6884.26,
                    "description": "",
                }
            },
            36.30,
            "spx",
        )
        self.assertEqual(f"{converted['hw']['raw_anchor_price']:.2f}", "6828.20")
        self.assertEqual(f"{converted['hw']['projected_price']:.2f}", "6847.96")

    def test_overnight_pivot_high_extends_ascending_ceiling_outward(self) -> None:
        result = apply_overnight_pivot_overrides(
            {name: self._projected_line(name, value) for name, value in self.base_lines.items()},
            overnight_high={"asc_ceiling": self._projected_line("asc_ceiling", 109.5)},
        )
        self.assertTrue(result["decisions"]["asc_ceiling"]["applied"])
        self.assertEqual(result["projected_lines"]["asc_ceiling"]["projected_price"], 109.5)

    def test_overnight_pivot_high_extends_descending_ceiling_outward(self) -> None:
        result = apply_overnight_pivot_overrides(
            {name: self._projected_line(name, value) for name, value in self.base_lines.items()},
            overnight_high={"desc_ceiling": self._projected_line("desc_ceiling", 101.5)},
        )
        self.assertTrue(result["decisions"]["desc_ceiling"]["applied"])
        self.assertEqual(result["projected_lines"]["desc_ceiling"]["projected_price"], 101.5)

    def test_overnight_pivot_low_extends_ascending_floor_outward(self) -> None:
        result = apply_overnight_pivot_overrides(
            {name: self._projected_line(name, value) for name, value in self.base_lines.items()},
            overnight_low={"asc_floor": self._projected_line("asc_floor", 103.0)},
        )
        self.assertTrue(result["decisions"]["asc_floor"]["applied"])
        self.assertEqual(result["projected_lines"]["asc_floor"]["projected_price"], 103.0)

    def test_overnight_pivot_low_extends_descending_floor_outward(self) -> None:
        result = apply_overnight_pivot_overrides(
            {name: self._projected_line(name, value) for name, value in self.base_lines.items()},
            overnight_low={"desc_floor": self._projected_line("desc_floor", 95.0)},
        )
        self.assertTrue(result["decisions"]["desc_floor"]["applied"])
        self.assertEqual(result["projected_lines"]["desc_floor"]["projected_price"], 95.0)

    def test_overnight_pivot_inside_channel_does_not_override(self) -> None:
        result = apply_overnight_pivot_overrides(
            {name: self._projected_line(name, value) for name, value in self.base_lines.items()},
            overnight_high={"asc_ceiling": self._projected_line("asc_ceiling", 107.0)},
            overnight_low={"asc_floor": self._projected_line("asc_floor", 105.0)},
        )
        self.assertFalse(result["decisions"]["asc_ceiling"]["applied"])
        self.assertFalse(result["decisions"]["asc_floor"]["applied"])
        self.assertEqual(result["projected_lines"]["asc_ceiling"]["projected_price"], 108.0)
        self.assertEqual(result["projected_lines"]["asc_floor"]["projected_price"], 104.0)

    def test_scenario_1_between_channels_output(self) -> None:
        scenario = evaluate_trading_scenario(102.0, self.base_lines)
        self.assertEqual(scenario["scenario_name"], "SCENARIO 1: BETWEEN CHANNELS")
        self.assertEqual(scenario["primary_play"]["entry"]["label"], "asc_floor")
        self.assertEqual(scenario["primary_play"]["stop"]["label"], "asc_ceiling")
        self.assertEqual(scenario["alternate_play"]["entry"]["label"], "desc_ceiling")
        self.assertEqual(scenario["confidence_level"], "MEDIUM")

    def test_scenario_2_inside_ascending_channel_output(self) -> None:
        scenario = evaluate_trading_scenario(106.0, self.base_lines, confirmation_confirmed=True)
        self.assertEqual(scenario["scenario_name"], "SCENARIO 2: INSIDE ASCENDING CHANNEL")
        self.assertEqual(scenario["primary_play"]["entry"]["label"], "asc_ceiling")
        self.assertEqual(scenario["primary_play"]["stop"]["label"], "hw")
        self.assertEqual(scenario["alternate_play"]["direction"], "CALL")
        self.assertEqual(scenario["confidence_level"], "HIGH")

    def test_scenario_3_inside_descending_channel_output(self) -> None:
        scenario = evaluate_trading_scenario(
            98.0,
            {
                "hw": 112.0,
                "asc_ceiling": 111.0,
                "asc_floor": 107.0,
                "desc_ceiling": 100.0,
                "desc_floor": 96.0,
                "lw": 92.0,
            },
            confirmation_confirmed=True,
        )
        self.assertEqual(scenario["scenario_name"], "SCENARIO 3: INSIDE DESCENDING CHANNEL")
        self.assertEqual(scenario["primary_play"]["entry"]["label"], "desc_floor")
        self.assertEqual(scenario["primary_play"]["stop"]["label"], "lw")
        self.assertEqual(scenario["alternate_play"]["direction"], "PUT")
        self.assertEqual(scenario["confidence_level"], "HIGH")

    def test_scenario_4_above_ascending_channel_output(self) -> None:
        scenario = evaluate_trading_scenario(109.0, self.base_lines)
        self.assertEqual(scenario["scenario_name"], "SCENARIO 4: ABOVE ASCENDING CHANNEL")
        self.assertEqual(scenario["primary_play"]["entry"]["label"], "hw")
        self.assertEqual(scenario["primary_play"]["stop"]["label"], "hw + 3")
        self.assertEqual(scenario["alternate_play"]["entry"]["label"], "asc_ceiling")
        self.assertEqual(scenario["confidence_level"], "MEDIUM")

    def test_scenario_5_below_descending_channel_output(self) -> None:
        scenario = evaluate_trading_scenario(94.0, self.base_lines)
        self.assertEqual(scenario["scenario_name"], "SCENARIO 5: BELOW DESCENDING CHANNEL")
        self.assertEqual(scenario["primary_play"]["entry"]["label"], "lw")
        self.assertEqual(scenario["primary_play"]["stop"]["label"], "lw - 3")
        self.assertEqual(scenario["alternate_play"]["entry"]["label"], "desc_floor")
        self.assertEqual(scenario["confidence_level"], "MEDIUM")

    def test_scenario_6a_extreme_gap_up_output(self) -> None:
        scenario = evaluate_trading_scenario(111.0, self.base_lines, open_price=111.0)
        self.assertEqual(scenario["scenario_name"], "SCENARIO 6a: EXTREME GAP UP")
        self.assertEqual(scenario["primary_play"]["entry"]["label"], "hw")
        self.assertEqual(scenario["primary_play"]["stop"]["label"], "asc_ceiling")
        self.assertIsNone(scenario["alternate_play"])
        self.assertEqual(scenario["confidence_level"], "LOW")

    def test_scenario_6b_extreme_gap_down_output(self) -> None:
        scenario = evaluate_trading_scenario(91.0, self.base_lines, open_price=91.0)
        self.assertEqual(scenario["scenario_name"], "SCENARIO 6b: EXTREME GAP DOWN")
        self.assertEqual(scenario["primary_play"]["entry"]["label"], "lw")
        self.assertEqual(scenario["primary_play"]["stop"]["label"], "desc_floor")
        self.assertIsNone(scenario["alternate_play"])
        self.assertEqual(scenario["confidence_level"], "LOW")

    def test_scenario_7_overlap_output(self) -> None:
        scenario = evaluate_trading_scenario(
            101.0,
            {
                "hw": 112.0,
                "asc_ceiling": 104.0,
                "asc_floor": 99.0,
                "desc_ceiling": 103.0,
                "desc_floor": 98.0,
                "lw": 92.0,
            },
        )
        self.assertEqual(scenario["scenario_name"], "SCENARIO 7: CHANNEL OVERLAP (COMPRESSION)")
        self.assertEqual(scenario["primary_play"]["direction"], "PUT")
        self.assertEqual(scenario["alternate_play"]["direction"], "CALL")
        self.assertEqual(scenario["confidence_level"], "MEDIUM")

    def test_scenario_reference_outputs_cover_all_states(self) -> None:
        reference = get_scenario_reference_outputs()
        self.assertEqual(len(reference), 8)
        self.assertIn("SCENARIO 6a: EXTREME GAP UP", reference)
        self.assertIn("SCENARIO 6b: EXTREME GAP DOWN", reference)

    def test_valid_put_confirmation(self) -> None:
        result = evaluate_830_confirmation(
            {"open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0},
            entry_line_price=104.5,
            direction="PUT",
        )
        self.assertTrue(result["confirmed"])

    def test_failed_put_confirmation_closes_above_line(self) -> None:
        result = evaluate_830_confirmation(
            {"open": 100.0, "high": 105.0, "low": 99.0, "close": 105.0},
            entry_line_price=104.5,
            direction="PUT",
        )
        self.assertTrue(result["failed"])
        self.assertFalse(result["confirmed"])

    def test_failed_put_confirmation_red_below_line(self) -> None:
        result = evaluate_830_confirmation(
            {"open": 105.0, "high": 105.5, "low": 100.0, "close": 103.0},
            entry_line_price=104.5,
            direction="PUT",
        )
        self.assertTrue(result["failed"])
        self.assertFalse(result["confirmed"])

    def test_valid_call_confirmation(self) -> None:
        result = evaluate_830_confirmation(
            {"open": 100.0, "high": 101.0, "low": 95.0, "close": 99.0},
            entry_line_price=96.0,
            direction="CALL",
        )
        self.assertTrue(result["confirmed"])

    def test_failed_call_confirmation_closes_below_line(self) -> None:
        result = evaluate_830_confirmation(
            {"open": 100.0, "high": 101.0, "low": 95.0, "close": 95.5},
            entry_line_price=96.0,
            direction="CALL",
        )
        self.assertTrue(result["failed"])
        self.assertFalse(result["confirmed"])

    def test_failed_call_confirmation_green_above_line(self) -> None:
        result = evaluate_830_confirmation(
            {"open": 95.0, "high": 101.0, "low": 94.5, "close": 99.0},
            entry_line_price=96.0,
            direction="CALL",
        )
        self.assertTrue(result["failed"])
        self.assertFalse(result["confirmed"])

    def test_sit_out_channel_width_under_three(self) -> None:
        scenario = evaluate_trading_scenario(
            102.0,
            {
                "hw": 110.0,
                "asc_ceiling": 104.5,
                "asc_floor": 102.0,
                "desc_ceiling": 101.0,
                "desc_floor": 99.0,
                "lw": 95.0,
            },
        )
        result = evaluate_sit_out_conditions(scenario, {"failed": False}, 102.0, False, datetime(2026, 4, 13, 9, 0, tzinfo=CENTRAL_TZ))
        self.assertTrue(result["sit_out"])
        self.assertIn("Channel width is under 3 points.", result["reasons"])

    def test_sit_out_price_more_than_fifteen_points_from_entry(self) -> None:
        scenario = evaluate_trading_scenario(102.0, self.base_lines)
        result = evaluate_sit_out_conditions(scenario, {"failed": False}, 125.0, False, datetime(2026, 4, 13, 9, 0, tzinfo=CENTRAL_TZ))
        self.assertTrue(result["sit_out"])
        self.assertIn("Price is more than 15 points from the nearest primary entry line.", result["reasons"])

    def test_sit_out_failed_confirmation_between_channels(self) -> None:
        scenario = evaluate_trading_scenario(102.0, self.base_lines)
        result = evaluate_sit_out_conditions(scenario, {"failed": True}, 102.0, False, datetime(2026, 4, 13, 9, 0, tzinfo=CENTRAL_TZ))
        self.assertTrue(result["sit_out"])
        self.assertIn("8:30 confirmation failed while price is between channels.", result["reasons"])

    def test_sit_out_major_news_toggle_enabled(self) -> None:
        scenario = evaluate_trading_scenario(102.0, self.base_lines)
        result = evaluate_sit_out_conditions(scenario, {"failed": False}, 102.0, True, datetime(2026, 4, 13, 9, 0, tzinfo=CENTRAL_TZ))
        self.assertTrue(result["sit_out"])
        self.assertIn("Fed/CPI/NFP day toggle is enabled.", result["reasons"])

    def test_sit_out_past_ten_am_ct(self) -> None:
        scenario = evaluate_trading_scenario(102.0, self.base_lines)
        result = evaluate_sit_out_conditions(scenario, {"failed": False}, 102.0, False, datetime(2026, 4, 13, 10, 1, tzinfo=CENTRAL_TZ))
        self.assertTrue(result["sit_out"])
        self.assertIn("Past 10:00 AM CT.", result["reasons"])

    def test_put_strike_rounds_down_to_nearest_five(self) -> None:
        self.assertEqual(calculate_option_strike("PUT", 4321.25), 4300)

    def test_call_strike_rounds_up_to_nearest_five(self) -> None:
        self.assertEqual(calculate_option_strike("CALL", 4321.25), 4345)

    def test_position_sizing_high_confidence(self) -> None:
        scenario = evaluate_trading_scenario(106.0, self.base_lines, confirmation_confirmed=True)
        self.assertEqual(scenario["primary_play"]["contracts"], 3)

    def test_position_sizing_medium_confidence(self) -> None:
        scenario = evaluate_trading_scenario(102.0, self.base_lines)
        self.assertEqual(scenario["primary_play"]["contracts"], 2)

    def test_position_sizing_low_confidence(self) -> None:
        scenario = evaluate_trading_scenario(111.0, self.base_lines, open_price=111.0)
        self.assertEqual(scenario["primary_play"]["contracts"], 1)

    def test_position_sizing_alternate_plays_are_always_one_contract(self) -> None:
        scenario = evaluate_trading_scenario(102.0, self.base_lines)
        self.assertEqual(scenario["alternate_play"]["contracts"], 1)

    def test_profit_management_returns_machine_usable_structure(self) -> None:
        plan = build_profit_management_plan(3)
        self.assertEqual(plan["tp1_action"]["action"], "close_partial")
        self.assertEqual(plan["tp1_action"]["contracts_to_close"], 2)
        self.assertTrue(plan["tp1_action"]["move_stop_to_breakeven"])
        self.assertEqual(plan["tp2_action"]["action"], "close_remaining")
        self.assertEqual(plan["tp2_action"]["contracts_to_close"], 1)
        self.assertEqual(plan["stop_action"]["action"], "close_all")
        self.assertEqual(plan["time_stop"], "10:30 AM CT")
        self.assertEqual(plan["time_stop_action"]["deadline"], "10:30 AM CT")


if __name__ == "__main__":
    unittest.main()
