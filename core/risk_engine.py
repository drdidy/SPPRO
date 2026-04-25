"""Risk gating, setup quality, and self-learning helpers for SPX Prophet.

This module is intentionally UI-independent. It can be called from Streamlit,
backtests, replay tools, or future broker integrations.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any

from core.projections import round_price
from core.time_utils import to_central_time


@dataclass(frozen=True)
class RiskLimits:
    """Operator-level risk controls for a daily SPX/ES session."""

    min_reward_risk: float = 1.25
    max_entry_distance_points: float = 7.5
    max_stop_distance_points: float = 18.0
    max_contracts: int = 3
    late_entry_cutoff_hour: int = 10
    late_entry_cutoff_minute: int = 0
    max_daily_losses: int = 1
    max_daily_trades: int = 2

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SetupQualityWeights:
    """Point allocation for the setup quality score."""

    structure: int = 25
    confirmation: int = 25
    risk: int = 20
    vwap: int = 20
    timing: int = 10

    def total(self) -> int:
        return self.structure + self.confirmation + self.risk + self.vwap + self.timing


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _play_prices(play: dict[str, Any] | None) -> dict[str, float]:
    if not play:
        return {"entry": 0.0, "stop": 0.0, "tp1": 0.0, "tp2": 0.0}
    return {
        "entry": _safe_float(play.get("entry", {}).get("price")),
        "stop": _safe_float(play.get("stop", {}).get("price")),
        "tp1": _safe_float(play.get("tp1", {}).get("price")),
        "tp2": _safe_float(play.get("tp2", {}).get("price")),
    }


def calculate_reward_risk(direction: str, play: dict[str, Any] | None) -> dict[str, Any]:
    """Calculate point risk/reward for a proposed primary play."""

    prices = _play_prices(play)
    direction = str(direction or "").upper()
    entry = prices["entry"]
    stop = prices["stop"]
    tp1 = prices["tp1"]
    tp2 = prices["tp2"]

    if entry <= 0 or stop <= 0 or tp1 <= 0:
        return {
            "valid": False,
            "risk_points": 0.0,
            "reward_points_tp1": 0.0,
            "reward_points_tp2": 0.0,
            "reward_risk_tp1": 0.0,
            "reward_risk_tp2": 0.0,
        }

    if direction in {"CALL", "LONG"}:
        risk = max(entry - stop, 0.0)
        reward1 = max(tp1 - entry, 0.0)
        reward2 = max(tp2 - entry, 0.0)
    elif direction in {"PUT", "SHORT"}:
        risk = max(stop - entry, 0.0)
        reward1 = max(entry - tp1, 0.0)
        reward2 = max(entry - tp2, 0.0)
    else:
        risk = 0.0
        reward1 = 0.0
        reward2 = 0.0

    return {
        "valid": risk > 0 and reward1 > 0,
        "risk_points": round_price(risk),
        "reward_points_tp1": round_price(reward1),
        "reward_points_tp2": round_price(reward2),
        "reward_risk_tp1": round_price(reward1 / risk) if risk > 0 else 0.0,
        "reward_risk_tp2": round_price(reward2 / risk) if risk > 0 else 0.0,
    }


def classify_vwap_alignment(direction: str, entry_price: float, vwap_context: dict[str, Any] | None) -> dict[str, Any]:
    """Score whether 5-minute ES VWAP supports the proposed entry.

    Logic:
    - For CALL/LONG: VWAP near or below entry strengthens support.
    - For PUT/SHORT: VWAP near or above entry strengthens resistance.
    - If VWAP is far away, it is neutral-to-weak.
    """

    if not vwap_context:
        return {
            "available": False,
            "score": 0,
            "label": "VWAP unavailable",
            "distance_points": None,
            "supports_direction": False,
            "notes": ["No 5-minute ES VWAP context was supplied."],
        }

    vwap_value = _safe_float(vwap_context.get("vwap"), 0.0)
    if vwap_value <= 0 or entry_price <= 0:
        return {
            "available": False,
            "score": 0,
            "label": "VWAP invalid",
            "distance_points": None,
            "supports_direction": False,
            "notes": ["VWAP or entry price was not usable."],
        }

    direction = str(direction or "").upper()
    distance = round_price(entry_price - vwap_value)
    abs_distance = abs(distance)
    slope = _safe_float(vwap_context.get("slope_points"), 0.0)

    near = abs_distance <= 3.0
    close = abs_distance <= 6.0
    supports = False
    notes: list[str] = []

    if direction in {"CALL", "LONG"}:
        supports = near or (close and vwap_value <= entry_price)
        notes.append("VWAP is acting like support for a bullish setup." if supports else "VWAP is not close enough to confirm bullish support.")
    elif direction in {"PUT", "SHORT"}:
        supports = near or (close and vwap_value >= entry_price)
        notes.append("VWAP is acting like resistance for a bearish setup." if supports else "VWAP is not close enough to confirm bearish resistance.")
    else:
        notes.append("Unknown direction, VWAP scored as neutral.")

    if near and supports:
        score = 20
        label = "Strong VWAP confluence"
    elif close and supports:
        score = 14
        label = "Moderate VWAP confluence"
    elif close:
        score = 8
        label = "VWAP nearby but mixed"
    else:
        score = 3
        label = "Weak VWAP confluence"

    if direction in {"CALL", "LONG"} and slope > 0:
        score = min(20, score + 2)
        notes.append("VWAP slope is rising with the bullish setup.")
    if direction in {"PUT", "SHORT"} and slope < 0:
        score = min(20, score + 2)
        notes.append("VWAP slope is falling with the bearish setup.")

    return {
        "available": True,
        "score": int(score),
        "label": label,
        "vwap": round_price(vwap_value),
        "entry_price": round_price(entry_price),
        "distance_points": distance,
        "abs_distance_points": round_price(abs_distance),
        "slope_points": round_price(slope),
        "supports_direction": supports,
        "notes": notes,
    }


def build_setup_quality_score(
    *,
    scenario: dict[str, Any],
    confirmation: dict[str, Any],
    sit_out: dict[str, Any],
    current_price: float,
    vwap_context: dict[str, Any] | None = None,
    current_time: Any = None,
    limits: RiskLimits | None = None,
) -> dict[str, Any]:
    """Build the scorecard that converts raw signals into trade decisions."""

    limits = limits or RiskLimits()
    weights = SetupQualityWeights()
    play = scenario.get("primary_play")
    direction = str((play or {}).get("direction") or scenario.get("primary_trade_direction") or "").upper()
    prices = _play_prices(play)
    rr = calculate_reward_risk(direction, play)
    entry_distance = abs(_safe_float(current_price) - prices["entry"]) if prices["entry"] else 0.0
    vwap = classify_vwap_alignment(direction, prices["entry"], vwap_context)

    structure_widths = scenario.get("channel_widths", {}) or {}
    narrowest_width = min(
        _safe_float(structure_widths.get("ascending"), 0.0),
        _safe_float(structure_widths.get("descending"), 0.0),
    )
    structure_score = weights.structure
    if narrowest_width <= 0:
        structure_score = 5
    elif narrowest_width < 3:
        structure_score = 8
    elif narrowest_width < 7:
        structure_score = 16

    confirmation_score = 0
    if confirmation.get("confirmed"):
        confirmation_score = weights.confirmation
    elif confirmation.get("tested") and not confirmation.get("failed"):
        confirmation_score = 14
    elif not confirmation.get("available"):
        confirmation_score = 10

    risk_score = weights.risk
    if not rr["valid"]:
        risk_score = 0
    elif rr["reward_risk_tp1"] < 1.0:
        risk_score = 6
    elif rr["reward_risk_tp1"] < limits.min_reward_risk:
        risk_score = 12

    timing_score = weights.timing
    now_ct = to_central_time(current_time) if current_time is not None else None
    if now_ct is not None:
        cutoff = now_ct.replace(hour=limits.late_entry_cutoff_hour, minute=limits.late_entry_cutoff_minute, second=0, microsecond=0)
        if now_ct > cutoff:
            timing_score = 2

    score_components = {
        "structure": int(structure_score),
        "confirmation": int(confirmation_score),
        "risk": int(risk_score),
        "vwap": int(vwap["score"]),
        "timing": int(timing_score),
    }
    raw_score = sum(score_components.values())
    final_score = int(round(raw_score / weights.total() * 100))

    blockers: list[str] = []
    warnings: list[str] = []

    if sit_out.get("sit_out"):
        blockers.extend(str(reason) for reason in sit_out.get("reasons", []))
    if not rr["valid"]:
        blockers.append("Reward/risk could not be validated.")
    elif rr["reward_risk_tp1"] < limits.min_reward_risk:
        blockers.append(f"Reward/risk to TP1 is below {limits.min_reward_risk}.")
    if rr["risk_points"] > limits.max_stop_distance_points:
        blockers.append(f"Stop distance exceeds {limits.max_stop_distance_points} points.")
    if entry_distance > limits.max_entry_distance_points:
        blockers.append(f"Current price is more than {limits.max_entry_distance_points} points from entry.")
    if confirmation.get("failed"):
        blockers.append("Confirmation failed.")
    if vwap.get("available") and not vwap.get("supports_direction"):
        warnings.append("VWAP does not strongly support the predicted direction.")

    if blockers:
        decision = "NO TRADE"
    elif final_score >= 80:
        decision = "TRADE"
    elif final_score >= 65:
        decision = "CONDITIONAL TRADE"
    elif final_score >= 50:
        decision = "WATCH ONLY"
    else:
        decision = "NO TRADE"

    suggested_contracts = int((play or {}).get("contracts") or 1)
    if decision == "CONDITIONAL TRADE":
        suggested_contracts = min(suggested_contracts, 1)
    if decision in {"WATCH ONLY", "NO TRADE"}:
        suggested_contracts = 0
    suggested_contracts = max(0, min(suggested_contracts, limits.max_contracts))

    return {
        "decision": decision,
        "score": final_score,
        "score_components": score_components,
        "reward_risk": rr,
        "entry_distance_points": round_price(entry_distance),
        "vwap_alignment": vwap,
        "suggested_contracts": suggested_contracts,
        "blockers": blockers,
        "warnings": warnings,
        "limits": limits.to_dict(),
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


def build_learning_event(
    *,
    trade_date: str,
    scenario: dict[str, Any],
    setup_quality: dict[str, Any],
    vwap_context: dict[str, Any] | None = None,
    outcome: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a compact record for future self-learning/backtest storage."""

    play = scenario.get("primary_play") or {}
    return {
        "trade_date": trade_date,
        "scenario_name": scenario.get("scenario_name"),
        "direction": play.get("direction"),
        "entry_price": (play.get("entry") or {}).get("price"),
        "stop_price": (play.get("stop") or {}).get("price"),
        "tp1_price": (play.get("tp1") or {}).get("price"),
        "tp2_price": (play.get("tp2") or {}).get("price"),
        "setup_score": setup_quality.get("score"),
        "decision": setup_quality.get("decision"),
        "vwap": (vwap_context or {}).get("vwap"),
        "vwap_distance_points": (setup_quality.get("vwap_alignment") or {}).get("distance_points"),
        "reward_risk_tp1": (setup_quality.get("reward_risk") or {}).get("reward_risk_tp1"),
        "outcome": outcome or {},
    }
