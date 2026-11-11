"""Journey progress and event evidence through the pure evaluator."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from custom_components.translink.api.gtfs_realtime import (
    STOP_NO_DATA,
    STOP_SKIPPED,
    TRIP_CANCELED,
    StopTimeEventRecord,
    StopTimeUpdateRecord,
    TripUpdateRecord,
    TripUpdateRecords,
    VehiclePositionRecord,
)
from custom_components.translink.api.models import (
    JourneyItinerary,
    JourneyLeg,
    JourneyPlanResult,
    Position,
    StopInfo,
)
from custom_components.translink.api.progress import (
    ProgressFeeds,
    evaluate_progress,
    snapshot_itinerary,
)


@pytest.fixture
def transfer() -> JourneyItinerary:
    """Central to Springfield with a transfer at Darra."""
    plan = JourneyPlanResult.model_validate_json(
        (Path(__file__).parent / "fixtures" / "plan_response.json").read_text()
    )
    return snapshot_itinerary(plan.itineraries[1])


def test_progress_before_departure_shows_scheduled_boarding(
    transfer: JourneyItinerary,
) -> None:
    """The action is scheduled before the first leg when no feed is available."""
    now = datetime(2026, 10, 5, 23, 27, tzinfo=UTC)
    result = evaluate_progress(transfer, planned_at=now, now=now)
    progress = result.progress
    assert progress.state == "not_started"
    assert progress.active_leg_index is None
    assert progress.active_leg_source == "unknown"
    assert progress.next_action is not None
    assert progress.next_action.type == "board"
    assert progress.next_action.stop_id == "SI:600019"
    assert progress.next_action.scheduled_time == now + timedelta(minutes=1)
    assert progress.next_action.time_source == "scheduled"
    assert progress.vehicle_observation is None
    assert not progress.transitions


def _transfer_feed(
    transfer: JourneyItinerary, now: datetime, *, stopped: bool, index: int = 0
) -> ProgressFeeds:
    leg = transfer.legs[index]
    full_trip_id = f"{leg.tripId.split('_')[-1]}-QR 26_27-44171-DY37"
    stop_id = leg.destination.id.removeprefix("SI:")
    route = leg.legRoute.code
    position = VehiclePositionRecord(
        entity_id="train1",
        vehicle_id="TRAIN1",
        vehicle_label=None,
        trip_id=full_trip_id,
        route_id=route,
        start_date="20261006",
        latitude=-27.47,
        longitude=153.02,
        timestamp=int(now.timestamp()),
        current_stop_sequence=12 if stopped else 11,
        current_status="STOPPED_AT" if stopped else "IN_TRANSIT_TO",
        stop_id=stop_id if stopped else "600320",
    )
    arrival = datetime.fromisoformat(leg.arrivalTimeUtc)
    update = TripUpdateRecord(
        entity_id="train1",
        trip_id=full_trip_id,
        route_id=route,
        start_date="20261006",
        timestamp=int(now.timestamp()),
        stop_time_updates=(
            StopTimeUpdateRecord(
                stop_sequence=12,
                stop_id=stop_id,
                arrival=StopTimeEventRecord(time=int(arrival.timestamp()), delay=0),
            ),
        ),
    )
    return ProgressFeeds(
        vehicle_positions=(position,), trip_updates={full_trip_id: update}
    )


def test_two_fresh_fixes_confirm_transfer(transfer: JourneyItinerary) -> None:
    """A dwell at the matching stop and sequence confirms the vehicle's arrival."""
    arrival = datetime(2026, 10, 5, 23, 56, tzinfo=UTC)
    previous = arrival - timedelta(seconds=25)
    before = evaluate_progress(
        transfer,
        planned_at=previous,
        now=previous,
        feeds=_transfer_feed(transfer, previous, stopped=False),
    )
    assert before.progress.state == "in_progress"
    assert before.progress.active_leg_source == "vehicle"
    assert not before.progress.transitions

    at_stop = evaluate_progress(
        transfer,
        planned_at=previous,
        now=arrival,
        feeds=_transfer_feed(transfer, arrival, stopped=True),
        memory=before.memory,
    )
    assert at_stop.progress.next_action.type == "transfer"
    assert at_stop.progress.next_action.time_source == "realtime"
    [event] = at_stop.progress.transitions
    assert event.type == "transfer_stop_reached"
    assert event.stop_id == "SI:600321"
    assert event.next_leg_route == "RPSP"
    assert event.next_leg_platform == "1"
    assert event.observed_at == arrival


