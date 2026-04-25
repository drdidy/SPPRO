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

    Expected columns: timestamp, open, high, low, close. If volume is present,
    true volume-weighted VWAP is used; otherwise the function falls back to an
    equal-weight proxy so the execution layer can still degrade gracefully.
    """

    if candles is None or candles.empty:
        return pd.DataFrame(columns=["timestamp", "vwap"])

    df = candles.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"]).map(to_central_time)

    typical_price = (df["high"].astype(float) + df["low"].astype(float) + df["close"].astype(float)) / 3.0
    if "volume" in df.columns:
        volume = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0).clip(lower=0.0)
        if float(volume.sum()) <= 0:
            volume = pd.Series([1.0] * len(df), index=df.index)
            quality = "proxy"
        else:
            quality = "volume"
    else:
        volume = pd.Series([1.0] * len(df), index=df.index)
        quality = "proxy"

    cumulative_tp_vol = (typical_price * volume).cumsum()
    cumulative_vol = volume.cumsum().replace(0, pd.NA).ffill().fillna(1.0)

    df["vwap"] = cumulative_tp_vol / cumulative_vol
    df["vwap_quality"] = quality
    return df.loc[:, ["timestamp", "vwap", "vwap_quality"]]


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
        "quality": str(latest.get("vwap_quality", "unknown")),
    }
