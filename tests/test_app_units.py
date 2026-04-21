"""App-layer unit consistency tests for SPX Prophet Tab 1."""

from __future__ import annotations

import unittest

from app import build_line_rows, get_structure_assertion_warnings, resolve_effective_offset, resolve_play_display_values


class AppUnitTests(unittest.TestCase):
    """Validate ES structure display and one-time SPX conversion behavior."""

    def setUp(self) -> None:
        self.original_lines_es = {
            "hw": {"label": "HW", "projected_price": 7207.59, "raw_anchor_price": 7185.75, "anchor_price": 7185.75, "candle_count": 21, "direction": "ascending", "line_type": "session_extreme"},
            "asc_ceiling": {"label": "ASC Ceiling", "projected_price": 7206.55, "raw_anchor_price": 7185.75, "anchor_price": 7185.75, "candle_count": 20, "direction": "ascending", "line_type": "channel"},
            "asc_floor": {"label": "ASC Floor", "projected_price": 7170.76, "raw_anchor_price": 7151.00, "anchor_price": 7151.00, "candle_count": 19, "direction": "ascending", "line_type": "channel"},
            "desc_ceiling": {"label": "DESC Ceiling", "projected_price": 7164.95, "raw_anchor_price": 7185.75, "anchor_price": 7185.75, "candle_count": 20, "direction": "descending", "line_type": "channel"},
            "desc_floor": {"label": "DESC Floor", "projected_price": 7131.24, "raw_anchor_price": 7151.00, "anchor_price": 7151.00, "candle_count": 19, "direction": "descending", "line_type": "channel"},
            "lw": {"label": "LW", "projected_price": 7117.58, "raw_anchor_price": 7141.50, "anchor_price": 7141.50, "candle_count": 23, "direction": "descending", "line_type": "session_extreme"},
        }
        self.override_decisions = {}

    def test_build_line_rows_uses_es_unit_labels(self) -> None:
        rows = build_line_rows(
            self.original_lines_es,
            self.original_lines_es,
            self.override_decisions,
            "ES",
        )

        first_row = rows[0]
        self.assertIn("Projected Level (ES)", first_row)
        self.assertIn("Raw Anchor (ES)", first_row)
        self.assertNotIn("Projected Level (SPX)", first_row)
        self.assertEqual(first_row["Projected Level (ES)"], "7,207.59")

    def test_structure_assertions_pass_for_valid_es_structure(self) -> None:
        warnings = get_structure_assertion_warnings(
            self.original_lines_es,
            self.original_lines_es,
            "ES",
        )
        self.assertEqual(warnings, [])

    def test_structure_assertions_flag_ac_above_hw_and_non_es_display(self) -> None:
        invalid_lines = {name: dict(details) for name, details in self.original_lines_es.items()}
        invalid_lines["asc_ceiling"]["projected_price"] = 7210.00
        displayed_lines = {name: dict(details) for name, details in invalid_lines.items()}
        displayed_lines["lw"]["projected_price"] = 7097.58

        warnings = get_structure_assertion_warnings(
            invalid_lines,
            displayed_lines,
            "SPX",
        )

        self.assertTrue(any("ASC Ceiling" in warning for warning in warnings))
        self.assertTrue(any("LW display mismatch" in warning for warning in warnings))
        self.assertTrue(any("single source of truth" in warning for warning in warnings))

    def test_trade_entry_display_uses_spx_line_once_and_blocks_invalid_stop(self) -> None:
        projected_lines_spx = {
            "lw": {"label": "LW", "projected_price": 7097.58},
        }
        play = {
            "direction": "CALL",
            "strike": 7120,
            "contracts": 2,
            "entry": {"label": "lw", "price": 0.0},
            "stop": {"label": "lw", "price": 0.0},
        }

        resolved = resolve_play_display_values(play, projected_lines_spx)

        self.assertEqual(resolved["entry"]["price"], 7097.58)
        self.assertIsNone(resolved["stop"])
        self.assertTrue(resolved["invalid_stop"])
        self.assertTrue(resolved["stop_unavailable"])
        self.assertFalse(resolved["setup_tradable"])
        self.assertIn("invalid_stop", resolved["integrity_flags"])
        self.assertIn("stop_unavailable", resolved["integrity_flags"])

    def test_live_effective_offset_prefers_live_inferred_offset(self) -> None:
        effective_offset, source, details = resolve_effective_offset(
            {
                "es_spx_offset": 20.0,
                "derived_live_offset": 33.75,
                "current_es_price": 7200.0,
                "current_spx_price": 7100.0,
                "historical_mode": False,
                "live_es_available": True,
                "live_spx_available": True,
            }
        )

        self.assertEqual(effective_offset, 33.75)
        self.assertEqual(source, "live_inferred_offset")
        self.assertEqual(details["manual_offset"], 20.0)
        self.assertEqual(details["live_inferred_offset"], 33.75)

    def test_historical_effective_offset_uses_manual_offset(self) -> None:
        effective_offset, source, details = resolve_effective_offset(
            {
                "es_spx_offset": 20.0,
                "derived_live_offset": 33.75,
                "current_es_price": 7200.0,
                "current_spx_price": 7100.0,
                "historical_mode": True,
                "live_es_available": True,
                "live_spx_available": True,
            }
        )

        self.assertEqual(effective_offset, 20.0)
        self.assertEqual(source, "manual_offset")
        self.assertEqual(details["effective_offset"], 20.0)


if __name__ == "__main__":
    unittest.main()
