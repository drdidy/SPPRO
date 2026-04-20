"""Market data fetching utilities for ES and SPX."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

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
        normalized.columns = normalized.columns.get_level_values(0)

    normalized = normalized.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
        }
    )
    normalized["timestamp"] = pd.to_datetime(normalized.index).map(market_time_to_central)
    normalized = normalized.loc[:, ["timestamp", "open", "high", "low", "close"]]
    normalized = normalized.dropna().reset_index(drop=True)
    return normalized


def fetch_market_candles(
    symbol: str,
    *,
    interval: str,
    start=None,
    end=None,
    period: str | None = None,
):
    """Fetch candles from yfinance and return the normalized dataframe."""

    import yfinance as yf

    download_kwargs = {
        "tickers": symbol,
        "interval": interval,
        "progress": False,
        "auto_adjust": False,
        "prepost": True,
    }
    if start is not None:
        download_kwargs["start"] = to_central_time(start)
    if end is not None:
        download_kwargs["end"] = to_central_time(end)
    if period is not None:
        download_kwargs["period"] = period

    raw = yf.download(**download_kwargs)
    return _normalize_price_frame(raw)


def fetch_es_hourly_candles(prior_session_date=None, next_trading_date=None, period: str = "10d"):
    """Fetch ES futures hourly candles in Central Time."""

    if prior_session_date is None or next_trading_date is None:
        return fetch_market_candles(ES_FUTURES_SYMBOL, interval="60m", period=period)

    start = at_central(prior_session_date, 8, 30) - timedelta(days=2)
    end = at_central(next_trading_date, 19, 0) + timedelta(hours=1)
    return fetch_market_candles(ES_FUTURES_SYMBOL, interval="60m", start=start, end=end)


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
