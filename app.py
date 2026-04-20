"""Phase 3 Streamlit integration for SPX Prophet."""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from html import escape
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
try:
    import streamlit as st
    import streamlit.components.v1 as components
    STREAMLIT_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - deployment environment issue
    st = None
    components = None
    STREAMLIT_IMPORT_ERROR = f"Streamlit import failed: {exc.__class__.__name__}: {exc}"

try:
    from core import data_fetch as core_data_fetch

    extract_spx_830_candle = core_data_fetch.extract_spx_830_candle
    fetch_spx_confirmation_candles = core_data_fetch.fetch_spx_confirmation_candles
    fetch_es_hourly_candles_with_diagnostics = getattr(core_data_fetch, "fetch_es_hourly_candles_with_diagnostics", None)
    fetch_es_hourly_candles = getattr(core_data_fetch, "fetch_es_hourly_candles", None)
    from core.pivots import build_six_line_anchors
    from core.projections import (
        LINE_DISPLAY_ORDER,
        apply_overnight_pivot_overrides,
        convert_projected_lines,
        round_price,
        project_six_lines,
    )
    from core.scenarios import (
        build_profit_management_plan,
        build_signal_package,
        evaluate_830_confirmation,
        evaluate_trading_scenario,
    )
    from core.time_utils import at_central, build_session_windows, current_central_time, filter_time_range
    CORE_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - deployment environment issue
    extract_spx_830_candle = None
    fetch_es_hourly_candles_with_diagnostics = None
    fetch_es_hourly_candles = None
    fetch_spx_confirmation_candles = None
    build_six_line_anchors = None
    LINE_DISPLAY_ORDER = []
    apply_overnight_pivot_overrides = None
    convert_projected_lines = None
    round_price = round
    project_six_lines = None
    build_profit_management_plan = None
    build_signal_package = None
    evaluate_830_confirmation = None
    evaluate_trading_scenario = None
    at_central = None
    build_session_windows = None
    current_central_time = None
    filter_time_range = None
    CORE_IMPORT_ERROR = f"Core import failed: {exc.__class__.__name__}: {exc}"

try:
    from options_provider import PROVIDER_NAMES, OptionLookupRequest, load_options_provider
    OPTIONS_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - deployment environment issue
    PROVIDER_NAMES = ["none"]

    class OptionLookupRequest:  # type: ignore[override]
        """Safe fallback request payload when the options bridge is unavailable."""

        def __init__(
            self,
            trade_date: str,
            session: str,
            direction: str,
            strike: int,
            scenario_name: str = "",
            underlying_symbol: str = "SPX",
            option_type: str = "AUTO",
        ) -> None:
            self.trade_date = trade_date
            self.session = session
            self.direction = direction
            self.strike = strike
            self.scenario_name = scenario_name
            self.underlying_symbol = underlying_symbol
            self.option_type = option_type

        def to_dict(self) -> dict[str, Any]:
            return {
                "trade_date": self.trade_date,
                "session": self.session,
                "direction": self.direction,
                "strike": self.strike,
                "scenario_name": self.scenario_name,
                "underlying_symbol": self.underlying_symbol,
                "option_type": self.option_type,
                "provider_status": "options_provider_import_failed",
            }

    class _FallbackOptionsProvider:
        def __init__(self, *, options_mode_enabled: bool = False) -> None:
            self.options_mode_enabled = bool(options_mode_enabled)

        def get_status(self):
            class _Status:
                def to_dict(self_inner) -> dict[str, Any]:
                    return {
                        "provider_name": "none",
                        "readiness_state": "unavailable",
                        "credentials_detected": False,
                        "options_mode_enabled": self.options_mode_enabled,
                        "configured": False,
                        "live_mode_available": False,
                        "implementation_ready": False,
                        "status_label": "Options provider unavailable",
                        "bridge_only": True,
                        "notes": [OPTIONS_IMPORT_ERROR or "Options provider import failed."],
                    }

            return _Status()

        def find_candidate_contracts(self, request: Any) -> list[dict[str, Any]]:
            return []

        def get_option_chain_snapshot(self, request: Any) -> dict[str, Any]:
            return {"provider": "none", "request": getattr(request, "to_dict", lambda: {})(), "status": "unavailable", "contracts": []}

        def get_option_quote(self, request: Any) -> dict[str, Any]:
            return {"provider": "none", "request": getattr(request, "to_dict", lambda: {})(), "status": "unavailable"}

    def load_options_provider(*, provider_name: str, options_mode_enabled: bool, secrets=None, environment=None):
        return _FallbackOptionsProvider(options_mode_enabled=options_mode_enabled)

    OPTIONS_IMPORT_ERROR = f"Options provider import failed: {exc.__class__.__name__}: {exc}"

APP_TITLE = "SPX PROPHET"
APP_VERSION = "v3.2"
TRADE_LOG_PATH = Path(__file__).resolve().parent / "trade_log.json"
SNAPSHOT_LOG_PATH = Path(__file__).resolve().parent / "daily_snapshots.json"
SETTINGS_PATH = Path(__file__).resolve().parent / "settings.json"
QUICK_TAG_OPTIONS = [
    "Green Day",
    "Red Day",
    "Hit All Targets",
    "Stopped Out",
    "Time Stop",
    "Lesson Learned",
    "Late Entry",
    "Perfect Confirmation",
    "Fakeout",
    "No Confirmation",
]
CONFIRMATION_STATUS_OPTIONS = ["Confirmed", "Failed", "Not Applicable", "Not Recorded"]
RESULT_OPTIONS = ["Win", "Loss", "Breakeven", "Time Stop"]
SESSION_OPTIONS = ["NY Options", "Asian Futures"]
TRADE_DIRECTION_OPTIONS = ["CALL", "PUT", "LONG", "SHORT"]
CHECKPOINT_OPTIONS = ["6:00 PM CT", "7:00 PM CT", "8:00 PM CT"]
DEFAULT_SETTINGS = {
    "es_spx_offset": 20.0,
    "news_day": False,
    "preferred_checkpoint": "6:00 PM CT",
    "data_mode": "Auto-fetch",
    "manual_price_space": "SPX",
    "options_provider": "none",
    "options_mode_enabled": False,
}


def get_startup_import_messages() -> list[str]:
    """Collect import/startup diagnostics for deployment-safe rendering."""

    return [message for message in [STREAMLIT_IMPORT_ERROR, CORE_IMPORT_ERROR] if message]


def render_startup_diagnostics() -> None:
    """Render exact startup diagnostics and stop cleanly when required imports fail."""

    messages = get_startup_import_messages()
    if not messages:
        return

    if st is None:
        raise RuntimeError("SPX Prophet startup import check failed. " + " | ".join(messages))

    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.title(f"{APP_TITLE} Startup Diagnostics")
    st.error("SPX Prophet could not finish importing required modules.")
    for message in messages:
        st.code(message)

    repo_root = Path(__file__).resolve().parent
    expected_paths = {
        "app.py": repo_root / "app.py",
        "core/__init__.py": repo_root / "core" / "__init__.py",
        "core/data_fetch.py": repo_root / "core" / "data_fetch.py",
        "core/time_utils.py": repo_root / "core" / "time_utils.py",
        "core/pivots.py": repo_root / "core" / "pivots.py",
        "core/projections.py": repo_root / "core" / "projections.py",
        "core/scenarios.py": repo_root / "core" / "scenarios.py",
        "options_provider.py": repo_root / "options_provider.py",
    }
    st.json(
        {
            "expected_repo_root": str(repo_root),
            "path_checks": {label: path.exists() for label, path in expected_paths.items()},
            "options_provider_import_warning": OPTIONS_IMPORT_ERROR,
        },
        expanded=False,
    )
    st.stop()


def normalize_confirmation_status(value: Any) -> str:
    """Normalize confirmation status values safely."""

    normalized = str(value or "").strip().lower()
    mapping = {
        "confirmed": "Confirmed",
        "failed": "Failed",
        "not applicable": "Not Applicable",
        "n/a": "Not Applicable",
        "na": "Not Applicable",
        "not recorded": "Not Recorded",
        "unknown": "Not Recorded",
        "": "Not Recorded",
    }
    return mapping.get(normalized, "Not Recorded")


def normalize_result_value(value: Any) -> str:
    """Normalize result values safely."""

    normalized = str(value or "").strip().lower()
    mapping = {
        "win": "Win",
        "loss": "Loss",
        "breakeven": "Breakeven",
        "break even": "Breakeven",
        "time stop": "Time Stop",
        "timestop": "Time Stop",
        "": "Breakeven",
    }
    return mapping.get(normalized, "Breakeven")


def normalize_trade_direction(value: Any) -> str:
    """Normalize trade direction values safely."""

    normalized = str(value or "").strip().upper()
    return normalized if normalized in TRADE_DIRECTION_OPTIONS else normalized


def normalize_tags(tags: Any) -> list[str]:
    """Normalize tags into a stable list format."""

    if tags is None:
        return []
    if isinstance(tags, str):
        raw_tags = [piece for piece in tags.split(",") if piece.strip()]
    elif isinstance(tags, list):
        raw_tags = tags
    else:
        raw_tags = [tags]

    normalized_tags: list[str] = []
    seen: set[str] = set()
    for tag in raw_tags:
        clean_tag = " ".join(str(tag).strip().split())
        if not clean_tag:
            continue
        dedupe_key = clean_tag.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized_tags.append(clean_tag)
    return normalized_tags


def normalize_settings_record(raw_settings: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize settings into a stable schema."""

    merged = dict(DEFAULT_SETTINGS)
    if isinstance(raw_settings, dict):
        merged.update(raw_settings)

    merged["es_spx_offset"] = float(merged.get("es_spx_offset", DEFAULT_SETTINGS["es_spx_offset"]))
    merged["news_day"] = bool(merged.get("news_day", DEFAULT_SETTINGS["news_day"]))
    if merged.get("preferred_checkpoint") not in CHECKPOINT_OPTIONS:
        merged["preferred_checkpoint"] = DEFAULT_SETTINGS["preferred_checkpoint"]
    if merged.get("data_mode") not in ["Auto-fetch", "Manual input"]:
        merged["data_mode"] = DEFAULT_SETTINGS["data_mode"]
    if merged.get("manual_price_space") not in ["SPX", "ES"]:
        merged["manual_price_space"] = DEFAULT_SETTINGS["manual_price_space"]
    if merged.get("options_provider") not in PROVIDER_NAMES:
        merged["options_provider"] = DEFAULT_SETTINGS["options_provider"]
    merged["options_mode_enabled"] = bool(merged.get("options_mode_enabled", DEFAULT_SETTINGS["options_mode_enabled"]))
    return merged


def compute_trade_signature(trade: dict[str, Any]) -> str:
    """Compute a lightweight trade signature for duplicate detection."""

    signature_fields = [
        str(trade.get("trade_date", "")),
        str(trade.get("session", "")),
        str(trade.get("scenario_name", "")),
        str(trade.get("direction", "")),
        str(round_price(float(trade.get("entry_line_value", 0.0)))),
        str(round_price(float(trade.get("entry_value", 0.0)))),
        str(round_price(float(trade.get("exit_value", 0.0)))),
        str(int(trade.get("contracts", 0))),
    ]
    return "|".join(signature_fields)


def calculate_trade_pnl_components(trade: dict[str, Any]) -> dict[str, Any]:
    """Calculate trade P&L consistently from trade fields when possible."""

    has_entry_value = "entry_value" in trade and trade.get("entry_value") is not None
    has_exit_value = "exit_value" in trade and trade.get("exit_value") is not None
    has_contracts = "contracts" in trade and trade.get("contracts") is not None
    can_derive = has_entry_value and has_exit_value and has_contracts

    if can_derive:
        try:
            entry_value = float(trade.get("entry_value", 0.0))
            exit_value = float(trade.get("exit_value", 0.0))
            contracts = max(int(trade.get("contracts", 1)), 1)
            direction = normalize_trade_direction(trade.get("direction", ""))
            if direction not in TRADE_DIRECTION_OPTIONS:
                raise ValueError("Unsupported direction for derived P&L")
            pnl_value = compute_preview_pnl(direction, entry_value, exit_value, contracts)
            return {"pnl_value": pnl_value, "pnl_source": "derived"}
        except (TypeError, ValueError):
            pass

    return {
        "pnl_value": round_price(float(trade.get("pnl_preview", 0.0))),
        "pnl_source": "preview-only",
    }


def build_trade_integrity_flags(trade: dict[str, Any]) -> list[str]:
    """Detect incomplete or suspicious trade fields."""

    flags: list[str] = []
    if not str(trade.get("scenario_name", "")).strip():
        flags.append("missing_scenario")
    if not str(trade.get("entry_line_label", "")).strip():
        flags.append("missing_entry_line")
    if not str(trade.get("trade_date", "")).strip():
        flags.append("missing_trade_date")
    if not str(trade.get("session", "")).strip():
        flags.append("missing_session")
    if not str(trade.get("direction", "")).strip():
        flags.append("missing_direction")
    return flags


def initialize_app_state() -> None:
    """Initialize stable session-state keys used across reruns."""

    st.session_state.setdefault("trade_form_prefill", {})
    st.session_state.setdefault("trade_form_notice", None)


def clear_trade_form_prefill() -> None:
    """Clear any persisted trade-form prefill state."""

    st.session_state.pop("trade_form_prefill", None)
    st.session_state.pop("trade_form_notice", None)


def is_valid_price_input(value: float | None) -> bool:
    """Return True when a numeric price input is usable."""

    return value is not None and float(value) > 0


def safe_option_index(options: list[Any], value: Any, default: int = 0) -> int:
    """Return a safe selectbox index for a value."""

    try:
        return options.index(value)
    except ValueError:
        return default


def backup_malformed_store(path: Path) -> str | None:
    """Move a malformed JSON store aside so the app can continue safely."""

    if not path.exists():
        return None

    backup_path = path.with_name(f"{path.stem}.malformed.{uuid4().hex[:8]}{path.suffix}.bak")
    try:
        path.replace(backup_path)
    except OSError:
        return None
    return backup_path.name


def load_json_list_store(path: Path, label: str) -> tuple[list[dict[str, Any]], str | None]:
    """Load a JSON list store safely and recover from malformed contents."""

    if not path.exists():
        return [], None

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        backup_name = backup_malformed_store(path)
        if backup_name:
            return [], f"Malformed JSON detected in {path.name}. Backed it up as {backup_name} and reset the store."
        return [], f"Malformed JSON detected in {path.name}. Starting with an empty {label} store."
    except OSError as exc:
        return [], f"Unable to read {path.name}: {exc}"

    if not isinstance(raw, list):
        backup_name = backup_malformed_store(path)
        if backup_name:
            return [], f"{path.name} did not contain a list. Backed it up as {backup_name} and reset the store."
        return [], f"{path.name} did not contain a list. Starting with an empty {label} store."

    cleaned = [item for item in raw if isinstance(item, dict)]
    skipped = len(raw) - len(cleaned)
    if skipped > 0:
        return cleaned, f"Skipped {skipped} invalid record(s) while loading {path.name}."
    return cleaned, None


def load_json_dict_store(path: Path, label: str, defaults: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Load a JSON dict store safely and recover from malformed contents."""

    if not path.exists():
        return dict(defaults), None

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        backup_name = backup_malformed_store(path)
        if backup_name:
            return dict(defaults), f"Malformed JSON detected in {path.name}. Backed it up as {backup_name} and reset the store."
        return dict(defaults), f"Malformed JSON detected in {path.name}. Starting with default {label} settings."
    except OSError as exc:
        return dict(defaults), f"Unable to read {path.name}: {exc}"

    if not isinstance(raw, dict):
        backup_name = backup_malformed_store(path)
        if backup_name:
            return dict(defaults), f"{path.name} did not contain an object. Backed it up as {backup_name} and reset the store."
        return dict(defaults), f"{path.name} did not contain an object. Starting with default {label} settings."

    merged = dict(defaults)
    merged.update(raw)
    return merged, None


def save_json_list_store(path: Path, records: list[dict[str, Any]], label: str) -> tuple[bool, str | None]:
    """Persist a JSON list store atomically."""

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f"{path.name}.tmp")
        temp_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
        temp_path.replace(path)
    except OSError as exc:
        return False, f"Unable to save {label}: {exc}"
    return True, None


def save_json_dict_store(path: Path, record: dict[str, Any], label: str) -> tuple[bool, str | None]:
    """Persist a JSON dict store atomically."""

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f"{path.name}.tmp")
        temp_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        temp_path.replace(path)
    except OSError as exc:
        return False, f"Unable to save {label}: {exc}"
    return True, None


def load_settings() -> tuple[dict[str, Any], str | None]:
    """Load persisted user settings with safe defaults."""

    settings, message = load_json_dict_store(SETTINGS_PATH, "app", DEFAULT_SETTINGS)
    return normalize_settings_record(settings), message


def save_settings(settings: dict[str, Any]) -> tuple[bool, str | None]:
    """Save persisted user settings."""

    payload = normalize_settings_record(settings)
    return save_json_dict_store(SETTINGS_PATH, payload, "settings")


def validate_app_inputs(inputs: dict[str, Any]) -> dict[str, list[str]]:
    """Validate sidebar inputs and classify issues by severity."""

    errors: list[str] = []
    warnings: list[str] = []

    if inputs["prior_session_date"] >= inputs["next_trading_date"]:
        errors.append("Next trading date must be after the prior NY session date.")

    if inputs["data_mode"] == "Manual input":
        manual_values = {
            "Rejection green candle high": inputs["pivot_green_high"],
            "Rejection red candle high": inputs["pivot_red_high"],
            "Bounce red candle low": inputs["pivot_red_low"],
            "Bounce green candle low": inputs["pivot_green_low"],
            "Highest wick price": inputs["hw_price"],
            "Lowest wick price": inputs["lw_price"],
        }
        invalid_manual = [label for label, value in manual_values.items() if not is_valid_price_input(value)]
        if invalid_manual:
            errors.append(f"Manual mode requires positive prices for: {', '.join(invalid_manual)}.")

    if not is_valid_price_input(inputs["current_spx_price"]):
        warnings.append("Tab 1 current SPX price is missing or invalid. Scenario-driven NY decision sections will be limited.")

    if not is_valid_price_input(inputs["current_es_price"]):
        warnings.append("Tab 2 current ES price is missing or invalid. Reference framework and handoff will be limited.")

    if float(inputs["es_spx_offset"]) < 0:
        warnings.append("ES-SPX offset is negative. This is allowed, but it is unusual and may indicate a settings issue.")

    return {"errors": errors, "warnings": warnings}


def build_unavailable_confirmation(reason: str) -> dict[str, Any]:
    """Build a consistent unavailable-confirmation payload."""

    return {
        "available": False,
        "tested": False,
        "confirmed": False,
        "failed": False,
        "status": reason,
        "entry_timing": "Enter only after a valid retest is available.",
    }


def enrich_auto_fetch_diagnostics(
    diagnostics: dict[str, Any] | None,
    candles: pd.DataFrame | None,
    prior_session_date: date,
    next_trading_date: date,
) -> dict[str, Any]:
    """Add session-filter and pivot diagnostics to the chosen ES fetch attempt."""

    enriched = dict(diagnostics or {})
    enriched.setdefault("mode", "Auto-fetch")
    enriched.setdefault("row_count_in_full_ny_session_filter", 0)
    enriched.setdefault("row_count_in_12_pm_to_4_pm_ct_afternoon_filter", 0)
    enriched.setdefault("row_count_in_overnight_filter", 0)
    enriched.setdefault("pivot_high_found", False)
    enriched.setdefault("pivot_low_found", False)
    enriched.setdefault("session_extremes_found", False)
    enriched.setdefault("explicit_error_message_if_dataframe_is_empty", None)
    enriched.setdefault("final_fetch_method_chosen", None)
    enriched.setdefault("successful_fetch_attempt", None)
    enriched.setdefault("all_attempts_returned_empty_data", False)

    normalized = candles.copy() if candles is not None else pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])
    if normalized.empty:
        enriched["explicit_error_message_if_dataframe_is_empty"] = (
            enriched.get("explicit_error_message_if_dataframe_is_empty")
            or "Yahoo returned no usable intraday ES=F data for the selected dates."
        )
        return enriched

    session_windows = build_session_windows(prior_session_date, next_trading_date)
    ny_session = filter_time_range(normalized, *session_windows["prior_ny_session"])
    afternoon = filter_time_range(normalized, *session_windows["prior_afternoon"])
    overnight = filter_time_range(normalized, at_central(prior_session_date, 17, 0), at_central(next_trading_date, 9, 0))

    enriched["row_count_in_full_ny_session_filter"] = int(len(ny_session))
    enriched["row_count_in_12_pm_to_4_pm_ct_afternoon_filter"] = int(len(afternoon))
    enriched["row_count_in_overnight_filter"] = int(len(overnight))

    if len(afternoon) >= 3:
        closes = afternoon["close"].astype(float).tolist()
        enriched["pivot_high_found"] = any(
            closes[index] > closes[index - 1] and closes[index] > closes[index + 1]
            for index in range(1, len(closes) - 1)
        )
        enriched["pivot_low_found"] = any(
            closes[index] < closes[index - 1] and closes[index] < closes[index + 1]
            for index in range(1, len(closes) - 1)
        )

    if not ny_session.empty:
        red_exists = bool((ny_session["close"].astype(float) < ny_session["open"].astype(float)).any())
        green_exists = bool((ny_session["close"].astype(float) > ny_session["open"].astype(float)).any())
        enriched["session_extremes_found"] = red_exists and green_exists

    return enriched


def fetch_es_candles_for_app(prior_session_date: date, next_trading_date: date) -> tuple[pd.DataFrame | None, dict[str, Any] | None]:
    """Fetch ES candles using the best available helper export."""

    if fetch_es_hourly_candles_with_diagnostics is not None:
        return fetch_es_hourly_candles_with_diagnostics(prior_session_date, next_trading_date)

    if fetch_es_hourly_candles is not None:
        candles = fetch_es_hourly_candles(prior_session_date, next_trading_date)
        return candles, {
            "mode": "Auto-fetch",
            "raw_ticker_used": "ES=F",
            "successful_fetch_attempt": "legacy_fetch_es_hourly_candles",
            "final_fetch_method_chosen": "Legacy core.data_fetch.fetch_es_hourly_candles export",
            "fetch_attempts": [
                {
                    "name": "legacy_fetch_es_hourly_candles",
                    "description": "Legacy core.data_fetch export",
                    "status": "usable" if candles is not None and not candles.empty else "empty",
                    "raw_row_count": int(len(candles)) if candles is not None else 0,
                    "normalized_row_count": int(len(candles)) if candles is not None else 0,
                    "rows_returned": bool(candles is not None and not candles.empty),
                    "error": None,
                }
            ],
            "all_attempts_returned_empty_data": bool(candles is None or candles.empty),
            "explicit_error_message_if_dataframe_is_empty": (
                "Yahoo returned no usable intraday ES=F data for the selected dates."
                if candles is None or candles.empty
                else None
            ),
            "fetch_error": None,
            "raw_yfinance_request_parameters": None,
            "row_count_returned_before_any_filtering": int(len(candles)) if candles is not None else 0,
            "first_timestamp_returned": None,
            "last_timestamp_returned": None,
            "timezone_info_before_conversion": "legacy_helper_unavailable",
            "row_count_after_timezone_conversion": int(len(candles)) if candles is not None else 0,
        }

    raise ImportError(
        "Neither fetch_es_hourly_candles_with_diagnostics nor fetch_es_hourly_candles is available in core.data_fetch."
    )