@pytest.mark.parametrize(
    "rejected",
    [
        "first_fix",
        "stale_fix",
        "stale_previous_fix",
        "stale_trip_update",
        "missing_status",
        "missing_previous_status",
        "missing_sequence",
        "duplicate_vehicle",
        "wrong_vehicle",
        "missing_vehicle_id",
        "wrong_route",
        "wrong_service_date",
        "wrong_stop",
        "passed_stop",
        "older_fix",
        "same_timestamp",
        "duplicate_update",
        "wrong_update_route",
        "wrong_update_date",
        "skipped",
        "cancelled",
        "ambiguous_occurrence",
        "no_occurrence_sequence",
        "wrong_schedule_baseline",
        "before_departure",
        "switched_trip",
    ],
)
def test_unconfirmed_arrival_does_not_emit(
    transfer: JourneyItinerary, rejected: str
) -> None:
    """Reject evidence that cannot prove the planned vehicle stopped."""
    now = datetime(2026, 10, 5, 23, 56, tzinfo=UTC)
    if rejected == "before_departure":
        now -= timedelta(hours=1)
    earlier = now - timedelta(seconds=100 if rejected == "stale_previous_fix" else 25)
    before = _transfer_feed(transfer, earlier, stopped=False)
    after = _transfer_feed(transfer, now, stopped=True)
    (position,) = after.vehicle_positions
    (update,) = after.trip_updates.values()
    (occurrence,) = update.stop_time_updates
    if rejected == "missing_previous_status":
        before.vehicle_positions[0].current_status = None
    elif rejected == "stale_fix":
        position.timestamp -= 100
    elif rejected == "stale_trip_update":
        update.timestamp -= 301
    elif rejected == "missing_status":
        position.current_status = None
    elif rejected == "missing_sequence":
        position.current_stop_sequence = None
    elif rejected == "duplicate_vehicle":
        after = replace(
            after, vehicle_positions=(position, replace(position, vehicle_id="TRAIN2"))
        )
    elif rejected == "wrong_vehicle":
        position.vehicle_id = "TRAIN2"
    elif rejected == "missing_vehicle_id":
        before.vehicle_positions[0].vehicle_id = None
    elif rejected == "wrong_route":
        position.route_id = "OTHER"
    elif rejected == "wrong_service_date":
        position.start_date = "20261005"
    elif rejected == "wrong_stop":
        position.stop_id = "600320"
    elif rejected == "passed_stop":
        position.current_stop_sequence = 13
    elif rejected == "older_fix":
        position.timestamp -= 26
    elif rejected == "same_timestamp":
        position.timestamp -= 25
    elif rejected == "duplicate_update":
        after = replace(
            after,
            trip_updates=TripUpdateRecords(
                after.trip_updates,
                (update, replace(update, vehicle_id="TRAIN2")),
            ),
        )
    elif rejected == "wrong_update_route":
        update.route_id = "OTHER"
    elif rejected == "wrong_update_date":
        update.start_date = "20261005"
    elif rejected == "skipped":
        occurrence.schedule_relationship = STOP_SKIPPED
    elif rejected == "cancelled":
        update.trip_schedule_relationship = TRIP_CANCELED
    elif rejected == "ambiguous_occurrence":
        update.stop_time_updates += (replace(occurrence, stop_sequence=24),)
    elif rejected == "no_occurrence_sequence":
        occurrence.stop_sequence = None
    elif rejected == "wrong_schedule_baseline":
        occurrence.arrival.time -= 30
    elif rejected == "switched_trip":
        position.trip_id += "-different"
        update.trip_id = position.trip_id
        update.stop_time_updates = ()

    prior = evaluate_progress(transfer, planned_at=earlier, now=earlier, feeds=before)
    latest = evaluate_progress(
        transfer,
        planned_at=earlier,
        now=now,
        feeds=after,
        memory=None if rejected == "first_fix" else prior.memory,
    ).progress
    assert not latest.transitions
    if rejected == "skipped":
        assert latest.next_action.skipped
    if rejected == "cancelled":
        assert latest.state == "cancelled"
    if rejected in {
        "wrong_route",
        "wrong_service_date",
        "duplicate_vehicle",
        "stale_fix",
    }:
        assert latest.vehicle_observation is None


