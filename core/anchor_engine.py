"""Anchor Selection Engine for SPX Prophet.

Evaluates pivot candidates from multiple session windows (PM Window, Asian Session,
London/Pre-NY, Pre-NY) and selects the most structurally relevant anchor for NY.

The PM Window (12 PM–3 PM CT) remains a valid candidate source but is no longer
the only one considered. Asian and London pivots can override PM pivots when their
projected lines are closer to actual NY price action.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from core.time_utils import at_central, filter_time_range, to_central_time, get_valid_candle_count
from core.projections import project_price, round_price

# ---------------------------------------------------------------------------
# Session source registry
# ---------------------------------------------------------------------------

SESSION_SOURCES: dict[str, dict[str, Any]] = {
    "PM_WINDOW": {
        "label": "PM Window",
        "description": "12:00 PM–3:00 PM CT (prior session)",
        "base_weight": 1.0,
    },
    "ASIAN": {
        "label": "Asian Session",
        "description": "5:00 PM–12:00 AM CT (prior day)",
        "base_weight": 0.9,
    },
    "LONDON": {
        "label": "London/Pre-NY",
        "description": "12:00 AM–7:00 AM CT",
        "base_weight": 0.85,
    },
    "PRE_NY": {
        "label": "Pre-NY",
        "description": "7:00 AM–8:25 AM CT",
        "base_weight": 0.8,
    },
}

_SESSION_ORDER = ["PM_WINDOW", "ASIAN", "LONDON", "PRE_NY"]


def _get_session_windows(
    prior_session_date: date,
    next_trading_date: date,
) -> dict[str, tuple[datetime, datetime]]:
    """Return (start, end) CT timestamps for each candidate session window."""
    return {
        "PM_WINDOW": (
            at_central(prior_session_date, 12, 0),
            at_central(prior_session_date, 15, 0),
        ),
        "ASIAN": (
            at_central(prior_session_date, 17, 0),
            at_central(next_trading_date, 0, 0),
        ),
        "LONDON": (
            at_central(next_trading_date, 0, 0),
            at_central(next_trading_date, 7, 0),
        ),
        "PRE_NY": (
            at_central(next_trading_date, 7, 0),
            at_central(next_trading_date, 8, 25),
        ),
    }


# ---------------------------------------------------------------------------
# Candidate detection
# ---------------------------------------------------------------------------

def _build_candidate(
    context: dict,
    extreme: dict,
    pivot_type: str,
    session_source: str,
    window_start: datetime,
    window_end: datetime,
    confirmed: bool,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    """Assemble a standardized pivot candidate dict."""
    return {
        "pivot_type": pivot_type,
        "session_source": session_source,
        "pivot_time": context["pivot_candle"]["timestamp"],
        "pivot_price": float(context["pivot_candle"]["close"]),
        "extreme_price": float(extreme["high" if pivot_type == "high" else "low"]),
        "pivot_extreme": extreme,
        "previous_candle": context.get("previous_candle"),
        "pivot_candle": context.get("pivot_candle"),
        "next_candle": context.get("next_candle"),
        "green_candle": context.get("green_candle"),
        "red_candle": context.get("red_candle"),
        "confirmed": confirmed,
        "fallback_reason": fallback_reason,
        "window_start": window_start,
        "window_end": window_end,
        # Scoring fields — populated by _score_and_sort
        "candidate_rank_score": 0.0,
        "selection_reason": "",
        "projected_level_at_830": None,
        "projected_level_at_900": None,
        "distance_to_current_price": None,
    }


def _find_pivot_in_window(
    candles_norm: "pd.DataFrame",
    window_start: datetime,
    window_end: datetime,
    pivot_type: str,
    session_source: str,
) -> dict[str, Any] | None:
    """Find the last strict pivot (or strongest-close fallback) in a time window.

    Extends the search window leftward by 2 hours so the i-1 context candle
    is available for the first eligible bar. Uses reset_index to guarantee
    positional integer indexing throughout.
    """
    from core.pivots import (
        _is_pivot_high,
        _is_pivot_low,
        _select_pivot_context_candles,
        _resolve_pivot_extreme,
    )

    context_start = window_start - timedelta(hours=2)
    extended = filter_time_range(candles_norm, context_start, window_end)
    extended = extended.reset_index(drop=True)

    if len(extended) < 3:
        return None

    is_pivot_fn = _is_pivot_high if pivot_type == "high" else _is_pivot_low
    last_match: dict[str, Any] | None = None

    for i in range(1, len(extended) - 1):
        row_ts = to_central_time(extended.iloc[i]["timestamp"])
        if row_ts < window_start:
            continue
        if not is_pivot_fn(extended, i):
            continue
        context = _select_pivot_context_candles(extended, i)
        extreme = _resolve_pivot_extreme(context, pivot_type)
        last_match = _build_candidate(
            context, extreme, pivot_type, session_source,
            window_start, window_end, confirmed=True,
        )

    if last_match is not None:
        return last_match

    # Fallback: strongest close inside the actual window
    in_win = filter_time_range(candles_norm, window_start, window_end)
    in_win = in_win.reset_index(drop=True)
    if in_win.empty:
        return None

    if pivot_type == "high":
        fb_pos = int(in_win["close"].astype(float).idxmax())
    else:
        fb_pos = int(in_win["close"].astype(float).idxmin())

    fb_ts = in_win.iloc[fb_pos]["timestamp"]
    ext_mask = extended["timestamp"] == fb_ts
    if not ext_mask.any():
        return None
    ext_pos = int(ext_mask.idxmax())

    context = _select_pivot_context_candles(extended, ext_pos)
    extreme = _resolve_pivot_extreme(context, pivot_type)
    return _build_candidate(
        context, extreme, pivot_type, session_source,
        window_start, window_end, confirmed=False,
        fallback_reason="no_strict_pivot_in_window",
    )


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _project_candidate(candidate: dict, target_time: datetime, direction: str) -> float:
    """Project a candidate anchor forward to target_time using the standard rate."""
    start = to_central_time(candidate["pivot_time"])
    try:
        count = get_valid_candle_count(start, to_central_time(target_time))
    except ValueError:
        count = 0
    return project_price(candidate["extreme_price"], count, direction)


def _score_and_sort(
    candidates: list[dict],
    pivot_type: str,
    reference_price: float | None,
    eight_thirty_target: datetime,
    nine_am_target: datetime,
) -> list[dict]:
    """Score every candidate and return the list sorted best-first.

    Score components:
    - Proximity (60 pts, when reference_price available): how close is the projected
      line at 9 AM to the reference price. Uses min distance across ascending and
      descending projections so both channel orientations are considered.
    - Extremeness (20 pts with proximity, 65 pts without): for high pivots, higher
      price scores better; for low pivots, lower price scores better.
    - Session weight (15 pts with proximity, 30 pts without): PM=1.0, Asian=0.9,
      London=0.85, Pre-NY=0.8, normalized to 0–15/30 pts.
    - Confirmation bonus (5 pts): strict pivot beats fallback strongest-close.
    """
    if not candidates:
        return candidates

    for c in candidates:
        c["projected_level_at_830"] = round_price(
            _project_candidate(c, eight_thirty_target, "ascending")
        )
        c["projected_level_at_900"] = round_price(
            _project_candidate(c, nine_am_target, "ascending")
        )
        if reference_price is not None:
            asc_9 = _project_candidate(c, nine_am_target, "ascending")
            desc_9 = _project_candidate(c, nine_am_target, "descending")
            c["distance_to_current_price"] = round_price(
                min(abs(asc_9 - reference_price), abs(desc_9 - reference_price))
            )

    prices = [c["extreme_price"] for c in candidates]
    p_min, p_max = min(prices), max(prices)
    price_range = p_max - p_min

    for c in candidates:
        if price_range > 0:
            extremeness = (
                (c["extreme_price"] - p_min) / price_range
                if pivot_type == "high"
                else (p_max - c["extreme_price"]) / price_range
            )
        else:
            extremeness = 1.0

        w = SESSION_SOURCES[c["session_source"]]["base_weight"]
        conf_bonus = 1.0 if c["confirmed"] else 0.0

        if reference_price is not None and c.get("distance_to_current_price") is not None:
            # proximity: 1 / (1 + dist/5) → 1.0 at 0 pts, ~0.5 at 5 pts, ~0.17 at 25 pts
            proximity = 1.0 / (1.0 + c["distance_to_current_price"] / 5.0)
            score = proximity * 60.0 + extremeness * 20.0 + w * 15.0 + conf_bonus * 5.0
        else:
            score = extremeness * 65.0 + w * 30.0 + conf_bonus * 5.0

        c["candidate_rank_score"] = round(score, 3)

    return sorted(candidates, key=lambda x: x["candidate_rank_score"], reverse=True)


def _confidence_level(candidates: list[dict]) -> str:
    """HIGH / MEDIUM / LOW based on score gap between top two candidates."""
    if len(candidates) <= 1:
        return "MEDIUM"
    top = candidates[0]["candidate_rank_score"]
    runner = candidates[1]["candidate_rank_score"]
    if top == 0:
        return "LOW"
    gap = (top - runner) / top
    if gap > 0.20:
        return "HIGH"
    if gap > 0.05:
        return "MEDIUM"
    return "LOW"


def _build_reason(
    selected: dict,
    all_candidates: list[dict],
    reference_price: float | None,
) -> str:
    """Human-readable explanation of why this candidate was selected."""
    src_label = SESSION_SOURCES[selected["session_source"]]["label"]
    ts = selected["pivot_time"]
    ts_str = ts.strftime("%-I:%M %p CT") if hasattr(ts, "strftime") else str(ts)
    price = selected["extreme_price"]

    if len(all_candidates) == 1:
        return f"Only {src_label} pivot available ({price:.2f} at {ts_str})."

    if selected["session_source"] == "PM_WINDOW":
        if reference_price is None:
            return f"PM Window pivot ({price:.2f}) selected as most extreme candidate."
        return (
            f"PM Window pivot ({price:.2f}) selected — "
            f"projected line closest to reference price ({reference_price:.2f})."
        )

    pm = next((c for c in all_candidates if c["session_source"] == "PM_WINDOW"), None)
    pm_str = f"PM Window ({pm['extreme_price']:.2f})" if pm else "PM Window"
    proj_900 = selected.get("projected_level_at_900")
    proj_str = f" Projected at 9 AM: {proj_900:.2f}." if proj_900 is not None else ""

    if reference_price is not None:
        return (
            f"{src_label} pivot ({price:.2f} at {ts_str}) overrides {pm_str} — "
            f"projected line is closer to reference price ({reference_price:.2f}).{proj_str}"
        )
    return (
        f"{src_label} pivot ({price:.2f} at {ts_str}) overrides {pm_str} — "
        f"structurally more extreme.{proj_str}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_anchor_selection(
    candles: "pd.DataFrame",
    prior_session_date: date,
    next_trading_date: date,
    reference_price: float | None = None,
    anchor_source_override: str | None = None,
) -> dict[str, Any]:
    """Evaluate multi-session pivot candidates and select the best anchors.

    Parameters
    ----------
    candles : pd.DataFrame
        Full ES candle frame (1-hour) covering at least the prior session and
        overnight through next_trading_date.
    prior_session_date : date
        Prior trading session date — defines the PM Window.
    next_trading_date : date
        Next trading session date — defines Asian, London, Pre-NY windows.
    reference_price : float | None
        Optional 9 AM reference price (ES) for proximity scoring. When None,
        selection is based purely on extremeness and session weight.
    anchor_source_override : str | None
        Force a specific session: "PM_WINDOW" | "ASIAN" | "LONDON" | "PRE_NY".
        None means Auto (all windows evaluated).

    Returns
    -------
    dict with keys:
        pivot_high      — selected high candidate (resolve_anchor_prices-compatible)
        pivot_low       — selected low candidate
        candidates      — {"pivot_high": [...scored], "pivot_low": [...scored]}
        selection       — metadata: source, confidence, reason for each role
        anchor_source_override — echoes the override parameter
    """
    from core.pivots import _normalize_candles

    normalized = _normalize_candles(candles)
    windows = _get_session_windows(prior_session_date, next_trading_date)
    t830 = at_central(next_trading_date, 8, 30)
    t900 = at_central(next_trading_date, 9, 0)

    sources = (
        [anchor_source_override]
        if anchor_source_override and anchor_source_override in windows
        else _SESSION_ORDER
    )

    high_cands: list[dict] = []
    low_cands: list[dict] = []

    for src in sources:
        w_start, w_end = windows[src]
        hc = _find_pivot_in_window(normalized, w_start, w_end, "high", src)
        if hc:
            high_cands.append(hc)
        lc = _find_pivot_in_window(normalized, w_start, w_end, "low", src)
        if lc:
            low_cands.append(lc)

    # Guarantee at least one candidate — fall back to PM_WINDOW
    if not high_cands:
        w_start, w_end = windows["PM_WINDOW"]
        hc = _find_pivot_in_window(normalized, w_start, w_end, "high", "PM_WINDOW")
        if hc:
            high_cands.append(hc)
    if not low_cands:
        w_start, w_end = windows["PM_WINDOW"]
        lc = _find_pivot_in_window(normalized, w_start, w_end, "low", "PM_WINDOW")
        if lc:
            low_cands.append(lc)

    high_scored = _score_and_sort(high_cands, "high", reference_price, t830, t900)
    low_scored = _score_and_sort(low_cands, "low", reference_price, t830, t900)

    sel_high = high_scored[0] if high_scored else None
    sel_low = low_scored[0] if low_scored else None

    if sel_high:
        sel_high["selection_reason"] = _build_reason(sel_high, high_scored, reference_price)
    if sel_low:
        sel_low["selection_reason"] = _build_reason(sel_low, low_scored, reference_price)

    return {
        "pivot_high": sel_high,
        "pivot_low": sel_low,
        "candidates": {
            "pivot_high": high_scored,
            "pivot_low": low_scored,
        },
        "selection": {
            "pivot_high_source": sel_high["session_source"] if sel_high else "PM_WINDOW",
            "pivot_low_source": sel_low["session_source"] if sel_low else "PM_WINDOW",
            "pivot_high_confidence": _confidence_level(high_scored),
            "pivot_low_confidence": _confidence_level(low_scored),
            "pivot_high_reason": sel_high.get("selection_reason", "") if sel_high else "",
            "pivot_low_reason": sel_low.get("selection_reason", "") if sel_low else "",
        },
        "anchor_source_override": anchor_source_override,
    }
