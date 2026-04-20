"""Validation test for the SPX Prophet core projection engine."""

from __future__ import annotations

import unittest
from datetime import datetime

from core.pivots import resolve_anchor_prices
from core.projections import extract_projected_values, project_session_lines
from core.time_utils import CENTRAL_TZ, get_valid_candle_count


class ValidationCaseTest(unittest.TestCase):
    """Validate the reference Friday-to-Monday projection case."""

    def test_friday_to_monday_validation_case(self) -> None:
        friday_noon = datetime(2020, 4, 10, 12, 0, tzinfo=CENTRAL_TZ)
        friday_two_pm = datetime(2020, 4, 10, 14, 0, tzinfo=CENTRAL_TZ)
        monday_nine_am = datetime(2020, 4, 13, 9, 0, tzinfo=CENTRAL_TZ)

        high_candle_count = get_valid_candle_count(friday_noon, monday_nine_am)
        low_candle_count = get_valid_candle_count(friday_two_pm, monday_nine_am)

        self.assertEqual(high_candle_count, 20)
        self.assertEqual(low_candle_count, 18)

        pivot_high = {
            "pivot_time": friday_noon,
            "green_candle": {
                "timestamp": friday_noon,
                "high": 6857.70,
                "open": 6854.50,
                "close": 6856.20,
                "color": "green",
            },
            "red_candle": {
                "timestamp": friday_two_pm,
                "high": 6859.50,
                "open": 6859.10,
                "close": 6857.25,
                "color": "red",
            },
        }

        pivot_low = {
            "pivot_time": friday_two_pm,
            "red_candle": {
                "timestamp": friday_two_pm,
                "low": 6848.75,
                "open": 6851.90,
                "close": 6849.25,
                "color": "red",
            },
            "green_candle": {
                "timestamp": friday_noon,
                "low": 6851.00,
                "open": 6851.10,
                "close": 6853.30,
                "color": "green",
            },
        }

        anchors = resolve_anchor_prices(pivot_high, pivot_low)
        projected_lines = project_session_lines(
            anchors={name: details["price"] for name, details in anchors.items()},
            high_candle_count=high_candle_count,
            low_candle_count=low_candle_count,
        )
        projected_values = extract_projected_values(projected_lines)

        formatted = {name: f"{value:.2f}" for name, value in projected_values.items()}
        expected = {
            "asc_ceiling": "6880.30",
            "asc_floor": "6867.47",
            "desc_ceiling": "6836.90",
            "desc_floor": "6832.28",
        }

        self.assertDictEqual(formatted, expected)


if __name__ == "__main__":
    unittest.main()
