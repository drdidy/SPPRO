"""VWAP utilities for ES 5-minute session context.

This module computes a rolling VWAP and a simple slope proxy that can be used
for confluence scoring.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from core.projections import round_price
from core.time_utils import to_central_time


def compute_vwap_5m(candles: pd.DataFrame) -> pd.DataFrame:
    """Compute 5-minute VWAP from an OHLC dataframe with timestamp column.

    Expected columns: timestamp, open, high, low, close
    """

    if candles is None or candles.empty:
        return pd.DataFrame(columns=["timestamp", "vwap"])

    df = candles.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"]).map(to_central_time)

    typical_price = (df["high"].astype(float) + df["low"].astype(float) + df["close"].astype(float)) / 3.0
    volume_proxy = 1.0

    cumulative_tp_vol = (typical_price * volume_proxy).cumsum()
    cumulative_vol = pd.Series([volume_proxy] * len(df)).cumsum()

    df["vwap"] = cumulative_tp_vol / cumulative_vol
    return df.loc[:, ["timestamp", "vwap"]]


def extract_latest_vwap_context(vwap_frame: pd.DataFrame) -> dict[str, Any] | None:
    """Return the latest VWAP value and a simple slope estimate."""

    if vwap_frame is None or vwap_frame.empty:
        return None

    latest = vwap_frame.iloc[-1]
    if len(vwap_frame) < 3:
        slope = 0.0
    else:
        slope = float(vwap_frame.iloc[-1]["vwap"] - vwap_frame.iloc[-3]["vwap"])

    return {
        "timestamp": str(latest["timestamp"]),
        "vwap": round_price(float(latest["vwap"])),
        "slope_points": round_price(slope),
    }