def inject_app_styles() -> None:
    """Apply the premium SPX Prophet visual system."""

    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap');
        :root {
            --spx-bg: #04070d;
            --spx-bg-soft: #0b1120;
            --spx-card: rgba(10, 15, 26, 0.86);
            --spx-card-strong: rgba(13, 19, 33, 0.94);
            --spx-border: rgba(255, 255, 255, 0.08);
            --spx-text: #ecf4ff;
            --spx-muted: #8ea1bc;
            --spx-muted-2: #5e708d;
            --spx-cyan: #00d4ff;
            --spx-green: #00e676;
            --spx-red: #ff5a76;
            --spx-gold: #ffd740;
            --spx-purple: #b388ff;
        }
        .stApp {
            background:
                radial-gradient(circle at top left, rgba(0, 212, 255, 0.08), transparent 24%),
                radial-gradient(circle at top right, rgba(179, 136, 255, 0.06), transparent 18%),
                linear-gradient(180deg, #04070d 0%, #09111e 58%, #05080f 100%);
            color: var(--spx-text);
        }
        .main .block-container {
            padding-top: 1rem;
            padding-bottom: 2.4rem;
            max-width: 1400px;
        }
        h1, h2, h3, h4 {
            font-family: "Outfit", "Segoe UI", sans-serif !important;
            letter-spacing: 0.01em;
            color: var(--spx-text);
        }
        p, li, label, div[data-testid="stMarkdownContainer"] {
            color: var(--spx-text);
        }
        .spx-shell {
            position: relative;
            overflow: hidden;
            border: 1px solid var(--spx-border);
            border-radius: 22px;
            padding: 1.05rem 1.2rem;
            background:
                linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.01)),
                var(--spx-card);
            margin-bottom: 1rem;
            box-shadow:
                0 12px 40px rgba(0, 0, 0, 0.28),
                inset 0 1px 0 rgba(255,255,255,0.03);
            animation: spxFadeUp 0.45s ease both;
        }
        .spx-shell::before {
            content: "";
            position: absolute;
            inset: 0 auto auto 0;
            width: 100%;
            height: 1px;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.18), transparent);
            opacity: 0.45;
        }
        .spx-section-title {
            font-size: 0.76rem;
            font-weight: 800;
            letter-spacing: 0.16em;
            text-transform: uppercase;
            color: var(--spx-muted);
            margin-bottom: 0.35rem;
        }
        .spx-section-subtitle {
            color: #d3deef;
            font-size: 0.98rem;
            margin-bottom: 0.15rem;
            line-height: 1.55;
        }
        .spx-summary {
            position: relative;
            overflow: hidden;
            border: 1px solid rgba(0, 212, 255, 0.22);
            background:
                radial-gradient(circle at 15% 25%, rgba(0, 212, 255, 0.18), transparent 28%),
                linear-gradient(135deg, rgba(0, 212, 255, 0.12), rgba(0, 212, 255, 0.03) 55%, rgba(255,255,255,0.02));
            border-radius: 22px;
            padding: 1.05rem 1.2rem;
            margin-bottom: 1rem;
            box-shadow: 0 16px 40px rgba(0, 0, 0, 0.25), 0 0 24px rgba(0, 212, 255, 0.08);
            animation: spxFadeUp 0.45s ease both;
        }
        .spx-summary-title {
            font-size: 0.76rem;
            text-transform: uppercase;
            letter-spacing: 0.16em;
            color: #7fe7ff;
            font-weight: 800;
            margin-bottom: 0.45rem;
        }
        .spx-summary-body {
            color: #f4fbff;
            font-size: 1.03rem;
            line-height: 1.65;
            font-weight: 600;
        }
        .spx-hero {
            position: relative;
            overflow: hidden;
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 28px;
            padding: 1.35rem 1.35rem 1.1rem 1.35rem;
            background:
                radial-gradient(circle at 12% 18%, rgba(0, 212, 255, 0.16), transparent 24%),
                radial-gradient(circle at 88% 0%, rgba(255, 90, 118, 0.12), transparent 22%),
                linear-gradient(145deg, rgba(13, 20, 34, 0.97), rgba(7, 11, 20, 0.98));
            margin-bottom: 1rem;
            box-shadow: 0 24px 60px rgba(0,0,0,0.34);
            animation: spxFadeUp 0.5s ease both;
        }
        .spx-hero::after {
            content: "";
            position: absolute;
            inset: auto -10% -45% auto;
            width: 42%;
            height: 75%;
            background: radial-gradient(circle, rgba(0,212,255,0.10), transparent 68%);
            pointer-events: none;
        }
        .spx-hero-top {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 1rem;
            margin-bottom: 1rem;
        }
        .spx-hero-kicker {
            color: var(--spx-muted);
            text-transform: uppercase;
            letter-spacing: 0.18em;
            font-size: 0.75rem;
            font-weight: 800;
            margin-bottom: 0.35rem;
        }
        .spx-hero-title {
            font-family: "Outfit", "Segoe UI", sans-serif;
            font-size: 2rem;
            font-weight: 800;
            line-height: 1.05;
            color: #f8fbff;
            margin: 0 0 0.35rem 0;
        }
        .spx-hero-subtitle {
            color: #bdd0e8;
            font-size: 1rem;
            line-height: 1.55;
            max-width: 760px;
        }
        .spx-hero-status {
            min-width: 220px;
            text-align: right;
        }
        .spx-hero-status-label {
            color: var(--spx-muted);
            text-transform: uppercase;
            letter-spacing: 0.14em;
            font-size: 0.72rem;
            margin-bottom: 0.35rem;
            font-weight: 800;
        }
        .spx-status-chip {
            display: inline-flex;
            align-items: center;
            gap: 0.55rem;
            padding: 0.75rem 1rem;
            border-radius: 999px;
            border: 1px solid rgba(255,255,255,0.08);
            font-weight: 800;
            color: #f8fbff;
            background: rgba(255,255,255,0.04);
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.04);
        }
        .spx-status-chip.good {
            background: linear-gradient(135deg, rgba(0, 230, 118, 0.18), rgba(0, 230, 118, 0.05));
            border-color: rgba(0,230,118,0.26);
        }
        .spx-status-chip.bad {
            background: linear-gradient(135deg, rgba(255, 23, 68, 0.18), rgba(255, 23, 68, 0.06));
            border-color: rgba(255,23,68,0.28);
            animation: spxPulseAlert 2.8s ease-in-out infinite;
        }
        .spx-hero-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.9rem;
        }
        .spx-hero-stat {
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 20px;
            padding: 0.95rem 1rem;
            background: rgba(255,255,255,0.03);
            backdrop-filter: blur(8px);
        }
        .spx-hero-stat-label {
            color: var(--spx-muted);
            text-transform: uppercase;
            letter-spacing: 0.12em;
            font-size: 0.72rem;
            font-weight: 800;
            margin-bottom: 0.35rem;
        }
        .spx-hero-stat-value {
            font-family: "JetBrains Mono", monospace;
            font-size: 1.28rem;
            font-weight: 700;
            color: #f8fbff;
            line-height: 1.2;
        }
        .spx-hero-stat-note {
            color: var(--spx-muted);
            font-size: 0.85rem;
            margin-top: 0.3rem;
        }
        .spx-banner {
            position: relative;
            overflow: hidden;
            border-radius: 22px;
            padding: 1.1rem 1.15rem;
            margin-bottom: 1rem;
            border: 1px solid rgba(255, 255, 255, 0.08);
            background:
                radial-gradient(circle at top left, rgba(0,212,255,0.11), transparent 24%),
                linear-gradient(135deg, rgba(18, 26, 42, 0.96), rgba(9, 14, 24, 0.94));
            box-shadow: 0 16px 42px rgba(0,0,0,0.26);
            animation: spxFadeUp 0.45s ease both;
        }
        .spx-banner-name {
            font-family: "Outfit", "Segoe UI", sans-serif;
            font-size: 1.36rem;
            font-weight: 800;
            color: #f8fbff;
            margin-bottom: 0.35rem;
        }
        .spx-banner-meta {
            color: var(--spx-muted);
            font-size: 0.9rem;
            margin-bottom: 0.35rem;
        }
        .spx-banner-text {
            color: #d8e1ee;
            font-size: 0.96rem;
            line-height: 1.58;
        }
        .spx-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.28rem 0.62rem;
            border-radius: 999px;
            font-size: 0.72rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-right: 0.45rem;
            margin-bottom: 0.2rem;
            border: 1px solid rgba(255, 255, 255, 0.08);
            color: #f8fbff;
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(6px);
        }
        .spx-pill.conf-high { background: rgba(0,230,118,0.14); border-color: rgba(0,230,118,0.24); }
        .spx-pill.conf-medium { background: rgba(0,212,255,0.12); border-color: rgba(0,212,255,0.24); }
        .spx-pill.conf-low { background: rgba(255,212,64,0.14); border-color: rgba(255,212,64,0.28); color: #fff2bf; }
        .spx-pill.scenario-bullish { background: rgba(0,230,118,0.12); border-color: rgba(0,230,118,0.22); }
        .spx-pill.scenario-bearish { background: rgba(255,90,118,0.14); border-color: rgba(255,90,118,0.24); }
        .spx-pill.scenario-neutral { background: rgba(0,212,255,0.12); border-color: rgba(0,212,255,0.24); }
        .spx-pill.scenario-warning { background: rgba(255,212,64,0.14); border-color: rgba(255,212,64,0.24); color: #fff4c5; }
        .spx-pill.scenario-compression { background: rgba(179,136,255,0.14); border-color: rgba(179,136,255,0.24); }
        .spx-play-note, .spx-muted {
            color: var(--spx-muted);
            font-size: 0.88rem;
            line-height: 1.45;
        }
        .spx-card {
            position: relative;
            overflow: hidden;
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 22px;
            padding: 1.05rem 1.1rem;
            background:
                linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.012)),
                var(--spx-card-strong);
            box-shadow: 0 14px 34px rgba(0,0,0,0.22);
            transition: transform 180ms ease, box-shadow 180ms ease, border-color 180ms ease;
            animation: spxFadeUp 0.45s ease both;
        }
        .spx-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 20px 42px rgba(0,0,0,0.28);
        }
        .spx-card.primary { border-color: rgba(0,212,255,0.16); }
        .spx-card.alternate { border-color: rgba(255,255,255,0.08); }
        .spx-card.levels { border-color: rgba(255,212,64,0.16); }
        .spx-card-title {
            display: flex;
            align-items: center;
            gap: 0.8rem;
            margin-bottom: 0.9rem;
        }
        .spx-card-icon {
            width: 2.55rem;
            height: 2.55rem;
            border-radius: 18px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-size: 1.3rem;
            font-weight: 800;
            background: rgba(255,255,255,0.05);
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.05);
        }
        .spx-card-heading {
            font-family: "Outfit", "Segoe UI", sans-serif;
            font-size: 1.16rem;
            font-weight: 700;
            color: #f8fbff;
            line-height: 1.2;
        }
        .spx-card-subtitle {
            color: var(--spx-muted);
            font-size: 0.88rem;
            margin-top: 0.15rem;
        }
        .spx-card-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.7rem;
            margin-bottom: 0.9rem;
        }
        .spx-card-stat {
            border: 1px solid rgba(255,255,255,0.07);
            border-radius: 16px;
            padding: 0.78rem 0.82rem;
            background: rgba(255,255,255,0.025);
        }
        .spx-card-stat-label {
            color: var(--spx-muted);
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            font-weight: 800;
            margin-bottom: 0.25rem;
        }
        .spx-card-stat-value {
            color: #f8fbff;
            font-size: 1rem;
            font-family: "JetBrains Mono", monospace;
            font-weight: 700;
            line-height: 1.35;
        }
        .spx-card-copy {
            color: #d7e2f1;
            font-size: 0.92rem;
            line-height: 1.6;
        }
        .spx-inline-list {
            display: flex;
            flex-wrap: wrap;
            gap: 0.55rem;
        }
        .spx-mini-line {
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            padding: 0.46rem 0.6rem;
            border-radius: 999px;
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.07);
            font-size: 0.82rem;
            color: #deebff;
        }
        .spx-mini-line .mono {
            font-family: "JetBrains Mono", monospace;
            font-weight: 700;
        }
        .spx-status-good {
            border: 1px solid rgba(0, 230, 118, 0.2);
            background: linear-gradient(135deg, rgba(0, 230, 118, 0.12), rgba(0, 230, 118, 0.04));
            border-radius: 18px;
            padding: 1rem 1.05rem;
            margin-bottom: 1rem;
        }
        .spx-status-bad {
            border: 1px solid rgba(255, 23, 68, 0.25);
            background: linear-gradient(135deg, rgba(255, 23, 68, 0.13), rgba(255, 23, 68, 0.05));
            border-radius: 18px;
            padding: 1rem 1.05rem;
            margin-bottom: 1rem;
            box-shadow: 0 0 26px rgba(255,23,68,0.08);
        }
        .spx-status-title {
            color: #f8fbff;
            font-weight: 800;
            margin-bottom: 0.35rem;
            font-size: 1rem;
        }
        .spx-reference {
            border-left: 3px solid rgba(255, 212, 64, 0.9);
            padding: 0.75rem 0.9rem;
            background: rgba(255, 212, 64, 0.08);
            border-radius: 0 12px 12px 0;
            color: #f4e6ac;
            margin-bottom: 0.8rem;
        }
        .spx-spacer-sm {
            height: 0.35rem;
        }
        .spx-spacer-md {
            height: 0.75rem;
        }
        div[data-testid="stForm"] {
            border: 1px solid rgba(255,255,255,0.07);
            border-radius: 22px;
            padding: 1rem 1rem 0.4rem 1rem;
            background: rgba(8, 12, 22, 0.72);
        }
        div[data-testid="stTextInput"] label,
        div[data-testid="stNumberInput"] label,
        div[data-testid="stSelectbox"] label,
        div[data-testid="stDateInput"] label,
        div[data-testid="stMultiSelect"] label,
        div[data-testid="stTextArea"] label {
            color: var(--spx-muted) !important;
            font-size: 0.8rem !important;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-weight: 700 !important;
        }
        div[data-baseweb="input"] > div,
        div[data-baseweb="select"] > div,
        textarea {
            background: rgba(7, 11, 20, 0.94) !important;
            border-color: rgba(255,255,255,0.08) !important;
            border-radius: 14px !important;
        }
        div[data-testid="stButton"] > button,
        div[data-testid="stDownloadButton"] > button {
            border-radius: 14px;
            border: 1px solid rgba(255,255,255,0.08);
            background: linear-gradient(135deg, rgba(20,28,45,0.96), rgba(10,16,28,0.96));
            color: #f4f8ff;
            font-weight: 700;
            transition: transform 150ms ease, box-shadow 150ms ease, border-color 150ms ease;
            box-shadow: 0 10px 22px rgba(0,0,0,0.16);
        }
        div[data-testid="stButton"] > button:hover,
        div[data-testid="stDownloadButton"] > button:hover {
            transform: translateY(-1px);
            border-color: rgba(0,212,255,0.22);
            box-shadow: 0 16px 30px rgba(0,0,0,0.22);
        }
        div[data-testid="stMetric"] {
            background:
                linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.01)),
                rgba(10, 16, 28, 0.88);
            border: 1px solid rgba(255, 255, 255, 0.07);
            border-radius: 18px;
            padding: 0.9rem 0.95rem;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.03);
        }
        div[data-testid="stMetricLabel"] {
            color: var(--spx-muted);
        }
        div[data-testid="stMetricValue"] {
            font-family: "JetBrains Mono", monospace;
        }
        div[data-testid="stDataFrame"] {
            border-radius: 18px;
            overflow: hidden;
        }
        div[data-testid="stExpander"] {
            border: 1px solid rgba(255, 255, 255, 0.07);
            border-radius: 18px;
            background: rgba(8, 12, 22, 0.76);
            overflow: hidden;
        }
        div[data-testid="stTabs"] button {
            font-family: "JetBrains Mono", monospace !important;
            font-weight: 700;
            letter-spacing: 0.04em;
            border-radius: 12px 12px 0 0;
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, rgba(10,15,25,0.98), rgba(6,10,18,0.98));
            border-right: 1px solid rgba(255,255,255,0.06);
        }
        [data-testid="stSidebar"] .block-container {
            padding-top: 1rem;
        }
        @keyframes spxFadeUp {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        @keyframes spxPulseAlert {
            0%, 100% { box-shadow: 0 0 0 rgba(255,23,68,0.0); }
            50% { box-shadow: 0 0 28px rgba(255,23,68,0.16); }
        }
        @media (max-width: 1080px) {
            .spx-hero-top {
                flex-direction: column;
            }
            .spx-hero-status {
                text-align: left;
            }
            .spx-hero-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
            .spx-card-grid {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_section_header(title: str, subtitle: str | None = None) -> None:
    """Render a compact styled section header."""

    subtitle_html = f'<div class="spx-section-subtitle">{subtitle}</div>' if subtitle else ""
    st.markdown(
        f"""
        <div class="spx-shell">
            <div class="spx-section-title">{title}</div>
            {subtitle_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_release_hygiene() -> None:
    """Render version, method, assumptions, and daily workflow guidance."""

    st.markdown(
        f"""
        <div class="spx-shell">
            <div class="spx-section-title">Release</div>
            <div class="spx-section-subtitle">{APP_TITLE} {APP_VERSION}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander("About / Method", expanded=False):
        st.write("SPX Prophet projects diagonal structure from prior-session anchors, evaluates scenario location, and combines that with confirmation, sit-out logic, journaling, and performance intelligence.")
        st.write("Version 3 focuses on edge proof analytics and productization prep while preserving the current operator workflow.")
    with st.expander("Assumptions", expanded=False):
        st.write("- Fixed rate = 1.04")
        st.write("- Nearby threshold = 5 points")
        st.write("- Override candidates must be projected to the same timestamp before comparison")
        st.write("- Expectancy uses stored journal P&L previews for wins and losses")
    with st.expander("Daily Workflow", expanded=False):
        st.write("1. Review Tab 1 for the NY structure, scenario, confirmation, and sit-out state.")
        st.write("2. Review Tab 2 if the evening ES session matters for the day.")
        st.write("3. Log the trade in Tab 3 using the handoff buttons or manual entry.")
        st.write("4. Review analytics, snapshots, and setup quality in Tab 3.")
    with st.expander("Maintenance Note", expanded=False):
        st.write(f"Current storage mode: local JSON files.")
        st.write("Future migration target: SQLite or another database-backed storage layer.")
        st.write(f"Current release: {APP_TITLE} {APP_VERSION}.")


def get_scenario_tone(scenario_name: str) -> str:
    """Map a scenario name to a visual tone."""

    name = str(scenario_name or "").upper()
    if "OVERLAP" in name or "COMPRESSION" in name:
        return "compression"
    if "EXTREME" in name or "SIT OUT" in name:
        return "warning"
    if "ASCENDING" in name or "GAP UP" in name or "PUT" in name:
        return "bearish"
    if "DESCENDING" in name or "GAP DOWN" in name or "CALL" in name:
        return "bullish"
    return "neutral"


def get_confidence_tone(confidence: str) -> str:
    """Map a confidence label to a CSS tone."""

    normalized = str(confidence or "").strip().lower()
    if normalized == "high":
        return "high"
    if normalized == "low":
        return "low"
    return "medium"


def render_tab1_hero(
    signal_package: dict[str, Any] | None,
    current_spx_price: float | None,
    current_es_price: float | None,
    effective_offset: float,
) -> None:
    """Render the compact Tab 1 hero header."""

    if signal_package is None:
        scenario_name = "Awaiting Valid SPX Input"
        confidence = "Pending"
        status_label = "Workflow Limited"
        status_class = "bad"
        status_icon = "!"
    else:
        scenario = signal_package["scenario"]
        sit_out = signal_package["sit_out"]
        scenario_name = scenario["scenario_name"]
        confidence = scenario["confidence_level"]
        status_label = "Sit Out Active" if sit_out["sit_out"] else "Eligible To Trade"
        status_class = "bad" if sit_out["sit_out"] else "good"
        status_icon = "●" if not sit_out["sit_out"] else "!"

    confidence_tone = get_confidence_tone(confidence)
    current_display = format_price(current_spx_price) if is_valid_price_input(current_spx_price) else "Not entered"

    st.markdown(
        f"""
        <div class="spx-hero">
            <div class="spx-hero-top">
                <div>
                    <div class="spx-hero-kicker">Decision Screen</div>
                    <div class="spx-hero-title">{escape(scenario_name)}</div>
                    <div class="spx-banner-meta">
                        <span class="spx-pill conf-{confidence_tone}">Confidence {escape(confidence)}</span>
                    </div>
                </div>
                <div class="spx-hero-status">
                    <div class="spx-hero-status-label">Current Price</div>
                    <div style="font-family:'JetBrains Mono', monospace; font-size:2.1rem; font-weight:800; color:#f8fbff; text-shadow:0 0 20px rgba(0,212,255,0.22); margin-bottom:0.65rem;">{current_display}</div>
                    <div class="spx-status-chip {status_class}"><span>{status_icon}</span><span>{escape(status_label)}</span></div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_key_levels_card(
    final_lines: dict[str, dict[str, Any]],
    current_spx_price: float | None,
    effective_offset: float,
) -> None:
    """Render a compact key-levels summary card."""

    current_label = format_price(current_spx_price) if is_valid_price_input(current_spx_price) else "Not entered"
    chips = "".join(
        f'<div class="spx-mini-line"><span>{escape(final_lines[name]["label"])} (SPX)</span><span class="mono">{format_price(final_lines[name]["projected_price"])}</span></div>'
        for name in LINE_DISPLAY_ORDER
    )
    st.markdown(
        f"""
        <div class="spx-card levels">
            <div class="spx-card-title">
                <div class="spx-card-icon">◆</div>
                <div>
                    <div class="spx-card-heading">Key Levels Summary</div>
                    <div class="spx-card-subtitle">Fast scan of the full projected stack in SPX decision terms.</div>
                </div>
            </div>
            <div class="spx-card-grid">
                <div class="spx-card-stat">
                    <div class="spx-card-stat-label">Current Price (SPX)</div>
                    <div class="spx-card-stat-value">{current_label}</div>
                </div>
                <div class="spx-card-stat">
                    <div class="spx-card-stat-label">Effective Offset</div>
                    <div class="spx-card-stat-value">{format_price(effective_offset)}</div>
                </div>
            </div>
            <div class="spx-inline-list">{chips}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def resolve_line_from_projected_bundle(
    projected_lines: dict[str, dict[str, Any]],
    line_label: str | None,
) -> dict[str, Any] | None:
    """Resolve a scenario line label against the final projected bundle."""

    if not line_label:
        return None

    normalized = str(line_label).strip().lower()
    if normalized in projected_lines:
        return projected_lines[normalized]

    for line_name, details in projected_lines.items():
        label = str(details.get("label", "")).strip().lower()
        if normalized == label:
            return details
        if normalized == line_name.replace("_", " "):
            return details

    return None


def resolve_play_display_values(
    play: dict[str, Any] | None,
    projected_lines: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Force displayed play prices to use final projected line values when available."""

    if play is None:
        return None

    resolved_play: dict[str, Any] = dict(play)
    for leg_name in ("entry", "stop", "tp1", "tp2"):
        leg = play.get(leg_name)
        if not isinstance(leg, dict):
            continue
        resolved_leg = dict(leg)
        resolved_line = resolve_line_from_projected_bundle(projected_lines, leg.get("label"))
        if resolved_line is not None:
            resolved_leg["price"] = float(resolved_line["projected_price"])
        resolved_play[leg_name] = resolved_leg

    return resolved_play


def build_ladder_items(
    projected_lines: dict[str, dict[str, Any]],
    current_price: float | None,
) -> list[dict[str, Any]]:
    """Build ladder markers from projected lines and current price."""

    items: list[dict[str, Any]] = [
        {
            "key": "hw",
            "label": projected_lines["hw"]["label"],
            "value": float(projected_lines["hw"]["projected_price"]),
            "side": "left",
            "color": "#ffd740",
            "kind": "extreme",
        },
        {
            "key": "asc_ceiling",
            "label": projected_lines["asc_ceiling"]["label"],
            "value": float(projected_lines["asc_ceiling"]["projected_price"]),
            "side": "left",
            "color": "#ff4d6d",
            "kind": "ascending",
        },
        {
            "key": "asc_floor",
            "label": projected_lines["asc_floor"]["label"],
            "value": float(projected_lines["asc_floor"]["projected_price"]),
            "side": "left",
            "color": "#ff8a80",
            "kind": "ascending",
        },
        {
            "key": "desc_ceiling",
            "label": projected_lines["desc_ceiling"]["label"],
            "value": float(projected_lines["desc_ceiling"]["projected_price"]),
            "side": "right",
            "color": "#00e676",
            "kind": "descending",
        },
        {
            "key": "desc_floor",
            "label": projected_lines["desc_floor"]["label"],
            "value": float(projected_lines["desc_floor"]["projected_price"]),
            "side": "right",
            "color": "#66ffa6",
            "kind": "descending",
        },
        {
            "key": "lw",
            "label": projected_lines["lw"]["label"],
            "value": float(projected_lines["lw"]["projected_price"]),
            "side": "right",
            "color": "#ffd740",
            "kind": "extreme",
        },
    ]

    if current_price is not None:
        items.append(
            {
                "key": "current_price",
                "label": "Current Price",
                "value": float(current_price),
                "side": "center",
                "color": "#00d4ff",
                "kind": "current",
            }
        )

    return items


def compute_ladder_layout(
    projected_lines: dict[str, dict[str, Any]],
    current_price: float | None,
) -> dict[str, Any]:
    """Compute proportional and anti-collision positions for the ladder."""

    items = build_ladder_items(projected_lines, current_price)
    values = [item["value"] for item in items]
    maximum = max(values)
    minimum = min(values)
    value_range = maximum - minimum
    padding = max(value_range * 0.08, 2.0)
    upper_bound = maximum + padding
    lower_bound = minimum - padding
    effective_range = max(upper_bound - lower_bound, 1.0)
    min_gap = 9.0

    sorted_items = sorted(items, key=lambda item: item["value"], reverse=True)
    previous_position: float | None = None

    for item in sorted_items:
        raw_top = ((upper_bound - item["value"]) / effective_range) * 100.0
        adjusted_top = raw_top if previous_position is None else max(raw_top, previous_position + min_gap)
        item["raw_top"] = raw_top
        item["top"] = min(adjusted_top, 95.0)
        previous_position = item["top"]

    overflow = sorted_items[-1]["top"] - 95.0 if sorted_items else 0.0
    if overflow > 0:
        for item in sorted_items:
            item["top"] = max(item["top"] - overflow, 5.0)

    return {
        "items": sorted_items,
        "upper_bound": upper_bound,
        "lower_bound": lower_bound,
        "has_current_price": current_price is not None,
    }


def render_spatial_ladder(
    projected_lines: dict[str, dict[str, Any]],
    current_price: float | None,
    price_space_label: str = "SPX",
) -> None:
    """Render the spatial ladder visualization with custom HTML/CSS."""

    st.markdown(
        f"""
        <div class="spx-shell">
            <div class="spx-section-title">Spatial Ladder</div>
            <div class="spx-section-subtitle">
                Live structure map shown in {price_space_label} terms. Ladder and visible line table use the same unit.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    layout = compute_ladder_layout(projected_lines, current_price)
    items = layout["items"]
    upper_bound = layout["upper_bound"]
    lower_bound = layout["lower_bound"]
    has_current_price = layout["has_current_price"]

    marker_html: list[str] = []
    guide_html: list[str] = []

    for item in items:
        top = item["top"]
        raw_top = item["raw_top"]
        value_label = f"{format_price(item['value'])} ({price_space_label})"
        color = item["color"]
        marker_class = f"ladder-marker {item['side']} {item['kind']}"
        label_class = f"ladder-label {item['side']} {item['kind']}"

        if item["kind"] == "current":
            marker_html.append(
                f"""
                <div class="current-band" style="top:{top:.2f}%;">
                    <div class="current-band-line"></div>
                    <div class="current-band-pill">Current Price | {value_label}</div>
                </div>
                """
            )
            continue

        guide_html.append(
            f"""
            <div class="ladder-guide" style="top:{raw_top:.2f}%;">
                <div class="ladder-guide-line" style="border-color:{color}33;"></div>
            </div>
            """
        )
        marker_html.append(
            f"""
            <div class="{marker_class}" style="top:{top:.2f}%;">
                <div class="ladder-dot" style="background:{color}; box-shadow:0 0 0 3px {color}22, 0 0 18px {color}55;"></div>
            </div>
            <div class="{label_class}" style="top:{top:.2f}%;">
                <div class="ladder-pill" style="border-color:{color}55;">
                    <span class="ladder-pill-label">{item['label']}</span>
                    <span class="ladder-pill-value">{value_label}</span>
                </div>
            </div>
            """
        )

    empty_state_html = ""
    if not has_current_price:
        empty_state_html = """
        <div class="ladder-empty-state">
            Current price not entered. Showing projected structure only.
        </div>
        """

    ladder_html = f"""
    <html>
    <head>
        <style>
            body {{
                margin: 0;
                font-family: Inter, "Segoe UI", sans-serif;
                background: transparent;
                color: #e8eef8;
            }}
            .ladder-shell {{
                position: relative;
                height: 560px;
                border-radius: 22px;
                border: 1px solid rgba(255, 255, 255, 0.08);
                background:
                    radial-gradient(circle at 50% 50%, rgba(0, 212, 255, 0.06), transparent 28%),
                    linear-gradient(180deg, rgba(12, 18, 30, 0.96), rgba(8, 12, 22, 0.96));
                overflow: hidden;
            }}
            .ladder-frame {{
                position: absolute;
                inset: 0;
            }}
            .ladder-rail {{
                position: absolute;
                top: 6%;
                bottom: 6%;
                width: 2px;
                left: 50%;
                transform: translateX(-50%);
                background: linear-gradient(180deg, rgba(255, 215, 64, 0.16), rgba(0, 212, 255, 0.5), rgba(255, 215, 64, 0.16));
                box-shadow: 0 0 24px rgba(0, 212, 255, 0.12);
            }}
            .ladder-boundary {{
                position: absolute;
                left: 50%;
                transform: translateX(-50%);
                font-size: 12px;
                color: #7f93b2;
                background: rgba(5, 9, 18, 0.85);
                padding: 4px 8px;
                border-radius: 999px;
                border: 1px solid rgba(255,255,255,0.05);
            }}
            .ladder-boundary.top {{
                top: 2%;
            }}
            .ladder-boundary.bottom {{
                bottom: 2%;
            }}
            .ladder-guide {{
                position: absolute;
                left: 0;
                right: 0;
                height: 0;
            }}
            .ladder-guide-line {{
                position: absolute;
                top: 0;
                left: 16%;
                right: 16%;
                border-top: 1px dashed rgba(255,255,255,0.08);
            }}
            .ladder-marker {{
                position: absolute;
                width: 22px;
                height: 22px;
                transform: translateY(-50%);
                z-index: 3;
            }}
            .ladder-marker.left {{
                left: calc(50% - 14px);
                transform: translate(-100%, -50%);
            }}
            .ladder-marker.right {{
                left: calc(50% + 14px);
                transform: translate(0, -50%);
            }}
            .ladder-dot {{
                width: 12px;
                height: 12px;
                border-radius: 50%;
                margin: 5px;
            }}
            .ladder-label {{
                position: absolute;
                transform: translateY(-50%);
                z-index: 4;
            }}
            .ladder-label.left {{
                right: calc(50% + 26px);
                text-align: right;
                width: 38%;
            }}
            .ladder-label.right {{
                left: calc(50% + 26px);
                width: 38%;
            }}
            .ladder-pill {{
                display: inline-flex;
                align-items: center;
                gap: 10px;
                max-width: 100%;
                background: rgba(9, 13, 24, 0.95);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 999px;
                padding: 8px 12px;
                box-shadow: 0 10px 22px rgba(0,0,0,0.18);
            }}
            .ladder-pill-label {{
                font-size: 12px;
                font-weight: 700;
                color: #f1f5fb;
                white-space: nowrap;
            }}
            .ladder-pill-value {{
                font-size: 12px;
                color: #8ea2c2;
                white-space: nowrap;
            }}
            .current-band {{
                position: absolute;
                left: 15%;
                right: 15%;
                height: 0;
                transform: translateY(-50%);
                z-index: 5;
            }}
            .current-band-line {{
                height: 8px;
                border-radius: 999px;
                background: linear-gradient(90deg, rgba(0, 212, 255, 0.12), rgba(0, 212, 255, 0.82), rgba(0, 212, 255, 0.12));
                box-shadow: 0 0 30px rgba(0, 212, 255, 0.45);
            }}
            .current-band-pill {{
                position: absolute;
                left: 50%;
                top: -18px;
                transform: translateX(-50%);
                background: rgba(2, 18, 26, 0.96);
                color: #e9fbff;
                border: 1px solid rgba(0, 212, 255, 0.4);
                border-radius: 999px;
                padding: 8px 14px;
                font-size: 12px;
                font-weight: 800;
                white-space: nowrap;
                box-shadow: 0 0 28px rgba(0, 212, 255, 0.24);
            }}
            .ladder-empty-state {{
                position: absolute;
                left: 50%;
                bottom: 4%;
                transform: translateX(-50%);
                padding: 8px 14px;
                background: rgba(255, 215, 64, 0.1);
                border: 1px solid rgba(255, 215, 64, 0.22);
                border-radius: 999px;
                color: #ffe695;
                font-size: 12px;
                font-weight: 700;
                z-index: 6;
            }}
        </style>
    </head>
    <body>
        <div class="ladder-shell">
            <div class="ladder-frame">
                <div class="ladder-boundary top">Top {format_price(upper_bound)}</div>
                <div class="ladder-boundary bottom">Bottom {format_price(lower_bound)}</div>
                <div class="ladder-rail"></div>
                {''.join(guide_html)}
                {''.join(marker_html)}
                {empty_state_html}
            </div>
        </div>
    </body>
    </html>
    """

    components.html(ladder_html, height=585, scrolling=False)


def previous_business_day(today: date) -> date:
    """Return the previous business day."""

    candidate = today - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def default_next_trading_day(today: date) -> date:
    """Return the next trading day candidate."""

    candidate = today
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def format_price(value: float | None) -> str:
    """Format a market price."""

    if value is None:
        return "-"
    return f"{round_price(value):,.2f}"


def format_timestamp(value: Any) -> str:
    """Format a timestamp in Central Time for display."""

    if value is None:
        return "-"
    return value.strftime("%Y-%m-%d %I:%M %p CT")


def to_internal_es_price(value: float, price_space: str, offset: float) -> float:
    """Convert a manual input price into internal ES terms."""

    if price_space == "SPX":
        return round_price(float(value) + float(offset))
    return round_price(float(value))


def resolve_effective_offset(inputs: dict[str, Any]) -> tuple[float, str]:
    """Resolve the offset used for ES/SPX conversion in the app layer."""

    configured_offset = float(inputs["es_spx_offset"])
    current_es = inputs.get("current_es_price")
    current_spx = inputs.get("current_spx_price")

    if is_valid_price_input(current_es) and is_valid_price_input(current_spx):
        derived_offset = round_price(float(current_es) - float(current_spx))
        if derived_offset >= 0:
            return derived_offset, "derived_from_current_prices"

    return configured_offset, "configured_setting"


def build_manual_anchor_bundle(
    prior_session_date: date,
    pivot_high_time,
    pivot_green_high: float,
    pivot_red_high: float,
    pivot_low_time,
    pivot_red_low: float,
    pivot_green_low: float,
    hw_time,
    hw_price: float,
    lw_time,
    lw_price: float,
    price_space: str,
    es_spx_offset: float,
) -> dict[str, Any]:
    """Build a manual six-line anchor bundle for the UI."""

    pivot_green_high_es = to_internal_es_price(pivot_green_high, price_space, es_spx_offset)
    pivot_red_high_es = to_internal_es_price(pivot_red_high, price_space, es_spx_offset)
    pivot_red_low_es = to_internal_es_price(pivot_red_low, price_space, es_spx_offset)
    pivot_green_low_es = to_internal_es_price(pivot_green_low, price_space, es_spx_offset)
    hw_price_es = to_internal_es_price(hw_price, price_space, es_spx_offset)
    lw_price_es = to_internal_es_price(lw_price, price_space, es_spx_offset)

    return {
        "pivot_high": {
            "pivot_time": pivot_high_time,
            "green_candle": {
                "timestamp": pivot_high_time,
                "high": pivot_green_high_es,
                "open": pivot_green_high_es,
                "close": pivot_green_high_es,
                "low": pivot_green_high_es,
                "color": "green",
            },
            "red_candle": {
                "timestamp": pivot_high_time,
                "high": pivot_red_high_es,
                "open": pivot_red_high_es,
                "close": pivot_red_high_es,
                "low": pivot_red_high_es,
                "color": "red",
            },
        },
        "pivot_low": {
            "pivot_time": pivot_low_time,
            "red_candle": {
                "timestamp": pivot_low_time,
                "low": pivot_red_low_es,
                "open": pivot_red_low_es,
                "close": pivot_red_low_es,
                "high": pivot_red_low_es,
                "color": "red",
            },
            "green_candle": {
                "timestamp": pivot_low_time,
                "low": pivot_green_low_es,
                "open": pivot_green_low_es,
                "close": pivot_green_low_es,
                "high": pivot_green_low_es,
                "color": "green",
            },
        },
        "anchors": {
            "hw": {
                "price": hw_price_es,
                "timestamp": hw_time,
                "source": {
                    "timestamp": hw_time,
                    "high": hw_price_es,
                    "low": hw_price_es,
                    "open": hw_price_es,
                    "close": hw_price_es,
                    "color": "red",
                },
                "direction": "ascending",
                "label": "HW",
                "line_type": "session_extreme",
            },
            "asc_ceiling": {
                "price": pivot_red_high_es,
                "timestamp": pivot_high_time,
                "projection_start_time": pivot_high_time,
                "source": {
                    "timestamp": pivot_high_time,
                    "high": pivot_red_high_es,
                    "low": pivot_red_high_es,
                    "open": pivot_red_high_es,
                    "close": pivot_red_high_es,
                    "color": "red",
                },
                "direction": "ascending",
                "label": "ASC Ceiling",
                "line_type": "channel",
            },
            "asc_floor": {
                "price": pivot_red_low_es,
                "timestamp": pivot_low_time,
                "projection_start_time": pivot_low_time,
                "source": {
                    "timestamp": pivot_low_time,
                    "high": pivot_red_low_es,
                    "low": pivot_red_low_es,
                    "open": pivot_red_low_es,
                    "close": pivot_red_low_es,
                    "color": "red",
                },
                "direction": "ascending",
                "label": "ASC Floor",
                "line_type": "channel",
            },
            "desc_ceiling": {
                "price": pivot_green_high_es,
                "timestamp": pivot_high_time,
                "projection_start_time": pivot_high_time,
                "source": {
                    "timestamp": pivot_high_time,
                    "high": pivot_green_high_es,
                    "low": pivot_green_high_es,
                    "open": pivot_green_high_es,
                    "close": pivot_green_high_es,
                    "color": "green",
                },
                "direction": "descending",
                "label": "DESC Ceiling",
                "line_type": "channel",
            },
            "desc_floor": {
                "price": pivot_green_low_es,
                "timestamp": pivot_low_time,
                "projection_start_time": pivot_low_time,
                "source": {
                    "timestamp": pivot_low_time,
                    "high": pivot_green_low_es,
                    "low": pivot_green_low_es,
                    "open": pivot_green_low_es,
                    "close": pivot_green_low_es,
                    "color": "green",
                },
                "direction": "descending",
                "label": "DESC Floor",
                "line_type": "channel",
            },
            "lw": {
                "price": lw_price_es,
                "timestamp": lw_time,
                "source": {
                    "timestamp": lw_time,
                    "high": lw_price_es,
                    "low": lw_price_es,
                    "open": lw_price_es,
                    "close": lw_price_es,
                    "color": "green",
                },
                "direction": "descending",
                "label": "LW",
                "line_type": "session_extreme",
            },
        },
        "afternoon_candles": [],
        "manual_price_space": price_space,
    }


def load_trades() -> tuple[list[dict[str, Any]], str | None]:
    """Load saved trades from local JSON storage."""

    return load_json_list_store(TRADE_LOG_PATH, "trade")


def load_snapshots() -> tuple[list[dict[str, Any]], str | None]:
    """Load saved daily snapshots from local JSON storage."""

    return load_json_list_store(SNAPSHOT_LOG_PATH, "snapshot")


def save_trades(trades: list[dict[str, Any]]) -> tuple[bool, str | None]:
    """Persist the full trade list to local JSON storage."""

    return save_json_list_store(TRADE_LOG_PATH, trades, "trades")


def save_snapshots(snapshots: list[dict[str, Any]]) -> tuple[bool, str | None]:
    """Persist the full snapshot list to local JSON storage."""

    return save_json_list_store(SNAPSHOT_LOG_PATH, snapshots, "snapshots")


def append_trade(trade: dict[str, Any]) -> tuple[bool, str | None]:
    """Append a trade record safely to local storage."""

    trades, load_error = load_trades()
    normalized_existing = [normalize_trade_record(existing_trade) for existing_trade in trades]
    candidate_trade = normalize_trade_record(trade)
    candidate_signature = candidate_trade["record_signature"]
    existing_signatures = {existing_trade["record_signature"] for existing_trade in normalized_existing}
    if candidate_signature in existing_signatures:
        return False, "Duplicate trade detected. Matching trade record was not saved."
    trades.append(candidate_trade)
    saved, save_error = save_trades(trades)
    if not saved:
        return False, save_error
    return True, load_error


def append_snapshot(snapshot: dict[str, Any]) -> tuple[bool, str | None]:
    """Append a daily snapshot safely to local storage."""

    snapshots, load_error = load_snapshots()
    snapshots.append(snapshot)
    saved, save_error = save_snapshots(snapshots)
    if not saved:
        return False, save_error
    return True, load_error


def delete_trade_by_id(trade_id: str) -> tuple[bool, str | None]:
    """Delete a saved trade by id."""

    trades, load_error = load_trades()
    filtered = [trade for trade in trades if str(trade.get("id")) != str(trade_id)]
    saved, save_error = save_trades(filtered)
    if not saved:
        return False, save_error
    if len(filtered) == len(trades):
        return True, load_error or "Selected trade was not found. No deletion was needed."
    return True, load_error


def compute_preview_pnl(direction: str, entry_value: float, exit_value: float, contracts: int) -> float:
    """Compute a practical preview P&L for the journal form."""

    normalized_direction = direction.upper()
    if normalized_direction == "SHORT":
        pnl = (float(entry_value) - float(exit_value)) * int(contracts)
    else:
        pnl = (float(exit_value) - float(entry_value)) * int(contracts)
    return round_price(pnl)


def normalize_trade_record(raw_trade: dict[str, Any]) -> dict[str, Any]:
    """Normalize a trade record for storage and display."""

    tags = normalize_tags(raw_trade.get("tags"))
    pnl_components = calculate_trade_pnl_components(raw_trade)
    normalized_trade = {
        "id": str(raw_trade.get("id") or uuid4()),
        "trade_date": str(raw_trade.get("trade_date", "")),
        "session": str(raw_trade.get("session", "")),
        "scenario_name": str(raw_trade.get("scenario_name", "")),
        "direction": normalize_trade_direction(raw_trade.get("direction", "")),
        "strike_or_contract_label": str(raw_trade.get("strike_or_contract_label", "")),
        "entry_line_label": str(raw_trade.get("entry_line_label", "")),
        "entry_line_value": round_price(float(raw_trade.get("entry_line_value", 0.0))),
        "entry_value": round_price(float(raw_trade.get("entry_value", 0.0))),
        "exit_value": round_price(float(raw_trade.get("exit_value", 0.0))),
        "contracts": int(raw_trade.get("contracts", 1)),
        "confluence_score": int(raw_trade.get("confluence_score", 0)),
        "result": normalize_result_value(raw_trade.get("result", "")),
        "confirmation_status": normalize_confirmation_status(raw_trade.get("confirmation_status", "Not Recorded")),
        "linked_snapshot_id": str(raw_trade.get("linked_snapshot_id", "")),
        "linked_snapshot_date": str(raw_trade.get("linked_snapshot_date", "")),
        "notes": str(raw_trade.get("notes", "")),
        "tags": tags,
        "pnl_preview": round_price(float(raw_trade.get("pnl_preview", 0.0))),
        "effective_pnl": pnl_components["pnl_value"],
        "pnl_source": pnl_components["pnl_source"],
        "record_status": "complete",
        "integrity_flags": [],
        "record_signature": "",
    }
    normalized_trade["integrity_flags"] = build_trade_integrity_flags(normalized_trade)
    normalized_trade["record_status"] = "incomplete" if normalized_trade["integrity_flags"] else "complete"
    normalized_trade["record_signature"] = compute_trade_signature(normalized_trade)
    return normalized_trade


def normalize_snapshot_record(raw_snapshot: dict[str, Any]) -> dict[str, Any]:
    """Normalize a snapshot record for storage and display."""

    review = raw_snapshot.get("review") or {}
    normalized_snapshot = {
        "id": str(raw_snapshot.get("id") or uuid4()),
        "snapshot_date": str(raw_snapshot.get("snapshot_date", "")),
        "captured_at": str(raw_snapshot.get("captured_at", "")),
        "projected_lines": raw_snapshot.get("projected_lines", {}) or {},
        "scenario": raw_snapshot.get("scenario", {}) or {},
        "sit_out": raw_snapshot.get("sit_out", {}) or {},
        "confirmation": raw_snapshot.get("confirmation", {}) or {},
        "review": {
            "traded": bool(review.get("traded", False)),
            "primary_setup_worked": bool(review.get("primary_setup_worked", False)),
            "alternate_setup_worked": bool(review.get("alternate_setup_worked", False)),
            "sit_out_would_have_helped": bool(review.get("sit_out_would_have_helped", False)),
            "best_move_of_day": str(review.get("best_move_of_day", "")),
            "notes": str(review.get("notes", "")),
        },
        "record_status": "complete",
        "integrity_flags": [],
    }
    if not normalized_snapshot["snapshot_date"]:
        normalized_snapshot["integrity_flags"].append("missing_snapshot_date")
    if not normalized_snapshot["scenario"]:
        normalized_snapshot["integrity_flags"].append("missing_scenario")
    normalized_snapshot["record_status"] = "incomplete" if normalized_snapshot["integrity_flags"] else "complete"
    return normalized_snapshot


def build_trade_history_dataframe(trades: list[dict[str, Any]]) -> pd.DataFrame:
    """Build the display dataframe for saved trades."""

    if not trades:
        return pd.DataFrame(
            columns=[
                "date",
                "session",
                "scenario",
                "direction",
                "entry",
                "exit",
                "contracts",
                "confluence",
                "confirmation_status",
                "result",
                "tags",
                "snapshot_date",
                "pnl",
                "pnl_source",
                "record_status",
            ]
        )

    return pd.DataFrame(
        [
            {
                "id": trade["id"],
                "date": trade["trade_date"],
                "session": trade["session"],
                "scenario": trade["scenario_name"],
                "direction": trade["direction"],
                "entry": trade["entry_value"],
                "exit": trade["exit_value"],
                "contracts": trade["contracts"],
                "confluence": trade["confluence_score"],
                "confirmation_status": trade.get("confirmation_status", "Not Recorded"),
                "result": trade["result"],
                "tags": ", ".join(trade["tags"]),
                "snapshot_date": trade.get("linked_snapshot_date", ""),
                "pnl": trade.get("effective_pnl", trade["pnl_preview"]),
                "pnl_source": trade.get("pnl_source", "preview-only"),
                "record_status": trade.get("record_status", "complete"),
                "pnl_preview": trade["pnl_preview"],
            }
            for trade in trades
        ]
    )


def compute_trade_statistics(trades: list[dict[str, Any]]) -> dict[str, float]:
    """Compute basic performance metrics from saved trades."""

    total_trades = len(trades)
    total_wins = sum(1 for trade in trades if trade["result"] == "Win")
    total_losses = sum(1 for trade in trades if trade["result"] == "Loss")
    total_pnl = round_price(sum(float(trade.get("effective_pnl", trade.get("pnl_preview", 0.0))) for trade in trades))
    win_rate = round_price((total_wins / total_trades) * 100.0) if total_trades else 0.0
    average_pnl = round_price(total_pnl / total_trades) if total_trades else 0.0

    return {
        "total_trades": total_trades,
        "total_wins": total_wins,
        "total_losses": total_losses,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "average_pnl": average_pnl,
    }


def export_trades_csv(trades: list[dict[str, Any]]) -> bytes:
    """Export trades to CSV bytes."""

    dataframe = build_trade_history_dataframe(trades)
    return dataframe.drop(columns=["id"], errors="ignore").to_csv(index=False).encode("utf-8")


def export_trades_json(trades: list[dict[str, Any]]) -> bytes:
    """Export trades to JSON bytes."""

    return json.dumps(trades, indent=2).encode("utf-8")


def export_snapshots_json(snapshots: list[dict[str, Any]]) -> bytes:
    """Export snapshots to JSON bytes."""

    return json.dumps(snapshots, indent=2).encode("utf-8")


def export_settings_json(settings: dict[str, Any]) -> bytes:
    """Export settings to JSON bytes."""

    return json.dumps(settings, indent=2).encode("utf-8")


def set_trade_form_prefill(prefill: dict[str, Any]) -> None:
    """Store a trade-log prefill payload in session state."""

    st.session_state["trade_form_prefill"] = prefill
    st.session_state["trade_form_notice"] = f"Trade Log prefilled from {prefill.get('source', 'current context')}."


def get_trade_form_prefill(signal_package: dict[str, Any] | None) -> dict[str, Any]:
    """Return the active trade form prefill with sensible defaults."""

    primary_play = signal_package["scenario"].get("primary_play") if signal_package else None
    default_prefill = {
        "source": "current Tab 1 primary play",
        "trade_date": current_central_time().date().isoformat(),
        "session": "NY Options",
        "scenario_name": signal_package["scenario"]["scenario_name"] if signal_package else "",
        "direction": signal_package["scenario"]["primary_trade_direction"] if signal_package and signal_package["scenario"]["primary_trade_direction"] else "CALL",
        "strike_or_contract_label": str(primary_play["strike"]) if primary_play else "",
        "entry_line_label": primary_play["entry"]["label"] if primary_play else "",
        "entry_line_value": float(primary_play["entry"]["price"]) if primary_play else 0.0,
        "contracts": int(primary_play["contracts"]) if primary_play else 1,
        "confidence_note": signal_package["scenario"]["confidence_level"] if signal_package else "",
        "confirmation_status": "Not Recorded",
        "linked_snapshot_id": "",
        "linked_snapshot_date": "",
        "notes": f"Confidence: {signal_package['scenario']['confidence_level']}" if signal_package else "",
    }
    merged = {**default_prefill, **st.session_state.get("trade_form_prefill", {})}
    try:
        date.fromisoformat(str(merged["trade_date"]))
    except (TypeError, ValueError):
        merged["trade_date"] = current_central_time().date().isoformat()
    return merged


def build_tab1_trade_prefill(signal_package: dict[str, Any]) -> dict[str, Any]:
    """Build a trade-log prefill from the current Tab 1 primary play."""

    primary_play = signal_package["scenario"].get("primary_play")
    if primary_play is None:
        raise ValueError("No primary play is available to prefill the trade log.")

    return {
        "source": "Tab 1 primary play",
        "trade_date": current_central_time().date().isoformat(),
        "session": "NY Options",
        "scenario_name": signal_package["scenario"]["scenario_name"],
        "direction": primary_play["direction"],
        "strike_or_contract_label": str(primary_play["strike"]),
        "entry_line_label": primary_play["entry"]["label"],
        "entry_line_value": float(primary_play["entry"]["price"]),
        "contracts": int(primary_play["contracts"]),
        "confidence_note": signal_package["scenario"]["confidence_level"],
        "confirmation_status": "Not Recorded",
        "linked_snapshot_id": "",
        "linked_snapshot_date": "",
        "notes": f"Confidence: {signal_package['scenario']['confidence_level']}",
    }


def build_tab2_trade_prefill(selected_checkpoint: dict[str, Any], current_es_price: float) -> dict[str, Any]:
    """Build a trade-log prefill from the current Tab 2 reference framework."""

    es_line_values = {name: details["projected_price"] for name, details in selected_checkpoint["es_lines"].items()}
    reference_scenario = evaluate_trading_scenario(
        current_price=current_es_price,
        line_values=es_line_values,
        open_price=current_es_price,
        confirmation_confirmed=False,
    )
    primary_play = reference_scenario.get("primary_play")
    if primary_play is None:
        raise ValueError("No reference play is available to prefill the trade log.")

    direction = "LONG" if primary_play["direction"] == "CALL" else "SHORT"
    return {
        "source": f"Tab 2 {selected_checkpoint['label']} reference framework",
        "trade_date": current_central_time().date().isoformat(),
        "session": "Asian Futures",
        "scenario_name": f"{reference_scenario['scenario_name']} (Reference)",
        "direction": direction,
        "strike_or_contract_label": selected_checkpoint["label"],
        "entry_line_label": primary_play["entry"]["label"],
        "entry_line_value": float(primary_play["entry"]["price"]),
        "contracts": int(primary_play["contracts"]),
        "confidence_note": reference_scenario["confidence_level"],
        "confirmation_status": "Not Applicable",
        "linked_snapshot_id": "",
        "linked_snapshot_date": "",
        "notes": f"Reference framework based on line location | Confidence: {reference_scenario['confidence_level']}",
    }


def build_option_lookup_request(
    *,
    session: str,
    direction: str,
    strike: int,
    trade_date: date,
    scenario_name: str = "",
    option_type: str = "AUTO",
) -> OptionLookupRequest:
    """Build a future-ready option lookup request from app-layer trade context."""

    return OptionLookupRequest(
        trade_date=trade_date.isoformat(),
        session=session,
        direction=direction,
        strike=int(strike),
        scenario_name=scenario_name,
        underlying_symbol="SPX",
        option_type=option_type,
    )


def render_options_provider_preview(
    provider: Any,
    provider_status: dict[str, Any],
    option_request: OptionLookupRequest | None,
) -> None:
    """Render a safe provider integration preview without requiring live connectivity."""

    with st.expander("Options Data", expanded=False):
        st.caption("Provider integration preview. Live options mode is not active unless a provider is configured and implemented.")
        st.write(f"Provider selected: {provider_status['provider_name']}")
        st.write(f"Options mode enabled: {'Yes' if provider_status['options_mode_enabled'] else 'No'}")
        st.write(f"Credentials detected: {'Yes' if provider_status['credentials_detected'] else 'No'}")
        st.write(f"Configured: {'Yes' if provider_status['configured'] else 'No'}")
        st.write(f"Live readiness status: {provider_status['readiness_state']}")
        st.write(f"Live options mode available: {'Yes' if provider_status['live_mode_available'] else 'No'}")
        st.write(f"Provider status: {provider_status['status_label']}")
        for note in provider_status.get("notes", []):
            st.write(f"- {note}")

        if provider_status.get("bridge_only", True):
            st.info("This provider is currently bridge-only. Live chain and quote retrieval are not active yet.")

        if option_request is None:
            st.info("No option lookup request is available yet. A primary SPX options setup with a strike is required.")
            st.markdown("**Candidate Contract Preview**")
            st.info("No candidate-contract preview is available without a prepared lookup request.")
            return

        st.markdown("**Prepared Contract Lookup Request**")
        st.json(option_request.to_dict(), expanded=False)

        preview_candidates = provider.find_candidate_contracts(option_request)
        st.markdown("**Candidate Contract Preview**")
        if preview_candidates:
            st.dataframe(preview_candidates, use_container_width=True, hide_index=True)
        else:
            st.info("No candidate contracts are available because the provider bridge is not live yet.")


def build_daily_snapshot(
    *,
    next_trading_date: date,
    projected_lines: dict[str, dict[str, Any]],
    scenario: dict[str, Any],
    sit_out: dict[str, Any],
    confirmation: dict[str, Any],
) -> dict[str, Any]:
    """Build a daily snapshot payload from the current operator state."""

    return {
        "id": str(uuid4()),
        "snapshot_date": next_trading_date.isoformat(),
        "captured_at": current_central_time().isoformat(),
        "projected_lines": {
            name: {
                "label": details["label"],
                "projected_price": round_price(details["projected_price"]),
                "anchor_price": round_price(details["anchor_price"]),
                "candle_count": int(details["candle_count"]),
                "direction": details["direction"],
            }
            for name, details in projected_lines.items()
        },
        "scenario": {
            "scenario_name": scenario["scenario_name"],
            "confidence_level": scenario["confidence_level"],
            "primary_trade_direction": scenario["primary_trade_direction"],
        },
        "sit_out": sit_out,
        "confirmation": confirmation,
        "review": {
            "traded": False,
            "primary_setup_worked": False,
            "alternate_setup_worked": False,
            "sit_out_would_have_helped": False,
            "best_move_of_day": "",
            "notes": "",
        },
    }


def build_breakdown_dataframe(trades: list[dict[str, Any]], dimension: str) -> pd.DataFrame:
    """Build strategy breakdowns by scenario, confluence, session, or tag."""

    rows: list[dict[str, Any]] = []

    for trade in trades:
        if dimension == "tag":
            tags = trade.get("tags") or ["No Tags"]
            for tag in tags:
                rows.append({"bucket": tag, "result": trade["result"], "pnl_value": float(trade.get("effective_pnl", trade["pnl_preview"]))})
        else:
            if dimension == "scenario":
                bucket = trade.get("scenario_name") or "Unknown"
            elif dimension == "confluence":
                bucket = str(trade.get("confluence_score", "Unknown"))
            elif dimension == "session":
                bucket = trade.get("session") or "Unknown"
            elif dimension == "confirmation":
                bucket = trade.get("confirmation_status") or "Not Recorded"
            else:
                bucket = "Unknown"
            rows.append({"bucket": bucket, "result": trade["result"], "pnl_value": float(trade.get("effective_pnl", trade["pnl_preview"]))})

    if not rows:
        return pd.DataFrame(columns=["bucket", "trades", "wins", "losses", "win_rate", "total_pnl", "avg_pnl"])

    dataframe = pd.DataFrame(rows)
    grouped = dataframe.groupby("bucket", dropna=False)
    summary = grouped.agg(
        trades=("bucket", "size"),
        wins=("result", lambda series: int((series == "Win").sum())),
        losses=("result", lambda series: int((series == "Loss").sum())),
        total_pnl=("pnl_value", "sum"),
        avg_pnl=("pnl_value", "mean"),
    ).reset_index()
    summary["win_rate"] = summary.apply(
        lambda row: round_price((row["wins"] / row["trades"]) * 100.0) if row["trades"] else 0.0,
        axis=1,
    )
    summary["total_pnl"] = summary["total_pnl"].map(round_price)
    summary["avg_pnl"] = summary["avg_pnl"].map(round_price)
    return summary.sort_values(["trades", "total_pnl"], ascending=[False, False]).reset_index(drop=True)


def parse_iso_date(value: Any) -> date | None:
    """Parse an ISO date safely."""

    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def filter_trades(
    trades: list[dict[str, Any]],
    *,
    date_from: date,
    date_to: date,
    scenarios: list[str],
    sessions: list[str],
    results: list[str],
    confluence_scores: list[int],
    confirmation_statuses: list[str],
    tags: list[str],
) -> list[dict[str, Any]]:
    """Filter trades for history and analytics views."""

    filtered: list[dict[str, Any]] = []

    for trade in trades:
        try:
            trade_day = date.fromisoformat(str(trade.get("trade_date", "")))
        except ValueError:
            continue

        if trade_day < date_from or trade_day > date_to:
            continue
        if scenarios and trade.get("scenario_name") not in scenarios:
            continue
        if sessions and trade.get("session") not in sessions:
            continue
        if results and trade.get("result") not in results:
            continue
        if confluence_scores and int(trade.get("confluence_score", -1)) not in confluence_scores:
            continue
        if confirmation_statuses and trade.get("confirmation_status", "Not Recorded") not in confirmation_statuses:
            continue
        trade_tags = trade.get("tags") or []
        if tags and not any(tag in trade_tags for tag in tags):
            continue

        filtered.append(trade)

    return filtered


def filter_snapshots_by_date(snapshots: list[dict[str, Any]], date_from: date, date_to: date) -> list[dict[str, Any]]:
    """Filter snapshots by snapshot date."""

    filtered: list[dict[str, Any]] = []
    for snapshot in snapshots:
        snapshot_day = parse_iso_date(snapshot.get("snapshot_date"))
        if snapshot_day is None:
            continue
        if date_from <= snapshot_day <= date_to:
            filtered.append(snapshot)
    return filtered


def update_snapshot_review(snapshot_id: str, review_payload: dict[str, Any]) -> tuple[bool, str | None]:
    """Update review fields for a saved snapshot."""

    snapshots, load_error = load_snapshots()
    normalized_snapshots = [normalize_snapshot_record(snapshot) for snapshot in snapshots]
    updated = False

    for snapshot in normalized_snapshots:
        if snapshot["id"] == snapshot_id:
            snapshot["review"] = {
                "traded": bool(review_payload.get("traded", False)),
                "primary_setup_worked": bool(review_payload.get("primary_setup_worked", False)),
                "alternate_setup_worked": bool(review_payload.get("alternate_setup_worked", False)),
                "sit_out_would_have_helped": bool(review_payload.get("sit_out_would_have_helped", False)),
                "best_move_of_day": str(review_payload.get("best_move_of_day", "")),
                "notes": str(review_payload.get("notes", "")),
            }
            updated = True
            break

    if not updated:
        return False, "Selected snapshot was not found."

    saved, save_error = save_snapshots(normalized_snapshots)
    if not saved:
        return False, save_error
    return True, load_error


def build_interaction_dataframe(trades: list[dict[str, Any]], first_dimension: str, second_dimension: str) -> pd.DataFrame:
    """Build a grouped interaction table for two strategy dimensions."""

    rows: list[dict[str, Any]] = []
    for trade in trades:
        rows.append(
            {
                "first": str(trade.get(first_dimension, "Unknown") or "Unknown"),
                "second": str(trade.get(second_dimension, "Unknown") or "Unknown"),
                "result": str(trade.get("result", "")),
                "pnl_value": float(trade.get("effective_pnl", trade.get("pnl_preview", 0.0))),
            }
        )

    if not rows:
        return pd.DataFrame(columns=[first_dimension, second_dimension, "trades", "wins", "losses", "win_rate", "total_pnl", "avg_pnl"])

    dataframe = pd.DataFrame(rows)
    grouped = dataframe.groupby(["first", "second"], dropna=False)
    summary = grouped.agg(
        trades=("result", "size"),
        wins=("result", lambda series: int((series == "Win").sum())),
        losses=("result", lambda series: int((series == "Loss").sum())),
        total_pnl=("pnl_value", "sum"),
        avg_pnl=("pnl_value", "mean"),
    ).reset_index()
    summary["win_rate"] = summary.apply(
        lambda row: round_price((row["wins"] / row["trades"]) * 100.0) if row["trades"] else 0.0,
        axis=1,
    )
    summary["total_pnl"] = summary["total_pnl"].map(round_price)
    summary["avg_pnl"] = summary["avg_pnl"].map(round_price)
    summary = summary.rename(columns={"first": first_dimension, "second": second_dimension})
    return summary.sort_values(["trades", "total_pnl"], ascending=[False, False]).reset_index(drop=True)


def compute_best_worst_summary(trades: list[dict[str, Any]]) -> dict[str, str]:
    """Compute best and worst setup summaries for cards."""

    scenario_breakdown = build_breakdown_dataframe(trades, "scenario")
    confirmation_breakdown = build_breakdown_dataframe(trades, "confirmation")

    def _label_for(dataframe: pd.DataFrame, metric: str, direction: str = "max") -> str:
        if dataframe.empty:
            return "No data"
        ordered = dataframe.sort_values([metric, "trades"], ascending=[direction == "min", False]).reset_index(drop=True)
        row = ordered.iloc[0]
        return f"{row['bucket']} ({metric.replace('_', ' ')}: {row[metric]})"

    return {
        "best_scenario_win_rate": _label_for(scenario_breakdown, "win_rate"),
        "best_scenario_total_pnl": _label_for(scenario_breakdown, "total_pnl"),
        "worst_scenario_total_pnl": _label_for(scenario_breakdown, "total_pnl", direction="min"),
        "best_confirmation_status": _label_for(confirmation_breakdown, "win_rate"),
        "worst_confirmation_status": _label_for(confirmation_breakdown, "win_rate", direction="min"),
    }


def compute_rolling_performance(trades: list[dict[str, Any]], window_sizes: list[int]) -> pd.DataFrame:
    """Compute rolling performance summaries over the most recent N trades."""

    if not trades:
        return pd.DataFrame(columns=["window", "trade_count", "win_rate", "total_pnl", "avg_pnl"])

    sorted_trades = sorted(
        trades,
        key=lambda trade: (parse_iso_date(trade.get("trade_date")) or date.min, str(trade.get("id", ""))),
    )
    rows: list[dict[str, Any]] = []
    for window in window_sizes:
        window_trades = sorted_trades[-window:]
        stats = compute_trade_statistics(window_trades)
        rows.append(
            {
                "window": f"Last {window} trades",
                "trade_count": len(window_trades),
                "win_rate": stats["win_rate"],
                "total_pnl": stats["total_pnl"],
                "avg_pnl": stats["average_pnl"],
            }
        )
    return pd.DataFrame(rows)


def compute_streaks(trades: list[dict[str, Any]]) -> dict[str, int | str]:
    """Compute current and longest win/loss streaks."""

    sorted_trades = sorted(
        trades,
        key=lambda trade: (parse_iso_date(trade.get("trade_date")) or date.min, str(trade.get("id", ""))),
    )
    results = [trade.get("result") for trade in sorted_trades]

    current_type = "None"
    current_count = 0
    longest_win = 0
    longest_loss = 0
    running_type = None
    running_count = 0

    for result in results:
        streak_type = "Win" if result == "Win" else "Loss" if result == "Loss" else None
        if streak_type is None:
            running_type = None
            running_count = 0
            continue
        if streak_type == running_type:
            running_count += 1
        else:
            running_type = streak_type
            running_count = 1
        current_type = running_type
        current_count = running_count
        if streak_type == "Win":
            longest_win = max(longest_win, running_count)
        if streak_type == "Loss":
            longest_loss = max(longest_loss, running_count)

    current_label = f"{current_type} x{current_count}" if current_type != "None" else "No active streak"
    return {
        "current_streak": current_label,
        "longest_win_streak": longest_win,
        "longest_loss_streak": longest_loss,
    }


def compute_sit_out_effectiveness(snapshots: list[dict[str, Any]], trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute sit-out effectiveness using snapshots and linked trades when available."""

    if not snapshots:
        return {
            "metrics": {
                "sit_out_triggered": 0,
                "sit_out_days_traded": 0,
                "sit_out_day_wins": 0,
                "sit_out_day_losses": 0,
                "sit_out_day_total_pnl": 0.0,
                "sit_out_would_have_helped": 0,
                "sit_out_missed_opportunity": 0,
            },
            "table": pd.DataFrame(columns=["snapshot_date", "scenario", "traded", "wins", "losses", "total_pnl", "would_have_helped"]),
        }

    rows: list[dict[str, Any]] = []
    for snapshot in snapshots:
        snapshot_id = snapshot.get("id", "")
        snapshot_date = snapshot.get("snapshot_date", "")
        related_trades = [
            trade
            for trade in trades
            if trade.get("linked_snapshot_id") == snapshot_id
            or (snapshot_date and trade.get("linked_snapshot_date") == snapshot_date)
        ]
        traded_flag = bool(snapshot.get("review", {}).get("traded", False) or related_trades)
        wins = sum(1 for trade in related_trades if trade.get("result") == "Win")
        losses = sum(1 for trade in related_trades if trade.get("result") == "Loss")
        total_pnl = round_price(sum(float(trade.get("effective_pnl", trade.get("pnl_preview", 0.0))) for trade in related_trades))
        rows.append(
            {
                "snapshot_date": snapshot_date,
                "scenario": snapshot.get("scenario", {}).get("scenario_name", ""),
                "sit_out_triggered": bool(snapshot.get("sit_out", {}).get("sit_out", False)),
                "traded": traded_flag,
                "wins": wins,
                "losses": losses,
                "total_pnl": total_pnl,
                "would_have_helped": bool(snapshot.get("review", {}).get("sit_out_would_have_helped", False)),
            }
        )

    dataframe = pd.DataFrame(rows)
    sit_out_days = dataframe[dataframe["sit_out_triggered"] == True]  # noqa: E712
    metrics = {
        "sit_out_triggered": int(len(sit_out_days)),
        "sit_out_days_traded": int((sit_out_days["traded"] == True).sum()) if not sit_out_days.empty else 0,  # noqa: E712
        "sit_out_day_wins": int(sit_out_days["wins"].sum()) if not sit_out_days.empty else 0,
        "sit_out_day_losses": int(sit_out_days["losses"].sum()) if not sit_out_days.empty else 0,
        "sit_out_day_total_pnl": round_price(sit_out_days["total_pnl"].sum()) if not sit_out_days.empty else 0.0,
        "sit_out_would_have_helped": int((sit_out_days["would_have_helped"] == True).sum()) if not sit_out_days.empty else 0,  # noqa: E712
        "sit_out_missed_opportunity": int((sit_out_days["would_have_helped"] == False).sum()) if not sit_out_days.empty else 0,  # noqa: E712
    }
    return {"metrics": metrics, "table": sit_out_days.reset_index(drop=True)}


def build_expectancy_dataframe(trades: list[dict[str, Any]], dimension: str, minimum_sample: int = 3) -> pd.DataFrame:
    """Build expectancy analytics by a strategy dimension."""

    rows: list[dict[str, Any]] = []
    for trade in trades:
        if dimension == "tag":
            buckets = trade.get("tags") or ["No Tags"]
        elif dimension == "scenario":
            buckets = [trade.get("scenario_name") or "Unknown"]
        elif dimension == "confirmation":
            buckets = [trade.get("confirmation_status") or "Not Recorded"]
        elif dimension == "session":
            buckets = [trade.get("session") or "Unknown"]
        else:
            buckets = ["Unknown"]

        pnl_value = float(trade.get("effective_pnl", trade.get("pnl_preview", 0.0)))
        for bucket in buckets:
            rows.append({"bucket": bucket, "result": trade.get("result"), "pnl_value": pnl_value})

    if not rows:
        return pd.DataFrame(
            columns=[
                "bucket",
                "trades",
                "wins",
                "losses",
                "win_rate",
                "loss_rate",
                "average_win",
                "average_loss",
                "expectancy",
                "sample_note",
            ]
        )

    dataframe = pd.DataFrame(rows)
    grouped_rows: list[dict[str, Any]] = []
    for bucket, group in dataframe.groupby("bucket", dropna=False):
        wins = group[group["result"] == "Win"]
        losses = group[group["result"] == "Loss"]
        trade_count = len(group)
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = win_count / trade_count if trade_count else 0.0
        loss_rate = loss_count / trade_count if trade_count else 0.0
        average_win = float(wins["pnl_value"].mean()) if not wins.empty else 0.0
        average_loss = abs(float(losses["pnl_value"].mean())) if not losses.empty else 0.0
        expectancy = (win_rate * average_win) - (loss_rate * average_loss)
        sample_note = "Sample too small" if trade_count < minimum_sample else "Sufficient sample"
        grouped_rows.append(
            {
                "bucket": bucket,
                "trades": trade_count,
                "wins": win_count,
                "losses": loss_count,
                "win_rate": round_price(win_rate * 100.0),
                "loss_rate": round_price(loss_rate * 100.0),
                "average_win": round_price(average_win),
                "average_loss": round_price(average_loss),
                "expectancy": round_price(expectancy),
                "sample_note": sample_note,
            }
        )

    return pd.DataFrame(grouped_rows).sort_values(["expectancy", "trades"], ascending=[False, False]).reset_index(drop=True)


def build_period_performance_dataframe(trades: list[dict[str, Any]], period: str) -> pd.DataFrame:
    """Build weekly or monthly performance summaries."""

    rows: list[dict[str, Any]] = []
    for trade in trades:
        trade_day = parse_iso_date(trade.get("trade_date"))
        if trade_day is None:
            continue
        if period == "weekly":
            iso_year, iso_week, _ = trade_day.isocalendar()
            bucket = f"{iso_year}-W{iso_week:02d}"
        else:
            bucket = trade_day.strftime("%Y-%m")
        rows.append({"bucket": bucket, "result": trade.get("result"), "pnl_value": float(trade.get("effective_pnl", trade.get("pnl_preview", 0.0)))})

    if not rows:
        return pd.DataFrame(columns=["period", "trades", "win_rate", "total_pnl", "avg_pnl"])

    dataframe = pd.DataFrame(rows)
    grouped = dataframe.groupby("bucket", dropna=False)
    summary = grouped.agg(
        trades=("result", "size"),
        wins=("result", lambda series: int((series == "Win").sum())),
        total_pnl=("pnl_value", "sum"),
        avg_pnl=("pnl_value", "mean"),
    ).reset_index()
    summary["win_rate"] = summary.apply(
        lambda row: round_price((row["wins"] / row["trades"]) * 100.0) if row["trades"] else 0.0,
        axis=1,
    )
    summary["total_pnl"] = summary["total_pnl"].map(round_price)
    summary["avg_pnl"] = summary["avg_pnl"].map(round_price)
    summary = summary.rename(columns={"bucket": "period"}).drop(columns=["wins"])
    return summary.sort_values("period", ascending=False).reset_index(drop=True)


def build_setup_quality_summary(trades: list[dict[str, Any]]) -> dict[str, str]:
    """Build setup quality cards from expectancy analytics."""

    scenario_expectancy = build_expectancy_dataframe(trades, "scenario")
    confirmation_expectancy = build_expectancy_dataframe(trades, "confirmation")
    session_expectancy = build_expectancy_dataframe(trades, "session")

    def _pick_label(dataframe: pd.DataFrame, direction: str = "max") -> str:
        if dataframe.empty:
            return "No data"
        ordered = dataframe.sort_values(["expectancy", "trades"], ascending=[direction == "min", False]).reset_index(drop=True)
        row = ordered.iloc[0]
        return f"{row['bucket']} ({row['expectancy']})"

    return {
        "highest_expectancy_scenario": _pick_label(scenario_expectancy, "max"),
        "lowest_expectancy_scenario": _pick_label(scenario_expectancy, "min"),
        "highest_expectancy_confirmation": _pick_label(confirmation_expectancy, "max"),
        "strongest_session": _pick_label(session_expectancy, "max"),
        "weakest_session": _pick_label(session_expectancy, "min"),
    }


def build_scenario_frequency_dataframe(trades: list[dict[str, Any]], snapshots: list[dict[str, Any]]) -> pd.DataFrame:
    """Build scenario occurrence frequency across trades and snapshots."""

    recent_trades = sorted(
        [trade for trade in trades if trade.get("scenario_name")],
        key=lambda trade: (parse_iso_date(trade.get("trade_date")) or date.min, str(trade.get("id", ""))),
    )[-30:]
    rows: list[dict[str, Any]] = []
    scenario_names = sorted(
        {
            trade.get("scenario_name")
            for trade in trades
            if trade.get("scenario_name")
        }.union(
            {
                snapshot.get("scenario", {}).get("scenario_name")
                for snapshot in snapshots
                if snapshot.get("scenario", {}).get("scenario_name")
            }
        )
    )

    for scenario_name in scenario_names:
        trade_count = sum(1 for trade in trades if trade.get("scenario_name") == scenario_name)
        snapshot_count = sum(1 for snapshot in snapshots if snapshot.get("scenario", {}).get("scenario_name") == scenario_name)
        recent_trade_count = sum(1 for trade in recent_trades if trade.get("scenario_name") == scenario_name)
        rows.append(
            {
                "scenario": scenario_name,
                "trade_count": trade_count,
                "snapshot_count": snapshot_count,
                "recent_trade_count": recent_trade_count,
            }
        )

    if not rows:
        return pd.DataFrame(columns=["scenario", "trade_count", "snapshot_count", "recent_trade_count"])
    return pd.DataFrame(rows).sort_values(["trade_count", "snapshot_count"], ascending=[False, False]).reset_index(drop=True)


def build_data_health_report(
    trades: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
    settings: dict[str, Any],
    *,
    load_error: str | None,
    snapshot_error: str | None,
    settings_message: str | None,
) -> dict[str, Any]:
    """Build a simple data health report for the operator."""

    trade_signatures = [trade.get("record_signature", "") for trade in trades if trade.get("record_signature")]
    duplicate_trade_count = max(len(trade_signatures) - len(set(trade_signatures)), 0)
    incomplete_trade_count = sum(1 for trade in trades if trade.get("record_status") == "incomplete")
    incomplete_snapshot_count = sum(1 for snapshot in snapshots if snapshot.get("record_status") == "incomplete")
    malformed_recoveries = [
        message
        for message in [load_error, snapshot_error, settings_message]
        if message and ("Backed it up as" in message or "Malformed JSON detected" in message)
    ]

    return {
        "trade_count": len(trades),
        "snapshot_count": len(snapshots),
        "settings_loaded": bool(settings),
        "malformed_recoveries": malformed_recoveries,
        "incomplete_trade_count": incomplete_trade_count,
        "incomplete_snapshot_count": incomplete_snapshot_count,
        "duplicate_trade_count": duplicate_trade_count,
        "preview_only_pnl_count": sum(1 for trade in trades if trade.get("pnl_source") == "preview-only"),
    }


def validate_trade_form_payload(payload: dict[str, Any]) -> list[str]:
    """Validate trade-entry payloads before saving."""

    errors: list[str] = []
    if not str(payload.get("scenario_name", "")).strip():
        errors.append("Scenario name is required.")
    if not str(payload.get("entry_line_label", "")).strip():
        errors.append("Entry line label is required.")
    if float(payload.get("entry_value", 0.0)) < 0:
        errors.append("Entry premium or entry price cannot be negative.")
    if float(payload.get("exit_value", 0.0)) < 0:
        errors.append("Exit premium or exit price cannot be negative.")
    if int(payload.get("contracts", 0)) < 1:
        errors.append("Contracts must be at least 1.")
    return errors


@st.cache_data(ttl=60, show_spinner=False)
def fetch_live_es_price() -> tuple[float | None, str]:
    """Fetch a current ES price for the sidebar input default."""

    import yfinance as yf

    ticker = yf.Ticker("ES=F")
    failures: list[str] = []

    try:
        fast_info = getattr(ticker, "fast_info", {}) or {}
        for key in ("lastPrice", "regularMarketPrice"):
            candidate = fast_info.get(key)
            if candidate:
                return round_price(float(candidate)), f"fast_info.{key}"
    except Exception as exc:
        failures.append(f"fast_info: {exc.__class__.__name__}: {exc}")

    try:
        info = getattr(ticker, "info", {}) or {}
        for key in ("regularMarketPrice", "currentPrice", "postMarketPrice", "preMarketPrice"):
            candidate = info.get(key)
            if candidate:
                return round_price(float(candidate)), f"info.{key}"
    except Exception as exc:
        failures.append(f"info: {exc.__class__.__name__}: {exc}")

    try:
        intraday = ticker.history(period="1d", interval="1m", prepost=True)
        if not intraday.empty:
            if "Close" in intraday.columns:
                return round_price(float(intraday["Close"].dropna().iloc[-1])), "1m_history"
            if "close" in intraday.columns:
                return round_price(float(intraday["close"].dropna().iloc[-1])), "1m_history"
    except Exception as exc:
        failures.append(f"1m_history: {exc.__class__.__name__}: {exc}")

    try:
        hourly = ticker.history(period="5d", interval="60m", prepost=True)
        if not hourly.empty:
            if "Close" in hourly.columns:
                return round_price(float(hourly["Close"].dropna().iloc[-1])), "60m_history"
            if "close" in hourly.columns:
                return round_price(float(hourly["close"].dropna().iloc[-1])), "60m_history"
    except Exception as exc:
        failures.append(f"60m_history: {exc.__class__.__name__}: {exc}")

    failure_suffix = f" | {'; '.join(failures)}" if failures else ""
    return None, f"unavailable: yfinance returned no usable ES quote{failure_suffix}"


@st.cache_data(ttl=60, show_spinner=False)
def fetch_live_spx_price() -> tuple[float | None, str]:
    """Fetch a current SPX price for the sidebar input default."""

    import yfinance as yf

    ticker = yf.Ticker("^GSPC")
    failures: list[str] = []

    try:
        fast_info = getattr(ticker, "fast_info", {}) or {}
        for key in ("regularMarketPrice", "lastPrice", "previousClose"):
            candidate = fast_info.get(key)
            if candidate:
                return round_price(float(candidate)), f"fast_info.{key}"
    except Exception as exc:
        failures.append(f"fast_info: {exc.__class__.__name__}: {exc}")

    try:
        info = getattr(ticker, "info", {}) or {}
        for key in ("regularMarketPrice", "currentPrice", "postMarketPrice", "preMarketPrice"):
            candidate = info.get(key)
            if candidate:
                return round_price(float(candidate)), f"info.{key}"
    except Exception as exc:
        failures.append(f"info: {exc.__class__.__name__}: {exc}")

    try:
        recent = ticker.history(period="5d", interval="1d", auto_adjust=False)
        if not recent.empty:
            if "Close" in recent.columns:
                return round_price(float(recent["Close"].dropna().iloc[-1])), "1d_history"
            if "close" in recent.columns:
                return round_price(float(recent["close"].dropna().iloc[-1])), "1d_history"
    except Exception as exc:
        failures.append(f"1d_history: {exc.__class__.__name__}: {exc}")

    failure_suffix = f" | {'; '.join(failures)}" if failures else ""
    return None, f"unavailable: yfinance returned no usable SPX quote{failure_suffix}"


def resolve_live_input_defaults(
    configured_offset: float,
    live_es_price: float | None,
    live_es_source: str,
    live_spx_price: float | None,
    live_spx_source: str,
) -> dict[str, Any]:
    """Resolve sidebar price defaults without inventing fake market prices."""

    es_available = live_es_price is not None
    spx_available = live_spx_price is not None

    default_es_price = float(live_es_price) if es_available else 0.0
    default_spx_price = float(live_spx_price) if spx_available else 0.0
    open_reference = default_spx_price if spx_available else 0.0
    derived_live_offset = (
        round_price(float(live_es_price) - float(live_spx_price))
        if es_available and spx_available
        else None
    )

    return {
        "default_es_price": default_es_price,
        "default_spx_price": default_spx_price,
        "default_open_reference": open_reference,
        "es_source": live_es_source if es_available else "manual_required_no_live_es_quote",
        "spx_source": live_spx_source if spx_available else "manual_required_no_live_spx_quote",
        "es_fetch_status": live_es_source,
        "spx_fetch_status": live_spx_source,
        "es_available": es_available,
        "spx_available": spx_available,
        "configured_offset": round_price(configured_offset),
        "derived_live_offset": derived_live_offset,
    }


def describe_current_spx_source(
    current_spx_price: float,
    current_es_price: float,
    current_offset: float,
    default_spx_price: float,
    live_spx_available: bool,
) -> str:
    """Describe the active SPX input source for the operator."""

    if not is_valid_price_input(current_spx_price):
        return "unavailable"
    if live_spx_available and abs(float(current_spx_price) - float(default_spx_price)) < 0.005:
        return "live SPX quote"
    if is_valid_price_input(current_es_price):
        derived_spx = round_price(float(current_es_price) - float(current_offset))
        if abs(float(current_spx_price) - derived_spx) < 0.005:
            return "derived from ES minus offset"
    return "manual entry"


def describe_current_es_source(
    current_es_price: float,
    default_es_price: float,
    live_es_available: bool,
) -> str:
    """Describe the active ES input source for the operator."""

    if not is_valid_price_input(current_es_price):
        return "unavailable"
    if live_es_available and abs(float(current_es_price) - float(default_es_price)) < 0.005:
        return "live ES quote"
    return "manual entry"


def classify_quote_failure(es_status: str, spx_status: str) -> str:
    """Classify live quote failure cause at the app layer."""

    statuses = f"{es_status} | {spx_status}".lower()
    if "unavailable" not in statuses:
        return "live quotes available"
    if "yfinance returned no usable" in statuses:
        return "provider failure"
    if any(token in statuses for token in ["timeout", "connection", "429", "forbidden", "unauthorized", "ssl", "proxy"]):
        return "deployment environment issue"
    return "provider failure or deployment environment issue"


def get_inputs(settings: dict[str, Any]) -> dict[str, Any]:
    """Collect sidebar inputs for Tab 1."""

    if st.session_state.pop("refresh_live_quotes", False):
        fetch_live_es_price.clear()
        fetch_live_spx_price.clear()

    now_ct = current_central_time()
    default_prior = previous_business_day(now_ct.date())
    default_next = default_next_trading_day(now_ct.date())
    live_es_price, live_es_source = fetch_live_es_price()
    live_spx_price, live_spx_source = fetch_live_spx_price()
    configured_offset = float(settings.get("es_spx_offset", DEFAULT_SETTINGS["es_spx_offset"]))
    live_defaults = resolve_live_input_defaults(
        configured_offset,
        live_es_price,
        live_es_source,
        live_spx_price,
        live_spx_source,
    )
    default_es_price = float(live_defaults["default_es_price"])
    default_spx_price = float(live_defaults["default_spx_price"])
    default_open_reference = float(live_defaults["default_open_reference"])

    with st.sidebar:
        st.header(APP_TITLE)
        if st.button("Refresh Live Quotes", use_container_width=True):
            st.session_state["refresh_live_quotes"] = True
            st.rerun()
        prior_session_date = st.date_input("Prior NY session date", value=default_prior)
        next_trading_date = st.date_input("Next trading date", value=default_next)
        data_mode_options = ["Auto-fetch", "Manual input"]
        data_mode = st.radio("Data source", data_mode_options, index=safe_option_index(data_mode_options, settings.get("data_mode", DEFAULT_SETTINGS["data_mode"])))

        st.subheader("Session Inputs")
        current_spx_price = st.number_input("9:00 AM SPX price", value=default_spx_price, step=0.25, format="%.2f")
        current_es_price = st.number_input("Current ES price", value=default_es_price, step=0.25, format="%.2f")
        open_reference = st.number_input("9:00 AM open reference", value=default_open_reference, step=0.25, format="%.2f")
        if not live_defaults["es_available"] or not live_defaults["spx_available"]:
            st.warning("Live quote unavailable. Enter current prices manually.")
        news_day = st.checkbox("Fed / CPI / NFP day", value=bool(settings.get("news_day", DEFAULT_SETTINGS["news_day"])))
        es_spx_offset = st.number_input("ES-SPX offset", value=configured_offset, step=0.25, format="%.2f")
        current_spx_source_label = describe_current_spx_source(
            current_spx_price=current_spx_price,
            current_es_price=current_es_price,
            current_offset=es_spx_offset,
            default_spx_price=default_spx_price,
            live_spx_available=live_defaults["spx_available"],
        )
        current_es_source_label = describe_current_es_source(
            current_es_price=current_es_price,
            default_es_price=default_es_price,
            live_es_available=live_defaults["es_available"],
        )
        st.caption(f"Current SPX source: {current_spx_source_label}")
        st.caption(f"Current ES source: {current_es_source_label}")
        st.caption(f"9:00 AM open reference source: {'live SPX quote' if live_defaults['spx_available'] and abs(float(open_reference) - float(default_open_reference)) < 0.005 else 'manual entry'}")
        with st.expander("Live Quote Status", expanded=False):
            st.write("Current SPX fetch")
            st.code(
                "\n".join(
                    [
                        "function: fetch_live_spx_price()",
                        "provider: yfinance",
                        "symbol: ^GSPC",
                        f"status: {'success' if live_defaults['spx_available'] else 'failed'}",
                        f"source: {live_defaults['spx_fetch_status']}",
                    ]
                )
            )
            st.write("Current ES fetch")
            st.code(
                "\n".join(
                    [
                        "function: fetch_live_es_price()",
                        "provider: yfinance",
                        "symbol: ES=F",
                        f"status: {'success' if live_defaults['es_available'] else 'failed'}",
                        f"source: {live_defaults['es_fetch_status']}",
                    ]
                )
            )
            st.write(f"Failure classification: {classify_quote_failure(live_defaults['es_fetch_status'], live_defaults['spx_fetch_status'])}")
        price_space_options = ["SPX", "ES"]
        manual_price_space = st.selectbox("Manual input price space", price_space_options, index=safe_option_index(price_space_options, settings.get("manual_price_space", DEFAULT_SETTINGS["manual_price_space"])))

        st.subheader("Options Provider")
        options_mode_enabled = st.checkbox("Options mode enabled", value=bool(settings.get("options_mode_enabled", DEFAULT_SETTINGS["options_mode_enabled"])))
        options_provider = st.selectbox("Options provider", PROVIDER_NAMES, index=safe_option_index(PROVIDER_NAMES, settings.get("options_provider", DEFAULT_SETTINGS["options_provider"])))

        st.subheader("Manual Anchors")
        pivot_high_hour = st.selectbox("Rejection pivot time", options=[12, 13, 14, 15, 16], index=0)
        pivot_low_hour = st.selectbox("Bounce pivot time", options=[12, 13, 14, 15, 16], index=2)
        pivot_green_high = st.number_input("Rejection green candle high", value=6857.70, step=0.25, format="%.2f")
        pivot_red_high = st.number_input("Rejection red candle high", value=6859.50, step=0.25, format="%.2f")
        pivot_red_low = st.number_input("Bounce red candle low", value=6848.75, step=0.25, format="%.2f")
        pivot_green_low = st.number_input("Bounce green candle low", value=6851.00, step=0.25, format="%.2f")
        hw_hour = st.selectbox("Highest wick time", options=list(range(9, 17)), index=4)
        hw_price = st.number_input("Highest wick price", value=6864.50, step=0.25, format="%.2f")
        lw_hour = st.selectbox("Lowest wick time", options=list(range(9, 17)), index=1)
        lw_price = st.number_input("Lowest wick price", value=6840.25, step=0.25, format="%.2f")

        st.subheader("Overnight Overrides")
        use_asc_ceiling_override = st.checkbox("Override ASC Ceiling")
        asc_ceiling_override = st.number_input("ASC Ceiling override value", value=0.00, step=0.25, format="%.2f")
        use_desc_ceiling_override = st.checkbox("Override DESC Ceiling")
        desc_ceiling_override = st.number_input("DESC Ceiling override value", value=0.00, step=0.25, format="%.2f")
        use_asc_floor_override = st.checkbox("Override ASC Floor")
        asc_floor_override = st.number_input("ASC Floor override value", value=0.00, step=0.25, format="%.2f")
        use_desc_floor_override = st.checkbox("Override DESC Floor")
        desc_floor_override = st.number_input("DESC Floor override value", value=0.00, step=0.25, format="%.2f")

    return {
        "prior_session_date": prior_session_date,
        "next_trading_date": next_trading_date,
        "data_mode": data_mode,
        "current_spx_price": current_spx_price,
        "current_es_price": current_es_price,
        "open_reference": open_reference,
        "current_spx_source": live_defaults["spx_source"],
        "current_es_source": live_defaults["es_source"],
        "current_spx_source_label": current_spx_source_label,
        "current_es_source_label": current_es_source_label,
        "live_es_available": live_defaults["es_available"],
        "live_spx_available": live_defaults["spx_available"],
        "derived_live_offset": live_defaults["derived_live_offset"],
        "es_fetch_status": live_defaults["es_fetch_status"],
        "spx_fetch_status": live_defaults["spx_fetch_status"],
        "quote_failure_classification": classify_quote_failure(live_defaults["es_fetch_status"], live_defaults["spx_fetch_status"]),
        "news_day": news_day,
        "es_spx_offset": es_spx_offset,
        "manual_price_space": manual_price_space,
        "options_mode_enabled": options_mode_enabled,
        "options_provider": options_provider,
        "pivot_high_time": at_central(prior_session_date, pivot_high_hour, 0),
        "pivot_low_time": at_central(prior_session_date, pivot_low_hour, 0),
        "pivot_green_high": pivot_green_high,
        "pivot_red_high": pivot_red_high,
        "pivot_red_low": pivot_red_low,
        "pivot_green_low": pivot_green_low,
        "hw_time": at_central(prior_session_date, hw_hour, 0),
        "hw_price": hw_price,
        "lw_time": at_central(prior_session_date, lw_hour, 0),
        "lw_price": lw_price,
        "use_asc_ceiling_override": use_asc_ceiling_override,
        "asc_ceiling_override": asc_ceiling_override,
        "use_desc_ceiling_override": use_desc_ceiling_override,
        "desc_ceiling_override": desc_ceiling_override,
        "use_asc_floor_override": use_asc_floor_override,
        "asc_floor_override": asc_floor_override,
        "use_desc_floor_override": use_desc_floor_override,
        "desc_floor_override": desc_floor_override,
    }


def resolve_anchor_bundle(
    inputs: dict[str, Any],
    conversion_offset: float,
) -> tuple[dict[str, Any], Any | None, str | None, dict[str, Any] | None]:
    """Resolve auto-fetched or manual anchors."""

    es_candles = None
    if inputs["data_mode"] == "Manual input":
        return (
            build_manual_anchor_bundle(
                prior_session_date=inputs["prior_session_date"],
                pivot_high_time=inputs["pivot_high_time"],
                pivot_green_high=inputs["pivot_green_high"],
                pivot_red_high=inputs["pivot_red_high"],
                pivot_low_time=inputs["pivot_low_time"],
                pivot_red_low=inputs["pivot_red_low"],
                pivot_green_low=inputs["pivot_green_low"],
                hw_time=inputs["hw_time"],
                hw_price=inputs["hw_price"],
                lw_time=inputs["lw_time"],
                lw_price=inputs["lw_price"],
                price_space=inputs["manual_price_space"],
                es_spx_offset=conversion_offset,
            ),
            es_candles,
            None,
            None,
        )

    base_diagnostics: dict[str, Any] | None = None

    try:
        es_candles, base_diagnostics = fetch_es_candles_for_app(
            inputs["prior_session_date"],
            inputs["next_trading_date"],
        )
        diagnostics = enrich_auto_fetch_diagnostics(
            base_diagnostics,
            es_candles,
            inputs["prior_session_date"],
            inputs["next_trading_date"],
        )
        if es_candles.empty:
            raise ValueError(
                diagnostics.get("explicit_error_message_if_dataframe_is_empty")
                or "Yahoo returned no usable intraday ES=F data for the selected dates."
            )
    except Exception as exc:
        diagnostics = enrich_auto_fetch_diagnostics(
            base_diagnostics,
            es_candles,
            inputs["prior_session_date"],
            inputs["next_trading_date"],
        )
        diagnostics["fetch_error"] = diagnostics.get("fetch_error") or f"{exc.__class__.__name__}: {exc}"
        if diagnostics.get("all_attempts_returned_empty_data"):
            diagnostics["explicit_error_message_if_dataframe_is_empty"] = (
                diagnostics.get("explicit_error_message_if_dataframe_is_empty")
                or "Yahoo returned no usable intraday ES=F data across all fetch attempts."
            )
        return (
            build_manual_anchor_bundle(
                prior_session_date=inputs["prior_session_date"],
                pivot_high_time=inputs["pivot_high_time"],
                pivot_green_high=inputs["pivot_green_high"],
                pivot_red_high=inputs["pivot_red_high"],
                pivot_low_time=inputs["pivot_low_time"],
                pivot_red_low=inputs["pivot_red_low"],
                pivot_green_low=inputs["pivot_green_low"],
                hw_time=inputs["hw_time"],
                hw_price=inputs["hw_price"],
                lw_time=inputs["lw_time"],
                lw_price=inputs["lw_price"],
                price_space=inputs["manual_price_space"],
                es_spx_offset=conversion_offset,
            ),
            es_candles,
            diagnostics.get("explicit_error_message_if_dataframe_is_empty") or diagnostics.get("fetch_error") or f"{exc.__class__.__name__}: {exc}",
            diagnostics,
        )

    try:
        return build_six_line_anchors(es_candles, inputs["prior_session_date"]), es_candles, None, diagnostics
    except Exception as exc:
        diagnostics = enrich_auto_fetch_diagnostics(
            base_diagnostics,
            es_candles,
            inputs["prior_session_date"],
            inputs["next_trading_date"],
        )
        diagnostics["anchor_build_error"] = f"{exc.__class__.__name__}: {exc}"
        diagnostics["fetch_error"] = diagnostics.get("fetch_error")
        return (
            build_manual_anchor_bundle(
                prior_session_date=inputs["prior_session_date"],
                pivot_high_time=inputs["pivot_high_time"],
                pivot_green_high=inputs["pivot_green_high"],
                pivot_red_high=inputs["pivot_red_high"],
                pivot_low_time=inputs["pivot_low_time"],
                pivot_red_low=inputs["pivot_red_low"],
                pivot_green_low=inputs["pivot_green_low"],
                hw_time=inputs["hw_time"],
                hw_price=inputs["hw_price"],
                lw_time=inputs["lw_time"],
                lw_price=inputs["lw_price"],
                price_space=inputs["manual_price_space"],
                es_spx_offset=conversion_offset,
            ),
            es_candles,
            f"Auto-fetch returned ES candles, but anchor extraction failed: {diagnostics['anchor_build_error']}",
            diagnostics,
        )


def build_override_inputs(
    inputs: dict[str, Any],
    projected_spx_9: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]] | None, dict[str, dict[str, Any]] | None]:
    """Build optional overnight override candidates in SPX space."""

    overnight_high: dict[str, dict[str, Any]] = {}
    overnight_low: dict[str, dict[str, Any]] = {}

    if inputs["use_asc_ceiling_override"]:
        overnight_high["asc_ceiling"] = {
            **projected_spx_9["asc_ceiling"],
            "projected_price": round_price(inputs["asc_ceiling_override"]),
        }
    if inputs["use_desc_ceiling_override"]:
        overnight_high["desc_ceiling"] = {
            **projected_spx_9["desc_ceiling"],
            "projected_price": round_price(inputs["desc_ceiling_override"]),
        }
    if inputs["use_asc_floor_override"]:
        overnight_low["asc_floor"] = {
            **projected_spx_9["asc_floor"],
            "projected_price": round_price(inputs["asc_floor_override"]),
        }
    if inputs["use_desc_floor_override"]:
        overnight_low["desc_floor"] = {
            **projected_spx_9["desc_floor"],
            "projected_price": round_price(inputs["desc_floor_override"]),
        }

    return overnight_high or None, overnight_low or None


def build_line_rows(
    original_lines: dict[str, dict[str, Any]],
    final_lines: dict[str, dict[str, Any]],
    override_decisions: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build a readable six-line table payload."""

    rows: list[dict[str, Any]] = []

    for name in LINE_DISPLAY_ORDER:
        original_line = original_lines[name]
        final_line = final_lines[name]
        decision = override_decisions.get(name, {})
        applied = bool(decision.get("applied"))
        origin = "Session extreme" if final_line["line_type"] == "session_extreme" else "Afternoon pivot"
        source_label = "Overnight override" if applied else origin

        rows.append(
            {
                "Line": final_line["label"],
                "Projected Level (SPX)": format_price(final_line["projected_price"]),
                "Raw Anchor (SPX)": format_price(final_line.get("raw_anchor_price", final_line["anchor_price"])),
                "Candle Count": final_line["candle_count"],
                "Direction": final_line["direction"],
                "Source": source_label,
                "Original Projected (SPX)": format_price(original_line["projected_price"]) if applied else "",
                "Override Projected (SPX)": format_price(final_line["projected_price"]) if applied else "",
            }
        )

    return rows


def render_six_lines_panel(
    original_lines: dict[str, dict[str, Any]],
    final_lines: dict[str, dict[str, Any]],
    override_decisions: dict[str, Any],
) -> None:
    """Render the six projected lines in operator-friendly order."""

    st.markdown(
        """
        <div class="spx-shell">
            <div class="spx-section-title">Projected Lines</div>
            <div class="spx-section-subtitle">
                Ordered display follows the house structure: HW, ASC Ceiling, ASC Floor, DESC Ceiling, DESC Floor, LW. All values below are shown in SPX terms.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.container():
        st.dataframe(
            build_line_rows(original_lines, final_lines, override_decisions),
            use_container_width=True,
            hide_index=True,
        )


def render_trade_decision_summary(signal_package: dict[str, Any], projected_lines: dict[str, dict[str, Any]]) -> None:
    """Render the fastest single-line operator summary."""

    scenario = signal_package["scenario"]
    primary_play = resolve_play_display_values(scenario.get("primary_play"), projected_lines)
    sit_out = signal_package["sit_out"]["sit_out"]

    scenario_name = scenario["scenario_name"]
    primary_direction = primary_play["direction"] if primary_play else "None"
    entry_line = primary_play["entry"]["label"] if primary_play else "None"
    contracts = str(primary_play["contracts"]) if primary_play else "0"
    strike = str(primary_play["strike"]) if primary_play else "-"
    sit_out_status = "SIT OUT" if sit_out else "ELIGIBLE"

    st.markdown(
        f"""
        <div class="spx-summary">
            <div class="spx-summary-title">Trade Decision Summary</div>
            <div class="spx-summary-body">
                Scenario: {scenario_name} | Primary: {primary_direction} | Entry: {entry_line} |
                Contracts: {contracts} | Strike: {strike} | Status: {sit_out_status}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_scenario_section(scenario: dict[str, Any]) -> None:
    """Render the scenario banner and summary."""

    scenario_tone = get_scenario_tone(scenario["scenario_name"])
    confidence_tone = get_confidence_tone(scenario["confidence_level"])
    st.markdown(
        f"""
        <div class="spx-banner">
            <div class="spx-section-title">Scenario State</div>
            <div class="spx-banner-name">{scenario['scenario_name']}</div>
            <div class="spx-banner-meta">
                <span class="spx-pill scenario-{scenario_tone}">Scenario Live</span>
                <span class="spx-pill conf-{confidence_tone}">Confidence {scenario['confidence_level']}</span>
                <span class="spx-pill scenario-neutral">Price {format_price(scenario['current_price'])}</span>
            </div>
            <div class="spx-banner-text">{scenario['description']}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_play_card(
    title: str,
    play: dict[str, Any] | None,
    projected_lines: dict[str, dict[str, Any]],
) -> None:
    """Render a single structured play card."""

    card_class = "primary" if "Primary" in title else "alternate"
    icon = "▲" if title == "Primary Trade" else "◇"
    subtitle = "Primary setup" if "Primary" in title else "Alternate setup"

    if play is None:
        st.markdown(
            f"""
            <div class="spx-card {card_class}">
                <div class="spx-card-title">
                    <div class="spx-card-icon">{icon}</div>
                    <div>
                        <div class="spx-card-heading">{escape(title)}</div>
                        <div class="spx-card-subtitle">{escape(subtitle)}</div>
                    </div>
                </div>
                <div class="spx-muted">No alternate play.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    play = resolve_play_display_values(play, projected_lines)

    st.markdown(
        f"""
        <div class="spx-card {card_class}">
            <div class="spx-card-title">
                <div class="spx-card-icon">{icon}</div>
                <div>
                    <div class="spx-card-heading">{escape(title)}</div>
                    <div class="spx-card-subtitle">{escape(subtitle)}</div>
                </div>
            </div>
            <div style="display:flex; align-items:flex-end; justify-content:space-between; gap:1rem; margin-bottom:1rem;">
                <div>
                    <div style="font-family:'Outfit','Segoe UI',sans-serif; font-size:2rem; font-weight:800; color:#f8fbff; line-height:1;">{escape(play['direction'])}</div>
                    <div style="font-family:'JetBrains Mono', monospace; font-size:2rem; font-weight:800; color:#f8fbff; line-height:1.05; text-shadow:0 0 18px rgba(0,212,255,0.14); margin-top:0.35rem;">{format_price(play['entry']['price'])}</div>
                </div>
                <div class="spx-banner-meta" style="margin-bottom:0;">
                    <span class="spx-pill scenario-neutral">{escape(play['entry']['label'])}</span>
                </div>
            </div>
            <div style="display:flex; flex-wrap:wrap; gap:0.9rem 1.2rem; color:#d7e2f1; font-size:1rem; line-height:1.7;">
                <div><span class="spx-muted">Strike</span> <span style="font-family:'JetBrains Mono', monospace; font-weight:700; color:#f8fbff;">{play['strike']}</span></div>
                <div><span class="spx-muted">{play['contracts']} contract{'s' if int(play['contracts']) != 1 else ''}</span></div>
                <div><span class="spx-muted">Stop</span> <span style="font-family:'JetBrains Mono', monospace; font-weight:700; color:#f8fbff;">{format_price(play['stop']['price'])}</span></div>
            </div>
            <div style="margin-top:0.35rem; color:#9cb0ca; font-size:0.9rem;">
                {escape(play['stop']['label'])}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def render_projection_verification(
    anchor_bundle: dict[str, Any],
    final_projected_lines_spx: dict[str, dict[str, Any]],
    final_projected_lines_es: dict[str, dict[str, Any]],
    displayed_lines: dict[str, dict[str, Any]],
    displayed_unit_label: str,
) -> None:
    """Temporary verification block proving Tab 1 structure uses a single unit system."""

    verification_rows: list[dict[str, Any]] = []
    warnings: list[str] = []

    for name in LINE_DISPLAY_ORDER:
        displayed_details = displayed_lines[name]
        spx_details = final_projected_lines_spx[name]
        es_details = final_projected_lines_es[name]
        raw_es_value = float(anchor_bundle["anchors"][name]["price"])
        raw_spx_value = float(spx_details.get("raw_anchor_price", spx_details["anchor_price"]))
        projected_es_value = float(es_details["projected_price"])
        projected_spx_value = float(spx_details["projected_price"])
        displayed_value = float(displayed_details["projected_price"])
        candle_count = int(spx_details["candle_count"])

        verification_rows.append(
            {
                "line_label": displayed_details["label"],
                "raw_es_value": f"{format_price(raw_es_value)} (ES)",
                "converted_spx_value": f"{format_price(raw_spx_value)} (SPX)",
                "projected_es_value": f"{format_price(projected_es_value)} (ES)",
                "projected_spx_value": f"{format_price(projected_spx_value)} (SPX)",
                "final_displayed_value": f"{format_price(displayed_value)} ({displayed_unit_label})",
                "candle_count": candle_count,
                "direction": spx_details["direction"],
            }
        )

        if name in {"hw", "lw"} and candle_count > 0 and abs(projected_spx_value - raw_spx_value) < 1e-9:
            warnings.append(
                f"{displayed_details['label']} has candle_count={candle_count} but projected_price still matches raw_anchor_price in SPX terms."
            )

    with st.expander("Projection Verification", expanded=False):
        st.dataframe(verification_rows, use_container_width=True, hide_index=True)
        for warning in warnings:
            st.warning(warning)
        if not warnings:
            st.caption("Verification passed: projected display values differ from raw anchors when candle counts are non-zero.")


def build_confirmation_detail(
    confirmation: dict[str, Any],
    primary_play: dict[str, Any] | None,
) -> dict[str, str]:
    """Build a transparent explanation for the 8:30 confirmation result."""

    if primary_play is None:
        return {
            "line_tested": "No active primary play",
            "status_label": "WAITING",
            "reason": "No primary play exists for this scenario, so no 8:30 confirmation can be evaluated.",
        }

    line_label = primary_play["entry"]["label"]
    line_price = float(primary_play["entry"]["price"])
    direction = primary_play["direction"]
    line_tested = f"{line_label} @ {format_price(line_price)}"

    if not confirmation.get("available"):
        return {
            "line_tested": line_tested,
            "status_label": "WAITING",
            "reason": "No 8:30 AM SPX candle was available from the data source.",
        }

    candle = confirmation["candle"]
    candle_color = candle["color"]
    close_price = float(candle["close"])
    high_price = float(candle["high"])
    low_price = float(candle["low"])

    if confirmation.get("confirmed"):
        if direction == "PUT":
            reason = (
                f"PUT confirmed because the 8:30 candle wicked to {line_label}, "
                f"stayed below {format_price(line_price)}, and closed green below the line."
            )
        else:
            reason = (
                f"CALL confirmed because the 8:30 candle wicked to {line_label}, "
                f"held above {format_price(line_price)}, and closed red above the line."
            )
        return {
            "line_tested": line_tested,
            "status_label": "CONFIRMED",
            "reason": reason,
        }

    if not confirmation.get("tested"):
        if direction == "PUT":
            reason = f"Waiting because the 8:30 high {format_price(high_price)} did not reach the {line_label} line."
        else:
            reason = f"Waiting because the 8:30 low {format_price(low_price)} did not reach the {line_label} line."
        return {
            "line_tested": line_tested,
            "status_label": "WAITING",
            "reason": reason,
        }

    if direction == "PUT":
        if close_price >= line_price:
            reason = (
                f"PUT failed because the candle closed at or above {line_label} "
                f"({format_price(close_price)} vs {format_price(line_price)})."
            )
        else:
            reason = (
                f"PUT failed because the candle closed {candle_color} below the line. "
                "A red close below the line is selling, not a failed breakout."
            )
    else:
        if close_price <= line_price:
            reason = (
                f"CALL failed because the candle closed at or below {line_label} "
                f"({format_price(close_price)} vs {format_price(line_price)})."
            )
        else:
            reason = (
                f"CALL failed because the candle closed {candle_color} above the line. "
                "A green close above the line is buying, not a failed breakdown."
            )

    return {
        "line_tested": line_tested,
        "status_label": "FAILED",
        "reason": reason,
    }


def render_confirmation_card(
    confirmation: dict[str, Any],
    primary_play: dict[str, Any] | None,
) -> None:
    """Render the 8:30 confirmation card with explanation."""

    detail = build_confirmation_detail(confirmation, primary_play)
    tone = "conf-high" if detail["status_label"] == "CONFIRMED" else "conf-low" if detail["status_label"] == "FAILED" else "conf-medium"
    st.markdown(
        f"""
        <div class="spx-card">
            <div class="spx-card-title">
                <div class="spx-card-icon">◉</div>
                <div>
                    <div class="spx-card-heading">8:30 Confirmation</div>
                    <div class="spx-card-subtitle">SPX candle test against the active entry line.</div>
                </div>
            </div>
            <div class="spx-banner-meta">
                <span class="spx-pill {tone}">{detail['status_label']}</span>
                <span class="spx-pill">Line {escape(detail['line_tested'])}</span>
            </div>
            <div class="spx-card-copy">{escape(detail['reason'])}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if confirmation.get("available"):
        candle = confirmation["candle"]
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Open", format_price(candle["open"]))
        col2.metric("High", format_price(candle["high"]))
        col3.metric("Low", format_price(candle["low"]))
        col4.metric("Close", format_price(candle["close"]))
        col5.metric("Color", str(candle["color"]).upper())
    else:
        st.info("No 8:30 candle data available.")

    st.caption(f"Engine status: {confirmation['status']} | Timing: {confirmation['entry_timing']}")


def render_sit_out_section(sit_out: dict[str, Any]) -> None:
    """Render the sit-out or eligible-to-trade status block."""

    if sit_out["sit_out"]:
        st.markdown('<div class="spx-status-bad"><div class="spx-status-title">⚠ SIT OUT — DO NOT TRADE</div><div class="spx-muted">One or more risk filters are active. Preserve capital and wait for cleaner structure.</div></div>', unsafe_allow_html=True)
        for reason in sit_out["reasons"]:
            st.write(f"- {reason}")
    else:
        st.markdown('<div class="spx-status-good"><div class="spx-status-title">● Eligible To Trade</div><div class="spx-muted">No sit-out condition is currently active. Focus stays on confirmation and line behavior.</div></div>', unsafe_allow_html=True)


def render_debug_section(
    anchor_bundle: dict[str, Any],
    final_projected_lines: dict[str, dict[str, Any]],
    original_projected_lines: dict[str, dict[str, Any]],
    override_result: dict[str, Any],
    overnight_high: dict[str, dict[str, Any]] | None,
    overnight_low: dict[str, dict[str, Any]] | None,
    fetch_diagnostics: dict[str, Any] | None,
) -> None:
    """Render collapsible debug sections for operator verification."""

    st.markdown(
        """
        <div class="spx-shell">
            <div class="spx-section-title">Debug</div>
            <div class="spx-section-subtitle">Full transparency remains available here without cluttering the main decision view.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    pivot_anchor_debug = {
        "pivot_high": anchor_bundle.get("pivot_high"),
        "pivot_low": anchor_bundle.get("pivot_low"),
        "session_extremes": anchor_bundle.get("session_extremes"),
        "resolved_anchors": anchor_bundle.get("anchors"),
    }

    candle_counts = {
        name: {
            "label": details["label"],
            "count_start": format_timestamp(details["projection_start_time"]),
            "anchor_timestamp": format_timestamp(details["anchor_timestamp"]),
            "candle_count": details["candle_count"],
            "projected_price": round_price(details["projected_price"]),
        }
        for name, details in final_projected_lines.items()
    }

    override_debug = {
        "decisions": override_result["decisions"],
        "original_lines": {
            name: {
                "label": details["label"],
                "projected_price": round_price(details["projected_price"]),
            }
            for name, details in original_projected_lines.items()
        },
        "final_lines": {
            name: {
                "label": details["label"],
                "projected_price": round_price(details["projected_price"]),
            }
            for name, details in final_projected_lines.items()
        },
    }

    with st.expander("Pivot Anchors", expanded=False):
        st.json(pivot_anchor_debug, expanded=False)

    with st.expander("Auto-Fetch Diagnostics", expanded=False):
        if fetch_diagnostics is None:
            st.info("Auto-fetch diagnostics are only available when Data Mode is set to Auto-fetch.")
        else:
            attempts = fetch_diagnostics.get("fetch_attempts") or []
            summary = {
                "raw_ticker_used": fetch_diagnostics.get("raw_ticker_used"),
                "successful_fetch_attempt": fetch_diagnostics.get("successful_fetch_attempt"),
                "final_fetch_method_chosen": fetch_diagnostics.get("final_fetch_method_chosen"),
                "all_attempts_returned_empty_data": fetch_diagnostics.get("all_attempts_returned_empty_data"),
                "row_count_returned_before_any_filtering": fetch_diagnostics.get("row_count_returned_before_any_filtering"),
                "first_timestamp_returned": fetch_diagnostics.get("first_timestamp_returned"),
                "last_timestamp_returned": fetch_diagnostics.get("last_timestamp_returned"),
                "timezone_info_before_conversion": fetch_diagnostics.get("timezone_info_before_conversion"),
                "row_count_after_timezone_conversion": fetch_diagnostics.get("row_count_after_timezone_conversion"),
                "row_count_in_full_ny_session_filter": fetch_diagnostics.get("row_count_in_full_ny_session_filter"),
                "row_count_in_12_pm_to_4_pm_ct_afternoon_filter": fetch_diagnostics.get("row_count_in_12_pm_to_4_pm_ct_afternoon_filter"),
                "row_count_in_overnight_filter": fetch_diagnostics.get("row_count_in_overnight_filter"),
                "pivot_high_found": fetch_diagnostics.get("pivot_high_found"),
                "pivot_low_found": fetch_diagnostics.get("pivot_low_found"),
                "session_extremes_found": fetch_diagnostics.get("session_extremes_found"),
                "explicit_error_message_if_dataframe_is_empty": fetch_diagnostics.get("explicit_error_message_if_dataframe_is_empty"),
                "fetch_error": fetch_diagnostics.get("fetch_error"),
            }
            st.json(summary, expanded=False)
            if attempts:
                st.dataframe(
                    [
                        {
                            "attempt": attempt.get("name"),
                            "description": attempt.get("description"),
                            "status": attempt.get("status"),
                            "raw_row_count": attempt.get("raw_row_count"),
                            "normalized_row_count": attempt.get("normalized_row_count"),
                            "rows_returned": attempt.get("rows_returned"),
                            "error": attempt.get("error"),
                        }
                        for attempt in attempts
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            st.json(fetch_diagnostics, expanded=False)

    with st.expander("Candle Counts", expanded=False):
        st.json(candle_counts, expanded=False)

    with st.expander("Overnight Override Decisions", expanded=False):
        st.json(override_debug, expanded=False)

    with st.expander("Raw Afternoon Candles", expanded=False):
        afternoon_candles = anchor_bundle.get("afternoon_candles") or []
        if afternoon_candles:
            st.dataframe(afternoon_candles, use_container_width=True, hide_index=True)
        else:
            st.info("No afternoon candles available.")

    with st.expander("Raw Overnight Pivot Candidates", expanded=False):
        candidates = {
            "overnight_high": overnight_high,
            "overnight_low": overnight_low,
        }
        if overnight_high or overnight_low:
            st.json(candidates, expanded=False)
        else:
            st.info("No overnight pivot candidates were provided.")


def build_evening_checkpoint_views(
    anchor_bundle: dict[str, Any],
    next_trading_date: date,
    es_spx_offset: float,
    overnight_high: dict[str, dict[str, Any]] | None,
    overnight_low: dict[str, dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Build 6 PM, 7 PM, and 8 PM checkpoint views for the evening session."""

    evening_session_date = next_trading_date - timedelta(days=1)
    checkpoints = [
        ("6:00 PM CT", at_central(evening_session_date, 18, 0)),
        ("7:00 PM CT", at_central(evening_session_date, 19, 0)),
        ("8:00 PM CT", at_central(evening_session_date, 20, 0)),
    ]

    views: list[dict[str, Any]] = []

    for label, checkpoint_time in checkpoints:
        projected_es = project_six_lines(anchor_bundle["anchors"], checkpoint_time)
        projected_spx = convert_projected_lines(projected_es, es_spx_offset, "spx")
        override_result = apply_overnight_pivot_overrides(
            projected_spx,
            overnight_high=overnight_high,
            overnight_low=overnight_low,
        )
        final_spx = override_result["projected_lines"]
        final_es = convert_projected_lines(final_spx, es_spx_offset, "es")
        views.append(
            {
                "label": label,
                "checkpoint_time": checkpoint_time,
                "spx_lines": final_spx,
                "es_lines": final_es,
                "override_decisions": override_result["decisions"],
            }
        )

    return views


def render_checkpoint_views(checkpoint_views: list[dict[str, Any]]) -> None:
    """Render SPX and ES values for evening checkpoints."""

    st.markdown(
        """
        <div class="spx-shell">
            <div class="spx-section-title">Checkpoint Views</div>
            <div class="spx-section-subtitle">These are observation checkpoints, not forced trade windows.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    columns = st.columns(len(checkpoint_views))
    for column, checkpoint in zip(columns, checkpoint_views, strict=False):
        with column:
            with st.container():
                st.markdown(
                    f"""
                    <div class="spx-card">
                        <div class="spx-card-title">
                            <div class="spx-card-icon">◌</div>
                            <div>
                                <div class="spx-card-heading">{escape(checkpoint['label'])}</div>
                                <div class="spx-card-subtitle">Reference checkpoint for ES monitoring, not a forced execution window.</div>
                            </div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.dataframe(
                    [
                        {
                            "line": checkpoint["spx_lines"][name]["label"],
                            "SPX": format_price(checkpoint["spx_lines"][name]["projected_price"]),
                            "ES": format_price(checkpoint["es_lines"][name]["projected_price"]),
                        }
                        for name in LINE_DISPLAY_ORDER
                    ],
                    use_container_width=True,
                    hide_index=True,
                )


def find_nearest_lines(line_values: dict[str, float], current_price: float) -> tuple[tuple[str, float] | None, tuple[str, float] | None]:
    """Find the nearest resistance above and support below the current price."""

    ordered = sorted(line_values.items(), key=lambda item: item[1])
    resistance = next(((name, value) for name, value in ordered if value >= current_price), None)
    support = next(((name, value) for name, value in reversed(ordered) if value <= current_price), None)
    return resistance, support


def render_evening_location_panel(current_es_price: float, selected_checkpoint: dict[str, Any]) -> dict[str, Any]:
    """Render the current ES price location relative to the checkpoint structure."""

    es_line_values = {name: details["projected_price"] for name, details in selected_checkpoint["es_lines"].items()}
    reference_scenario = evaluate_trading_scenario(
        current_price=current_es_price,
        line_values=es_line_values,
        open_price=current_es_price,
        confirmation_confirmed=False,
    )
    nearest_resistance, nearest_support = find_nearest_lines(es_line_values, current_es_price)

    st.markdown(
        """
        <div class="spx-shell">
            <div class="spx-section-title">Current ES Structure</div>
            <div class="spx-section-subtitle">Reference framework based on line location.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    top_left, top_mid, top_right = st.columns(3)
    top_left.metric("Checkpoint", selected_checkpoint["label"])
    top_mid.metric("Current ES", format_price(current_es_price))
    top_right.metric("Structure", reference_scenario["scenario_name"])

    lower_left, lower_right = st.columns(2)
    lower_left.metric(
        "Nearest Resistance Above",
        f"{nearest_resistance[0]} @ {format_price(nearest_resistance[1])}" if nearest_resistance else "None above",
    )
    lower_right.metric(
        "Nearest Support Below",
        f"{nearest_support[0]} @ {format_price(nearest_support[1])}" if nearest_support else "None below",
    )

    with st.container(border=True):
        st.markdown('<div class="spx-reference">Reference framework based on line location</div>', unsafe_allow_html=True)
        st.write(reference_scenario["description"])
        st.write(f"Primary reference direction: {reference_scenario['primary_trade_direction'] or 'None'}")
        st.write(f"Alternate reference direction: {reference_scenario['alternate_trade'] or 'None'}")
        st.write(f"Confidence label: {reference_scenario['confidence_level']}")

    return reference_scenario


def render_evening_decision_framework() -> None:
    """Render the checkpoint-based evening monitoring workflow."""

    with st.container():
        st.markdown(
            """
            <div class="spx-card">
                <div class="spx-card-title">
                    <div class="spx-card-icon">◍</div>
                    <div>
                        <div class="spx-card-heading">Evening Decision Framework</div>
                        <div class="spx-card-subtitle">Checkpoint-based monitoring for delayed touches and delayed reactions.</div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.write("Session open / observe: 5:00 PM CT")
        st.write("First checkpoint: 6:00 PM CT")
        st.write("Second checkpoint: 7:00 PM CT")
        st.write("Third checkpoint: 8:00 PM CT")
        st.write("Continue monitoring line interactions after 8:00 PM CT if price has not yet reached the relevant line.")
        st.write("If price touches a line, the expected reaction may occur in the same hour or the following hour.")


def render_evening_line_ladder(selected_checkpoint: dict[str, Any]) -> None:
    """Render the ES line ladder from highest to lowest."""

    with st.container():
        st.markdown(
            """
            <div class="spx-card">
                <div class="spx-card-title">
                    <div class="spx-card-icon">▥</div>
                    <div>
                        <div class="spx-card-heading">Ordered ES Line Ladder</div>
                        <div class="spx-card-subtitle">Highest to lowest structure for faster evening scanning.</div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.dataframe(
            [
                {
                    "line": selected_checkpoint["es_lines"][name]["label"],
                    "ES value": format_price(selected_checkpoint["es_lines"][name]["projected_price"]),
                }
                for name in LINE_DISPLAY_ORDER
            ],
            use_container_width=True,
            hide_index=True,
        )


def render_evening_debug(
    es_spx_offset: float,
    current_es_price: float,
    checkpoint_views: list[dict[str, Any]],
) -> None:
    """Render transparency details for the Asian session tab."""

    st.markdown(
        """
        <div class="spx-shell">
            <div class="spx-section-title">Debug / Transparency</div>
            <div class="spx-section-subtitle">Offset, checkpoint labels, and full SPX-to-ES values remain visible here.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    debug_payload = {
        "es_spx_offset": round_price(es_spx_offset),
        "current_es_input": round_price(current_es_price),
        "checkpoint_labels": [checkpoint["label"] for checkpoint in checkpoint_views],
        "checkpoints": {
            checkpoint["label"]: {
                "spx_values": {
                    name: round_price(details["projected_price"])
                    for name, details in checkpoint["spx_lines"].items()
                },
                "es_values": {
                    name: round_price(details["projected_price"])
                    for name, details in checkpoint["es_lines"].items()
                },
            }
            for checkpoint in checkpoint_views
        },
    }
    st.json(debug_payload, expanded=False)


def render_trade_log_tab(
    signal_package: dict[str, Any] | None,
    settings: dict[str, Any],
    settings_message: str | None = None,
) -> None:
    """Render the trade journal, history, and analytics tab."""

    st.markdown(
        """
        <div class="spx-hero">
            <div class="spx-hero-top">
                <div>
                    <div class="spx-hero-kicker">Trade Journal + Intelligence</div>
                    <div class="spx-hero-title">Review The Edge</div>
                    <div class="spx-hero-subtitle">Capture execution quality, review snapshots, and track which scenarios actually pay you over time.</div>
                </div>
                <div class="spx-hero-status">
                    <div class="spx-hero-status-label">Mode</div>
                    <div class="spx-status-chip good"><span>◉</span><span>Journal Ready</span></div>
                </div>
            </div>
            <div class="spx-hero-grid">
                <div class="spx-hero-stat">
                    <div class="spx-hero-stat-label">Entry</div>
                    <div class="spx-hero-stat-value">Log Trades</div>
                    <div class="spx-hero-stat-note">Capture scenario, confirmation, and notes.</div>
                </div>
                <div class="spx-hero-stat">
                    <div class="spx-hero-stat-label">Review</div>
                    <div class="spx-hero-stat-value">Snapshots</div>
                    <div class="spx-hero-stat-note">Connect structure to outcome quality.</div>
                </div>
                <div class="spx-hero-stat">
                    <div class="spx-hero-stat-label">Analytics</div>
                    <div class="spx-hero-stat-value">Expectancy</div>
                    <div class="spx-hero-stat-note">Find the setups that truly hold edge.</div>
                </div>
                <div class="spx-hero-stat">
                    <div class="spx-hero-stat-label">Storage</div>
                    <div class="spx-hero-stat-value">Local JSON</div>
                    <div class="spx-hero-stat-note">Backed up and exportable.</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    trades, load_error = load_trades()
    snapshots, snapshot_error = load_snapshots()
    normalized_trades = [normalize_trade_record(trade) for trade in trades]
    normalized_snapshots = [normalize_snapshot_record(snapshot) for snapshot in snapshots]
    if load_error:
        st.warning(load_error)
    if snapshot_error:
        st.warning(snapshot_error)

    data_health = build_data_health_report(
        normalized_trades,
        normalized_snapshots,
        settings,
        load_error=load_error,
        snapshot_error=snapshot_error,
        settings_message=settings_message,
    )

    prefill = get_trade_form_prefill(signal_package)
    default_scenario_name = prefill["scenario_name"]
    default_direction = prefill["direction"] or "CALL"
    default_entry_label = prefill["entry_line_label"]
    default_entry_value = prefill["entry_line_value"]
    default_contracts = prefill["contracts"]
    default_confluence = 0
    available_snapshot_options = ["No snapshot link"]
    snapshot_lookup: dict[str, tuple[str, str]] = {"No snapshot link": ("", "")}
    for snapshot in reversed(normalized_snapshots):
        option_label = f"{snapshot['snapshot_date']} | {snapshot['scenario'].get('scenario_name', 'Snapshot')}"
        available_snapshot_options.append(option_label)
        snapshot_lookup[option_label] = (snapshot["id"], snapshot["snapshot_date"])

    render_section_header("Trade Entry", "Capture the execution details while the trade context is still fresh.")
    with st.container(border=True):
        if st.session_state.get("trade_form_notice"):
            st.info(st.session_state["trade_form_notice"])
            if st.button("Clear Prefill", type="secondary", use_container_width=False):
                clear_trade_form_prefill()
                st.rerun()
        with st.form("trade_entry_form", clear_on_submit=False):
            col1, col2 = st.columns(2)
            with col1:
                trade_date = st.date_input("Trade date", value=date.fromisoformat(prefill["trade_date"]))
                session = st.selectbox("Session", SESSION_OPTIONS, index=safe_option_index(SESSION_OPTIONS, prefill["session"]))
                scenario_name = st.text_input("Scenario name", value=default_scenario_name)
                direction = st.selectbox("Direction", TRADE_DIRECTION_OPTIONS, index=safe_option_index(TRADE_DIRECTION_OPTIONS, default_direction))
                strike_or_contract_label = st.text_input("Strike or contract label", value=prefill["strike_or_contract_label"])
                entry_line_label = st.text_input("Entry line label", value=default_entry_label)
                entry_line_value = st.number_input("Entry line value", value=float(default_entry_value), step=0.25, format="%.2f")
            with col2:
                entry_value = st.number_input("Entry premium or entry price", value=0.0, step=0.05, format="%.2f")
                exit_value = st.number_input("Exit premium or exit price", value=0.0, step=0.05, format="%.2f")
                contracts = st.number_input("Contracts", min_value=1, value=int(default_contracts), step=1)
                confluence_score = st.number_input("Confluence score", min_value=0, max_value=5, value=default_confluence, step=1)
                result = st.selectbox("Result", RESULT_OPTIONS)
                confirmation_status = st.selectbox(
                    "Confirmation status",
                    CONFIRMATION_STATUS_OPTIONS,
                    index=safe_option_index(CONFIRMATION_STATUS_OPTIONS, prefill.get("confirmation_status", "Not Recorded"), default=CONFIRMATION_STATUS_OPTIONS.index("Not Recorded")),
                )
                snapshot_default_label = "No snapshot link"
                for option_label, (snapshot_id, snapshot_date) in snapshot_lookup.items():
                    if snapshot_id == prefill.get("linked_snapshot_id") or (snapshot_date and snapshot_date == prefill.get("linked_snapshot_date")):
                        snapshot_default_label = option_label
                        break
                snapshot_link_label = st.selectbox("Linked daily snapshot", available_snapshot_options, index=safe_option_index(available_snapshot_options, snapshot_default_label))
                notes = st.text_area("Notes", value=prefill.get("notes", ""), height=120)

            quick_tags = st.multiselect("Quick tags", QUICK_TAG_OPTIONS, default=[])
            preview_pnl = compute_preview_pnl(direction, entry_value, exit_value, int(contracts))
            st.info(
                "P&L Preview (simple journal logic): "
                f"{format_price(preview_pnl)} based on entry, exit, direction, and contracts."
            )

            submitted = st.form_submit_button("Save Trade", use_container_width=True)

            if submitted:
                raw_trade_record = {
                    "id": str(uuid4()),
                    "trade_date": trade_date.isoformat(),
                    "session": session,
                    "scenario_name": scenario_name,
                    "direction": direction,
                    "strike_or_contract_label": strike_or_contract_label,
                    "entry_line_label": entry_line_label,
                    "entry_line_value": entry_line_value,
                    "entry_value": entry_value,
                    "exit_value": exit_value,
                    "contracts": int(contracts),
                    "confluence_score": int(confluence_score),
                    "result": result,
                    "confirmation_status": confirmation_status,
                    "linked_snapshot_id": snapshot_lookup[snapshot_link_label][0],
                    "linked_snapshot_date": snapshot_lookup[snapshot_link_label][1],
                    "notes": notes,
                    "tags": quick_tags,
                    "pnl_preview": preview_pnl,
                }
                form_errors = validate_trade_form_payload(raw_trade_record)
                if form_errors:
                    for form_error in form_errors:
                        st.error(form_error)
                else:
                    trade_record = normalize_trade_record(raw_trade_record)
                    saved, error = append_trade(trade_record)
                    if saved:
                        clear_trade_form_prefill()
                        st.success("Trade saved.")
                        if error:
                            st.warning(error)
                        st.rerun()
                    else:
                        st.error(error or "Unable to save trade.")

    if normalized_trades:
        trade_dates: list[date] = []
        for trade in normalized_trades:
            try:
                trade_dates.append(date.fromisoformat(str(trade["trade_date"])))
            except ValueError:
                continue
        min_trade_date = min(trade_dates) if trade_dates else current_central_time().date()
        max_trade_date = max(trade_dates) if trade_dates else current_central_time().date()
    else:
        min_trade_date = current_central_time().date()
        max_trade_date = current_central_time().date()

    render_section_header("Filters", "Shape the journal view by date, session, scenario, confirmation, and tags.")
    with st.container(border=True):
        filter_col1, filter_col2, filter_col3 = st.columns(3)
        with filter_col1:
            filter_date_from = st.date_input("From", value=min_trade_date, key="filter_date_from")
            filter_scenarios = st.multiselect(
                "Scenario",
                options=sorted({trade["scenario_name"] for trade in normalized_trades if trade.get("scenario_name")}),
                default=[],
            )
        with filter_col2:
            filter_date_to = st.date_input("To", value=max_trade_date, key="filter_date_to")
            filter_sessions = st.multiselect(
                "Session",
                options=sorted({trade["session"] for trade in normalized_trades if trade.get("session")}),
                default=[],
            )
        with filter_col3:
            filter_results = st.multiselect(
                "Result",
                options=RESULT_OPTIONS,
                default=[],
            )
            filter_confirmation_status = st.multiselect(
                "Confirmation status",
                options=CONFIRMATION_STATUS_OPTIONS,
                default=[],
            )

        filter_col4, filter_col5 = st.columns(2)
        with filter_col4:
            filter_confluence_scores = st.multiselect(
                "Confluence score",
                options=sorted({int(trade.get("confluence_score", 0)) for trade in normalized_trades}),
                default=[],
            )
        with filter_col5:
            filter_tags = st.multiselect(
                "Tags",
                options=sorted({tag for trade in normalized_trades for tag in trade.get("tags", [])}),
                default=[],
            )

    filtered_trades = filter_trades(
        normalized_trades,
        date_from=filter_date_from,
        date_to=filter_date_to,
        scenarios=filter_scenarios,
        sessions=filter_sessions,
        results=filter_results,
        confluence_scores=filter_confluence_scores,
        confirmation_statuses=filter_confirmation_status,
        tags=filter_tags,
    )
    filtered_snapshots = filter_snapshots_by_date(normalized_snapshots, filter_date_from, filter_date_to)

    render_section_header("Performance Dashboard", "Fast pulse check on the filtered trade set.")
    stats = compute_trade_statistics(filtered_trades)
    stat1, stat2, stat3 = st.columns(3)
    stat1.metric("Total Trades", str(stats["total_trades"]))
    stat2.metric("Total Wins", str(stats["total_wins"]))
    stat3.metric("Total Losses", str(stats["total_losses"]))

    stat4, stat5, stat6 = st.columns(3)
    stat4.metric("Win Rate", f"{stats['win_rate']:.2f}%")
    stat5.metric("Total P&L", format_price(stats["total_pnl"]))
    stat6.metric("Average P&L / Trade", format_price(stats["average_pnl"]))

    render_section_header("Version 2 Strategy Intelligence", "Compare outcomes by scenario, confluence, session, confirmation, and tags.")
    st.caption("Analytics update live from the filtered trade set below.")
    breakdown_tabs = st.tabs(["By Scenario", "By Confluence", "By Session", "By Confirmation", "By Tag"])
    breakdown_dimensions = [
        ("scenario", "scenario"),
        ("confluence", "confluence score"),
        ("session", "session"),
        ("confirmation", "confirmation status"),
        ("tag", "result tag"),
    ]
    for tab, (dimension, label) in zip(breakdown_tabs, breakdown_dimensions, strict=False):
        with tab:
            breakdown = build_breakdown_dataframe(filtered_trades, dimension)
            if breakdown.empty:
                st.info(f"No trade data available for {label} analytics yet.")
            else:
                st.dataframe(breakdown, use_container_width=True, hide_index=True)

    render_section_header("Version 2.1 Decision-Filter Intelligence", "Review which filters and confirmations actually improve outcomes.")
    best_worst = compute_best_worst_summary(filtered_trades)
    best_col1, best_col2, best_col3 = st.columns(3)
    best_col1.metric("Best Scenario by Win Rate", best_worst["best_scenario_win_rate"])
    best_col2.metric("Best Scenario by Total P&L", best_worst["best_scenario_total_pnl"])
    best_col3.metric("Worst Scenario by Total P&L", best_worst["worst_scenario_total_pnl"])

    best_col4, best_col5 = st.columns(2)
    best_col4.metric("Best Confirmation Status", best_worst["best_confirmation_status"])
    best_col5.metric("Worst Confirmation Status", best_worst["worst_confirmation_status"])

    rolling_dataframe = compute_rolling_performance(filtered_trades, [7, 14, 30])
    streaks = compute_streaks(filtered_trades)
    rolling_col, streak_col = st.columns([1.6, 1], gap="large")
    with rolling_col:
        with st.container(border=True):
            st.markdown("#### Rolling Performance")
            if rolling_dataframe.empty:
                st.info("No trades available for rolling performance yet.")
            else:
                st.dataframe(rolling_dataframe, use_container_width=True, hide_index=True)
    with streak_col:
        with st.container(border=True):
            st.markdown("#### Recent Streaks")
            st.metric("Current Streak", str(streaks["current_streak"]))
            st.metric("Longest Win Streak", str(streaks["longest_win_streak"]))
            st.metric("Longest Loss Streak", str(streaks["longest_loss_streak"]))

    sit_out_intelligence = compute_sit_out_effectiveness(filtered_snapshots, filtered_trades)
    st.markdown("#### Sit-Out Effectiveness")
    sitout_col1, sitout_col2, sitout_col3 = st.columns(3)
    sitout_col1.metric("Sit-Out Triggered", str(sit_out_intelligence["metrics"]["sit_out_triggered"]))
    sitout_col2.metric("Sit-Out Days Traded Anyway", str(sit_out_intelligence["metrics"]["sit_out_days_traded"]))
    sitout_col3.metric("Sit-Out Day P&L", format_price(sit_out_intelligence["metrics"]["sit_out_day_total_pnl"]))

    sitout_col4, sitout_col5, sitout_col6 = st.columns(3)
    sitout_col4.metric("Sit-Out Day Wins", str(sit_out_intelligence["metrics"]["sit_out_day_wins"]))
    sitout_col5.metric("Sit-Out Day Losses", str(sit_out_intelligence["metrics"]["sit_out_day_losses"]))
    sitout_col6.metric("Sit-Out Would Have Helped", str(sit_out_intelligence["metrics"]["sit_out_would_have_helped"]))
    st.metric("Sit-Out Would Have Missed Opportunity", str(sit_out_intelligence["metrics"]["sit_out_missed_opportunity"]))
    if sit_out_intelligence["table"].empty:
        st.info("No sit-out-triggered snapshots are available in the selected date range.")
    else:
        st.dataframe(sit_out_intelligence["table"], use_container_width=True, hide_index=True)

    st.markdown("#### Confirmation Intelligence")
    confirmation_tabs = st.tabs(["Status Comparison", "Scenario x Confirmation", "Session x Confirmation"])
    with confirmation_tabs[0]:
        confirmation_breakdown = build_breakdown_dataframe(filtered_trades, "confirmation")
        if confirmation_breakdown.empty:
            st.info("No trade data available for confirmation-status analytics yet.")
        else:
            st.dataframe(confirmation_breakdown, use_container_width=True, hide_index=True)
    with confirmation_tabs[1]:
        scenario_confirmation = build_interaction_dataframe(filtered_trades, "scenario_name", "confirmation_status")
        if scenario_confirmation.empty:
            st.info("No scenario and confirmation interaction data available yet.")
        else:
            st.dataframe(scenario_confirmation, use_container_width=True, hide_index=True)
    with confirmation_tabs[2]:
        session_confirmation = build_interaction_dataframe(filtered_trades, "session", "confirmation_status")
        if session_confirmation.empty:
            st.info("No session and confirmation interaction data available yet.")
        else:
            st.dataframe(session_confirmation, use_container_width=True, hide_index=True)

    render_section_header("V3 Edge Proof", "Expectancy, frequency, and periodic performance for deeper strategy validation.")
    expectancy_tabs = st.tabs(["Expectancy", "Weekly", "Monthly", "Scenario Frequency", "Advanced Breakdowns"])
    with expectancy_tabs[0]:
        expectancy_col1, expectancy_col2 = st.columns(2)
        with expectancy_col1:
            st.markdown("**By Scenario**")
            scenario_expectancy = build_expectancy_dataframe(filtered_trades, "scenario")
            if scenario_expectancy.empty:
                st.info("No trade data available for scenario expectancy yet.")
            else:
                st.dataframe(scenario_expectancy, use_container_width=True, hide_index=True)
            st.markdown("**By Confirmation Status**")
            confirmation_expectancy = build_expectancy_dataframe(filtered_trades, "confirmation")
            if confirmation_expectancy.empty:
                st.info("No trade data available for confirmation expectancy yet.")
            else:
                st.dataframe(confirmation_expectancy, use_container_width=True, hide_index=True)
        with expectancy_col2:
            st.markdown("**By Session**")
            session_expectancy = build_expectancy_dataframe(filtered_trades, "session")
            if session_expectancy.empty:
                st.info("No trade data available for session expectancy yet.")
            else:
                st.dataframe(session_expectancy, use_container_width=True, hide_index=True)
            st.markdown("**By Tag**")
            tag_expectancy = build_expectancy_dataframe(filtered_trades, "tag")
            if tag_expectancy.empty:
                st.info("No trade data available for tag expectancy yet.")
            else:
                st.dataframe(tag_expectancy, use_container_width=True, hide_index=True)
    with expectancy_tabs[1]:
        weekly_performance = build_period_performance_dataframe(filtered_trades, "weekly")
        if weekly_performance.empty:
            st.info("No weekly performance data available yet.")
        else:
            st.dataframe(weekly_performance, use_container_width=True, hide_index=True)
    with expectancy_tabs[2]:
        monthly_performance = build_period_performance_dataframe(filtered_trades, "monthly")
        if monthly_performance.empty:
            st.info("No monthly performance data available yet.")
        else:
            st.dataframe(monthly_performance, use_container_width=True, hide_index=True)
    with expectancy_tabs[3]:
        scenario_frequency = build_scenario_frequency_dataframe(filtered_trades, filtered_snapshots)
        if scenario_frequency.empty:
            st.info("No scenario occurrence data available yet.")
        else:
            st.dataframe(scenario_frequency, use_container_width=True, hide_index=True)
    with expectancy_tabs[4]:
        advanced_col1, advanced_col2 = st.columns(2)
        with advanced_col1:
            scenario_confirmation_pnl = build_interaction_dataframe(filtered_trades, "scenario_name", "confirmation_status")
            st.markdown("**Scenario within Confirmation Status**")
            if scenario_confirmation_pnl.empty:
                st.info("No scenario-within-confirmation data available yet.")
            else:
                st.dataframe(scenario_confirmation_pnl, use_container_width=True, hide_index=True)
        with advanced_col2:
            session_confirmation_pnl = build_interaction_dataframe(filtered_trades, "session", "confirmation_status")
            st.markdown("**Session within Confirmation Status**")
            if session_confirmation_pnl.empty:
                st.info("No session-within-confirmation data available yet.")
            else:
                st.dataframe(session_confirmation_pnl, use_container_width=True, hide_index=True)

    render_section_header("Setup Quality Dashboard", "Spot the strongest and weakest edges in the filtered record set.")
    setup_quality = build_setup_quality_summary(filtered_trades)
    quality_col1, quality_col2, quality_col3 = st.columns(3)
    quality_col1.metric("Highest Expectancy Scenario", setup_quality["highest_expectancy_scenario"])
    quality_col2.metric("Lowest Expectancy Scenario", setup_quality["lowest_expectancy_scenario"])
    quality_col3.metric("Highest Expectancy Confirmation", setup_quality["highest_expectancy_confirmation"])
    quality_col4, quality_col5 = st.columns(2)
    quality_col4.metric("Strongest Session", setup_quality["strongest_session"])
    quality_col5.metric("Weakest Session", setup_quality["weakest_session"])

    history_dataframe = build_trade_history_dataframe(filtered_trades)

    history_col, actions_col = st.columns([2.3, 1], gap="large")
    with history_col:
        with st.container(border=True):
            st.markdown("#### Trade History")
            if history_dataframe.empty:
                st.info("No trades saved yet.")
            else:
                st.dataframe(
                    history_dataframe.drop(columns=["id"], errors="ignore"),
                    use_container_width=True,
                    hide_index=True,
                )

            if not history_dataframe.empty:
                st.markdown("#### Basic Visuals")
                pnl_series = history_dataframe[["date", "pnl"]].copy()
                pnl_series["cumulative_pnl"] = pnl_series["pnl"].cumsum()
                st.line_chart(pnl_series.set_index("date")["cumulative_pnl"])

                result_counts = history_dataframe["result"].value_counts()
                st.bar_chart(result_counts)

    with actions_col:
        with st.container(border=True):
            st.markdown("#### Export")
            st.download_button(
                "Export CSV",
                data=export_trades_csv(filtered_trades),
                file_name="spx_prophet_trade_log.csv",
                mime="text/csv",
                use_container_width=True,
            )
            st.download_button(
                "Export JSON",
                data=export_trades_json(filtered_trades),
                file_name="spx_prophet_trade_log.json",
                mime="application/json",
                use_container_width=True,
            )
            st.download_button(
                "Export Snapshots JSON",
                data=export_snapshots_json(normalized_snapshots),
                file_name="spx_prophet_snapshots.json",
                mime="application/json",
                use_container_width=True,
            )
            st.download_button(
                "Export Settings JSON",
                data=export_settings_json(settings),
                file_name="spx_prophet_settings.json",
                mime="application/json",
                use_container_width=True,
            )
            st.download_button(
                "Export All Data Backup",
                data=json.dumps(
                    {
                        "app": f"{APP_TITLE} {APP_VERSION}",
                        "trades": normalized_trades,
                        "snapshots": normalized_snapshots,
                        "settings": normalize_settings_record(settings),
                    },
                    indent=2,
                ).encode("utf-8"),
                file_name="spx_prophet_all_data_backup.json",
                mime="application/json",
                use_container_width=True,
            )

        with st.container(border=True):
            st.markdown("#### Delete Trade")
            if history_dataframe.empty:
                st.info("No trades available to delete.")
            else:
                delete_options = {
                    f"{row['date']} | {row['session']} | {row['direction']} | {row['scenario']}": row["id"]
                    for _, row in history_dataframe.iterrows()
                }
                delete_label = st.selectbox("Select trade to delete", list(delete_options.keys()))
                if st.button("Delete Selected Trade", type="secondary", use_container_width=True):
                    deleted, error = delete_trade_by_id(delete_options[delete_label])
                    if deleted:
                        st.success("Trade deleted.")
                        if error:
                            st.warning(error)
                        st.rerun()
                    else:
                        st.error(error or "Unable to delete trade.")

        with st.container(border=True):
            st.markdown("#### Daily Snapshots")
            if not normalized_snapshots:
                st.info("No daily snapshots saved yet.")
            else:
                snapshot_table = pd.DataFrame(
                    [
                        {
                            "snapshot_date": snapshot.get("snapshot_date", ""),
                            "captured_at": snapshot.get("captured_at", ""),
                            "scenario": snapshot.get("scenario", {}).get("scenario_name", ""),
                            "sit_out": snapshot.get("sit_out", {}).get("sit_out", False),
                            "confirmation": snapshot.get("confirmation", {}).get("status", ""),
                            "traded": snapshot.get("review", {}).get("traded", False),
                        }
                        for snapshot in reversed(normalized_snapshots)
                    ]
                )
                st.dataframe(snapshot_table, use_container_width=True, hide_index=True)
                snapshot_review_options = {
                    f"{snapshot['snapshot_date']} | {snapshot['scenario'].get('scenario_name', 'Snapshot')}": snapshot
                    for snapshot in reversed(normalized_snapshots)
                }
                selected_snapshot_label = st.selectbox("Select snapshot to review", list(snapshot_review_options.keys()))
                selected_snapshot = snapshot_review_options[selected_snapshot_label]
                with st.expander("Review Selected Snapshot", expanded=False):
                    with st.form("snapshot_review_form"):
                        traded = st.checkbox("Traded", value=selected_snapshot["review"]["traded"])
                        primary_setup_worked = st.checkbox("Primary setup worked", value=selected_snapshot["review"]["primary_setup_worked"])
                        alternate_setup_worked = st.checkbox("Alternate setup worked", value=selected_snapshot["review"]["alternate_setup_worked"])
                        sit_out_would_have_helped = st.checkbox("Sit-out would have helped", value=selected_snapshot["review"]["sit_out_would_have_helped"])
                        best_move_of_day = st.text_input("Best move of day", value=selected_snapshot["review"]["best_move_of_day"])
                        snapshot_notes = st.text_area("Snapshot notes", value=selected_snapshot["review"]["notes"], height=120)
                        update_snapshot_submitted = st.form_submit_button("Save Snapshot Review", use_container_width=True)
                        if update_snapshot_submitted:
                            snapshot_saved, snapshot_message = update_snapshot_review(
                                selected_snapshot["id"],
                                {
                                    "traded": traded,
                                    "primary_setup_worked": primary_setup_worked,
                                    "alternate_setup_worked": alternate_setup_worked,
                                    "sit_out_would_have_helped": sit_out_would_have_helped,
                                    "best_move_of_day": best_move_of_day,
                                    "notes": snapshot_notes,
                                },
                            )
                            if snapshot_saved:
                                st.success("Snapshot review saved.")
                                if snapshot_message:
                                    st.warning(snapshot_message)
                                st.rerun()
                            else:
                                st.error(snapshot_message or "Unable to save snapshot review.")
                with st.expander("Selected Snapshot Payload", expanded=False):
                    st.json(selected_snapshot, expanded=False)

        with st.container(border=True):
            st.markdown("#### Data Health")
            st.write(f"Trades loaded: {data_health['trade_count']}")
            st.write(f"Snapshots loaded: {data_health['snapshot_count']}")
            st.write(f"Incomplete trades: {data_health['incomplete_trade_count']}")
            st.write(f"Incomplete snapshots: {data_health['incomplete_snapshot_count']}")
            st.write(f"Duplicate trade warnings: {data_health['duplicate_trade_count']}")
            st.write(f"Preview-only P&L records: {data_health['preview_only_pnl_count']}")
            if data_health["malformed_recoveries"]:
                st.warning("Malformed stores were recovered during load.")
                for message in data_health["malformed_recoveries"]:
                    st.write(f"- {message}")
            else:
                st.success("No malformed store recovery was needed on this run.")


def main() -> None:
    """Run the current Streamlit integration."""

    render_startup_diagnostics()
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    initialize_app_state()
    inject_app_styles()
    settings, settings_message = load_settings()
    st.title(APP_TITLE)
    if settings_message:
        st.warning(settings_message)

    inputs = get_inputs(settings)
    validation = validate_app_inputs(inputs)
    for warning in validation["warnings"]:
        st.warning(warning)
    if validation["errors"]:
        for error in validation["errors"]:
            st.error(error)
        st.stop()

    effective_offset, effective_offset_source = resolve_effective_offset(inputs)

    persisted_settings = {
        "es_spx_offset": inputs["es_spx_offset"],
        "news_day": inputs["news_day"],
        "preferred_checkpoint": settings.get("preferred_checkpoint", DEFAULT_SETTINGS["preferred_checkpoint"]),
        "data_mode": inputs["data_mode"],
        "manual_price_space": inputs["manual_price_space"],
        "options_provider": inputs["options_provider"],
        "options_mode_enabled": inputs["options_mode_enabled"],
    }
    settings_saved, settings_save_error = save_settings(persisted_settings)
    if not settings_saved and settings_save_error:
        st.warning(settings_save_error)

    options_provider = load_options_provider(
        provider_name=persisted_settings["options_provider"],
        options_mode_enabled=persisted_settings["options_mode_enabled"],
        secrets=st.secrets,
        environment=os.environ,
    )
    options_provider_status = options_provider.get_status().to_dict()

    anchor_bundle, es_candles, data_error, fetch_diagnostics = resolve_anchor_bundle(inputs, effective_offset)

    if data_error:
        if fetch_diagnostics and fetch_diagnostics.get("anchor_build_error"):
            st.warning("Auto-fetch returned ES candles, but the app could not build anchors. Manual anchors are being used.")
        else:
            st.warning(
                "Auto-fetch failed because Yahoo returned no usable intraday ES=F data. Manual anchors are being used."
            )

    nine_am_target = at_central(inputs["next_trading_date"], 9, 0)
    try:
        projected_es_9 = project_six_lines(anchor_bundle["anchors"], nine_am_target)
        projected_spx_9 = convert_projected_lines(projected_es_9, effective_offset, "spx")
    except Exception as exc:
        st.error(f"Unable to project line structure for the selected inputs: {exc}")
        st.stop()

    overnight_high, overnight_low = build_override_inputs(inputs, projected_spx_9)
    override_result = apply_overnight_pivot_overrides(
        projected_spx_9,
        overnight_high=overnight_high,
        overnight_low=overnight_low,
    )
    final_projected_lines = override_result["projected_lines"]
    final_projected_lines_es = convert_projected_lines(final_projected_lines, effective_offset, "es")
    line_values_spx = {name: details["projected_price"] for name, details in final_projected_lines.items()}

    spx_830_candle = None
    try:
        spx_candles = fetch_spx_confirmation_candles(inputs["next_trading_date"])
        spx_830_candle = extract_spx_830_candle(spx_candles, inputs["next_trading_date"])
    except Exception as exc:
        st.warning(f"SPX confirmation data fetch failed: {exc}")

    signal_package: dict[str, Any] | None = None
    if is_valid_price_input(inputs["current_spx_price"]):
        try:
            seed_scenario = evaluate_trading_scenario(
                current_price=inputs["current_spx_price"],
                line_values=line_values_spx,
                open_price=inputs["open_reference"],
                confirmation_confirmed=False,
            )
            primary_play = seed_scenario["primary_play"]
            confirmation = evaluate_830_confirmation(
                spx_830_candle,
                primary_play["entry"]["price"] if primary_play else inputs["current_spx_price"],
                primary_play["direction"] if primary_play else "CALL",
            )
            signal_package = build_signal_package(
                current_price=inputs["current_spx_price"],
                line_values=line_values_spx,
                confirmation=confirmation,
                news_day=inputs["news_day"],
                current_time=current_central_time(),
                open_price=inputs["open_reference"],
            )
        except Exception as exc:
            st.warning(f"Tab 1 scenario logic could not be built from the current inputs: {exc}")
            confirmation = build_unavailable_confirmation("Scenario unavailable because the current SPX setup could not be evaluated.")
    else:
        confirmation = build_unavailable_confirmation("Scenario unavailable because current SPX price is missing or invalid.")

    try:
        checkpoint_views = build_evening_checkpoint_views(
            anchor_bundle=anchor_bundle,
            next_trading_date=inputs["next_trading_date"],
            es_spx_offset=effective_offset,
            overnight_high=overnight_high,
            overnight_low=overnight_low,
        )
    except Exception as exc:
        st.error(f"Unable to build Asian session checkpoints: {exc}")
        checkpoint_views = []

    tab_signal, tab_asian, tab_trade_log = st.tabs(["SIGNAL & LEVELS", "ASIAN SESSION", "TRADE LOG"])

    with tab_signal:
        render_tab1_hero(
            signal_package=signal_package,
            current_spx_price=inputs["current_spx_price"],
            current_es_price=inputs["current_es_price"],
            effective_offset=effective_offset,
        )
        if not inputs.get("live_spx_available", True) and not is_valid_price_input(inputs["current_spx_price"]):
            st.warning("Live SPX price is unavailable. Enter the 9:00 AM SPX price manually before using the scenario engine.")
        if not inputs.get("live_es_available", True) and not is_valid_price_input(inputs["current_es_price"]):
            st.warning("Live ES price is unavailable. Enter the current ES price manually before relying on futures-relative displays.")
        if signal_package is not None:
            render_trade_decision_summary(signal_package, final_projected_lines)
        if signal_package is None:
            st.warning("Current SPX price is unavailable or invalid. Enter it manually to enable Tab 1 trade decisions. Projected structure remains available below.")
        action_col1, action_col2 = st.columns(2)
        with action_col1:
            primary_play = signal_package["scenario"].get("primary_play") if signal_package else None
            if primary_play is None:
                st.warning("No primary play is available to hand off into the Trade Log.")
            elif st.button("Prefill Trade Log from Primary Play", use_container_width=True):
                set_trade_form_prefill(build_tab1_trade_prefill(signal_package))
                st.success("Trade Log prefilled from Tab 1. Open Tab 3 to review or save.")
        with action_col2:
            if st.button("Save Daily Snapshot", use_container_width=True, disabled=signal_package is None):
                snapshot_payload = build_daily_snapshot(
                    next_trading_date=inputs["next_trading_date"],
                    projected_lines=final_projected_lines,
                    scenario=signal_package["scenario"],
                    sit_out=signal_package["sit_out"],
                    confirmation=confirmation,
                )
                snapshot_saved, snapshot_error = append_snapshot(snapshot_payload)
                if snapshot_saved:
                    st.success("Daily snapshot saved.")
                    if snapshot_error:
                        st.warning(snapshot_error)
                else:
                    st.error(snapshot_error or "Unable to save daily snapshot.")

        option_lookup_request = None
        if signal_package is not None and signal_package["scenario"].get("primary_play") is not None:
            primary_play = signal_package["scenario"]["primary_play"]
            option_lookup_request = build_option_lookup_request(
                session="NY Options",
                direction=primary_play["direction"],
                strike=int(primary_play["strike"]),
                trade_date=inputs["next_trading_date"],
                scenario_name=signal_package["scenario"]["scenario_name"],
            )
        decision_col1, decision_col2 = st.columns(2, gap="large")
        if signal_package is not None:
            with decision_col1:
                render_play_card("Primary Trade", signal_package["scenario"]["primary_play"], final_projected_lines)
            with decision_col2:
                render_play_card("Alternate Trade", signal_package["scenario"]["alternate_play"], final_projected_lines)

        render_spatial_ladder(
            final_projected_lines,
            inputs["current_spx_price"] if is_valid_price_input(inputs["current_spx_price"]) else None,
            price_space_label="SPX",
        )

        if signal_package is not None:
            with st.expander("Confirmation", expanded=False):
                render_confirmation_card(
                    confirmation,
                    resolve_play_display_values(signal_package["scenario"]["primary_play"], final_projected_lines),
                )
            with st.expander("Structure", expanded=False):
                render_scenario_section(signal_package["scenario"])
                render_sit_out_section(signal_package["sit_out"])
                render_key_levels_card(final_projected_lines, inputs["current_spx_price"], effective_offset)
                render_six_lines_panel(projected_spx_9, final_projected_lines, override_result["decisions"])
                render_projection_verification(
                    anchor_bundle,
                    final_projected_lines,
                    final_projected_lines_es,
                    final_projected_lines,
                    "SPX",
                )
        else:
            with st.expander("Structure", expanded=False):
                render_key_levels_card(final_projected_lines, inputs["current_spx_price"], effective_offset)
                render_six_lines_panel(projected_spx_9, final_projected_lines, override_result["decisions"])
                render_projection_verification(
                    anchor_bundle,
                    final_projected_lines,
                    final_projected_lines_es,
                    final_projected_lines,
                    "SPX",
                )
    with tab_asian:
        st.markdown(
            """
            <div class="spx-hero">
                <div class="spx-hero-top">
                    <div>
                        <div class="spx-hero-kicker">Asian Session Console</div>
                        <div class="spx-hero-title">Evening ES Monitoring</div>
                        <div class="spx-hero-subtitle">
                            Compare checkpoints quickly, monitor delayed touches, and use the line-location engine as a reference framework rather than a forced timing model.
                        </div>
                    </div>
                    <div class="spx-hero-status">
                        <div class="spx-hero-status-label">Framework</div>
                        <div class="spx-status-chip good"><span>◌</span><span>Observation First</span></div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if not checkpoint_views:
            st.warning("Checkpoint views are unavailable for the current inputs.")
        else:
            checkpoint_labels = [checkpoint["label"] for checkpoint in checkpoint_views]
            selected_label = st.selectbox(
                "Reference checkpoint for current ES location",
                checkpoint_labels,
                index=safe_option_index(checkpoint_labels, settings.get("preferred_checkpoint", DEFAULT_SETTINGS["preferred_checkpoint"])),
            )
            if persisted_settings["preferred_checkpoint"] != selected_label:
                persisted_settings["preferred_checkpoint"] = selected_label
                checkpoint_settings_saved, checkpoint_settings_error = save_settings(persisted_settings)
                if not checkpoint_settings_saved and checkpoint_settings_error:
                    st.warning(checkpoint_settings_error)
            selected_checkpoint = next(checkpoint for checkpoint in checkpoint_views if checkpoint["label"] == selected_label)

            if is_valid_price_input(inputs["current_es_price"]):
                reference_scenario = render_evening_location_panel(inputs["current_es_price"], selected_checkpoint)
                if reference_scenario.get("primary_play") is None:
                    st.warning("No Tab 2 reference play is available to hand off into the Trade Log at this checkpoint.")
                elif st.button("Prefill Trade Log from Evening Framework", use_container_width=True):
                    set_trade_form_prefill(build_tab2_trade_prefill(selected_checkpoint, inputs["current_es_price"]))
                    st.success("Trade Log prefilled from Tab 2. Open Tab 3 to review or save.")
            else:
                st.info("Enter a valid current ES price to enable the Tab 2 reference framework and trade-log handoff.")
            render_evening_decision_framework()
            render_evening_line_ladder(selected_checkpoint)
            with st.expander("Checkpoint Levels", expanded=False):
                render_checkpoint_views(checkpoint_views)

    with tab_trade_log:
        render_trade_log_tab(signal_package, persisted_settings, settings_message=settings_message)


if __name__ == "__main__":
    main()
