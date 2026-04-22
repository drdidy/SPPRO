"""App-layer unit consistency tests for SPX Prophet Tab 1."""

from __future__ import annotations

import unittest
import app as app_module

from app import (
    align_play_conversion_to_effective_offset,
    build_selected_contract_binding,
    build_nearby_strike_ladder,
    build_line_rows,
    build_contract_selection_key,
    build_option_display_state,
    classify_budget_status,
    compute_live_scenario_snapshot,
    compute_live_structure_state,
    get_structure_assertion_warnings,
    resolve_effective_offset,
    resolve_live_current_spx,
    resolve_play_display_values,
    resolve_recommended_contract_row,
    resolve_selected_contract_row,
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
        self.option_candidates = [
            {"symbol": "SPXW 260422P07090000", "strike": 7090, "option_type": "PUT", "expiration": "2026-04-22", "mark": 17.0, "bid": 16.9, "ask": 17.1, "delta": -0.52, "predicted_entry_price": 10.5, "rr_ratio": 1.1, "contract_score": 0.61},
            {"symbol": "SPXW 260422P07095000", "strike": 7095, "option_type": "PUT", "expiration": "2026-04-22", "mark": 18.0, "bid": 17.9, "ask": 18.1, "delta": -0.55, "predicted_entry_price": 11.2, "rr_ratio": 1.2, "contract_score": 0.65},
            {"symbol": "SPXW 260422P07100000", "strike": 7100, "option_type": "PUT", "expiration": "2026-04-22", "mark": 21.0, "bid": 20.9, "ask": 21.1, "delta": -0.60, "predicted_entry_price": 13.09, "rr_ratio": 1.429, "contract_score": 0.91},
            {"symbol": "SPXW 260422P07105000", "strike": 7105, "option_type": "PUT", "expiration": "2026-04-22", "mark": 23.0, "bid": 22.9, "ask": 23.1, "delta": -0.63, "predicted_entry_price": 14.4, "rr_ratio": 1.31, "contract_score": 0.88},
            {"symbol": "SPXW 260422P07110000", "strike": 7110, "option_type": "PUT", "expiration": "2026-04-22", "mark": 25.0, "bid": 24.9, "ask": 25.1, "delta": -0.66, "predicted_entry_price": 16.0, "rr_ratio": 1.15, "contract_score": 0.80},
            {"symbol": "SPXW 260422C07100000", "strike": 7100, "option_type": "CALL", "expiration": "2026-04-22", "mark": 8.0, "bid": 7.9, "ask": 8.1, "delta": 0.32, "predicted_entry_price": 5.0, "rr_ratio": 0.7, "contract_score": 0.40},
            {"symbol": "SPXW 260423P07100000", "strike": 7100, "option_type": "PUT", "expiration": "2026-04-23", "mark": 28.0, "bid": 27.9, "ask": 28.1, "delta": -0.58, "predicted_entry_price": 17.0, "rr_ratio": 1.0, "contract_score": 0.50},
        ]
        app_module.st.session_state.setdefault("contract_override_store", {})
        app_module.st.session_state["contract_override_store"].clear()

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

    def test_nearby_ladder_builds_around_recommended_strike_same_type_and_expiration(self) -> None:
        recommended = self.option_candidates[2]
        ladder = build_nearby_strike_ladder(
            self.option_candidates,
            recommended,
            contracts=2,
            budget_cap=500.0,
            ladder_anchor_strike=7100,
        )

        self.assertEqual([row["strike"] for row in ladder], [7090, 7095, 7100, 7105, 7110])
        self.assertTrue(all(row["option_type"] == "PUT" for row in ladder))
        self.assertTrue(all(row["expiration"] == "2026-04-22" for row in ladder))

    def test_ladder_stays_centered_on_locked_anchor_after_refresh(self) -> None:
        recommended = self.option_candidates[2]
        refreshed = [dict(row) for row in self.option_candidates]
        refreshed[0]["mark"] = 19.5
        refreshed[4]["mark"] = 27.0

        ladder = build_nearby_strike_ladder(
            refreshed,
            recommended,
            contracts=1,
            budget_cap=500.0,
            ladder_anchor_strike=7100,
        )

        self.assertEqual([row["strike"] for row in ladder], [7090, 7095, 7100, 7105, 7110])

    def test_estimated_entry_cost_and_budget_labels_are_correct(self) -> None:
        recommended = self.option_candidates[2]
        ladder = build_nearby_strike_ladder(
            self.option_candidates,
            recommended,
            contracts=2,
            budget_cap=2500.0,
            ladder_anchor_strike=7100,
        )
        target_row = next(row for row in ladder if row["contract_symbol"] == "SPXW 260422P07100000")

        self.assertEqual(target_row["estimated_entry_cost"], 2618.0)
        self.assertEqual(target_row["budget_status"], "Near Budget")
        self.assertEqual(classify_budget_status(2000.0, 2500.0), "Within Budget")
        self.assertEqual(classify_budget_status(2600.0, 2500.0), "Near Budget")
        self.assertEqual(classify_budget_status(3000.0, 2500.0), "Above Budget")

    def test_manual_strike_selection_preserves_original_recommendation(self) -> None:
        selection_key = build_contract_selection_key(app_module.current_central_time().date(), "primary")
        app_module.st.session_state["contract_override_store"][selection_key] = "SPXW 260422P07095000"
        resolved = resolve_selected_contract_row(
            self.option_candidates,
            self.option_candidates[2],
            selection_key=selection_key,
        )

        self.assertTrue(resolved["manual_override"])
        self.assertEqual(resolved["user_selected_contract_symbol"], "SPXW 260422P07095000")
        self.assertEqual(self.option_candidates[2]["symbol"], "SPXW 260422P07100000")

    def test_manual_selected_contract_drives_display_binding_instead_of_recommended(self) -> None:
        play = {"strike": 7100, "direction": "PUT"}
        recommended_contract = {
            "contract_symbol": "SPXW 260422P07100000",
            "strike": 7100,
            "option_type": "PUT",
            "price": 21.0,
            "predicted_entry_price": 13.09,
            "rr_ratio": 1.429,
        }
        user_selected_contract = {
            "contract_symbol": "SPXW 260422P07095000",
            "strike": 7095,
            "option_type": "PUT",
            "price": 18.5,
            "predicted_entry_price": 11.4,
            "rr_ratio": 1.11,
        }

        payload = build_selected_contract_binding(play, user_selected_contract)
        validation = validate_contract_binding(user_selected_contract, payload)

        self.assertEqual(payload["displayed_contract_symbol"], "SPXW 260422P07095000")
        self.assertEqual(payload["displayed_strike"], 7095)
        self.assertEqual(payload["current_mark"], 18.5)
        self.assertEqual(payload["predicted_entry_price"], 11.4)
        self.assertNotEqual(payload["displayed_contract_symbol"], recommended_contract["contract_symbol"])
        self.assertNotEqual(payload["current_mark"], recommended_contract["price"])
        self.assertEqual(validation["binding_status"], "OK")

    def test_locked_contract_fallback_recenters_when_locked_symbol_disappears(self) -> None:
        session_plan = {"session_plan_locked": True, "contract_symbol": "SPXW 260422P07100000", "planned_strike": 7100}
        candidates_without_locked = [row for row in self.option_candidates if row["symbol"] != "SPXW 260422P07100000" and row["option_type"] == "PUT" and row["expiration"] == "2026-04-22"]

        resolved = resolve_recommended_contract_row(candidates_without_locked, session_plan=session_plan)

        self.assertTrue(resolved["fallback_used"])
        self.assertFalse(resolved["centered_from_locked_plan"])
        self.assertEqual(resolved["recommended_contract"]["symbol"], "SPXW 260422P07090000")

    def test_ladder_handles_fewer_than_five_strikes_on_one_side(self) -> None:
        recommended = self.option_candidates[0]
        limited = [row for row in self.option_candidates if row["option_type"] == "PUT" and row["expiration"] == "2026-04-22"]
        ladder = build_nearby_strike_ladder(
            limited,
            recommended,
            contracts=1,
            budget_cap=500.0,
            ladder_anchor_strike=7090,
        )

        self.assertEqual([row["strike"] for row in ladder], [7090, 7095, 7100, 7105, 7110])


if __name__ == "__main__":
    unittest.main()