def test_alighting_with_repeated_stop_no_data_and_empty_feed(
    transfer: JourneyItinerary,
) -> None:
    """Keep the resolved occurrence and the earlier fix across an empty poll."""
    arrival = datetime(2026, 10, 6, 0, 24, tzinfo=UTC)
    start = arrival - timedelta(seconds=40)
    before = _transfer_feed(transfer, start, stopped=False, index=1)
    (update,) = before.trip_updates.values()
    (visit,) = update.stop_time_updates
    visit.schedule_relationship = STOP_NO_DATA
    update.stop_time_updates += (
        replace(
            visit,
            stop_sequence=24,
            arrival=StopTimeEventRecord(time=int(arrival.timestamp()) + 400, delay=0),
        ),
    )
    prior = evaluate_progress(transfer, planned_at=start, now=start, feeds=before)
    assert prior.progress.next_action.time_source == "scheduled"

    no_feed = evaluate_progress(
        transfer,
        planned_at=start,
        now=start + timedelta(seconds=20),
        memory=prior.memory,
    )
    assert no_feed.progress.vehicle_observation is None

    stopped = _transfer_feed(transfer, arrival, stopped=True, index=1)
    result = evaluate_progress(
        transfer,
        planned_at=start,
        now=arrival,
        feeds=replace(stopped, trip_updates={}),
        memory=no_feed.memory,
    )
    [event] = result.progress.transitions
    assert event.type == "alighting_stop_reached"
    assert event.stop_id == "SI:600089"
    assert event.next_leg_route is None

    retrace = arrival + timedelta(seconds=10)
    before_again = evaluate_progress(
        transfer,
        planned_at=start,
        now=retrace,
        feeds=_transfer_feed(transfer, retrace, stopped=False, index=1),
        memory=result.memory,
    )
    later = arrival + timedelta(seconds=20)
    repeated = evaluate_progress(
        transfer,
        planned_at=start,
        now=later,
        feeds=_transfer_feed(transfer, later, stopped=True, index=1),
        memory=before_again.memory,
    )
    assert repeated.progress.state == "finished"
    assert not repeated.progress.transitions


def test_schedule_only_walk_and_private_endpoints() -> None:
    """A train-walk-train itinerary shows the next boarding without private inputs."""
    plan = JourneyPlanResult.model_validate_json(
        (
            Path(__file__).parent / "fixtures/trip_page/plan_response_trip.json"
        ).read_text()
    )
    raw = plan.itineraries[1].model_copy(deep=True)
    walk = raw.legs[1]
    walk.origin = StopInfo(
        id="A:private",
        name="14 Private Street",
        position=Position(lat=-27.0, lng=153.0),
    )
    walk.destination = None
    snapshot = snapshot_itinerary(raw)
    start = datetime.fromisoformat(walk.departureTimeUtc)
    end = datetime.fromisoformat(walk.arrivalTimeUtc)
    now = start + (end - start) / 2
    result = evaluate_progress(snapshot, planned_at=start, now=now)
    assert result.progress.state == "in_progress"
    assert result.progress.active_leg_index == 1
    assert result.progress.active_leg_source == "schedule"
    assert result.progress.next_action.type == "board"
    assert result.progress.next_action.leg_index == 2
    assert "Private Street" not in snapshot.model_dump_json()
    assert "-27.0" not in snapshot.model_dump_json()
    assert "Private Street" not in result.progress.model_dump_json()


def test_same_vehicle_continuation_skips_transfer_cue(
    transfer: JourneyItinerary,
) -> None:
    """A continuation remains on board and guides alighting at the last leg."""
    transfer.legs[1].sameVehicleContinuation = True
    arrival = datetime(2026, 10, 5, 23, 56, tzinfo=UTC)
    earlier = arrival - timedelta(seconds=25)
    prior = evaluate_progress(
        transfer,
        planned_at=earlier,
        now=earlier,
        feeds=_transfer_feed(transfer, earlier, stopped=False),
    )
    assert prior.progress.next_action.type == "alight"
    assert prior.progress.next_action.leg_index == 1
    result = evaluate_progress(
        transfer,
        planned_at=earlier,
        now=arrival,
        feeds=_transfer_feed(transfer, arrival, stopped=True),
        memory=prior.memory,
    )
    assert not result.progress.transitions


