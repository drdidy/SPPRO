"""Historical date-flow checks for the SPX Prophet app layer."""

from __future__ import annotations

import unittest
from datetime import date, datetime

from app import build_projection_target, is_historical_projection_run, resolve_signal_evaluation_time
from core.projections import project_six_lines
from core.time_utils import CENTRAL_TZ


class AppHistoricalTests(unittest.TestCase):
    """Ensure the app uses selected next-trading-date targeting for historical runs."""

    def setUp(self) -> None:
        self.anchors = {
            "hw": {"price": 110.0, "timestamp": datetime(2020, 4, 9, 10, 0, tzinfo=CENTRAL_TZ), "projection_start_time": datetime(2020, 4, 9, 10, 0, tzinfo=CENTRAL_TZ), "direction": "ascending", "label": "HW"},
            "asc_ceiling": {"price": 108.0, "timestamp": datetime(2020, 4, 9, 15, 0, tzinfo=CENTRAL_TZ), "projection_start_time": datetime(2020, 4, 9, 15, 0, tzinfo=CENTRAL_TZ), "direction": "ascending", "label": "ASC Ceiling"},
            "asc_floor": {"price": 104.0, "timestamp": datetime(2020, 4, 9, 14, 0, tzinfo=CENTRAL_TZ), "projection_start_time": datetime(2020, 4, 9, 14, 0, tzinfo=CENTRAL_TZ), "direction": "ascending", "label": "ASC Floor"},
            "desc_ceiling": {"price": 108.0, "timestamp": datetime(2020, 4, 9, 15, 0, tzinfo=CENTRAL_TZ), "projection_start_time": datetime(2020, 4, 9, 15, 0, tzinfo=CENTRAL_TZ), "direction": "descending", "label": "DESC Ceiling"},
            "desc_floor": {"price": 104.0, "timestamp": datetime(2020, 4, 9, 14, 0, tzinfo=CENTRAL_TZ), "projection_start_time": datetime(2020, 4, 9, 14, 0, tzinfo=CENTRAL_TZ), "direction": "descending", "label": "DESC Floor"},
            "lw": {"price": 100.0, "timestamp": datetime(2020, 4, 9, 8, 0, tzinfo=CENTRAL_TZ), "projection_start_time": datetime(2020, 4, 9, 8, 0, tzinfo=CENTRAL_TZ), "direction": "descending", "label": "LW"},
        }

    def test_projection_target_is_selected_thursday_to_friday_nine_am(self) -> None:
        target = build_projection_target(date(2020, 4, 10))
        self.assertEqual(target, datetime(2020, 4, 10, 9, 0, tzinfo=CENTRAL_TZ))

    def test_projection_target_is_selected_friday_to_monday_nine_am(self) -> None:
        target = build_projection_target(date(2020, 4, 13))
        self.assertEqual(target, datetime(2020, 4, 13, 9, 0, tzinfo=CENTRAL_TZ))

    def test_projection_target_is_selected_weekday_to_weekday_nine_am(self) -> None:
        target = build_projection_target(date(2020, 4, 15))
        self.assertEqual(target, datetime(2020, 4, 15, 9, 0, tzinfo=CENTRAL_TZ))

    def test_historical_mode_detects_non_current_trading_date(self) -> None:
        self.assertTrue(is_historical_projection_run(date(2020, 4, 10), reference_date=date(2026, 4, 20)))
        self.assertFalse(is_historical_projection_run(date(2026, 4, 20), reference_date=date(2026, 4, 20)))

    def test_signal_time_uses_selected_target_for_historical_run(self) -> None:
        resolved = resolve_signal_evaluation_time(date(2020, 4, 10))
        self.assertEqual(resolved, datetime(2020, 4, 10, 9, 0, tzinfo=CENTRAL_TZ))

    def test_selected_target_changes_projected_values(self) -> None:
        friday_target = build_projection_target(date(2020, 4, 10))
        monday_target = build_projection_target(date(2020, 4, 13))

        friday_lines = project_six_lines(self.anchors, friday_target)
        monday_lines = project_six_lines(self.anchors, monday_target)

        self.assertNotEqual(friday_lines["asc_ceiling"]["projected_price"], monday_lines["asc_ceiling"]["projected_price"])
        self.assertEqual(friday_lines["asc_ceiling"]["target_time"], friday_target)
        self.assertEqual(monday_lines["asc_ceiling"]["target_time"], monday_target)


if __name__ == "__main__":
    unittest.main()
