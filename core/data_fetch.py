"""Market data fetching utilities for ES and SPX."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Final

from core.time_utils import at_central, market_time_to_central, to_central_time

ES_FUTURES_SYMBOL: Final[str] = "ES=F"
SPX_SYMBOL: Final[str] = "^GSPC"


def _normalize_price_frame(frame):
    """Normalize a yfinance frame into the SPX Prophet candle schema."""

    import pandas as pd

    if frame.empty:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])

    normalized = frame.copy()

    if isinstance(normalized.columns, pd.MultiIndex):
        flattened_columns = []
        seen: dict[str, int] = {}
        for column in normalized.columns.to_flat_index():
            base_name = str(column[0])
            count = seen.get(base_name, 0)
            flattened_columns.append(base_name if count == 0 else f"{base_name}_{count}")
            seen[base_name] = count + 1
        normalized.columns = flattened_columns

    normalized = normalized.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Open_1": "open_alt",
            "High_1": "high_alt",
            "Low_1": "low_alt",
            "Close_1": "close_alt",
        }
    )
    for canonical, alternate in [
        ("open", "open_alt"),
        ("high", "high_alt"),
        ("low", "low_alt"),
        ("close", "close_alt"),
    ]:
        if canonical not in normalized.columns and alternate in normalized.columns:
            normalized[canonical] = normalized[alternate]
    normalized["timestamp"] = pd.to_datetime(normalized.index).map(market_time_to_central)
    normalized = normalized.loc[:, ["timestamp", "open", "high", "low", "close"]]
    normalized = normalized.dropna().reset_index(drop=True)
    return normalized


def _serialize_download_kwargs(download_kwargs: dict[str, Any]) -> dict[str, Any]:
    """Convert yfinance download kwargs into a JSON-friendly structure."""

    serialized: dict[str, Any] = {}
    for key, value in download_kwargs.items():
        if hasattr(value, "isoformat"):
            serialized[key] = value.isoformat()
        else:
            serialized[key] = value
    return serialized


def _to_yfinance_history_kwargs(request_kwargs: dict[str, Any]) -> dict[str, Any]:
    """Convert request kwargs into a Ticker.history-friendly payload."""

    history_kwargs: dict[str, Any] = {
        "interval": request_kwargs["interval"],
        "prepost": request_kwargs.get("prepost", True),
    }
    if "period" in request_kwargs:
        history_kwargs["period"] = request_kwargs["period"]
    if "start" in request_kwargs:
        history_kwargs["start"] = request_kwargs["start"]
    if "end" in request_kwargs:
        history_kwargs["end"] = request_kwargs["end"]
    return history_kwargs


def _naive_market_datetime(value):
    """Return a timezone-naive datetime for yfinance history requests."""

    return to_central_time(value).replace(tzinfo=None)


def _history_request(symbol: str, request_kwargs: dict[str, Any]):
    """Fetch a yfinance history frame with cleaner single-ticker semantics."""

    import yfinance as yf

    ticker = yf.Ticker(symbol)
    return ticker.history(**_to_yfinance_history_kwargs(request_kwargs))


def _fetch_es_candles_simple(interval: str = "60m", period: str = "7d"):
    """Reliable ES candle fetch that avoids yf.download MultiIndex issues."""

    import pandas as pd

    raw = _history_request(
        ES_FUTURES_SYMBOL,
        {
            "ticker": ES_FUTURES_SYMBOL,
            "interval": interval,
            "period": period,
            "prepost": True,
        },
    )

    if raw.empty:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])

    return _normalize_price_frame(raw)


def _build_es_intraday_attempts(prior_session_date: date, next_trading_date: date) -> list[dict[str, Any]]:
    """Build a conservative ES intraday fetch sequence for Yahoo."""

    minimal_start = _naive_market_datetime(at_central(prior_session_date, 7, 0))
    minimal_end = _naive_market_datetime(at_central(next_trading_date, 10, 0))

    return [
        {
            "name": "preferred_period_7d_60m",
            "description": "Simple Ticker.history period request",
            "request_kwargs": {
                "ticker": ES_FUTURES_SYMBOL,
                "interval": "60m",
                "period": "7d",
                "prepost": True,
            },
            "method": "simple_period",
        },
        {
            "name": "fallback_period_5d_60m",
            "description": "Simple shorter period fallback",
            "request_kwargs": {
                "ticker": ES_FUTURES_SYMBOL,
                "interval": "60m",
                "period": "5d",
                "prepost": True,
            },
            "method": "simple_period",
        },
        {
            "name": "fallback_period_1mo_60m",
            "description": "Simple longer period fallback",
            "request_kwargs": {
                "ticker": ES_FUTURES_SYMBOL,
                "interval": "60m",
                "period": "1mo",
                "prepost": True,
            },
            "method": "simple_period",
        },
        {
            "name": "alternate_minimal_range_60m",
            "description": "Alternate minimal range history request",
            "request_kwargs": {
                "ticker": ES_FUTURES_SYMBOL,
                "interval": "60m",
                "start": minimal_start,
                "end": minimal_end,
                "prepost": True,
            },
            "method": "range_history",
        },
    ]


def fetch_es_hourly_candles_with_diagnostics(prior_session_date: date, next_trading_date: date):
    """Fetch ES futures hourly candles with multi-step Yahoo diagnostics."""

    import pandas as pd
    attempts = _build_es_intraday_attempts(prior_session_date, next_trading_date)
    diagnostics: dict[str, Any] = {
        "raw_ticker_used": ES_FUTURES_SYMBOL,
        "fetch_attempts": [],
        "successful_fetch_attempt": None,
        "final_fetch_method_chosen": None,
        "all_attempts_returned_empty_data": False,
        "explicit_error_message_if_dataframe_is_empty": None,
        "fetch_error": None,
        "raw_yfinance_request_parameters": None,
        "row_count_returned_before_any_filtering": 0,
        "first_timestamp_returned": None,
        "last_timestamp_returned": None,
        "timezone_info_before_conversion": None,
        "row_count_after_timezone_conversion": 0,
    }

    chosen_frame = None
    chosen_attempt_record: dict[str, Any] | None = None

    for attempt in attempts:
        request_kwargs = attempt["request_kwargs"]
        attempt_record: dict[str, Any] = {
            "name": attempt["name"],
            "description": attempt["description"],
            "request_parameters": _serialize_download_kwargs(request_kwargs),
            "rows_returned": False,
            "raw_row_count": 0,
            "normalized_row_count": 0,
            "status": "pending",
            "error": None,
            "method": attempt.get("method", "Ticker.history"),
        }
        try:
            if attempt_record["method"] == "simple_period":
                normalized = _fetch_es_candles_simple(
                    interval=str(request_kwargs["interval"]),
                    period=str(request_kwargs["period"]),
                )
                attempt_record["raw_row_count"] = int(len(normalized))
                attempt_record["rows_returned"] = bool(len(normalized) > 0)
                attempt_record["first_timestamp_returned"] = (
                    str(normalized.iloc[0]["timestamp"]) if len(normalized) > 0 else None
                )
                attempt_record["last_timestamp_returned"] = (
                    str(normalized.iloc[-1]["timestamp"]) if len(normalized) > 0 else None
                )
                attempt_record["timezone_info_before_conversion"] = "normalized_to_central_via_simple_fetch"
            else:
                raw_frame = _history_request(ES_FUTURES_SYMBOL, request_kwargs)
                attempt_record["raw_row_count"] = int(len(raw_frame))
                attempt_record["rows_returned"] = bool(len(raw_frame) > 0)
                if hasattr(raw_frame, "index") and len(raw_frame.index) > 0:
                    attempt_record["first_timestamp_returned"] = str(raw_frame.index[0])
                    attempt_record["last_timestamp_returned"] = str(raw_frame.index[-1])
                    timezone = getattr(raw_frame.index, "tz", None)
                    attempt_record["timezone_info_before_conversion"] = str(timezone) if timezone is not None else "naive"
                else:
                    attempt_record["first_timestamp_returned"] = None
                    attempt_record["last_timestamp_returned"] = None
                    attempt_record["timezone_info_before_conversion"] = "unavailable"
                normalized = _normalize_price_frame(raw_frame)
            attempt_record["normalized_row_count"] = int(len(normalized))

            if normalized.empty:
                attempt_record["status"] = "empty"
            else:
                attempt_record["status"] = "usable"
                if chosen_frame is None:
                    chosen_frame = normalized
                    chosen_attempt_record = attempt_record
        except Exception as exc:
            attempt_record["status"] = "error"
            attempt_record["error"] = str(exc)

        diagnostics["fetch_attempts"].append(attempt_record)

    if chosen_frame is None:
        diagnostics["all_attempts_returned_empty_data"] = True
        diagnostics["fetch_error"] = "Yahoo returned no usable intraday ES=F data across all fetch attempts."
        diagnostics["explicit_error_message_if_dataframe_is_empty"] = (
            "Yahoo returned no usable intraday ES=F data across all fetch attempts."
        )
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"]), diagnostics

    diagnostics["successful_fetch_attempt"] = chosen_attempt_record["name"]
    diagnostics["final_fetch_method_chosen"] = chosen_attempt_record["description"]
    diagnostics["raw_yfinance_request_parameters"] = chosen_attempt_record["request_parameters"]
    diagnostics["row_count_returned_before_any_filtering"] = chosen_attempt_record["raw_row_count"]
    diagnostics["first_timestamp_returned"] = chosen_attempt_record["first_timestamp_returned"]
    diagnostics["last_timestamp_returned"] = chosen_attempt_record["last_timestamp_returned"]
    diagnostics["timezone_info_before_conversion"] = chosen_attempt_record["timezone_info_before_conversion"]
    diagnostics["row_count_after_timezone_conversion"] = chosen_attempt_record["normalized_row_count"]
    return chosen_frame, diagnostics


def fetch_market_candles(
    symbol: str,
    *,
    interval: str,
    start=None,
    end=None,
    period: str | None = None,
):
    """Fetch candles from yfinance and return the normalized dataframe."""

    request_kwargs = {
        "ticker": symbol,
        "interval": interval,
        "prepost": True,
    }
    if start is not None:
        request_kwargs["start"] = _naive_market_datetime(start)
    if end is not None:
        request_kwargs["end"] = _naive_market_datetime(end)
    if period is not None:
        request_kwargs["period"] = period

    raw = _history_request(symbol, request_kwargs)
    return _normalize_price_frame(raw)


def fetch_es_hourly_candles(prior_session_date=None, next_trading_date=None, period: str = "10d"):
    """Fetch ES futures hourly candles in Central Time."""

    if prior_session_date is None or next_trading_date is None:
        return fetch_market_candles(ES_FUTURES_SYMBOL, interval="60m", period=period)

    normalized, diagnostics = fetch_es_hourly_candles_with_diagnostics(prior_session_date, next_trading_date)
    if normalized.empty:
        raise ValueError(
            diagnostics.get("explicit_error_message_if_dataframe_is_empty")
            or "Yahoo returned no usable intraday ES=F data."
        )
    return normalized


def fetch_spx_confirmation_candles(next_trading_date):
    """Fetch 30-minute SPX candles for the 8:30 confirmation workflow."""

    start = at_central(next_trading_date, 7, 0) - timedelta(days=3)
    end = at_central(next_trading_date, 10, 0) + timedelta(hours=1)
    return fetch_market_candles(SPX_SYMBOL, interval="30m", start=start, end=end)


def extract_spx_830_candle(spx_candles, next_trading_date):
    """Extract the 8:30 AM CT SPX candle for the target session."""

    target_start = at_central(next_trading_date, 8, 30)
    target_end = at_central(next_trading_date, 8, 59)
    matches = spx_candles.loc[
        spx_candles["timestamp"].map(lambda value: target_start <= to_central_time(value) <= target_end)
    ]
    if matches.empty:
        return None

    row = matches.iloc[-1]
    return {
        "timestamp": market_time_to_central(row["timestamp"]),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
    }
