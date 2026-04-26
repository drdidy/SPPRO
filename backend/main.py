"""Production API bridge for SPX Prophet.

This first slice intentionally serves a stable mock payload. The existing
Streamlit app remains the source of truth while the Next.js operator surface is
developed. The next wiring pass can replace `build_mock_operator_snapshot()`
with a real adapter around the tested Python intelligence functions.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


class OperatorSnapshot(BaseModel):
    """Single response object consumed by the production operator UI."""

    generated_at: str
    decision: dict[str, Any] = Field(default_factory=dict)
    market_context: dict[str, Any] = Field(default_factory=dict)
    primary_play: dict[str, Any] = Field(default_factory=dict)
    alternate_play: dict[str, Any] = Field(default_factory=dict)
    strike_ladders: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    structure: dict[str, Any] = Field(default_factory=dict)


SNAPSHOT_PATH = Path(os.environ.get("SPX_PROPHET_SNAPSHOT_PATH", Path(__file__).resolve().parents[1] / "data" / "operator_snapshot.json"))


def load_latest_operator_snapshot() -> OperatorSnapshot | None:
    """Load the latest real Streamlit-exported operator snapshot when available."""

    if not SNAPSHOT_PATH.exists():
        return None
    try:
        payload = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return OperatorSnapshot(**payload)
    except Exception:
        return None
    return None


def build_mock_operator_snapshot() -> OperatorSnapshot:
    """Return realistic demo data for the first Next.js production shell."""

    return OperatorSnapshot(
        generated_at=datetime.now(timezone.utc).isoformat(),
        decision={
            "state": "WAIT",
            "modifier": "VALID",
            "bias": "Bearish",
            "scenario": "Between Channels",
            "confidence": 74,
            "risk": "LOW",
            "event_risk": "Major",
            "planned_entry": 7167.16,
            "selected_strike": "7155P",
            "expected_fill": 7.71,
            "budget": "Over Budget",
            "reason": "Waiting for price to return to the Asian polarity entry line.",
        },
        market_context={
            "risk_mode": "High Watch",
            "event_risk": "Major",
            "next_event": "No scheduled release loaded",
            "interpretation": "Headline risk may widen fills and reduce estimate reliability.",
            "headlines": [
                {
                    "title": "Macro calendar feed ready for high-impact events",
                    "source": "SPX Prophet",
                    "time": "Now",
                    "url": None,
                },
                {
                    "title": "Policy and headline shock watch is active",
                    "source": "SPX Prophet",
                    "time": "Now",
                    "url": None,
                },
                {
                    "title": "Live news feed can be connected after API credentials are added",
                    "source": "SPX Prophet",
                    "time": "Setup",
                    "url": None,
                },
            ],
        },
        primary_play={
            "title": "Primary Idea",
            "direction": "Put",
            "status": "Armed",
            "contract": "7155P",
            "current_mark": 23.30,
            "at_entry": 7.49,
            "expected_fill": 7.71,
            "rr": 1.31,
            "zone": "Near Zone",
            "budget": "Over Budget",
            "quality": "Moderate",
            "reason": "Best bearish fit if SPX retests the planned entry line.",
        },
        alternate_play={
            "title": "Alternate Idea",
            "direction": "Call",
            "status": "Watch",
            "contract": "7180C",
            "current_mark": 9.80,
            "at_entry": 5.35,
            "expected_fill": 5.54,
            "rr": 1.05,
            "zone": "Outside Zone",
            "budget": "Within Budget",
            "quality": "Weak",
            "reason": "Informational only until bullish polarity confirms.",
        },
        strike_ladders={
            "primary": [
                {"strike": "7145P", "mark": 18.40, "at_entry": 6.10, "fill": 6.31, "rr": 1.18, "budget": "Over", "tag": "Balanced"},
                {"strike": "7150P", "mark": 20.70, "at_entry": 6.82, "fill": 7.02, "rr": 1.24, "budget": "Over", "tag": "Best RR"},
                {"strike": "7155P", "mark": 23.30, "at_entry": 7.49, "fill": 7.71, "rr": 1.31, "budget": "Over", "tag": "Selected"},
                {"strike": "7160P", "mark": 26.10, "at_entry": 8.20, "fill": 8.43, "rr": 1.22, "budget": "Over", "tag": "System Pick"},
                {"strike": "7165P", "mark": 28.60, "at_entry": 9.06, "fill": 9.34, "rr": 1.06, "budget": "Over", "tag": "Rich"},
            ],
            "alternate": [
                {"strike": "7170C", "mark": 12.30, "at_entry": 6.14, "fill": 6.36, "rr": 0.92, "budget": "Over", "tag": "Watch"},
                {"strike": "7175C", "mark": 10.90, "at_entry": 5.71, "fill": 5.92, "rr": 0.98, "budget": "Over", "tag": "Balanced"},
                {"strike": "7180C", "mark": 9.80, "at_entry": 5.35, "fill": 5.54, "rr": 1.05, "budget": "Within", "tag": "Selected"},
                {"strike": "7185C", "mark": 8.45, "at_entry": 4.88, "fill": 5.04, "rr": 1.01, "budget": "Within", "tag": "Budget Fit"},
                {"strike": "7190C", "mark": 7.10, "at_entry": 4.22, "fill": 4.39, "rr": 0.86, "budget": "Within", "tag": "Cheap"},
            ],
        },
        structure={
            "current_es": 7194.75,
            "anchor_source": "Asian",
            "anchor_confidence": "Medium",
            "levels": [
                {"label": "Upper Polarity", "value": 7211.25, "tone": "danger"},
                {"label": "Active Entry Line", "value": 7167.16, "tone": "accent"},
                {"label": "Mid Structure", "value": 7146.80, "tone": "neutral"},
                {"label": "Lower Polarity", "value": 7108.40, "tone": "positive"},
            ],
        },
    )


app = FastAPI(title="SPX Prophet API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/operator-snapshot", response_model=OperatorSnapshot)
def operator_snapshot() -> OperatorSnapshot:
    return load_latest_operator_snapshot() or build_mock_operator_snapshot()
