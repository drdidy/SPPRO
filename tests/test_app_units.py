"""App-layer unit consistency tests for SPX Prophet Tab 1."""

from __future__ import annotations

from datetime import date
import unittest
import app as app_module
import pandas as pd

from app import (
    _non_negative_option_price,
    align_play_conversion_to_effective_offset,
    apply_event_risk_to_execution_guidance,
    build_anchor_candidate_table,
    build_ladder_display_dataframe,
    build_line_polarity_decision,
    build_render_fallback_payload,
    build_top_level_tab_labels,
    build_entry_zone_model,
    build_execution_checklist,
    build_execution_state,
    build_live_play_trade_prefill,
    build_selected_contract_binding,
    build_stop_target_authority,
    build_nearby_strike_ladder,
    build_line_rows,
    build_contract_selection_key,
    build_option_display_state,
    choose_execution_contract_from_ladder,
    classify_trigger_state,
    classify_budget_status,
    compute_preview_pnl,
    compute_live_scenario_snapshot,
    compute_live_structure_state,
    evaluate_play_outcome,
    estimate_option_price_at_time,
    estimate_contract_value_at_planned_entry,
    get_structure_assertion_warnings,
    resolve_effective_offset,
    resolve_hero_action_label,
    resolve_live_current_spx,
    resolve_play_display_values,
    resolve_recommended_contract_row,
    resolve_trade_direction_display,
    normalize_result_value,
    normalize_trade_record,
    resolve_locked_anchor_bundle,
    resolve_selected_contract_row,
    summarize_event_risk,
    validate_contract_binding,
    evaluate_line_polarity,
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
        app_module.st.session_state.setdefault("anchor_selection_store", {})
        app_module.st.session_state["anchor_selection_store"].clear()

    def _build_anchor_candidate_frame(
        self,
        *,
        pm_low: float = 7131.9,
        asian_low: float = 7125.2,
        london_low: float = 7127.4,
    ) -> pd.DataFrame:
        prior_session_date = date(2026, 4, 22)
        next_trading_date = date(2026, 4, 23)
        rows: list[dict[str, float | object]] = []

        def add(ts, close: float) -> None:
            rows.append(
                {
                    "timestamp": ts,
                    "open": close - 0.25,
                    "high": close + 0.5,
                    "low": close - 0.5,
                    "close": close,
                }
            )

        for hour, close in [
            (8, 7146.0),
            (9, 7144.0),
            (10, 7147.0),
            (11, 7145.0),
            (12, 7140.0),
            (13, pm_low),
            (14, 7150.0),
            (15, 7142.0),
            (16, 7144.0),
            (17, 7130.0),
            (18, asian_low),
            (19, 7132.0),
            (20, 7131.0),
            (21, 7130.0),
            (22, 7129.5),
            (23, 7130.0),
        ]:
            add(app_module.at_central(prior_session_date, hour, 0), close)

        for hour, close in [
            (0, 7129.0),
            (1, 7130.0),
            (2, 7131.0),
            (3, london_low),
            (4, 7132.0),
            (5, 7133.0),
            (6, 7134.0),
            (7, 7135.0),
            (8, 7136.0),
        ]:
            add(app_module.at_central(next_trading_date, hour, 0), close)

        return pd.DataFrame(rows)

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

    def test_trade_direction_display_includes_hero_headline(self) -> None:
        self.assertEqual(resolve_trade_direction_display("CALL")["headline"], "BUY CALL")
        self.assertEqual(resolve_trade_direction_display("PUT")["headline"], "BUY PUT")
        self.assertEqual(resolve_trade_direction_display("")["headline"], "WAIT")

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
        session_plan = {
            "session_plan_locked": True,
            "contract_symbol": "SPXW 260422P07100000",
            "planned_strike": 7100,
            "option_type": "PUT",
            "expiration": "2026-04-22",
        }
        candidates_without_locked = [row for row in self.option_candidates if row["symbol"] != "SPXW 260422P07100000" and row["option_type"] == "PUT" and row["expiration"] == "2026-04-22"]

        resolved = resolve_recommended_contract_row(candidates_without_locked, session_plan=session_plan)

        self.assertTrue(resolved["fallback_used"])
        self.assertTrue(resolved["centered_from_locked_plan"])
        self.assertIsNone(resolved["recommended_contract"])
        self.assertTrue(resolved["recommended_unavailable"])
        self.assertEqual(resolved["fallback_contract"]["symbol"], "SPXW 260422P07095000")

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

    def test_trade_prefill_preserves_recommended_and_selected_contract_identity(self) -> None:
        signal_package = {"scenario": {"scenario_name": "SCENARIO 2: INSIDE ASCENDING CHANNEL", "confidence_level": "High"}}
        play_spx = {"direction": "PUT", "strike": 7100, "contracts": 2, "entry": {"label": "desc_floor", "price": 7120.0}, "stop": {"price": 7158.0}}
        play_es = {"entry": {"price": 7159.5}}
        recommended_quote = {
            "contract_symbol": "SPXW 260422P07100000",
            "strike": 7100,
            "option_type": "PUT",
            "expiration": "2026-04-22",
        }
        selected_quote = {
            "contract_symbol": "SPXW 260422P07095000",
            "strike": 7095,
            "option_type": "PUT",
            "expiration": "2026-04-22",
            "price": 18.0,
            "predicted_entry_price": 11.2,
            "estimated_entry_cost": 2240.0,
            "estimated_fill_cost": 2300.0,
            "budget_status": "Within Budget",
        }
        intelligence = {
            "planned_entry_mark": 13.0,
            "live_predicted_entry_mark": 13.0,
            "locked_entry_spx": 7120.0,
            "lock_cutoff_label": "8:25 AM CT",
            "session_plan_locked": True,
            "locked_timestamp": "2026-04-22T08:25:00-05:00",
            "entry_zone_status": "APPROACHING",
            "move_completion_pct": 22.0,
            "regime": "PULLBACK",
            "plan_status": "HOLDING",
            "chase_status": "WAIT",
            "prediction_confidence": "MEDIUM",
            "stop_quality": "Balanced",
            "quality": "Acceptable",
        }

        prefill = build_live_play_trade_prefill(
            signal_package=signal_package,
            play_type="primary",
            play_spx=play_spx,
            play_es=play_es,
            lead_option_quote=selected_quote,
            recommended_contract_quote=recommended_quote,
            intelligence=intelligence,
            final_status="ELIGIBLE",
            selection_context={"manual_override": True, "ladder_anchor_strike": 7100},
        )

        self.assertEqual(prefill["recommended_contract_symbol"], "SPXW 260422P07100000")
        self.assertEqual(prefill["recommended_strike"], 7100)
        self.assertEqual(prefill["operator_selected_contract_symbol"], "SPXW 260422P07095000")
        self.assertEqual(prefill["operator_selected_strike"], 7095)
        self.assertTrue(prefill["manual_strike_override"])
        self.assertEqual(prefill["estimated_entry_cost"], 2240.0)
        self.assertEqual(prefill["budget_status"], "Within Budget")
        self.assertEqual(prefill["ladder_anchor_strike"], 7100)

    def test_non_negative_option_price_clamps_invalid_negative_premiums(self) -> None:
        self.assertEqual(_non_negative_option_price(-19.53), 0.0)
        self.assertEqual(_non_negative_option_price(-2.37), 0.0)
        self.assertEqual(_non_negative_option_price(4.25), 4.25)

    def test_option_trade_preview_pnl_uses_spx_contract_multiplier(self) -> None:
        self.assertEqual(compute_preview_pnl("CALL", 2.0, 3.0, 2), 200.0)
        self.assertEqual(compute_preview_pnl("PUT", 5.0, 4.0, 1), -100.0)
        self.assertEqual(compute_preview_pnl("LONG", 7100.0, 7105.0, 1), 5.0)

    def test_blank_trade_result_remains_unreviewed(self) -> None:
        self.assertEqual(normalize_result_value(""), "Unreviewed")
        self.assertEqual(normalize_trade_record({"trade_date": "2026-04-22", "session": "NY Options", "scenario_name": "Scenario", "direction": "CALL", "entry_line_label": "asc_floor"})["result"], "Unreviewed")

    def test_intelligence_tab_is_edge_lab_only(self) -> None:
        self.assertEqual(build_top_level_tab_labels("Production Mode"), ["LIVE MODE", "HISTORICAL", "TRADE LOG"])
        self.assertEqual(build_top_level_tab_labels("Edge Lab"), ["LIVE MODE", "HISTORICAL", "TRADE LOG", "INTELLIGENCE"])

    def test_trade_record_preserves_forward_pricing_and_anchor_metadata(self) -> None:
        record = normalize_trade_record(
            {
                "trade_date": "2026-04-22",
                "session": "NY Options",
                "scenario_name": "SCENARIO 2: INSIDE ASCENDING CHANNEL",
                "direction": "CALL",
                "entry_line_label": "asc_floor",
                "entry_line_value": 7120.0,
                "entry_value": 4.8,
                "exit_value": 5.2,
                "contracts": 1,
                "projected_mark_at_entry": 5.1,
                "projected_fill_at_entry": 5.25,
                "premium_projection_confidence": "medium",
                "selected_anchor_source": "ASIAN",
                "selected_anchor_price": 7125.2,
                "selected_anchor_time": "2026-04-21T18:00:00-05:00",
                "selected_anchor_confidence": "MEDIUM",
                "alternative_anchor_sources": ["PM_WINDOW", "LONDON"],
                "anchor_selection_reason": "Asian pivot line respected first.",
                "anchor_override_used": False,
            }
        )

        self.assertEqual(record["projected_mark_at_entry"], 5.1)
        self.assertEqual(record["projected_fill_at_entry"], 5.25)
        self.assertEqual(record["premium_projection_confidence"], "medium")
        self.assertEqual(record["selected_anchor_source"], "ASIAN")
        self.assertEqual(record["selected_anchor_price"], 7125.2)
        self.assertEqual(record["alternative_anchor_sources"], ["PM_WINDOW", "LONDON"])
        self.assertEqual(record["anchor_selection_reason"], "Asian pivot line respected first.")

    def test_historical_play_outcome_requires_polarity_retest_after_extended_reaction(self) -> None:
        play = {
            "direction": "CALL",
            "entry": {"label": "asc_floor", "price": 100.0},
            "stop": {"label": "stop", "price": 95.0},
            "tp1": {"label": "tp1", "price": 110.0},
            "tp2": {"label": "tp2", "price": 115.0},
            "contracts": 1,
        }
        projected = {"asc_floor": {"label": "asc_floor", "projected_price": 100.0, "line_type": "ascending"}}
        candles = pd.DataFrame(
            [
                {"timestamp": pd.Timestamp("2026-04-22 08:00"), "open": 100.0, "high": 106.0, "low": 99.5, "close": 105.0},
                {"timestamp": pd.Timestamp("2026-04-22 09:00"), "open": 103.0, "high": 102.0, "low": 99.75, "close": 101.0},
                {"timestamp": pd.Timestamp("2026-04-22 10:00"), "open": 101.0, "high": 111.0, "low": 100.5, "close": 110.0},
            ]
        )

        outcome = evaluate_play_outcome(play, projected, candles)

        self.assertTrue(outcome["entry_triggered"])
        self.assertTrue(outcome["tp1_hit"])
        self.assertEqual(outcome["result_classification"], "TP1")
        self.assertEqual(outcome["entry_confirmation"]["polarity_state"], "support_hold")

    def test_historical_play_outcome_blocks_extended_reaction_without_retest(self) -> None:
        play = {
            "direction": "CALL",
            "entry": {"label": "asc_floor", "price": 100.0},
            "stop": {"label": "stop", "price": 95.0},
            "tp1": {"label": "tp1", "price": 110.0},
            "tp2": {"label": "tp2", "price": 115.0},
            "contracts": 1,
        }
        projected = {"asc_floor": {"label": "asc_floor", "projected_price": 100.0, "line_type": "ascending"}}
        candles = pd.DataFrame(
            [
                {"timestamp": pd.Timestamp("2026-04-22 08:00"), "open": 100.0, "high": 106.0, "low": 99.5, "close": 105.0},
                {"timestamp": pd.Timestamp("2026-04-22 09:00"), "open": 105.0, "high": 111.0, "low": 104.0, "close": 110.0},
            ]
        )

        outcome = evaluate_play_outcome(play, projected, candles)

        self.assertFalse(outcome["entry_triggered"])
        self.assertEqual(outcome["result_classification"], "Not Triggered")

    def test_nearby_ladder_clamps_negative_predicted_values_and_costs(self) -> None:
        candidates = [dict(row) for row in self.option_candidates if row["option_type"] == "PUT" and row["expiration"] == "2026-04-22"]
        candidates[1]["predicted_entry_price"] = -19.53
        calibration_overlays = {
            "SPXW 260422P07095000": {"expected_fill_mark": -3.91},
        }

        ladder = build_nearby_strike_ladder(
            candidates,
            candidates[2],
            contracts=2,
            budget_cap=500.0,
            ladder_anchor_strike=7100,
            calibration_overlays=calibration_overlays,
        )
        target_row = next(row for row in ladder if row["contract_symbol"] == "SPXW 260422P07095000")

        self.assertEqual(target_row["predicted_entry_price"], 0.0)
        self.assertEqual(target_row["expected_fill_mark"], 0.0)
        self.assertEqual(target_row["estimated_entry_cost"], 0.0)
        self.assertEqual(target_row["estimated_fill_cost"], 0.0)

    def test_entry_zone_status_behaves_deterministically_around_locked_entry(self) -> None:
        in_zone = build_entry_zone_model(
            locked_entry_spx=7120.0,
            current_spx_price=7121.0,
            direction="PUT",
            stop_spx=7158.0,
            move_completion_pct=10.0,
        )
        missed = build_entry_zone_model(
            locked_entry_spx=7120.0,
            current_spx_price=7100.0,
            direction="PUT",
            stop_spx=7158.0,
            move_completion_pct=65.0,
        )

        self.assertEqual(in_zone["status"], "IN_ZONE")
        self.assertEqual(missed["status"], "MISSED")
        self.assertGreater(in_zone["width"], 0.0)

    def test_trigger_state_transitions_cover_ready_triggered_and_invalidated(self) -> None:
        zone = {"status": "NEAR_ZONE", "width": 3.0}
        waiting = classify_trigger_state(
            direction="PUT",
            entry_zone=zone,
            plan_validity="valid",
            current_spx_price=7126.0,
            locked_entry_spx=7120.0,
            structure_valid=True,
            move_completion_pct=12.0,
        )
        triggered = classify_trigger_state(
            direction="PUT",
            entry_zone={"status": "IN_ZONE", "width": 3.0},
            plan_validity="valid",
            current_spx_price=7120.5,
            locked_entry_spx=7120.0,
            structure_valid=True,
            move_completion_pct=18.0,
        )
        invalidated = classify_trigger_state(
            direction="PUT",
            entry_zone=zone,
            plan_validity="invalid",
            current_spx_price=7132.0,
            locked_entry_spx=7120.0,
            structure_valid=False,
            move_completion_pct=18.0,
        )

        self.assertEqual(waiting["trigger_state"], "READY")
        self.assertEqual(triggered["trigger_state"], "TRIGGERED")
        self.assertEqual(invalidated["trigger_state"], "INVALIDATED")

    def test_build_execution_state_marks_expired_when_move_is_spent(self) -> None:
        state = build_execution_state(
            play={"direction": "PUT", "contracts": 2, "entry": {"price": 7120.0}, "stop": {"price": 7158.0}, "tp1": {"price": 7103.72}, "tp2": {"price": 7066.28}},
            play_es={"entry": {"price": 7159.5}, "stop": {"price": 7197.5}},
            intelligence={
                "locked_entry_spx": 7120.0,
                "planned_entry_mark": 13.0,
                "entry_zone_status": "MISSED",
                "move_completion_pct": 95.0,
                "rr_ratio": 1.2,
                "prediction_confidence": "MEDIUM",
            },
            live_context={"scenario_origin": "SCENARIO 3: INSIDE DESCENDING CHANNEL", "live_scenario": "SCENARIO 3: INSIDE DESCENDING CHANNEL"},
            risk_class="MEDIUM",
            selected_contract_quote={"contract_symbol": "SPXW 260422P07100000", "price": 21.0, "delta": -0.6, "estimated_entry_cost": 2600.0, "budget_status": "Near Budget"},
            option_display_state={"ladder_rows": [], "recommended_contract_symbol": "SPXW 260422P07100000", "budget_cap": 2500.0},
            current_spx_price=7095.0,
            structure_valid=True,
        )

        self.assertEqual(state["expiry_status"], "EXPIRED")
        self.assertEqual(state["setup_state"], "EXPIRED")
        self.assertEqual(state["move_completion_bucket"], "SPENT")

    def test_stop_target_authority_is_null_safe(self) -> None:
        authority = build_stop_target_authority(
            play_spx={"entry": {"price": 7120.0}, "stop": {"price": 7158.0}},
            play_es={"entry": {"price": 7159.5}},
        )

        self.assertEqual(authority["authoritative_stop_spx"], 7158.0)
        self.assertIsNone(authority["target_1_spx"])
        self.assertIsNone(authority["rr_to_target_1"])

    def test_checklist_status_maps_from_pass_fail_conditions(self) -> None:
        ready = build_execution_checklist(
            structure_valid=True,
            entry_zone_status="IN_ZONE",
            stop_valid=True,
            rr_ratio=1.3,
            budget_execution_status="WITHIN_BUDGET",
            trigger_state="TRIGGERED",
            timing_bucket="ideal",
            evidence_level="Moderate",
        )
        blocked = build_execution_checklist(
            structure_valid=False,
            entry_zone_status="MISSED",
            stop_valid=False,
            rr_ratio=0.3,
            budget_execution_status="OVER_BUDGET",
            trigger_state="ARMED",
            timing_bucket="late",
            evidence_level="None",
        )

        self.assertEqual(ready["checklist_status"], "READY")
        self.assertEqual(blocked["checklist_status"], "BLOCKED")

    def test_trade_prefill_captures_execution_hardening_fields(self) -> None:
        signal_package = {"scenario": {"scenario_name": "SCENARIO 3: INSIDE DESCENDING CHANNEL", "confidence_level": "High"}}
        play_spx = {"direction": "PUT", "strike": 7100, "contracts": 2, "entry": {"label": "desc_floor", "price": 7120.0}, "stop": {"price": 7158.0}}
        play_es = {"entry": {"price": 7159.5}, "stop": {"price": 7197.5}}
        selected_quote = {
            "contract_symbol": "SPXW 260422P07095000",
            "strike": 7095,
            "option_type": "PUT",
            "expiration": "2026-04-22",
            "price": 18.0,
            "predicted_entry_price": 11.2,
            "estimated_entry_cost": 2240.0,
            "estimated_fill_cost": 2300.0,
            "budget_status": "Within Budget",
        }
        authority = {
            "setup_state": "ARMED",
            "trigger_type": "RETEST_AND_REJECT",
            "trigger_state": "ARMED",
            "trigger_reason": "Waiting for price to retest the locked entry zone",
            "entry_zone_status": "NEAR_ZONE",
            "invalidation_code": "NONE",
            "invalidation_message": "",
            "expiry_status": "OPEN",
            "checklist_status": "WAIT",
            "authoritative_stop_spx": 7158.0,
            "target_1_spx": 7103.72,
            "target_2_spx": 7066.28,
            "budget_execution_status": "WITHIN_BUDGET",
            "locked_selected_contract_symbol": "SPXW 260422P07100000",
            "locked_selected_strike": 7100,
            "locked_selected_option_type": "PUT",
            "locked_selected_entry_mark": 13.0,
            "locked_selected_budget_status": "Near Budget",
        }
        intelligence = {
            "planned_entry_mark": 13.0,
            "live_predicted_entry_mark": 13.0,
            "locked_entry_spx": 7120.0,
            "lock_cutoff_label": "8:25 AM CT",
            "session_plan_locked": True,
            "locked_timestamp": "2026-04-22T08:25:00-05:00",
            "entry_zone_status": "NEAR_ZONE",
            "move_completion_pct": 22.0,
            "regime": "PULLBACK",
            "plan_status": "HOLDING",
            "chase_status": "WAIT",
            "prediction_confidence": "MEDIUM",
            "stop_quality": "Balanced",
            "quality": "Acceptable",
        }

        prefill = build_live_play_trade_prefill(
            signal_package=signal_package,
            play_type="primary",
            play_spx=play_spx,
            play_es=play_es,
            lead_option_quote=selected_quote,
            recommended_contract_quote=selected_quote,
            intelligence=intelligence,
            final_status="ELIGIBLE",
            authority=authority,
            selection_context={"manual_override": False, "ladder_anchor_strike": 7100},
        )

        self.assertEqual(prefill["setup_state"], "ARMED")
        self.assertEqual(prefill["trigger_state"], "ARMED")
        self.assertEqual(prefill["alert_state"], "")
        self.assertEqual(prefill["target_1_spx"], 7103.72)
        self.assertEqual(prefill["budget_execution_status"], "WITHIN_BUDGET")
        self.assertEqual(prefill["locked_selected_contract_symbol"], "SPXW 260422P07100000")

    def test_forward_pricing_estimates_entry_value_and_conservative_fill(self) -> None:
        projection = estimate_contract_value_at_planned_entry(
            current_underlying_price=7140.0,
            planned_underlying_entry_price=7120.0,
            current_mark=4.9,
            current_bid=4.8,
            current_ask=5.0,
            current_last=4.95,
            option_type="PUT",
            strike=7100,
            expiration="2026-04-22",
            delta=-0.42,
            gamma=0.01,
            theta=-0.18,
            vega=0.09,
            implied_volatility=0.24,
            spread_width=0.2,
            liquidity_score=450.0,
            time_to_entry_minutes=25.0,
            entry_time_bucket="near",
            calibration_bias=0.1,
            event_risk_level="quiet",
            event_window_active=False,
            headline_shock_risk=False,
        )

        self.assertIsNotNone(projection["projected_mark_at_entry"])
        self.assertGreaterEqual(projection["projected_fill_at_entry"], projection["projected_mark_at_entry"])
        self.assertGreaterEqual(projection["projected_bid_at_entry"], 0.01)
        self.assertIn(projection["projection_confidence"], {"high", "medium", "low", "speculative"})

    def test_forward_pricing_falls_back_cleanly_when_greeks_missing(self) -> None:
        projection = estimate_contract_value_at_planned_entry(
            current_underlying_price=7140.0,
            planned_underlying_entry_price=7120.0,
            current_mark=4.9,
            current_bid=4.7,
            current_ask=5.1,
            current_last=None,
            option_type="PUT",
            strike=7100,
            expiration="2026-04-22",
            delta=-0.42,
            gamma=None,
            theta=None,
            vega=None,
            implied_volatility=None,
            spread_width=0.4,
            liquidity_score=10.0,
            time_to_entry_minutes=None,
            entry_time_bucket="unavailable",
            calibration_bias=None,
            event_risk_level="major",
            event_window_active=True,
            headline_shock_risk=True,
        )

        self.assertIsNotNone(projection["projected_mark_at_entry"])
        self.assertIn(projection["projection_confidence"], {"low", "speculative"})
        self.assertTrue(projection["projection_warning"])

    def test_time_target_pricing_applies_theta_and_keeps_fill_conservative(self) -> None:
        now_ct = app_module.at_central(date(2026, 4, 22), 8, 20)
        target_ct = app_module.at_central(date(2026, 4, 22), 9, 0)

        projection = estimate_option_price_at_time(
            current_underlying_price=7140.0,
            target_underlying_price=7140.0,
            current_option_mark=5.0,
            bid=4.9,
            ask=5.1,
            delta=-0.40,
            gamma=0.01,
            theta=-0.24,
            vega=0.08,
            implied_volatility=0.22,
            option_type="PUT",
            strike=7100.0,
            current_time=now_ct,
            target_time=target_ct,
            event_risk_level="quiet",
            liquidity_score=220.0,
            spread_width=0.2,
            is_market_open=False,
        )

        self.assertLess(projection["projected_mark_at_target_time"], 5.0)
        self.assertGreaterEqual(projection["expected_fill_at_target_time"], projection["projected_mark_at_target_time"])
        self.assertEqual(projection["target_time_label"], "Projected @ 9:00 AM CT")

    def test_time_target_pricing_increases_with_favorable_underlying_move(self) -> None:
        now_ct = app_module.at_central(date(2026, 4, 22), 8, 15)
        target_ct = app_module.at_central(date(2026, 4, 22), 9, 0)

        projection = estimate_option_price_at_time(
            current_underlying_price=7140.0,
            target_underlying_price=7125.0,
            current_option_mark=4.8,
            bid=4.7,
            ask=4.9,
            delta=-0.45,
            gamma=0.012,
            theta=-0.16,
            vega=0.08,
            implied_volatility=0.23,
            option_type="PUT",
            strike=7100.0,
            current_time=now_ct,
            target_time=target_ct,
            event_risk_level="quiet",
            liquidity_score=300.0,
            spread_width=0.2,
            is_market_open=False,
        )

        self.assertGreater(projection["projected_mark_at_target_time"], 4.8)

    def test_time_target_pricing_applies_iv_crush_into_open(self) -> None:
        now_ct = app_module.at_central(date(2026, 4, 22), 8, 20)
        target_ct = app_module.at_central(date(2026, 4, 22), 9, 0)

        with_crush = estimate_option_price_at_time(
            current_underlying_price=7140.0,
            target_underlying_price=7140.0,
            current_option_mark=5.0,
            bid=4.9,
            ask=5.1,
            delta=-0.35,
            gamma=0.01,
            theta=-0.10,
            vega=0.20,
            implied_volatility=0.24,
            option_type="PUT",
            strike=7100.0,
            current_time=now_ct,
            target_time=target_ct,
            event_risk_level="quiet",
            liquidity_score=250.0,
            spread_width=0.2,
            is_market_open=False,
        )
        no_crush = estimate_option_price_at_time(
            current_underlying_price=7140.0,
            target_underlying_price=7140.0,
            current_option_mark=5.0,
            bid=4.9,
            ask=5.1,
            delta=-0.35,
            gamma=0.01,
            theta=-0.10,
            vega=0.20,
            implied_volatility=0.24,
            option_type="PUT",
            strike=7100.0,
            current_time=now_ct,
            target_time=app_module.at_central(date(2026, 4, 22), 8, 25),
            event_risk_level="quiet",
            liquidity_score=250.0,
            spread_width=0.2,
            is_market_open=False,
        )

        self.assertLess(with_crush["projected_mark_at_target_time"], no_crush["projected_mark_at_target_time"])

    def test_time_target_pricing_never_goes_negative_and_missing_greeks_lower_quality(self) -> None:
        now_ct = app_module.at_central(date(2026, 4, 22), 8, 15)
        target_ct = app_module.at_central(date(2026, 4, 22), 9, 0)

        projection = estimate_option_price_at_time(
            current_underlying_price=7140.0,
            target_underlying_price=7110.0,
            current_option_mark=0.15,
            bid=0.10,
            ask=0.20,
            delta=-0.10,
            gamma=None,
            theta=None,
            vega=None,
            implied_volatility=None,
            option_type="PUT",
            strike=7000.0,
            current_time=now_ct,
            target_time=target_ct,
            event_risk_level="major",
            liquidity_score=5.0,
            spread_width=0.10,
            is_market_open=False,
        )

        self.assertGreaterEqual(projection["projected_mark_at_target_time"], 0.01)
        self.assertGreaterEqual(projection["expected_fill_at_target_time"], projection["projected_mark_at_target_time"])
        self.assertIn(projection["estimate_quality"], {"Weak", "Insufficient"})

    def test_budget_aware_execution_selection_prefers_viable_within_budget_contract(self) -> None:
        rows = [
            {"contract_symbol": "REC", "budget_status": "Above Budget", "rr_ratio": 1.6, "contract_score": 0.9, "delta": -0.58, "premium_projection_confidence": "High", "projected_fill_at_entry": 7.5, "labels": []},
            {"contract_symbol": "BUDGET", "budget_status": "Within Budget", "rr_ratio": 1.2, "contract_score": 0.75, "delta": -0.55, "premium_projection_confidence": "Medium", "projected_fill_at_entry": 3.9, "labels": []},
        ]

        chosen = choose_execution_contract_from_ladder(rows, recommended_symbol="REC")

        self.assertEqual(chosen["contract_symbol"], "BUDGET")

    def test_event_risk_overlay_downgrades_execution_guidance(self) -> None:
        overlay = apply_event_risk_to_execution_guidance(
            current_action="ENTER NOW",
            current_reason="Structure valid and in zone",
            event_risk_context={"event_risk_level": "major", "event_trading_mode": "reduced confidence", "event_risk_reason": "CPI window active"},
        )

        hero_label = resolve_hero_action_label(
            {"execution_action": overlay["action"], "setup_state": "READY"},
            {"event_risk_level": "major"},
        )

        self.assertEqual(overlay["action"], "WAIT FOR EVENT PASS")
        self.assertEqual(hero_label, "CAUTION EVENT RISK")

    def test_event_risk_summary_stays_compact_when_news_unavailable(self) -> None:
        summary = summarize_event_risk({"event_risk_status": "Unknown", "event_risk_reason": "News unavailable"})
        self.assertEqual(summary, "Event Risk: Unknown | News unavailable")

    def test_ladder_display_dataframe_handles_missing_optional_projection_columns(self) -> None:
        frame = build_ladder_display_dataframe(
            [
                {
                    "labels": ["Recommended"],
                    "selection_reason": "System Pick",
                    "strike": 7100,
                    "current_mark": 4.9,
                    "predicted_entry_price": 5.2,
                    "delta": -0.42,
                    "rr_ratio": 1.3,
                    "budget_status": "Within Budget",
                }
            ],
            developer_mode=False,
        )

        self.assertIn("at_entry", frame.columns)
        self.assertIn("expected_fill", frame.columns)
        self.assertEqual(frame.iloc[0]["at_entry"], 5.2)

    def test_render_fallback_payload_hides_traceback_text_in_production(self) -> None:
        payload = build_render_fallback_payload("Strike Selection", RuntimeError("bad column"), developer_mode=False)
        debug_payload = build_render_fallback_payload("Strike Selection", RuntimeError("bad column"), developer_mode=True)

        self.assertEqual(payload["title"], "Strike Selection")
        self.assertEqual(payload["reason"], "Temporarily unavailable")
        self.assertIn("RuntimeError", debug_payload["reason"])

    def test_option_display_state_keeps_selected_execution_quote_bound_to_projected_fields(self) -> None:
        signal_package = {"scenario": {"scenario_name": "SCENARIO 3: INSIDE DESCENDING CHANNEL", "confidence_level": "High"}}
        play_spx = {"direction": "PUT", "strike": 7100, "contracts": 1, "entry": {"label": "desc_floor", "price": 7120.0}, "stop": {"price": 7158.0}}
        display_state = build_option_display_state(
            play_role="primary",
            candidates=self.option_candidates,
            play_spx=play_spx,
            play_es={"entry": {"price": 7159.5}},
            next_trading_date=app_module.current_central_time().date(),
            session_plan={"session_plan_locked": True, "contract_symbol": "SPXW 260422P07100000", "planned_strike": 7100, "option_type": "PUT", "expiration": "2026-04-22"},
            signal_package=signal_package,
            trades=[],
            current_spx_price=7132.0,
            planned_anchor_key="primary:test",
            budget_cap=500.0,
            live_context={"live_scenario": "SCENARIO 3: INSIDE DESCENDING CHANNEL"},
            event_risk_context={"event_risk_level": "quiet", "event_window_active": False, "headline_shock_risk": False},
        )

        self.assertIsNotNone(display_state["selected_quote"])
        self.assertIn("projected_mark_at_entry", display_state["selected_quote"])
        self.assertIn("premium_projection_confidence", display_state["selected_quote"])
        self.assertIn("projection_target_label", display_state["selected_quote"])

    def test_line_polarity_support_hold_requires_close_near_line(self) -> None:
        result = evaluate_line_polarity(
            line={"name": "asc_floor", "projected_price": 7120.0, "distance": 1.0},
            candle={"high": 7121.0, "low": 7119.25, "close": 7122.5},
            desired_direction="CALL",
            vwap_value=7118.0,
            pending_retest_store={},
        )

        self.assertTrue(result["actionable"])
        self.assertEqual(result["polarity_state"], "support_hold")
        self.assertEqual(result["decision"], "TRADE")
        self.assertEqual(result["vwap_alignment"], "CONFIRMED")

    def test_line_polarity_opposite_direction_blocks_play(self) -> None:
        result = evaluate_line_polarity(
            line={"name": "asc_floor", "projected_price": 7120.0, "distance": 1.0},
            candle={"high": 7121.0, "low": 7119.25, "close": 7122.5},
            desired_direction="PUT",
            pending_retest_store={},
        )

        self.assertFalse(result["actionable"])
        self.assertTrue(result["polarity_conflict"])
        self.assertEqual(result["decision"], "NO TRADE")
        self.assertEqual(result["confirmed_direction"], "CALL")

    def test_line_polarity_extended_rejection_blocks_entry_and_marks_retest(self) -> None:
        store: dict[str, object] = {}
        result = evaluate_line_polarity(
            line={"name": "desc_ceiling", "projected_price": 7120.0, "distance": 5.0},
            candle={"high": 7120.5, "low": 7119.25, "close": 7115.75},
            desired_direction="PUT",
            pending_retest_store=store,
        )

        self.assertFalse(result["actionable"])
        self.assertEqual(result["decision"], "WAIT")
        self.assertEqual(result["polarity_state"], "extended_rejection")
        self.assertTrue(result["pending_retest"])
        self.assertTrue(store)

    def test_line_polarity_retest_confirmation_allows_trade_after_extended_rejection(self) -> None:
        store: dict[str, object] = {}
        evaluate_line_polarity(
            line={"name": "desc_ceiling", "projected_price": 7120.0, "distance": 5.0},
            candle={"high": 7120.5, "low": 7119.25, "close": 7115.75},
            desired_direction="PUT",
            pending_retest_store=store,
        )
        retest = evaluate_line_polarity(
            line={"name": "desc_ceiling", "projected_price": 7120.0, "distance": 1.0},
            candle={"high": 7120.75, "low": 7119.25, "close": 7118.0},
            desired_direction="PUT",
            pending_retest_store=store,
        )

        self.assertTrue(retest["actionable"])
        self.assertEqual(retest["polarity_state"], "resistance_rejection")
        self.assertFalse(store)

    def test_polarity_decision_uses_nearest_actionable_line(self) -> None:
        decision = build_line_polarity_decision(
            projected_lines={
                "asc_floor": {"label": "ASC Floor", "projected_price": 7120.0, "line_type": "channel"},
                "desc_ceiling": {"label": "DESC Ceiling", "projected_price": 7145.0, "line_type": "channel"},
            },
            current_price=7119.75,
            current_candle={"high": 7120.5, "low": 7119.0, "close": 7118.25},
            desired_direction="PUT",
            pending_retest_store={},
        )

        self.assertEqual(decision["decision"], "TRADE")
        self.assertEqual(decision["polarity_state"], "resistance_rejection")
        self.assertEqual(decision["line_used"]["name"], "asc_floor")

    def test_polarity_decision_prioritizes_opposite_confirmation_over_wait(self) -> None:
        decision = build_line_polarity_decision(
            projected_lines={
                "asc_floor": {"label": "ASC Floor", "projected_price": 7120.0, "line_type": "channel"},
                "desc_ceiling": {"label": "DESC Ceiling", "projected_price": 7145.0, "line_type": "channel"},
            },
            current_price=7120.25,
            current_candle={"high": 7120.75, "low": 7119.5, "close": 7122.0},
            desired_direction="PUT",
            pending_retest_store={},
        )

        self.assertTrue(decision["polarity_conflict"])
        self.assertEqual(decision["decision"], "NO TRADE")
        self.assertEqual(decision["confirmed_direction"], "CALL")

    def test_execution_state_blocks_entry_when_line_reaction_is_extended(self) -> None:
        play = {"direction": "PUT", "strike": 7100, "contracts": 1, "entry": {"label": "desc_floor", "price": 7120.0}, "stop": {"price": 7158.0}, "setup_tradable": True}
        quote = {"contract_symbol": "SPXW 260422P07100000", "price": 4.8, "predicted_entry_price": 4.2, "budget_status": "Within Budget"}
        state = build_execution_state(
            play=play,
            play_es={"entry": {"price": 7159.5}},
            intelligence={"rr_ratio": 1.4, "planned_entry_mark": 4.2, "locked_entry_spx": 7120.0, "move_completion_pct": 10, "entry_zone_status": "IN ZONE", "prediction_confidence": "HIGH"},
            live_context={"scenario_origin": "SCENARIO 3: INSIDE DESCENDING CHANNEL", "live_scenario": "SCENARIO 3: INSIDE DESCENDING CHANNEL"},
            risk_class="LOW",
            selected_contract_quote=quote,
            option_display_state={"budget_cap": 500.0, "ladder_rows": [quote], "recommended_contract_symbol": quote["contract_symbol"]},
            current_spx_price=7115.75,
            structure_valid=True,
            projected_lines_spx={"desc_floor": {"label": "DESC Floor", "projected_price": 7120.0, "line_type": "channel"}},
            current_candle={"high": 7120.5, "low": 7119.25, "close": 7115.75},
        )

        self.assertEqual(state["line_polarity_state"], "extended_rejection")
        self.assertFalse(state["line_polarity_actionable"])
        self.assertEqual(state["execution_action"], "WAIT FOR RETEST")
        self.assertEqual(state["setup_state"], "ARMED")

    def test_execution_state_invalidates_play_when_polarity_confirms_opposite_direction(self) -> None:
        play = {"direction": "PUT", "strike": 7100, "contracts": 1, "entry": {"label": "asc_floor", "price": 7120.0}, "stop": {"price": 7158.0}, "setup_tradable": True}
        quote = {"contract_symbol": "SPXW 260422P07100000", "price": 4.8, "predicted_entry_price": 4.2, "budget_status": "Within Budget"}
        state = build_execution_state(
            play=play,
            play_es={"entry": {"price": 7159.5}},
            intelligence={"rr_ratio": 1.4, "planned_entry_mark": 4.2, "locked_entry_spx": 7120.0, "move_completion_pct": 10, "entry_zone_status": "IN ZONE", "prediction_confidence": "HIGH"},
            live_context={"scenario_origin": "SCENARIO 2: INSIDE ASCENDING CHANNEL", "live_scenario": "SCENARIO 2: INSIDE ASCENDING CHANNEL"},
            risk_class="LOW",
            selected_contract_quote=quote,
            option_display_state={"budget_cap": 500.0, "ladder_rows": [quote], "recommended_contract_symbol": quote["contract_symbol"]},
            current_spx_price=7122.0,
            structure_valid=True,
            projected_lines_spx={"asc_floor": {"label": "ASC Floor", "projected_price": 7120.0, "line_type": "channel"}},
            current_candle={"high": 7120.75, "low": 7119.5, "close": 7122.0},
        )

        self.assertTrue(state["line_polarity_conflict"])
        self.assertEqual(state["execution_action"], "SKIP TRADE")
        self.assertEqual(state["trigger_state"], "INVALIDATED")
        self.assertEqual(state["setup_state"], "INVALIDATED")

    def test_pm_window_anchor_still_selected_when_most_relevant(self) -> None:
        frame = self._build_anchor_candidate_frame()
        bundle = app_module._build_session_aware_anchor_bundle(
            candles=frame,
            prior_session_date=date(2026, 4, 22),
            next_trading_date=date(2026, 4, 23),
            current_es_price=7152.2,
            anchor_source_override="Auto",
        )

        selected_floor = bundle["anchor_selection"]["by_line"]["asc_floor"]
        self.assertEqual(selected_floor["session_source"], "PM_WINDOW")

    def test_asian_anchor_can_override_pm_when_structurally_closer(self) -> None:
        frame = self._build_anchor_candidate_frame()
        bundle = app_module._build_session_aware_anchor_bundle(
            candles=frame,
            prior_session_date=date(2026, 4, 22),
            next_trading_date=date(2026, 4, 23),
            current_es_price=7141.4,
            anchor_source_override="Auto",
        )

        selected_floor = bundle["anchor_selection"]["by_line"]["asc_floor"]
        self.assertEqual(selected_floor["session_source"], "ASIAN")
        self.assertIn("PM-window", selected_floor["selection_reason"])

    def test_london_anchor_can_override_when_pre_ny_structure_respects_it(self) -> None:
        frame = self._build_anchor_candidate_frame()
        bundle = app_module._build_session_aware_anchor_bundle(
            candles=frame,
            prior_session_date=date(2026, 4, 22),
            next_trading_date=date(2026, 4, 23),
            current_es_price=7134.2,
            anchor_source_override="Auto",
        )

        selected_floor = bundle["anchor_selection"]["by_line"]["asc_floor"]
        self.assertEqual(selected_floor["session_source"], "LONDON")

    def test_anchor_candidate_projection_to_ny_open_is_computed(self) -> None:
        frame = self._build_anchor_candidate_frame()
        bundle = app_module._build_session_aware_anchor_bundle(
            candles=frame,
            prior_session_date=date(2026, 4, 22),
            next_trading_date=date(2026, 4, 23),
            current_es_price=7141.4,
            anchor_source_override="Auto",
        )

        rows = build_anchor_candidate_table(bundle)
        asian_low = next(
            row for row in rows if row["session_source"] == "Asian Session" and row["pivot_type"] == "LOW"
        )
        self.assertAlmostEqual(asian_low["projected_9_00"], 7140.30, places=2)

    def test_candidate_closest_to_reaction_price_gets_higher_score(self) -> None:
        frame = self._build_anchor_candidate_frame()
        bundle = app_module._build_session_aware_anchor_bundle(
            candles=frame,
            prior_session_date=date(2026, 4, 22),
            next_trading_date=date(2026, 4, 23),
            current_es_price=7141.4,
            anchor_source_override="Auto",
        )

        rows = build_anchor_candidate_table(bundle)
        asian_score = next(row["score"] for row in rows if row["session_source"] == "Asian Session" and row["pivot_type"] == "LOW")
        pm_score = next(row["score"] for row in rows if row["session_source"] == "PM Window" and row["pivot_type"] == "LOW")
        self.assertGreater(asian_score, pm_score)

    def test_selected_anchor_freezes_at_session_lock(self) -> None:
        frame = self._build_anchor_candidate_frame()
        original_now = app_module.current_central_time
        try:
            app_module.current_central_time = lambda: app_module.at_central(date(2026, 4, 23), 8, 30)
            asian_bundle = app_module._build_session_aware_anchor_bundle(
                candles=frame,
                prior_session_date=date(2026, 4, 22),
                next_trading_date=date(2026, 4, 23),
                current_es_price=7141.4,
                anchor_source_override="Auto",
            )
            locked_bundle = resolve_locked_anchor_bundle(
                asian_bundle,
                next_trading_date=date(2026, 4, 23),
                cutoff_label="8:25 AM CT",
            )
            pm_bundle = app_module._build_session_aware_anchor_bundle(
                candles=frame,
                prior_session_date=date(2026, 4, 22),
                next_trading_date=date(2026, 4, 23),
                current_es_price=7152.2,
                anchor_source_override="Auto",
            )
            frozen_bundle = resolve_locked_anchor_bundle(
                pm_bundle,
                next_trading_date=date(2026, 4, 23),
                cutoff_label="8:25 AM CT",
            )
        finally:
            app_module.current_central_time = original_now

        self.assertEqual(locked_bundle["anchor_selection"]["by_line"]["asc_floor"]["session_source"], "ASIAN")
        self.assertEqual(frozen_bundle["anchor_selection"]["by_line"]["asc_floor"]["session_source"], "ASIAN")
        self.assertEqual(frozen_bundle["anchor_selection"]["alternative_anchor_note"], "Alternative anchor line being respected")

    def test_old_anchor_lock_version_is_replaced_by_session_aware_selection(self) -> None:
        frame = self._build_anchor_candidate_frame()
        original_now = app_module.current_central_time
        try:
            current_bundle = app_module._build_session_aware_anchor_bundle(
                candles=frame,
                prior_session_date=date(2026, 4, 22),
                next_trading_date=date(2026, 4, 23),
                current_es_price=7141.4,
                anchor_source_override="Auto",
            )
            stale_bundle = app_module._build_session_aware_anchor_bundle(
                candles=frame,
                prior_session_date=date(2026, 4, 22),
                next_trading_date=date(2026, 4, 23),
                current_es_price=7152.2,
                anchor_source_override="Auto",
            )
            stale_bundle["anchor_selection"]["engine_version"] = "legacy-pm-lock"
            app_module.st.session_state["anchor_selection_store"][date(2026, 4, 23).isoformat()] = stale_bundle
            app_module.current_central_time = lambda: app_module.at_central(date(2026, 4, 23), 8, 30)
            resolved = resolve_locked_anchor_bundle(
                current_bundle,
                next_trading_date=date(2026, 4, 23),
                cutoff_label="8:25 AM CT",
            )
        finally:
            app_module.current_central_time = original_now

        self.assertEqual(resolved["anchor_selection"]["engine_version"], app_module.ANCHOR_SELECTION_ENGINE_VERSION)
        self.assertEqual(resolved["anchor_selection"]["by_line"]["asc_floor"]["session_source"], "ASIAN")

    def test_manual_anchor_source_override_prevents_auto_selection(self) -> None:
        frame = self._build_anchor_candidate_frame()
        bundle = app_module._build_session_aware_anchor_bundle(
            candles=frame,
            prior_session_date=date(2026, 4, 22),
            next_trading_date=date(2026, 4, 23),
            current_es_price=7141.4,
            anchor_source_override="PM Window",
        )

        selected_floor = bundle["anchor_selection"]["by_line"]["asc_floor"]
        self.assertEqual(selected_floor["session_source"], "PM_WINDOW")
        self.assertTrue(bundle["anchor_selection"]["override_used"])

    def test_edge_lab_anchor_candidate_table_includes_all_session_candidates(self) -> None:
        frame = self._build_anchor_candidate_frame()
        bundle = app_module._build_session_aware_anchor_bundle(
            candles=frame,
            prior_session_date=date(2026, 4, 22),
            next_trading_date=date(2026, 4, 23),
            current_es_price=7141.4,
            anchor_source_override="Auto",
        )

        rows = build_anchor_candidate_table(bundle)
        session_sources = {row["session_source"] for row in rows}
        self.assertTrue({"PM Window", "Asian Session", "London", "Pre-NY"}.issubset(session_sources))

    def test_trade_prefill_stores_selected_anchor_metadata(self) -> None:
        frame = self._build_anchor_candidate_frame()
        bundle = app_module._build_session_aware_anchor_bundle(
            candles=frame,
            prior_session_date=date(2026, 4, 22),
            next_trading_date=date(2026, 4, 23),
            current_es_price=7141.4,
            anchor_source_override="Auto",
        )
        signal_package = {"scenario": {"scenario_name": "SCENARIO 3: INSIDE DESCENDING CHANNEL", "confidence_level": "High"}}
        play_spx = {"direction": "PUT", "strike": 7100, "contracts": 1, "entry": {"label": "desc_floor", "price": 7120.0}, "stop": {"price": 7158.0}}
        prefill = build_live_play_trade_prefill(
            signal_package=signal_package,
            play_type="primary",
            play_spx=play_spx,
            play_es={"entry": {"price": 7159.5}},
            lead_option_quote={
                "contract_symbol": "SPXW 260422P07100000",
                "strike": 7100,
                "price": 4.8,
                "predicted_entry_price": 4.2,
                "budget_status": "Within Budget",
            },
            intelligence={
                "planned_entry_mark": 4.2,
                "live_predicted_entry_mark": 4.2,
                "locked_entry_spx": 7120.0,
                "lock_cutoff_label": "8:25 AM CT",
                "session_plan_locked": True,
                "locked_timestamp": "2026-04-23T08:25:00-05:00",
            },
            final_status="ELIGIBLE",
            anchor_bundle=bundle,
        )

        self.assertEqual(prefill["selected_anchor_source"], "ASIAN")
        self.assertIsNotNone(prefill["selected_anchor_price"])
        self.assertTrue(prefill["anchor_selection_reason"])


if __name__ == "__main__":
    unittest.main()
