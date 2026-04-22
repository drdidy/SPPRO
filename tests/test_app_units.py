"""App-layer unit consistency tests for SPX Prophet Tab 1."""

from __future__ import annotations

import unittest

from app import (
    align_play_conversion_to_effective_offset,
    build_selected_contract_binding,
    build_line_rows,
    compute_live_scenario_snapshot,
    compute_live_structure_state,
    get_structure_assertion_warnings,
    resolve_effective_offset,
    resolve_live_current_spx,
    resolve_play_display_values,
    validate_contract_binding,
)


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

    def test_live_effective_offset_uses_manual_offset(self) -> None:
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

        self.assertEqual(effective_offset, 20.0)
        self.assertEqual(source, "manual_offset")
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

    def test_play_conversion_aligns_spx_entry_to_es_minus_offset(self) -> None:
        play_spx = {
            "entry": {"label": "desc_floor", "price": 7113.57},
            "stop": {"label": "asc_floor", "price": 7150.00},
        }
        play_es = {
            "entry": {"label": "desc_floor", "price": 7178.18},
            "stop": {"label": "asc_floor", "price": 7210.25},
        }

        aligned = align_play_conversion_to_effective_offset(play_spx, play_es, 39.5)

        self.assertEqual(aligned["entry"]["price"], 7138.68)
        self.assertTrue(aligned["conversion_invalid"])
        self.assertAlmostEqual(aligned["conversion_debug"]["entry"]["additional_adjustment_applied"], -25.11, places=2)

    def test_live_structure_state_reports_between_channels(self) -> None:
        line_values = {name: details["projected_price"] for name, details in self.original_lines_es.items()}

        snapshot = compute_live_structure_state(7168.00, line_values)

        self.assertEqual(snapshot["live_structure_state"], "BETWEEN_CHANNELS")

    def test_live_current_spx_prefers_es_minus_effective_offset(self) -> None:
        resolved = resolve_live_current_spx(7178.18, 39.5, 7120.07)

        self.assertEqual(resolved, 7138.68)

    def test_live_scenario_snapshot_remaps_inside_descending(self) -> None:
        line_values = {name: details["projected_price"] for name, details in self.original_lines_es.items()}

        snapshot = compute_live_scenario_snapshot(
            current_price=7140.00,
            line_values=line_values,
            open_price=7145.00,
            scenario_origin="SCENARIO 1: BETWEEN CHANNELS",
            previous_live_scenario="SCENARIO 1: BETWEEN CHANNELS",
            previous_structure_state="BETWEEN_CHANNELS",
            confirmation_confirmed=False,
            timestamp="2026-04-22T09:05:00-05:00",
        )

        self.assertEqual(snapshot["live_structure_state"], "INSIDE_DESC_CHANNEL")
        self.assertEqual(snapshot["live_scenario"], "SCENARIO 3: INSIDE DESCENDING CHANNEL")
        self.assertEqual(snapshot["scenario_transition"], "SCENARIO 1: BETWEEN CHANNELS -> SCENARIO 3: INSIDE DESCENDING CHANNEL")
        self.assertEqual(snapshot["structure_transition"], "BETWEEN_CHANNELS -> INSIDE_DESC_CHANNEL")

    def test_selected_contract_binding_uses_selected_symbol_metrics_for_same_strike(self) -> None:
        play = {"strike": 7100, "direction": "PUT"}
        selected_contract = {
            "contract_symbol": "SPXW 260422P07100000",
            "strike": 7100,
            "option_type": "PUT",
            "price": 21.0,
            "bid": 20.9,
            "ask": 21.1,
            "predicted_entry_price": 13.09,
            "rr_ratio": 1.429,
        }

        payload = build_selected_contract_binding(play, selected_contract)

        self.assertEqual(payload["displayed_contract_symbol"], "SPXW 260422P07100000")
        self.assertEqual(payload["displayed_strike"], 7100)
        self.assertEqual(payload["current_mark"], 21.0)
        self.assertEqual(payload["predicted_entry_price"], 13.09)

    def test_selected_contract_binding_updates_visible_strike_when_selected_contract_changes(self) -> None:
        play = {"strike": 7100, "direction": "PUT"}
        selected_contract = {
            "contract_symbol": "SPXW 260422P07110000",
            "strike": 7110,
            "option_type": "PUT",
            "price": 16.5,
            "predicted_entry_price": 10.2,
        }

        payload = build_selected_contract_binding(play, selected_contract)
        validation = validate_contract_binding(selected_contract, payload)

        self.assertEqual(payload["displayed_strike"], 7110)
        self.assertEqual(payload["displayed_contract_symbol"], "SPXW 260422P07110000")
        self.assertEqual(validation["binding_status"], "OK")

    def test_binding_validator_catches_strike_and_symbol_mismatch(self) -> None:
        selected_contract = {
            "contract_symbol": "SPXW 260422P07100000",
            "strike": 7100,
        }
        displayed_payload = {
            "displayed_contract_symbol": "SPXW 260422P07110000",
            "displayed_strike": 7110,
            "source_contract_symbol": "SPXW 260422P07110000",
        }

        validation = validate_contract_binding(selected_contract, displayed_payload)

        self.assertEqual(validation["binding_status"], "MISMATCH")
        self.assertIn("symbol_mismatch", validation["errors"])
        self.assertIn("strike_mismatch", validation["errors"])

    def test_stale_play_strike_cannot_override_new_selected_contract(self) -> None:
        stale_play = {"strike": 7100, "direction": "PUT"}
        new_selected_contract = {
            "contract_symbol": "SPXW 260422P07110000",
            "strike": 7110,
            "price": 18.0,
        }

        payload = build_selected_contract_binding(stale_play, new_selected_contract)

        self.assertEqual(payload["displayed_strike"], 7110)
        self.assertEqual(payload["current_mark"], 18.0)


if __name__ == "__main__":
    unittest.main()
