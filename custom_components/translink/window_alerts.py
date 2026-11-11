"""Correlate fresh realtime evidence and evaluate commute alert transitions."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Literal, cast

from .api.client import (
    _endpoint_prediction,
    _leg_matches_feed,
    _realtime_freshness,
    parse_iso_datetime,
)
from .api.gtfs_realtime import (
    TRIP_CANCELED,
    TripUpdateRecord,
    distinct_trip_updates,
    extract_base_trip_id,
)
from .api.models import JourneyLeg, PlanNotice
from .const import (
    DEFAULT_REALTIME_REGION,
    EVENT_TRIP_CANCELLED,
    EVENT_TRIP_DELAYED,
    EVENT_TRIP_DISRUPTION,
    EVENT_TRIP_RECOVERED,
    REALTIME_FEED_REGIONS,
    WINDOW_RECOVERY_HYSTERESIS_MINUTES,
)
from .window_matching import WindowTrip
from .window_schedule import BRISBANE

type ObservationStatus = Literal["confirmed", "stale", "unknown"]


class RealtimeIndex:
    """Index feed records without collapsing distinct updates into aliases."""

    def __init__(self, records: Mapping[str, TripUpdateRecord]) -> None:
        """Group records by normalized trip ID while preserving collisions."""
        self._trips: dict[str, list[TripUpdateRecord]] = defaultdict(list)
        for record in distinct_trip_updates(records):
            if base := extract_base_trip_id(record.trip_id):
                self._trips[base].append(record)

    def match(self, leg: JourneyLeg, scheduled: datetime) -> TripUpdateRecord | None:
        """Require one compatible identity and a consistent service date."""
        trip_id = leg.tripId or ""
        route = leg.legRoute
        if not _leg_matches_feed(
            leg, REALTIME_FEED_REGIONS[DEFAULT_REALTIME_REGION], True
        ):
            return None
        route_code = route.code if route else None
        parts = trip_id.rsplit("_", 2)
        encoded_date = parts[-2] if len(parts) == 3 else ""
        has_encoded_date = (
            len(encoded_date) == 8
            and encoded_date.isascii()
            and encoded_date.isdecimal()
        )
        service_date = (
            encoded_date
            if has_encoded_date
            else scheduled.astimezone(BRISBANE).strftime("%Y%m%d")
        )

        candidates = []
        for record in self._trips.get(extract_base_trip_id(trip_id) or "", ()):
            exact = record.trip_id == trip_id
            if record.start_date != service_date and not (
                exact and has_encoded_date and record.start_date is None
            ):
                continue
            if (
                route_code
                and record.route_id
                and (record.route_id.split("-", 1)[0] != route_code.split("-", 1)[0])
            ):
                continue
            candidates.append(record)

        exact_matches = [record for record in candidates if record.trip_id == trip_id]
        matches = exact_matches or candidates
        return matches[0] if len(matches) == 1 else None


@dataclass(frozen=True, slots=True)
class AlertLedgerEntry:
    """The alert transitions emitted for one trip in one occurrence."""

    delay_state: Literal["none", "delayed", "recovered"] = "none"
    last_delay: int | None = None
    cancelled: bool = False
    notice_ids: tuple[str, ...] = ()

    @classmethod
    def from_storage(cls, data: Mapping[str, Any]) -> AlertLedgerEntry:
        """Restore alert state, normalizing the notice collection."""
        return cls(
            cast(Literal["none", "delayed", "recovered"], data["delay_state"]),
            data["last_delay"],
            data["cancelled"],
            tuple(data["notice_ids"]),
        )

    def to_storage(self) -> dict[str, Any]:
        """Return the entry as JSON-compatible data."""
        return {**asdict(self), "notice_ids": list(self.notice_ids)}


@dataclass(frozen=True, slots=True)
class WindowAlert:
    """An event to publish to Home Assistant."""

    event_type: str
    delay: int | None = None
    previous_delay: int | None = None
    notice: PlanNotice | None = None


@dataclass(frozen=True, slots=True)
class WindowObservation:
    """Current trip state derived from uniquely matched realtime updates."""

    trip: WindowTrip
    status: ObservationStatus = "unknown"
    delay: int | None = None
    cancelled: bool = False
    updated_at: datetime | None = None
    notices: tuple[PlanNotice, ...] = ()
    recovery_confirmed: bool = False

    def as_state(self) -> dict[str, Any]:
        """Return the bounded state shown in the tracked trips sensor."""
        return {
            "fingerprint": self.trip.key,
            "route": self.trip.route,
            "scheduled_departure": self.trip.departure.isoformat(),
            "effective_departure": self.trip.effective_departure.isoformat(),
            "state": (
                "departed"
                if self.trip.departed
                else "tracked"
                if self.trip.returned
                else "not_returned"
            ),
            "realtime_status": self.status,
            "delay_minutes": self.delay,
            "cancelled": self.cancelled,
            "realtime_updated_at": self.updated_at.isoformat()
            if self.updated_at
            else None,
        }


def _notice_is_relevant(notice: PlanNotice, departure: datetime) -> bool:
    for value, is_start in ((notice.startsUtc, True), (notice.endsUtc, False)):
        if value is None:
            continue
        # Reject malformed or offset-free bounds.
        try:
            boundary = datetime.fromisoformat(value)
        except ValueError:
            return False
        if boundary.tzinfo is None or (
            departure < boundary if is_start else departure > boundary
        ):
            return False
    return True


def observe_window_trip(
    trip: WindowTrip,
    realtime: RealtimeIndex,
    now: datetime,
    plan_notices: Mapping[str, PlanNotice],
) -> WindowObservation:
    """Use the shared endpoint prediction and freshness rules for each leg."""
    if trip.departed or not trip.returned:
        return WindowObservation(
            replace(trip, departed=trip.departed or now > trip.effective_departure)
        )

    notices: dict[str, PlanNotice] = {}
    status: ObservationStatus = "unknown"
    first_departure = trip.effective_departure
    updated_at = None
    delay_seconds = None
    confirmed_delays = 0
    cancelled = False

    for index, leg in enumerate(trip.legs):
        scheduled = parse_iso_datetime(leg.departureTimeUtc)
        if scheduled is None or (record := realtime.match(leg, scheduled)) is None:
            continue
        # Feed timestamps cannot confirm alerts on behalf of an undated update.
        if not record.timestamp:
            continue
        timestamp, freshness = _realtime_freshness(record, now)
        if freshness == "stale":
            if status != "confirmed":
                status = "stale"
            continue
        assert timestamp is not None

        boarding = _endpoint_prediction(
            leg,
            record,
            None,
            [],
            timestamp,
            freshness,
            arrival=False,
            allow_trip_delay=True,
        )
        alighting = _endpoint_prediction(
            leg,
            record,
            None,
            [],
            timestamp,
            freshness,
            arrival=True,
            allow_trip_delay=True,
        )
        leg_cancelled = (
            record.trip_schedule_relationship == TRIP_CANCELED
            or boarding.relationship == "skipped"
            or alighting.relationship == "skipped"
        )
        if boarding.status == "no_data" or (
            boarding.delay_seconds is None and not leg_cancelled
        ):
            continue

        effective = first_departure if index == 0 else scheduled
        if boarding.delay_seconds is not None:
            effective = scheduled + timedelta(seconds=boarding.delay_seconds)
            if index == 0:
                first_departure = effective
        if now > effective:
            continue

        status = "confirmed"
        updated_at = max(updated_at, timestamp) if updated_at else timestamp
        cancelled |= leg_cancelled
        if boarding.delay_seconds is not None:
            confirmed_delays += 1
            delay_seconds = (
                boarding.delay_seconds
                if delay_seconds is None
                else max(delay_seconds, boarding.delay_seconds)
            )
        for reference in leg.notices:
            if reference.id is None:
                continue
            key = str(reference.id)
            notice = plan_notices.get(key) or PlanNotice(id=reference.id)
            if _notice_is_relevant(notice, scheduled):
                notices[key] = notice

    trip = replace(
        trip, effective_departure=first_departure, departed=now > first_departure
    )
    return WindowObservation(
        trip,
        status,
        round(delay_seconds / 60) if delay_seconds is not None else None,
        cancelled,
        updated_at,
        tuple(notices.values()),
        recovery_confirmed=confirmed_delays == len(trip.legs),
    )


def evaluate_window_trip(
    observation: WindowObservation,
    ledger: AlertLedgerEntry,
    *,
    threshold: int,
    step: int,
) -> tuple[AlertLedgerEntry, tuple[WindowAlert, ...]]:
    """Emit confirmed delay transitions, cancellations and leg-specific notices."""
    if observation.status != "confirmed" or observation.trip.departed:
        return ledger, ()

    alerts = []
    delay = observation.delay
    previous = ledger.last_delay
    if observation.cancelled and not ledger.cancelled:
        alerts.append(WindowAlert(EVENT_TRIP_CANCELLED, delay, previous))
        ledger = replace(ledger, cancelled=True)
    if delay is not None and not ledger.cancelled:
        if ledger.delay_state == "delayed":
            assert previous is not None
            if delay >= previous + step:
                alerts.append(WindowAlert(EVENT_TRIP_DELAYED, delay, previous))
                ledger = replace(ledger, last_delay=delay)
            elif (
                observation.recovery_confirmed
                and delay <= threshold - WINDOW_RECOVERY_HYSTERESIS_MINUTES
            ):
                alerts.append(WindowAlert(EVENT_TRIP_RECOVERED, delay, previous))
                ledger = replace(ledger, delay_state="recovered")
        elif delay >= threshold:
            alerts.append(WindowAlert(EVENT_TRIP_DELAYED, delay, previous))
            ledger = replace(ledger, delay_state="delayed", last_delay=delay)

    seen = list(ledger.notice_ids)
    for notice in observation.notices:
        key = str(notice.id)
        if key not in seen:
            alerts.append(WindowAlert(EVENT_TRIP_DISRUPTION, delay, previous, notice))
            seen.append(key)
    return replace(ledger, notice_ids=tuple(seen)), tuple(alerts)
