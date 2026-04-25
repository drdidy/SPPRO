"""Quality-review layer for SPX Prophet.

This wrapper combines the scenario engine with risk, VWAP, and learning fields.
It is designed for decision support, review, replay, and journaling.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from core.risk_engine import RiskLimits, build_learning_event, build_setup_quality_score
from core.scenarios import build_signal_package


def build_quality_package(
    *,
    current_price: float,
    line_values: dict[str, float],
    confirmation: dict[str, Any],
    news_day: bool = False,
    current_time: Any = None,
    open_price: float | None = None,
    vwap_context: dict[str, Any] | None = None,
    session_date: str | date | None = None,
    risk_limits: RiskLimits | None = None,
) -> dict[str, Any]:
    """Build a quality-reviewed package around the existing scenario output."""

    base = build_signal_package(
        current_price=current_price,
        line_values=line_values,
        confirmation=confirmation,
        news_day=news_day,
        current_time=current_time,
        open_price=open_price,
    )

    setup_quality = build_setup_quality_score(
        scenario=base["scenario"],
        confirmation=base["confirmation"],
        sit_out=base["sit_out"],
        current_price=current_price,
        vwap_context=vwap_context,
        current_time=current_time,
        limits=risk_limits,
    )

    primary = base["scenario"].get("primary_play") or {}
    entry = primary.get("entry") or {}
    stop = primary.get("stop") or {}
    tp1 = primary.get("tp1") or {}
    tp2 = primary.get("tp2") or {}

    learning_event = build_learning_event(
        trade_date=str(session_date or ""),
        scenario=base["scenario"],
        setup_quality=setup_quality,
        vwap_context=vwap_context,
    )

    quality_card = {
        "decision": setup_quality["decision"],
        "score": setup_quality["score"],
        "scenario": base["scenario"].get("scenario_name"),
        "direction": primary.get("direction"),
        "entry_label": entry.get("label"),
        "entry_price": entry.get("price"),
        "stop_label": stop.get("label"),
        "stop_price": stop.get("price"),
        "tp1_label": tp1.get("label"),
        "tp1_price": tp1.get("price"),
        "tp2_label": tp2.get("label"),
        "tp2_price": tp2.get("price"),
        "reward_risk_tp1": setup_quality.get("reward_risk", {}).get("reward_risk_tp1"),
        "suggested_contracts": setup_quality.get("suggested_contracts"),
        "vwap_label": setup_quality.get("vwap_alignment", {}).get("label"),
        "vwap_distance_points": setup_quality.get("vwap_alignment", {}).get("distance_points"),
        "blockers": setup_quality.get("blockers", []),
        "warnings": setup_quality.get("warnings", []),
    }

    return {
        **base,
        "setup_quality": setup_quality,
        "learning_event": learning_event,
        "quality_card": quality_card,
    }


def quality_card_lines(package: dict[str, Any]) -> list[str]:
    """Return compact display lines for the top-level UI card."""

    quality = package.get("setup_quality", {})
    scenario = package.get("scenario", {})
    lines = [
        f"Quality state: {quality.get('decision', 'UNKNOWN')} | Score: {quality.get('score', 0)}/100",
        f"Scenario: {scenario.get('scenario_name', 'unknown')}",
    ]
    rr = quality.get("reward_risk", {})
    if rr:
        lines.append(f"Reward/risk to TP1: {rr.get('reward_risk_tp1', 0)}")
    vwap = quality.get("vwap_alignment", {})
    if vwap:
        lines.append(f"VWAP: {vwap.get('label', 'unavailable')}")
    for item in quality.get("blockers", []):
        lines.append(f"Blocker: {item}")
    for item in quality.get("warnings", []):
        lines.append(f"Warning: {item}")
    return lines
