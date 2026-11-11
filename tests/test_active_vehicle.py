"""Tests for active vehicle selection through the journey summary."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.translink.api.client import (
    VEHICLE_POSITION_MAX_AGE_SECONDS,
    VEHICLE_POSITION_MAX_FUTURE_SKEW_SECONDS,
)
from custom_components.translink.client import (
    JourneyPlanResult,
    VehiclePositionRecord,
    build_journey_summary,
    parse_trip_updates,
)
from tests.test_client import _stop_update, _trip_entity

FIRST_TRIP = "s_B_100_1_20261006_2001"
SECOND_TRIP = "s_T_FERN_1_20261006_2002"


def journey_time(hour: int, minute: int) -> datetime:
    return datetime(2026, 10, 6, hour, minute, tzinfo=UTC)


@pytest.fixture
def transfer_plan() -> JourneyPlanResult:
    """Bus, walking transfer and a train with independent routes and times."""
    return JourneyPlanResult.model_validate(
        {
            "itineraries": [
                {
                    "firstDepartureTimeUtc": journey_time(5, 0).isoformat(),
                    "lastArrivalTimeUtc": journey_time(6, 0).isoformat(),
                    "legs": [
                        {
                            "tripId": FIRST_TRIP,
                            "travelMode": "Bus",
                            "departureTimeUtc": journey_time(5, 0).isoformat(),
                            "arrivalTimeUtc": journey_time(5, 25).isoformat(),
                            "origin": {
                                "id": "123",
                                "position": {"lat": -27.4, "lng": 153.0},
                            },
                            "destination": {"id": "456"},
                            "legRoute": {
                                "name": "Route 100",
                                "code": "100",
                                "vehicle": "Bus",
                            },
                        },
                        {"travelMode": "Walk"},
                        {
                            "tripId": SECOND_TRIP,
                            "travelMode": "Train",
                            "departureTimeUtc": journey_time(5, 35).isoformat(),
                            "arrivalTimeUtc": journey_time(6, 0).isoformat(),
                            "legRoute": {
                                "name": "Ferny Grove",
                                "code": "FERN",
                                "vehicle": "Train",
                                "hexColorCode": "#223344",
                            },
                        },
                    ],
                },
            ],
        }
    )


def position(trip: str, route: str, time: datetime) -> VehiclePositionRecord:
    return VehiclePositionRecord(
        entity_id=f"entity-{route}",
        vehicle_id=f"vehicle-{route}",
        vehicle_label=route,
        trip_id=trip,
        route_id=route,
        latitude=-27.6,
        longitude=153.2,
        timestamp=int(time.timestamp()),
    )


def test_transfer_tracks_second_leg_and_keeps_first_service(
    transfer_plan: JourneyPlanResult,
) -> None:
    """At 05:40 the train fix wins and the bus still describes first service."""
    now = journey_time(5, 40)
    old_bus = replace(position(FIRST_TRIP, "100", journey_time(5, 15)), latitude=-27.9)
    train = position("2002-QR", "FERN-rail", journey_time(5, 39))
    boarding = parse_trip_updates(
        _trip_entity(trip=FIRST_TRIP, delay=180, timestamp=int(now.timestamp()))
    )
    summary = build_journey_summary(transfer_plan, (old_bus, train), boarding, now=now)
    assert summary.active_leg_index == 2
    assert summary.active_trip_id == SECOND_TRIP
    assert summary.active_route_name == "Ferny Grove"
    assert summary.active_route_code == "FERN"
    assert summary.active_route_color == "#223344"
    assert summary.active_vehicle_type == "Train"
    assert summary.vehicle_position_status == "live"
    assert summary.vehicle_position_timestamp == "2026-10-06T05:39:00+00:00"
    assert summary.vehicle_latitude == -27.6
    assert summary.vehicle_longitude == 153.2
    assert summary.vehicle_tracked is True
    assert summary.next_service_name == "Route 100"
    assert summary.next_service_route_code == "100"
    assert summary.next_service_vehicle == "Bus"
    assert summary.trip_id == FIRST_TRIP
    assert summary.departure_time == journey_time(5, 0)
    assert summary.arrival_time == journey_time(6, 0)
    assert summary.delay_mins == 3
    assert summary.status == "departed"


@pytest.mark.parametrize(
    ("hour", "minute", "index"),
    [(4, 55, 0), (5, 10, 0), (5, 25, 0), (5, 30, 2), (6, 1, None)],
)
def test_active_leg_boundaries(
    transfer_plan: JourneyPlanResult, hour: int, minute: int, index: int | None
) -> None:
    summary = build_journey_summary(transfer_plan, now=journey_time(hour, minute))
    assert summary.active_leg_index == index
    assert summary.vehicle_position_status == (
        "no_active_leg" if index is None else "no_position"
    )
    assert summary.vehicle_latitude is None
    assert summary.vehicle_longitude is None


@pytest.mark.parametrize("fresh", [True, False])
def test_applicable_alighting_prediction_extends_first_leg(
    transfer_plan: JourneyPlanResult, fresh: bool
) -> None:
    from custom_components.translink.const import REALTIME_MAX_AGE_SECONDS

    now = journey_time(5, 30)
    updated_at = int(now.timestamp()) - (0 if fresh else REALTIME_MAX_AGE_SECONDS + 1)
    updates = parse_trip_updates(
        _trip_entity(
            _stop_update(
                "456", event_field=2, predicted_time=journey_time(5, 32), delay=420
            ),
            trip=FIRST_TRIP,
            timestamp=updated_at,
        )
    )
    summary = build_journey_summary(transfer_plan, trip_updates=updates, now=now)
    assert summary.active_leg_index == (0 if fresh else 2)


def test_unknown_arrival_keeps_first_leg_active(
    transfer_plan: JourneyPlanResult,
) -> None:
    transfer_plan.itineraries[0].legs[0].arrivalTimeUtc = None
    summary = build_journey_summary(transfer_plan, now=journey_time(5, 40))
    assert summary.active_leg_index == 0


def test_live_bus_follows_boarding_then_loses_its_fix(
    transfer_plan: JourneyPlanResult,
) -> None:
    now = journey_time(5, 10)
    bus = position(FIRST_TRIP, "100", now)
    assert (
        build_journey_summary(transfer_plan, (bus,), now=now).vehicle_id
        == bus.vehicle_id
    )
    later = now + timedelta(seconds=VEHICLE_POSITION_MAX_AGE_SECONDS + 1)
    summary = build_journey_summary(transfer_plan, (bus,), now=later)
    assert summary.active_leg_index == 0
    assert summary.vehicle_position_status == "stale"
    assert summary.vehicle_latitude is None


@pytest.mark.parametrize(
    ("offset", "status"),
    [
        (-VEHICLE_POSITION_MAX_AGE_SECONDS, "live"),
        (-VEHICLE_POSITION_MAX_AGE_SECONDS - 1, "stale"),
        (VEHICLE_POSITION_MAX_FUTURE_SKEW_SECONDS, "live"),
        (VEHICLE_POSITION_MAX_FUTURE_SKEW_SECONDS + 1, "stale"),
        (None, "stale"),
    ],
)
def test_position_timestamp_policy(
    transfer_plan: JourneyPlanResult, offset: int | None, status: str
) -> None:
    now = journey_time(5, 10)
    bus = replace(
        position(FIRST_TRIP, "100", now),
        timestamp=None if offset is None else int(now.timestamp()) + offset,
    )
    summary = build_journey_summary(transfer_plan, (bus,), now=now)
    assert summary.vehicle_position_status == status
    assert summary.vehicle_tracked is (status == "live")
    assert summary.vehicle_latitude == (-27.6 if status == "live" else None)


@pytest.mark.parametrize("reason", ["route", "service_date", "alias"])
def test_reject_conflicting_service_context(
    transfer_plan: JourneyPlanResult, reason: str
) -> None:
    now = journey_time(5, 10)
    bus = position(FIRST_TRIP, "100", now)
    if reason == "route":
        bus = replace(bus, route_id="200-local")
    elif reason == "service_date":
        bus = replace(bus, start_date="20261005")
    else:
        bus = replace(bus, trip_id=None, vehicle_id=FIRST_TRIP)

    summary = build_journey_summary(transfer_plan, {FIRST_TRIP: bus}, now=now)
    assert summary.vehicle_position_status == "no_position"
    assert summary.vehicle_latitude is None


def test_only_one_distinct_fresh_vehicle_can_be_live(
    transfer_plan: JourneyPlanResult,
) -> None:
    now = journey_time(5, 10)
    bus = replace(position(FIRST_TRIP, "100", now), start_date="20261006")
    duplicate = replace(
        bus, entity_id="alternate-entity", timestamp=int(now.timestamp()) - 1
    )
    other = replace(bus, vehicle_id=None, entity_id="second-vehicle")
    live = build_journey_summary(
        transfer_plan,
        {"trip": bus, "entity": duplicate, "vehicle": bus},
        now=now,
    )
    assert live.vehicle_position_status == "live"
    assert live.vehicle_position_timestamp == now.isoformat()
    ambiguous = build_journey_summary(transfer_plan, (bus, other), now=now)
    assert ambiguous.vehicle_position_status == "ambiguous"
    assert ambiguous.vehicle_id is None
    assert ambiguous.vehicle_latitude is None
    no_vehicle_id = build_journey_summary(transfer_plan, (other,), now=now)
    assert no_vehicle_id.vehicle_id == "second-vehicle"


def test_anonymous_records_cannot_hide_an_ambiguous_position(
    transfer_plan: JourneyPlanResult,
) -> None:
    now = journey_time(5, 10)
    first = replace(position(FIRST_TRIP, "100", now), vehicle_id=None, entity_id="")
    second = replace(first, latitude=-27.2)
    summary = build_journey_summary(transfer_plan, (first, second), now=now)
    assert summary.vehicle_position_status == "ambiguous"
    assert summary.vehicle_latitude is None
