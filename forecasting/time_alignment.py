"""Explicit clock-label alignment requested by the dataset owner.

CSV labels stay timezone-naive. Their calendar date and clock hour are matched
unchanged to the weather/API UTC axis. This is an alignment convention, not a
claim that the source timezone is known to be UTC. No timezone conversion or
geographic offset is applied to observations.
"""

from datetime import datetime, timedelta, timezone

TIME_POLICY = "as_provided_no_shift"


def time_alignment_metadata() -> dict[str, object]:
    return {
        "policy": TIME_POLICY,
        "source_timezone": None,
        "source_clock_shift_hours": 0,
        "forecast_axis": "UTC",
        "basis": "Match source clock labels directly to weather/API clock labels per user instruction; source timezone is unspecified.",
    }


def source_hour_end_on_forecast_axis(hour_start: datetime) -> datetime:
    if hour_start.tzinfo is not None:
        raise ValueError("Ожидается исходная метка CSV без часового пояса")
    # +1 hour labels the END of the aggregated hour; it is not a timezone shift.
    return (hour_start + timedelta(hours=1)).replace(tzinfo=timezone.utc)
