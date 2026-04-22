"""Phase 3 Streamlit integration for SPX Prophet."""

from __future__ import annotations

import json
import os
from datetime import date, time, timedelta
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
    from options_provider import (
        PROVIDER_NAMES,
        TASTYTRADE_AUTH_CODE_KEYS,
        TASTYTRADE_CLIENT_ID_KEYS,
        TASTYTRADE_CLIENT_SECRET_KEYS,
        TASTYTRADE_REDIRECT_URI_KEYS,
        TASTYTRADE_REFRESH_TOKEN_KEYS,
        TASTYTRADE_TEST_KEYS,
        OptionLookupRequest,
        load_options_provider,
    )
    OPTIONS_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - deployment environment issue
    PROVIDER_NAMES = ["none"]
    TASTYTRADE_CLIENT_ID_KEYS = ["TASTYTRADE_CLIENT_ID", "tastytrade_client_id"]
    TASTYTRADE_CLIENT_SECRET_KEYS = ["TASTYTRADE_CLIENT_SECRET", "tastytrade_client_secret"]
    TASTYTRADE_REDIRECT_URI_KEYS = ["TASTYTRADE_REDIRECT_URI", "tastytrade_redirect_uri"]
    TASTYTRADE_REFRESH_TOKEN_KEYS = ["TASTYTRADE_REFRESH_TOKEN", "tastytrade_refresh_token"]
    TASTYTRADE_AUTH_CODE_KEYS = ["TASTYTRADE_AUTH_CODE", "tastytrade_auth_code"]
    TASTYTRADE_TEST_KEYS = ["TASTYTRADE_IS_TEST", "tastytrade_is_test"]

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
DEFAULT_OPTIONS_PROVIDER = "tastytrade" if "tastytrade" in PROVIDER_NAMES else "none"

DEFAULT_SETTINGS = {
    "es_spx_offset": 20.0,
    "news_day": False,
    "preferred_checkpoint": "6:00 PM CT",
    "data_mode": "Auto-fetch",
    "visibility_mode": "Production Mode",
    "manual_price_space": "SPX",
    "options_provider": DEFAULT_OPTIONS_PROVIDER,
    "options_mode_enabled": DEFAULT_OPTIONS_PROVIDER != "none",
    "session_plan_lock_cutoff": "8:25 AM CT",
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


def resolve_trade_direction_display(direction: Any) -> dict[str, str]:
    """Map option mechanics into operator-first directional language."""

    normalized = normalize_trade_direction(direction)
    if normalized in {"CALL", "LONG"}:
        return {
            "bias": "BULLISH",
            "arrow": "↑",
            "setup": "BULLISH SETUP",
            "compact": "↑ Bullish",
            "tone": "good",
        }
    if normalized in {"PUT", "SHORT"}:
        return {
            "bias": "BEARISH",
            "arrow": "↓",
            "setup": "BEARISH SETUP",
            "compact": "↓ Bearish",
            "tone": "bad",
        }
    return {
        "bias": "NEUTRAL",
        "arrow": "→",
        "setup": "NEUTRAL SETUP",
        "compact": "→ Neutral",
        "tone": "neutral",
    }


def resolve_trade_execution_display(direction: Any, decision: Any) -> str:
    """Render execution separately from directional bias."""

    normalized = normalize_trade_direction(direction)
    decision_text = str(decision or "").strip().upper()

    if decision_text == "NO TRADE":
        return "No Trade"

    execution = {
        "CALL": "Buy Call",
        "PUT": "Buy Put",
        "LONG": "Long",
        "SHORT": "Short",
    }.get(normalized, "Execution Pending")

    if decision_text == "CONDITIONAL BUY":
        return f"{execution} (Conditional)"
    if decision_text == "STRONG BUY":
        return f"{execution} (Ready)"
    return execution


def resolve_presentation_state(decision: Any, bias_label: str) -> dict[str, str]:
    """Return display-first state/bias wording without changing logic."""

    decision_text = str(decision or "").strip().upper()
    if decision_text == "NO TRADE":
        return {
            "headline": "NO TRADE",
            "secondary": f"Market bias: {bias_label.title()}",
        }
    if decision_text == "STRONG BUY":
        return {
            "headline": f"{bias_label} SETUP",
            "secondary": "Actionable now",
        }
    if decision_text == "CONDITIONAL BUY":
        return {
            "headline": f"{bias_label} SETUP",
            "secondary": "Conditional entry",
        }
    return {
        "headline": f"{bias_label} SETUP",
        "secondary": "Monitoring",
    }


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
    if merged.get("visibility_mode") == "Developer Mode":
        merged["visibility_mode"] = "Edge Lab"
    if merged.get("visibility_mode") not in ["Production Mode", "Edge Lab"]:
        merged["visibility_mode"] = DEFAULT_SETTINGS["visibility_mode"]
    if merged.get("manual_price_space") not in ["SPX", "ES"]:
        merged["manual_price_space"] = DEFAULT_SETTINGS["manual_price_space"]
    if merged.get("options_provider") not in PROVIDER_NAMES:
        merged["options_provider"] = DEFAULT_SETTINGS["options_provider"]
    if merged.get("session_plan_lock_cutoff") not in ["8:15 AM CT", "8:20 AM CT", "8:25 AM CT", "8:29 AM CT"]:
        merged["session_plan_lock_cutoff"] = DEFAULT_SETTINGS["session_plan_lock_cutoff"]
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
    st.session_state.setdefault("live_state_store", {})


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

    if not inputs.get("historical_mode", False):
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
        enriched["session_extremes_found"] = True

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
            --spx-font-sans: "Outfit", "Segoe UI", sans-serif;
            --spx-font-mono: "JetBrains Mono", monospace;
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
        html, body, .stApp, .main .block-container {
            font-family: var(--spx-font-sans);
        }
        h1, h2, h3, h4 {
            font-family: var(--spx-font-sans) !important;
            letter-spacing: 0.01em;
            color: var(--spx-text);
        }
        p, li, label, div[data-testid="stMarkdownContainer"] {
            color: var(--spx-text);
            line-height: 1.5;
        }
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] input,
        [data-testid="stSidebar"] textarea,
        [data-testid="stSidebar"] button,
        [data-testid="stSidebar"] [data-baseweb="select"],
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"],
        [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
            font-family: var(--spx-font-sans) !important;
        }
        [data-testid="stSidebar"] .block-container {
            padding-top: 0.7rem;
        }
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
            font-size: 0.88rem !important;
            line-height: 1.35 !important;
            font-weight: 500 !important;
        }
        [data-testid="stSidebar"] .stSelectbox,
        [data-testid="stSidebar"] .stDateInput,
        [data-testid="stSidebar"] .stNumberInput,
        [data-testid="stSidebar"] .stTextInput,
        [data-testid="stSidebar"] .stRadio,
        [data-testid="stSidebar"] .stCheckbox,
        [data-testid="stSidebar"] .stExpander {
            margin-bottom: 0.35rem !important;
        }
        [data-testid="stMetric"] {
            background: linear-gradient(180deg, rgba(255,255,255,0.022), rgba(255,255,255,0.01));
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 16px;
            padding: 0.65rem 0.8rem;
            box-shadow: none;
        }
        [data-testid="stMetricLabel"] p {
            color: var(--spx-muted) !important;
            font-size: 0.68rem !important;
            font-weight: 600 !important;
            letter-spacing: 0.08em !important;
            text-transform: uppercase;
        }
        [data-testid="stMetricValue"] {
            font-family: var(--spx-font-mono) !important;
            font-size: 1.08rem !important;
            font-weight: 650 !important;
            color: #f8fbff !important;
        }
        .stCaption {
            color: var(--spx-muted) !important;
            font-size: 0.78rem !important;
            line-height: 1.35 !important;
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
            font-weight: 700;
            letter-spacing: 0.16em;
            text-transform: uppercase;
            color: var(--spx-muted);
            margin-bottom: 0.35rem;
        }
        .spx-section-subtitle {
            color: #d3deef;
            font-size: 0.92rem;
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
            font-weight: 700;
            margin-bottom: 0.45rem;
        }
        .spx-summary-body {
            color: #f4fbff;
            font-size: 0.96rem;
            line-height: 1.65;
            font-weight: 500;
        }
        .spx-hero {
            position: relative;
            overflow: hidden;
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 28px;
            padding: 1.1rem 1.2rem 0.95rem 1.2rem;
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
            font-family: var(--spx-font-sans);
            font-size: 1.92rem;
            font-weight: 800;
            line-height: 1.05;
            color: #f8fbff;
            margin: 0 0 0.35rem 0;
        }
        .spx-hero-subtitle {
            color: #bdd0e8;
            font-size: 0.94rem;
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
            font-size: 0.7rem;
            margin-bottom: 0.35rem;
            font-weight: 700;
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
        .spx-status-chip.warn {
            background: linear-gradient(135deg, rgba(255, 212, 64, 0.18), rgba(255, 212, 64, 0.06));
            border-color: rgba(255,212,64,0.28);
        }
        .spx-status-chip.bad {
            background: linear-gradient(135deg, rgba(255, 23, 68, 0.18), rgba(255, 23, 68, 0.06));
            border-color: rgba(255,23,68,0.28);
            animation: spxPulseAlert 2.8s ease-in-out infinite;
        }
        .spx-hero-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.75rem;
        }
        .spx-hero-stat {
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 20px;
            padding: 0.82rem 0.9rem;
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
            font-size: 1.16rem;
            font-weight: 700;
            color: #f8fbff;
            line-height: 1.2;
        }
        .spx-hero-stat-note {
            color: var(--spx-muted);
            font-size: 0.8rem;
            margin-top: 0.3rem;
        }
        .spx-decision-action {
            font-family: var(--spx-font-sans);
            font-size: 2.2rem;
            font-weight: 850;
            letter-spacing: 0.01em;
            line-height: 1;
            color: #f8fbff;
            margin: 0.05rem 0 0.45rem 0;
        }
        .spx-decision-meta {
            display: flex;
            flex-wrap: wrap;
            gap: 0.38rem;
            margin-bottom: 0.2rem;
        }
        .spx-decision-strip {
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 18px;
            padding: 0.72rem 0.88rem;
            background: rgba(255,255,255,0.03);
        }
        .spx-decision-strip-label {
            color: var(--spx-muted);
            text-transform: uppercase;
            letter-spacing: 0.12em;
            font-size: 0.68rem;
            font-weight: 700;
            margin-bottom: 0.18rem;
        }
        .spx-decision-strip-value {
            color: #f8fbff;
            font-family: var(--spx-font-mono);
            font-size: 1.22rem;
            font-weight: 760;
            line-height: 1.15;
        }
        .spx-best-contract {
            border: 1px solid rgba(0,212,255,0.16);
            background: linear-gradient(135deg, rgba(0,212,255,0.10), rgba(255,255,255,0.02));
            border-radius: 16px;
            padding: 0.75rem 0.85rem;
            margin-bottom: 0.7rem;
        }
        .spx-best-contract-title {
            color: #7fe7ff;
            text-transform: uppercase;
            letter-spacing: 0.14em;
            font-size: 0.68rem;
            font-weight: 800;
            margin-bottom: 0.28rem;
        }
        .spx-best-contract-symbol {
            color: #f8fbff;
            font-family: var(--spx-font-mono);
            font-size: 0.98rem;
            font-weight: 760;
            margin-bottom: 0.22rem;
        }
        .spx-best-contract-meta {
            color: #dce8f8;
            font-size: 0.82rem;
            line-height: 1.45;
        }
        .spx-banner {
            position: relative;
            overflow: hidden;
            border-radius: 22px;
            padding: 0.9rem 1rem;
            margin-bottom: 0.8rem;
            border: 1px solid rgba(255, 255, 255, 0.08);
            background:
                radial-gradient(circle at top left, rgba(0,212,255,0.11), transparent 24%),
                linear-gradient(135deg, rgba(18, 26, 42, 0.96), rgba(9, 14, 24, 0.94));
            box-shadow: 0 16px 42px rgba(0,0,0,0.26);
            animation: spxFadeUp 0.45s ease both;
        }
        .spx-banner-name {
            font-family: var(--spx-font-sans);
            font-size: 1.14rem;
            font-weight: 760;
            color: #f8fbff;
            margin-bottom: 0.22rem;
        }
        .spx-banner-meta {
            color: var(--spx-muted);
            font-size: 0.78rem;
            margin-bottom: 0.22rem;
        }
        .spx-banner-text {
            color: #d8e1ee;
            font-size: 0.88rem;
            line-height: 1.48;
        }
        .spx-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.28rem 0.62rem;
            border-radius: 999px;
            font-size: 0.7rem;
            font-weight: 700;
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
        .spx-play-shell {
            position: relative;
            overflow: hidden;
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 22px;
            padding: 0.95rem 1rem 1rem 1rem;
            background:
                radial-gradient(circle at top right, rgba(0,212,255,0.08), transparent 30%),
                linear-gradient(180deg, rgba(12,18,31,0.97), rgba(8,12,22,0.96));
            box-shadow: 0 14px 30px rgba(0,0,0,0.18);
            margin-bottom: 0.8rem;
        }
        .spx-play-shell.alternate {
            opacity: 0.9;
            border-color: rgba(255,255,255,0.06);
            background:
                radial-gradient(circle at top right, rgba(255,255,255,0.05), transparent 28%),
                linear-gradient(180deg, rgba(10,14,24,0.93), rgba(8,11,20,0.94));
        }
        .spx-play-topline {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 0.8rem;
            margin-bottom: 0.65rem;
        }
        .spx-play-title {
            font-size: 0.92rem;
            font-weight: 740;
            color: #e3edf9;
        }
        .spx-play-title.alt {
            font-size: 0.84rem;
            color: #bfd0e2;
        }
        .spx-play-topline-note {
            color: var(--spx-muted);
            font-size: 0.74rem;
        }
        .spx-decision-banner {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 0.75rem;
            padding: 0.78rem 0.88rem;
            border-radius: 18px;
            border: 1px solid rgba(255,255,255,0.08);
            margin-bottom: 0.78rem;
        }
        .spx-decision-banner.enter {
            background: linear-gradient(135deg, rgba(0,230,118,0.18), rgba(0,230,118,0.08));
            border-color: rgba(0,230,118,0.28);
            box-shadow: 0 0 20px rgba(0,230,118,0.08);
        }
        .spx-decision-banner.wait {
            background: linear-gradient(135deg, rgba(0,212,255,0.16), rgba(0,212,255,0.08));
            border-color: rgba(0,212,255,0.24);
            box-shadow: 0 0 20px rgba(0,212,255,0.07);
        }
        .spx-decision-banner.caution {
            background: linear-gradient(135deg, rgba(255,193,7,0.18), rgba(255,193,7,0.08));
            border-color: rgba(255,193,7,0.28);
            box-shadow: 0 0 20px rgba(255,193,7,0.08);
        }
        .spx-decision-banner.skip {
            background: linear-gradient(135deg, rgba(255,82,82,0.22), rgba(255,82,82,0.09));
            border-color: rgba(255,82,82,0.3);
            box-shadow: 0 0 20px rgba(255,82,82,0.08);
        }
        .spx-decision-main {
            font-family: var(--spx-font-sans);
            font-size: 1.22rem;
            font-weight: 830;
            color: #f8fbff;
            letter-spacing: 0.01em;
        }
        .spx-decision-sub {
            color: #d1e0f1;
            font-size: 0.8rem;
            margin-top: 0.16rem;
            line-height: 1.35;
        }
        .spx-play-context {
            text-align: right;
            min-width: 92px;
        }
        .spx-play-context-label {
            color: var(--spx-muted);
            font-size: 0.64rem;
            text-transform: uppercase;
            letter-spacing: 0.12em;
        }
        .spx-play-context-value {
            margin-top: 0.14rem;
            font-family: var(--spx-font-mono);
            font-size: 1.08rem;
            font-weight: 780;
            color: #f8fbff;
        }
        .spx-entry-grid {
            display: grid;
            grid-template-columns: 1.15fr 0.95fr;
            gap: 0.7rem;
            margin-bottom: 0.78rem;
        }
        .spx-entry-card {
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 16px;
            padding: 0.72rem 0.8rem;
            background: rgba(255,255,255,0.028);
        }
        .spx-entry-card-label {
            color: var(--spx-muted);
            font-size: 0.64rem;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            margin-bottom: 0.2rem;
        }
        .spx-entry-card-value {
            font-family: var(--spx-font-mono);
            font-size: 1.18rem;
            font-weight: 820;
            color: #f8fbff;
        }
        .spx-entry-card-note {
            color: #bad0e5;
            font-size: 0.78rem;
            margin-top: 0.2rem;
        }
        .spx-plan-box {
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 16px;
            padding: 0.72rem 0.82rem;
            background: rgba(255,255,255,0.028);
            margin-bottom: 0.78rem;
        }
        .spx-plan-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 0.6rem;
            margin-bottom: 0.48rem;
        }
        .spx-plan-title {
            color: #f5f9ff;
            font-size: 0.74rem;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            font-weight: 780;
        }
        .spx-plan-metric {
            color: #dce8f8;
            font-family: var(--spx-font-mono);
            font-size: 0.86rem;
            font-weight: 720;
        }
        .spx-drift-track {
            width: 100%;
            height: 9px;
            border-radius: 999px;
            background: rgba(255,255,255,0.07);
            overflow: hidden;
            margin-bottom: 0.46rem;
        }
        .spx-drift-fill {
            height: 100%;
            border-radius: 999px;
        }
        .spx-drift-fill.good { background: linear-gradient(90deg, #00e676, #1de9b6); }
        .spx-drift-fill.warn { background: linear-gradient(90deg, #ffd54f, #ffb300); }
        .spx-drift-fill.bad { background: linear-gradient(90deg, #ff6e6e, #ff5252); }
        .spx-entry-compare {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.55rem;
        }
        .spx-entry-compare-block {
            border-radius: 14px;
            padding: 0.56rem 0.6rem;
            background: rgba(255,255,255,0.03);
        }
        .spx-entry-compare-label {
            color: var(--spx-muted);
            font-size: 0.63rem;
            text-transform: uppercase;
            letter-spacing: 0.12em;
        }
        .spx-entry-compare-value {
            margin-top: 0.14rem;
            font-family: var(--spx-font-mono);
            font-size: 0.98rem;
            font-weight: 760;
        }
        .spx-entry-compare-value.planned { color: #9cb2cc; }
        .spx-entry-compare-value.live { color: #86eeff; }
        .spx-badge-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.42rem;
            margin-bottom: 0.78rem;
        }
        .spx-chip {
            display: inline-flex;
            align-items: center;
            padding: 0.28rem 0.56rem;
            border-radius: 999px;
            border: 1px solid rgba(255,255,255,0.08);
            font-size: 0.71rem;
            font-weight: 740;
            letter-spacing: 0.03em;
            color: #edf5ff;
            background: rgba(255,255,255,0.04);
        }
        .spx-chip.green { background: rgba(0,230,118,0.14); border-color: rgba(0,230,118,0.24); }
        .spx-chip.blue { background: rgba(0,212,255,0.14); border-color: rgba(0,212,255,0.24); }
        .spx-chip.yellow { background: rgba(255,193,7,0.14); border-color: rgba(255,193,7,0.25); color: #fff2bf; }
        .spx-chip.red { background: rgba(255,82,82,0.14); border-color: rgba(255,82,82,0.24); color: #ffd0d0; }
        .spx-chip.gray { background: rgba(255,255,255,0.05); border-color: rgba(255,255,255,0.08); color: #d1deef; }
        .spx-metric-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.62rem;
            margin-bottom: 0.74rem;
        }
        .spx-metric-grid.secondary {
            grid-template-columns: repeat(4, minmax(0, 1fr));
        }
        .spx-metric-grid.tertiary {
            grid-template-columns: repeat(3, minmax(0, 1fr));
        }
        .spx-metric-block {
            border-radius: 14px;
            padding: 0.58rem 0.64rem;
            background: rgba(255,255,255,0.026);
            border: 1px solid rgba(255,255,255,0.06);
        }
        .spx-metric-block.layer1 .spx-metric-value {
            font-size: 1.16rem;
            font-weight: 820;
            color: #f8fbff;
        }
        .spx-metric-block.layer2 .spx-metric-value {
            font-size: 0.96rem;
            font-weight: 740;
            color: #e4edf8;
        }
        .spx-metric-block.layer3 {
            opacity: 0.74;
        }
        .spx-metric-block.muted {
            opacity: 0.5;
        }
        .spx-metric-label {
            color: var(--spx-muted);
            font-size: 0.63rem;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            margin-bottom: 0.16rem;
        }
        .spx-metric-value {
            font-family: var(--spx-font-mono);
        }
        .spx-risk-note {
            display: flex;
            align-items: center;
            gap: 0.45rem;
            border-radius: 14px;
            padding: 0.55rem 0.68rem;
            background: rgba(255,82,82,0.12);
            border: 1px solid rgba(255,82,82,0.22);
            color: #ffd4d4;
            font-size: 0.8rem;
            margin-bottom: 0.75rem;
        }
        .spx-risk-note-icon {
            font-size: 0.95rem;
            font-weight: 800;
        }
        .spx-play-note, .spx-muted {
            color: var(--spx-muted);
            font-size: 0.82rem;
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
            font-family: var(--spx-font-sans);
            font-size: 1.02rem;
            font-weight: 650;
            color: #f8fbff;
            line-height: 1.2;
        }
        .spx-card-subtitle {
            color: var(--spx-muted);
            font-size: 0.8rem;
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
            font-size: 0.7rem;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            font-weight: 700;
            margin-bottom: 0.25rem;
        }
        .spx-card-stat-value {
            color: #f8fbff;
            font-size: 0.98rem;
            font-family: var(--spx-font-mono);
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
            font-family: var(--spx-font-mono);
            font-weight: 700;
        }
        .spx-inline-status {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            align-items: center;
            margin-bottom: 0.8rem;
            color: #dfe8f6;
            font-size: 0.86rem;
        }
        .spx-inline-summary {
            color: #eef5ff;
            font-size: 0.9rem;
            font-weight: 600;
            line-height: 1.45;
            margin-bottom: 0.55rem;
        }
        .spx-inline-summary .mono {
            font-family: var(--spx-font-mono);
            font-weight: 700;
            color: #f8fbff;
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
            font-family: var(--spx-font-mono);
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
            font-family: var(--spx-font-sans) !important;
            font-weight: 650;
            letter-spacing: 0.04em;
            border-radius: 12px 12px 0 0;
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, rgba(10,15,25,0.98), rgba(6,10,18,0.98));
            border-right: 1px solid rgba(255,255,255,0.06);
        }
        [data-testid="stSidebar"] .block-container {
            padding-top: 1rem;
            padding-bottom: 1.1rem;
        }
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] div[data-testid="stMarkdownContainer"] {
            font-size: 0.86rem !important;
            line-height: 1.4;
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


def status_chip_class(status_label: str) -> tuple[str, str]:
    """Map a final status label to the existing hero chip styles."""

    normalized = str(status_label or "").upper()
    if normalized == "ELIGIBLE":
        return "good", "●"
    if normalized == "ELIGIBLE WITH CAUTION":
        return "warn", "!"
    return "bad", "!"


def final_status_to_action(final_status: str | None, signal_package: dict[str, Any] | None) -> str:
    """Map internal final status to one operator-facing action label."""

    if signal_package is None:
        return "WAIT"

    normalized = str(final_status or "").upper()
    if normalized == "ELIGIBLE":
        return "ENTER NOW"
    if normalized == "ELIGIBLE WITH CAUTION":
        return "ENTER WITH CAUTION"
    return "SKIP TRADE"


def classify_entry_timing(current_spx: float | None, entry_spx: float | None) -> dict[str, Any]:
    """Classify timing from current SPX distance to entry."""

    if current_spx is None or entry_spx is None:
        return {"label": "UNKNOWN", "distance": None}

    distance = abs(float(current_spx) - float(entry_spx))
    if distance < 5.0:
        label = "IDEAL"
    elif distance < 10.0:
        label = "EARLY"
    elif distance < 20.0:
        label = "LATE"
    else:
        label = "CHASE"
    return {"label": label, "distance": round_price(distance)}


def get_decision_reason(
    action_label: str,
    signal_package: dict[str, Any] | None,
    play: dict[str, Any] | None,
    intelligence: dict[str, Any],
    timing_label: str,
) -> str:
    """Return one short decision reason for the operator."""

    if action_label == "SKIP TRADE":
        if not play or not play.get("stop") or play.get("invalid_stop"):
            return "No valid structural stop"
        if intelligence.get("rr_ratio") is None or float(intelligence.get("rr_ratio") or 0.0) < 0.5:
            return "Poor reward-to-risk at current price"
        if timing_label in {"LATE", "CHASE"}:
            return "Late entry relative to move"
        if signal_package and signal_package.get("sit_out", {}).get("sit_out"):
            return "Outside optimal structure"
        return "Signal suppressed by decision filter"

    if action_label == "ENTER WITH CAUTION":
        if timing_label in {"LATE", "CHASE"}:
            return "Late relative to planned entry"
        if intelligence.get("rr_ratio") is not None and float(intelligence.get("rr_ratio") or 0.0) < 1.0:
            return "Reduced reward-to-risk"
        return "Trade requires caution"

    if timing_label == "IDEAL":
        return "At key structural level"
    if intelligence.get("rr_ratio") is not None and float(intelligence.get("rr_ratio") or 0.0) >= 1.0:
        return "Favorable RR with valid stop"
    return "Within optimal entry zone"


LIVE_STRUCTURE_STATE_LABELS = {
    "CHANNEL_OVERLAP": "Channel Overlap",
    "BETWEEN_CHANNELS": "Between Channels",
    "INSIDE_ASC_CHANNEL": "Inside Ascending Channel",
    "INSIDE_DESC_CHANNEL": "Inside Descending Channel",
    "ABOVE_ASC_CHANNEL": "Above Ascending Channel",
    "BELOW_DESC_CHANNEL": "Below Descending Channel",
    "OUTSIDE_ALL_STRUCTURES": "Outside All Structures",
}


def format_live_state_label(value: str | None) -> str:
    """Format raw live state labels for calm production display."""

    return LIVE_STRUCTURE_STATE_LABELS.get(str(value or "").upper(), str(value or "Unknown").replace("_", " ").title())


def compute_live_structure_state(current_price: float | None, line_values: dict[str, float]) -> dict[str, Any]:
    """Compute the raw current structure state from projected boundaries only."""

    required = {"hw", "asc_ceiling", "asc_floor", "desc_ceiling", "desc_floor", "lw"}
    if current_price is None or required.difference(line_values):
        return {
            "live_structure_state": "OUTSIDE_ALL_STRUCTURES",
            "structure_reason": "Structure unavailable",
        }

    price = float(current_price)
    hw = float(line_values["hw"])
    asc_ceiling = float(line_values["asc_ceiling"])
    asc_floor = float(line_values["asc_floor"])
    desc_ceiling = float(line_values["desc_ceiling"])
    desc_floor = float(line_values["desc_floor"])
    lw = float(line_values["lw"])

    in_ascending = asc_floor <= price <= asc_ceiling
    in_descending = desc_floor <= price <= desc_ceiling

    if in_ascending and in_descending:
        return {
            "live_structure_state": "CHANNEL_OVERLAP",
            "structure_reason": "Price is inside both projected channels.",
        }
    if desc_ceiling < price < asc_floor:
        return {
            "live_structure_state": "BETWEEN_CHANNELS",
            "structure_reason": "Price is between the descending ceiling and ascending floor.",
        }
    if in_ascending:
        return {
            "live_structure_state": "INSIDE_ASC_CHANNEL",
            "structure_reason": "Price is inside the ascending channel.",
        }
    if in_descending:
        return {
            "live_structure_state": "INSIDE_DESC_CHANNEL",
            "structure_reason": "Price is inside the descending channel.",
        }
    if asc_ceiling < price < hw:
        return {
            "live_structure_state": "ABOVE_ASC_CHANNEL",
            "structure_reason": "Price is above the ascending channel but below HW.",
        }
    if lw < price < desc_floor:
        return {
            "live_structure_state": "BELOW_DESC_CHANNEL",
            "structure_reason": "Price is below the descending channel but above LW.",
        }
    return {
        "live_structure_state": "OUTSIDE_ALL_STRUCTURES",
        "structure_reason": "Price is outside the projected channel framework.",
    }


def compute_live_scenario_snapshot(
    *,
    current_price: float | None,
    line_values: dict[str, float],
    open_price: float | None,
    scenario_origin: str,
    previous_live_scenario: str | None = None,
    previous_structure_state: str | None = None,
    confirmation_confirmed: bool = False,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Resolve the current live scenario and transition state from one source of truth."""

    structure_snapshot = compute_live_structure_state(current_price, line_values)
    live_structure_state = structure_snapshot["live_structure_state"]
    structure_reason = structure_snapshot["structure_reason"]

    try:
        live_scenario_payload = evaluate_trading_scenario(
            current_price=float(current_price) if current_price is not None else 0.0,
            line_values=line_values,
            open_price=open_price,
            confirmation_confirmed=confirmation_confirmed,
        ) if current_price is not None else None
    except Exception:
        live_scenario_payload = None

    live_scenario = (
        str(live_scenario_payload.get("scenario_name", "")).strip()
        if isinstance(live_scenario_payload, dict)
        else ""
    ) or "OUTSIDE_FRAMEWORK"

    previous_live = str(previous_live_scenario or scenario_origin or live_scenario)
    previous_structure = str(previous_structure_state or live_structure_state)
    scenario_transition = f"{previous_live} -> {live_scenario}" if previous_live != live_scenario else ""
    structure_transition = f"{previous_structure} -> {live_structure_state}" if previous_structure != live_structure_state else ""

    if live_scenario == "OUTSIDE_FRAMEWORK":
        reasoning_label = "Current price no longer maps cleanly to one of the active framework scenarios."
    elif scenario_transition:
        reasoning_label = f"Live scenario remapped from {previous_live} to {live_scenario}."
    else:
        reasoning_label = structure_reason

    return {
        "scenario_origin": str(scenario_origin or ""),
        "live_scenario": live_scenario,
        "previous_live_scenario": previous_live,
        "live_structure_state": live_structure_state,
        "previous_structure_state": previous_structure,
        "structure_transition": structure_transition,
        "scenario_transition": scenario_transition,
        "live_state_timestamp": timestamp or current_central_time().isoformat(),
        "reasoning_label": reasoning_label,
        "structure_reason": structure_reason,
    }


def resolve_live_scenario_context(
    *,
    current_price: float | None,
    line_values: dict[str, float],
    open_price: float | None,
    scenario_origin: str,
    state_key: str,
    confirmation_confirmed: bool = False,
) -> dict[str, Any]:
    """Persist and return the latest live scenario/state snapshot for the active session."""

    live_state_store = st.session_state.setdefault("live_state_store", {})
    previous_state = live_state_store.get(state_key, {})
    snapshot = compute_live_scenario_snapshot(
        current_price=current_price,
        line_values=line_values,
        open_price=open_price,
        scenario_origin=scenario_origin,
        previous_live_scenario=previous_state.get("live_scenario"),
        previous_structure_state=previous_state.get("live_structure_state"),
        confirmation_confirmed=confirmation_confirmed,
    )
    live_state_store[state_key] = snapshot
    return snapshot


def build_scenario_transition_note(live_context: dict[str, Any] | None) -> str:
    """Build one compact scenario transition note for the operator surface."""

    if not live_context:
        return ""
    transition = str(live_context.get("scenario_transition") or "")
    if transition:
        live_label = str(live_context.get("live_scenario") or "")
        if live_label:
            return f"Structure changed: now {live_label.lower()}"
        return "Market structure has shifted"
    origin = str(live_context.get("scenario_origin") or "")
    live = str(live_context.get("live_scenario") or "")
    if origin and live and origin != live:
        return f"Structure changed: now {live.lower()}"
    return ""


def build_live_decision_sentence(
    *,
    authority: dict[str, Any] | None,
    intelligence: dict[str, Any],
    live_context: dict[str, Any] | None,
) -> str:
    """Return one concise operator sentence from the current live state."""

    authority = authority or {}
    decision = str(authority.get("decision", "NO TRADE"))
    live_scenario = str((live_context or {}).get("live_scenario", ""))
    scenario_transition = str((live_context or {}).get("scenario_transition", ""))

    if decision == "NO TRADE":
        if scenario_transition:
            return "Market structure has shifted. Entry no longer valid."
        if not authority.get("stop_valid", False):
            return "Structure invalid. No structural stop. Trade suppressed."
        return str(authority.get("reason_line", "No valid live trade."))
    if decision == "CONDITIONAL BUY":
        if scenario_transition:
            return f"Live scenario shifted to {live_scenario}. {authority.get('condition_required', 'Wait for better location.')}"
        return str(authority.get("condition_required") or "Plan still valid, but the market must improve into the entry zone.")
    if intelligence.get("plan_status") == "HOLDING" and intelligence.get("regime") == "PULLBACK":
        return "Plan holding. Pullback regime. Entry still valid."
    return str(authority.get("reason_line", "Setup remains actionable."))


def build_low_data_state(records: list[dict[str, Any]] | pd.DataFrame | None, *, minimum: int = 5, label: str = "reviewed trades") -> dict[str, Any]:
    """Return a single low-data summary so the UI can avoid repeating empty-state scaffolding."""

    if records is None:
        count = 0
    elif isinstance(records, pd.DataFrame):
        count = int(len(records))
    else:
        count = int(len(records))

    return {
        "count": count,
        "enough": count >= minimum,
        "message": None if count >= minimum else f"Not enough {label} yet. More observations are needed before this section becomes useful.",
    }


def resolve_live_current_spx(current_es_price: float | None, effective_offset: float, fallback_spx: float | None) -> float | None:
    """Resolve the current live SPX proxy from current ES and the active offset."""

    if is_valid_price_input(current_es_price):
        return round_price(float(current_es_price) - float(effective_offset))
    return _to_float_or_none(fallback_spx)


def is_live_market_session() -> bool:
    """Return whether the current CT time is during the regular live session."""

    now_ct = current_central_time()
    start = time(8, 30)
    end = time(16, 0)
    return start <= now_ct.time() <= end


INTELLIGENCE_PLAN_HOLD_THRESHOLD_PCT = 0.08
INTELLIGENCE_PLAN_DRIFT_THRESHOLD_PCT = 0.18
INTELLIGENCE_PLAN_HOLD_THRESHOLD_ABS = 1.0
INTELLIGENCE_PLAN_DRIFT_THRESHOLD_ABS = 2.0
INTELLIGENCE_CONFIDENCE_HIGH_DRIFT_PCT = 0.08
INTELLIGENCE_CONFIDENCE_MEDIUM_DRIFT_PCT = 0.18
INTELLIGENCE_MIN_RR = 1.0
INTELLIGENCE_MIN_RR_HARD_FLOOR = 0.5
SESSION_PLAN_LOCK_CUTOFFS = {
    "8:15 AM CT": (8, 15),
    "8:20 AM CT": (8, 20),
    "8:25 AM CT": (8, 25),
    "8:29 AM CT": (8, 29),
}
ENTRY_ZONE_IN_THRESHOLD = 3.0
ENTRY_ZONE_APPROACHING_THRESHOLD = 8.0
MOVE_COMPLETION_CAP_PCT = 200.0


def resolve_session_plan_cutoff_time(cutoff_label: str) -> tuple[int, int]:
    """Resolve the configured lock cutoff label into hour/minute components."""

    return SESSION_PLAN_LOCK_CUTOFFS.get(cutoff_label, SESSION_PLAN_LOCK_CUTOFFS[DEFAULT_SETTINGS["session_plan_lock_cutoff"]])


def build_session_plan_lock_timestamp(next_trading_date: date, cutoff_label: str):
    """Build the selected session-plan lock timestamp in Central Time."""

    hour, minute = resolve_session_plan_cutoff_time(cutoff_label)
    return at_central(next_trading_date, hour, minute)


def resolve_planned_entry_mark(
    live_predicted_entry_mark: float | None,
    anchor_key: str | None,
) -> float | None:
    """Return the active planned entry mark, using the locked session value when available."""

    if live_predicted_entry_mark is None:
        return None
    if st is None or not hasattr(st, "session_state") or anchor_key is None:
        return round_price(live_predicted_entry_mark)

    locked_store = st.session_state.setdefault("session_plan_store", {})
    locked_plan = locked_store.get(anchor_key)
    if isinstance(locked_plan, dict) and locked_plan.get("session_plan_locked") and locked_plan.get("planned_entry_mark") is not None:
        return round_price(float(locked_plan["planned_entry_mark"]))

    planned_store = st.session_state.setdefault("planned_entry_mark_store", {})
    planned_store[anchor_key] = round_price(live_predicted_entry_mark)
    return round_price(float(planned_store[anchor_key]))


def build_planned_anchor_key(
    play_role: str,
    signal_package: dict[str, Any] | None,
    play: dict[str, Any] | None,
    next_trading_date: date | None = None,
) -> str | None:
    """Build a stable session key for each play/date pair."""

    if play is None:
        return None
    date_key = next_trading_date.isoformat() if isinstance(next_trading_date, date) else "live"
    return "|".join([date_key, str(play_role or "")])


def build_session_plan_snapshot(
    *,
    play_role: str,
    signal_package: dict[str, Any] | None,
    play_spx: dict[str, Any] | None,
    play_es: dict[str, Any] | None,
    lead_option_quote: dict[str, Any] | None,
    intelligence: dict[str, Any] | None,
    next_trading_date: date,
    cutoff_label: str,
) -> dict[str, Any] | None:
    """Build a freeze-safe session snapshot from the current live play."""

    if play_spx is None or intelligence is None:
        return None

    entry_spx = _to_float_or_none(play_spx.get("entry", {}).get("price"))
    entry_es = _to_float_or_none(play_es.get("entry", {}).get("price")) if play_es else None
    planned_entry_mark = _to_float_or_none(intelligence.get("planned_entry_mark"))
    strike_value = play_spx.get("strike")
    direction = str(play_spx.get("direction", "") or "")
    scenario_name = str(signal_package.get("scenario", {}).get("scenario_name", "")) if signal_package else ""

    if entry_spx is None or planned_entry_mark is None or strike_value in (None, "") or not direction:
        return None

    stop_price = _to_float_or_none(play_spx.get("stop", {}).get("price")) if isinstance(play_spx.get("stop"), dict) and not play_spx.get("invalid_stop") else None
    rr_ratio = _to_float_or_none(lead_option_quote.get("rr_ratio")) if lead_option_quote else None
    expected_gain = _to_float_or_none(lead_option_quote.get("expected_gain")) if lead_option_quote else None
    expected_loss = _to_float_or_none(lead_option_quote.get("expected_loss")) if lead_option_quote else None
    contract_symbol = str(lead_option_quote.get("contract_symbol", "")) if lead_option_quote else ""

    return {
        "play_role": play_role,
        "next_trading_date": next_trading_date.isoformat(),
        "lock_cutoff_label": cutoff_label,
        "lock_cutoff_timestamp": build_session_plan_lock_timestamp(next_trading_date, cutoff_label).isoformat(),
        "session_plan_locked": True,
        "locked_timestamp": current_central_time().isoformat(),
        "locked_entry_spx": round_price(entry_spx),
        "locked_entry_es": round_price(entry_es) if entry_es is not None else None,
        "planned_entry_mark": round_price(planned_entry_mark),
        "planned_strike": int(strike_value),
        "scenario_name": scenario_name,
        "direction": direction,
        "expected_gain": round_price(expected_gain) if expected_gain is not None else None,
        "expected_loss": round_price(expected_loss) if expected_loss is not None else None,
        "rr_ratio": round(float(rr_ratio), 4) if rr_ratio is not None else None,
        "stop_spx": round_price(stop_price) if stop_price is not None else None,
        "contract_symbol": contract_symbol,
        "entry_label": str(play_spx.get("entry", {}).get("label", "")),
    }


def resolve_session_plan_state(
    *,
    anchor_key: str | None,
    play_role: str,
    signal_package: dict[str, Any] | None,
    play_spx: dict[str, Any] | None,
    play_es: dict[str, Any] | None,
    lead_option_quote: dict[str, Any] | None,
    intelligence: dict[str, Any] | None,
    next_trading_date: date,
    cutoff_label: str,
) -> dict[str, Any]:
    """Resolve the active session plan, freezing it at the configured cutoff."""

    lock_timestamp = build_session_plan_lock_timestamp(next_trading_date, cutoff_label)
    now_ct = current_central_time()
    lock_active = now_ct >= lock_timestamp
    base_state = {
        "anchor_key": anchor_key,
        "lock_cutoff_label": cutoff_label,
        "lock_cutoff_timestamp": lock_timestamp,
        "lock_active": lock_active,
        "session_plan_locked": False,
        "plan_available": False,
        "locked_timestamp": None,
        "locked_entry_spx": None,
        "locked_entry_es": None,
        "planned_entry_mark": None,
        "planned_strike": None,
        "scenario_name": str(signal_package.get("scenario", {}).get("scenario_name", "")) if signal_package else "",
        "direction": str(play_spx.get("direction", "")) if play_spx else "",
        "expected_gain": None,
        "expected_loss": None,
        "rr_ratio": None,
        "stop_spx": None,
        "contract_symbol": "",
        "entry_label": str(play_spx.get("entry", {}).get("label", "")) if play_spx else "",
        "lock_unavailable_reason": None,
    }

    if st is None or not hasattr(st, "session_state") or anchor_key is None:
        snapshot = build_session_plan_snapshot(
            play_role=play_role,
            signal_package=signal_package,
            play_spx=play_spx,
            play_es=play_es,
            lead_option_quote=lead_option_quote,
            intelligence=intelligence,
            next_trading_date=next_trading_date,
            cutoff_label=cutoff_label,
        )
        if snapshot is None:
            return base_state
        return {**base_state, **snapshot, "plan_available": True, "session_plan_locked": lock_active}

    plan_store = st.session_state.setdefault("session_plan_store", {})
    lock_failures = st.session_state.setdefault("session_plan_lock_failures", {})
    existing = plan_store.get(anchor_key)
    if isinstance(existing, dict):
        return {**base_state, **existing, "plan_available": True, "session_plan_locked": bool(existing.get("session_plan_locked", False))}

    if lock_active:
        snapshot = build_session_plan_snapshot(
            play_role=play_role,
            signal_package=signal_package,
            play_spx=play_spx,
            play_es=play_es,
            lead_option_quote=lead_option_quote,
            intelligence=intelligence,
            next_trading_date=next_trading_date,
            cutoff_label=cutoff_label,
        )
        if snapshot is None:
            failure = {
                **base_state,
                "lock_unavailable_reason": "no_valid_plan_at_lock_cutoff",
            }
            lock_failures[anchor_key] = failure
            return failure
        plan_store[anchor_key] = snapshot
        return {**base_state, **snapshot, "plan_available": True, "session_plan_locked": True}

    snapshot = build_session_plan_snapshot(
        play_role=play_role,
        signal_package=signal_package,
        play_spx=play_spx,
        play_es=play_es,
        lead_option_quote=lead_option_quote,
        intelligence=intelligence,
        next_trading_date=next_trading_date,
        cutoff_label=cutoff_label,
    )
    if snapshot is None:
        return base_state
    snapshot["session_plan_locked"] = False
    snapshot["locked_timestamp"] = None
    return {**base_state, **snapshot, "plan_available": True}


def render_tab1_hero(
    signal_package: dict[str, Any] | None,
    current_spx_price: float | None,
    current_es_price: float | None,
    effective_offset: float,
    final_status: str | None = None,
    final_decision: str | None = None,
    primary_play: dict[str, Any] | None = None,
    lead_option_quote: dict[str, Any] | None = None,
    intelligence_summary: dict[str, Any] | None = None,
    adaptive_overlay: dict[str, Any] | None = None,
    hero_authority: dict[str, Any] | None = None,
    active_play_label: str = "None",
    live_context: dict[str, Any] | None = None,
) -> None:
    """Render the compact live decision center."""

    if signal_package is None:
        scenario_name = "Awaiting Valid SPX Input"
        status_label = "Workflow Limited"
        status_class = "bad"
        status_icon = "!"
        decision_reason = "Waiting for valid live setup"
    else:
        scenario = signal_package["scenario"]
        scenario_name = str((live_context or {}).get("live_scenario") or scenario["scenario_name"])
        status_label = final_status or "ELIGIBLE"
        status_class, status_icon = status_chip_class(status_label)
        status_icon = "●" if status_label == "ELIGIBLE" else "!"
        action_label = final_decision or final_status_to_action(status_label, signal_package)
        hero_intelligence = intelligence_summary or assess_trade_intelligence(primary_play, lead_option_quote, current_spx_price=current_spx_price)
        timing_entry_value = hero_intelligence.get("locked_entry_spx") if hero_intelligence else None
        if timing_entry_value is None and primary_play:
            timing_entry_value = _to_float_or_none(primary_play.get("entry", {}).get("price"))
        timing_label = classify_entry_timing(current_spx_price, timing_entry_value)["label"]
        decision_reason = get_decision_reason(action_label, signal_package, primary_play, hero_intelligence, timing_label)

    if signal_package is not None:
        status_icon = "●" if status_label == "ELIGIBLE" else "!"
    current_display = format_price(current_es_price) if is_valid_price_input(current_es_price) else "Not entered"
    hero_entry_value = intelligence_summary.get("locked_entry_spx") if intelligence_summary else None
    if hero_entry_value is None and primary_play and primary_play.get("entry"):
        hero_entry_value = primary_play["entry"]["price"]
    entry_spx = format_price(hero_entry_value) if hero_entry_value is not None else "-"
    strike_value = str(primary_play["strike"]) if primary_play and primary_play.get("strike") is not None else "-"
    authority = hero_authority or {}
    authority_decision = authority.get("decision", "NO TRADE")
    authority_confidence = authority.get("confidence_score", 0)
    authority_ev = authority.get("expected_value")
    authority_risk = authority.get("risk_class", "HIGH")
    authority_reason = authority.get("reason_line", decision_reason)
    action_label = authority_decision
    adaptive_evidence = authority.get("evidence_level", (adaptive_overlay or {}).get("adaptive_evidence_level", "None"))
    ev_display = format_price(authority_ev) if authority_ev is not None else "Insufficient"
    live_structure_state = format_live_state_label((live_context or {}).get("live_structure_state"))
    transition_note = build_scenario_transition_note(live_context)
    show_lock = bool(intelligence_summary and intelligence_summary.get("session_plan_locked"))

    st.markdown(
        f"""
        <div class="spx-hero">
            <div class="spx-hero-top">
                <div>
                    <div class="spx-hero-kicker">Decision Center</div>
                    <div class="spx-decision-action">{escape(authority_decision)}</div>
                    <div class="spx-decision-meta">
                        <span class="spx-pill scenario-neutral">{escape(scenario_name)}</span>
                        <span class="spx-pill scenario-neutral">{escape(live_structure_state)}</span>
                        <span class="spx-pill scenario-neutral">Confidence {int(authority_confidence)}%</span>
                        <span class="spx-pill scenario-neutral">Risk {escape(authority_risk)}</span>
                    </div>
                    <div class="spx-hero-subtitle">{escape(authority_reason)}</div>
                    {f'<div class="spx-hero-stat-note" style="margin-top:0.35rem;">{escape(transition_note)}</div>' if transition_note else ''}
                </div>
                <div class="spx-hero-status">
                    <div class="spx-hero-status-label">Current Price (ES)</div>
                    <div style="font-family:'JetBrains Mono', monospace; font-size:2rem; font-weight:800; color:#f8fbff; text-shadow:0 0 20px rgba(0,212,255,0.22); margin-bottom:0.55rem;">{current_display}</div>
                    <div class="spx-status-chip {status_class}"><span>{status_icon}</span><span>{escape(authority_decision)}</span></div>
                </div>
            </div>
            <div class="spx-hero-grid">
                <div class="spx-decision-strip">
                    <div class="spx-decision-strip-label">Planned Entry</div>
                    <div class="spx-decision-strip-value">{entry_spx} SPX</div>
                </div>
                <div class="spx-decision-strip">
                    <div class="spx-decision-strip-label">Strike</div>
                    <div class="spx-decision-strip-value">{strike_value}</div>
                </div>
                <div class="spx-decision-strip">
                    <div class="spx-decision-strip-label">Current ES</div>
                    <div class="spx-decision-strip-value">{current_display}</div>
                </div>
                <div class="spx-decision-strip" style="{'' if authority_ev is not None else 'opacity:0.72;'}">
                    <div class="spx-decision-strip-label">Expected Value</div>
                    <div class="spx-decision-strip-value">{ev_display}</div>
                </div>
                <div class="spx-decision-strip">
                    <div class="spx-decision-strip-label">Active Play</div>
                    <div class="spx-decision-strip-value">{escape(active_play_label)}</div>
                </div>
                <div class="spx-decision-strip" style="opacity:0.82;">
                    <div class="spx-decision-strip-label">Evidence</div>
                    <div class="spx-decision-strip-value">{escape(adaptive_evidence)}</div>
                </div>
                {f'<div class="spx-decision-strip" style="opacity:0.82;"><div class="spx-decision-strip-label">Lock</div><div class="spx-decision-strip-value">Locked</div></div>' if show_lock else ''}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_key_levels_card(
    final_lines: dict[str, dict[str, Any]],
    current_es_price: float | None,
    effective_offset: float,
    *,
    compact: bool = False,
) -> None:
    """Render a compact key-levels summary card."""

    current_label = format_price(current_es_price) if is_valid_price_input(current_es_price) else "Not entered"
    subtitle = "Projected ES stack." if compact else "Fast scan of the full projected stack in ES source terms."
    groups = [
        ("Top", ["hw", "asc_ceiling"]),
        ("Mid", ["asc_floor"]),
        ("Lower", ["desc_ceiling", "desc_floor"]),
        ("Extreme", ["lw"]),
    ]

    with st.container(border=True):
        st.markdown("**Key Levels Summary**")
        st.caption(subtitle)

        header_bits = [f"Current ES {current_label}"]
        if not compact:
            header_bits.append(f"Offset {format_price(effective_offset)}")
        st.markdown(" | ".join(header_bits))

        for group_name, line_names in groups:
            items = []
            for name in line_names:
                details = final_lines[name]
                items.append(f"{details['label']} `{format_price(details['projected_price'])}`")
            st.caption(group_name)
            st.markdown(" | ".join(items))

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

    integrity_flags = list(resolved_play.get("integrity_flags", []))
    entry_price = _to_float_or_none(resolved_play.get("entry", {}).get("price"))
    stop_price = _to_float_or_none(resolved_play.get("stop", {}).get("price"))
    invalid_stop = bool(
        entry_price is not None
        and stop_price is not None
        and abs(entry_price - stop_price) < 1e-9
    )
    stop_unavailable = stop_price is None or invalid_stop
    if stop_unavailable:
        integrity_flags.append("stop_unavailable")
    if invalid_stop:
        integrity_flags.append("invalid_stop")
        resolved_play["stop"] = None
    elif stop_price is None:
        resolved_play["stop"] = None
    resolved_play["invalid_stop"] = invalid_stop
    resolved_play["stop_unavailable"] = stop_unavailable
    resolved_play["setup_complete"] = bool(entry_price is not None and not stop_unavailable)
    resolved_play["setup_tradable"] = bool(entry_price is not None and not stop_unavailable)
    resolved_play["setup_status"] = "tradable" if resolved_play["setup_tradable"] else "incomplete_stop_unavailable"
    resolved_play["integrity_flags"] = sorted(set(integrity_flags))

    return resolved_play


def align_play_conversion_to_effective_offset(
    play_spx: dict[str, Any] | None,
    play_es: dict[str, Any] | None,
    effective_offset: float,
) -> dict[str, Any] | None:
    """Force SPX display legs to equal ES leg minus the effective offset."""

    if play_spx is None:
        return None

    aligned_play = dict(play_spx)
    conversion_debug: dict[str, dict[str, Any]] = {}

    for leg_name in ("entry", "stop", "tp1", "tp2"):
        spx_leg = play_spx.get(leg_name) if isinstance(play_spx.get(leg_name), dict) else None
        es_leg = play_es.get(leg_name) if isinstance(play_es and play_es.get(leg_name), dict) else None
        if spx_leg is None:
            continue

        aligned_leg = dict(spx_leg)
        spx_before = _to_float_or_none(spx_leg.get("price"))
        es_price = _to_float_or_none(es_leg.get("price")) if es_leg else None
        additional_adjustment = None
        expected_spx = None
        conversion_valid = None

        if es_price is not None:
            expected_spx = round_price(es_price - float(effective_offset))
            if spx_before is not None:
                additional_adjustment = round_price(spx_before - expected_spx)
                conversion_valid = abs(additional_adjustment) < 0.01
            aligned_leg["price"] = expected_spx

        aligned_play[leg_name] = aligned_leg
        conversion_debug[leg_name] = {
            "source_es": es_price,
            "spx_before_alignment": spx_before,
            "effective_offset": round_price(effective_offset),
            "additional_adjustment_applied": additional_adjustment,
            "final_displayed_spx": expected_spx,
            "conversion_valid": conversion_valid,
        }

    entry_debug = conversion_debug.get("entry", {})
    aligned_play["conversion_debug"] = conversion_debug
    aligned_play["conversion_invalid"] = bool(entry_debug.get("conversion_valid") is False)
    return aligned_play


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


def build_projection_target(next_trading_date: date):
    """Return the fixed 9:00 AM CT projection target for a selected trading day."""

    return at_central(next_trading_date, 9, 0)


def is_historical_projection_run(next_trading_date: date, reference_date: date | None = None) -> bool:
    """Return True when the selected next trading date is not the current trading date."""

    comparison_date = reference_date or current_central_time().date()
    return next_trading_date != default_next_trading_day(comparison_date)


def resolve_signal_evaluation_time(next_trading_date: date, historical_mode: bool | None = None):
    """Resolve the timestamp used for signal-package time-based checks."""

    projection_target = build_projection_target(next_trading_date)
    if historical_mode is None:
        historical_mode = is_historical_projection_run(next_trading_date)
    if historical_mode:
        return projection_target
    return current_central_time()


def sync_projection_price_inputs(
    next_trading_date: date,
    historical_mode: bool,
    live_defaults: dict[str, Any],
    historical_defaults: dict[str, Any] | None = None,
) -> bool:
    """Keep price inputs aligned with the selected projection context."""

    previous_date = st.session_state.get("_projection_context_next_date")
    previous_mode = st.session_state.get("_projection_context_mode")

    if previous_date != next_trading_date or previous_mode != historical_mode:
        if historical_mode:
            st.session_state["current_spx_price_input"] = float((historical_defaults or {}).get("default_spx_price", 0.0))
            st.session_state["current_es_price_input"] = float((historical_defaults or {}).get("default_es_price", 0.0))
            st.session_state["open_reference_input"] = float((historical_defaults or {}).get("default_open_reference", 0.0))
        else:
            st.session_state["current_spx_price_input"] = float(live_defaults["default_spx_price"])
            st.session_state["current_es_price_input"] = float(live_defaults["default_es_price"])
            st.session_state["open_reference_input"] = float(live_defaults["default_open_reference"])

    st.session_state["_projection_context_next_date"] = next_trading_date
    st.session_state["_projection_context_mode"] = historical_mode
    return historical_mode


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


def resolve_effective_offset(inputs: dict[str, Any]) -> tuple[float, str, dict[str, Any]]:
    """Resolve the offset used for ES/SPX conversion in the app layer."""

    manual_offset = float(inputs["es_spx_offset"])
    live_inferred_offset = _to_float_or_none(inputs.get("derived_live_offset"))
    current_es = _to_float_or_none(inputs.get("current_es_price"))
    current_spx = _to_float_or_none(inputs.get("current_spx_price"))
    details = {
        "current_es": round_price(current_es) if current_es is not None else None,
        "current_spx": round_price(current_spx) if current_spx is not None else None,
        "manual_offset": round_price(manual_offset),
        "live_inferred_offset": round_price(live_inferred_offset) if live_inferred_offset is not None else None,
        "effective_offset": round_price(manual_offset),
        "effective_offset_source": "manual_offset",
    }

    return manual_offset, "manual_offset", details


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
    pivot_high_extreme_es = max(pivot_green_high_es, pivot_red_high_es)
    pivot_low_extreme_es = min(pivot_red_low_es, pivot_green_low_es)

    return {
        "pivot_high": {
            "pivot_time": pivot_high_time,
            "pivot_extreme": {
                "timestamp": pivot_high_time,
                "high": pivot_high_extreme_es,
                "low": pivot_high_extreme_es,
                "open": pivot_high_extreme_es,
                "close": pivot_high_extreme_es,
                "color": "manual",
            },
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
            "pivot_extreme": {
                "timestamp": pivot_low_time,
                "low": pivot_low_extreme_es,
                "high": pivot_low_extreme_es,
                "open": pivot_low_extreme_es,
                "close": pivot_low_extreme_es,
                "color": "manual",
            },
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
                "projection_start_time": hw_time,
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
                "price": pivot_high_extreme_es,
                "timestamp": pivot_high_time,
                "projection_start_time": pivot_high_time,
                "source": {
                    "timestamp": pivot_high_time,
                    "high": pivot_high_extreme_es,
                    "low": pivot_high_extreme_es,
                    "open": pivot_high_extreme_es,
                    "close": pivot_high_extreme_es,
                    "color": "manual",
                },
                "associated_context_candle": {
                    "timestamp": pivot_high_time,
                    "high": pivot_red_high_es,
                    "low": pivot_red_high_es,
                    "open": pivot_red_high_es,
                    "close": pivot_red_high_es,
                    "color": "red",
                },
                "pivot_extreme": {"timestamp": pivot_high_time, "high": pivot_high_extreme_es, "low": pivot_high_extreme_es, "open": pivot_high_extreme_es, "close": pivot_high_extreme_es, "color": "manual"},
                "anchor_basis": "pivot_high_extreme",
                "direction": "ascending",
                "label": "ASC Ceiling",
                "line_type": "channel",
            },
            "asc_floor": {
                "price": pivot_low_extreme_es,
                "timestamp": pivot_low_time,
                "projection_start_time": pivot_low_time,
                "source": {
                    "timestamp": pivot_low_time,
                    "high": pivot_low_extreme_es,
                    "low": pivot_low_extreme_es,
                    "open": pivot_low_extreme_es,
                    "close": pivot_low_extreme_es,
                    "color": "manual",
                },
                "associated_context_candle": {
                    "timestamp": pivot_low_time,
                    "high": pivot_red_low_es,
                    "low": pivot_red_low_es,
                    "open": pivot_red_low_es,
                    "close": pivot_red_low_es,
                    "color": "red",
                },
                "pivot_extreme": {"timestamp": pivot_low_time, "high": pivot_low_extreme_es, "low": pivot_low_extreme_es, "open": pivot_low_extreme_es, "close": pivot_low_extreme_es, "color": "manual"},
                "anchor_basis": "pivot_low_extreme",
                "direction": "ascending",
                "label": "ASC Floor",
                "line_type": "channel",
            },
            "desc_ceiling": {
                "price": pivot_high_extreme_es,
                "timestamp": pivot_high_time,
                "projection_start_time": pivot_high_time,
                "source": {
                    "timestamp": pivot_high_time,
                    "high": pivot_high_extreme_es,
                    "low": pivot_high_extreme_es,
                    "open": pivot_high_extreme_es,
                    "close": pivot_high_extreme_es,
                    "color": "manual",
                },
                "associated_context_candle": {
                    "timestamp": pivot_high_time,
                    "high": pivot_green_high_es,
                    "low": pivot_green_high_es,
                    "open": pivot_green_high_es,
                    "close": pivot_green_high_es,
                    "color": "green",
                },
                "pivot_extreme": {"timestamp": pivot_high_time, "high": pivot_high_extreme_es, "low": pivot_high_extreme_es, "open": pivot_high_extreme_es, "close": pivot_high_extreme_es, "color": "manual"},
                "anchor_basis": "pivot_high_extreme",
                "direction": "descending",
                "label": "DESC Ceiling",
                "line_type": "channel",
            },
            "desc_floor": {
                "price": pivot_low_extreme_es,
                "timestamp": pivot_low_time,
                "projection_start_time": pivot_low_time,
                "source": {
                    "timestamp": pivot_low_time,
                    "high": pivot_low_extreme_es,
                    "low": pivot_low_extreme_es,
                    "open": pivot_low_extreme_es,
                    "close": pivot_low_extreme_es,
                    "color": "manual",
                },
                "associated_context_candle": {
                    "timestamp": pivot_low_time,
                    "high": pivot_green_low_es,
                    "low": pivot_green_low_es,
                    "open": pivot_green_low_es,
                    "close": pivot_green_low_es,
                    "color": "green",
                },
                "pivot_extreme": {"timestamp": pivot_low_time, "high": pivot_low_extreme_es, "low": pivot_low_extreme_es, "open": pivot_low_extreme_es, "close": pivot_low_extreme_es, "color": "manual"},
                "anchor_basis": "pivot_low_extreme",
                "direction": "descending",
                "label": "DESC Floor",
                "line_type": "channel",
            },
            "lw": {
                "price": lw_price_es,
                "timestamp": lw_time,
                "projection_start_time": lw_time,
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
        "source_points": {
            "pivot_high": {"timestamp": pivot_high_time, "price": pivot_high_extreme_es, "source": {"timestamp": pivot_high_time, "high": pivot_high_extreme_es, "low": pivot_high_extreme_es, "open": pivot_high_extreme_es, "close": pivot_high_extreme_es, "color": "manual"}, "search_window": "12:00 PM CT to 4:00 PM CT"},
            "pivot_highest_wick": {"timestamp": hw_time, "price": hw_price_es, "source": {"timestamp": hw_time, "high": hw_price_es, "low": hw_price_es, "open": hw_price_es, "close": hw_price_es, "color": "manual"}, "search_window": "8:30 AM CT to 4:00 PM CT"},
            "pivot_low": {"timestamp": pivot_low_time, "price": pivot_low_extreme_es, "source": {"timestamp": pivot_low_time, "high": pivot_low_extreme_es, "low": pivot_low_extreme_es, "open": pivot_low_extreme_es, "close": pivot_low_extreme_es, "color": "manual"}, "search_window": "12:00 PM CT to 4:00 PM CT"},
            "pivot_lowest_wick": {"timestamp": lw_time, "price": lw_price_es, "source": {"timestamp": lw_time, "high": lw_price_es, "low": lw_price_es, "open": lw_price_es, "close": lw_price_es, "color": "manual"}, "search_window": "8:30 AM CT to 4:00 PM CT"},
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
        "play_type": str(raw_trade.get("play_type", "")),
        "direction": normalize_trade_direction(raw_trade.get("direction", "")),
        "strike_or_contract_label": str(raw_trade.get("strike_or_contract_label", "")),
        "entry_line_label": str(raw_trade.get("entry_line_label", "")),
        "entry_line_value": round_price(float(raw_trade.get("entry_line_value", 0.0))),
        "entry_spx": round_price(float(raw_trade.get("entry_spx", raw_trade.get("entry_line_value", 0.0)))),
        "entry_es": round_price(float(raw_trade.get("entry_es", 0.0))),
        "entry_value": round_price(float(raw_trade.get("entry_value", 0.0))),
        "option_mark_at_decision": round_price(float(raw_trade.get("option_mark_at_decision", 0.0))),
        "predicted_entry_price": round_price(float(raw_trade.get("predicted_entry_price", 0.0))),
        "planned_entry_mark": round_price(float(raw_trade.get("planned_entry_mark", raw_trade.get("predicted_entry_price", 0.0)))),
        "live_predicted_entry_mark": round_price(float(raw_trade.get("live_predicted_entry_mark", raw_trade.get("predicted_entry_price", 0.0)))),
        "lock_cutoff": str(raw_trade.get("lock_cutoff", "")),
        "session_plan_locked": bool(raw_trade.get("session_plan_locked", False)),
        "locked_timestamp": str(raw_trade.get("locked_timestamp", "")),
        "locked_entry_spx": round_price(float(raw_trade.get("locked_entry_spx", raw_trade.get("entry_spx", 0.0)))),
        "locked_entry_es": round_price(float(raw_trade.get("locked_entry_es", raw_trade.get("entry_es", 0.0)))),
        "locked_entry_mark": round_price(float(raw_trade.get("locked_entry_mark", raw_trade.get("planned_entry_mark", raw_trade.get("predicted_entry_price", 0.0))))),
        "locked_strike": str(raw_trade.get("locked_strike", raw_trade.get("strike_or_contract_label", ""))),
        "locked_direction": str(raw_trade.get("locked_direction", raw_trade.get("direction", ""))),
        "locked_stop_spx": round_price(float(raw_trade.get("locked_stop_spx", raw_trade.get("stop_value", 0.0)))),
        "locked_suggested_stop_spx": round_price(float(raw_trade.get("locked_suggested_stop_spx", raw_trade.get("suggested_stop_spx", 0.0)))),
        "locked_expected_gain": round_price(float(raw_trade.get("locked_expected_gain", raw_trade.get("expected_gain", 0.0)))),
        "locked_expected_loss": round_price(float(raw_trade.get("locked_expected_loss", raw_trade.get("expected_loss", 0.0)))),
        "locked_rr_ratio": round(float(raw_trade.get("locked_rr_ratio", raw_trade.get("rr_ratio", 0.0))), 3),
        "locked_contract_symbol": str(raw_trade.get("locked_contract_symbol", raw_trade.get("selected_contract_symbol", ""))),
        "locked_contract_score": round(float(raw_trade.get("locked_contract_score", raw_trade.get("contract_score", 0.0))), 4),
        "play_role": str(raw_trade.get("play_role", raw_trade.get("play_type", ""))),
        "plan_locked": bool(raw_trade.get("plan_locked", raw_trade.get("session_plan_locked", False))),
        "lock_cutoff_used": str(raw_trade.get("lock_cutoff_used", raw_trade.get("lock_cutoff", ""))),
        "plan_locked_timestamp": str(raw_trade.get("plan_locked_timestamp", raw_trade.get("locked_timestamp", ""))),
        "final_decision_at_lock": str(raw_trade.get("final_decision_at_lock", raw_trade.get("final_decision", ""))),
        "scenario_origin": str(raw_trade.get("scenario_origin", raw_trade.get("scenario_name", ""))),
        "live_scenario": str(raw_trade.get("live_scenario", "")),
        "previous_live_scenario": str(raw_trade.get("previous_live_scenario", "")),
        "live_structure_state": str(raw_trade.get("live_structure_state", "")),
        "previous_structure_state": str(raw_trade.get("previous_structure_state", "")),
        "structure_transition": str(raw_trade.get("structure_transition", "")),
        "scenario_transition": str(raw_trade.get("scenario_transition", "")),
        "live_state_timestamp": str(raw_trade.get("live_state_timestamp", "")),
        "entry_zone_status": str(raw_trade.get("entry_zone_status", "")),
        "move_completion_pct": round(float(raw_trade.get("move_completion_pct", 0.0)), 2),
        "current_mark": round_price(float(raw_trade.get("current_mark", raw_trade.get("option_mark_at_decision", 0.0)))),
        "current_spx_at_decision": round_price(float(raw_trade.get("current_spx_at_decision", raw_trade.get("entry_spx", 0.0)))),
        "current_es_at_decision": round_price(float(raw_trade.get("current_es_at_decision", raw_trade.get("entry_es", 0.0)))),
        "current_mark_at_decision": round_price(float(raw_trade.get("current_mark_at_decision", raw_trade.get("current_mark", raw_trade.get("option_mark_at_decision", 0.0))))),
        "selected_contract_symbol": str(raw_trade.get("selected_contract_symbol", "")),
        "best_contract_selected": bool(raw_trade.get("best_contract_selected", bool(raw_trade.get("selected_contract_symbol", "")))),
        "stop_value": round_price(float(raw_trade.get("stop_value", 0.0))),
        "suggested_stop_spx": round_price(float(raw_trade.get("suggested_stop_spx", 0.0))),
        "expected_gain": round_price(float(raw_trade.get("expected_gain", 0.0))),
        "expected_loss": round_price(float(raw_trade.get("expected_loss", 0.0))),
        "rr_ratio": round(float(raw_trade.get("rr_ratio", 0.0)), 3),
        "contract_score": round(float(raw_trade.get("contract_score", 0.0)), 4),
        "regime": str(raw_trade.get("regime", "")),
        "plan_status": str(raw_trade.get("plan_status", "")),
        "chase_status": str(raw_trade.get("chase_status", "")),
        "prediction_confidence": str(raw_trade.get("prediction_confidence", "")),
        "final_decision": str(raw_trade.get("final_decision", "")),
        "final_authority_decision": str(raw_trade.get("final_authority_decision", raw_trade.get("final_decision", ""))),
        "final_authority_confidence": round(float(raw_trade.get("final_authority_confidence", 0.0)), 2),
        "final_authority_expected_value": round_price(float(raw_trade.get("final_authority_expected_value", 0.0))),
        "final_authority_risk_class": str(raw_trade.get("final_authority_risk_class", "")),
        "final_authority_reason": str(raw_trade.get("final_authority_reason", "")),
        "final_authority_top_reasons": list(raw_trade.get("final_authority_top_reasons", [])) if isinstance(raw_trade.get("final_authority_top_reasons", []), list) else [],
        "expected_return_20": round_price(float(raw_trade.get("expected_return_20", 0.0))),
        "expected_return_50": round_price(float(raw_trade.get("expected_return_50", 0.0))),
        "expected_return_100": round_price(float(raw_trade.get("expected_return_100", 0.0))),
        "decision_state_at_action": str(raw_trade.get("decision_state_at_action", raw_trade.get("final_authority_decision", raw_trade.get("final_decision", "")))),
        "override_flag": bool(raw_trade.get("override_flag", False)),
        "override_reason": str(raw_trade.get("override_reason", "")),
        "entry_drift_abs": round_price(float(raw_trade.get("entry_drift_abs", 0.0))),
        "entry_drift_pct": round(float(raw_trade.get("entry_drift_pct", 0.0)), 4),
        "price_vs_plan": round_price(float(raw_trade.get("price_vs_plan", 0.0))),
        "stop_quality": str(raw_trade.get("stop_quality", "")),
        "trade_quality": str(raw_trade.get("trade_quality", "")),
        "integrity_flags": list(raw_trade.get("integrity_flags", [])) if isinstance(raw_trade.get("integrity_flags", []), list) else [],
        "actual_trade_taken": bool(raw_trade.get("actual_trade_taken", False)),
        "actual_entry_price_option": _positive_price_or_none(raw_trade.get("actual_entry_price_option", raw_trade.get("entry_value"))),
        "actual_entry_price_spx": _positive_price_or_none(raw_trade.get("actual_entry_price_spx", raw_trade.get("entry_spx"))),
        "actual_contract_symbol": str(raw_trade.get("actual_contract_symbol", raw_trade.get("selected_contract_symbol", ""))),
        "actual_contract_mark_if_known": _positive_price_or_none(raw_trade.get("actual_contract_mark_if_known", raw_trade.get("entry_value"))),
        "actual_stop_used": _positive_price_or_none(raw_trade.get("actual_stop_used", raw_trade.get("stop_value"))),
        "actual_exit_price_option": _positive_price_or_none(raw_trade.get("actual_exit_price_option", raw_trade.get("exit_value"))),
        "actual_exit_price_spx": _positive_price_or_none(raw_trade.get("actual_exit_price_spx", 0.0)),
        "actual_exit_reason": str(raw_trade.get("actual_exit_reason", raw_trade.get("result", ""))),
        "actual_contracts": int(raw_trade.get("actual_contracts", raw_trade.get("contracts", 1)) or 1),
        "actual_notes": str(raw_trade.get("actual_notes", raw_trade.get("notes", ""))),
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
    normalized_trade.update(derive_outcome_tracking_fields(normalized_trade))
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
                "execution",
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
                **{
                    "id": trade["id"],
                    "date": trade["trade_date"],
                    "session": trade["session"],
                    "scenario": trade["scenario_name"],
                    "direction": resolve_trade_direction_display(trade["direction"])["compact"],
                    "execution": resolve_trade_execution_display(
                        trade["direction"],
                        trade.get("final_authority_decision") or trade.get("final_decision") or trade.get("decision_state_at_action"),
                    ),
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
        "play_type": "primary",
        "direction": signal_package["scenario"]["primary_trade_direction"] if signal_package and signal_package["scenario"]["primary_trade_direction"] else "CALL",
        "strike_or_contract_label": str(primary_play["strike"]) if primary_play else "",
        "entry_line_label": primary_play["entry"]["label"] if primary_play else "",
        "entry_line_value": float(primary_play["entry"]["price"]) if primary_play else 0.0,
        "entry_spx": float(primary_play["entry"]["price"]) if primary_play else 0.0,
        "entry_es": 0.0,
        "entry_value": 0.0,
        "stop_value": 0.0,
        "suggested_stop_spx": 0.0,
        "contracts": int(primary_play["contracts"]) if primary_play else 1,
        "confidence_note": signal_package["scenario"]["confidence_level"] if signal_package else "",
        "confirmation_status": "Not Recorded",
        "linked_snapshot_id": "",
        "linked_snapshot_date": "",
        "notes": f"Confidence: {signal_package['scenario']['confidence_level']}" if signal_package else "",
        "selected_contract_symbol": "",
        "option_mark_at_decision": 0.0,
        "current_mark": 0.0,
        "predicted_entry_price": 0.0,
        "planned_entry_mark": 0.0,
        "live_predicted_entry_mark": 0.0,
        "lock_cutoff": "",
        "session_plan_locked": False,
        "locked_timestamp": "",
        "locked_entry_spx": 0.0,
        "locked_entry_es": 0.0,
        "locked_entry_mark": 0.0,
        "locked_strike": "",
        "locked_direction": "",
        "locked_stop_spx": 0.0,
        "locked_suggested_stop_spx": 0.0,
        "locked_expected_gain": 0.0,
        "locked_expected_loss": 0.0,
        "locked_rr_ratio": 0.0,
        "locked_contract_symbol": "",
        "locked_contract_score": 0.0,
        "play_role": "primary",
        "plan_locked": False,
        "lock_cutoff_used": "",
        "plan_locked_timestamp": "",
        "final_decision_at_lock": "",
        "scenario_origin": signal_package["scenario"]["scenario_name"] if signal_package else "",
        "live_scenario": "",
        "previous_live_scenario": "",
        "live_structure_state": "",
        "previous_structure_state": "",
        "structure_transition": "",
        "scenario_transition": "",
        "live_state_timestamp": "",
        "entry_zone_status": "",
        "move_completion_pct": 0.0,
        "current_spx_at_decision": 0.0,
        "current_es_at_decision": 0.0,
        "current_mark_at_decision": 0.0,
        "best_contract_selected": False,
        "expected_gain": 0.0,
        "expected_loss": 0.0,
        "rr_ratio": 0.0,
        "contract_score": 0.0,
        "regime": "",
        "plan_status": "",
        "chase_status": "",
        "prediction_confidence": "",
        "final_decision": "",
        "final_authority_decision": "",
        "final_authority_confidence": 0.0,
        "final_authority_expected_value": 0.0,
        "final_authority_risk_class": "",
        "final_authority_reason": "",
        "final_authority_top_reasons": [],
        "expected_return_20": 0.0,
        "expected_return_50": 0.0,
        "expected_return_100": 0.0,
        "decision_state_at_action": "",
        "override_flag": False,
        "override_reason": "",
        "entry_drift_abs": 0.0,
        "entry_drift_pct": 0.0,
        "price_vs_plan": 0.0,
        "stop_quality": "",
        "trade_quality": "",
        "actual_trade_taken": False,
        "actual_entry_price_option": 0.0,
        "actual_entry_price_spx": 0.0,
        "actual_contract_symbol": "",
        "actual_contract_mark_if_known": 0.0,
        "actual_stop_used": 0.0,
        "actual_exit_price_option": 0.0,
        "actual_exit_price_spx": 0.0,
        "actual_exit_reason": "",
        "actual_contracts": 1,
        "actual_notes": "",
        "integrity_flags": [],
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

    selected_contract = st.session_state.get("tab1_primary_selected_contract", {})
    strike_or_contract_label = selected_contract.get("contract_symbol") or str(primary_play["strike"])
    notes = [f"Confidence: {signal_package['scenario']['confidence_level']}"]
    if selected_contract.get("option_mark_at_decision") is not None:
        notes.append(f"Option mark at decision: {format_price(selected_contract['option_mark_at_decision'])}")
    if selected_contract.get("predicted_entry_price") is not None:
        notes.append(f"Predicted entry price: {format_price(selected_contract['predicted_entry_price'])}")
    if selected_contract.get("contract_symbol"):
        notes.append(f"Selected contract: {selected_contract['contract_symbol']}")
    if selected_contract.get("stop_value") is not None:
        notes.append(f"Stop: {format_price(selected_contract['stop_value'])}")
    if selected_contract.get("integrity_flags"):
        notes.append(f"Flags: {', '.join(selected_contract['integrity_flags'])}")

    return {
        "source": "Tab 1 primary play",
        "trade_date": current_central_time().date().isoformat(),
        "session": "NY Options",
        "scenario_name": signal_package["scenario"]["scenario_name"],
        "direction": primary_play["direction"],
        "strike_or_contract_label": strike_or_contract_label,
        "entry_line_label": primary_play["entry"]["label"],
        "entry_line_value": float(primary_play["entry"]["price"]),
        "entry_value": float(selected_contract["option_mark_at_decision"]) if selected_contract.get("option_mark_at_decision") is not None else 0.0,
        "contracts": int(primary_play["contracts"]),
        "confidence_note": signal_package["scenario"]["confidence_level"],
        "confirmation_status": "Not Recorded",
        "linked_snapshot_id": "",
        "linked_snapshot_date": "",
        "notes": " | ".join(notes),
        "selected_contract_symbol": selected_contract.get("contract_symbol", ""),
        "option_mark_at_decision": float(selected_contract["option_mark_at_decision"]) if selected_contract.get("option_mark_at_decision") is not None else 0.0,
        "predicted_entry_price": float(selected_contract["predicted_entry_price"]) if selected_contract.get("predicted_entry_price") is not None else 0.0,
        "stop_value": float(selected_contract["stop_value"]) if selected_contract.get("stop_value") is not None else 0.0,
        "expected_gain": float(selected_contract["expected_gain"]) if selected_contract.get("expected_gain") is not None else 0.0,
        "expected_loss": float(selected_contract["expected_loss"]) if selected_contract.get("expected_loss") is not None else 0.0,
        "rr_ratio": float(selected_contract["rr_ratio"]) if selected_contract.get("rr_ratio") is not None else 0.0,
        "contract_score": float(selected_contract["contract_score"]) if selected_contract.get("contract_score") is not None else 0.0,
        "integrity_flags": list(selected_contract.get("integrity_flags", [])),
    }


def build_live_play_trade_prefill(
    *,
    signal_package: dict[str, Any],
    play_type: str,
    play_spx: dict[str, Any],
    play_es: dict[str, Any] | None,
    lead_option_quote: dict[str, Any] | None,
    intelligence: dict[str, Any],
    final_status: str,
    final_decision: str | None = None,
    authority: dict[str, Any] | None = None,
    live_context: dict[str, Any] | None = None,
    override_flag: bool = False,
    override_reason: str = "",
) -> dict[str, Any]:
    """Build a trade-log prefill from the exact visible live play snapshot."""

    notes = [f"Confidence: {signal_package['scenario']['confidence_level']}", f"Final status: {final_status}"]
    contract_symbol = lead_option_quote.get("contract_symbol", "") if lead_option_quote else ""
    current_mark = float(lead_option_quote["price"]) if lead_option_quote and lead_option_quote.get("price") is not None else 0.0
    predicted_entry = float(lead_option_quote["predicted_entry_price"]) if lead_option_quote and lead_option_quote.get("predicted_entry_price") is not None else 0.0
    expected_gain = float(lead_option_quote["expected_gain"]) if lead_option_quote and lead_option_quote.get("expected_gain") is not None else 0.0
    expected_loss = float(lead_option_quote["expected_loss"]) if lead_option_quote and lead_option_quote.get("expected_loss") is not None else 0.0
    rr_ratio = float(lead_option_quote["rr_ratio"]) if lead_option_quote and lead_option_quote.get("rr_ratio") is not None else 0.0
    contract_score = float(lead_option_quote["contract_score"]) if lead_option_quote and lead_option_quote.get("contract_score") is not None else 0.0
    stop_spx = float(play_spx["stop"]["price"]) if play_spx.get("stop") else 0.0
    entry_es = float(play_es["entry"]["price"]) if play_es and play_es.get("entry") else 0.0
    locked_entry_spx = float(intelligence.get("locked_entry_spx") or play_spx["entry"]["price"])

    return {
        "source": f"Tab 1 {play_type} play",
        "trade_date": current_central_time().date().isoformat(),
        "session": "NY Options",
        "scenario_name": signal_package["scenario"]["scenario_name"],
        "play_type": play_type,
        "direction": play_spx["direction"],
        "strike_or_contract_label": contract_symbol or str(play_spx["strike"]),
        "entry_line_label": play_spx["entry"]["label"],
        "entry_line_value": locked_entry_spx,
        "entry_spx": locked_entry_spx,
        "entry_es": entry_es,
        "entry_value": current_mark,
        "stop_value": stop_spx,
        "suggested_stop_spx": float(intelligence.get("suggested_stop") or 0.0),
        "contracts": int(play_spx["contracts"]),
        "confidence_note": signal_package["scenario"]["confidence_level"],
        "confirmation_status": "Not Recorded",
        "linked_snapshot_id": "",
        "linked_snapshot_date": "",
        "notes": " | ".join(notes),
        "selected_contract_symbol": contract_symbol,
        "option_mark_at_decision": current_mark,
        "current_mark": current_mark,
        "predicted_entry_price": predicted_entry,
        "planned_entry_mark": float(intelligence.get("planned_entry_mark") or 0.0),
        "live_predicted_entry_mark": float(intelligence.get("live_predicted_entry_mark") or 0.0),
        "lock_cutoff": str(intelligence.get("lock_cutoff_label") or ""),
        "session_plan_locked": bool(intelligence.get("session_plan_locked")),
        "locked_timestamp": str(intelligence.get("locked_timestamp") or ""),
        "locked_entry_spx": float(intelligence.get("locked_entry_spx") or play_spx["entry"]["price"]),
        "locked_entry_es": entry_es,
        "locked_entry_mark": float(intelligence.get("planned_entry_mark") or 0.0),
        "locked_strike": str(play_spx.get("strike", "")),
        "locked_direction": str(play_spx.get("direction", "")),
        "locked_stop_spx": stop_spx,
        "locked_suggested_stop_spx": float(intelligence.get("suggested_stop") or 0.0),
        "locked_expected_gain": expected_gain,
        "locked_expected_loss": expected_loss,
        "locked_rr_ratio": rr_ratio,
        "locked_contract_symbol": contract_symbol,
        "locked_contract_score": contract_score,
        "play_role": play_type,
        "plan_locked": bool(intelligence.get("session_plan_locked")),
        "lock_cutoff_used": str(intelligence.get("lock_cutoff_label") or ""),
        "plan_locked_timestamp": str(intelligence.get("locked_timestamp") or ""),
        "final_decision_at_lock": str(final_decision or final_status),
        "scenario_origin": str((live_context or {}).get("scenario_origin", signal_package["scenario"]["scenario_name"])),
        "live_scenario": str((live_context or {}).get("live_scenario", "")),
        "previous_live_scenario": str((live_context or {}).get("previous_live_scenario", "")),
        "live_structure_state": str((live_context or {}).get("live_structure_state", "")),
        "previous_structure_state": str((live_context or {}).get("previous_structure_state", "")),
        "structure_transition": str((live_context or {}).get("structure_transition", "")),
        "scenario_transition": str((live_context or {}).get("scenario_transition", "")),
        "live_state_timestamp": str((live_context or {}).get("live_state_timestamp", "")),
        "entry_zone_status": str(intelligence.get("entry_zone_status", "")),
        "move_completion_pct": float(intelligence.get("move_completion_pct") or 0.0),
        "current_spx_at_decision": float(lead_option_quote.get("spx_price_at_lookup")) if lead_option_quote and lead_option_quote.get("spx_price_at_lookup") is not None else 0.0,
        "current_es_at_decision": float(lead_option_quote.get("es_price_at_lookup")) if lead_option_quote and lead_option_quote.get("es_price_at_lookup") is not None else 0.0,
        "current_mark_at_decision": current_mark,
        "best_contract_selected": bool(contract_symbol),
        "expected_gain": expected_gain,
        "expected_loss": expected_loss,
        "rr_ratio": rr_ratio,
        "contract_score": contract_score,
        "regime": str(intelligence.get("regime", "")),
        "plan_status": str(intelligence.get("plan_status", "")),
        "chase_status": str(intelligence.get("chase_status", "")),
        "prediction_confidence": str(intelligence.get("prediction_confidence", "")),
        "final_decision": str(final_decision or final_status_to_action(final_status, signal_package)),
        "final_authority_decision": str((authority or {}).get("decision", "")),
        "final_authority_confidence": float((authority or {}).get("confidence_score", 0.0) or 0.0),
        "final_authority_expected_value": float((authority or {}).get("expected_value", 0.0) or 0.0),
        "final_authority_risk_class": str((authority or {}).get("risk_class", "")),
        "final_authority_reason": str((authority or {}).get("reason_line", "")),
        "final_authority_top_reasons": list((authority or {}).get("top_reasons", [])),
        "expected_return_20": float((authority or {}).get("expected_return_20", 0.0) or 0.0),
        "expected_return_50": float((authority or {}).get("expected_return_50", 0.0) or 0.0),
        "expected_return_100": float((authority or {}).get("expected_return_100", 0.0) or 0.0),
        "decision_state_at_action": str((authority or {}).get("decision_state", final_decision or final_status)),
        "override_flag": bool(override_flag),
        "override_reason": str(override_reason or ""),
        "entry_drift_abs": float(intelligence.get("entry_drift_abs") or 0.0),
        "entry_drift_pct": float(intelligence.get("entry_drift_pct") or 0.0),
        "price_vs_plan": float(intelligence.get("price_vs_plan") or 0.0),
        "stop_quality": str(intelligence.get("stop_quality", "")),
        "trade_quality": str(intelligence.get("quality", "")),
        "actual_trade_taken": False,
        "actual_entry_price_option": 0.0,
        "actual_entry_price_spx": 0.0,
        "actual_contract_symbol": contract_symbol,
        "actual_contract_mark_if_known": 0.0,
        "actual_stop_used": stop_spx,
        "actual_exit_price_option": 0.0,
        "actual_exit_price_spx": 0.0,
        "actual_exit_reason": "",
        "actual_contracts": int(play_spx["contracts"]),
        "actual_notes": "",
        "integrity_flags": list(play_spx.get("integrity_flags", [])),
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


def normalize_option_candidate_rows(candidates: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Normalize provider candidate rows for the app table."""

    normalized_rows: list[dict[str, Any]] = []
    for candidate in candidates or []:
        normalized_rows.append(
            {
                "contract_symbol": candidate.get("symbol", ""),
                "option_type": candidate.get("option_type") or candidate.get("right", ""),
                "strike": candidate.get("strike", ""),
                "expiration": candidate.get("expiration") or candidate.get("expiration_date", ""),
                "bid": candidate.get("bid", ""),
                "ask": candidate.get("ask", ""),
                "last": candidate.get("last", ""),
                "mark": candidate.get("mark", ""),
                "volume": candidate.get("volume", ""),
                "open_interest": candidate.get("open_interest", ""),
                "delta": candidate.get("delta", ""),
                "gamma": candidate.get("gamma", ""),
                "theta": candidate.get("theta", ""),
                "vega": candidate.get("vega", ""),
                "implied_volatility": candidate.get("implied_volatility", ""),
                "predicted_entry_price": candidate.get("predicted_entry_price", ""),
                "expected_gain": candidate.get("expected_gain", ""),
                "expected_loss": candidate.get("expected_loss", ""),
                "rr_ratio": candidate.get("rr_ratio", ""),
                "contract_score": candidate.get("contract_score", ""),
                "selection": candidate.get("selection_label", ""),
                "integrity_flags": ", ".join(candidate.get("integrity_flags", [])),
            }
        )
    return normalized_rows


def _to_float_or_none(value: Any) -> float | None:
    """Return a float when the value is numeric-like, otherwise None."""

    try:
        if value in {"", None}:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive_price_or_none(value: Any) -> float | None:
    """Return a positive numeric price when available."""

    parsed = _to_float_or_none(value)
    if parsed is None or abs(parsed) < 1e-9:
        return None
    return float(parsed)


def derive_outcome_tracking_fields(trade: dict[str, Any]) -> dict[str, Any]:
    """Derive outcome-tracking and learning-loop fields from a stored trade snapshot."""

    planned_entry_mark = _positive_price_or_none(trade.get("planned_entry_mark")) or _positive_price_or_none(trade.get("locked_entry_mark"))
    live_predicted_entry_mark = _positive_price_or_none(trade.get("live_predicted_entry_mark")) or _positive_price_or_none(trade.get("predicted_entry_price"))
    current_mark_at_decision = _positive_price_or_none(trade.get("current_mark_at_decision")) or _positive_price_or_none(trade.get("current_mark")) or _positive_price_or_none(trade.get("option_mark_at_decision"))
    current_spx_at_decision = _positive_price_or_none(trade.get("current_spx_at_decision")) or _positive_price_or_none(trade.get("entry_spx"))
    current_es_at_decision = _positive_price_or_none(trade.get("current_es_at_decision")) or _positive_price_or_none(trade.get("entry_es"))
    locked_entry_spx = _positive_price_or_none(trade.get("locked_entry_spx")) or _positive_price_or_none(trade.get("entry_spx"))
    locked_entry_es = _positive_price_or_none(trade.get("locked_entry_es")) or _positive_price_or_none(trade.get("entry_es"))
    locked_entry_mark = _positive_price_or_none(trade.get("locked_entry_mark")) or planned_entry_mark

    actual_trade_taken = bool(trade.get("actual_trade_taken", False))
    actual_entry_price_option = _positive_price_or_none(trade.get("actual_entry_price_option"))
    actual_entry_price_spx = _positive_price_or_none(trade.get("actual_entry_price_spx"))
    actual_exit_price_option = _positive_price_or_none(trade.get("actual_exit_price_option"))
    actual_exit_price_spx = _positive_price_or_none(trade.get("actual_exit_price_spx"))

    prediction_anchor = live_predicted_entry_mark or planned_entry_mark
    prediction_error_abs = (
        round_price(abs(actual_entry_price_option - prediction_anchor))
        if actual_entry_price_option is not None and prediction_anchor is not None
        else None
    )
    prediction_error_signed = (
        round_price(actual_entry_price_option - prediction_anchor)
        if actual_entry_price_option is not None and prediction_anchor is not None
        else None
    )
    prediction_error_pct = (
        round(prediction_error_abs / max(abs(prediction_anchor), 0.01), 4)
        if prediction_error_abs is not None and prediction_anchor is not None
        else None
    )
    fill_slippage_abs = (
        round_price(actual_entry_price_option - current_mark_at_decision)
        if actual_entry_price_option is not None and current_mark_at_decision is not None
        else None
    )
    fill_slippage_signed = fill_slippage_abs
    fill_slippage_pct = (
        round(fill_slippage_abs / max(abs(current_mark_at_decision), 0.01), 4)
        if fill_slippage_abs is not None and current_mark_at_decision is not None
        else None
    )
    plan_vs_actual_entry_gap = (
        round_price(actual_entry_price_spx - locked_entry_spx)
        if actual_entry_price_spx is not None and locked_entry_spx is not None
        else None
    )

    realized_move = (
        round_price(actual_exit_price_option - actual_entry_price_option)
        if actual_entry_price_option is not None and actual_exit_price_option is not None
        else None
    )
    realized_gain = round_price(max(realized_move or 0.0, 0.0)) if realized_move is not None else None
    realized_loss = round_price(max(-(realized_move or 0.0), 0.0)) if realized_move is not None else None
    actual_rr_if_available = (
        round(realized_gain / realized_loss, 3)
        if realized_gain is not None and realized_loss is not None and realized_loss > 0
        else None
    )

    expected_gain = _positive_price_or_none(trade.get("locked_expected_gain")) or _positive_price_or_none(trade.get("expected_gain"))
    expected_loss = _positive_price_or_none(trade.get("locked_expected_loss")) or _positive_price_or_none(trade.get("expected_loss"))
    expected_vs_realized_gain_gap = (
        round_price(realized_gain - expected_gain)
        if realized_gain is not None and expected_gain is not None
        else None
    )
    expected_vs_realized_loss_gap = (
        round_price(realized_loss - expected_loss)
        if realized_loss is not None and expected_loss is not None
        else None
    )

    normalized_result = normalize_result_value(trade.get("result", ""))
    final_decision = str(trade.get("final_decision", "") or "").upper()
    regime = str(trade.get("regime", "") or "").upper()
    chase_status = str(trade.get("chase_status", "") or "").upper()
    plan_status = str(trade.get("plan_status", "") or "").upper()
    stop_quality = str(trade.get("stop_quality", "") or "").upper()
    entry_zone_status = str(trade.get("entry_zone_status", "") or "").upper()

    if actual_trade_taken:
        if actual_entry_price_option is None:
            trade_outcome_class = "INCOMPLETE"
        elif normalized_result == "Win":
            trade_outcome_class = "WIN"
        elif normalized_result == "Loss" or normalized_result == "Time Stop":
            trade_outcome_class = "LOSS"
        elif normalized_result == "Breakeven":
            trade_outcome_class = "BREAKEVEN"
        else:
            trade_outcome_class = "UNREVIEWED"
    else:
        if (
            actual_entry_price_option is None
            and actual_exit_price_option is None
            and actual_exit_price_spx is None
            and not str(trade.get("actual_exit_reason", "")).strip()
            and normalized_result == "Breakeven"
        ):
            trade_outcome_class = "UNREVIEWED"
        elif normalized_result == "Win":
            trade_outcome_class = "MISSED_WIN"
        elif normalized_result == "Loss" or normalized_result == "Time Stop":
            trade_outcome_class = "MISSED_LOSS"
        elif normalized_result == "Breakeven":
            trade_outcome_class = "BREAKEVEN"
        else:
            trade_outcome_class = "UNREVIEWED"

    if trade_outcome_class == "UNREVIEWED":
        decision_correctness = "UNREVIEWED"
    elif final_decision == "SKIP TRADE":
        decision_correctness = "WRONG_SKIP" if trade_outcome_class in {"WIN", "MISSED_WIN"} else "CORRECT_SKIP"
    else:
        decision_correctness = "CORRECT_ENTRY" if trade_outcome_class in {"WIN", "MISSED_WIN"} else "WRONG_ENTRY"

    if trade_outcome_class == "UNREVIEWED":
        regime_correctness = "UNREVIEWED"
    elif regime == "PULLBACK":
        if entry_zone_status in {"IN ZONE", "APPROACHING"} and trade_outcome_class in {"WIN", "MISSED_WIN", "BREAKEVEN"}:
            regime_correctness = "CORRECT"
        elif entry_zone_status == "MISSED":
            regime_correctness = "WRONG"
        else:
            regime_correctness = "PARTIAL"
    elif regime == "EXPANSION":
        if trade_outcome_class in {"WIN", "MISSED_WIN"} and chase_status in {"ENTER NOW", "ENTER WITH CAUTION"}:
            regime_correctness = "CORRECT"
        elif trade_outcome_class in {"LOSS", "MISSED_LOSS", "BREAKEVEN"} and chase_status in {"WAIT", "CHASE NOT ALLOWED"}:
            regime_correctness = "CORRECT"
        else:
            regime_correctness = "PARTIAL"
    else:
        regime_correctness = "UNREVIEWED"

    if trade_outcome_class == "UNREVIEWED":
        chase_correctness = "UNREVIEWED"
    elif chase_status in {"ENTER NOW", "ENTER WITH CAUTION"}:
        chase_correctness = "CORRECT" if trade_outcome_class in {"WIN", "MISSED_WIN"} else "WRONG"
    elif chase_status in {"WAIT", "CHASE NOT ALLOWED"}:
        chase_correctness = "CORRECT" if trade_outcome_class in {"LOSS", "MISSED_LOSS", "BREAKEVEN"} else "WRONG"
    else:
        chase_correctness = "UNREVIEWED"

    if trade_outcome_class == "UNREVIEWED":
        stop_quality_correctness = "UNREVIEWED"
    elif stop_quality in {"WIDE", "VERY WIDE"}:
        stop_quality_correctness = "CORRECT" if trade_outcome_class in {"LOSS", "MISSED_LOSS"} else "WRONG"
    elif stop_quality in {"TIGHT", "BALANCED"}:
        stop_quality_correctness = "CORRECT" if trade_outcome_class in {"WIN", "MISSED_WIN"} else "WRONG"
    else:
        stop_quality_correctness = "UNREVIEWED"

    return {
        "plan_locked": bool(trade.get("plan_locked", trade.get("session_plan_locked", False))),
        "lock_cutoff_used": str(trade.get("lock_cutoff_used", trade.get("lock_cutoff", ""))),
        "plan_locked_timestamp": str(trade.get("plan_locked_timestamp", trade.get("locked_timestamp", ""))),
        "play_role": str(trade.get("play_role", trade.get("play_type", ""))),
        "final_decision_at_lock": str(trade.get("final_decision_at_lock", trade.get("final_decision", ""))),
        "locked_entry_spx": locked_entry_spx,
        "locked_entry_es": locked_entry_es,
        "locked_entry_mark": locked_entry_mark,
        "locked_strike": str(trade.get("locked_strike", trade.get("strike_or_contract_label", ""))),
        "locked_direction": str(trade.get("locked_direction", trade.get("direction", ""))),
        "locked_stop_spx": _positive_price_or_none(trade.get("locked_stop_spx")) or _positive_price_or_none(trade.get("stop_value")),
        "locked_suggested_stop_spx": _positive_price_or_none(trade.get("locked_suggested_stop_spx")) or _positive_price_or_none(trade.get("suggested_stop_spx")),
        "locked_expected_gain": expected_gain,
        "locked_expected_loss": expected_loss,
        "locked_rr_ratio": _to_float_or_none(trade.get("locked_rr_ratio")) or _to_float_or_none(trade.get("rr_ratio")),
        "locked_contract_symbol": str(trade.get("locked_contract_symbol", trade.get("selected_contract_symbol", ""))),
        "locked_contract_score": _to_float_or_none(trade.get("locked_contract_score")) or _to_float_or_none(trade.get("contract_score")),
        "current_spx_at_decision": current_spx_at_decision,
        "current_es_at_decision": current_es_at_decision,
        "current_mark_at_decision": current_mark_at_decision,
        "actual_trade_taken": actual_trade_taken,
        "actual_entry_price_option": actual_entry_price_option,
        "actual_entry_price_spx": actual_entry_price_spx,
        "actual_contract_symbol": str(trade.get("actual_contract_symbol", trade.get("selected_contract_symbol", ""))),
        "actual_contract_mark_if_known": _positive_price_or_none(trade.get("actual_contract_mark_if_known")) or actual_entry_price_option,
        "actual_stop_used": _positive_price_or_none(trade.get("actual_stop_used")) or _positive_price_or_none(trade.get("stop_value")),
        "actual_exit_price_option": actual_exit_price_option,
        "actual_exit_price_spx": actual_exit_price_spx,
        "actual_exit_reason": str(trade.get("actual_exit_reason", trade.get("result", ""))),
        "actual_contracts": int(trade.get("actual_contracts", trade.get("contracts", 1)) or 1),
        "actual_notes": str(trade.get("actual_notes", trade.get("notes", ""))),
        "prediction_error_abs": prediction_error_abs,
        "prediction_error_signed": prediction_error_signed,
        "prediction_error_pct": prediction_error_pct,
        "fill_slippage_abs": fill_slippage_abs,
        "fill_slippage_signed": fill_slippage_signed,
        "fill_slippage_pct": fill_slippage_pct,
        "plan_vs_actual_entry_gap": plan_vs_actual_entry_gap,
        "trade_outcome_class": trade_outcome_class,
        "decision_correctness": decision_correctness,
        "regime_correctness": regime_correctness,
        "chase_correctness": chase_correctness,
        "stop_quality_correctness": stop_quality_correctness,
        "expected_vs_realized_gain_gap": expected_vs_realized_gain_gap,
        "expected_vs_realized_loss_gap": expected_vs_realized_loss_gap,
        "actual_rr_if_available": actual_rr_if_available,
        "realized_gain": realized_gain,
        "realized_loss": realized_loss,
    }


CALIBRATION_MIN_SAMPLES = 5
CONFIDENCE_RELIABILITY_THRESHOLDS = {
    "HIGH": 0.10,
    "MEDIUM": 0.20,
    "LOW": 0.35,
}
ADAPTIVE_ENGINE_MIN_SAMPLES = 10
ADAPTATION_STRENGTH_FACTOR = 0.5
ADAPTIVE_RR_VARIANCE_THRESHOLD = 1.0
ADAPTIVE_CHASE_VARIANCE_THRESHOLD = 36.0
ADAPTIVE_CONFIDENCE_VARIANCE_THRESHOLD = 0.23


def build_bias_breakdown_dataframe(
    trades: list[dict[str, Any]],
    *,
    group_field: str,
    metric_field: str,
    min_samples: int = CALIBRATION_MIN_SAMPLES,
) -> pd.DataFrame:
    """Build grouped bias summaries for calibration diagnostics."""

    rows = [derive_outcome_tracking_fields(trade) | trade for trade in trades]
    working = pd.DataFrame(rows)
    if working.empty or group_field not in working.columns or metric_field not in working.columns:
        return pd.DataFrame()
    working = working.loc[working[metric_field].notna() & working[group_field].notna()].copy()
    if working.empty:
        return pd.DataFrame()
    grouped = (
        working.groupby(group_field)[metric_field]
        .agg(["count", "mean", "median"])
        .reset_index()
        .rename(
            columns={
                group_field: "group",
                "count": "samples",
                "mean": "avg_bias",
                "median": "median_bias",
            }
        )
    )
    grouped = grouped.loc[grouped["samples"] >= min_samples].copy()
    if grouped.empty:
        return pd.DataFrame()
    grouped["avg_bias"] = grouped["avg_bias"].round(2)
    grouped["median_bias"] = grouped["median_bias"].round(2)
    return grouped.sort_values(by="samples", ascending=False)


def build_confidence_calibration_dataframe(trades: list[dict[str, Any]]) -> pd.DataFrame:
    """Measure how reliable the existing confidence labels have been."""

    rows = [derive_outcome_tracking_fields(trade) | trade for trade in trades]
    working = pd.DataFrame(rows)
    if working.empty or "prediction_confidence" not in working.columns:
        return pd.DataFrame()
    working = working.loc[working["prediction_confidence"].astype(str).str.len() > 0].copy()
    if working.empty:
        return pd.DataFrame()

    def _is_reliable(row: pd.Series) -> bool | None:
        confidence = str(row.get("prediction_confidence", "")).upper()
        threshold = CONFIDENCE_RELIABILITY_THRESHOLDS.get(confidence)
        error_pct = row.get("prediction_error_pct")
        if threshold is None or pd.isna(error_pct):
            return None
        return float(error_pct) <= threshold

    working["reliable"] = working.apply(_is_reliable, axis=1)
    working = working.loc[working["reliable"].notna()].copy()
    if working.empty:
        return pd.DataFrame()
    grouped = (
        working.groupby("prediction_confidence")["reliable"]
        .agg(["count", "mean"])
        .reset_index()
        .rename(columns={"prediction_confidence": "confidence", "count": "samples", "mean": "accuracy_pct"})
    )
    grouped["accuracy_pct"] = (grouped["accuracy_pct"] * 100.0).round(2)
    return grouped.sort_values(by="confidence")


def build_chase_calibration_dataframe(trades: list[dict[str, Any]]) -> pd.DataFrame:
    """Measure chase correctness by chase status and regime."""

    rows = [derive_outcome_tracking_fields(trade) | trade for trade in trades]
    working = pd.DataFrame(rows)
    if working.empty:
        return pd.DataFrame()
    working = working.loc[working["chase_correctness"].isin(["CORRECT", "WRONG"])].copy()
    if working.empty:
        return pd.DataFrame()
    grouped = (
        working.groupby(["chase_status", "regime"])["chase_correctness"]
        .agg(
            samples="count",
            correct_pct=lambda values: (values.eq("CORRECT").mean() * 100.0),
        )
        .reset_index()
    )
    grouped["correct_pct"] = grouped["correct_pct"].round(2)
    return grouped.sort_values(by=["samples", "correct_pct"], ascending=[False, False])


def resolve_calibration_preview(
    trades: list[dict[str, Any]],
    prefill: dict[str, Any],
    *,
    min_samples: int = CALIBRATION_MIN_SAMPLES,
) -> dict[str, Any]:
    """Build a deterministic calibrated entry/fill estimate for the active prefill."""

    base_entry = _positive_price_or_none(prefill.get("live_predicted_entry_mark")) or _positive_price_or_none(prefill.get("predicted_entry_price")) or _positive_price_or_none(prefill.get("planned_entry_mark"))
    if base_entry is None:
        return {
            "calibrated_entry_mark": None,
            "expected_fill_mark": None,
            "prediction_bias_used": None,
            "slippage_bias_used": None,
            "prediction_bias_source": "unavailable",
            "slippage_bias_source": "unavailable",
            "prediction_sample_count": 0,
            "slippage_sample_count": 0,
            "evidence_label": "No Evidence",
            "sufficient_data": False,
        }

    prediction_sources = [
        ("scenario_name", str(prefill.get("scenario_name", "")).strip(), "scenario"),
        ("direction", str(prefill.get("direction", "")).strip(), "direction"),
        ("regime", str(prefill.get("regime", "")).strip(), "regime"),
    ]
    slippage_sources = [
        ("scenario_name", str(prefill.get("scenario_name", "")).strip(), "scenario"),
        ("regime", str(prefill.get("regime", "")).strip(), "regime"),
        ("chase_status", str(prefill.get("chase_status", "")).strip(), "chase"),
    ]

    enriched = pd.DataFrame([derive_outcome_tracking_fields(trade) | trade for trade in trades])

    def _resolve_bias(metric_field: str, candidates: list[tuple[str, str, str]]) -> tuple[float | None, str, int]:
        if enriched.empty or metric_field not in enriched.columns:
            return None, "unavailable", 0
        usable = enriched.loc[enriched[metric_field].notna()].copy()
        if usable.empty:
            return None, "unavailable", 0
        for field_name, field_value, label in candidates:
            if not field_value or field_name not in usable.columns:
                continue
            subset = usable.loc[usable[field_name].astype(str) == field_value]
            if len(subset) >= min_samples:
                return round_price(float(subset[metric_field].mean())), label, int(len(subset))
        if len(usable) >= min_samples:
            return round_price(float(usable[metric_field].mean())), "overall", int(len(usable))
        return None, "insufficient", int(len(usable))

    prediction_bias, prediction_bias_source, prediction_sample_count = _resolve_bias("prediction_error_signed", prediction_sources)
    slippage_bias, slippage_bias_source, slippage_sample_count = _resolve_bias("fill_slippage_signed", slippage_sources)
    calibrated_entry_mark = round_price(base_entry + prediction_bias) if prediction_bias is not None else None
    expected_fill_mark = round_price(calibrated_entry_mark + slippage_bias) if calibrated_entry_mark is not None and slippage_bias is not None else None
    usable_sample_count = max(prediction_sample_count, slippage_sample_count)
    evidence_label = (
        "Strong Evidence"
        if usable_sample_count >= min_samples and calibrated_entry_mark is not None
        else "Limited Evidence"
        if usable_sample_count > 0
        else "No Evidence"
    )

    return {
        "calibrated_entry_mark": calibrated_entry_mark,
        "expected_fill_mark": expected_fill_mark,
        "prediction_bias_used": prediction_bias,
        "slippage_bias_used": slippage_bias,
        "prediction_bias_source": prediction_bias_source,
        "slippage_bias_source": slippage_bias_source,
        "prediction_sample_count": prediction_sample_count,
        "slippage_sample_count": slippage_sample_count,
        "evidence_label": evidence_label,
        "sufficient_data": calibrated_entry_mark is not None,
    }


def adaptive_evidence_label(sample_count: int) -> str:
    """Convert sample counts into operator-facing evidence labels."""

    if sample_count >= ADAPTIVE_ENGINE_MIN_SAMPLES * 2:
        return "Strong"
    if sample_count >= ADAPTIVE_ENGINE_MIN_SAMPLES:
        return "Moderate"
    if sample_count > 0:
        return "Weak"
    return "None"


def compute_series_variance(values: pd.Series) -> float | None:
    """Safely compute variance for adaptive stability checks."""

    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if len(numeric) < 2:
        return 0.0 if len(numeric) == 1 else None
    return float(numeric.var())


def resolve_adaptive_metric(
    enriched: pd.DataFrame,
    *,
    metric_field: str,
    candidates: list[tuple[str | None, str | None, str]],
    min_samples: int,
    variance_threshold: float,
) -> dict[str, Any]:
    """Resolve a stable grouped metric with fallback and no-adaptation safety."""

    fallback_path: list[str] = []
    if enriched.empty or metric_field not in enriched.columns:
        return {
            "state": "NO_ADAPTATION",
            "value": None,
            "source": "unavailable",
            "sample_count": 0,
            "variance": None,
            "evidence_level": "None",
            "fallback_path": fallback_path,
        }

    usable = enriched.loc[enriched[metric_field].notna()].copy()
    if usable.empty:
        return {
            "state": "NO_ADAPTATION",
            "value": None,
            "source": "unavailable",
            "sample_count": 0,
            "variance": None,
            "evidence_level": "None",
            "fallback_path": fallback_path,
        }

    for field_name, field_value, label in candidates:
        if label != "overall":
            fallback_path.append(label)
            if not field_name or not field_value or field_name not in usable.columns:
                continue
            subset = usable.loc[usable[field_name].astype(str) == str(field_value)]
        else:
            fallback_path.append("overall")
            subset = usable

        sample_count = int(len(subset))
        if sample_count < min_samples:
            continue

        variance = compute_series_variance(subset[metric_field])
        if variance is not None and variance > variance_threshold:
            continue

        return {
            "state": "ADAPTED",
            "value": round_price(float(pd.to_numeric(subset[metric_field], errors="coerce").dropna().mean())),
            "source": label,
            "sample_count": sample_count,
            "variance": round_price(variance) if variance is not None else None,
            "evidence_level": adaptive_evidence_label(sample_count),
            "fallback_path": fallback_path,
        }

    weak_sample_count = int(len(usable))
    return {
        "state": "NO_ADAPTATION",
        "value": None,
        "source": "insufficient",
        "sample_count": weak_sample_count,
        "variance": compute_series_variance(usable[metric_field]),
        "evidence_level": adaptive_evidence_label(weak_sample_count),
        "fallback_path": fallback_path,
    }


def build_adaptive_edge_metrics(enriched: pd.DataFrame) -> dict[str, float]:
    """Estimate where adaptive filtering may recover edge or reduce risk."""

    wrong_skips = enriched.loc[enriched["decision_correctness"] == "WRONG_SKIP"].copy() if not enriched.empty and "decision_correctness" in enriched.columns else pd.DataFrame()
    reviewed_skips = enriched.loc[enriched["decision_correctness"].isin(["WRONG_SKIP", "CORRECT_SKIP"])].copy() if not enriched.empty and "decision_correctness" in enriched.columns else pd.DataFrame()
    wrong_entries = enriched.loc[enriched["decision_correctness"] == "WRONG_ENTRY"].copy() if not enriched.empty and "decision_correctness" in enriched.columns else pd.DataFrame()
    reviewed_entries = enriched.loc[enriched["decision_correctness"].isin(["WRONG_ENTRY", "CORRECT_ENTRY"])].copy() if not enriched.empty and "decision_correctness" in enriched.columns else pd.DataFrame()

    return {
        "adaptive_edge_gain_estimate": round_price((len(wrong_skips) / len(reviewed_skips)) * 100.0) if not reviewed_skips.empty else 0.0,
        "adaptive_risk_reduction_estimate": round_price((len(wrong_entries) / len(reviewed_entries)) * 100.0) if not reviewed_entries.empty else 0.0,
    }


def resolve_adaptive_overlay(
    trades: list[dict[str, Any]],
    *,
    scenario_name: str,
    regime: str,
    raw_prediction_confidence: str,
    raw_final_decision: str,
    rr_ratio: float | None,
    distance_to_entry: float | None,
    stop_valid: bool,
) -> dict[str, Any]:
    """Build a safe adaptive recommendation overlay without overriding raw logic."""

    enriched = pd.DataFrame([derive_outcome_tracking_fields(trade) | trade for trade in trades])
    if enriched.empty:
        return {
            "adaptive_recommendation": "NO_ADAPTATION",
            "override_flag": False,
            "adaptive_reason": "Insufficient data",
            "adaptive_evidence_level": "None",
            "base_rr_threshold": INTELLIGENCE_MIN_RR,
            "adaptive_rr_threshold": None,
            "adaptive_rr_source": "NO_ADAPTATION",
            "adaptive_rr_evidence_level": "None",
            "adaptive_rr_sample_count": 0,
            "base_chase_tolerance": ENTRY_ZONE_APPROACHING_THRESHOLD,
            "adaptive_chase_tolerance": None,
            "chase_adaptation_source": "NO_ADAPTATION",
            "chase_adaptation_evidence_level": "None",
            "chase_sample_count": 0,
            "raw_prediction_confidence": raw_prediction_confidence,
            "effective_prediction_confidence": raw_prediction_confidence,
            "confidence_adjustment_reason": "Insufficient data",
            "confidence_evidence_level": "None",
            "confidence_sample_count": 0,
            "confidence_source": "NO_ADAPTATION",
            "rr_variance": None,
            "chase_variance": None,
            "confidence_variance": None,
            "rr_fallback_path": [],
            "chase_fallback_path": [],
            "confidence_fallback_path": [],
            "adaptive_edge_gain_estimate": 0.0,
            "adaptive_risk_reduction_estimate": 0.0,
        }

    rr_rows = enriched.loc[enriched["locked_rr_ratio"].notna() & enriched["actual_rr_if_available"].notna()].copy()
    if not rr_rows.empty:
        rr_rows["rr_bias"] = pd.to_numeric(rr_rows["locked_rr_ratio"], errors="coerce") - pd.to_numeric(rr_rows["actual_rr_if_available"], errors="coerce")
    chase_rows = enriched.loc[enriched["plan_vs_actual_entry_gap"].notna()].copy()
    if not chase_rows.empty:
        chase_rows["chase_gap_abs"] = pd.to_numeric(chase_rows["plan_vs_actual_entry_gap"], errors="coerce").abs()
        chase_rows["chase_bias"] = chase_rows["chase_gap_abs"] - ENTRY_ZONE_APPROACHING_THRESHOLD
    confidence_rows = enriched.loc[enriched["prediction_error_pct"].notna() & enriched["prediction_confidence"].notna()].copy()
    if not confidence_rows.empty:
        threshold = CONFIDENCE_RELIABILITY_THRESHOLDS.get(str(raw_prediction_confidence).upper(), CONFIDENCE_RELIABILITY_THRESHOLDS["MEDIUM"])
        confidence_rows["confidence_correct"] = (
            pd.to_numeric(confidence_rows["prediction_error_pct"], errors="coerce") <= threshold
        ).astype(float)

    adaptive_candidates = [
        ("scenario_name", scenario_name, "scenario"),
        ("regime", regime, "regime"),
        (None, None, "overall"),
    ]

    rr_resolution = resolve_adaptive_metric(
        rr_rows,
        metric_field="rr_bias",
        candidates=adaptive_candidates,
        min_samples=ADAPTIVE_ENGINE_MIN_SAMPLES,
        variance_threshold=ADAPTIVE_RR_VARIANCE_THRESHOLD,
    )
    chase_resolution = resolve_adaptive_metric(
        chase_rows,
        metric_field="chase_bias",
        candidates=adaptive_candidates,
        min_samples=ADAPTIVE_ENGINE_MIN_SAMPLES,
        variance_threshold=ADAPTIVE_CHASE_VARIANCE_THRESHOLD,
    )
    confidence_filtered = confidence_rows.loc[confidence_rows["prediction_confidence"].astype(str).str.upper() == str(raw_prediction_confidence).upper()].copy() if not confidence_rows.empty else pd.DataFrame()
    confidence_resolution = resolve_adaptive_metric(
        confidence_filtered,
        metric_field="confidence_correct",
        candidates=adaptive_candidates,
        min_samples=ADAPTIVE_ENGINE_MIN_SAMPLES,
        variance_threshold=ADAPTIVE_CONFIDENCE_VARIANCE_THRESHOLD,
    )

    base_rr_threshold = INTELLIGENCE_MIN_RR
    adaptive_rr_threshold = (
        round_price(max(INTELLIGENCE_MIN_RR_HARD_FLOOR, base_rr_threshold + (float(rr_resolution["value"]) * ADAPTATION_STRENGTH_FACTOR)))
        if rr_resolution["state"] == "ADAPTED" and rr_resolution["value"] is not None
        else None
    )
    base_chase_tolerance = ENTRY_ZONE_APPROACHING_THRESHOLD
    adaptive_chase_tolerance = (
        round_price(max(2.0, base_chase_tolerance + (float(chase_resolution["value"]) * ADAPTATION_STRENGTH_FACTOR)))
        if chase_resolution["state"] == "ADAPTED" and chase_resolution["value"] is not None
        else None
    )

    effective_prediction_confidence = str(raw_prediction_confidence or "LOW").upper() or "LOW"
    confidence_adjustment_reason = "No stable adaptive evidence"
    if confidence_resolution["state"] == "ADAPTED" and confidence_resolution["value"] is not None:
        reliability = float(confidence_resolution["value"])
        if effective_prediction_confidence == "HIGH":
            effective_prediction_confidence = "HIGH" if reliability >= 0.75 else "MEDIUM" if reliability >= 0.55 else "LOW"
        elif effective_prediction_confidence == "MEDIUM":
            effective_prediction_confidence = "HIGH" if reliability >= 0.75 else "MEDIUM" if reliability >= 0.45 else "LOW"
        else:
            effective_prediction_confidence = "MEDIUM" if reliability >= 0.65 else "LOW"
        confidence_adjustment_reason = f"Historical {confidence_resolution['source']} accuracy {round_price(reliability * 100.0)}%"

    raw_action = str(raw_final_decision or "WAIT").upper()
    if rr_resolution["state"] != "ADAPTED" and chase_resolution["state"] != "ADAPTED" and confidence_resolution["state"] != "ADAPTED":
        adaptive_recommendation = "NO_ADAPTATION"
        adaptive_reason = "Insufficient stable evidence"
    elif not stop_valid:
        adaptive_recommendation = "WAIT"
        adaptive_reason = "No valid stop for adaptive overlay"
    elif adaptive_rr_threshold is not None and rr_ratio is not None and rr_ratio < adaptive_rr_threshold:
        adaptive_recommendation = "WAIT"
        adaptive_reason = "Adaptive RR filter is tighter here"
    elif adaptive_chase_tolerance is not None and distance_to_entry is not None and distance_to_entry > adaptive_chase_tolerance:
        adaptive_recommendation = "WAIT"
        adaptive_reason = "Historically this setup extends too far"
    elif effective_prediction_confidence == "LOW":
        adaptive_recommendation = "ENTER WITH CAUTION" if raw_action == "ENTER NOW" else "WAIT"
        adaptive_reason = "Historical accuracy lowers confidence"
    elif raw_action in {"ENTER NOW", "ENTER WITH CAUTION"}:
        adaptive_recommendation = raw_action
        adaptive_reason = "Adaptive layer agrees with current setup"
    elif raw_action == "WAIT":
        adaptive_recommendation = "ENTER WITH CAUTION"
        adaptive_reason = "Adaptive history supports earlier execution"
    else:
        adaptive_recommendation = "ENTER WITH CAUTION"
        adaptive_reason = "Adaptive history suggests missed edge"

    evidence_rank = {"None": 0, "Weak": 1, "Moderate": 2, "Strong": 3}
    adapted_evidence_levels = [
        resolution["evidence_level"]
        for resolution in [rr_resolution, chase_resolution, confidence_resolution]
        if resolution["state"] == "ADAPTED"
    ]
    adaptive_evidence_level = min(adapted_evidence_levels, key=lambda label: evidence_rank.get(label, 0)) if adapted_evidence_levels else "None"

    raw_for_compare = "WAIT" if raw_action == "SKIP TRADE" else raw_action
    edge_metrics = build_adaptive_edge_metrics(enriched)

    return {
        "adaptive_recommendation": adaptive_recommendation,
        "override_flag": adaptive_recommendation not in {"NO_ADAPTATION", raw_for_compare},
        "adaptive_reason": adaptive_reason,
        "adaptive_evidence_level": adaptive_evidence_level,
        "base_rr_threshold": base_rr_threshold,
        "adaptive_rr_threshold": adaptive_rr_threshold,
        "adaptive_rr_source": rr_resolution["source"] if rr_resolution["state"] == "ADAPTED" else "NO_ADAPTATION",
        "adaptive_rr_evidence_level": rr_resolution["evidence_level"],
        "adaptive_rr_sample_count": rr_resolution["sample_count"],
        "base_chase_tolerance": base_chase_tolerance,
        "adaptive_chase_tolerance": adaptive_chase_tolerance,
        "chase_adaptation_source": chase_resolution["source"] if chase_resolution["state"] == "ADAPTED" else "NO_ADAPTATION",
        "chase_adaptation_evidence_level": chase_resolution["evidence_level"],
        "chase_sample_count": chase_resolution["sample_count"],
        "raw_prediction_confidence": raw_prediction_confidence,
        "effective_prediction_confidence": effective_prediction_confidence,
        "confidence_adjustment_reason": confidence_adjustment_reason,
        "confidence_evidence_level": confidence_resolution["evidence_level"],
        "confidence_sample_count": confidence_resolution["sample_count"],
        "confidence_source": confidence_resolution["source"] if confidence_resolution["state"] == "ADAPTED" else "NO_ADAPTATION",
        "rr_variance": rr_resolution["variance"],
        "chase_variance": chase_resolution["variance"],
        "confidence_variance": confidence_resolution["variance"],
        "rr_fallback_path": rr_resolution["fallback_path"],
        "chase_fallback_path": chase_resolution["fallback_path"],
        "confidence_fallback_path": confidence_resolution["fallback_path"],
        "adaptive_edge_gain_estimate": edge_metrics["adaptive_edge_gain_estimate"],
        "adaptive_risk_reduction_estimate": edge_metrics["adaptive_risk_reduction_estimate"],
    }


def get_decision_authority_rank(decision: str) -> int:
    """Rank authority decisions for hero selection."""

    mapping = {
        "STRONG BUY": 3,
        "CONDITIONAL BUY": 2,
        "NO TRADE": 1,
    }
    return mapping.get(str(decision or "").upper(), 0)


def get_history_expectancy_snapshot(
    trades: list[dict[str, Any]],
    *,
    scenario_name: str,
    play_role: str,
    direction: str,
    min_samples: int = 5,
) -> dict[str, Any]:
    """Resolve a deterministic expectancy cohort using historical journal outcomes only."""

    if not trades:
        return {
            "expected_value": None,
            "sample_count": 0,
            "source": "insufficient",
            "evidence": "None",
            "expected_return_20": None,
            "expected_return_50": None,
            "expected_return_100": None,
        }

    enriched = pd.DataFrame([normalize_trade_record(trade) for trade in trades])
    if enriched.empty or "effective_pnl" not in enriched.columns:
        return {
            "expected_value": None,
            "sample_count": 0,
            "source": "insufficient",
            "evidence": "None",
            "expected_return_20": None,
            "expected_return_50": None,
            "expected_return_100": None,
        }

    candidates = [
        (enriched.loc[(enriched["scenario_name"] == scenario_name) & (enriched["play_role"] == play_role)], "scenario / play"),
        (enriched.loc[(enriched["scenario_name"] == scenario_name) & (enriched["direction"] == direction)], "scenario / direction"),
        (enriched.loc[enriched["direction"] == direction], "direction"),
        (enriched, "overall"),
    ]
    for subset, label in candidates:
        if len(subset) >= min_samples:
            expected_value = round_price(float(pd.to_numeric(subset["effective_pnl"], errors="coerce").dropna().mean()))
            sample_count = int(len(subset))
            return {
                "expected_value": expected_value,
                "sample_count": sample_count,
                "source": label,
                "evidence": "Strong" if sample_count >= 15 else "Moderate",
                "expected_return_20": round_price(expected_value * 20.0),
                "expected_return_50": round_price(expected_value * 50.0),
                "expected_return_100": round_price(expected_value * 100.0),
            }

    return {
        "expected_value": None,
        "sample_count": int(len(enriched)),
        "source": "insufficient",
        "evidence": "Weak" if len(enriched) > 0 else "None",
        "expected_return_20": None,
        "expected_return_50": None,
        "expected_return_100": None,
    }


def build_authority_reason_candidates(
    *,
    structure_valid: bool,
    stop_valid: bool,
    rr_ratio: float | None,
    plan_status: str,
    chase_status: str,
    entry_zone_status: str,
    move_completion_pct: float | None,
    prediction_confidence: str,
    calibration_evidence: str,
) -> list[str]:
    """Build ranked human-readable reasons behind the authority decision."""

    reasons: list[str] = []
    reasons.append("Structure valid" if structure_valid else "Structure invalid")
    reasons.append("Valid structural stop" if stop_valid else "No valid structural stop")
    if rr_ratio is None:
        reasons.append("RR unavailable")
    elif rr_ratio >= 1.0:
        reasons.append(f"RR {rr_ratio:.2f} acceptable")
    else:
        reasons.append(f"RR {rr_ratio:.2f} below threshold")
    if plan_status == "HOLDING":
        reasons.append("Plan still holding")
    elif plan_status == "DRIFTING":
        reasons.append("Plan drifting from anchor")
    elif plan_status == "BROKEN":
        reasons.append("Plan broken")
    if chase_status == "CHASE NOT ALLOWED":
        reasons.append("Chase penalty active")
    elif chase_status == "WAIT":
        reasons.append("Wait condition still active")
    elif chase_status == "ENTER WITH CAUTION":
        reasons.append("Entry requires caution")
    elif chase_status == "ENTER NOW":
        reasons.append("Execution path open")
    if entry_zone_status == "IN ZONE":
        reasons.append("Entry still in zone")
    elif entry_zone_status == "APPROACHING":
        reasons.append("Price near planned zone")
    elif entry_zone_status == "MISSED":
        reasons.append("Move already extended")
    if move_completion_pct is not None:
        reasons.append(f"Move {round_price(move_completion_pct)}% complete")
    if prediction_confidence:
        reasons.append(f"{prediction_confidence.title()} prediction confidence")
    if calibration_evidence and calibration_evidence != "No Evidence":
        reasons.append(f"{calibration_evidence} calibration evidence")
    return reasons


def build_play_decision_authority(
    *,
    signal_package: dict[str, Any] | None,
    play: dict[str, Any] | None,
    lead_option_quote: dict[str, Any] | None,
    intelligence: dict[str, Any],
    calibration_preview: dict[str, Any] | None,
    adaptive_overlay: dict[str, Any] | None,
    play_role: str,
    trades: list[dict[str, Any]],
    raw_final_decision: str,
) -> dict[str, Any]:
    """Build one authoritative operator decision without changing strategy logic."""

    if play is None:
        return {
            "decision": "NO TRADE",
            "confidence_score": 0,
            "expected_value": None,
            "risk_class": "HIGH",
            "reason_line": "No active setup",
            "top_reasons": ["No active setup"],
            "condition_required": "",
            "structure_valid": False,
            "stop_valid": False,
            "use_allowed": False,
            "override_required": True,
            "decision_state": "NO TRADE",
            "evidence_level": "None",
            "expected_return_20": None,
            "expected_return_50": None,
            "expected_return_100": None,
            "factor_states": [],
            "raw_final_decision": raw_final_decision,
        }

    structure_valid = bool(play.get("setup_tradable")) and not bool(signal_package and signal_package.get("sit_out", {}).get("sit_out"))
    stop_valid = not bool(play.get("stop_unavailable") or play.get("invalid_stop"))
    rr_ratio = _to_float_or_none(intelligence.get("rr_ratio"))
    move_completion_pct = _to_float_or_none(intelligence.get("move_completion_pct"))
    calibration_evidence = str((calibration_preview or {}).get("evidence_label", "No Evidence"))
    adaptive_evidence = str((adaptive_overlay or {}).get("adaptive_evidence_level", "None"))
    effective_confidence_label = str((adaptive_overlay or {}).get("effective_prediction_confidence", intelligence.get("prediction_confidence", "LOW")))

    confidence_score = 50
    if structure_valid:
        confidence_score += 14
    else:
        confidence_score -= 22
    if stop_valid:
        confidence_score += 12
    else:
        confidence_score -= 28
    if rr_ratio is not None:
        if rr_ratio >= 1.4:
            confidence_score += 14
        elif rr_ratio >= 1.0:
            confidence_score += 8
        elif rr_ratio >= 0.5:
            confidence_score -= 10
        else:
            confidence_score -= 22
    if intelligence.get("plan_status") == "HOLDING":
        confidence_score += 10
    elif intelligence.get("plan_status") == "DRIFTING":
        confidence_score -= 6
    elif intelligence.get("plan_status") == "BROKEN":
        confidence_score -= 16
    if intelligence.get("entry_zone_status") == "IN ZONE":
        confidence_score += 10
    elif intelligence.get("entry_zone_status") == "APPROACHING":
        confidence_score += 5
    elif intelligence.get("entry_zone_status") == "MISSED":
        confidence_score -= 16
    elif intelligence.get("entry_zone_status") == "NOT REACHED":
        confidence_score -= 6
    if intelligence.get("chase_status") == "ENTER NOW":
        confidence_score += 8
    elif intelligence.get("chase_status") == "ENTER WITH CAUTION":
        confidence_score += 3
    elif intelligence.get("chase_status") == "WAIT":
        confidence_score -= 4
    elif intelligence.get("chase_status") == "CHASE NOT ALLOWED":
        confidence_score -= 18
    confidence_score += {"HIGH": 8, "MEDIUM": 3, "LOW": -8}.get(effective_confidence_label.upper(), 0)
    confidence_score += {"Strong": 6, "Moderate": 3, "Weak": 0, "None": 0}.get(calibration_evidence, 0)
    confidence_score = int(max(0, min(100, confidence_score)))

    risk_score = 0
    if not stop_valid:
        risk_score += 3
    if rr_ratio is None or rr_ratio < 1.0:
        risk_score += 2
    if intelligence.get("chase_status") in {"ENTER WITH CAUTION", "CHASE NOT ALLOWED"}:
        risk_score += 1
    if intelligence.get("plan_status") in {"DRIFTING", "BROKEN"}:
        risk_score += 1
    if move_completion_pct is not None and move_completion_pct >= 70:
        risk_score += 1
    if intelligence.get("stop_quality") in {"Tight", "Balanced"} and rr_ratio is not None and rr_ratio >= 1.0:
        risk_score -= 1
    risk_class = "LOW" if risk_score <= 0 else "MEDIUM" if risk_score <= 2 else "HIGH"

    expectancy_snapshot = get_history_expectancy_snapshot(
        trades,
        scenario_name=str(signal_package.get("scenario", {}).get("scenario_name", "")) if signal_package else "",
        play_role=play_role,
        direction=str(play.get("direction", "")),
    )
    expected_value = expectancy_snapshot["expected_value"]

    if not structure_valid or not stop_valid or raw_final_decision == "SKIP TRADE":
        decision = "NO TRADE"
        condition_required = ""
    elif raw_final_decision == "WAIT" or intelligence.get("chase_status") == "WAIT":
        decision = "CONDITIONAL BUY"
        condition_required = "Wait for price to return toward the planned zone"
    elif rr_ratio is None or rr_ratio < 1.0 or intelligence.get("plan_status") == "DRIFTING" or intelligence.get("entry_zone_status") not in {"IN ZONE", "APPROACHING"} or (move_completion_pct is not None and move_completion_pct >= 70):
        decision = "CONDITIONAL BUY"
        if not stop_valid:
            condition_required = "Valid stop required"
        elif intelligence.get("entry_zone_status") not in {"IN ZONE", "APPROACHING"}:
            condition_required = "Price must return closer to the planned zone"
        elif move_completion_pct is not None and move_completion_pct >= 70:
            condition_required = "Entry only if extension cools off"
        else:
            condition_required = "Enter only if price improves toward plan"
    else:
        decision = "STRONG BUY"
        condition_required = ""

    reasons = build_authority_reason_candidates(
        structure_valid=structure_valid,
        stop_valid=stop_valid,
        rr_ratio=rr_ratio,
        plan_status=str(intelligence.get("plan_status", "")),
        chase_status=str(intelligence.get("chase_status", "")),
        entry_zone_status=str(intelligence.get("entry_zone_status", "")),
        move_completion_pct=move_completion_pct,
        prediction_confidence=effective_confidence_label,
        calibration_evidence=calibration_evidence if calibration_evidence != "No Evidence" else adaptive_evidence,
    )
    top_reasons = reasons[:3]

    if decision == "STRONG BUY":
        reason_line = "Structure valid, entry still near planned zone, RR acceptable, no chase penalty"
    elif decision == "CONDITIONAL BUY":
        reason_line = condition_required or "Setup valid but move partially extended"
    elif not stop_valid:
        reason_line = "No valid structural stop"
    elif rr_ratio is not None and rr_ratio < 1.0:
        reason_line = "Poor reward-to-risk at current price"
    else:
        reason_line = "Structure or timing does not justify a trade"

    factor_states = [
        {"label": "Structure", "state": "GOOD" if structure_valid else "BAD"},
        {"label": "Stop", "state": "GOOD" if stop_valid else "BAD"},
        {"label": "RR", "state": "GOOD" if rr_ratio is not None and rr_ratio >= 1.0 else "BAD" if rr_ratio is not None else "WARN"},
        {"label": "Timing", "state": "GOOD" if str(intelligence.get("entry_zone_status")) == "IN ZONE" else "WARN" if str(intelligence.get("entry_zone_status")) == "APPROACHING" else "BAD"},
        {"label": "Confidence", "state": "GOOD" if effective_confidence_label == "HIGH" else "WARN" if effective_confidence_label == "MEDIUM" else "BAD"},
        {"label": "Evidence", "state": "GOOD" if calibration_evidence == "Strong" else "WARN" if calibration_evidence in {"Moderate", "Limited Evidence"} else "BAD"},
    ]

    return {
        "decision": decision,
        "confidence_score": confidence_score,
        "expected_value": expected_value,
        "risk_class": risk_class,
        "reason_line": reason_line,
        "top_reasons": top_reasons,
        "condition_required": condition_required,
        "structure_valid": structure_valid,
        "stop_valid": stop_valid,
        "use_allowed": decision != "NO TRADE",
        "override_required": decision == "NO TRADE",
        "decision_state": decision,
        "evidence_level": calibration_evidence if calibration_evidence != "No Evidence" else adaptive_evidence,
        "expected_return_20": expectancy_snapshot["expected_return_20"],
        "expected_return_50": expectancy_snapshot["expected_return_50"],
        "expected_return_100": expectancy_snapshot["expected_return_100"],
        "expected_value_source": expectancy_snapshot["source"],
        "expected_value_samples": expectancy_snapshot["sample_count"],
        "factor_states": factor_states,
        "raw_final_decision": raw_final_decision,
    }


def choose_hero_authority(primary: dict[str, Any] | None, alternate: dict[str, Any] | None) -> tuple[str, dict[str, Any] | None]:
    """Choose the dominant operator action between primary and alternate."""

    candidates = [("Primary", primary), ("Alternate", alternate)]
    usable = [(label, item) for label, item in candidates if item]
    if not usable:
        return "None", None

    ordered = sorted(
        usable,
        key=lambda item: (
            get_decision_authority_rank(item[1]["decision"]),
            int(item[1].get("confidence_score", 0)),
            float(item[1].get("expected_value") or -9999.0),
            1 if item[0] == "Primary" else 0,
        ),
        reverse=True,
    )
    best_label, best_item = ordered[0]
    if all(item[1]["decision"] == "NO TRADE" for item in usable):
        return "None", {
            **best_item,
            "decision": "NO TRADE",
            "reason_line": "Both plays fail the operator decision filter",
        }
    return best_label, best_item


def build_outcome_review_dataframe(trades: list[dict[str, Any]], *, developer_mode: bool = False) -> pd.DataFrame:
    """Build a compact planned-vs-actual review table."""

    rows: list[dict[str, Any]] = []
    for trade in trades:
        outcome = derive_outcome_tracking_fields(trade)
        row = {
            "date": trade.get("trade_date", ""),
            "scenario": trade.get("scenario_name", ""),
            "play": outcome.get("play_role", ""),
            "decision": trade.get("final_decision", ""),
            "outcome": outcome.get("trade_outcome_class", ""),
            "planned_mark": outcome.get("locked_entry_mark"),
            "actual_mark": outcome.get("actual_entry_price_option"),
            "pred_error": outcome.get("prediction_error_abs"),
            "planned_spx": outcome.get("locked_entry_spx"),
            "actual_spx": outcome.get("actual_entry_price_spx"),
            "entry_gap": outcome.get("plan_vs_actual_entry_gap"),
            "exp_gain": outcome.get("locked_expected_gain"),
            "real_gain": outcome.get("realized_gain"),
            "gain_gap": outcome.get("expected_vs_realized_gain_gap"),
            "exp_loss": outcome.get("locked_expected_loss"),
            "real_loss": outcome.get("realized_loss"),
            "loss_gap": outcome.get("expected_vs_realized_loss_gap"),
            "decision_correct": outcome.get("decision_correctness"),
            "regime_correct": outcome.get("regime_correctness"),
            "chase_correct": outcome.get("chase_correctness"),
            "slippage": outcome.get("fill_slippage_abs"),
        }
        if developer_mode:
            row.update(
                {
                    "plan_status": trade.get("plan_status", ""),
                    "regime": trade.get("regime", ""),
                    "chase": trade.get("chase_status", ""),
                    "entry_zone": trade.get("entry_zone_status", ""),
                    "move_completion_pct": trade.get("move_completion_pct", None),
                }
            )
        rows.append(row)
    return pd.DataFrame(rows)


def build_learning_dashboard_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize prediction quality, decision quality, and plan-integrity feedback."""

    if not trades:
        return {
            "avg_prediction_error": 0.0,
            "median_prediction_error": 0.0,
            "avg_slippage": 0.0,
            "filled_better_pct": 0.0,
            "filled_worse_pct": 0.0,
            "correct_skip_count": 0,
            "wrong_skip_count": 0,
            "correct_entry_count": 0,
            "wrong_entry_count": 0,
            "regime_correct_pct": 0.0,
            "chase_correct_pct": 0.0,
            "holding_good_entry_pct": 0.0,
            "broken_should_skip_pct": 0.0,
            "avg_move_completion_before_entry": 0.0,
            "avg_move_completion_missed": 0.0,
        }

    enriched = [derive_outcome_tracking_fields(trade) | trade for trade in trades]
    prediction_errors = [float(item["prediction_error_abs"]) for item in enriched if item.get("prediction_error_abs") is not None]
    slippages = [float(item["fill_slippage_abs"]) for item in enriched if item.get("fill_slippage_abs") is not None]
    fills = [item for item in enriched if item.get("actual_entry_price_option") is not None and item.get("current_mark_at_decision") is not None]
    regime_reviewed = [item for item in enriched if item.get("regime_correctness") in {"CORRECT", "PARTIAL", "WRONG"}]
    chase_reviewed = [item for item in enriched if item.get("chase_correctness") in {"CORRECT", "WRONG"}]
    holding_rows = [item for item in enriched if str(item.get("plan_status", "")).upper() == "HOLDING"]
    broken_rows = [item for item in enriched if str(item.get("plan_status", "")).upper() == "BROKEN"]
    entered_rows = [item for item in enriched if item.get("actual_trade_taken")]
    missed_rows = [item for item in enriched if item.get("trade_outcome_class") in {"MISSED_WIN", "MISSED_LOSS"}]
    entered_move_completion = [float(item.get("move_completion_pct")) for item in entered_rows if item.get("move_completion_pct") not in {None, ""}]
    missed_move_completion = [float(item.get("move_completion_pct")) for item in missed_rows if item.get("move_completion_pct") not in {None, ""}]

    return {
        "avg_prediction_error": round_price(float(pd.Series(prediction_errors).mean())) if prediction_errors else 0.0,
        "median_prediction_error": round_price(float(pd.Series(prediction_errors).median())) if prediction_errors else 0.0,
        "avg_slippage": round_price(float(pd.Series(slippages).mean())) if slippages else 0.0,
        "filled_better_pct": round_price((sum(1 for item in fills if float(item["actual_entry_price_option"]) <= float(item["current_mark_at_decision"])) / len(fills)) * 100.0) if fills else 0.0,
        "filled_worse_pct": round_price((sum(1 for item in fills if float(item["actual_entry_price_option"]) > float(item["current_mark_at_decision"])) / len(fills)) * 100.0) if fills else 0.0,
        "correct_skip_count": sum(1 for item in enriched if item.get("decision_correctness") == "CORRECT_SKIP"),
        "wrong_skip_count": sum(1 for item in enriched if item.get("decision_correctness") == "WRONG_SKIP"),
        "correct_entry_count": sum(1 for item in enriched if item.get("decision_correctness") == "CORRECT_ENTRY"),
        "wrong_entry_count": sum(1 for item in enriched if item.get("decision_correctness") == "WRONG_ENTRY"),
        "regime_correct_pct": round_price((sum(1 for item in regime_reviewed if item.get("regime_correctness") == "CORRECT") / len(regime_reviewed)) * 100.0) if regime_reviewed else 0.0,
        "chase_correct_pct": round_price((sum(1 for item in chase_reviewed if item.get("chase_correctness") == "CORRECT") / len(chase_reviewed)) * 100.0) if chase_reviewed else 0.0,
        "holding_good_entry_pct": round_price((sum(1 for item in holding_rows if item.get("trade_outcome_class") in {"WIN", "MISSED_WIN"}) / len(holding_rows)) * 100.0) if holding_rows else 0.0,
        "broken_should_skip_pct": round_price((sum(1 for item in broken_rows if item.get("decision_correctness") == "CORRECT_SKIP") / len(broken_rows)) * 100.0) if broken_rows else 0.0,
        "avg_move_completion_before_entry": round_price(float(pd.Series(entered_move_completion).mean())) if entered_move_completion else 0.0,
        "avg_move_completion_missed": round_price(float(pd.Series(missed_move_completion).mean())) if missed_move_completion else 0.0,
    }


def _normalize_series(values: list[float | None], *, higher_is_better: bool = True) -> list[float]:
    """Normalize a list of numeric values onto a 0-1 scale."""

    clean_values = [value for value in values if value is not None]
    if not clean_values:
        return [0.0 for _ in values]

    floor = min(clean_values)
    ceiling = max(clean_values)
    if abs(ceiling - floor) < 1e-9:
        return [1.0 if value is not None else 0.0 for value in values]

    normalized: list[float] = []
    for value in values:
        if value is None:
            normalized.append(0.0)
            continue
        raw = (value - floor) / (ceiling - floor)
        normalized.append(raw if higher_is_better else 1.0 - raw)
    return normalized


def rank_option_candidates(
    candidates: list[dict[str, Any]] | None,
    *,
    play_spx: dict[str, Any] | None,
    current_spx_price: float | None,
) -> list[dict[str, Any]]:
    """Attach prediction and scoring fields to option candidates and sort the best first."""

    if not candidates or play_spx is None:
        return list(candidates or [])

    entry_leg = play_spx.get("entry") if isinstance(play_spx.get("entry"), dict) else {}
    stop_leg = play_spx.get("stop") if isinstance(play_spx.get("stop"), dict) else {}
    target_leg = play_spx.get("tp1") if isinstance(play_spx.get("tp1"), dict) else None
    if not target_leg:
        target_leg = play_spx.get("tp2") if isinstance(play_spx.get("tp2"), dict) else {}

    entry_price = _to_float_or_none(entry_leg.get("price"))
    stop_price = _to_float_or_none(stop_leg.get("price"))
    target_price = _to_float_or_none(target_leg.get("price"))
    stop_valid = not play_spx.get("invalid_stop") and stop_price is not None and entry_price is not None and abs(entry_price - stop_price) >= 1e-9
    if entry_price is None or target_price is None:
        return list(candidates)

    strike_anchor = current_spx_price if is_valid_price_input(current_spx_price) else entry_price
    distance_to_entry_signed = (entry_price - float(current_spx_price)) if is_valid_price_input(current_spx_price) else 0.0
    target_move = abs(target_price - entry_price)
    stop_move = abs(stop_price - entry_price) if stop_valid and stop_price is not None else None

    deltas = [_to_float_or_none(candidate.get("delta")) for candidate in candidates]
    gammas = [_to_float_or_none(candidate.get("gamma")) for candidate in candidates]
    spreads = []
    liquidities = []
    strike_distances = []
    delta_fit = []

    for candidate, delta_value in zip(candidates, deltas, strict=False):
        bid = _to_float_or_none(candidate.get("bid"))
        ask = _to_float_or_none(candidate.get("ask"))
        strike = _to_float_or_none(candidate.get("strike"))
        volume = max(_to_float_or_none(candidate.get("volume")) or 0.0, 0.0)
        open_interest = max(_to_float_or_none(candidate.get("open_interest")) or 0.0, 0.0)
        spread = (ask - bid) if bid is not None and ask is not None else None
        spreads.append(spread if spread is None or spread >= 0 else None)
        liquidities.append(volume + open_interest)
        strike_distances.append(abs(strike - strike_anchor) if strike is not None else None)
        if delta_value is None:
            delta_fit.append(None)
        else:
            delta_fit.append(max(0.0, 1.0 - (abs(abs(delta_value) - 0.60) / 0.60)))

    gamma_scores = _normalize_series(gammas, higher_is_better=True)
    liquidity_scores = _normalize_series(liquidities, higher_is_better=True)
    spread_scores = _normalize_series(spreads, higher_is_better=False)
    distance_scores = _normalize_series(strike_distances, higher_is_better=False)

    ranked_candidates: list[dict[str, Any]] = []
    for idx, candidate in enumerate(candidates):
        enriched = dict(candidate)
        delta_value = deltas[idx]
        absolute_delta = abs(delta_value) if delta_value is not None else 0.0
        mark_value = _to_float_or_none(candidate.get("mark"))
        if mark_value is None:
            mark_value = _to_float_or_none(candidate.get("last"))
        if mark_value is None:
            mark_value = _to_float_or_none(candidate.get("ask"))
        if mark_value is None:
            mark_value = _to_float_or_none(candidate.get("bid"))

        expected_gain = target_move * absolute_delta if delta_value is not None else None
        expected_loss = (stop_move * absolute_delta) if stop_move is not None and delta_value is not None else None
        rr_ratio = (
            expected_gain / expected_loss
            if expected_gain is not None and expected_loss is not None and expected_loss > 0
            else None
        )
        predicted_entry_price = (
            mark_value + (distance_to_entry_signed * delta_value)
            if mark_value is not None and delta_value is not None and entry_price is not None
            else None
        )
        quote_incomplete = any(_to_float_or_none(candidate.get(field)) is None for field in ("bid", "ask", "mark"))
        spread_penalty = 0.0
        spread_value = spreads[idx]
        if spread_value is not None and mark_value not in {None, 0.0} and spread_value > max(1.0, mark_value * 0.25):
            spread_penalty = 0.12
        integrity_flags = list(candidate.get("integrity_flags", []))
        penalty_flags: list[str] = []
        if not stop_valid:
            integrity_flags.append("stop_unavailable")
            penalty_flags.append("stop_unavailable")
        if quote_incomplete:
            integrity_flags.append("quote_incomplete")
            penalty_flags.append("quote_incomplete")
        inefficient_stop = bool(expected_gain is not None and expected_loss is not None and expected_loss > expected_gain)
        if inefficient_stop:
            integrity_flags.append("inefficient_stop")
            penalty_flags.append("inefficient_stop")
        if spread_penalty > 0:
            penalty_flags.append("wide_spread")

        contract_score = (
            (delta_fit[idx] or 0.0) * 0.30
            + gamma_scores[idx] * 0.25
            + liquidity_scores[idx] * 0.20
            + spread_scores[idx] * 0.15
            + distance_scores[idx] * 0.10
        )
        if not stop_valid:
            contract_score -= 0.25
        if quote_incomplete:
            contract_score -= 0.15
        if inefficient_stop:
            contract_score -= 0.10
        contract_score -= spread_penalty
        contract_score = max(contract_score, 0.0)

        enriched.update(
            {
                "distance_to_entry": abs(distance_to_entry_signed),
                "target_move": target_move,
                "stop_move": stop_move,
                "predicted_entry_price": round_price(predicted_entry_price) if predicted_entry_price is not None else None,
                "expected_gain": round_price(expected_gain) if expected_gain is not None else None,
                "expected_loss": round_price(expected_loss) if expected_loss is not None else None,
                "rr_ratio": round(rr_ratio, 3) if rr_ratio is not None else None,
                "contract_score": round(contract_score, 4),
                "delta_score": round(delta_fit[idx] or 0.0, 4),
                "gamma_score": round(gamma_scores[idx], 4),
                "liquidity_score": round(liquidity_scores[idx], 4),
                "spread_score": round(spread_scores[idx], 4),
                "distance_score": round(distance_scores[idx], 4),
                "score_penalty": round((0.25 if not stop_valid else 0.0) + (0.15 if quote_incomplete else 0.0) + (0.10 if inefficient_stop else 0.0) + spread_penalty, 4),
                "penalty_flags": penalty_flags,
                "integrity_flags": sorted(set(integrity_flags)),
                "stop_unavailable": not stop_valid,
                "inefficient_stop": inefficient_stop,
            }
        )
        ranked_candidates.append(enriched)

    ranked_candidates.sort(key=lambda row: row.get("contract_score", 0.0), reverse=True)
    for idx, candidate in enumerate(ranked_candidates):
        candidate["selection_label"] = "BEST CONTRACT" if idx == 0 else ""
    return ranked_candidates


def extract_lead_option_quote(candidates: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """Extract the best available lead quote from normalized option candidates."""

    rows = normalize_option_candidate_rows(candidates)
    if not rows:
        return None
    lead = rows[0]
    price = lead.get("mark")
    if price in {"", None}:
        price = lead.get("last")
    if price in {"", None}:
        price = lead.get("ask")
    if price in {"", None}:
        price = lead.get("bid")
    return {
        "contract_symbol": lead.get("contract_symbol", ""),
        "price": float(price) if price not in {"", None} else None,
        "bid": float(lead["bid"]) if lead.get("bid") not in {"", None} else None,
        "ask": float(lead["ask"]) if lead.get("ask") not in {"", None} else None,
        "expiration": lead.get("expiration", ""),
        "strike": lead.get("strike", ""),
        "predicted_entry_price": float(lead["predicted_entry_price"]) if lead.get("predicted_entry_price") not in {"", None} else None,
        "expected_gain": float(lead["expected_gain"]) if lead.get("expected_gain") not in {"", None} else None,
        "expected_loss": float(lead["expected_loss"]) if lead.get("expected_loss") not in {"", None} else None,
        "rr_ratio": float(lead["rr_ratio"]) if lead.get("rr_ratio") not in {"", None} else None,
        "contract_score": float(lead["contract_score"]) if lead.get("contract_score") not in {"", None} else None,
        "spx_price_at_lookup": _to_float_or_none(candidates[0].get("spx_price_at_lookup")) if candidates else None,
        "es_price_at_lookup": _to_float_or_none(candidates[0].get("es_price_at_lookup")) if candidates else None,
    }


def attach_option_lookup_context(
    contracts: list[dict[str, Any]] | None,
    *,
    lookup_timestamp,
    current_es_price: float | None,
    current_spx_price: float | None,
    effective_offset: float,
    scenario_name: str,
    direction: str,
    source_line_es: float | None,
    computed_spx_entry: float | None,
) -> list[dict[str, Any]]:
    """Attach future-learning context to returned option contracts without changing the visible UI."""

    enriched: list[dict[str, Any]] = []
    for contract in contracts or []:
        enriched_contract = dict(contract)
        enriched_contract.update(
            {
                "lookup_timestamp": lookup_timestamp.isoformat() if hasattr(lookup_timestamp, "isoformat") else str(lookup_timestamp),
                "es_price_at_lookup": current_es_price,
                "spx_price_at_lookup": current_spx_price,
                "es_spx_offset": effective_offset,
                "scenario_name": scenario_name,
                "direction": direction,
                "source_line_es": source_line_es,
                "computed_spx_entry": computed_spx_entry,
            }
        )
        enriched.append(enriched_contract)
    return enriched


def render_options_provider_preview(
    provider: Any,
    provider_status: dict[str, Any],
    option_sections: list[dict[str, Any]],
    *,
    developer_mode: bool = False,
) -> None:
    """Render a safe provider integration preview without requiring live connectivity."""

    with st.expander("Options Data", expanded=False):
        provider_name = str(provider_status.get("provider_name", "none")).title()
        provider_bits = [
            provider_name,
            "Connected" if provider_status.get("configured") else "Not configured",
            "OAuth" if str(provider_status.get("auth_mode", "none")).startswith("oauth") else str(provider_status.get("auth_mode", "none")).replace("_", " ").title(),
            provider_status.get("status_label", "Unavailable"),
        ]
        st.markdown(" | ".join(str(bit) for bit in provider_bits if bit))
        if developer_mode:
            st.caption(
                f"Auth mode: {provider_status.get('auth_mode', 'none')} | "
                f"Environment: {provider_status.get('active_environment', 'sandbox')}"
            )
        provider_name = str(provider_status.get("provider_name", "none")).lower()
        if provider_name == "none" or not provider_status.get("credentials_detected"):
            with st.container(border=True):
                st.markdown("**Tastytrade Setup**")
                st.write("Provider name: `tastytrade`")
                st.write("Authentication mode: OAuth")
                if developer_mode:
                    st.write(f"Client ID keys: `{TASTYTRADE_CLIENT_ID_KEYS[0]}`, `{TASTYTRADE_CLIENT_ID_KEYS[1]}`")
                    st.write(f"Client secret keys: `{TASTYTRADE_CLIENT_SECRET_KEYS[0]}`, `{TASTYTRADE_CLIENT_SECRET_KEYS[1]}`")
                    st.write(f"Preferred refresh-token keys: `{TASTYTRADE_REFRESH_TOKEN_KEYS[0]}`, `{TASTYTRADE_REFRESH_TOKEN_KEYS[1]}`")
                    st.write(f"Optional auth-code keys: `{TASTYTRADE_AUTH_CODE_KEYS[0]}`, `{TASTYTRADE_AUTH_CODE_KEYS[1]}`")
                    st.write(f"Optional redirect-URI keys: `{TASTYTRADE_REDIRECT_URI_KEYS[0]}`, `{TASTYTRADE_REDIRECT_URI_KEYS[1]}`")
                    st.write(f"Optional sandbox flag keys: `{TASTYTRADE_TEST_KEYS[0]}`, `{TASTYTRADE_TEST_KEYS[1]}`")
                if provider_name == "none":
                    st.info("tastytrade is the production default. Live contract lookup will activate automatically when the provider bridge and credentials are available.")
                else:
                    st.info("tastytrade is selected, but OAuth credentials were not detected.")

        if not option_sections:
            st.info("No options lookup request is available yet. A valid SPX options setup is required before candidate contracts can be shown.")
            return

        if developer_mode and provider_status.get("bridge_only", True):
            st.info("Provider bridge is available, but live options chain and quotes are not active yet.")

        for section in option_sections:
            request_payload = section["request"].to_dict()
            play_spx = section.get("play_spx")
            play_es = section.get("play_es")
            chain_snapshot = section.get("chain_snapshot") or {"status": "unavailable", "contracts": []}
            preview_candidates = normalize_option_candidate_rows(chain_snapshot.get("contracts"))
            if not preview_candidates and not provider_status.get("live_mode_available", False):
                preview_candidates = normalize_option_candidate_rows(provider.find_candidate_contracts(section["request"]))

            st.markdown(f"**{section['title']}**")
            summary_bits = [
                str(request_payload.get("direction", "")),
                f"ES {format_price(play_es['entry']['price'])}" if play_es else "ES -",
                f"SPX {format_price(play_spx['entry']['price'])}" if play_spx else "SPX -",
                f"Strike {play_spx['strike']}" if play_spx else "Strike -",
            ]
            lead_quote = extract_lead_option_quote(chain_snapshot.get("contracts"))
            if lead_quote and lead_quote.get("price") is not None:
                summary_bits.append(f"Mark {format_price(lead_quote['price'])}")
            st.markdown(" | ".join(str(bit) for bit in summary_bits if bit))
            best_contract = (chain_snapshot.get("contracts") or [None])[0]
            if best_contract:
                best_mark_value = _to_float_or_none(best_contract.get("mark"))
                if best_mark_value is None:
                    best_mark_value = _to_float_or_none(best_contract.get("last"))
                intelligence_bits = [
                    "BEST CONTRACT",
                    str(best_contract.get("symbol") or "-"),
                    f"Pred Entry {format_price(best_contract.get('predicted_entry_price'))}" if best_contract.get("predicted_entry_price") is not None else "Pred Entry -",
                    f"Mark {format_price(best_mark_value)}" if best_mark_value is not None else "Mark -",
                    f"Gain {format_price(best_contract.get('expected_gain'))}" if best_contract.get("expected_gain") is not None else "Gain -",
                    f"Loss {format_price(best_contract.get('expected_loss'))}" if best_contract.get("expected_loss") is not None else "Loss -",
                    f"RR {best_contract.get('rr_ratio')}" if best_contract.get("rr_ratio") is not None else "RR -",
                    f"Score {best_contract.get('contract_score')}" if best_contract.get("contract_score") is not None else "Score -",
                ]
                st.caption(" • ".join(intelligence_bits))
                if best_contract.get("stop_unavailable"):
                    st.caption("Setup incomplete: structural stop unavailable. RR stays blank until a valid stop exists.")
            if developer_mode:
                st.caption(f"Connection/data status: {chain_snapshot.get('status', 'unavailable')}")
            if developer_mode and chain_snapshot.get("message"):
                st.write(chain_snapshot["message"])
            if chain_snapshot.get("error"):
                st.warning(chain_snapshot["error"])

            if preview_candidates:
                preview_df = pd.DataFrame(preview_candidates)
                default_columns = [
                    "selection",
                    "contract_symbol",
                    "option_type",
                    "strike",
                    "expiration",
                    "bid",
                    "ask",
                    "mark",
                    "volume",
                    "open_interest",
                    "delta",
                    "implied_volatility",
                    "predicted_entry_price",
                ]
                research_columns = [
                    "gamma",
                    "theta",
                    "vega",
                    "expected_gain",
                    "expected_loss",
                    "rr_ratio",
                    "contract_score",
                    "delta_score",
                    "gamma_score",
                    "liquidity_score",
                    "spread_score",
                    "distance_score",
                    "score_penalty",
                    "penalty_flags",
                ]
                visible_columns = [column for column in default_columns if column in preview_df.columns]
                if developer_mode:
                    visible_columns.extend([column for column in research_columns if column in preview_df.columns and column not in visible_columns])
                render_df = preview_df[visible_columns] if visible_columns else preview_df

                def _highlight_best(row):
                    return [
                        "background-color: rgba(0, 230, 118, 0.14); font-weight: 600;"
                        if row.get("selection") == "BEST CONTRACT"
                        else ""
                        for _ in row
                    ]

                with st.expander("Candidate Contracts", expanded=developer_mode):
                    st.dataframe(
                        render_df.style.apply(_highlight_best, axis=1),
                        use_container_width=True,
                        hide_index=True,
                    )
            else:
                st.info("No live option candidates are available.")
            if developer_mode and best_contract:
                st.caption(
                    "Scores | "
                    f"delta {best_contract.get('delta_score', 0):.4f} | "
                    f"gamma {best_contract.get('gamma_score', 0):.4f} | "
                    f"liquidity {best_contract.get('liquidity_score', 0):.4f} | "
                    f"spread {best_contract.get('spread_score', 0):.4f} | "
                    f"distance {best_contract.get('distance_score', 0):.4f} | "
                    f"penalties {', '.join(best_contract.get('penalty_flags', [])) or 'none'}"
                )
            if developer_mode:
                st.markdown("**Prepared Lookup Request**")
                st.json(request_payload, expanded=False)

        notes = provider_status.get("notes", [])
        if developer_mode and notes:
            with st.expander("Provider Notes", expanded=False):
                for note in notes:
                    st.write(f"- {note}")
        provider_diagnostics = next((section.get("chain_snapshot", {}).get("diagnostics") or {} for section in option_sections if section.get("chain_snapshot")), {})
        if developer_mode and provider_diagnostics:
            with st.expander("Provider Diagnostics", expanded=False):
                stage_col1, stage_col2, stage_col3, stage_col4 = st.columns(4)
                stage_col1.metric("Token", "OK" if provider_diagnostics.get("token_retrieval", {}).get("success") else "Fail")
                stage_col2.metric("Chain", "OK" if provider_diagnostics.get("chain_lookup", {}).get("success") else "Fail")
                stage_col3.metric("Quotes", "OK" if provider_diagnostics.get("quote_lookup", {}).get("success") else "Fail")
                stage_col4.metric("Failure Stage", str(provider_diagnostics.get("failure_stage") or "None"))
                st.write(f"Auth mode: {provider_diagnostics.get('auth_mode') or provider_status.get('auth_mode', 'none')}")
                st.write(f"Environment: {provider_diagnostics.get('active_environment') or provider_status.get('active_environment', 'sandbox')}")
                st.write(f"Token message: {provider_diagnostics.get('token_retrieval', {}).get('message') or 'None'}")
                st.write(f"Failure message: {provider_diagnostics.get('failure_message') or 'None'}")
                symbol_resolution = provider_diagnostics.get("symbol_resolution", {})
                expiration_resolution = provider_diagnostics.get("expiration_resolution", {})
                strike_resolution = provider_diagnostics.get("strike_resolution", {})
                if symbol_resolution:
                    st.write(f"Requested underlying: {symbol_resolution.get('requested_underlying') or 'None'}")
                    st.write(f"Underlying candidates: {symbol_resolution.get('underlying_candidates') or []}")
                    st.write(f"Resolved underlying: {symbol_resolution.get('normalized_underlying_used') or 'None'}")
                    st.write(f"Lookup attempts: {symbol_resolution.get('lookup_attempts') or []}")
                if expiration_resolution:
                    st.write(f"Expiration target: {expiration_resolution.get('requested_date') or 'None'}")
                    st.write(f"Returned expirations: {expiration_resolution.get('returned_expirations') or []}")
                    st.write(f"Chosen expiration: {expiration_resolution.get('chosen_expiration') or 'None'}")
                if strike_resolution:
                    st.write(f"Strike target: {strike_resolution.get('requested_strike')}")
                    st.write(f"Exact strike exists: {strike_resolution.get('exact_strike_exists')}")
                    st.write(f"Nearby strikes: {strike_resolution.get('available_nearby_strikes') or []}")
                st.json(provider_diagnostics, expanded=False)


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


def extract_timestamp_row(frame: pd.DataFrame | None, target_time) -> dict[str, Any] | None:
    """Return the last row that matches an exact Central-Time timestamp."""

    if frame is None or frame.empty:
        return None
    matches = frame.loc[frame["timestamp"].map(to_central_time) == target_time]
    if matches.empty:
        return None
    row = matches.iloc[-1]
    return {
        "timestamp": to_central_time(row["timestamp"]),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
    }


def fetch_historical_input_defaults(
    prior_session_date: date,
    next_trading_date: date,
    es_spx_offset: float,
) -> dict[str, Any]:
    """Fetch recent historical 9:00 AM defaults for the selected date pair."""

    days_back = (current_central_time().date() - next_trading_date).days
    unavailable = {
        "default_spx_price": 0.0,
        "default_es_price": 0.0,
        "default_open_reference": 0.0,
        "spx_available": False,
        "es_available": False,
        "spx_source": "historical_unavailable",
        "es_source": "historical_unavailable",
    }
    if days_back < 0 or days_back > 31:
        unavailable["spx_source"] = "historical_out_of_range_manual_required"
        unavailable["es_source"] = "historical_out_of_range_manual_required"
        return unavailable

    try:
        es_candles, _ = fetch_es_candles_for_app(prior_session_date, next_trading_date)
        es_row = extract_timestamp_row(es_candles, at_central(next_trading_date, 9, 0))
    except Exception:
        es_row = None

    try:
        spx_candles = fetch_spx_confirmation_candles(next_trading_date)
        spx_row = extract_timestamp_row(spx_candles, at_central(next_trading_date, 9, 0))
    except Exception:
        spx_row = None

    return {
        "default_spx_price": float(spx_row["open"]) if spx_row else 0.0,
        "default_es_price": float(es_row["open"]) if es_row else 0.0,
        "default_open_reference": float(spx_row["open"]) if spx_row else 0.0,
        "spx_available": spx_row is not None,
        "es_available": es_row is not None,
        "spx_source": "historical 9:00 AM SPX open" if spx_row else "historical_spx_bar_unavailable",
        "es_source": "historical 9:00 AM ES open" if es_row else "historical_es_bar_unavailable",
        "derived_live_offset": round_price(float(es_row["open"]) - float(spx_row["open"])) if es_row and spx_row else None,
        "configured_offset": round_price(es_spx_offset),
        "es_fetch_status": "historical_success" if es_row else "historical_failed",
        "spx_fetch_status": "historical_success" if spx_row else "historical_failed",
    }


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
        operating_mode = st.radio("Operating mode", ["Live Mode", "Historical Mode"], index=0)
        visibility_options = ["Production Mode", "Edge Lab"]
        visibility_mode = st.radio(
            "Visibility",
            visibility_options,
            index=safe_option_index(visibility_options, settings.get("visibility_mode", DEFAULT_SETTINGS["visibility_mode"])),
        )
        historical_mode = operating_mode == "Historical Mode"
        if not historical_mode and st.button("Refresh Live Quotes", use_container_width=True):
            st.session_state["refresh_live_quotes"] = True
            st.rerun()
        if historical_mode:
            prior_session_date = st.date_input("Prior NY session date", value=default_prior)
            next_trading_date = st.date_input("Next trading date", value=default_next)
        else:
            next_trading_date = st.date_input("Next trading day", value=default_next, min_value=default_next, key="live_next_trading_day")
            prior_session_date = previous_business_day(next_trading_date)
            st.caption(f"Prior NY session: {prior_session_date}")
            st.caption(f"Next trading day: {next_trading_date}")
        historical_defaults = fetch_historical_input_defaults(prior_session_date, next_trading_date, configured_offset) if historical_mode else None
        sync_projection_price_inputs(next_trading_date, historical_mode, live_defaults, historical_defaults)
        data_mode_options = ["Auto-fetch", "Manual input"]
        data_mode = st.radio("Data source", data_mode_options, index=safe_option_index(data_mode_options, settings.get("data_mode", DEFAULT_SETTINGS["data_mode"])))

        st.subheader("Session Inputs")
        active_defaults = historical_defaults if historical_mode and historical_defaults is not None else live_defaults
        current_spx_price = st.number_input("9:00 AM SPX price", value=float(st.session_state.get("current_spx_price_input", active_defaults["default_spx_price"])), step=0.25, format="%.2f", key="current_spx_price_input")
        current_es_price = st.number_input("Current ES price", value=float(st.session_state.get("current_es_price_input", active_defaults["default_es_price"])), step=0.25, format="%.2f", key="current_es_price_input")
        open_reference = st.number_input("9:00 AM open reference", value=float(st.session_state.get("open_reference_input", active_defaults["default_open_reference"])), step=0.25, format="%.2f", key="open_reference_input")
        if historical_mode:
            if historical_defaults and historical_defaults["spx_available"] and historical_defaults["es_available"]:
                st.info("Historical projection mode active. Recent historical 9:00 AM ES/SPX values were loaded automatically and remain editable.")
            else:
                st.info("Historical projection mode active. Enter historical 9:00 AM prices manually to enable scenario outputs.")
        elif not live_defaults["es_available"] or not live_defaults["spx_available"]:
            st.warning("Live quote unavailable. Enter current prices manually.")
        news_day = st.checkbox("Fed / CPI / NFP day", value=bool(settings.get("news_day", DEFAULT_SETTINGS["news_day"])))
        live_effective_offset = (
            float(live_defaults["derived_live_offset"])
            if not historical_mode and live_defaults.get("es_available") and live_defaults.get("spx_available") and live_defaults.get("derived_live_offset") is not None
            else None
        )
        es_spx_offset = st.number_input("ES-SPX offset", value=configured_offset, step=0.25, format="%.2f")
        if historical_mode:
            current_spx_source_label = historical_defaults["spx_source"] if historical_defaults and historical_defaults["spx_available"] and abs(float(current_spx_price) - float(historical_defaults["default_spx_price"])) < 0.005 else ("manual entry" if is_valid_price_input(current_spx_price) else "unavailable")
            current_es_source_label = historical_defaults["es_source"] if historical_defaults and historical_defaults["es_available"] and abs(float(current_es_price) - float(historical_defaults["default_es_price"])) < 0.005 else ("manual entry" if is_valid_price_input(current_es_price) else "unavailable")
            open_reference_source_label = "historical 9:00 AM SPX open" if historical_defaults and historical_defaults["spx_available"] and abs(float(open_reference) - float(historical_defaults["default_open_reference"])) < 0.005 else ("manual entry" if is_valid_price_input(open_reference) else "unavailable")
        else:
            current_spx_source_label = describe_current_spx_source(
                current_spx_price=current_spx_price,
                current_es_price=current_es_price,
                current_offset=es_spx_offset,
                default_spx_price=live_defaults["default_spx_price"],
                live_spx_available=live_defaults["spx_available"],
            )
            current_es_source_label = describe_current_es_source(
                current_es_price=current_es_price,
                default_es_price=live_defaults["default_es_price"],
                live_es_available=live_defaults["es_available"],
            )
            open_reference_source_label = "live SPX quote" if live_defaults["spx_available"] and abs(float(open_reference) - float(live_defaults["default_open_reference"])) < 0.005 else "manual entry"
        with st.expander("Advanced Controls", expanded=False):
            st.caption(f"Current SPX source: {current_spx_source_label}")
            st.caption(f"Current ES source: {current_es_source_label}")
            st.caption(f"9:00 AM open source: {open_reference_source_label}")
            if not historical_mode:
                if live_effective_offset is not None:
                    st.caption(f"Live inferred offset: {format_price(live_effective_offset)}")
                    if abs(float(es_spx_offset) - float(live_effective_offset)) >= 0.01:
                        st.caption("Manual offset override is active.")
                else:
                    st.caption("Live inferred offset unavailable.")
            price_space_options = ["SPX", "ES"]
            manual_price_space = st.selectbox("Manual input price space", price_space_options, index=safe_option_index(price_space_options, settings.get("manual_price_space", DEFAULT_SETTINGS["manual_price_space"])))
            session_lock_options = list(SESSION_PLAN_LOCK_CUTOFFS.keys())
            session_plan_lock_cutoff = st.selectbox(
                "Session plan lock cutoff",
                session_lock_options,
                index=safe_option_index(session_lock_options, settings.get("session_plan_lock_cutoff", DEFAULT_SETTINGS["session_plan_lock_cutoff"])),
            )
            if visibility_mode == "Edge Lab":
                options_mode_enabled = st.checkbox("Options mode enabled", value=bool(settings.get("options_mode_enabled", DEFAULT_SETTINGS["options_mode_enabled"])))
                options_provider = st.selectbox("Options provider", PROVIDER_NAMES, index=safe_option_index(PROVIDER_NAMES, settings.get("options_provider", DEFAULT_SETTINGS["options_provider"])))
            else:
                options_mode_enabled = DEFAULT_OPTIONS_PROVIDER != "none"
                options_provider = DEFAULT_OPTIONS_PROVIDER
                st.caption(f"Options provider: {options_provider}")

        with st.expander("Manual Anchors", expanded=False):
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

        with st.expander("Overnight Overrides", expanded=False):
            use_asc_ceiling_override = st.checkbox("Override ASC Ceiling")
            asc_ceiling_override = st.number_input("ASC Ceiling override value", value=0.00, step=0.25, format="%.2f")
            use_desc_ceiling_override = st.checkbox("Override DESC Ceiling")
            desc_ceiling_override = st.number_input("DESC Ceiling override value", value=0.00, step=0.25, format="%.2f")
            use_asc_floor_override = st.checkbox("Override ASC Floor")
            asc_floor_override = st.number_input("ASC Floor override value", value=0.00, step=0.25, format="%.2f")
            use_desc_floor_override = st.checkbox("Override DESC Floor")
            desc_floor_override = st.number_input("DESC Floor override value", value=0.00, step=0.25, format="%.2f")

        if not historical_mode and visibility_mode == "Edge Lab":
            with st.expander("Diagnostics", expanded=False):
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

    return {
        "prior_session_date": prior_session_date,
        "next_trading_date": next_trading_date,
        "data_mode": data_mode,
        "visibility_mode": visibility_mode,
        "developer_mode": visibility_mode == "Edge Lab",
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
        "historical_mode": historical_mode,
        "operating_mode": operating_mode,
        "news_day": news_day,
        "es_spx_offset": es_spx_offset,
        "manual_price_space": manual_price_space,
        "session_plan_lock_cutoff": session_plan_lock_cutoff,
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
) -> tuple[dict[str, Any] | None, Any | None, str | None, dict[str, Any] | None]:
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
            None,
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
            None,
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
    unit_label: str,
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
                f"Projected Level ({unit_label})": format_price(final_line["projected_price"]),
                f"Raw Anchor ({unit_label})": format_price(final_line.get("raw_anchor_price", final_line["anchor_price"])),
                "Candle Count": final_line["candle_count"],
                "Direction": final_line["direction"],
                "Source": source_label,
                f"Original Projected ({unit_label})": format_price(original_line["projected_price"]) if applied else "",
                f"Override Projected ({unit_label})": format_price(final_line["projected_price"]) if applied else "",
            }
        )

    return rows


def get_structure_assertion_warnings(
    final_projected_lines_es: dict[str, dict[str, Any]],
    displayed_lines: dict[str, dict[str, Any]],
    displayed_unit_label: str,
) -> list[str]:
    """Return app-layer structural warnings for the visible ES display path."""

    warnings: list[str] = []

    hw_value = float(final_projected_lines_es["hw"]["projected_price"])
    ac_value = float(final_projected_lines_es["asc_ceiling"]["projected_price"])
    lw_value = float(final_projected_lines_es["lw"]["projected_price"])
    af_value = float(final_projected_lines_es["asc_floor"]["projected_price"])
    df_value = float(final_projected_lines_es["desc_floor"]["projected_price"])

    if ac_value > hw_value:
        warnings.append(
            f"Structural violation: ASC Ceiling ({format_price(ac_value)} ES) is above HW ({format_price(hw_value)} ES)."
        )

    if lw_value > af_value:
        warnings.append(
            f"Structural violation: LW ({format_price(lw_value)} ES) is above ASC Floor ({format_price(af_value)} ES)."
        )

    if lw_value > df_value:
        warnings.append(
            f"Structural violation: LW ({format_price(lw_value)} ES) is above DESC Floor ({format_price(df_value)} ES)."
        )

    displayed_lw = float(displayed_lines["lw"]["projected_price"])
    if abs(displayed_lw - lw_value) > 1e-9:
        warnings.append(
            f"LW display mismatch: projected LW is {format_price(lw_value)} ES but visible LW is {format_price(displayed_lw)} {displayed_unit_label}."
        )

    if displayed_unit_label.strip().upper() != "ES":
        warnings.append(
            f"Structure display unit mismatch: visible structural displays are labeled {displayed_unit_label}, but ES must be the single source of truth."
        )

    return warnings


def render_six_lines_panel(
    original_lines: dict[str, dict[str, Any]],
    final_lines: dict[str, dict[str, Any]],
    override_decisions: dict[str, Any],
    unit_label: str = "ES",
) -> None:
    """Render the six projected lines in operator-friendly order."""

    st.markdown(
        f"""
        <div class="spx-shell">
            <div class="spx-section-title">Projected Lines</div>
            <div class="spx-section-subtitle">
                Ordered display follows the house structure: HW, ASC Ceiling, ASC Floor, DESC Ceiling, DESC Floor, LW. All values below are shown in {unit_label} terms.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.container():
        st.dataframe(
            build_line_rows(original_lines, final_lines, override_decisions, unit_label),
            use_container_width=True,
            hide_index=True,
        )


def render_trade_decision_summary(
    signal_package: dict[str, Any],
    projected_lines: dict[str, dict[str, Any]],
    *,
    final_status: str,
    final_decision: str | None = None,
    intelligence_summary: dict[str, Any] | None = None,
    authority: dict[str, Any] | None = None,
    active_play_label: str = "Primary",
    live_context: dict[str, Any] | None = None,
) -> None:
    """Render the fastest single-line operator summary."""

    scenario = signal_package["scenario"]
    primary_play = resolve_play_display_values(scenario.get("primary_play"), projected_lines)
    action_label = (authority or {}).get("decision") or final_decision or final_status_to_action(final_status, signal_package)
    primary_direction = primary_play["direction"] if primary_play else "-"
    direction_display = resolve_trade_direction_display(primary_direction)
    execution_display = resolve_trade_execution_display(primary_direction, action_label)
    presentation_state = resolve_presentation_state(action_label, direction_display["bias"])
    condition_label = (
        "No valid setup"
        if str(action_label).upper() == "NO TRADE"
        else "Conditional entry"
        if str(action_label).upper() == "CONDITIONAL BUY"
        else "Ready now"
    )
    summary_entry_value = intelligence_summary.get("locked_entry_spx") if intelligence_summary else None
    if summary_entry_value is None and primary_play:
        summary_entry_value = primary_play["entry"]["price"]
    entry_value = format_price(summary_entry_value) if summary_entry_value is not None else "-"
    strike = str(primary_play["strike"]) if primary_play else "-"
    ev_display = format_price((authority or {}).get("expected_value")) if (authority or {}).get("expected_value") is not None else "Insufficient"
    confidence_display = f"{int((authority or {}).get('confidence_score', 0))}%"
    live_scenario = str((live_context or {}).get("live_scenario") or scenario["scenario_name"])
    live_structure = format_live_state_label((live_context or {}).get("live_structure_state"))

    st.markdown(
        f"""
        <div class="spx-summary">
            <div class="spx-summary-title">Trade Summary</div>
            <div class="spx-summary-body">
                {presentation_state['secondary'].replace('Market bias: ', '')} | {execution_display} | {condition_label}
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
                <span class="spx-pill scenario-neutral">Price {format_price(scenario['current_price'])} SPX</span>
            </div>
            <div class="spx-banner-text">{scenario['description']}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def classify_stop_quality(entry_price: float | None, stop_price: float | None) -> dict[str, Any]:
    """Classify stop distance in simple, operator-readable buckets."""

    if entry_price is None or stop_price is None:
        return {"label": "Unavailable", "distance": None}

    stop_distance = abs(float(entry_price) - float(stop_price))
    if stop_distance < 8.0:
        label = "Tight"
    elif stop_distance < 18.0:
        label = "Balanced"
    elif stop_distance < 30.0:
        label = "Wide"
    else:
        label = "Very Wide"
    return {"label": label, "distance": round_price(stop_distance)}


def assess_trade_intelligence(
    play: dict[str, Any] | None,
    lead_option_quote: dict[str, Any] | None,
    current_option_mark: float | None = None,
    current_spx_price: float | None = None,
    planned_anchor_key: str | None = None,
    session_plan: dict[str, Any] | None = None,
    *,
    min_rr: float = INTELLIGENCE_MIN_RR,
) -> dict[str, Any]:
    """Assess forward-facing trade quality without changing scenario logic."""

    entry_price = _to_float_or_none(play.get("entry", {}).get("price")) if isinstance(play, dict) else None
    stop_price = _to_float_or_none(play.get("stop", {}).get("price")) if isinstance(play, dict) and isinstance(play.get("stop"), dict) else None
    target_leg = play.get("tp1") if isinstance(play, dict) and isinstance(play.get("tp1"), dict) else None
    if not target_leg:
        target_leg = play.get("tp2") if isinstance(play, dict) and isinstance(play.get("tp2"), dict) else None
    target_price = _to_float_or_none(target_leg.get("price")) if isinstance(target_leg, dict) else None
    rr_ratio = _to_float_or_none(lead_option_quote.get("rr_ratio")) if lead_option_quote else None
    expected_gain = _to_float_or_none(lead_option_quote.get("expected_gain")) if lead_option_quote else None
    expected_loss = _to_float_or_none(lead_option_quote.get("expected_loss")) if lead_option_quote else None
    current_mark = current_option_mark
    if current_mark is None and lead_option_quote is not None:
        current_mark = _to_float_or_none(lead_option_quote.get("price"))
    live_predicted_entry_mark = _to_float_or_none(lead_option_quote.get("predicted_entry_price")) if lead_option_quote else None
    planned_entry_mark = _to_float_or_none(session_plan.get("planned_entry_mark")) if isinstance(session_plan, dict) and session_plan.get("plan_available") else resolve_planned_entry_mark(live_predicted_entry_mark, planned_anchor_key)
    entry_anchor_spx = _to_float_or_none(session_plan.get("locked_entry_spx")) if isinstance(session_plan, dict) and session_plan.get("plan_available") else entry_price
    stop_anchor = _to_float_or_none(session_plan.get("stop_spx")) if isinstance(session_plan, dict) and session_plan.get("plan_available") and session_plan.get("stop_spx") is not None else stop_price
    stop_distance = abs(entry_anchor_spx - stop_anchor) if entry_anchor_spx is not None and stop_anchor is not None else None
    target_move = abs(target_price - entry_anchor_spx) if entry_anchor_spx is not None and target_price is not None else None
    stop_valid = bool(stop_price is not None and entry_price is not None and abs(entry_price - stop_price) >= 1e-9 and not play.get("invalid_stop"))
    if isinstance(session_plan, dict) and session_plan.get("plan_available") and session_plan.get("stop_spx") is not None:
        stop_valid = True
    if isinstance(session_plan, dict) and session_plan.get("lock_active") and not session_plan.get("plan_available"):
        stop_valid = False
    inefficient_stop = bool(expected_gain is not None and expected_loss is not None and expected_loss > expected_gain)
    entry_drift = (live_predicted_entry_mark - planned_entry_mark) if live_predicted_entry_mark is not None and planned_entry_mark is not None else None
    entry_drift_abs = abs(entry_drift) if entry_drift is not None else None
    entry_drift_pct = (entry_drift_abs / max(abs(planned_entry_mark), 0.01)) if entry_drift_abs is not None and planned_entry_mark is not None else None
    price_vs_plan = (current_mark - planned_entry_mark) if current_mark is not None and planned_entry_mark is not None else None
    distance_to_entry = abs(current_spx_price - entry_anchor_spx) if current_spx_price is not None and entry_anchor_spx is not None else None
    session_plan_available = bool(session_plan.get("plan_available")) if isinstance(session_plan, dict) else bool(planned_entry_mark is not None)
    session_lock_active = bool(session_plan.get("lock_active")) if isinstance(session_plan, dict) else False
    locked_timestamp = session_plan.get("locked_timestamp") if isinstance(session_plan, dict) else None

    hold_threshold = max(INTELLIGENCE_PLAN_HOLD_THRESHOLD_ABS, abs(planned_entry_mark or 0.0) * INTELLIGENCE_PLAN_HOLD_THRESHOLD_PCT)
    drift_threshold = max(INTELLIGENCE_PLAN_DRIFT_THRESHOLD_ABS, abs(planned_entry_mark or 0.0) * INTELLIGENCE_PLAN_DRIFT_THRESHOLD_PCT)
    if session_lock_active and not session_plan_available:
        plan_status = "UNAVAILABLE"
    elif entry_drift_abs is None:
        plan_status = "UNKNOWN"
    elif entry_drift_abs <= hold_threshold:
        plan_status = "HOLDING"
    elif entry_drift_abs <= drift_threshold:
        plan_status = "DRIFTING"
    else:
        plan_status = "BROKEN"

    if session_lock_active and not session_plan_available:
        regime = "UNKNOWN"
    elif distance_to_entry is None or price_vs_plan is None:
        regime = "UNKNOWN"
    elif distance_to_entry < 5.0 and abs(price_vs_plan) <= hold_threshold:
        regime = "PULLBACK"
    elif current_spx_price is not None and entry_price is not None and abs(current_spx_price - entry_price) >= 10.0:
        regime = "EXPANSION"
    elif abs(price_vs_plan) > hold_threshold:
        regime = "EXPANSION"
    else:
        regime = "PULLBACK"

    if session_lock_active and not session_plan_available:
        chase_status = "CHASE NOT ALLOWED"
    elif stop_valid and plan_status == "HOLDING" and regime == "PULLBACK":
        chase_status = "WAIT"
    elif stop_valid and plan_status in {"HOLDING", "DRIFTING"} and regime == "EXPANSION" and distance_to_entry is not None and distance_to_entry < 10.0:
        chase_status = "ENTER NOW" if rr_ratio is not None and rr_ratio >= min_rr else "ENTER WITH CAUTION"
    elif stop_valid and plan_status == "DRIFTING" and distance_to_entry is not None and distance_to_entry < 20.0:
        chase_status = "ENTER WITH CAUTION"
    elif not stop_valid or plan_status == "BROKEN":
        chase_status = "CHASE NOT ALLOWED"
    else:
        chase_status = "WAIT"

    if session_lock_active and not session_plan_available:
        prediction_confidence = "LOW"
    elif not stop_valid or plan_status == "BROKEN":
        prediction_confidence = "LOW"
    elif entry_drift_pct is not None and entry_drift_pct <= INTELLIGENCE_CONFIDENCE_HIGH_DRIFT_PCT and regime == "PULLBACK":
        prediction_confidence = "HIGH"
    elif entry_drift_pct is not None and entry_drift_pct <= INTELLIGENCE_CONFIDENCE_MEDIUM_DRIFT_PCT:
        prediction_confidence = "MEDIUM"
    else:
        prediction_confidence = "LOW"

    if session_lock_active and not session_plan_available:
        status = "NOT ELIGIBLE"
        quality = "Low Quality"
        downgrade_reason = "session_plan_unavailable"
    elif not stop_valid or rr_ratio is None:
        status = "NOT ELIGIBLE"
        quality = "Low Quality"
        downgrade_reason = "stop_unavailable"
    elif rr_ratio < INTELLIGENCE_MIN_RR_HARD_FLOOR:
        status = "NOT ELIGIBLE"
        quality = "Low Quality"
        downgrade_reason = "rr_below_0_5"
    elif rr_ratio < min_rr:
        status = "ELIGIBLE (LOW QUALITY)"
        quality = "Low Quality"
        downgrade_reason = "rr_below_min"
    elif inefficient_stop:
        status = "ELIGIBLE"
        quality = "Acceptable"
        downgrade_reason = "inefficient_stop"
    else:
        status = "ELIGIBLE"
        quality = "High"
        downgrade_reason = "none"

    suggested_stop = None
    if entry_anchor_spx is not None and target_move is not None and play.get("direction") in {"CALL", "PUT"}:
        suggested_stop_distance = target_move / max(min_rr, 1e-9)
        suggested_stop = round_price(entry_anchor_spx - suggested_stop_distance) if play.get("direction") == "CALL" else round_price(entry_anchor_spx + suggested_stop_distance)

    if session_lock_active and not session_plan_available:
        entry_zone_status = "UNAVAILABLE"
    elif distance_to_entry is None:
        entry_zone_status = "UNKNOWN"
    else:
        if distance_to_entry <= ENTRY_ZONE_IN_THRESHOLD:
            entry_zone_status = "IN ZONE"
        elif distance_to_entry <= ENTRY_ZONE_APPROACHING_THRESHOLD:
            entry_zone_status = "APPROACHING"
        elif target_move is not None and distance_to_entry > ENTRY_ZONE_APPROACHING_THRESHOLD and current_spx_price is not None and entry_anchor_spx is not None:
            if play.get("direction") == "CALL" and current_spx_price > entry_anchor_spx:
                entry_zone_status = "MISSED"
            elif play.get("direction") == "PUT" and current_spx_price < entry_anchor_spx:
                entry_zone_status = "MISSED"
            else:
                entry_zone_status = "NOT REACHED"
        else:
            entry_zone_status = "NOT REACHED"

    move_completion_pct = None
    if entry_anchor_spx is not None and target_price is not None and current_spx_price is not None and abs(target_price - entry_anchor_spx) >= 1e-9:
        if play.get("direction") == "CALL":
            progress = ((current_spx_price - entry_anchor_spx) / (target_price - entry_anchor_spx)) * 100.0
        else:
            progress = ((entry_anchor_spx - current_spx_price) / (entry_anchor_spx - target_price)) * 100.0
        move_completion_pct = round(min(max(progress, 0.0), MOVE_COMPLETION_CAP_PCT), 2)

    return {
        "status": status,
        "quality": quality,
        "rr_ratio": rr_ratio,
        "expected_gain": expected_gain,
        "expected_loss": expected_loss,
        "stop_distance": round_price(stop_distance) if stop_distance is not None else None,
        "target_move": round_price(target_move) if target_move is not None else None,
        "inefficient_stop": inefficient_stop,
        "downgrade_reason": downgrade_reason,
        "min_rr": min_rr,
        "suggested_stop": suggested_stop,
        "planned_entry_mark": round_price(planned_entry_mark) if planned_entry_mark is not None else None,
        "live_predicted_entry_mark": round_price(live_predicted_entry_mark) if live_predicted_entry_mark is not None else None,
        "current_option_mark": round_price(current_mark) if current_mark is not None else None,
        "locked_entry_spx": round_price(entry_anchor_spx) if entry_anchor_spx is not None else None,
        "locked_timestamp": locked_timestamp,
        "session_plan_locked": bool(session_plan.get("session_plan_locked")) if isinstance(session_plan, dict) else False,
        "session_plan_available": session_plan_available,
        "entry_drift": round_price(entry_drift) if entry_drift is not None else None,
        "entry_drift_abs": round_price(entry_drift_abs) if entry_drift_abs is not None else None,
        "entry_drift_pct": round(entry_drift_pct, 4) if entry_drift_pct is not None else None,
        "price_vs_plan": round_price(price_vs_plan) if price_vs_plan is not None else None,
        "entry_zone_status": entry_zone_status,
        "move_completion_pct": move_completion_pct,
        "regime": regime,
        "plan_status": plan_status,
        "chase_status": chase_status,
        "prediction_confidence": prediction_confidence,
        "distance_to_entry": round_price(distance_to_entry) if distance_to_entry is not None else None,
        "hold_threshold": round_price(hold_threshold),
        "drift_threshold": round_price(drift_threshold),
        "lock_cutoff_label": session_plan.get("lock_cutoff_label") if isinstance(session_plan, dict) else None,
        "lock_active": session_lock_active,
    }


def resolve_final_trade_status(
    signal_package: dict[str, Any] | None,
    play: dict[str, Any] | None,
    lead_option_quote: dict[str, Any] | None,
    *,
    current_spx_price: float | None = None,
    planned_anchor_key: str | None = None,
    session_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve one final operator-facing status from structural and intelligence layers."""

    structural_status = "NOT ELIGIBLE" if signal_package is None else ("NOT ELIGIBLE" if signal_package["sit_out"]["sit_out"] else "ELIGIBLE")
    intelligence = assess_trade_intelligence(
        play,
        lead_option_quote,
        current_spx_price=current_spx_price,
        planned_anchor_key=planned_anchor_key,
        session_plan=session_plan,
    )
    intelligence_status = intelligence["status"]

    if structural_status == "NOT ELIGIBLE" or intelligence_status == "NOT ELIGIBLE":
        final_status = "NOT ELIGIBLE"
    elif "CAUTION" in intelligence_status:
        final_status = "ELIGIBLE WITH CAUTION"
    else:
        final_status = "ELIGIBLE"

    if structural_status == "NOT ELIGIBLE" or intelligence.get("chase_status") == "CHASE NOT ALLOWED":
        final_decision = "SKIP TRADE"
    elif intelligence.get("chase_status") == "WAIT":
        final_decision = "WAIT"
    elif intelligence.get("chase_status") == "ENTER NOW" and intelligence.get("prediction_confidence") in {"HIGH", "MEDIUM"}:
        final_decision = "ENTER NOW"
    elif intelligence.get("chase_status") == "ENTER WITH CAUTION" or final_status == "ELIGIBLE WITH CAUTION":
        final_decision = "ENTER WITH CAUTION"
    elif final_status == "ELIGIBLE":
        final_decision = "ENTER NOW"
    else:
        final_decision = "WAIT"

    return {
        "structural_status": structural_status,
        "intelligence_status": intelligence_status,
        "final_status": final_status,
        "final_decision": final_decision,
        "intelligence": intelligence,
    }


def build_calibration_bias_note(calibration_preview: dict[str, Any] | None) -> str:
    """Build a short operator-facing calibration note."""

    if not calibration_preview:
        return ""

    notes: list[str] = []
    prediction_bias = _to_float_or_none(calibration_preview.get("prediction_bias_used"))
    slippage_bias = _to_float_or_none(calibration_preview.get("slippage_bias_used"))

    if prediction_bias is not None:
        if prediction_bias > 0:
            notes.append("Historically underpriced")
        elif prediction_bias < 0:
            notes.append("Historically overpriced")

    if slippage_bias is not None:
        if slippage_bias > 0:
            notes.append("Fill usually worse")
        elif slippage_bias < 0:
            notes.append("Fill usually better")

    return " | ".join(notes[:2])



def render_play_card(
    title: str,
    play_spx: dict[str, Any] | None,
    projected_lines_spx: dict[str, dict[str, Any]],
    projected_lines_es: dict[str, dict[str, Any]],
    lead_option_quote: dict[str, Any] | None = None,
    *,
    compact: bool = False,
    effective_offset: float | None = None,
    offset_diagnostics: dict[str, Any] | None = None,
    developer_mode: bool = False,
    final_status: str | None = None,
    status_breakdown: dict[str, str] | None = None,
    current_spx_price: float | None = None,
    planned_anchor_key: str | None = None,
    session_plan: dict[str, Any] | None = None,
    calibration_preview: dict[str, Any] | None = None,
    adaptive_overlay: dict[str, Any] | None = None,
    authority: dict[str, Any] | None = None,
    live_context: dict[str, Any] | None = None,
) -> None:
    """Render a single structured play card."""

    if play_spx is None:
        with st.container(border=True):
            st.markdown(f"**{title}**")
            st.caption("No setup.")
        return

    def _decision_class(value: str) -> str:
        mapping = {
            "ENTER NOW": "enter",
            "WAIT": "wait",
            "ENTER WITH CAUTION": "caution",
            "SKIP TRADE": "skip",
        }
        return mapping.get(str(value or "").upper(), "wait")

    def _chip_class(value: str, kind: str = "neutral") -> str:
        text = str(value or "").upper()
        if kind == "regime":
            return "blue" if text == "PULLBACK" else "green" if text == "EXPANSION" else "gray"
        if kind == "chase":
            return {
                "WAIT": "blue",
                "ENTER NOW": "green",
                "ENTER WITH CAUTION": "yellow",
                "CHASE NOT ALLOWED": "red",
            }.get(text, "gray")
        if kind == "plan":
            return {
                "HOLDING": "green",
                "DRIFTING": "yellow",
                "BROKEN": "red",
            }.get(text, "gray")
        if kind == "confidence":
            return {"HIGH": "green", "MEDIUM": "yellow", "LOW": "red"}.get(text, "gray")
        if kind == "timing":
            return {"IDEAL": "green", "EARLY": "blue", "LATE": "yellow", "CHASE": "red"}.get(text, "gray")
        return {"ACTIVE": "green", "FILTERED": "red", "INVALID": "red"}.get(text, "gray")

    play = resolve_play_display_values(play_spx, projected_lines_spx)
    play_es = resolve_play_display_values(play_spx, projected_lines_es)
    if effective_offset is not None:
        play = align_play_conversion_to_effective_offset(play, play_es, effective_offset)
    entry_line_es = resolve_line_from_projected_bundle(projected_lines_es, play["entry"]["label"])
    entry_es_value = entry_line_es["projected_price"] if entry_line_es is not None else (_to_float_or_none(play_es.get("entry", {}).get("price")) if play_es else None)
    stop_price = _to_float_or_none(play.get("stop", {}).get("price")) if isinstance(play, dict) and isinstance(play.get("stop"), dict) else None
    entry_price = _to_float_or_none(play.get("entry", {}).get("price")) if isinstance(play.get("entry"), dict) else None
    stop_quality = classify_stop_quality(entry_price, stop_price) if stop_price is not None and not play.get("invalid_stop") else {"label": "Unavailable", "distance": None}
    intelligence = assess_trade_intelligence(
        play,
        lead_option_quote,
        current_spx_price=current_spx_price,
        planned_anchor_key=planned_anchor_key,
        session_plan=session_plan,
    )
    intelligence["stop_quality"] = stop_quality["label"]
    timing = classify_entry_timing(current_spx_price, _to_float_or_none(intelligence.get("locked_entry_spx")) or entry_price)

    is_primary = "alternate" not in title.lower()
    visible_status = final_status or intelligence["status"]
    action_label = (status_breakdown or {}).get("final_decision") or final_status_to_action(visible_status, st.session_state.get("current_signal_package"))
    decision_suppressed = action_label == "SKIP TRADE"
    trade_state = "FILTERED" if decision_suppressed else ("INVALID" if not play.get("stop") or play.get("invalid_stop") else "ACTIVE")
    quality_display = "Ignored (Decision Override)" if decision_suppressed else intelligence["quality"]
    decision_reason = get_decision_reason(action_label, st.session_state.get("current_signal_package"), play, intelligence, timing["label"])
    pred_label = "Estimated Entry (Live)" if is_live_market_session() else "Predicted Entry"
    planned_entry_mark = format_price(intelligence.get("planned_entry_mark")) if intelligence.get("planned_entry_mark") is not None else "-"
    live_predicted_mark = format_price(intelligence.get("live_predicted_entry_mark")) if intelligence.get("live_predicted_entry_mark") is not None else "-"
    calibrated_entry_mark = format_price(calibration_preview.get("calibrated_entry_mark")) if calibration_preview and calibration_preview.get("calibrated_entry_mark") is not None else "-"
    expected_fill_mark = format_price(calibration_preview.get("expected_fill_mark")) if calibration_preview and calibration_preview.get("expected_fill_mark") is not None else "-"
    calibration_evidence = str(calibration_preview.get("evidence_label", "No Evidence")) if calibration_preview else "No Evidence"
    calibration_bias_note = build_calibration_bias_note(calibration_preview)
    adaptive_recommendation = str((adaptive_overlay or {}).get("adaptive_recommendation", "NO_ADAPTATION"))
    adaptive_evidence = str((adaptive_overlay or {}).get("adaptive_evidence_level", "None"))
    adaptive_reason = str((adaptive_overlay or {}).get("adaptive_reason", "No adaptive overlay"))
    effective_confidence = str((adaptive_overlay or {}).get("effective_prediction_confidence", intelligence.get("prediction_confidence", "-")))
    authority = authority or {}
    authority_decision = str(authority.get("decision", "NO TRADE"))
    authority_confidence = int(authority.get("confidence_score", 0) or 0)
    authority_expected_value = authority.get("expected_value")
    authority_risk_class = str(authority.get("risk_class", "HIGH"))
    authority_reason = str(authority.get("reason_line", decision_reason))
    authority_top_reasons = list(authority.get("top_reasons", []))
    authority_condition = str(authority.get("condition_required", ""))
    use_allowed = bool(authority.get("use_allowed", False))
    override_required = bool(authority.get("override_required", False))
    expected_return_20 = authority.get("expected_return_20")
    expected_return_50 = authority.get("expected_return_50")
    expected_return_100 = authority.get("expected_return_100")
    decision_class = {"STRONG BUY": "enter", "CONDITIONAL BUY": "caution", "NO TRADE": "skip"}.get(authority_decision, "wait")
    ev_display = format_price(authority_expected_value) if authority_expected_value is not None else "Insufficient"
    top_reason_html = "".join(
        f'<span class="spx-chip scenario-neutral">{escape(reason)}</span>'
        for reason in authority_top_reasons[:3]
    )
    locked_entry_value = format_price(intelligence.get("locked_entry_spx")) if intelligence.get("locked_entry_spx") is not None else format_price(play["entry"]["price"])
    drift_pct_value = float(intelligence.get("entry_drift_pct", 0.0) or 0.0) * 100.0 if intelligence.get("entry_drift_pct") is not None else None
    drift_text = (
        f"{format_price(intelligence.get('entry_drift_abs'))} ({drift_pct_value:.1f}%)"
        if intelligence.get("entry_drift_abs") is not None and intelligence.get("entry_drift_pct") is not None
        else "-"
    )
    mark_value = format_price(lead_option_quote.get("price")) if lead_option_quote else "-"
    expected_gain = format_price(lead_option_quote.get("expected_gain")) if lead_option_quote and lead_option_quote.get("expected_gain") is not None else "-"
    expected_loss = format_price(lead_option_quote.get("expected_loss")) if lead_option_quote and lead_option_quote.get("expected_loss") is not None else "-"
    rr_value = str(lead_option_quote.get("rr_ratio")) if lead_option_quote and lead_option_quote.get("rr_ratio") is not None else "-"
    contract_score = str(lead_option_quote.get("contract_score")) if lead_option_quote and lead_option_quote.get("contract_score") is not None else "-"
    detail_bits: list[str] = []
    if not compact and lead_option_quote and (lead_option_quote.get("bid") is not None or lead_option_quote.get("ask") is not None):
        detail_bits.append(
            "Bid/Ask "
            f"{format_price(lead_option_quote.get('bid')) if lead_option_quote.get('bid') is not None else '-'} / {format_price(lead_option_quote.get('ask')) if lead_option_quote.get('ask') is not None else '-'}"
        )

    drift_fill_pct = 0.0 if drift_pct_value is None else max(0.0, min(100.0, (drift_pct_value / 20.0) * 100.0))
    drift_fill_class = "good" if drift_pct_value is not None and drift_pct_value <= 5.0 else "warn" if drift_pct_value is not None and drift_pct_value <= 15.0 else "bad"
    current_spx_display = format_price(current_spx_price) if current_spx_price is not None else "-"
    stop_display = format_price(play["stop"]["price"]) if play.get("stop") and not play.get("invalid_stop") else "Unavailable"
    suggested_stop_display = format_price(intelligence["suggested_stop"]) if intelligence.get("suggested_stop") is not None else "-"
    move_completion_display = f"{float(intelligence.get('move_completion_pct')):.0f}%" if intelligence.get("move_completion_pct") is not None else "-"
    zone_display = str(intelligence.get("entry_zone_status", "UNKNOWN"))
    lock_label = "Locked Entry" if intelligence.get("session_plan_locked") else "Session Entry"
    action_class = _decision_class(action_label)
    title_class = "spx-play-title" if is_primary else "spx-play-title alt"
    regime_tooltip = "Price returning toward planned entry" if intelligence.get("regime") == "PULLBACK" else "Price moving away from planned entry" if intelligence.get("regime") == "EXPANSION" else "Regime unavailable"
    live_scenario = str((live_context or {}).get("live_scenario") or st.session_state.get("current_signal_package", {}).get("scenario", {}).get("scenario_name", ""))
    live_structure_state = format_live_state_label((live_context or {}).get("live_structure_state"))
    transition_note = build_scenario_transition_note(live_context)
    decision_sentence = build_live_decision_sentence(authority=authority, intelligence=intelligence, live_context=live_context)
    expectancy_note = (
        f"20 trades {format_price(expected_return_20)} | 50 trades {format_price(expected_return_50)} | 100 trades {format_price(expected_return_100)}"
        if expected_return_20 is not None and expected_return_50 is not None and expected_return_100 is not None
        else ""
    )
    override_note_html = (
        """
        <div class="spx-risk-note" title="System conditions overridden manually. Increased risk.">
            <span class="spx-risk-note-icon">!</span>
            <span>Signal suppressed due to decision filter</span>
        </div>
        """
        if authority_decision == "NO TRADE"
        else ""
    )
    best_contract_html = ""
    if lead_option_quote and lead_option_quote.get("contract_symbol"):
        best_contract_html = f"""
        <div class="spx-best-contract">
            <div class="spx-best-contract-title">Best Contract</div>
            <div class="spx-best-contract-symbol">{escape(str(lead_option_quote['contract_symbol']))}</div>
            <div class="spx-best-contract-meta">Mark {mark_value} | Pred {live_predicted_mark} | Cal {calibrated_entry_mark} | Fill {expected_fill_mark} | RR {rr_value if intelligence.get('rr_ratio') is not None else '-'} | Score {contract_score}</div>
        </div>
        """

    st.markdown(
        f"""
        <div class="spx-play-shell {'primary' if is_primary else 'alternate'}{' filtered' if authority_decision == 'NO TRADE' else ''}">
            <div class="spx-play-topline">
                <div class="{title_class}">{escape(title)}</div>
                <div class="spx-play-topline-note">{escape(trade_state)} | {escape(play['direction'])} | Strike {escape(str(play['strike']))}</div>
            </div>
            <div class="spx-decision-banner {decision_class}">
                <div>
                    <div class="spx-decision-main">{escape(authority_decision)}</div>
                    <div class="spx-decision-sub">{escape(authority_reason)}</div>
                </div>
                <div class="spx-play-context">
                    <div class="spx-play-context-label">Confidence</div>
                    <div class="spx-play-context-value">{authority_confidence}%</div>
                </div>
            </div>
            <div class="spx-entry-grid">
                <div class="spx-entry-card">
                    <div class="spx-entry-card-label">Planned Entry</div>
                    <div class="spx-entry-card-value">{locked_entry_value} SPX</div>
                    <div class="spx-entry-card-note">ES {format_price(entry_es_value) if entry_es_value is not None else '-'}</div>
                </div>
                <div class="spx-entry-card">
                    <div class="spx-entry-card-label">Current Mark</div>
                    <div class="spx-entry-card-value">{mark_value}</div>
                    <div class="spx-entry-card-note">Strike {escape(str(play['strike']))}</div>
                </div>
            </div>
            <div class="spx-metric-grid secondary">
                <div class="spx-metric-block layer2">
                    <div class="spx-metric-label">Predicted</div>
                    <div class="spx-metric-value">{live_predicted_mark}</div>
                </div>
                <div class="spx-metric-block layer2">
                    <div class="spx-metric-label">Calibrated</div>
                    <div class="spx-metric-value">{calibrated_entry_mark}</div>
                </div>
                <div class="spx-metric-block layer2">
                    <div class="spx-metric-label">Expected Fill</div>
                    <div class="spx-metric-value">{expected_fill_mark}</div>
                </div>
                <div class="spx-metric-block layer2">
                    <div class="spx-metric-label">Evidence</div>
                    <div class="spx-metric-value">{escape(calibration_evidence)}</div>
                </div>
            </div>
            <div class="spx-plan-box">
                <div class="spx-plan-header">
                    <div class="spx-plan-title">Decision Stack</div>
                    <div class="spx-plan-metric">EV {ev_display} | Risk {escape(authority_risk_class)}</div>
                </div>
                <div class="spx-badge-row">{top_reason_html}</div>
                <div class="spx-entry-compare">
                    <div class="spx-entry-compare-block">
                        <div class="spx-entry-compare-label">Plan</div>
                        <div class="spx-entry-compare-value planned">{escape(str(intelligence.get('plan_status', '-')))}</div>
                    </div>
                    <div class="spx-entry-compare-block">
                        <div class="spx-entry-compare-label">Regime</div>
                        <div class="spx-entry-compare-value live">{escape(str(intelligence.get('regime', '-')))}</div>
                    </div>
                </div>
            </div>
        <div class="spx-badge-row">
            <span class="spx-chip {_chip_class(intelligence.get('plan_status', '-'), 'plan')}">{escape(str(intelligence.get('plan_status', '-')))}</span>
            <span class="spx-chip {_chip_class(intelligence.get('regime', '-'), 'regime')}" title="{escape(regime_tooltip)}">{escape(str(intelligence.get('regime', '-')))}</span>
            <span class="spx-chip {_chip_class(intelligence.get('chase_status', '-'), 'chase')}">{escape(str(intelligence.get('chase_status', '-')))}</span>
            <span class="spx-chip {_chip_class(zone_display, 'chase')}">{escape(zone_display)}</span>
            <span class="spx-chip {_chip_class(intelligence.get('prediction_confidence', '-'), 'confidence')}">{escape(str(intelligence.get('prediction_confidence', '-')))}</span>
            <span class="spx-chip {_chip_class(stop_quality['label'], 'confidence')}">{escape(str(stop_quality['label']))}</span>
        </div>
        <div class="spx-badge-row">
            <span class="spx-chip {_chip_class(adaptive_recommendation, 'chase')}">{escape('Adaptive ' + adaptive_recommendation)}</span>
            <span class="spx-chip scenario-neutral">{escape('Evidence ' + adaptive_evidence)}</span>
            <span class="spx-chip {_chip_class(effective_confidence, 'confidence')}">{escape('Eff ' + effective_confidence)}</span>
        </div>
            <div class="spx-metric-grid">
                <div class="spx-metric-block layer1">
                    <div class="spx-metric-label">Entry</div>
                    <div class="spx-metric-value">{locked_entry_value}</div>
                </div>
                <div class="spx-metric-block layer1">
                    <div class="spx-metric-label">Mark</div>
                    <div class="spx-metric-value">{mark_value}</div>
                </div>
                <div class="spx-metric-block layer1{' muted' if authority_decision == 'NO TRADE' else ''}">
                    <div class="spx-metric-label">RR</div>
                    <div class="spx-metric-value">{escape(rr_value if intelligence.get('rr_ratio') is not None else '-')}</div>
                </div>
            </div>
            <div class="spx-metric-grid secondary">
                <div class="spx-metric-block layer2">
                    <div class="spx-metric-label">Stop</div>
                    <div class="spx-metric-value">{stop_display}</div>
                </div>
                <div class="spx-metric-block layer2">
                    <div class="spx-metric-label">Quality</div>
                    <div class="spx-metric-value">{escape(quality_display)}</div>
                </div>
                <div class="spx-metric-block layer2">
                    <div class="spx-metric-label">Risk</div>
                    <div class="spx-metric-value">{escape(authority_risk_class)}</div>
                </div>
                <div class="spx-metric-block layer2">
                    <div class="spx-metric-label">Expected Value</div>
                    <div class="spx-metric-value">{ev_display}</div>
                </div>
            </div>
            <div class="spx-metric-grid tertiary">
                <div class="spx-metric-block layer3">
                    <div class="spx-metric-label">20 Trades</div>
                    <div class="spx-metric-value">{format_price(expected_return_20) if expected_return_20 is not None else 'Insufficient'}</div>
                </div>
                <div class="spx-metric-block layer3">
                    <div class="spx-metric-label">50 Trades</div>
                    <div class="spx-metric-value">{format_price(expected_return_50) if expected_return_50 is not None else 'Insufficient'}</div>
                </div>
                <div class="spx-metric-block layer3">
                    <div class="spx-metric-label">100 Trades</div>
                    <div class="spx-metric-value">{format_price(expected_return_100) if expected_return_100 is not None else 'Insufficient'}</div>
                </div>
            </div>
            <div class="spx-metric-grid tertiary">
                <div class="spx-metric-block layer3">
                    <div class="spx-metric-label">Move</div>
                    <div class="spx-metric-value">{move_completion_display}</div>
                </div>
                <div class="spx-metric-block layer3">
                    <div class="spx-metric-label">Zone</div>
                    <div class="spx-metric-value">{escape(zone_display)}</div>
                </div>
            </div>
            <div class="spx-metric-grid tertiary">
                <div class="spx-metric-block layer3">
                    <div class="spx-metric-label">Adaptive</div>
                    <div class="spx-metric-value">{escape(adaptive_recommendation)}</div>
                </div>
                <div class="spx-metric-block layer3">
                    <div class="spx-metric-label">Adaptive Why</div>
                    <div class="spx-metric-value">{escape(adaptive_reason)}</div>
                </div>
            </div>
            <div class="spx-metric-grid tertiary">
                <div class="spx-metric-block layer3">
                    <div class="spx-metric-label">Suggested Stop</div>
                    <div class="spx-metric-value">{suggested_stop_display}</div>
                </div>
                <div class="spx-metric-block layer3{' muted' if authority_decision == 'NO TRADE' else ''}">
                    <div class="spx-metric-label">Gain</div>
                    <div class="spx-metric-value">{expected_gain}</div>
                </div>
                <div class="spx-metric-block layer3{' muted' if authority_decision == 'NO TRADE' else ''}">
                    <div class="spx-metric-label">Loss</div>
                    <div class="spx-metric-value">{expected_loss}</div>
                </div>
                <div class="spx-metric-block layer3{' muted' if authority_decision == 'NO TRADE' else ''}">
                    <div class="spx-metric-label">Score</div>
                    <div class="spx-metric-value">{escape(contract_score)}</div>
                </div>
            </div>
        <div class="spx-play-note">{escape(authority_condition if authority_decision == 'CONDITIONAL BUY' and authority_condition else ('Manual override active' if authority_decision == 'NO TRADE' else 'Ready to execute if price behavior holds'))}</div>
            {override_note_html}
            {best_contract_html}
        </div>
        """,
        unsafe_allow_html=True,
    )
    if detail_bits:
        st.caption(" | ".join(detail_bits))
    button_key = f"use_play_{title.lower().replace(' ', '_')}"
    override_intent_key = f"{button_key}_override_intent"
    override_reason_key = f"{button_key}_override_reason"
    if use_allowed and st.button("Use This Play", key=button_key, use_container_width=True):
        signal_package = st.session_state.get("current_live_signal_package") or st.session_state.get("current_signal_package")
        if signal_package is None:
            st.warning("No live signal snapshot is available for this play yet.")
        else:
            inferred_play_type = "alternate" if "alternate" in title.lower() else "primary"
            set_trade_form_prefill(
                build_live_play_trade_prefill(
                    signal_package=signal_package,
                    play_type=inferred_play_type,
                    play_spx=play,
                    play_es=play_es,
                    lead_option_quote=lead_option_quote,
                    intelligence=intelligence,
                    final_status=visible_status,
                    final_decision=action_label,
                    authority=authority,
                )
            )
            st.success("Trade Log prefilled from this play.")
    elif not use_allowed:
        st.warning("Manual override active")
        if not st.session_state.get(override_intent_key, False):
            if st.button("Override Trade Guard", key=f"{button_key}_override", use_container_width=True):
                st.session_state[override_intent_key] = True
                st.rerun()
        else:
            override_reason_input = st.text_input("Override reason", key=override_reason_key)
            if st.button("Confirm Override And Use This Play", key=f"{button_key}_confirm_override", use_container_width=True, disabled=not override_reason_input.strip()):
                signal_package = st.session_state.get("current_live_signal_package") or st.session_state.get("current_signal_package")
                if signal_package is None:
                    st.warning("No live signal snapshot is available for this play yet.")
                else:
                    inferred_play_type = "alternate" if "alternate" in title.lower() else "primary"
                    set_trade_form_prefill(
                        build_live_play_trade_prefill(
                            signal_package=signal_package,
                            play_type=inferred_play_type,
                            play_spx=play,
                            play_es=play_es,
                            lead_option_quote=lead_option_quote,
                            intelligence=intelligence,
                            final_status=visible_status,
                            final_decision=action_label,
                            authority=authority,
                            override_flag=True,
                            override_reason=override_reason_input.strip(),
                        )
                    )
                    st.session_state[override_intent_key] = False
                    st.success("Trade Log prefilled with override flag.")
    if developer_mode and effective_offset is not None:
        entry_debug = (play.get("conversion_debug") or {}).get("entry", {})
        with st.expander(f"{title} Conversion Check", expanded=False):
            st.caption(f"Source ES line used: {format_price(entry_debug.get('source_es')) if entry_debug.get('source_es') is not None else 'Unavailable'}")
            if offset_diagnostics is not None:
                st.caption(f"Manual offset: {format_price(offset_diagnostics.get('manual_offset')) if offset_diagnostics.get('manual_offset') is not None else 'Unavailable'}")
                st.caption(f"Inferred/live offset: {format_price(offset_diagnostics.get('live_inferred_offset')) if offset_diagnostics.get('live_inferred_offset') is not None else 'Unavailable'}")
                st.caption(f"Effective offset used: {format_price(offset_diagnostics.get('effective_offset')) if offset_diagnostics.get('effective_offset') is not None else format_price(effective_offset)}")
            else:
                st.caption(f"Effective offset used: {format_price(effective_offset)}")
            st.caption(f"Additional adjustment applied: {format_price(entry_debug.get('additional_adjustment_applied')) if entry_debug.get('additional_adjustment_applied') is not None else '0.00'}")
            st.caption(f"Final displayed SPX entry: {format_price(entry_debug.get('final_displayed_spx')) if entry_debug.get('final_displayed_spx') is not None else format_price(play['entry']['price'])}")
            if play.get("conversion_invalid"):
                st.warning("Conversion check failed: ES - effective offset did not match the incoming SPX entry before alignment.")
            st.caption(
                f"Stop distance: {format_price(stop_quality['distance']) if stop_quality['distance'] is not None else 'Unavailable'} | "
                f"Stop quality rule: Tight < 8, Balanced < 18, Wide < 30, Very Wide >= 30"
            )
            st.caption(
                f"Planned entry mark: {format_price(intelligence.get('planned_entry_mark')) if intelligence.get('planned_entry_mark') is not None else 'Unavailable'} | "
                f"Live predicted entry: {format_price(intelligence.get('live_predicted_entry_mark')) if intelligence.get('live_predicted_entry_mark') is not None else 'Unavailable'} | "
                f"Drift abs: {format_price(intelligence.get('entry_drift_abs')) if intelligence.get('entry_drift_abs') is not None else 'Unavailable'} | "
                f"Drift pct: {float(intelligence.get('entry_drift_pct', 0.0)) * 100:.2f}% | "
                f"Price vs plan: {format_price(intelligence.get('price_vs_plan')) if intelligence.get('price_vs_plan') is not None else 'Unavailable'}"
            )
            st.caption(
                f"Lock cutoff: {intelligence.get('lock_cutoff_label', '-')} | "
                f"Plan locked: {'Yes' if intelligence.get('session_plan_locked') else 'No'} | "
                f"Locked timestamp: {intelligence.get('locked_timestamp') or 'Unavailable'} | "
                f"Locked entry: {format_price(intelligence.get('locked_entry_spx')) if intelligence.get('locked_entry_spx') is not None else 'Unavailable'} | "
                f"Zone: {zone_display} | "
                f"Move completion: {move_completion_display}"
            )
            st.caption(
                f"Timing distance: {format_price(timing['distance']) if timing['distance'] is not None else 'Unavailable'} | "
                f"Timing label: {timing['label']} | "
                f"Hold threshold: {format_price(intelligence.get('hold_threshold'))} | "
                f"Drift threshold: {format_price(intelligence.get('drift_threshold'))} | "
                f"Prediction confidence: {intelligence.get('prediction_confidence', '-')} | "
                f"RR threshold: {intelligence['min_rr']:.2f} | "
                f"Structural: {(status_breakdown or {}).get('structural_status', '-') } | "
                f"Intelligence: {(status_breakdown or {}).get('intelligence_status', intelligence['status'])} | "
                f"Final: {(status_breakdown or {}).get('final_status', visible_status)} | "
                f"Decision: {(status_breakdown or {}).get('final_decision', action_label)} | "
                f"Downgrade reason: {intelligence['downgrade_reason']}"
            )
            st.caption(
                f"Calibration evidence: {calibration_evidence} | "
                f"Prediction bias source: {(calibration_preview or {}).get('prediction_bias_source', 'unavailable')} | "
                f"Prediction samples: {(calibration_preview or {}).get('prediction_sample_count', 0)} | "
                f"Prediction bias: {format_price((calibration_preview or {}).get('prediction_bias_used')) if (calibration_preview or {}).get('prediction_bias_used') is not None else 'Unavailable'} | "
                f"Slippage source: {(calibration_preview or {}).get('slippage_bias_source', 'unavailable')} | "
                f"Slippage samples: {(calibration_preview or {}).get('slippage_sample_count', 0)} | "
                f"Slippage bias: {format_price((calibration_preview or {}).get('slippage_bias_used')) if (calibration_preview or {}).get('slippage_bias_used') is not None else 'Unavailable'}"
            )
            st.caption(
                f"Adaptive RR: base {format_price((adaptive_overlay or {}).get('base_rr_threshold')) if (adaptive_overlay or {}).get('base_rr_threshold') is not None else 'Unavailable'} | "
                f"adaptive {format_price((adaptive_overlay or {}).get('adaptive_rr_threshold')) if (adaptive_overlay or {}).get('adaptive_rr_threshold') is not None else 'NO_ADAPTATION'} | "
                f"source {(adaptive_overlay or {}).get('adaptive_rr_source', 'NO_ADAPTATION')} | "
                f"samples {(adaptive_overlay or {}).get('adaptive_rr_sample_count', 0)} | "
                f"variance {format_price((adaptive_overlay or {}).get('rr_variance')) if (adaptive_overlay or {}).get('rr_variance') is not None else 'Unavailable'} | "
                f"path {' > '.join((adaptive_overlay or {}).get('rr_fallback_path', [])) or '-'}"
            )
            st.caption(
                f"Adaptive chase: base {format_price((adaptive_overlay or {}).get('base_chase_tolerance')) if (adaptive_overlay or {}).get('base_chase_tolerance') is not None else 'Unavailable'} | "
                f"adaptive {format_price((adaptive_overlay or {}).get('adaptive_chase_tolerance')) if (adaptive_overlay or {}).get('adaptive_chase_tolerance') is not None else 'NO_ADAPTATION'} | "
                f"source {(adaptive_overlay or {}).get('chase_adaptation_source', 'NO_ADAPTATION')} | "
                f"samples {(adaptive_overlay or {}).get('chase_sample_count', 0)} | "
                f"variance {format_price((adaptive_overlay or {}).get('chase_variance')) if (adaptive_overlay or {}).get('chase_variance') is not None else 'Unavailable'} | "
                f"path {' > '.join((adaptive_overlay or {}).get('chase_fallback_path', [])) or '-'}"
            )
            st.caption(
                f"Adaptive confidence: raw {(adaptive_overlay or {}).get('raw_prediction_confidence', intelligence.get('prediction_confidence', '-'))} | "
                f"effective {(adaptive_overlay or {}).get('effective_prediction_confidence', intelligence.get('prediction_confidence', '-'))} | "
                f"source {(adaptive_overlay or {}).get('confidence_source', 'NO_ADAPTATION')} | "
                f"samples {(adaptive_overlay or {}).get('confidence_sample_count', 0)} | "
                f"variance {format_price((adaptive_overlay or {}).get('confidence_variance')) if (adaptive_overlay or {}).get('confidence_variance') is not None else 'Unavailable'} | "
                f"path {' > '.join((adaptive_overlay or {}).get('confidence_fallback_path', [])) or '-'} | "
                f"Reason {(adaptive_overlay or {}).get('confidence_adjustment_reason', '-')}"
            )
            st.caption(
                f"Adaptive edge gain est: {format_price((adaptive_overlay or {}).get('adaptive_edge_gain_estimate'))}% | "
                f"Adaptive risk reduction est: {format_price((adaptive_overlay or {}).get('adaptive_risk_reduction_estimate'))}% | "
                f"Override flag: {'Yes' if (adaptive_overlay or {}).get('override_flag') else 'No'}"
            )

def render_projection_verification(
    anchor_bundle: dict[str, Any],
    final_projected_lines_spx: dict[str, dict[str, Any]],
    final_projected_lines_es: dict[str, dict[str, Any]],
    displayed_lines: dict[str, dict[str, Any]],
    displayed_unit_label: str,
) -> None:
    """Temporary verification block proving Tab 1 structure uses a single unit system."""

    def _extract_pivot_extreme_value(pivot_payload: dict[str, Any] | None, pivot_type: str) -> float | None:
        if not pivot_payload:
            return None

        pivot_extreme = pivot_payload.get("pivot_extreme")
        if isinstance(pivot_extreme, dict):
            key = "high" if pivot_type == "high" else "low"
            value = pivot_extreme.get(key)
            if value is not None:
                return float(value)

        source_key = "pivot_high" if pivot_type == "high" else "pivot_low"
        source_points = anchor_bundle.get("source_points") or {}
        source_point = source_points.get(source_key)
        if isinstance(source_point, dict) and source_point.get("price") is not None:
            return float(source_point["price"])

        return None

    def _extract_context_value(pivot_payload: dict[str, Any] | None, candle_key: str, value_key: str) -> float | None:
        if not pivot_payload:
            return None
        candle = pivot_payload.get(candle_key)
        if isinstance(candle, dict) and candle.get(value_key) is not None:
            return float(candle[value_key])
        return None

    verification_rows: list[dict[str, Any]] = []
    warnings: list[str] = get_structure_assertion_warnings(
        final_projected_lines_es,
        displayed_lines,
        displayed_unit_label,
    )

    for name in LINE_DISPLAY_ORDER:
        displayed_details = displayed_lines[name]
        spx_details = final_projected_lines_spx[name]
        es_details = final_projected_lines_es[name]
        raw_es_value = float(anchor_bundle["anchors"][name]["price"])
        projected_es_value = float(es_details["projected_price"])
        displayed_value = float(displayed_details["projected_price"])
        candle_count = int(es_details["candle_count"])

        verification_rows.append(
            {
                "line_label": displayed_details["label"],
                "raw_anchor_es": f"{format_price(raw_es_value)} (ES)",
                "raw_anchor_timestamp": format_timestamp(es_details.get("raw_anchor_timestamp")),
                "projected_es": f"{format_price(projected_es_value)} (ES)",
                "displayed_es": f"{format_price(displayed_value)} ({displayed_unit_label})",
                "candle_count": candle_count,
                "direction": es_details["direction"],
            }
        )

        if name in {"hw", "lw"} and candle_count > 0 and abs(projected_es_value - raw_es_value) < 1e-9:
            warnings.append(
                f"{displayed_details['label']} has candle_count={candle_count} but projected ES still matches the raw ES anchor."
            )

    with st.expander("Projection Verification", expanded=False):
        st.dataframe(verification_rows, use_container_width=True, hide_index=True)
        for warning in warnings:
            st.warning(warning)
        if not warnings:
            st.caption("Verification passed: projected display values differ from raw anchors when candle counts are non-zero.")

        source_points = anchor_bundle.get("source_points")
        if source_points:
            st.dataframe(
                [
                    {
                        "Source Point": source_name,
                        "Timestamp": format_timestamp(details["timestamp"]),
                        "Price (ES)": format_price(details["price"]),
                        "Search Window": details.get("search_window", ""),
                    }
                    for source_name, details in source_points.items()
                ],
                use_container_width=True,
                hide_index=True,
            )


def render_historical_projection_panel(
    inputs: dict[str, Any],
    projection_target,
    anchor_bundle: dict[str, Any],
    projected_lines_es: dict[str, dict[str, Any]],
) -> None:
    """Render a compact historical-date verification block."""

    overnight_start = at_central(inputs["prior_session_date"], 17, 0)
    overnight_end = projection_target
    details = {
        "Prior Session Date": str(inputs["prior_session_date"]),
        "Next Trading Date": str(inputs["next_trading_date"]),
        "Projection Target Timestamp": format_timestamp(projection_target),
        "Data Mode": inputs["data_mode"],
        "Anchor Source": "manual_anchor_bundle" if inputs["data_mode"] == "Manual input" else "auto_fetch_anchor_bundle",
        "Prior Afternoon Pivot Window": f"{format_timestamp(at_central(inputs['prior_session_date'], 11, 0))} -> {format_timestamp(at_central(inputs['prior_session_date'], 16, 0))}",
        "Prior Session Wick Window": f"{format_timestamp(at_central(inputs['prior_session_date'], 8, 0))} -> {format_timestamp(at_central(inputs['prior_session_date'], 16, 0))}",
        "Overnight Window": f"{format_timestamp(overnight_start)} -> {format_timestamp(overnight_end)}",
    }
    rows = [
        {
            "Line": projected_lines_es[name]["label"],
            "Projected Value (ES)": format_price(projected_lines_es[name]["projected_price"]),
        }
        for name in LINE_DISPLAY_ORDER
    ]

    with st.expander("Historical Projection Verification", expanded=False):
        st.json(details, expanded=False)
        st.dataframe(rows, use_container_width=True, hide_index=True)


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
    *,
    compact: bool = False,
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
                    <div class="spx-card-subtitle">{'Compact SPX confirmation.' if compact else 'SPX candle test against the active entry line.'}</div>
                </div>
            </div>
            <div class="spx-banner-meta">
                <span class="spx-pill {tone}">{detail['status_label']}</span>
                <span class="spx-pill">Line {escape(detail['line_tested'])}</span>
            </div>
            {'' if compact else f'<div class="spx-card-copy">{escape(detail["reason"])}</div>'}
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
    elif not compact:
        st.info("No 8:30 candle data available.")

    if not compact:
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
        "source_points": anchor_bundle.get("source_points"),
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

    developer_mode = settings.get("visibility_mode") == "Edge Lab"

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

    journal_tabs = st.tabs(["Log Trade", "Review Outcomes", "Analytics / Edge"])
    log_tab, review_tab, analytics_tab = journal_tabs

    with log_tab:
        render_section_header("Log Trade", "Capture the exact decision snapshot fast, then add execution details only if needed.")
        with st.container(border=True):
            summary_cols = st.columns(5)
            summary_cols[0].metric("Decision", str(prefill.get("final_authority_decision") or prefill.get("final_decision") or "Unspecified"))
            summary_cols[1].metric("Confidence", f"{float(prefill.get('final_authority_confidence', 0.0)):.0f}%")
            summary_cols[2].metric("Risk", str(prefill.get("final_authority_risk_class") or "Unrated"))
            summary_cols[3].metric("Expected Value", format_price(_to_float_or_none(prefill.get("final_authority_expected_value"))) if _to_float_or_none(prefill.get("final_authority_expected_value")) is not None else "Insufficient")
            summary_cols[4].metric("Override", "Yes" if prefill.get("override_flag") else "No")
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
                entry_value = st.number_input("Entry premium or entry price", value=float(prefill.get("entry_value", 0.0)), step=0.05, format="%.2f")
                exit_value = st.number_input("Exit premium or exit price", value=0.0, step=0.05, format="%.2f")
                stop_value = st.number_input("Stop value", value=float(prefill.get("stop_value", 0.0)), step=0.05, format="%.2f")
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
            with st.expander("Outcome Tracking", expanded=False):
                review_col1, review_col2 = st.columns(2)
                with review_col1:
                    actual_trade_taken = st.checkbox("Trade actually taken", value=bool(prefill.get("actual_trade_taken", False)))
                    actual_entry_price_spx = st.number_input("Actual entry SPX", value=float(prefill.get("actual_entry_price_spx", prefill.get("entry_spx", 0.0))), step=0.25, format="%.2f")
                    actual_exit_price_spx = st.number_input("Actual exit SPX", value=float(prefill.get("actual_exit_price_spx", 0.0)), step=0.25, format="%.2f")
                    actual_stop_used = st.number_input("Actual stop used", value=float(prefill.get("actual_stop_used", prefill.get("stop_value", 0.0))), step=0.25, format="%.2f")
                    actual_exit_reason = st.text_input("Actual exit reason", value=str(prefill.get("actual_exit_reason", "")))
                with review_col2:
                    actual_contract_symbol = st.text_input("Actual contract symbol", value=str(prefill.get("actual_contract_symbol", prefill.get("selected_contract_symbol", ""))))
                    actual_contract_mark_if_known = st.number_input("Actual fill mark", value=float(prefill.get("actual_contract_mark_if_known", prefill.get("entry_value", 0.0))), step=0.05, format="%.2f")
                    actual_notes = st.text_area("Execution notes", value=str(prefill.get("actual_notes", "")), height=80)
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
                    "entry_spx": float(prefill.get("entry_spx", entry_line_value)),
                    "entry_es": float(prefill.get("entry_es", 0.0)),
                    "entry_value": entry_value,
                    "stop_value": stop_value,
                    "suggested_stop_spx": float(prefill.get("suggested_stop_spx", 0.0)),
                    "option_mark_at_decision": float(prefill.get("option_mark_at_decision", 0.0)),
                    "current_mark": float(prefill.get("current_mark", prefill.get("option_mark_at_decision", 0.0))),
                    "predicted_entry_price": float(prefill.get("predicted_entry_price", 0.0)),
                    "planned_entry_mark": float(prefill.get("planned_entry_mark", prefill.get("predicted_entry_price", 0.0))),
                    "live_predicted_entry_mark": float(prefill.get("live_predicted_entry_mark", prefill.get("predicted_entry_price", 0.0))),
                    "lock_cutoff": str(prefill.get("lock_cutoff", "")),
                    "session_plan_locked": bool(prefill.get("session_plan_locked", False)),
                    "locked_timestamp": str(prefill.get("locked_timestamp", "")),
                    "locked_entry_spx": float(prefill.get("locked_entry_spx", prefill.get("entry_spx", entry_line_value))),
                    "locked_entry_es": float(prefill.get("locked_entry_es", prefill.get("entry_es", 0.0))),
                    "locked_entry_mark": float(prefill.get("locked_entry_mark", prefill.get("planned_entry_mark", prefill.get("predicted_entry_price", 0.0)))),
                    "locked_strike": str(prefill.get("locked_strike", strike_or_contract_label)),
                    "locked_direction": str(prefill.get("locked_direction", direction)),
                    "locked_stop_spx": float(prefill.get("locked_stop_spx", stop_value)),
                    "locked_suggested_stop_spx": float(prefill.get("locked_suggested_stop_spx", prefill.get("suggested_stop_spx", 0.0))),
                    "locked_expected_gain": float(prefill.get("locked_expected_gain", prefill.get("expected_gain", 0.0))),
                    "locked_expected_loss": float(prefill.get("locked_expected_loss", prefill.get("expected_loss", 0.0))),
                    "locked_rr_ratio": float(prefill.get("locked_rr_ratio", prefill.get("rr_ratio", 0.0))),
                    "locked_contract_symbol": str(prefill.get("locked_contract_symbol", prefill.get("selected_contract_symbol", ""))),
                    "locked_contract_score": float(prefill.get("locked_contract_score", prefill.get("contract_score", 0.0))),
                    "play_role": str(prefill.get("play_role", prefill.get("play_type", ""))),
                    "plan_locked": bool(prefill.get("plan_locked", prefill.get("session_plan_locked", False))),
                    "lock_cutoff_used": str(prefill.get("lock_cutoff_used", prefill.get("lock_cutoff", ""))),
                    "plan_locked_timestamp": str(prefill.get("plan_locked_timestamp", prefill.get("locked_timestamp", ""))),
                    "final_decision_at_lock": str(prefill.get("final_decision_at_lock", prefill.get("final_decision", ""))),
                    "entry_zone_status": str(prefill.get("entry_zone_status", "")),
                    "move_completion_pct": float(prefill.get("move_completion_pct", 0.0)),
                    "current_spx_at_decision": float(prefill.get("current_spx_at_decision", prefill.get("entry_spx", entry_line_value))),
                    "current_es_at_decision": float(prefill.get("current_es_at_decision", prefill.get("entry_es", 0.0))),
                    "current_mark_at_decision": float(prefill.get("current_mark_at_decision", prefill.get("current_mark", prefill.get("option_mark_at_decision", 0.0)))),
                    "selected_contract_symbol": str(prefill.get("selected_contract_symbol", "")),
                    "best_contract_selected": bool(prefill.get("best_contract_selected", False)),
                    "play_type": str(prefill.get("play_type", "")),
                    "expected_gain": float(prefill.get("expected_gain", 0.0)),
                    "expected_loss": float(prefill.get("expected_loss", 0.0)),
                    "rr_ratio": float(prefill.get("rr_ratio", 0.0)),
                    "contract_score": float(prefill.get("contract_score", 0.0)),
                    "regime": str(prefill.get("regime", "")),
                    "plan_status": str(prefill.get("plan_status", "")),
                    "chase_status": str(prefill.get("chase_status", "")),
                    "prediction_confidence": str(prefill.get("prediction_confidence", "")),
                    "final_decision": str(prefill.get("final_decision", "")),
                    "final_authority_decision": str(prefill.get("final_authority_decision", prefill.get("final_decision", ""))),
                    "final_authority_confidence": float(prefill.get("final_authority_confidence", 0.0)),
                    "final_authority_expected_value": float(prefill.get("final_authority_expected_value", 0.0)),
                    "final_authority_risk_class": str(prefill.get("final_authority_risk_class", "")),
                    "final_authority_reason": str(prefill.get("final_authority_reason", "")),
                    "final_authority_top_reasons": list(prefill.get("final_authority_top_reasons", [])),
                    "expected_return_20": float(prefill.get("expected_return_20", 0.0)),
                    "expected_return_50": float(prefill.get("expected_return_50", 0.0)),
                    "expected_return_100": float(prefill.get("expected_return_100", 0.0)),
                    "decision_state_at_action": str(prefill.get("decision_state_at_action", prefill.get("final_authority_decision", prefill.get("final_decision", "")))),
                    "override_flag": bool(prefill.get("override_flag", False)),
                    "override_reason": str(prefill.get("override_reason", "")),
                    "entry_drift_abs": float(prefill.get("entry_drift_abs", 0.0)),
                    "entry_drift_pct": float(prefill.get("entry_drift_pct", 0.0)),
                    "price_vs_plan": float(prefill.get("price_vs_plan", 0.0)),
                    "stop_quality": str(prefill.get("stop_quality", "")),
                    "trade_quality": str(prefill.get("trade_quality", "")),
                    "integrity_flags": list(prefill.get("integrity_flags", [])),
                    "actual_trade_taken": actual_trade_taken,
                    "actual_entry_price_option": entry_value if actual_trade_taken else 0.0,
                    "actual_entry_price_spx": actual_entry_price_spx if actual_trade_taken else 0.0,
                    "actual_contract_symbol": actual_contract_symbol,
                    "actual_contract_mark_if_known": actual_contract_mark_if_known if actual_trade_taken else 0.0,
                    "actual_stop_used": actual_stop_used if actual_trade_taken else 0.0,
                    "actual_exit_price_option": exit_value if actual_trade_taken else 0.0,
                    "actual_exit_price_spx": actual_exit_price_spx if actual_trade_taken else 0.0,
                    "actual_exit_reason": actual_exit_reason,
                    "actual_contracts": int(contracts),
                    "actual_notes": actual_notes,
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

    with review_tab:
        render_section_header("Review Outcomes", "Compare the plan, the trade, and what actually happened.")
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
    learning_metrics = build_learning_dashboard_metrics(filtered_trades)
    outcome_review_df = build_outcome_review_dataframe(filtered_trades, developer_mode=developer_mode)
    prediction_bias_by_scenario = build_bias_breakdown_dataframe(filtered_trades, group_field="scenario_name", metric_field="prediction_error_signed")
    prediction_bias_by_direction = build_bias_breakdown_dataframe(filtered_trades, group_field="direction", metric_field="prediction_error_signed")
    prediction_bias_by_regime = build_bias_breakdown_dataframe(filtered_trades, group_field="regime", metric_field="prediction_error_signed")
    slippage_bias_by_scenario = build_bias_breakdown_dataframe(filtered_trades, group_field="scenario_name", metric_field="fill_slippage_signed")
    slippage_bias_by_regime = build_bias_breakdown_dataframe(filtered_trades, group_field="regime", metric_field="fill_slippage_signed")
    slippage_bias_by_chase = build_bias_breakdown_dataframe(filtered_trades, group_field="chase_status", metric_field="fill_slippage_signed")
    confidence_calibration_df = build_confidence_calibration_dataframe(filtered_trades)
    chase_calibration_df = build_chase_calibration_dataframe(filtered_trades)
    calibration_preview = resolve_calibration_preview(filtered_trades, prefill)
    history_dataframe = build_trade_history_dataframe(filtered_trades)
    review_low_data = build_low_data_state(filtered_trades, minimum=3, label="reviewed trades")
    analytics_low_data = build_low_data_state(filtered_trades, minimum=5, label="reviewed trades")

    with review_tab:
        render_section_header("Outcome Review", "Compare the locked plan and decision snapshot to what actually happened.")
        if outcome_review_df.empty:
            st.info(review_low_data["message"] or "No reviewed trade outcomes are available yet.")
        else:
            review_columns = [
                "date",
                "scenario",
                "play",
                "decision",
                "outcome",
                "planned_mark",
                "actual_mark",
                "pred_error",
                "planned_spx",
                "actual_spx",
                "entry_gap",
                "exp_gain",
                "real_gain",
                "gain_gap",
                "exp_loss",
                "real_loss",
                "loss_gap",
                "decision_correct",
                "regime_correct",
                "chase_correct",
                "slippage",
            ]
            if developer_mode:
                review_columns.extend(["plan_status", "regime", "chase", "entry_zone", "move_completion_pct"])
            st.dataframe(outcome_review_df[review_columns], use_container_width=True, hide_index=True)

        review_col, history_col = st.columns([1.15, 1], gap="large")
        with review_col:
            with st.container(border=True):
                st.markdown("#### Journal History")
                if history_dataframe.empty:
                    st.info("No trades saved yet.")
                else:
                    st.dataframe(
                        history_dataframe.drop(columns=["id"], errors="ignore"),
                        use_container_width=True,
                        hide_index=True,
                    )

                    st.markdown("#### Equity Curve")
                    pnl_series = history_dataframe[["date", "pnl"]].copy()
                    pnl_series["cumulative_pnl"] = pnl_series["pnl"].cumsum()
                    st.line_chart(pnl_series.set_index("date")["cumulative_pnl"])

            with st.container(border=True):
                st.markdown("#### Snapshot Review")
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
                    if developer_mode:
                        with st.expander("Selected Snapshot Payload", expanded=False):
                            st.json(selected_snapshot, expanded=False)

        with history_col:
            with st.container(border=True):
                st.markdown("#### Journal Actions")
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
                st.markdown("#### Result Mix")
                if history_dataframe.empty:
                    st.info("No saved trade results yet.")
                else:
                    result_counts = history_dataframe["result"].value_counts()
                    st.bar_chart(result_counts)

    with analytics_tab:
        render_section_header("Analytics / Edge", "Performance, calibration, learning, and strategy intelligence in one place.")
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
        if not analytics_low_data["enough"]:
            st.info(analytics_low_data["message"])

        render_section_header("Learning Loop", "Measure prediction quality, decision quality, and plan integrity against actual execution.")
        learn_col1, learn_col2, learn_col3 = st.columns(3)
        learn_col1.metric("Avg Prediction Error", format_price(learning_metrics["avg_prediction_error"]))
        learn_col2.metric("Median Prediction Error", format_price(learning_metrics["median_prediction_error"]))
        learn_col3.metric("Avg Slippage", format_price(learning_metrics["avg_slippage"]))
        learn_col4, learn_col5, learn_col6 = st.columns(3)
        learn_col4.metric("Filled Better Than Predicted", f"{learning_metrics['filled_better_pct']:.2f}%")
        learn_col5.metric("Regime Correct", f"{learning_metrics['regime_correct_pct']:.2f}%")
        learn_col6.metric("Chase Correct", f"{learning_metrics['chase_correct_pct']:.2f}%")
        learn_col7, learn_col8, learn_col9, learn_col10 = st.columns(4)
        learn_col7.metric("Correct Skip", str(learning_metrics["correct_skip_count"]))
        learn_col8.metric("Wrong Skip", str(learning_metrics["wrong_skip_count"]))
        learn_col9.metric("Correct Entry", str(learning_metrics["correct_entry_count"]))
        learn_col10.metric("Wrong Entry", str(learning_metrics["wrong_entry_count"]))
        plan_col1, plan_col2, plan_col3, plan_col4 = st.columns(4)
        plan_col1.metric("Holding -> Good Entry", f"{learning_metrics['holding_good_entry_pct']:.2f}%")
        plan_col2.metric("Broken -> Should Skip", f"{learning_metrics['broken_should_skip_pct']:.2f}%")
        plan_col3.metric("Avg Move Completion Before Entry", f"{learning_metrics['avg_move_completion_before_entry']:.2f}%")
        plan_col4.metric("Avg Move Completion Missed", f"{learning_metrics['avg_move_completion_missed']:.2f}%")

        render_section_header("Calibration", "Use observed bias to surface corrected guidance without overwriting the raw prediction.")
        calibration_col1, calibration_col2, calibration_col3, calibration_col4 = st.columns(4)
        derived_rows = [derive_outcome_tracking_fields(trade) for trade in filtered_trades]
        prediction_bias_values = [float(row["prediction_error_signed"]) for row in derived_rows if row.get("prediction_error_signed") is not None]
        slippage_bias_values = [float(row["fill_slippage_signed"]) for row in derived_rows if row.get("fill_slippage_signed") is not None]
        prediction_bias_metric = round_price(float(pd.Series(prediction_bias_values).mean())) if prediction_bias_values else 0.0
        slippage_bias_metric = round_price(float(pd.Series(slippage_bias_values).mean())) if slippage_bias_values else 0.0
        calibration_col1.metric("Prediction Bias", format_price(prediction_bias_metric))
        calibration_col2.metric("Slippage Bias", format_price(slippage_bias_metric))
        calibration_col3.metric("Calibrated Entry", format_price(calibration_preview["calibrated_entry_mark"]) if calibration_preview["calibrated_entry_mark"] is not None else "Insufficient")
        calibration_col4.metric("Expected Fill", format_price(calibration_preview["expected_fill_mark"]) if calibration_preview["expected_fill_mark"] is not None else "Insufficient")
        if developer_mode:
            st.caption(
                f"Prediction bias source: {calibration_preview['prediction_bias_source']} | "
                f"Slippage bias source: {calibration_preview['slippage_bias_source']} | "
                f"Prediction bias used: {format_price(calibration_preview['prediction_bias_used']) if calibration_preview['prediction_bias_used'] is not None else 'Unavailable'} | "
                f"Slippage bias used: {format_price(calibration_preview['slippage_bias_used']) if calibration_preview['slippage_bias_used'] is not None else 'Unavailable'}"
            )
        else:
            st.caption("Calibrated values are additive overlays on the raw predicted entry and current fill expectation.")

        confidence_col1, confidence_col2 = st.columns(2)
        with confidence_col1:
            st.markdown("**Confidence Calibration**")
            if confidence_calibration_df.empty:
                st.info("Insufficient reviewed confidence data.")
            else:
                st.dataframe(confidence_calibration_df, use_container_width=True, hide_index=True)
        with confidence_col2:
            st.markdown("**Chase Calibration**")
            if chase_calibration_df.empty:
                st.info("Insufficient reviewed chase data.")
            else:
                st.dataframe(chase_calibration_df, use_container_width=True, hide_index=True)

        if developer_mode:
            bias_tab1, bias_tab2 = st.tabs(["Prediction Bias", "Slippage Bias"])
            with bias_tab1:
                st.markdown("**By Scenario**")
                st.dataframe(prediction_bias_by_scenario, use_container_width=True, hide_index=True) if not prediction_bias_by_scenario.empty else st.info("Insufficient scenario bias data.")
                st.markdown("**By Direction**")
                st.dataframe(prediction_bias_by_direction, use_container_width=True, hide_index=True) if not prediction_bias_by_direction.empty else st.info("Insufficient direction bias data.")
                st.markdown("**By Regime**")
                st.dataframe(prediction_bias_by_regime, use_container_width=True, hide_index=True) if not prediction_bias_by_regime.empty else st.info("Insufficient regime bias data.")
            with bias_tab2:
                st.markdown("**By Scenario**")
                st.dataframe(slippage_bias_by_scenario, use_container_width=True, hide_index=True) if not slippage_bias_by_scenario.empty else st.info("Insufficient scenario slippage data.")
                st.markdown("**By Regime**")
                st.dataframe(slippage_bias_by_regime, use_container_width=True, hide_index=True) if not slippage_bias_by_regime.empty else st.info("Insufficient regime slippage data.")
                st.markdown("**By Chase Status**")
                st.dataframe(slippage_bias_by_chase, use_container_width=True, hide_index=True) if not slippage_bias_by_chase.empty else st.info("Insufficient chase slippage data.")

        render_section_header("Strategy Intelligence", "Compare outcomes by scenario, confluence, session, confirmation, and tags.")
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

        render_section_header("Decision Filter Intelligence", "Review which filters and confirmations actually improve outcomes.")
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

        render_section_header("Expectancy", "See what happens when you trust the system repeatedly.")
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

        render_section_header("Setup Quality", "Spot the strongest and weakest edges in the filtered record set.")
        setup_quality = build_setup_quality_summary(filtered_trades)
        quality_col1, quality_col2, quality_col3 = st.columns(3)
        quality_col1.metric("Highest Expectancy Scenario", setup_quality["highest_expectancy_scenario"])
        quality_col2.metric("Lowest Expectancy Scenario", setup_quality["lowest_expectancy_scenario"])
        quality_col3.metric("Highest Expectancy Confirmation", setup_quality["highest_expectancy_confirmation"])
        quality_col4, quality_col5 = st.columns(2)
        quality_col4.metric("Strongest Session", setup_quality["strongest_session"])
        quality_col5.metric("Weakest Session", setup_quality["weakest_session"])

        export_col, health_col = st.columns([1.2, 1], gap="large")
        with export_col:
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
        with health_col:
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


def build_synthetic_spx_session(es_candles: pd.DataFrame | None, es_spx_offset: float) -> pd.DataFrame:
    """Convert fetched ES candles into a synthetic SPX frame for historical review."""

    if es_candles is None or es_candles.empty:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])

    synthetic = es_candles.copy()
    for column in ("open", "high", "low", "close"):
        synthetic[column] = synthetic[column].astype(float) - float(es_spx_offset)
    return synthetic


def get_next_day_session_candles(candles: pd.DataFrame | None, next_trading_date: date) -> pd.DataFrame:
    """Filter a fetched candle set down to the selected next-trading-day session."""

    if candles is None or candles.empty:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])
    return filter_time_range(candles, at_central(next_trading_date, 8, 0), at_central(next_trading_date, 16, 0))


def review_play_against_session(
    play_spx: dict[str, Any] | None,
    projected_lines_spx: dict[str, dict[str, Any]],
    session_candles_spx: pd.DataFrame,
) -> dict[str, Any]:
    """Build a simple next-session trigger review for one play."""

    if play_spx is None:
        return {"available": False, "summary": "No play available."}
    if session_candles_spx.empty:
        return {"available": False, "summary": "No next-day session candles available."}

    play = resolve_play_display_values(play_spx, projected_lines_spx)
    if play is None:
        return {"available": False, "summary": "Play could not be resolved."}
    if play.get("invalid_stop") or not play.get("stop"):
        return {
            "available": False,
            "summary": "Stop not defined.",
            "integrity_flags": ["invalid_stop"],
        }

    def touched(row: pd.Series, level: float | None) -> bool:
        return level is not None and float(row["low"]) <= float(level) <= float(row["high"])

    entry_price = float(play["entry"]["price"])
    stop_price = float(play["stop"]["price"]) if play.get("stop") else None
    tp1_price = float(play["tp1"]["price"]) if play.get("tp1") else None
    tp2_price = float(play["tp2"]["price"]) if play.get("tp2") else None

    entry_time = stop_time = tp1_time = tp2_time = None
    for _, row in session_candles_spx.iterrows():
        if entry_time is None and touched(row, entry_price):
            entry_time = row["timestamp"]
        if entry_time is None:
            continue
        if stop_time is None and touched(row, stop_price):
            stop_time = row["timestamp"]
        if tp1_time is None and touched(row, tp1_price):
            tp1_time = row["timestamp"]
        if tp2_time is None and touched(row, tp2_price):
            tp2_time = row["timestamp"]

    if entry_time is None:
        summary = "Entry not triggered"
    elif stop_time is not None and (tp1_time is None or stop_time <= tp1_time):
        summary = "Stopped after trigger"
    elif tp2_time is not None:
        summary = "TP2 reached"
    elif tp1_time is not None:
        summary = "TP1 reached"
    else:
        summary = "Triggered with no target/stop touch"

    return {
        "available": True,
        "summary": summary,
        "entry_time": entry_time,
        "stop_time": stop_time,
        "tp1_time": tp1_time,
        "tp2_time": tp2_time,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "tp1_price": tp1_price,
        "tp2_price": tp2_price,
        "integrity_flags": list(play.get("integrity_flags", [])),
    }


def compute_directional_points(direction: str, entry_price: float, exit_price: float) -> float:
    """Compute simple directional point P&L from a line-based entry/exit pair."""

    normalized = str(direction or "").upper()
    if normalized in {"PUT", "SHORT"}:
        return round_price(float(entry_price) - float(exit_price))
    return round_price(float(exit_price) - float(entry_price))


def confirmation_status_label(confirmation: dict[str, Any]) -> str:
    """Normalize a confirmation payload into a compact label."""

    if not confirmation.get("available"):
        return "Not Recorded"
    if confirmation.get("confirmed"):
        return "Confirmed"
    if confirmation.get("failed"):
        return "Failed"
    return "Not Recorded"


def evaluate_play_outcome(
    play_spx: dict[str, Any] | None,
    projected_lines_spx: dict[str, dict[str, Any]],
    session_candles_spx: pd.DataFrame,
) -> dict[str, Any]:
    """Evaluate trigger ordering, result classification, and estimated points for one play."""

    if play_spx is None:
        return {
            "available": False,
            "entry_triggered": False,
            "stop_hit": False,
            "tp1_hit": False,
            "tp2_hit": False,
            "result_classification": "No Play",
            "estimated_pnl": 0.0,
            "event_order": "No play",
        }

    play = resolve_play_display_values(play_spx, projected_lines_spx)
    if play is None or session_candles_spx.empty:
        return {
            "available": False,
            "entry_triggered": False,
            "stop_hit": False,
            "tp1_hit": False,
            "tp2_hit": False,
            "result_classification": "No Session Data",
            "estimated_pnl": 0.0,
            "event_order": "Unavailable",
            "integrity_flags": [],
        }
    if play.get("invalid_stop") or not play.get("stop"):
        return {
            "available": False,
            "entry_triggered": False,
            "stop_hit": False,
            "tp1_hit": False,
            "tp2_hit": False,
            "result_classification": "Invalid Stop",
            "estimated_pnl": 0.0,
            "event_order": "Invalid stop",
            "integrity_flags": ["invalid_stop"],
        }

    entry_price = float(play["entry"]["price"])
    stop_price = float(play["stop"]["price"]) if play.get("stop") else None
    tp1_price = float(play["tp1"]["price"]) if play.get("tp1") else None
    tp2_price = float(play["tp2"]["price"]) if play.get("tp2") else None
    direction = str(play.get("direction", "CALL"))

    def touched(row: pd.Series, level: float | None) -> bool:
        return level is not None and float(row["low"]) <= float(level) <= float(row["high"])

    entry_triggered = False
    entry_time = None
    stop_time = None
    tp1_time = None
    tp2_time = None
    event_order: list[str] = []
    result_classification = "Not Triggered"
    estimated_pnl = 0.0
    ambiguous = False

    for _, row in session_candles_spx.iterrows():
        if not entry_triggered and touched(row, entry_price):
            entry_triggered = True
            entry_time = row["timestamp"]
            event_order.append(f"entry@{format_timestamp(entry_time)}")
        if not entry_triggered:
            continue

        row_events: list[tuple[str, float]] = []
        if stop_time is None and touched(row, stop_price):
            row_events.append(("stop", float(stop_price)))
        if tp1_time is None and touched(row, tp1_price):
            row_events.append(("tp1", float(tp1_price)))
        if tp2_time is None and touched(row, tp2_price):
            row_events.append(("tp2", float(tp2_price)))

        if len(row_events) > 1 and any(name == "stop" for name, _ in row_events) and any(name.startswith("tp") for name, _ in row_events):
            ambiguous = True
            for name, _ in row_events:
                event_order.append(f"{name}@{format_timestamp(row['timestamp'])}")
            result_classification = "Ambiguous Same-Bar Outcome"
            estimated_pnl = 0.0
            break

        for name, price in row_events:
            if name == "stop":
                stop_time = row["timestamp"]
                event_order.append(f"stop@{format_timestamp(stop_time)}")
            elif name == "tp1":
                tp1_time = row["timestamp"]
                event_order.append(f"tp1@{format_timestamp(tp1_time)}")
            elif name == "tp2":
                tp2_time = row["timestamp"]
                event_order.append(f"tp2@{format_timestamp(tp2_time)}")

        if tp2_time is not None:
            result_classification = "TP2"
            estimated_pnl = compute_directional_points(direction, entry_price, float(tp2_price))
            break
        if stop_time is not None and tp1_time is None:
            result_classification = "Stopped"
            estimated_pnl = compute_directional_points(direction, entry_price, float(stop_price))
            break

    if not entry_triggered:
        result_classification = "Not Triggered"
    elif not ambiguous:
        if result_classification == "Not Triggered" and tp1_time is not None and stop_time is not None:
            result_classification = "TP1 Then Stop"
            estimated_pnl = round_price(
                (
                    compute_directional_points(direction, entry_price, float(tp1_price))
                    + compute_directional_points(direction, entry_price, float(stop_price))
                ) / 2.0
            )
        elif result_classification == "Not Triggered" and tp1_time is not None:
            result_classification = "TP1"
            estimated_pnl = compute_directional_points(direction, entry_price, float(tp1_price))
        elif result_classification == "Not Triggered":
            result_classification = "Triggered No Exit"
            estimated_pnl = 0.0

    return {
        "available": True,
        "entry_triggered": entry_triggered,
        "entry_time": entry_time,
        "stop_hit": stop_time is not None,
        "stop_time": stop_time,
        "tp1_hit": tp1_time is not None,
        "tp1_time": tp1_time,
        "tp2_hit": tp2_time is not None,
        "tp2_time": tp2_time,
        "result_classification": result_classification,
        "estimated_pnl": round_price(estimated_pnl),
        "event_order": " -> ".join(event_order) if event_order else "No events",
        "integrity_flags": list(play.get("integrity_flags", [])),
    }


def build_backtest_metrics(filtered_rows: pd.DataFrame) -> dict[str, float]:
    """Build top-line backtest metrics from filtered result rows."""

    if filtered_rows.empty:
        return {
            "setups_tested": 0,
            "trade_count": 0,
            "win_rate": 0.0,
            "loss_rate": 0.0,
            "average_pnl": 0.0,
            "total_pnl": 0.0,
            "expectancy": 0.0,
        }

    trades = filtered_rows.loc[filtered_rows["trade_taken"]].copy()
    if trades.empty:
        return {
            "setups_tested": int(len(filtered_rows)),
            "trade_count": 0,
            "win_rate": 0.0,
            "loss_rate": 0.0,
            "average_pnl": 0.0,
            "total_pnl": 0.0,
            "expectancy": 0.0,
        }

    wins = trades.loc[trades["estimated_pnl"] > 0]
    losses = trades.loc[trades["estimated_pnl"] < 0]
    trade_count = len(trades)
    win_rate = len(wins) / trade_count if trade_count else 0.0
    loss_rate = len(losses) / trade_count if trade_count else 0.0
    average_win = float(wins["estimated_pnl"].mean()) if not wins.empty else 0.0
    average_loss = abs(float(losses["estimated_pnl"].mean())) if not losses.empty else 0.0
    expectancy = (win_rate * average_win) - (loss_rate * average_loss)

    return {
        "setups_tested": int(len(filtered_rows)),
        "trade_count": int(trade_count),
        "win_rate": round_price(win_rate * 100.0),
        "loss_rate": round_price(loss_rate * 100.0),
        "average_pnl": round_price(float(trades["estimated_pnl"].mean())),
        "total_pnl": round_price(float(trades["estimated_pnl"].sum())),
        "expectancy": round_price(expectancy),
    }


def compute_backtest_expectancy(pnl_series: pd.Series) -> float:
    """Compute expectancy from a points P&L series."""

    clean = pd.to_numeric(pnl_series, errors="coerce").dropna()
    if clean.empty:
        return 0.0
    wins = clean.loc[clean > 0]
    losses = clean.loc[clean < 0]
    count = len(clean)
    win_rate = len(wins) / count if count else 0.0
    loss_rate = len(losses) / count if count else 0.0
    average_win = float(wins.mean()) if not wins.empty else 0.0
    average_loss = abs(float(losses.mean())) if not losses.empty else 0.0
    return round_price((win_rate * average_win) - (loss_rate * average_loss))


def build_group_backtest_summary(rows: pd.DataFrame, group_column: str) -> pd.DataFrame:
    """Summarize grouped backtest trade performance."""

    trades = rows.loc[rows["trade_taken"]].copy()
    if trades.empty or group_column not in trades.columns:
        return pd.DataFrame()
    grouped = trades.groupby(group_column, dropna=False)
    summary = grouped["estimated_pnl"].agg(["count", "sum", "mean"]).reset_index()
    summary = summary.rename(
        columns={
            group_column: group_column,
            "count": "trade_count",
            "sum": "total_pnl",
            "mean": "average_pnl",
        }
    )
    summary["win_rate"] = grouped["estimated_pnl"].apply(lambda s: round_price(s.gt(0).mean() * 100.0)).values
    summary["expectancy"] = grouped["estimated_pnl"].apply(compute_backtest_expectancy).values
    return summary


def select_card_winner(summary: pd.DataFrame, label_column: str, metric_column: str, highest: bool = True) -> str:
    """Return a compact label for the best or worst grouped metric."""

    if summary.empty or metric_column not in summary.columns:
        return "N/A"
    ranked = summary.loc[summary["trade_count"] > 0].copy()
    if ranked.empty:
        return "N/A"
    ranked = ranked.sort_values(by=[metric_column, "trade_count"], ascending=[not highest, False])
    best = ranked.iloc[0]
    return f"{best[label_column]} ({format_price(float(best[metric_column])) if metric_column != 'win_rate' else f'{float(best[metric_column]):.1f}%'} | n={int(best['trade_count'])})"


def build_play_path_summary(rows: pd.DataFrame, prefix: str) -> dict[str, float]:
    """Summarize either the primary or alternate path."""

    trigger_col = f"{prefix}_entry_triggered"
    pnl_col = f"{prefix}_estimated_pnl"
    if rows.empty or trigger_col not in rows.columns or pnl_col not in rows.columns:
        return {"triggered": 0, "win_rate": 0.0, "total_pnl": 0.0}
    triggered_rows = rows.loc[rows[trigger_col]].copy()
    if triggered_rows.empty:
        return {"triggered": 0, "win_rate": 0.0, "total_pnl": 0.0}
    return {
        "triggered": int(len(triggered_rows)),
        "win_rate": round_price(triggered_rows[pnl_col].gt(0).mean() * 100.0),
        "total_pnl": round_price(float(triggered_rows[pnl_col].sum())),
    }


def classify_first_outcome(review: dict[str, Any]) -> str:
    """Reduce a play review into a first-outcome bucket."""

    if not review.get("entry_triggered"):
        return "No Trade"
    if review.get("result_classification") == "Ambiguous Same-Bar Outcome":
        return "Ambiguous Same-Bar"
    stop_time = review.get("stop_time")
    tp1_time = review.get("tp1_time")
    tp2_time = review.get("tp2_time")
    events: list[tuple[str, Any]] = []
    if stop_time is not None:
        events.append(("Stop Hit First", stop_time))
    if tp1_time is not None:
        events.append(("TP1 Hit First", tp1_time))
    if tp2_time is not None:
        events.append(("TP2 Hit First", tp2_time))
    if not events:
        return "No Exit"
    events.sort(key=lambda item: item[1])
    return events[0][0]


def build_time_based_backtest_summary(rows: pd.DataFrame, frequency: str) -> pd.DataFrame:
    """Summarize backtest performance by week or month."""

    if rows.empty:
        return pd.DataFrame()
    summary_rows: list[dict[str, Any]] = []
    working = rows.copy()
    working["next_trading_date"] = pd.to_datetime(working["next_trading_date"], errors="coerce")
    working = working.dropna(subset=["next_trading_date"])
    if working.empty:
        return pd.DataFrame()
    if frequency == "weekly":
        working["period_label"] = working["next_trading_date"].dt.to_period("W-FRI").astype(str)
    else:
        working["period_label"] = working["next_trading_date"].dt.to_period("M").astype(str)
    for period_label, period_rows in working.groupby("period_label"):
        metrics = build_backtest_metrics(period_rows)
        summary_rows.append(
            {
                "period": period_label,
                "setups": int(len(period_rows)),
                "trades": int(metrics["trade_count"]),
                "win_rate": metrics["win_rate"],
                "total_pnl": metrics["total_pnl"],
                "expectancy": metrics["expectancy"],
            }
        )
    return pd.DataFrame(summary_rows)


def build_sitout_effectiveness_summary(rows: pd.DataFrame) -> dict[str, float]:
    """Summarize sit-out behavior within the backtest set."""

    sitout_rows = rows.loc[rows["sit_out"] == "Sit Out"].copy()
    if sitout_rows.empty:
        return {
            "setups": 0,
            "traded": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "protective": 0,
            "costly": 0,
        }
    traded_rows = sitout_rows.loc[sitout_rows["trade_taken"]].copy()
    return {
        "setups": int(len(sitout_rows)),
        "traded": int(len(traded_rows)),
        "win_rate": round_price(traded_rows["estimated_pnl"].gt(0).mean() * 100.0) if not traded_rows.empty else 0.0,
        "total_pnl": round_price(float(traded_rows["estimated_pnl"].sum())) if not traded_rows.empty else 0.0,
        "protective": int((traded_rows["estimated_pnl"] < 0).sum()) if not traded_rows.empty else 0,
        "costly": int((traded_rows["estimated_pnl"] > 0).sum()) if not traded_rows.empty else 0,
    }


def render_review_card(title: str, review: dict[str, Any]) -> None:
    """Render a compact historical review card."""

    with st.container(border=True):
        st.markdown(f"**{title}**")
        st.write(review["summary"])
        if review.get("available"):
            st.write(f"Entry: {format_price(review.get('entry_price'))} SPX")
            st.write(f"Entry trigger: {format_timestamp(review.get('entry_time'))}")
            st.write(f"Stop trigger: {format_timestamp(review.get('stop_time'))}")
            st.write(f"TP1 trigger: {format_timestamp(review.get('tp1_time'))}")
            st.write(f"TP2 trigger: {format_timestamp(review.get('tp2_time'))}")


def render_historical_context_banner(inputs: dict[str, Any], nine_am_target, anchor_bundle: dict[str, Any]) -> None:
    """Render a compact historical context banner."""

    source_mode = "Auto-fetch" if inputs.get("data_mode") == "auto" else "Manual input"
    anchor_source = anchor_bundle.get("source", "Session anchors")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Prior Session", inputs["prior_session_date"].strftime("%Y-%m-%d"))
    col2.metric("Next Trading Day", inputs["next_trading_date"].strftime("%Y-%m-%d"))
    col3.metric("Projection Target", format_timestamp(nine_am_target))
    col4.metric("Anchor Source", f"{anchor_source} | {source_mode}")


def render_live_decision_center(
    signal_package: dict[str, Any] | None,
    current_spx_price: float | None,
    current_es_price: float | None,
    effective_offset: float,
    *,
    intelligence_summary: dict[str, Any] | None = None,
    adaptive_overlay: dict[str, Any] | None = None,
    hero_authority: dict[str, Any] | None = None,
    active_play_label: str = "None",
    live_context: dict[str, Any] | None = None,
) -> None:
    """Render the production-first live decision center using native Streamlit components."""

    authority = hero_authority or {}
    chosen_play = None
    if signal_package is not None:
        scenario_payload = signal_package["scenario"]
        if str(active_play_label).lower() == "alternate":
            chosen_play = scenario_payload.get("alternate_play") or scenario_payload.get("primary_play")
        else:
            chosen_play = scenario_payload.get("primary_play") or scenario_payload.get("alternate_play")
    live_scenario = str((live_context or {}).get("live_scenario") or "Awaiting Valid SPX Input")
    live_structure_state = format_live_state_label((live_context or {}).get("live_structure_state"))
    transition_note = build_scenario_transition_note(live_context)
    current_es_display = format_price(current_es_price) if is_valid_price_input(current_es_price) else "Not entered"
    decision = str(authority.get("decision", "NO TRADE"))
    confidence = int(authority.get("confidence_score", 0) or 0)
    expected_value = authority.get("expected_value")
    risk_class = str(authority.get("risk_class", "HIGH"))
    reason_line = str(authority.get("reason_line", "Waiting for valid live setup."))
    evidence_label = str(authority.get("evidence_level", (adaptive_overlay or {}).get("adaptive_evidence_level", "None")))
    direction_value = chosen_play.get("direction") if isinstance(chosen_play, dict) else ""
    direction_display = resolve_trade_direction_display(direction_value)
    execution_display = resolve_trade_execution_display(direction_value, decision)
    presentation_state = resolve_presentation_state(decision, direction_display["bias"])
    entry_value = intelligence_summary.get("locked_entry_spx") if intelligence_summary else None
    if entry_value is None and signal_package is not None:
        primary_play = signal_package["scenario"].get("primary_play")
        if isinstance(primary_play, dict) and isinstance(primary_play.get("entry"), dict):
            entry_value = primary_play["entry"].get("price")
    strike_value = "-"
    if signal_package is not None:
        primary_play = signal_package["scenario"].get("primary_play")
        if isinstance(primary_play, dict) and primary_play.get("strike") is not None:
            strike_value = str(primary_play["strike"])
    lock_label = "Locked" if intelligence_summary and intelligence_summary.get("session_plan_locked") else "-"

    with st.container(border=True):
        top_left, top_right = st.columns([3, 1.2], gap="large")
        with top_left:
            st.caption("Decision Center")
            st.markdown(f"### {presentation_state['headline']}")
            st.caption(presentation_state["secondary"])
            if str(decision).upper() != "NO TRADE":
                st.caption(execution_display)
            st.markdown(f"`{live_scenario}`  |  `{live_structure_state}`")
            st.write(reason_line)
            if transition_note:
                st.caption(transition_note)
        with top_right:
            st.metric("Current Price (ES)", current_es_display)
            st.caption(f"Active Play: {active_play_label}")

        stat1, stat2, stat3, stat4, stat5, stat6 = st.columns(6)
        stat1.metric("Planned Entry", f"{format_price(entry_value) if entry_value is not None else '-'} SPX")
        stat2.metric("Strike", str(strike_value))
        stat3.metric("Confidence", f"{confidence}%")
        stat4.metric("Risk", risk_class)
        stat5.metric("Expected Value", format_price(expected_value) if expected_value is not None else "-")
        stat6.metric("Evidence", evidence_label if evidence_label else "None")
        if lock_label != "-":
            st.caption(f"Lock Status: {lock_label}")


def render_operator_play_card(
    title: str,
    play_spx: dict[str, Any] | None,
    projected_lines_spx: dict[str, dict[str, Any]],
    projected_lines_es: dict[str, dict[str, Any]],
    lead_option_quote: dict[str, Any] | None = None,
    *,
    compact: bool = False,
    effective_offset: float | None = None,
    offset_diagnostics: dict[str, Any] | None = None,
    developer_mode: bool = False,
    final_status: str | None = None,
    status_breakdown: dict[str, str] | None = None,
    current_spx_price: float | None = None,
    planned_anchor_key: str | None = None,
    session_plan: dict[str, Any] | None = None,
    calibration_preview: dict[str, Any] | None = None,
    adaptive_overlay: dict[str, Any] | None = None,
    authority: dict[str, Any] | None = None,
    live_context: dict[str, Any] | None = None,
) -> None:
    """Render a calmer operator-first play card for live mode."""

    if play_spx is None:
        with st.container(border=True):
            st.markdown(f"**{title}**")
            st.caption("No setup.")
        return

    def _decision_class(value: str) -> str:
        return {"STRONG BUY": "enter", "CONDITIONAL BUY": "caution", "NO TRADE": "skip"}.get(str(value or "").upper(), "wait")

    def _chip_class(value: str, kind: str = "neutral") -> str:
        text = str(value or "").upper()
        if kind == "regime":
            return "blue" if text == "PULLBACK" else "green" if text == "EXPANSION" else "gray"
        if kind == "plan":
            return {"HOLDING": "green", "DRIFTING": "yellow", "BROKEN": "red"}.get(text, "gray")
        if kind == "chase":
            return {"WAIT": "blue", "ENTER NOW": "green", "ENTER WITH CAUTION": "yellow", "CHASE NOT ALLOWED": "red"}.get(text, "gray")
        if kind == "state":
            return {"ACTIVE": "green", "FILTERED": "red", "INVALID": "red"}.get(text, "gray")
        return {"HIGH": "green", "MEDIUM": "yellow", "LOW": "red"}.get(text, "gray")

    play = resolve_play_display_values(play_spx, projected_lines_spx)
    play_es = resolve_play_display_values(play_spx, projected_lines_es)
    if effective_offset is not None:
        play = align_play_conversion_to_effective_offset(play, play_es, effective_offset)
    intelligence = assess_trade_intelligence(
        play,
        lead_option_quote,
        current_spx_price=current_spx_price,
        planned_anchor_key=planned_anchor_key,
        session_plan=session_plan,
    )
    stop_price = _to_float_or_none(play.get("stop", {}).get("price")) if isinstance(play.get("stop"), dict) else None
    entry_price = _to_float_or_none(play.get("entry", {}).get("price")) if isinstance(play.get("entry"), dict) else None
    stop_quality = classify_stop_quality(entry_price, stop_price) if stop_price is not None and not play.get("invalid_stop") else {"label": "Unavailable", "distance": None}
    intelligence["stop_quality"] = stop_quality["label"]

    authority = authority or {}
    decision = str(authority.get("decision", "NO TRADE"))
    confidence = int(authority.get("confidence_score", 0) or 0)
    risk_class = str(authority.get("risk_class", "HIGH"))
    expected_value = authority.get("expected_value")
    reason_line = str(authority.get("reason_line", "No active setup"))
    top_reasons = list(authority.get("top_reasons", []))
    condition_required = str(authority.get("condition_required", ""))
    evidence_level = str(authority.get("evidence_level", "None"))
    calibration_evidence = str(calibration_preview.get("evidence_label", "No Evidence")) if calibration_preview else "No Evidence"
    use_allowed = bool(authority.get("use_allowed", False))
    is_primary = "alternate" not in title.lower()
    trade_state = "FILTERED" if decision == "NO TRADE" else ("INVALID" if play.get("stop_unavailable") else "ACTIVE")
    direction_display = resolve_trade_direction_display(play.get("direction"))
    execution_display = resolve_trade_execution_display(play.get("direction"), decision)
    presentation_state = resolve_presentation_state(decision, direction_display["bias"])
    locked_entry_value = intelligence.get("locked_entry_spx") if intelligence.get("locked_entry_spx") is not None else play["entry"]["price"]
    current_mark = _to_float_or_none(lead_option_quote.get("price")) if lead_option_quote else None
    rr_value = intelligence.get("rr_ratio")
    move_completion = intelligence.get("move_completion_pct")
    live_scenario = str((live_context or {}).get("live_scenario") or st.session_state.get("current_signal_package", {}).get("scenario", {}).get("scenario_name", ""))
    live_structure_state = format_live_state_label((live_context or {}).get("live_structure_state"))
    transition_note = build_scenario_transition_note(live_context)
    decision_sentence = build_live_decision_sentence(authority=authority, intelligence=intelligence, live_context=live_context)
    evidence_note = build_calibration_bias_note(calibration_preview)
    drift_pct_value = float(intelligence.get("entry_drift_pct", 0.0) or 0.0) * 100.0 if intelligence.get("entry_drift_pct") is not None else None
    drift_fill_pct = 0.0 if drift_pct_value is None else max(0.0, min(100.0, (drift_pct_value / 20.0) * 100.0))
    predicted_value = intelligence.get("live_predicted_entry_mark")
    calibrated_value = calibration_preview.get("calibrated_entry_mark") if calibration_preview else None
    expected_fill = calibration_preview.get("expected_fill_mark") if calibration_preview else None
    top_reason_summary = " | ".join(str(reason) for reason in top_reasons[:3] if str(reason).strip())
    best_contract_symbol = str(lead_option_quote.get("contract_symbol", "")) if lead_option_quote else ""

    st.markdown(
        f"""
        <div class="spx-play-shell {'primary' if is_primary else 'alternate'}{' filtered' if decision == 'NO TRADE' else ''}">
            <div class="spx-play-topline">
                <div class="{'spx-play-title' if is_primary else 'spx-play-title alt'}">{escape(title)}</div>
                <div class="spx-play-topline-note">Strike {escape(str(play['strike']))} | <span class="spx-chip {_chip_class(trade_state, 'state')}">{escape(trade_state)}</span></div>
            </div>
            <div class="spx-decision-banner {_decision_class(decision)}">
                <div>
                    <div class="spx-decision-main">{escape(presentation_state['headline'])}</div>
                    <div class="spx-decision-sub">{escape(presentation_state['secondary'] if decision == 'NO TRADE' else execution_display)}</div>
                </div>
                <div class="spx-play-context">
                    <div class="spx-play-context-label">{escape(decision)}</div>
                    <div class="spx-play-context-value">{confidence}%</div>
                </div>
            </div>
            <div class="spx-badge-row">
                <span class="spx-chip scenario-neutral">{escape(live_scenario)}</span>
                <span class="spx-chip scenario-neutral">{escape(live_structure_state)}</span>
                <span class="spx-chip {_chip_class(intelligence.get('plan_status', ''), 'plan')}">{escape(str(intelligence.get('plan_status', '-')))}</span>
                <span class="spx-chip {_chip_class(intelligence.get('regime', ''), 'regime')}">{escape(str(intelligence.get('regime', '-')))}</span>
                <span class="spx-chip {_chip_class(intelligence.get('chase_status', ''), 'chase')}">{escape(str(intelligence.get('chase_status', '-')))}</span>
            </div>
            <div class="spx-entry-grid">
                <div class="spx-entry-card">
                    <div class="spx-entry-card-label">Planned Entry</div>
                    <div class="spx-entry-card-value">{format_price(locked_entry_value)} SPX</div>
                    <div class="spx-entry-card-note">Stop {format_price(stop_price) if stop_price is not None else 'Unavailable'}</div>
                </div>
                <div class="spx-entry-card">
                    <div class="spx-entry-card-label">Current Mark</div>
                    <div class="spx-entry-card-value">{format_price(current_mark) if current_mark is not None else '-'}</div>
                    <div class="spx-entry-card-note">Risk {escape(risk_class)}</div>
                </div>
            </div>
            <div class="spx-metric-grid secondary">
                <div class="spx-metric-block layer2"><div class="spx-metric-label">Predicted</div><div class="spx-metric-value">{format_price(predicted_value) if predicted_value is not None else '-'}</div></div>
                <div class="spx-metric-block layer2"><div class="spx-metric-label">Calibrated</div><div class="spx-metric-value">{format_price(calibrated_value) if calibrated_value is not None else '-'}</div></div>
                <div class="spx-metric-block layer2"><div class="spx-metric-label">Expected Fill</div><div class="spx-metric-value">{format_price(expected_fill) if expected_fill is not None else '-'}</div></div>
                <div class="spx-metric-block layer2"><div class="spx-metric-label">Evidence</div><div class="spx-metric-value">{escape(calibration_evidence if calibration_evidence != 'No Evidence' else evidence_level)}</div></div>
            </div>
            <div class="spx-metric-grid secondary">
                <div class="spx-metric-block layer2"><div class="spx-metric-label">RR</div><div class="spx-metric-value">{rr_value if rr_value is not None else '-'}</div></div>
                <div class="spx-metric-block layer2"><div class="spx-metric-label">Expected Value</div><div class="spx-metric-value">{format_price(expected_value) if expected_value is not None else '-'}</div></div>
                <div class="spx-metric-block layer2"><div class="spx-metric-label">Zone</div><div class="spx-metric-value">{escape(str(intelligence.get('entry_zone_status', '-')))}</div></div>
                <div class="spx-metric-block layer2"><div class="spx-metric-label">Move</div><div class="spx-metric-value">{f"{float(move_completion):.0f}%" if move_completion is not None else '-'}</div></div>
            </div>
            <div class="spx-play-note">{escape(decision_sentence)}</div>
            {f'<div class="spx-play-note" style="margin-top:0.35rem;">{escape(transition_note)}</div>' if transition_note else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )
    if decision == "CONDITIONAL BUY" and condition_required:
        st.caption(condition_required)
    if best_contract_symbol:
        with st.container(border=True):
            st.markdown("**Best Contract**")
            st.markdown(f"`{best_contract_symbol}`")
            st.caption(
                " | ".join(
                    [
                        f"Mark {format_price(current_mark) if current_mark is not None else '-'}",
                        f"Pred {format_price(predicted_value) if predicted_value is not None else '-'}",
                        f"Cal {format_price(calibrated_value) if calibrated_value is not None else '-'}",
                        f"Fill {format_price(expected_fill) if expected_fill is not None else '-'}",
                        f"RR {rr_value if rr_value is not None else '-'}",
                    ]
                )
            )
    if top_reason_summary:
        st.caption(f"Top reasons: {top_reason_summary}")
    if decision == "NO TRADE":
        st.info("Manual override active")
    if lead_option_quote and (lead_option_quote.get("bid") is not None or lead_option_quote.get("ask") is not None):
        st.caption(
            "Bid/Ask "
            f"{format_price(lead_option_quote.get('bid')) if lead_option_quote.get('bid') is not None else '-'} / "
            f"{format_price(lead_option_quote.get('ask')) if lead_option_quote.get('ask') is not None else '-'}"
        )

    button_key = f"use_play_{title.lower().replace(' ', '_')}"
    override_intent_key = f"{button_key}_override_intent"
    override_reason_key = f"{button_key}_override_reason"
    if use_allowed and st.button("Use This Play", key=button_key, use_container_width=True):
        signal_package = st.session_state.get("current_live_signal_package") or st.session_state.get("current_signal_package")
        if signal_package is None:
            st.warning("No live signal snapshot is available for this play yet.")
        else:
            inferred_play_type = "alternate" if "alternate" in title.lower() else "primary"
            set_trade_form_prefill(
                build_live_play_trade_prefill(
                    signal_package=signal_package,
                    play_type=inferred_play_type,
                    play_spx=play,
                    play_es=play_es,
                    lead_option_quote=lead_option_quote,
                    intelligence=intelligence,
                    final_status=final_status or intelligence["status"],
                    final_decision=(status_breakdown or {}).get("final_decision"),
                    authority=authority,
                    live_context=live_context,
                )
            )
            st.success("Trade Log prefilled from this play.")
    elif not use_allowed:
        st.warning("Manual override active")
        if not st.session_state.get(override_intent_key, False):
            if st.button("Override Trade Guard", key=f"{button_key}_override", use_container_width=True):
                st.session_state[override_intent_key] = True
                st.rerun()
        else:
            override_reason_input = st.text_input("Override reason", key=override_reason_key)
            if st.button("Confirm Override And Use This Play", key=f"{button_key}_confirm_override", use_container_width=True, disabled=not override_reason_input.strip()):
                signal_package = st.session_state.get("current_live_signal_package") or st.session_state.get("current_signal_package")
                if signal_package is None:
                    st.warning("No live signal snapshot is available for this play yet.")
                else:
                    inferred_play_type = "alternate" if "alternate" in title.lower() else "primary"
                    set_trade_form_prefill(
                        build_live_play_trade_prefill(
                            signal_package=signal_package,
                            play_type=inferred_play_type,
                            play_spx=play,
                            play_es=play_es,
                            lead_option_quote=lead_option_quote,
                            intelligence=intelligence,
                            final_status=final_status or intelligence["status"],
                            final_decision=(status_breakdown or {}).get("final_decision"),
                            authority=authority,
                            live_context=live_context,
                            override_flag=True,
                            override_reason=override_reason_input.strip(),
                        )
                    )
                    st.session_state[override_intent_key] = False
                    st.success("Trade Log prefilled with override flag.")

    with st.expander("Edge Lab" if developer_mode else "Advanced", expanded=False):
        if drift_pct_value is not None:
            st.caption(f"Plan Integrity {drift_pct_value:.1f}%")
            st.progress(drift_fill_pct / 100.0)
        else:
            st.caption("Plan integrity unavailable.")
        st.caption(
            f"Scenario origin {str((live_context or {}).get('scenario_origin') or '-')}"
            f" | Live {live_scenario or '-'}"
            f" | Structure {live_structure_state or '-'}"
            f" | Zone {intelligence.get('entry_zone_status', '-')}"
            f" | Stop quality {stop_quality['label']}"
        )
        if evidence_note:
            st.caption(evidence_note)
        if developer_mode and effective_offset is not None:
            entry_debug = (play.get('conversion_debug') or {}).get('entry', {})
            if offset_diagnostics is not None:
                st.caption(
                    f"Manual offset {format_price(offset_diagnostics.get('manual_offset')) if offset_diagnostics.get('manual_offset') is not None else 'Unavailable'}"
                    f" | Live inferred {format_price(offset_diagnostics.get('live_inferred_offset')) if offset_diagnostics.get('live_inferred_offset') is not None else 'Unavailable'}"
                    f" | Effective {format_price(offset_diagnostics.get('effective_offset')) if offset_diagnostics.get('effective_offset') is not None else format_price(effective_offset)}"
                )
            st.caption(
                f"Source ES {format_price(entry_debug.get('source_es')) if entry_debug.get('source_es') is not None else 'Unavailable'}"
                f" | Displayed SPX {format_price(entry_debug.get('final_displayed_spx')) if entry_debug.get('final_displayed_spx') is not None else 'Unavailable'}"
                f" | Adjustment {format_price(entry_debug.get('additional_adjustment_applied')) if entry_debug.get('additional_adjustment_applied') is not None else '0.00'}"
            )
            if play.get("conversion_invalid"):
                st.warning("Conversion check failed before alignment.")
            st.caption(
                f"Adaptive {str((adaptive_overlay or {}).get('adaptive_recommendation', 'NO_ADAPTATION'))}"
                f" | Evidence {str((adaptive_overlay or {}).get('adaptive_evidence_level', 'None'))}"
                f" | Effective confidence {str((adaptive_overlay or {}).get('effective_prediction_confidence', intelligence.get('prediction_confidence', '-')))}"
            )


def render_live_mode_shell(
    inputs: dict[str, Any],
    signal_package: dict[str, Any] | None,
    confirmation: dict[str, Any],
    final_projected_lines: dict[str, dict[str, Any]],
    final_projected_lines_es: dict[str, dict[str, Any]],
    projected_es_9: dict[str, dict[str, Any]],
    override_result: dict[str, Any],
    anchor_bundle: dict[str, Any],
    effective_offset: float,
    offset_diagnostics: dict[str, Any],
    checkpoint_views: list[dict[str, Any]],
    persisted_settings: dict[str, Any],
    settings: dict[str, Any],
    options_provider: Any,
    options_provider_status: dict[str, Any],
) -> None:
    """Render the live operator workflow."""

    developer_mode = bool(inputs.get("developer_mode"))
    live_signal_tab, live_asian_tab = st.tabs(["SIGNAL & LEVELS", "ASIAN SESSION"])

    with live_signal_tab:
        if not inputs.get("live_spx_available", True) and not is_valid_price_input(inputs["current_spx_price"]):
            st.warning("Live SPX price is unavailable. Enter the 9:00 AM SPX price manually before using the scenario engine.")
        if not inputs.get("live_es_available", True) and not is_valid_price_input(inputs["current_es_price"]):
            st.warning("Live ES price is unavailable. Enter the current ES price manually before relying on futures-relative displays.")

        live_current_spx = resolve_live_current_spx(inputs.get("current_es_price"), effective_offset, inputs.get("current_spx_price"))
        line_values_spx = {name: float(details["projected_price"]) for name, details in final_projected_lines.items()}
        live_signal_package = None
        if signal_package is not None and live_current_spx is not None:
            try:
                live_signal_package = build_signal_package(
                    current_price=float(live_current_spx),
                    line_values=line_values_spx,
                    confirmation=confirmation,
                    news_day=inputs["news_day"],
                    current_time=resolve_signal_evaluation_time(inputs["next_trading_date"], inputs["historical_mode"]),
                    open_price=inputs["open_reference"],
                )
            except Exception:
                live_signal_package = None
        display_signal_package = live_signal_package or signal_package
        st.session_state["current_live_signal_package"] = display_signal_package
        primary_play_spx_raw = resolve_play_display_values(display_signal_package["scenario"].get("primary_play"), final_projected_lines) if display_signal_package else None
        primary_play_es = resolve_play_display_values(display_signal_package["scenario"].get("primary_play"), final_projected_lines_es) if display_signal_package else None
        alternate_play_spx_raw = resolve_play_display_values(display_signal_package["scenario"].get("alternate_play"), final_projected_lines) if display_signal_package else None
        alternate_play_es = resolve_play_display_values(display_signal_package["scenario"].get("alternate_play"), final_projected_lines_es) if display_signal_package else None
        primary_play_spx = align_play_conversion_to_effective_offset(primary_play_spx_raw, primary_play_es, effective_offset) if primary_play_spx_raw else None
        alternate_play_spx = align_play_conversion_to_effective_offset(alternate_play_spx_raw, alternate_play_es, effective_offset) if alternate_play_spx_raw else None
        live_context = (
            resolve_live_scenario_context(
                current_price=live_current_spx,
                line_values=line_values_spx,
                open_price=inputs["open_reference"],
                scenario_origin=str(signal_package["scenario"].get("scenario_name", "")),
                state_key=f"{inputs['next_trading_date'].isoformat()}|live_state",
                confirmation_confirmed=bool(confirmation.get("confirmed", False)),
            )
            if signal_package is not None
            else None
        )
        primary_planned_anchor_key = build_planned_anchor_key("primary", signal_package, primary_play_spx, inputs.get("next_trading_date"))
        alternate_planned_anchor_key = build_planned_anchor_key("alternate", signal_package, alternate_play_spx, inputs.get("next_trading_date"))
        option_sections: list[dict[str, Any]] = []
        for section_title, play_spx, play_es in [
            ("Primary Contracts", primary_play_spx, primary_play_es),
            ("Alternate Contracts", alternate_play_spx, alternate_play_es),
        ]:
            option_request = None
            chain_snapshot = {"status": "unavailable", "contracts": []}
            if play_spx is not None and play_spx.get("strike"):
                try:
                    option_request = build_option_lookup_request(
                        session="NY Options",
                        direction=str(play_spx.get("direction", "")),
                        strike=int(play_spx.get("strike", 0)),
                        trade_date=inputs["next_trading_date"],
                        scenario_name=str((live_context or {}).get("live_scenario") or (display_signal_package["scenario"].get("scenario_name", "") if display_signal_package else "")),
                    )
                    chain_snapshot = options_provider.get_option_chain_snapshot(option_request) if options_provider is not None else {"status": "unavailable", "contracts": []}
                    chain_snapshot["contracts"] = attach_option_lookup_context(
                        chain_snapshot.get("contracts"),
                        lookup_timestamp=current_central_time(),
                        current_es_price=inputs.get("current_es_price"),
                        current_spx_price=live_current_spx,
                        effective_offset=effective_offset,
                        scenario_name=str((live_context or {}).get("live_scenario") or (display_signal_package["scenario"].get("scenario_name", "") if display_signal_package else "")),
                        direction=str(play_spx.get("direction", "")),
                        source_line_es=float(play_es["entry"]["price"]) if play_es else None,
                        computed_spx_entry=float(play_spx["entry"]["price"]) if play_spx else None,
                    )
                    chain_snapshot["contracts"] = rank_option_candidates(
                        chain_snapshot.get("contracts"),
                        play_spx=play_spx,
                        current_spx_price=live_current_spx,
                    )
                    option_sections.append(
                        {
                            "title": section_title,
                            "request": option_request,
                            "play_spx": play_spx,
                            "play_es": play_es,
                            "chain_snapshot": chain_snapshot,
                        }
                    )
                except (TypeError, ValueError):
                    option_request = None
        lead_option_map = {
            section["title"]: extract_lead_option_quote(section["chain_snapshot"].get("contracts"))
            for section in option_sections
        }
        primary_lead_option = lead_option_map.get("Primary Contracts")
        alternate_lead_option = lead_option_map.get("Alternate Contracts")
        saved_trades, _ = load_trades()
        normalized_calibration_trades = [normalize_trade_record(trade) for trade in saved_trades]
        primary_pre_intelligence = assess_trade_intelligence(
            primary_play_spx,
            primary_lead_option,
            current_spx_price=live_current_spx,
            planned_anchor_key=primary_planned_anchor_key,
        )
        alternate_pre_intelligence = assess_trade_intelligence(
            alternate_play_spx,
            alternate_lead_option,
            current_spx_price=live_current_spx,
            planned_anchor_key=alternate_planned_anchor_key,
        )
        primary_session_plan = resolve_session_plan_state(
            anchor_key=primary_planned_anchor_key,
            play_role="primary",
            signal_package=signal_package,
            play_spx=primary_play_spx,
            play_es=primary_play_es,
            lead_option_quote=primary_lead_option,
            intelligence=primary_pre_intelligence,
            next_trading_date=inputs["next_trading_date"],
            cutoff_label=inputs["session_plan_lock_cutoff"],
        )
        alternate_session_plan = resolve_session_plan_state(
            anchor_key=alternate_planned_anchor_key,
            play_role="alternate",
            signal_package=signal_package,
            play_spx=alternate_play_spx,
            play_es=alternate_play_es,
            lead_option_quote=alternate_lead_option,
            intelligence=alternate_pre_intelligence,
            next_trading_date=inputs["next_trading_date"],
            cutoff_label=inputs["session_plan_lock_cutoff"],
        )
        primary_calibration_preview = (
            resolve_calibration_preview(
                normalized_calibration_trades,
                build_live_play_trade_prefill(
                    signal_package=signal_package,
                    play_type="primary",
                    play_spx=primary_play_spx,
                    play_es=primary_play_es,
                    lead_option_quote=primary_lead_option,
                    intelligence=primary_pre_intelligence,
                    final_status=final_status_to_action("ELIGIBLE", signal_package),
                    final_decision=final_status_to_action("ELIGIBLE", signal_package),
                    live_context=live_context,
                ),
            )
            if signal_package is not None and primary_play_spx is not None
            else None
        )
        alternate_calibration_preview = (
            resolve_calibration_preview(
                normalized_calibration_trades,
                build_live_play_trade_prefill(
                    signal_package=signal_package,
                    play_type="alternate",
                    play_spx=alternate_play_spx,
                    play_es=alternate_play_es,
                    lead_option_quote=alternate_lead_option,
                    intelligence=alternate_pre_intelligence,
                    final_status=final_status_to_action("ELIGIBLE", signal_package),
                    final_decision=final_status_to_action("ELIGIBLE", signal_package),
                    live_context=live_context,
                ),
            )
            if signal_package is not None and alternate_play_spx is not None
            else None
        )
        final_status_breakdown = resolve_final_trade_status(
            display_signal_package,
            primary_play_spx,
            primary_lead_option,
            current_spx_price=live_current_spx,
            planned_anchor_key=primary_planned_anchor_key,
            session_plan=primary_session_plan,
        )
        alternate_status_breakdown = resolve_final_trade_status(
            display_signal_package,
            alternate_play_spx,
            alternate_lead_option,
            current_spx_price=live_current_spx,
            planned_anchor_key=alternate_planned_anchor_key,
            session_plan=alternate_session_plan,
        )
        final_status = final_status_breakdown["final_status"]
        primary_adaptive_overlay = (
            resolve_adaptive_overlay(
                normalized_calibration_trades,
                scenario_name=str(display_signal_package["scenario"].get("scenario_name", "")),
                regime=str(primary_pre_intelligence.get("regime", "")),
                raw_prediction_confidence=str(primary_pre_intelligence.get("prediction_confidence", "")),
                raw_final_decision=str(final_status_breakdown.get("final_decision", "")),
                rr_ratio=_to_float_or_none(primary_lead_option.get("rr_ratio")) if primary_lead_option else None,
                distance_to_entry=_to_float_or_none(primary_pre_intelligence.get("distance_to_entry")),
                stop_valid=bool(primary_play_spx and primary_play_spx.get("stop") and not primary_play_spx.get("invalid_stop") and primary_pre_intelligence.get("rr_ratio") is not None),
            )
            if signal_package is not None and primary_play_spx is not None
            else None
        )
        alternate_adaptive_overlay = (
            resolve_adaptive_overlay(
                normalized_calibration_trades,
                scenario_name=str(display_signal_package["scenario"].get("scenario_name", "")),
                regime=str(alternate_pre_intelligence.get("regime", "")),
                raw_prediction_confidence=str(alternate_pre_intelligence.get("prediction_confidence", "")),
                raw_final_decision=str(final_status_to_action(alternate_pre_intelligence.get("status", "ELIGIBLE"), signal_package)),
                rr_ratio=_to_float_or_none(alternate_lead_option.get("rr_ratio")) if alternate_lead_option else None,
                distance_to_entry=_to_float_or_none(alternate_pre_intelligence.get("distance_to_entry")),
                stop_valid=bool(alternate_play_spx and alternate_play_spx.get("stop") and not alternate_play_spx.get("invalid_stop") and alternate_pre_intelligence.get("rr_ratio") is not None),
            )
            if signal_package is not None and alternate_play_spx is not None
            else None
        )
        primary_authority = build_play_decision_authority(
            signal_package=display_signal_package,
            play=primary_play_spx,
            lead_option_quote=primary_lead_option,
            intelligence=final_status_breakdown.get("intelligence", {}),
            calibration_preview=primary_calibration_preview,
            adaptive_overlay=primary_adaptive_overlay,
            play_role="primary",
            trades=normalized_calibration_trades,
            raw_final_decision=str(final_status_breakdown.get("final_decision", "")),
        )
        alternate_authority = build_play_decision_authority(
            signal_package=display_signal_package,
            play=alternate_play_spx,
            lead_option_quote=alternate_lead_option,
            intelligence=alternate_status_breakdown.get("intelligence", {}),
            calibration_preview=alternate_calibration_preview,
            adaptive_overlay=alternate_adaptive_overlay,
            play_role="alternate",
            trades=normalized_calibration_trades,
            raw_final_decision=str(alternate_status_breakdown.get("final_decision", "")),
        )
        hero_active_play, hero_authority = choose_hero_authority(primary_authority, alternate_authority)
        render_live_decision_center(
            display_signal_package,
            live_current_spx,
            inputs["current_es_price"],
            effective_offset,
            intelligence_summary=final_status_breakdown.get("intelligence"),
            adaptive_overlay=primary_adaptive_overlay,
            hero_authority=hero_authority,
            active_play_label=hero_active_play,
            live_context=live_context,
        )
        if display_signal_package is not None:
            render_trade_decision_summary(
                display_signal_package,
                final_projected_lines,
                final_status=final_status,
                final_decision=final_status_breakdown.get("final_decision"),
                intelligence_summary=final_status_breakdown.get("intelligence"),
                authority=hero_authority,
                active_play_label=hero_active_play,
                live_context=live_context,
            )
        else:
            st.warning("Current SPX price is unavailable or invalid. Enter it manually to enable Tab 1 trade decisions. Projected structure remains available below.")
        action_col1, action_col2 = st.columns(2)
        with action_col1:
            primary_play = display_signal_package["scenario"].get("primary_play") if display_signal_package else None
            if primary_play is None:
                st.warning("No primary play is available to hand off into the Trade Log.")
            elif st.button("Prefill Trade Log from Primary Play", use_container_width=True, key="live_prefill_trade_log", disabled=primary_authority.get("decision") == "NO TRADE"):
                set_trade_form_prefill(
                    build_live_play_trade_prefill(
                        signal_package=display_signal_package,
                        play_type="primary",
                        play_spx=primary_play_spx,
                        play_es=primary_play_es,
                        lead_option_quote=primary_lead_option,
                        intelligence=final_status_breakdown.get("intelligence", {}),
                        final_status=final_status,
                        final_decision=final_status_breakdown.get("final_decision"),
                        authority=primary_authority,
                        live_context=live_context,
                    )
                )
                st.success("Trade Log prefilled from Live Mode.")
            elif primary_authority.get("decision") == "NO TRADE":
                st.caption("Primary play is blocked by the decision authority layer. Override from the card if you still want to journal it.")
        with action_col2:
            if st.button("Save Daily Snapshot", use_container_width=True, disabled=display_signal_package is None, key="live_save_snapshot"):
                snapshot_payload = build_daily_snapshot(
                    next_trading_date=inputs["next_trading_date"],
                    projected_lines=final_projected_lines,
                    scenario=display_signal_package["scenario"],
                    sit_out=display_signal_package["sit_out"],
                    confirmation=confirmation,
                )
                snapshot_saved, snapshot_error = append_snapshot(snapshot_payload)
                if snapshot_saved:
                    st.success("Daily snapshot saved.")
                    if snapshot_error:
                        st.warning(snapshot_error)
                else:
                    st.error(snapshot_error or "Unable to save daily snapshot.")
        primary_contract_candidates = next((section["chain_snapshot"].get("contracts", []) for section in option_sections if section["title"] == "Primary Contracts"), [])
        st.session_state["tab1_primary_selected_contract"] = {
            "contract_symbol": primary_lead_option.get("contract_symbol", "") if primary_lead_option else "",
            "option_mark_at_decision": primary_lead_option.get("price") if primary_lead_option else None,
            "predicted_entry_price": primary_lead_option.get("predicted_entry_price") if primary_lead_option else None,
            "expected_gain": primary_lead_option.get("expected_gain") if primary_lead_option else None,
            "expected_loss": primary_lead_option.get("expected_loss") if primary_lead_option else None,
            "rr_ratio": primary_lead_option.get("rr_ratio") if primary_lead_option else None,
            "contract_score": primary_lead_option.get("contract_score") if primary_lead_option else None,
            "stop_value": float(primary_play_spx["stop"]["price"]) if primary_play_spx and primary_play_spx.get("stop") else None,
            "integrity_flags": list((primary_contract_candidates[0].get("integrity_flags", []) if primary_contract_candidates else [])),
            "final_authority_decision": primary_authority.get("decision"),
            "final_authority_confidence": primary_authority.get("confidence_score"),
            "final_authority_expected_value": primary_authority.get("expected_value"),
            "final_authority_risk_class": primary_authority.get("risk_class"),
            "final_authority_reason": primary_authority.get("reason_line"),
        }

        decision_col1, decision_col2 = st.columns(2, gap="large")
        if display_signal_package is not None:
            with decision_col1:
                render_operator_play_card("Primary Trade", display_signal_package["scenario"]["primary_play"], final_projected_lines, final_projected_lines_es, primary_lead_option, compact=not developer_mode, effective_offset=effective_offset, offset_diagnostics=offset_diagnostics, developer_mode=developer_mode, final_status=final_status, status_breakdown=final_status_breakdown, current_spx_price=live_current_spx, planned_anchor_key=primary_planned_anchor_key, session_plan=primary_session_plan, calibration_preview=primary_calibration_preview, adaptive_overlay=primary_adaptive_overlay, authority=primary_authority, live_context=live_context)
            with decision_col2:
                render_operator_play_card("Alternate Trade", display_signal_package["scenario"]["alternate_play"], final_projected_lines, final_projected_lines_es, alternate_lead_option, compact=not developer_mode, effective_offset=effective_offset, offset_diagnostics=offset_diagnostics, developer_mode=developer_mode, final_status=alternate_status_breakdown["final_status"], status_breakdown=alternate_status_breakdown, current_spx_price=live_current_spx, planned_anchor_key=alternate_planned_anchor_key, session_plan=alternate_session_plan, calibration_preview=alternate_calibration_preview, adaptive_overlay=alternate_adaptive_overlay, authority=alternate_authority, live_context=live_context)

        render_spatial_ladder(final_projected_lines_es, inputs["current_es_price"] if is_valid_price_input(inputs["current_es_price"]) else None, price_space_label="ES")
        render_key_levels_card(final_projected_lines_es, inputs["current_es_price"], effective_offset, compact=not developer_mode)

        if developer_mode:
            with st.expander("Structure Details", expanded=False):
                if display_signal_package is not None:
                    render_scenario_section(display_signal_package["scenario"])
                    render_sit_out_section(display_signal_package["sit_out"])
                render_six_lines_panel(projected_es_9, final_projected_lines_es, override_result["decisions"], "ES")
            with st.expander("Verification", expanded=False):
                render_projection_verification(anchor_bundle, final_projected_lines, final_projected_lines_es, final_projected_lines_es, "ES")
        render_options_provider_preview(
            options_provider,
            options_provider_status,
            option_sections,
            developer_mode=developer_mode,
        )

    with live_asian_tab:
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
                        <div class="spx-status-chip good"><span>◉</span><span>Observation First</span></div>
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
                key="live_checkpoint_selector",
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
                    st.warning("No live reference play is available to hand off into the Trade Log.")
                elif st.button("Prefill Trade Log from Evening Framework", use_container_width=True, key="live_evening_prefill"):
                    set_trade_form_prefill(build_tab2_trade_prefill(selected_checkpoint, inputs["current_es_price"]))
                    st.success("Trade Log prefilled from Live Mode.")
            else:
                st.info("Enter a valid current ES price to enable the evening reference framework and handoff.")
            render_evening_decision_framework()
            render_evening_line_ladder(selected_checkpoint)
            with st.expander("Checkpoint Levels", expanded=False):
                render_checkpoint_views(checkpoint_views)


def render_historical_backtest_tab(inputs: dict[str, Any], effective_offset: float) -> None:
    """Render a practical historical backtest runner."""

    st.markdown("**Backtest**")
    start_default = previous_business_day(inputs["prior_session_date"])
    col1, col2 = st.columns(2)
    with col1:
        backtest_start = st.date_input("Start next trading day", value=start_default, key="historical_backtest_start")
    with col2:
        backtest_end = st.date_input("End next trading day", value=inputs["next_trading_date"], key="historical_backtest_end")
    filter_col1, filter_col2, filter_col3 = st.columns(3)
    with filter_col1:
        scenario_filter = st.text_input("Scenario filter", value="", key="historical_backtest_scenario_filter")
    with filter_col2:
        confirmation_filter = st.selectbox("Confirmation filter", ["All", "Confirmed", "Failed", "Not Recorded"], key="historical_backtest_confirmation_filter")
    with filter_col3:
        sit_out_filter = st.selectbox("Sit-out filter", ["All", "Sit Out", "Trade Eligible"], key="historical_backtest_sitout_filter")

    if not st.button("Run Historical Backtest", use_container_width=True, key="run_historical_backtest"):
        st.info("Choose a next-trading-day range and run the engine over those dates.")
        return
    if backtest_end < backtest_start:
        st.error("Backtest end date must be on or after the start date.")
        return

    rows: list[dict[str, Any]] = []
    cursor = backtest_start
    while cursor <= backtest_end:
        if cursor.weekday() >= 5:
            cursor += timedelta(days=1)
            continue
        prior_session_date = previous_business_day(cursor)
        try:
            es_candles, _ = fetch_es_candles_for_app(prior_session_date, cursor)
            if es_candles is None or es_candles.empty:
                cursor += timedelta(days=1)
                continue
            anchor_bundle = build_six_line_anchors(es_candles, prior_session_date)
            projected_es = project_six_lines(anchor_bundle["anchors"], build_projection_target(cursor))
            projected_spx = convert_projected_lines(projected_es, effective_offset, "spx")
            next_session_spx = build_synthetic_spx_session(get_next_day_session_candles(es_candles, cursor), effective_offset)
            nine_am_bar = next_session_spx.loc[next_session_spx["timestamp"] == at_central(cursor, 9, 0)]
            if nine_am_bar.empty:
                cursor += timedelta(days=1)
                continue
            nine_am_row = nine_am_bar.iloc[0]
            spx_candles = fetch_spx_confirmation_candles(cursor)
            spx_830_candle = extract_spx_830_candle(spx_candles, cursor)
            seed_scenario = evaluate_trading_scenario(
                current_price=float(nine_am_row["close"]),
                line_values={name: details["projected_price"] for name, details in projected_spx.items()},
                open_price=float(nine_am_row["open"]),
                confirmation_confirmed=False,
            )
            primary_seed = seed_scenario.get("primary_play")
            confirmation = evaluate_830_confirmation(
                spx_830_candle,
                primary_seed["entry"]["price"] if primary_seed else float(nine_am_row["close"]),
                primary_seed["direction"] if primary_seed else "CALL",
            )
            signal_package = build_signal_package(
                current_price=float(nine_am_row["close"]),
                line_values={name: details["projected_price"] for name, details in projected_spx.items()},
                confirmation=confirmation,
                news_day=False,
                current_time=build_projection_target(cursor),
                open_price=float(nine_am_row["open"]),
            )
            primary_review = evaluate_play_outcome(signal_package["scenario"].get("primary_play"), projected_spx, next_session_spx)
            alternate_review = evaluate_play_outcome(signal_package["scenario"].get("alternate_play"), projected_spx, next_session_spx)
            trade_taken = bool(primary_review["entry_triggered"] or alternate_review["entry_triggered"])
            chosen_result = primary_review if primary_review["entry_triggered"] else alternate_review
            integrity_flags = sorted(
                set(primary_review.get("integrity_flags", [])) | set(alternate_review.get("integrity_flags", []))
            )
            invalid_stop_row = "invalid_stop" in integrity_flags
            rows.append(
                {
                    "prior_session_date": prior_session_date.isoformat(),
                    "next_trading_date": cursor.isoformat(),
                    "scenario": signal_package["scenario"]["scenario_name"],
                    "confirmation": confirmation_status_label(confirmation),
                    "sit_out": "Sit Out" if signal_package["sit_out"]["sit_out"] else "Trade Eligible",
                    "primary_entry_triggered": bool(primary_review["entry_triggered"]),
                    "alternate_entry_triggered": bool(alternate_review["entry_triggered"]),
                    "primary_stop_hit": bool(primary_review["stop_hit"]),
                    "primary_tp1_hit": bool(primary_review["tp1_hit"]),
                    "primary_tp2_hit": bool(primary_review["tp2_hit"]),
                    "primary_result_classification": primary_review["result_classification"],
                    "primary_estimated_pnl": float(primary_review["estimated_pnl"]),
                    "primary_event_order": primary_review["event_order"],
                    "primary_integrity_flags": ", ".join(primary_review.get("integrity_flags", [])),
                    "alternate_stop_hit": bool(alternate_review["stop_hit"]),
                    "alternate_tp1_hit": bool(alternate_review["tp1_hit"]),
                    "alternate_tp2_hit": bool(alternate_review["tp2_hit"]),
                    "alternate_result_classification": alternate_review["result_classification"],
                    "alternate_estimated_pnl": float(alternate_review["estimated_pnl"]),
                    "alternate_event_order": alternate_review["event_order"],
                    "alternate_integrity_flags": ", ".join(alternate_review.get("integrity_flags", [])),
                    "stop_hit": bool(chosen_result["stop_hit"]) if trade_taken else False,
                    "tp1_hit": bool(chosen_result["tp1_hit"]) if trade_taken else False,
                    "tp2_hit": bool(chosen_result["tp2_hit"]) if trade_taken else False,
                    "result_classification": chosen_result["result_classification"] if (trade_taken or invalid_stop_row) else "No Trade",
                    "estimated_pnl": float(chosen_result["estimated_pnl"]) if trade_taken else 0.0,
                    "trade_taken": trade_taken,
                    "chosen_path": "Primary" if primary_review["entry_triggered"] else ("Alternate" if alternate_review["entry_triggered"] else "None"),
                    "first_outcome": classify_first_outcome(chosen_result) if trade_taken else ("Invalid Stop" if invalid_stop_row else "No Trade"),
                    "event_order": chosen_result["event_order"] if (trade_taken or invalid_stop_row) else "No trade",
                    "integrity_flags": ", ".join(integrity_flags),
                }
            )
        except Exception:
            pass
        cursor += timedelta(days=1)

    if not rows:
        st.warning("No historical backtest rows could be built for the selected range.")
        return

    backtest_df = pd.DataFrame(rows)
    filtered_df = backtest_df.copy()
    if scenario_filter.strip():
        filtered_df = filtered_df.loc[filtered_df["scenario"].str.contains(scenario_filter.strip(), case=False, na=False)]
    if confirmation_filter != "All":
        filtered_df = filtered_df.loc[filtered_df["confirmation"] == confirmation_filter]
    if sit_out_filter != "All":
        filtered_df = filtered_df.loc[filtered_df["sit_out"] == sit_out_filter]

    scenario_summary = build_group_backtest_summary(filtered_df, "scenario")
    confirmation_summary = build_group_backtest_summary(filtered_df, "confirmation")
    sitout_summary = build_group_backtest_summary(filtered_df, "sit_out")
    primary_summary = build_play_path_summary(filtered_df, "primary")
    alternate_summary = build_play_path_summary(filtered_df, "alternate")
    outcome_counts = filtered_df["first_outcome"].value_counts()
    weekly_summary = build_time_based_backtest_summary(filtered_df, "weekly")
    monthly_summary = build_time_based_backtest_summary(filtered_df, "monthly")
    sitout_effectiveness = build_sitout_effectiveness_summary(filtered_df)
    metrics = build_backtest_metrics(filtered_df)
    trade_rows = filtered_df.loc[filtered_df["trade_taken"]].copy()

    st.markdown("**Backtest Intelligence**")
    intel1, intel2, intel3 = st.columns(3)
    intel4, intel5, intel6 = st.columns(3)
    with intel1:
        st.metric("Best Scenario Win Rate", select_card_winner(scenario_summary, "scenario", "win_rate", highest=True))
    with intel2:
        st.metric("Best Scenario Expectancy", select_card_winner(scenario_summary, "scenario", "expectancy", highest=True))
    with intel3:
        st.metric("Worst Scenario Expectancy", select_card_winner(scenario_summary, "scenario", "expectancy", highest=False))
    with intel4:
        st.metric("Best Confirmation", select_card_winner(confirmation_summary, "confirmation", "expectancy", highest=True))
    with intel5:
        st.metric("Best Sit-Out Outcome", select_card_winner(sitout_summary, "sit_out", "expectancy", highest=True))
    with intel6:
        st.metric("Ambiguous Outcomes", int((filtered_df["result_classification"] == "Ambiguous Same-Bar Outcome").sum()))

    st.markdown("**Primary vs Alternate**")
    play_col1, play_col2, play_col3 = st.columns(3)
    play_col4, play_col5, play_col6 = st.columns(3)
    play_col1.metric("Primary Triggered", primary_summary["triggered"])
    play_col2.metric("Primary Win Rate", f"{primary_summary['win_rate']:.1f}%")
    play_col3.metric("Primary Total P&L", format_price(primary_summary["total_pnl"]))
    play_col4.metric("Alternate Triggered", alternate_summary["triggered"])
    play_col5.metric("Alternate Win Rate", f"{alternate_summary['win_rate']:.1f}%")
    play_col6.metric("Alternate Total P&L", format_price(alternate_summary["total_pnl"]))

    st.markdown("**Outcome Order**")
    order_col1, order_col2, order_col3, order_col4 = st.columns(4)
    order_col1.metric("Stop Hit First", int(outcome_counts.get("Stop Hit First", 0)))
    order_col2.metric("TP1 Hit First", int(outcome_counts.get("TP1 Hit First", 0)))
    order_col3.metric("TP2 Hit First", int(outcome_counts.get("TP2 Hit First", 0)))
    order_col4.metric("Ambiguous Same-Bar", int(outcome_counts.get("Ambiguous Same-Bar", 0)))

    st.markdown("**Sit-Out Effectiveness**")
    sit1, sit2, sit3, sit4, sit5 = st.columns(5)
    sit1.metric("Sit-Out Setups", sitout_effectiveness["setups"])
    sit2.metric("Sit-Out Traded", sitout_effectiveness["traded"])
    sit3.metric("Sit-Out Win Rate", f"{sitout_effectiveness['win_rate']:.1f}%")
    sit4.metric("Protective", sitout_effectiveness["protective"])
    sit5.metric("Costly", sitout_effectiveness["costly"])
    st.caption(f"Performance if traded: {format_price(sitout_effectiveness['total_pnl'])}")

    st.markdown("**Backtest Snapshot**")
    stats1, stats2, stats3, stats4, stats5, stats6 = st.columns(6)
    stats1.metric("Total Setups", metrics["setups_tested"])
    stats2.metric("Trades", metrics["trade_count"])
    stats3.metric("Win Rate", f"{metrics['win_rate']:.1f}%")
    stats4.metric("Loss Rate", f"{metrics['loss_rate']:.1f}%")
    stats5.metric("Average P&L", format_price(metrics["average_pnl"]))
    stats6.metric("Total P&L", format_price(metrics["total_pnl"]))
    st.metric("Expectancy", format_price(metrics["expectancy"]))

    summary_left, summary_right = st.columns(2, gap="large")
    with summary_left:
        st.markdown("**Performance by Scenario**")
        if trade_rows.empty:
            st.info("No completed trades in the filtered set.")
        else:
            st.dataframe(scenario_summary, use_container_width=True, hide_index=True)
        st.markdown("**Performance by Confirmation**")
        if trade_rows.empty:
            st.info("No completed trades in the filtered set.")
        else:
            st.dataframe(confirmation_summary, use_container_width=True, hide_index=True)
    with summary_right:
        st.markdown("**Performance by Sit-Out**")
        if trade_rows.empty:
            st.info("No completed trades in the filtered set.")
        else:
            st.dataframe(sitout_summary, use_container_width=True, hide_index=True)
        st.markdown("**Weekly Summary**")
        if weekly_summary.empty:
            st.info("No weekly rows are available for the selected set.")
        else:
            st.dataframe(weekly_summary, use_container_width=True, hide_index=True)

    st.markdown("**Monthly Summary**")
    if monthly_summary.empty:
        st.info("No monthly rows are available for the selected set.")
    else:
        st.dataframe(monthly_summary, use_container_width=True, hide_index=True)

    st.markdown("**Backtest Table**")
    if filtered_df.empty:
        st.info("No sessions matched the selected filters.")
    else:
        display_df = filtered_df[
            [
                "prior_session_date",
                "next_trading_date",
                "scenario",
                "confirmation",
                "sit_out",
                "primary_entry_triggered",
                "alternate_entry_triggered",
                "stop_hit",
                "tp1_hit",
                "tp2_hit",
                "first_outcome",
                "result_classification",
                "estimated_pnl",
                "event_order",
            ]
        ].copy()
        st.dataframe(display_df, use_container_width=True, hide_index=True)


def render_historical_projection_mode(
    inputs: dict[str, Any],
    signal_package: dict[str, Any] | None,
    confirmation: dict[str, Any],
    final_projected_lines: dict[str, dict[str, Any]],
    final_projected_lines_es: dict[str, dict[str, Any]],
    projected_es_9: dict[str, dict[str, Any]],
    override_result: dict[str, Any],
    anchor_bundle: dict[str, Any],
    nine_am_target,
    effective_offset: float,
    es_candles: pd.DataFrame | None,
) -> None:
    """Render the historical analysis workflow."""

    developer_mode = bool(inputs.get("developer_mode"))
    projection_tab, review_tab, backtest_tab = st.tabs(["Historical Projection", "Historical Review", "Backtest"])
    synthetic_spx_session = build_synthetic_spx_session(get_next_day_session_candles(es_candles, inputs["next_trading_date"]), effective_offset)

    with projection_tab:
        historical_authority = None
        if signal_package is not None:
            historical_authority = {
                "decision": "NO TRADE" if signal_package["sit_out"]["sit_out"] else "CONDITIONAL BUY",
                "confidence_score": {"High": 78, "Medium": 62, "Low": 44}.get(str(signal_package["scenario"].get("confidence_level", "Medium")), 62),
                "expected_value": None,
                "risk_class": "MEDIUM",
                "reason_line": str(signal_package["scenario"].get("description", "Historical review context")),
                "evidence_level": "Historical",
            }
        render_live_decision_center(
            signal_package,
            inputs["current_spx_price"],
            inputs["current_es_price"],
            effective_offset,
            hero_authority=historical_authority,
            active_play_label="Historical",
        )
        render_historical_context_banner(inputs, nine_am_target, anchor_bundle)
        if signal_package is not None:
            historical_final_status = "NOT ELIGIBLE" if signal_package["sit_out"]["sit_out"] else "ELIGIBLE"
            render_trade_decision_summary(signal_package, final_projected_lines, final_status=historical_final_status)
            decision_col1, decision_col2 = st.columns(2, gap="large")
            with decision_col1:
                render_play_card("Primary Trade", signal_package["scenario"]["primary_play"], final_projected_lines, final_projected_lines_es, compact=not developer_mode, effective_offset=effective_offset, developer_mode=developer_mode)
            with decision_col2:
                render_play_card("Alternate Trade", signal_package["scenario"]["alternate_play"], final_projected_lines, final_projected_lines_es, compact=not developer_mode, effective_offset=effective_offset, developer_mode=developer_mode)
        else:
            st.info("Enter historical SPX and ES prices to generate scenario and trade cards.")

        render_spatial_ladder(final_projected_lines_es, inputs["current_es_price"] if is_valid_price_input(inputs["current_es_price"]) else None, price_space_label="ES")
        render_six_lines_panel(projected_es_9, final_projected_lines_es, override_result["decisions"], "ES")
        if developer_mode:
            with st.expander("Historical Structure Details", expanded=False):
                if signal_package is not None:
                    render_scenario_section(signal_package["scenario"])
                    render_sit_out_section(signal_package["sit_out"])
                render_historical_projection_panel(inputs, nine_am_target, anchor_bundle, final_projected_lines_es)
            with st.expander("Verification", expanded=False):
                render_projection_verification(anchor_bundle, final_projected_lines, final_projected_lines_es, final_projected_lines_es, "ES")

    with review_tab:
        st.markdown("**Historical Review**")
        if signal_package is None:
            st.info("Enter historical SPX and ES prices to review what would have happened after 9:00 AM CT.")
        else:
            left, right = st.columns(2)
            with left:
                render_review_card(
                    "Primary Entry Review",
                    review_play_against_session(signal_package["scenario"]["primary_play"], final_projected_lines, synthetic_spx_session),
                )
            with right:
                render_review_card(
                    "Alternate Entry Review",
                    review_play_against_session(signal_package["scenario"]["alternate_play"], final_projected_lines, synthetic_spx_session),
                )
            with st.expander("Next-Day Session Candles", expanded=False):
                if synthetic_spx_session.empty:
                    st.info("No next-day session candles were available for review.")
                else:
                    st.dataframe(synthetic_spx_session, use_container_width=True, hide_index=True)

    with backtest_tab:
        render_historical_backtest_tab(inputs, effective_offset)


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

    effective_offset, effective_offset_source, offset_diagnostics = resolve_effective_offset(inputs)

    persisted_settings = {
        "es_spx_offset": inputs["es_spx_offset"],
        "news_day": inputs["news_day"],
        "preferred_checkpoint": settings.get("preferred_checkpoint", DEFAULT_SETTINGS["preferred_checkpoint"]),
        "data_mode": inputs["data_mode"],
        "visibility_mode": inputs["visibility_mode"],
        "manual_price_space": inputs["manual_price_space"],
        "session_plan_lock_cutoff": inputs["session_plan_lock_cutoff"],
        "options_provider": inputs["options_provider"],
        "options_mode_enabled": inputs["options_mode_enabled"],
    }
    settings_saved, settings_save_error = save_settings(persisted_settings)
    if not settings_saved and settings_save_error:
        st.warning(settings_save_error)
    if inputs.get("developer_mode"):
        with st.sidebar.expander("Offset Diagnostics", expanded=False):
            st.caption(f"Current ES: {format_price(offset_diagnostics.get('current_es')) if offset_diagnostics.get('current_es') is not None else 'Unavailable'}")
            st.caption(f"Current SPX: {format_price(offset_diagnostics.get('current_spx')) if offset_diagnostics.get('current_spx') is not None else 'Unavailable'}")
            st.caption(f"Live inferred offset: {format_price(offset_diagnostics.get('live_inferred_offset')) if offset_diagnostics.get('live_inferred_offset') is not None else 'Unavailable'}")
            st.caption(f"Manual offset: {format_price(offset_diagnostics.get('manual_offset'))}")
            st.caption(f"Effective offset: {format_price(offset_diagnostics.get('effective_offset'))} ({offset_diagnostics.get('effective_offset_source')})")

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
            st.warning("Auto-fetch returned ES candles, but the app could not build anchors for the selected session. No projected structure is being shown.")
        else:
            st.warning(
                "Auto-fetch failed because Yahoo returned no usable intraday ES=F data for the selected session. No projected structure is being shown."
            )
        if inputs["data_mode"] == "Auto-fetch" and anchor_bundle is None:
            st.stop()

    nine_am_target = build_projection_target(inputs["next_trading_date"])
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
                current_time=resolve_signal_evaluation_time(inputs["next_trading_date"], inputs["historical_mode"]),
                open_price=inputs["open_reference"],
            )
        except Exception as exc:
            st.warning(f"Tab 1 scenario logic could not be built from the current inputs: {exc}")
            confirmation = build_unavailable_confirmation("Scenario unavailable because the current SPX setup could not be evaluated.")
    else:
        confirmation = build_unavailable_confirmation("Scenario unavailable because current SPX price is missing or invalid.")
    st.session_state["current_signal_package"] = signal_package

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

    top_live_tab, top_historical_tab, top_trade_log_tab = st.tabs(["LIVE MODE", "HISTORICAL MODE", "TRADE LOG"])

    with top_live_tab:
        if inputs["operating_mode"] == "Live Mode":
            render_live_mode_shell(
                inputs=inputs,
                signal_package=signal_package,
                confirmation=confirmation,
                final_projected_lines=final_projected_lines,
                final_projected_lines_es=final_projected_lines_es,
                projected_es_9=projected_es_9,
                override_result=override_result,
                anchor_bundle=anchor_bundle,
                effective_offset=effective_offset,
                offset_diagnostics=offset_diagnostics,
                checkpoint_views=checkpoint_views,
                persisted_settings=persisted_settings,
                settings=settings,
                options_provider=options_provider,
                options_provider_status=options_provider_status,
            )
        else:
            st.info("Historical Mode is active in the sidebar. Switch back to Live Mode to use the current-session operator workflow.")

    with top_historical_tab:
        if inputs["operating_mode"] == "Historical Mode":
            render_historical_projection_mode(
                inputs=inputs,
                signal_package=signal_package,
                confirmation=confirmation,
                final_projected_lines=final_projected_lines,
                final_projected_lines_es=final_projected_lines_es,
                projected_es_9=projected_es_9,
                override_result=override_result,
                anchor_bundle=anchor_bundle,
                nine_am_target=nine_am_target,
                effective_offset=effective_offset,
                es_candles=es_candles,
            )
        else:
            st.info("Live Mode is active in the sidebar. Switch to Historical Mode to inspect prior sessions, review historical outcomes, and run backtests.")

    with top_trade_log_tab:
        render_trade_log_tab(signal_package, persisted_settings, settings_message=settings_message)

if __name__ == "__main__":
    main()
