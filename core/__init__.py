"""Core engine package for SPX Prophet."""

from core.confluence import score_confluence
from core.data_fetch import extract_spx_830_candle, fetch_es_hourly_candles, fetch_spx_confirmation_candles
from core.pivots import build_six_line_anchors, detect_session_pivots, resolve_anchor_prices
from core.projections import (
    apply_overnight_pivot_overrides,
    convert_projected_lines,
    project_price,
    project_session_lines,
    project_six_lines,
)
from core.scenarios import (
    build_profit_management_plan,
    build_signal_package,
    evaluate_830_confirmation,
    evaluate_trading_scenario,
    get_scenario_reference_outputs,
)
from core.time_utils import (
    at_central,
    build_session_windows,
    get_valid_candle_count,
    market_time_to_central,
    to_central_time,
)

__all__ = [
    "at_central",
    "apply_overnight_pivot_overrides",
    "build_session_windows",
    "build_profit_management_plan",
    "build_signal_package",
    "build_six_line_anchors",
    "convert_projected_lines",
    "detect_session_pivots",
    "evaluate_830_confirmation",
    "evaluate_trading_scenario",
    "extract_spx_830_candle",
    "fetch_es_hourly_candles",
    "fetch_spx_confirmation_candles",
    "get_valid_candle_count",
    "market_time_to_central",
    "project_price",
    "project_session_lines",
    "project_six_lines",
    "get_scenario_reference_outputs",
    "resolve_anchor_prices",
    "score_confluence",
    "to_central_time",
]
