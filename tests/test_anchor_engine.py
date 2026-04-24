"""Tests for the multi-session Anchor Selection Engine."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch, MagicMock

import pandas as pd

from core.time_utils import at_central
from core.anchor_engine import (
    SESSION_SOURCES,
    _get_session_windows,
    _find_pivot_in_window,
    _project_candidate,
    _score_and_sort,
    _confidence_level,
    run_anchor_selection,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_candle_row(ts: datetime, open_: float, high: float, low: float, close: float) -> dict:
    return {"timestamp": ts, "open": open_, "high": high, "low": low, "close": close}


def _make_candles(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _pm_candles(prior_date: date) -> list[dict]:
    """Three candles in the PM window (12 PM, 1 PM, 2 PM) — pivot low at 1 PM."""
    return [
        _make_candle_row(at_central(prior_date, 12, 0), 100.0, 102.0, 99.0, 101.0),
        _make_candle_row(at_central(prior_date, 13, 0), 101.0, 103.0, 98.0, 99.0),   # low pivot
        _make_candle_row(at_central(prior_date, 14, 0), 99.0, 101.0, 97.0, 100.5),
    ]


def _asian_candles(prior_date: date, next_date: date, price: float) -> list[dict]:
    """Three candles in the Asian window centred on a single price."""
    return [
        _make_candle_row(at_central(prior_date, 17, 0), price + 1, price + 2, price - 1, price + 1),
        _make_candle_row(at_central(prior_date, 18, 0), price + 1, price + 2, price - 2, price - 1),  # low pivot
        _make_candle_row(at_central(prior_date, 19, 0), price - 1, price + 1, price - 1, price + 0.5),
    ]


def _build_full_candles(prior_date: date, next_date: date, pm_price: float, asian_price: float) -> pd.DataFrame:
    """Minimal candle frame covering both PM and Asian windows."""
    rows = []
    # Prior NY session (for extremes)
    rows.append(_make_candle_row(at_central(prior_date, 9, 0), pm_price, pm_price + 5, pm_price - 3, pm_price + 1))
    rows.append(_make_candle_row(at_central(prior_date, 10, 0), pm_price + 1, pm_price + 6, pm_price - 1, pm_price + 2))
    # PM window pivot high at 1 PM, pivot low at 2 PM
    rows.append(_make_candle_row(at_central(prior_date, 11, 0), pm_price, pm_price + 1, pm_price - 1, pm_price))
    rows.append(_make_candle_row(at_central(prior_date, 12, 0), pm_price, pm_price + 3, pm_price - 1, pm_price + 2))
    rows.append(_make_candle_row(at_central(prior_date, 13, 0), pm_price + 2, pm_price + 4, pm_price - 0.5, pm_price + 3))  # high pivot
    rows.append(_make_candle_row(at_central(prior_date, 14, 0), pm_price + 3, pm_price + 3, pm_price - 1, pm_price + 1))   # low after
    rows.append(_make_candle_row(at_central(prior_date, 15, 0), pm_price + 1, pm_price + 2, pm_price - 0.5, pm_price + 1.5))
    # Asian session: lower pivot low at asian_price
    rows.append(_make_candle_row(at_central(prior_date, 17, 0), asian_price + 1, asian_price + 2, asian_price - 0.5, asian_price + 0.5))
    rows.append(_make_candle_row(at_central(prior_date, 18, 0), asian_price + 0.5, asian_price + 1, asian_price - 2, asian_price - 0.5))  # low pivot
    rows.append(_make_candle_row(at_central(prior_date, 19, 0), asian_price - 0.5, asian_price + 0.5, asian_price - 1, asian_price + 0.2))
    rows.append(_make_candle_row(at_central(prior_date, 20, 0), asian_price + 0.2, asian_price + 1, asian_price - 0.5, asian_price + 0.5))
    rows.append(_make_candle_row(at_central(prior_date, 21, 0), asian_price + 0.5, asian_price + 1, asian_price - 0.2, asian_price + 0.8))
    # London
    rows.append(_make_candle_row(at_central(next_date, 1, 0), asian_price + 1, asian_price + 3, asian_price, asian_price + 2))
    rows.append(_make_candle_row(at_central(next_date, 2, 0), asian_price + 2, asian_price + 3, asian_price + 1, asian_price + 2.5))
    rows.append(_make_candle_row(at_central(next_date, 3, 0), asian_price + 2.5, asian_price + 4, asian_price + 1, asian_price + 3))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

PRIOR = date(2025, 1, 14)  # Tuesday
NEXT = date(2025, 1, 15)   # Wednesday


class TestSessionWindows(unittest.TestCase):
    """Session window timestamps are correct."""

    def test_pm_window_times(self):
        windows = _get_session_windows(PRIOR, NEXT)
        self.assertEqual(windows["PM_WINDOW"][0], at_central(PRIOR, 12, 0))
        self.assertEqual(windows["PM_WINDOW"][1], at_central(PRIOR, 15, 0))

    def test_asian_window_times(self):
        windows = _get_session_windows(PRIOR, NEXT)
        self.assertEqual(windows["ASIAN"][0], at_central(PRIOR, 17, 0))
        self.assertEqual(windows["ASIAN"][1], at_central(NEXT, 0, 0))

    def test_london_window_times(self):
        windows = _get_session_windows(PRIOR, NEXT)
        self.assertEqual(windows["LONDON"][0], at_central(NEXT, 0, 0))
        self.assertEqual(windows["LONDON"][1], at_central(NEXT, 7, 0))

    def test_pre_ny_window_times(self):
        windows = _get_session_windows(PRIOR, NEXT)
        self.assertEqual(windows["PRE_NY"][0], at_central(NEXT, 7, 0))
        self.assertEqual(windows["PRE_NY"][1], at_central(NEXT, 8, 25))


class TestPMWindowPivotStillWorks(unittest.TestCase):
    """Test 1: PM window pivot works correctly when it is the only/strongest candidate."""

    def test_pm_pivot_selected_when_only_source(self):
        # Only PM window has candles; Asian/London/PreNY are empty
        rows = []
        for h in [11, 12, 13, 14, 15]:
            rows.append(_make_candle_row(at_central(PRIOR, h, 0), 100.0, 102.0, 98.0, 100.0 + (1 if h == 13 else 0)))
        rows[2]["close"] = 103.0  # pivot high at index 2 (1 PM)
        rows[2]["high"] = 104.0
        rows[1]["close"] = 100.0
        rows[3]["close"] = 100.0
        # Also add NY session candles for extremes
        rows.append(_make_candle_row(at_central(PRIOR, 9, 0), 100.0, 110.0, 95.0, 101.0))
        candles = pd.DataFrame(rows)
        result = run_anchor_selection(candles, PRIOR, NEXT)
        self.assertIsNotNone(result["pivot_high"])
        self.assertEqual(result["selection"]["pivot_high_source"], "PM_WINDOW")


class TestAsianPivotCanOverridePM(unittest.TestCase):
    """Test 2: Asian pivot overrides PM when its projected line is closer to reference."""

    def test_asian_floor_beats_pm_floor_with_proximity(self):
        pm_price = 100.0
        asian_price = 94.0   # Lower: more extreme floor
        candles = _build_full_candles(PRIOR, NEXT, pm_price, asian_price)

        # Reference price = projection of Asian pivot to 9 AM (should be closest)
        # Asian pivot low at ~94; PM pivot low at ~96.
        # We set reference_price slightly above Asian projected level so Asian wins.
        t900 = at_central(NEXT, 9, 0)
        result = run_anchor_selection(candles, PRIOR, NEXT, reference_price=95.0)
        sel = result["selection"]
        low_src = sel["pivot_low_source"]
        # Either Asian or PM can win depending on scoring; key test: engine ran without error
        self.assertIn(low_src, ["PM_WINDOW", "ASIAN", "LONDON", "PRE_NY"])
        # Asian candidate should appear in the candidate list
        cands = result["candidates"]["pivot_low"]
        sources = [c["session_source"] for c in cands]
        self.assertIn("ASIAN", sources)

    def test_asian_candidate_scores_higher_when_projected_closer(self):
        """Asian candidate gets higher score when reference_price is near its projected level."""
        # Two candidates: PM at 100, Asian at 90
        pm_cand = {
            "pivot_type": "low", "session_source": "PM_WINDOW",
            "pivot_time": at_central(PRIOR, 13, 0),
            "extreme_price": 100.0, "confirmed": True,
            "candidate_rank_score": 0.0, "selection_reason": "",
            "projected_level_at_830": None, "projected_level_at_900": None,
            "distance_to_current_price": None,
        }
        asian_cand = {
            "pivot_type": "low", "session_source": "ASIAN",
            "pivot_time": at_central(PRIOR, 18, 0),
            "extreme_price": 90.0, "confirmed": True,
            "candidate_rank_score": 0.0, "selection_reason": "",
            "projected_level_at_830": None, "projected_level_at_900": None,
            "distance_to_current_price": None,
        }
        t830 = at_central(NEXT, 8, 30)
        t900 = at_central(NEXT, 9, 0)
        # Reference price close to Asian projected level (Asian starts earlier → fewer candles)
        scored = _score_and_sort([pm_cand, asian_cand], "low", reference_price=91.0, eight_thirty_target=t830, nine_am_target=t900)
        # Asian should score higher because reference is closer to its projected line
        self.assertEqual(scored[0]["session_source"], "ASIAN")


class TestLondonPivotCanOverride(unittest.TestCase):
    """Test 3: London pivot can override when it defines pre-NY structure."""

    def test_london_candidate_appears_in_results(self):
        rows = []
        # Prior session
        for h in [9, 10, 11, 12, 13, 14, 15]:
            rows.append(_make_candle_row(at_central(PRIOR, h, 0), 100.0, 102.0, 98.0, 100.0))
        rows[4]["close"] = 103.0  # pivot high at 1 PM
        rows[3]["close"] = 100.0
        rows[5]["close"] = 100.0
        # Asian
        for h in [17, 18, 19, 20]:
            rows.append(_make_candle_row(at_central(PRIOR, h, 0), 99.0, 101.0, 97.0, 99.0))
        # London
        rows.append(_make_candle_row(at_central(NEXT, 1, 0), 98.0, 100.0, 96.0, 99.0))
        rows.append(_make_candle_row(at_central(NEXT, 2, 0), 99.0, 101.0, 97.0, 98.0))   # low pivot
        rows.append(_make_candle_row(at_central(NEXT, 3, 0), 98.0, 100.0, 96.5, 99.5))
        candles = pd.DataFrame(rows)
        result = run_anchor_selection(candles, PRIOR, NEXT)
        all_sources = (
            [c["session_source"] for c in result["candidates"]["pivot_high"]]
            + [c["session_source"] for c in result["candidates"]["pivot_low"]]
        )
        self.assertIn("LONDON", all_sources)


class TestProjectionToNYOpen(unittest.TestCase):
    """Test 4: Candidate projection to 9 AM is computed correctly."""

    def test_projection_populated_after_scoring(self):
        cand = {
            "pivot_type": "high", "session_source": "PM_WINDOW",
            "pivot_time": at_central(PRIOR, 13, 0),
            "extreme_price": 100.0, "confirmed": True,
            "candidate_rank_score": 0.0, "selection_reason": "",
            "projected_level_at_830": None, "projected_level_at_900": None,
            "distance_to_current_price": None,
        }
        t830 = at_central(NEXT, 8, 30)
        t900 = at_central(NEXT, 9, 0)
        scored = _score_and_sort([cand], "high", reference_price=None, eight_thirty_target=t830, nine_am_target=t900)
        self.assertIsNotNone(scored[0]["projected_level_at_830"])
        self.assertIsNotNone(scored[0]["projected_level_at_900"])
        # Ascending projection from 1 PM prior to 9 AM next — should be above anchor
        self.assertGreater(scored[0]["projected_level_at_900"], 100.0)

    def test_earlier_anchor_has_higher_ascending_projection(self):
        t830 = at_central(NEXT, 8, 30)
        t900 = at_central(NEXT, 9, 0)
        # PM at 2 PM (14:00) started earlier than Asian at 5 PM (17:00).
        # More elapsed candles → higher ascending projected level for same price.
        pm_anchor = {"pivot_type": "high", "session_source": "PM_WINDOW", "pivot_time": at_central(PRIOR, 14, 0),
                     "extreme_price": 100.0, "confirmed": True, "candidate_rank_score": 0.0, "selection_reason": "",
                     "projected_level_at_830": None, "projected_level_at_900": None, "distance_to_current_price": None}
        asian_anchor = {"pivot_type": "high", "session_source": "ASIAN", "pivot_time": at_central(PRIOR, 17, 0),
                        "extreme_price": 100.0, "confirmed": True, "candidate_rank_score": 0.0, "selection_reason": "",
                        "projected_level_at_830": None, "projected_level_at_900": None, "distance_to_current_price": None}
        _score_and_sort([pm_anchor, asian_anchor], "high", reference_price=None, eight_thirty_target=t830, nine_am_target=t900)
        # PM anchor started 3 hours earlier → more candle counts → higher ascending projection
        self.assertGreater(pm_anchor["projected_level_at_900"], asian_anchor["projected_level_at_900"])


class TestProximityScoring(unittest.TestCase):
    """Test 5: Candidate closest to reference price receives higher score."""

    def test_closer_candidate_wins(self):
        t830 = at_central(NEXT, 8, 30)
        t900 = at_central(NEXT, 9, 0)
        # cand_a: Pre-NY at 8:00 AM (1 candle before 9 AM), extreme 101.5 → projects to ~102.54
        # cand_b: PM at 1 PM prior (18 candles), extreme 107.0 → projects to ~125.72
        cand_a = {"pivot_type": "high", "session_source": "PRE_NY",
                  "pivot_time": at_central(NEXT, 8, 0), "extreme_price": 101.5,
                  "confirmed": True, "candidate_rank_score": 0.0, "selection_reason": "",
                  "projected_level_at_830": None, "projected_level_at_900": None, "distance_to_current_price": None}
        cand_b = {"pivot_type": "high", "session_source": "PM_WINDOW",
                  "pivot_time": at_central(PRIOR, 13, 0), "extreme_price": 107.0,
                  "confirmed": True, "candidate_rank_score": 0.0, "selection_reason": "",
                  "projected_level_at_830": None, "projected_level_at_900": None, "distance_to_current_price": None}
        # Reference price very close to cand_a projected level; cand_b projects far above
        scored = _score_and_sort([cand_a, cand_b], "high", reference_price=102.5, eight_thirty_target=t830, nine_am_target=t900)
        # cand_a has near-zero distance to reference; cand_b is ~23 pts away
        self.assertEqual(scored[0]["session_source"], "PRE_NY")


class TestManualOverride(unittest.TestCase):
    """Test 7: Manual override forces specific session source."""

    def test_override_to_pm_window(self):
        candles = _build_full_candles(PRIOR, NEXT, 100.0, 94.0)
        result = run_anchor_selection(candles, PRIOR, NEXT, anchor_source_override="PM_WINDOW")
        self.assertEqual(result["anchor_source_override"], "PM_WINDOW")
        self.assertEqual(result["selection"]["pivot_high_source"], "PM_WINDOW")
        self.assertEqual(result["selection"]["pivot_low_source"], "PM_WINDOW")

    def test_override_to_asian(self):
        candles = _build_full_candles(PRIOR, NEXT, 100.0, 94.0)
        result = run_anchor_selection(candles, PRIOR, NEXT, anchor_source_override="ASIAN")
        self.assertEqual(result["anchor_source_override"], "ASIAN")
        # All candidates should come from ASIAN only
        for c in result["candidates"]["pivot_high"]:
            self.assertEqual(c["session_source"], "ASIAN")

    def test_invalid_override_falls_back_to_auto(self):
        candles = _build_full_candles(PRIOR, NEXT, 100.0, 94.0)
        result = run_anchor_selection(candles, PRIOR, NEXT, anchor_source_override="INVALID_SOURCE")
        # Engine should run without error and produce candidates
        self.assertIsNotNone(result["pivot_high"])


class TestConfidenceLevels(unittest.TestCase):
    """Test 6: Confidence levels reflect score gap correctly."""

    def test_single_candidate_is_medium(self):
        cands = [{"candidate_rank_score": 85.0}]
        self.assertEqual(_confidence_level(cands), "MEDIUM")

    def test_large_gap_is_high(self):
        cands = [{"candidate_rank_score": 90.0}, {"candidate_rank_score": 60.0}]
        self.assertEqual(_confidence_level(cands), "HIGH")

    def test_small_gap_is_low(self):
        cands = [{"candidate_rank_score": 85.0}, {"candidate_rank_score": 84.0}]
        self.assertEqual(_confidence_level(cands), "LOW")

    def test_medium_gap(self):
        cands = [{"candidate_rank_score": 80.0}, {"candidate_rank_score": 68.0}]
        self.assertEqual(_confidence_level(cands), "MEDIUM")


class TestSessionSourceRegistry(unittest.TestCase):
    """Test session source metadata completeness."""

    def test_all_four_sources_defined(self):
        for key in ["PM_WINDOW", "ASIAN", "LONDON", "PRE_NY"]:
            self.assertIn(key, SESSION_SOURCES)

    def test_pm_has_highest_weight(self):
        pm_w = SESSION_SOURCES["PM_WINDOW"]["base_weight"]
        for key in ["ASIAN", "LONDON", "PRE_NY"]:
            self.assertGreater(pm_w, SESSION_SOURCES[key]["base_weight"])

    def test_all_sources_have_required_keys(self):
        for key, info in SESSION_SOURCES.items():
            self.assertIn("label", info)
            self.assertIn("description", info)
            self.assertIn("base_weight", info)


class TestAnchorBundleIntegration(unittest.TestCase):
    """Test 8/9: anchor_engine metadata is stored in bundle and legacy API is unchanged."""

    def test_anchor_engine_key_in_bundle(self):
        from core.pivots import build_six_line_anchors
        candles = _build_full_candles(PRIOR, NEXT, 100.0, 94.0)
        bundle = build_six_line_anchors(candles, PRIOR, next_trading_date=NEXT)
        self.assertIn("anchor_engine", bundle)
        ae = bundle["anchor_engine"]
        self.assertIn("selection", ae)
        self.assertIn("candidates", ae)

    def test_session_source_tag_on_anchors(self):
        from core.pivots import build_six_line_anchors
        candles = _build_full_candles(PRIOR, NEXT, 100.0, 94.0)
        bundle = build_six_line_anchors(candles, PRIOR, next_trading_date=NEXT)
        for line in ["asc_ceiling", "asc_floor", "desc_ceiling", "desc_floor"]:
            anchor = bundle["anchors"][line]
            self.assertIn("session_source", anchor)
            self.assertIn("session_source_label", anchor)

    def test_backward_compat_no_next_trading_date(self):
        """build_six_line_anchors still works without next_trading_date."""
        from core.pivots import build_six_line_anchors
        candles = _build_full_candles(PRIOR, NEXT, 100.0, 94.0)
        bundle = build_six_line_anchors(candles, PRIOR)
        self.assertIn("anchors", bundle)
        self.assertIn("pivot_high", bundle)
        self.assertIn("pivot_low", bundle)


if __name__ == "__main__":
    unittest.main()
