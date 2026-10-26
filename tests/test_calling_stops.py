"""Scheduled/realtime joins use actual times and unambiguous stop occurrences."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from custom_components.translink.api.client import (
    _match_trip_record,
    _prediction_time,
    _realtime_stop,
    build_calling_stops,
    build_journey_summary,
)
from custom_components.translink.api.gtfs_realtime import (
    StopTimeEventRecord,
    StopTimeUpdateRecord,
    parse_trip_updates,
)
from custom_components.translink.api.models import JourneyPlanResult, TripTimetable


@pytest.fixture
def captured_case(plan_response_data, sample_trip_updates_bytes):
    """Captured planner/feed pair with a labelled synthetic schedule baseline."""
    plan = JourneyPlanResult.model_validate(plan_response_data)
    leg = plan.itineraries[0].legs[0]
    update = parse_trip_updates(sample_trip_updates_bytes)[
        "39040861-QR 26_27-44171-DK22"
    ]
    names = {s.id.removeprefix("SI:"): s.name for s in leg.skippedStops}
    rows = []
    for stop in update.stop_time_updates:
        if stop.stop_sequence < 21:
            continue
        event = stop.departure or stop.arrival
        rows.append(
            {
                "stopId": stop.stop_id,
                "name": names.get(stop.stop_id, stop.stop_id),
                "order": stop.stop_sequence,
                "scheduledDepartureUtc": datetime.fromtimestamp(
                    event.time - event.delay, UTC
                ).isoformat(),
                "canBoardDebark": "Alighting" if stop.departure is None else "Both",
            }
        )
    timetable = TripTimetable(id=leg.tripId, departures=rows)
    return plan, leg, update, timetable


def test_captured_overlay_and_service_date(captured_case):
    plan, leg, update, timetable = captured_case
    assert _match_trip_record(leg.tripId, {"39040861": update}, "RPSP") is update
    assert update.start_date == "20261006"
    assert leg.departureTimeUtc.startswith("2026-10-05")
    calls, source, updated = build_calling_stops(leg, timetable, update)
    assert source == "scheduled_with_realtime"
    assert len(calls) == 16
    assert calls[0].role == "origin" and calls[0].platform == "5"
    assert (
        calls[-1].role == "destination" and calls[-1].realtime.departureTimeUtc is None
    )
    assert calls[0].realtime.departureTimeUtc == "2026-10-05T23:43:00+00:00"
    assert calls[0].realtime.departureDelaySeconds == 0
    assert calls[1].platform is None
    assert updated == datetime.fromtimestamp(update.timestamp, UTC).isoformat()
    summary = build_journey_summary(
        plan, trip_updates={"39040861": update}, trip_timetables={leg.tripId: timetable}
    )
    assert summary.itinerary_legs[0]["callingStopsSource"] == source
    assert summary.itinerary_legs[0]["skippedStops"] == [
        s.name for s in leg.skippedStops
    ]
    wrong_date = deepcopy(update)
    wrong_date.start_date = "20261007"
    assert _match_trip_record(leg.tripId, {"39040861": wrong_date}, "RPSP") is None
    assert (
        _match_trip_record(leg.tripId, {leg.tripId: wrong_date}, "RPSP") is wrong_date
    )


def test_realtime_partial_and_absent_predictions(captured_case):
    _, leg, update, timetable = captured_case
    calls, source, _ = build_calling_stops(leg, None, update)
    assert source == "realtime_partial"
    assert calls[0].name == leg.origin.name
    assert calls[1].name == leg.skippedStops[0].name
    assert all(s.scheduledTimeUtc is None and s.order is None for s in calls)
    no_delay = deepcopy(update)
    for stop in no_delay.stop_time_updates:
        if stop.departure:
            stop.departure.delay = None
        if stop.arrival:
            stop.arrival.delay = None
    calls, source, _ = build_calling_stops(leg, timetable, no_delay)
    assert source == "scheduled"
    assert all(s.realtime is None for s in calls)
    assert build_calling_stops(leg, None, None) == ([], "unavailable", None)


def test_ambiguous_occurrences_fail_closed(captured_case):
    _, leg, update, timetable = captured_case
    repeated = deepcopy(timetable)
    duplicate = repeated.departures[0].model_copy(update={"order": 20})
    repeated.departures.insert(0, duplicate)
    assert build_calling_stops(leg, repeated, None)[1] == "unavailable"
    feed = deepcopy(update)
    first = next(s for s in feed.stop_time_updates if s.stop_id == "600019")
    feed.stop_time_updates = (first, first, *feed.stop_time_updates)
    assert build_calling_stops(leg, None, feed)[1] == "unavailable"
    calls, _, _ = build_calling_stops(leg, timetable, feed)
    assert calls[0].realtime is None
    missing = leg.model_copy(deep=True)
    missing.destination.id = "missing"
    assert build_calling_stops(missing, timetable, update)[1] == "unavailable"
    missing.origin = None
    assert build_calling_stops(missing, timetable, update)[1] == "unavailable"
    walk = leg.model_copy(update={"travelMode": "Walk"})
    assert build_calling_stops(walk, timetable, update)[1] == "unavailable"
    missing_id = leg.model_copy(deep=True)
    missing_id.origin.id = None
    assert build_calling_stops(missing_id, timetable, update)[1] == "unavailable"


def test_relationships_and_missing_times(captured_case):
    _, leg, update, timetable = captured_case
    no_data = deepcopy(update)
    stop = next(s for s in no_data.stop_time_updates if s.stop_id == "600019")
    stop.schedule_relationship = 2
    stop.arrival = stop.departure = None
    calls, source, _ = build_calling_stops(leg, timetable, no_data)
    assert source == "scheduled_with_realtime"
    assert calls[0].realtime.scheduleRelationship == "no_data"
    assert calls[0].realtime.departureTimeUtc is None
    assert (
        _realtime_stop(
            StopTimeUpdateRecord(schedule_relationship=99)
        ).scheduleRelationship
        == "unknown"
    )
    assert _prediction_time(None) is None
    assert _prediction_time(10**100) is None
    unique = leg.model_copy(update={"departureTimeUtc": None, "arrivalTimeUtc": None})
    assert build_calling_stops(unique, timetable, None)[1] == "scheduled"
    # Explicit zero is retained; an omitted event remains absent.
    result = _realtime_stop(
        StopTimeUpdateRecord(arrival=StopTimeEventRecord(time=None, delay=0))
    )
    assert result.arrivalTimeUtc is None and result.arrivalDelaySeconds == 0
