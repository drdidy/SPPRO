"""Timezone, trading-hours, and session window helpers for SPX Prophet."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

CENTRAL_TZ = ZoneInfo("America/Chicago")
EASTERN_TZ = ZoneInfo("America/New_York")


def to_central_time(value: datetime) -> datetime:
    """Convert a datetime-like value to timezone-aware Central Time."""

    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()

    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)

    return value.astimezone(CENTRAL_TZ)


def market_time_to_central(value: datetime, source_tz=EASTERN_TZ) -> datetime:
    """Convert a market timestamp to Central Time.

    Naive timestamps are assumed to be in the source market timezone, which is
    Eastern Time for the yfinance feeds used in this project.
    """

    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()

    if value.tzinfo is None:
        value = value.replace(tzinfo=source_tz)

    return value.astimezone(CENTRAL_TZ)


def at_central(session_date: date, hour: int, minute: int = 0) -> datetime:
    """Build a Central Time datetime for a given date and wall-clock time."""

    return datetime.combine(session_date, time(hour, minute), tzinfo=CENTRAL_TZ)


def _ceil_to_hour(value: datetime) -> datetime:
    """Round a timestamp up to the next whole hour in Central Time."""

    value = to_central_time(value)
    rounded = value.replace(minute=0, second=0, microsecond=0)
    return rounded + timedelta(hours=1)


def _floor_to_hour(value: datetime) -> datetime:
    """Round a timestamp down to the current whole hour in Central Time."""

    value = to_central_time(value)
    return value.replace(minute=0, second=0, microsecond=0)


def is_valid_candle_close(timestamp: datetime) -> bool:
    """Return True when an hourly candle close is valid for ES trading."""

    timestamp = to_central_time(timestamp)

    if any((timestamp.minute, timestamp.second, timestamp.microsecond)):
        return False

    weekday = timestamp.weekday()
    hour = timestamp.hour

    if weekday == 5:
        return False

    if weekday == 6:
        return hour >= 18

    if weekday == 4:
        return hour <= 16

    return hour != 17


def get_valid_candle_count(start_time: datetime, end_time: datetime) -> int:
    """Count valid 1-hour candle closes after start_time through end_time."""

    start_ct = _ceil_to_hour(start_time)
    end_ct = _floor_to_hour(end_time)

    if end_ct < start_ct:
        raise ValueError("end_time must be greater than or equal to start_time")

    count = 0
    cursor = start_ct

    while cursor <= end_ct:
        if is_valid_candle_close(cursor):
            count += 1
        cursor += timedelta(hours=1)

    return count


def filter_time_range(frame, start_time: datetime, end_time: datetime):
    """Filter a dataframe-like object by Central Time timestamps."""

    start_ct = to_central_time(start_time)
    end_ct = to_central_time(end_time)
    timestamps = frame["timestamp"].map(to_central_time)
    return frame.loc[(timestamps >= start_ct) & (timestamps <= end_ct)].copy().reset_index(drop=True)


def current_central_time() -> datetime:
    """Return the current Central Time wall-clock timestamp."""

    return datetime.now(tz=CENTRAL_TZ)


def build_session_windows(prior_session_date: date, next_trading_date: date) -> dict[str, tuple[datetime, datetime]]:
    """Build the main SPX Prophet session windows in Central Time."""

    return {
        "prior_afternoon": (
            at_central(prior_session_date, 12, 0),
            at_central(prior_session_date, 16, 0),
        ),
        "prior_ny_session": (
            at_central(prior_session_date, 8, 30),
            at_central(prior_session_date, 16, 0),
        ),
        "asian_session": (
            at_central(prior_session_date, 17, 0),
            at_central(next_trading_date, 2, 0),
        ),
        "london_session": (
            at_central(next_trading_date, 2, 0),
            at_central(next_trading_date, 8, 30),
        ),
        "reaction_730": (
            at_central(next_trading_date, 7, 30),
            at_central(next_trading_date, 8, 30),
        ),
        "opening_drive": (
            at_central(next_trading_date, 8, 30),
            at_central(next_trading_date, 9, 0),
        ),
        "nine_am_target": (
            at_central(next_trading_date, 9, 0),
            at_central(next_trading_date, 9, 0),
        ),
        "asian_six_pm_target": (
            at_central(next_trading_date, 18, 0),
            at_central(next_trading_date, 18, 0),
        ),
        "asian_seven_pm_target": (
            at_central(next_trading_date, 19, 0),
            at_central(next_trading_date, 19, 0),
        ),
    }
