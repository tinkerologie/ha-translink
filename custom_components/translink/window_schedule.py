"""Brisbane-local occurrence rules for commute windows."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .const import (
    BRISBANE_TZ,
    CONF_WINDOW_DATE,
    CONF_WINDOW_END,
    CONF_WINDOW_KIND,
    CONF_WINDOW_LEAD,
    CONF_WINDOW_START,
    CONF_WINDOW_WEEKDAYS,
    WINDOW_GRACE_MINUTES,
    WINDOW_MAX_DURATION_HOURS,
    WINDOW_ONCE,
    WINDOW_OPTION_LIMITS,
    WINDOW_RECURRING,
)

BRISBANE = ZoneInfo(BRISBANE_TZ)


@dataclass(frozen=True, slots=True)
class WindowOccurrence:
    """One occurrence with UTC polling and departure boundaries."""

    date: date
    start: datetime
    end: datetime
    activation: datetime
    grace_end: datetime


@dataclass(frozen=True, slots=True)
class WindowSchedule:
    """A one-off date or a recurring set of Brisbane weekdays."""

    start: time
    end: time
    lead: timedelta
    once: date | None
    weekdays: frozenset[int]

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> WindowSchedule:
        """Parse a schedule and report invalid fields using flow error keys."""
        start = time.fromisoformat(config[CONF_WINDOW_START])
        end = time.fromisoformat(config[CONF_WINDOW_END])
        if any(
            value.second or value.microsecond or value.tzinfo for value in (start, end)
        ):
            raise ValueError("window_minute_precision_required")
        day = date(2000, 1, 1)
        duration = datetime.combine(day, end) - datetime.combine(day, start)
        if duration < timedelta():
            duration += timedelta(days=1)
        if not timedelta() < duration <= timedelta(hours=WINDOW_MAX_DURATION_HOURS):
            raise ValueError("invalid_window_duration")

        if config.get(CONF_WINDOW_KIND, WINDOW_RECURRING) == WINDOW_ONCE:
            if not config.get(CONF_WINDOW_DATE):
                raise ValueError("window_date_required")
            once = date.fromisoformat(config[CONF_WINDOW_DATE])
            weekdays: frozenset[int] = frozenset()
        else:
            once = None
            weekdays = frozenset(
                int(day) for day in config.get(CONF_WINDOW_WEEKDAYS, ())
            )
            if not weekdays:
                raise ValueError("window_weekdays_required")
        lead = timedelta(
            minutes=config.get(
                CONF_WINDOW_LEAD, WINDOW_OPTION_LIMITS[CONF_WINDOW_LEAD][0]
            )
        )
        return cls(start, end, lead, once, weekdays)

    @property
    def identity(self) -> str:
        """Return the canonical schedule portion of a config entry unique ID."""
        if self.once is not None:
            days = f"{WINDOW_ONCE}_{self.once.isoformat()}"
        else:
            mask = sum(1 << weekday for weekday in self.weekdays)
            days = f"{WINDOW_RECURRING}_{mask}"
        return f"{days}_{self.start:%H%M}_{self.end:%H%M}"

    def on(self, day: date) -> WindowOccurrence:
        """Construct the occurrence that starts on the given Brisbane date."""
        end_day = day + timedelta(days=self.end < self.start)
        start = datetime.combine(day, self.start, BRISBANE).astimezone(UTC)
        end = datetime.combine(end_day, self.end, BRISBANE).astimezone(UTC)
        return WindowOccurrence(
            day,
            start,
            end,
            start - self.lead,
            end + timedelta(minutes=WINDOW_GRACE_MINUTES),
        )

    def occurrence_at(self, now: datetime) -> WindowOccurrence | None:
        """Find the current or next occurrence, including possible grace."""
        if self.once is not None:
            occurrence = self.on(self.once)
            return occurrence if now < occurrence.grace_end else None

        today = now.astimezone(BRISBANE).date()
        days = (today + timedelta(days=offset) for offset in range(-1, 8))
        return next(
            occurrence
            for day in days
            if day.weekday() in self.weekdays
            and now < (occurrence := self.on(day)).grace_end
        )

    def next_after(self, occurrence: WindowOccurrence) -> WindowOccurrence:
        """Find the following occurrence of a recurring window."""
        day = occurrence.date
        return self.on(
            next(
                candidate
                for offset in range(1, 8)
                if (candidate := day + timedelta(days=offset)).weekday()
                in self.weekdays
            )
        )
