"""Commute window schedules use Brisbane civil dates."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.translink.window_schedule import WindowSchedule


def test_overnight_occurrence_belongs_to_start_weekday() -> None:
    """Find Sunday through Monday even with a different local timezone."""
    schedule = WindowSchedule.from_config(
        {"window_weekdays": ["6"], "window_start": "23:00", "window_end": "01:00"}
    )
    now = datetime(2026, 11, 8, 7, tzinfo=ZoneInfo("America/Los_Angeles"))
    occurrence = schedule.occurrence_at(now)
    assert occurrence is not None
    assert occurrence.date.isoformat() == "2026-11-08"
    assert occurrence.start == datetime(2026, 11, 8, 13, tzinfo=UTC)
    assert occurrence.end == datetime(2026, 11, 8, 15, tzinfo=UTC)
    assert occurrence.activation == occurrence.start - timedelta(minutes=15)
    assert occurrence.grace_end == occurrence.end + timedelta(hours=1)
    assert schedule.next_after(occurrence).date.isoformat() == "2026-11-15"


def test_one_off_before_activation_and_after_grace() -> None:
    """Expose the next occurrence until the one-off ends."""
    schedule = WindowSchedule.from_config(
        {
            "window_kind": "once",
            "window_date": "2026-11-11",
            "window_start": "07:30",
            "window_end": "08:30",
        }
    )
    occurrence = schedule.occurrence_at(datetime(2026, 11, 10, 20, tzinfo=UTC))
    assert occurrence is not None
    assert occurrence.activation == datetime(2026, 11, 10, 21, 15, tzinfo=UTC)
    assert schedule.occurrence_at(occurrence.grace_end) is None


@pytest.mark.parametrize(("start", "end"), [("09:00", "09:00"), ("07:00", "19:01")])
def test_invalid_duration(start: str, end: str) -> None:
    """Reject an empty or overlong window."""
    with pytest.raises(ValueError, match="invalid_window_duration"):
        WindowSchedule.from_config(
            {"window_start": start, "window_end": end, "window_weekdays": ["0"]}
        )


def test_start_and_end_have_whole_minute_precision() -> None:
    """A minute-based window ID cannot alias a schedule using seconds."""
    with pytest.raises(ValueError, match="window_minute_precision_required"):
        WindowSchedule.from_config(
            {
                "window_start": "07:30:10",
                "window_end": "08:00:00",
                "window_weekdays": ["0"],
            }
        )