def test_late_final_prediction_defers_finished(transfer: JourneyItinerary) -> None:
    """A matching stop prediction extends the final arrival past the timetable."""
    arrival = datetime(2026, 10, 6, 0, 24, tzinfo=UTC)
    now = arrival + timedelta(minutes=1)
    feeds = _transfer_feed(transfer, now, stopped=False, index=1)
    (update,) = feeds.trip_updates.values()
    (visit,) = update.stop_time_updates
    visit.arrival.time += 120
    visit.arrival.delay = 120
    result = evaluate_progress(
        transfer,
        planned_at=arrival,
        now=now,
        feeds=replace(feeds, vehicle_positions=()),
    )
    assert result.progress.state == "in_progress"
    assert result.progress.active_leg_index == 1
    assert result.progress.active_leg_source == "realtime_schedule"
    assert result.progress.next_action.predicted_time == arrival + timedelta(minutes=2)

    # The last known final-arrival bound still applies during a partial outage.
    missing = evaluate_progress(
        transfer,
        planned_at=arrival,
        now=now,
        memory=result.memory,
    )
    assert missing.progress.state == "in_progress"
    assert missing.final_arrival == result.final_arrival


def test_changed_journey_starts_with_no_previous_vehicle_evidence(
    transfer: JourneyItinerary,
) -> None:
    arrival = datetime(2026, 10, 5, 23, 56, tzinfo=UTC)
    earlier = arrival - timedelta(seconds=25)
    before = evaluate_progress(
        transfer,
        planned_at=earlier,
        now=earlier,
        feeds=_transfer_feed(transfer, earlier, stopped=False),
    )
    transfer.legs[0].departureTimeUtc = "2026-10-05T23:29:00Z"
    result = evaluate_progress(
        transfer,
        planned_at=earlier,
        now=arrival,
        feeds=_transfer_feed(transfer, arrival, stopped=True),
        memory=before.memory,
    )
    assert result.progress.journey_id != before.progress.journey_id
    assert not result.progress.transitions


@pytest.mark.parametrize(
    "malformed", ["empty", "missing_arrival", "overlap", "reversed"]
)
def test_ambiguous_schedule_remains_unknown(
    transfer: JourneyItinerary, malformed: str
) -> None:
    if malformed == "empty":
        transfer.legs.clear()
    elif malformed == "missing_arrival":
        transfer.legs[0].arrivalTimeUtc = None
    elif malformed == "overlap":
        transfer.legs[0].arrivalTimeUtc = "2026-10-06T00:15:00Z"
    elif malformed == "reversed":
        transfer.legs[0].arrivalTimeUtc = "2026-10-05T00:15:00Z"
    now = datetime(2026, 10, 5, 23, 56, tzinfo=UTC)
    result = evaluate_progress(transfer, planned_at=now, now=now)
    assert result.progress.state is None
    assert result.progress.active_leg_source == "unknown"
    assert result.progress.next_action is None


def test_walk_only_journey_has_no_transit_action() -> None:
    itinerary = JourneyItinerary(
        legs=[
            JourneyLeg(
                travelMode="Walk",
                departureTimeUtc="2026-10-05T23:55:00Z",
                arrivalTimeUtc="2026-10-05T23:57:00Z",
            )
        ]
    )
    now = datetime(2026, 10, 5, 23, 56, tzinfo=UTC)
    result = evaluate_progress(itinerary, planned_at=now, now=now)
    assert result.progress.active_leg_index == 0
    assert result.progress.next_action is None


def test_schedule_progress_without_trip_identifier(transfer: JourneyItinerary) -> None:
    """A timetable still supports a cue when vehicle evidence cannot be correlated."""
    transfer.legs[0].tripId = None
    now = datetime(2026, 10, 5, 23, 56, tzinfo=UTC)
    result = evaluate_progress(transfer, planned_at=now, now=now)
    assert result.progress.active_leg_source == "schedule"
    assert result.progress.vehicle_observation is None
    assert result.progress.next_action.type == "transfer"


def test_same_vehicle_sample_remains_visible_without_advancing_evidence(
    transfer: JourneyItinerary,
) -> None:
    """Multiple polls of the same observation never constitute a transition."""
    arrival = datetime(2026, 10, 5, 23, 56, tzinfo=UTC)
    now = arrival - timedelta(seconds=25)
    feeds = _transfer_feed(transfer, now, stopped=False)
    first = evaluate_progress(transfer, planned_at=now, now=now, feeds=feeds)
    second = evaluate_progress(
        transfer,
        planned_at=now,
        now=now + timedelta(seconds=10),
        feeds=feeds,
        memory=first.memory,
    )
    assert second.progress.vehicle_observation == first.progress.vehicle_observation
    assert second.progress.active_leg_source == "vehicle"
    assert not second.progress.transitions
