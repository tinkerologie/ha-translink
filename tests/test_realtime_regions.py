"""Tests for the regional realtime feeds and journey enrichment."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.translink.api.gtfs_realtime import (
    StopTimeEventRecord,
    StopTimeUpdateRecord,
    TripUpdateRecord,
    VehiclePositionRecord,
)
from custom_components.translink.client import (
    JourneyPlanResult,
    TranslinkClient,
    build_journey_summary,
)
from tests.test_client import _stop_update
from tests.test_gtfs_realtime import _encode_field

CNS_DEPARTURE = datetime(2026, 10, 6, 5, tzinfo=UTC)
CNS_ARRIVAL = CNS_DEPARTURE + timedelta(minutes=20)
CNS_NOW = CNS_DEPARTURE - timedelta(minutes=5)
CNS_TRIP = "s_C_C110_0_20261006_38292621"
CNS_FEED_TRIP = "38292621-2026-CNS"


@pytest.fixture
def cairns_plan() -> JourneyPlanResult:
    """Synthetic service using observed Cairns ID formats and route prefix."""
    return JourneyPlanResult.model_validate(
        {
            "itineraries": [
                {
                    "firstDepartureTimeUtc": CNS_DEPARTURE.isoformat(),
                    "lastArrivalTimeUtc": CNS_ARRIVAL.isoformat(),
                    "legs": [
                        {
                            "tripId": CNS_TRIP,
                            "travelMode": "Bus",
                            "legRoute": {
                                "code": "110",
                                "regionName": "Cairns",
                                "regionId": "C",
                            },
                            "departureTimeUtc": CNS_DEPARTURE.isoformat(),
                            "arrivalTimeUtc": CNS_ARRIVAL.isoformat(),
                            "origin": {
                                "id": "SI:750441",
                                "name": "Cairns City station",
                            },
                            "destination": {
                                "id": "SI:750360",
                                "name": "James Cook University",
                            },
                        }
                    ],
                }
            ],
        }
    )


@pytest.fixture
def cairns_update() -> TripUpdateRecord:
    """Include different delays at boarding and alighting."""
    return TripUpdateRecord(
        entity_id="synthetic-cns-update",
        trip_id=CNS_FEED_TRIP,
        route_id="C110-33",
        start_date="20261006",
        delay_seconds=480,
        timestamp=int(CNS_NOW.timestamp()),
        vehicle_id="cns-bus-1",
        stop_time_updates=(
            StopTimeUpdateRecord(
                stop_id="00750441",
                stop_sequence=1,
                departure=StopTimeEventRecord(
                    delay=182,
                    time=int(CNS_DEPARTURE.timestamp()) + 182,
                ),
            ),
            StopTimeUpdateRecord(
                stop_id="750360",
                stop_sequence=2,
                arrival=StopTimeEventRecord(
                    delay=480,
                    time=int(CNS_ARRIVAL.timestamp()) + 480,
                ),
            ),
        ),
    )


@pytest.fixture
def cairns_position() -> VehiclePositionRecord:
    """The vehicle feed omits a service date and shares the full update trip ID."""
    return VehiclePositionRecord(
        entity_id="synthetic-cns-position",
        trip_id=CNS_FEED_TRIP,
        route_id="C110-33",
        vehicle_id="cns-bus-1",
        vehicle_label=None,
        latitude=-16.92,
        longitude=145.77,
        timestamp=int(CNS_NOW.timestamp()),
    )


def test_cairns_journey_uses_validated_boarding_visit_and_position(
    cairns_plan: JourneyPlanResult,
    cairns_update: TripUpdateRecord,
    cairns_position: VehiclePositionRecord,
) -> None:
    """Delay comes from the Cairns boarding visit and position from the same trip."""
    summary = build_journey_summary(
        cairns_plan,
        trip_updates={"38292621": cairns_update},
        vehicle_positions=(cairns_position,),
        realtime_region="CNS",
        now=CNS_NOW,
    )
    assert summary.departure_delay_seconds == 182
    assert summary.arrival_delay_seconds == 480
    assert summary.delay_mins == 3
    assert summary.itinerary_legs[0]["callingStopsSource"] == "realtime_partial"
    assert summary.vehicle_position_status == "live"
    assert summary.vehicle_position_timestamp == CNS_NOW.isoformat()
    assert summary.vehicle_id == "cns-bus-1"


@pytest.mark.parametrize(
    ("route_id", "service_date", "expected_status"),
    [
        ("C112-33", None, "no_position"),
        ("C", None, "no_position"),
        ("C110-33", "20261005", "no_position"),
        (None, None, "live"),
    ],
)
def test_cairns_vehicle_rejects_contradictory_optional_identity(
    cairns_plan: JourneyPlanResult,
    cairns_update: TripUpdateRecord,
    cairns_position: VehiclePositionRecord,
    route_id: str | None,
    service_date: str | None,
    expected_status: str,
) -> None:
    """An exact vehicle trip still has to agree with explicit route and date."""
    summary = build_journey_summary(
        cairns_plan,
        trip_updates={"38292621": cairns_update},
        vehicle_positions=(
            replace(cairns_position, route_id=route_id, start_date=service_date),
        ),
        realtime_region="CNS",
        now=CNS_NOW,
    )
    assert summary.departure_delay_seconds == 182
    assert summary.vehicle_position_status == expected_status
    assert summary.vehicle_tracked is (expected_status == "live")


@pytest.fixture
def feed_session() -> MagicMock:
    """Serve an empty protobuf message over the public client transport."""
    session = MagicMock(closed=False)
    response = session.get.return_value.__aenter__.return_value
    response.status = 200
    response.read = AsyncMock(return_value=b"")
    return session


@pytest.mark.parametrize(
    ("region", "expected_paths"),
    [
        ("CNS", ["VehiclePositions", "TripUpdates", "Alerts"]),
        ("SEQ", ["VehiclePositions", "TripUpdates", "Alerts"]),
        ("none", []),
        ("unknown", []),
    ],
)
async def test_realtime_client_requests_only_allowlisted_feeds(
    feed_session: MagicMock, region: str, expected_paths: list[str]
) -> None:
    """Select all three feed URLs from the entry's allowlisted region."""
    client = TranslinkClient(session=feed_session)
    assert await client.fetch_vehicle_positions(region) == ()
    assert await client.fetch_trip_updates(region) == {}
    assert await client.fetch_alerts(region) == []
    assert [call.args[0] for call in feed_session.get.call_args_list] == [
        f"https://gtfsrt.api.translink.com.au/api/realtime/{region}/{path}"
        for path in expected_paths
    ]


def _cairns_trip_payload(
    header_timestamp: int | None,
    record_timestamp: int | None,
) -> bytes:
    header = _encode_field(1, 2, "2.0")
    if header_timestamp is not None:
        header += _encode_field(3, 0, header_timestamp)
    descriptor = (
        _encode_field(1, 2, CNS_FEED_TRIP)
        + _encode_field(3, 2, "20261006")
        + _encode_field(5, 2, "C110-33")
    )
    update = (
        _encode_field(1, 2, descriptor)
        + _stop_update(
            "750441",
            delay=182,
            predicted_time=CNS_DEPARTURE + timedelta(seconds=182),
        )
        + _encode_field(
            3, 2, _encode_field(1, 2, "cns-bus-1") + _encode_field(2, 2, "Cairns bus")
        )
    )
    if record_timestamp is not None:
        update += _encode_field(4, 0, record_timestamp)
    entity = _encode_field(1, 2, "cns-update") + _encode_field(3, 2, update)
    return _encode_field(1, 2, header) + _encode_field(2, 2, entity)


@pytest.mark.parametrize(
    ("header_age", "record_age", "expected_status", "evidence_age"),
    [
        (300, None, "live", 300),
        (-60, None, "live", -60),
        (0, 301, "stale", 301),
        (0, -61, "stale", -61),
        (301, 0, "stale", 301),
        (-61, 0, "stale", -61),
        (None, 0, "unavailable", None),
    ],
)
async def test_cairns_feed_freshness_preserves_stale_journey_evidence(
    feed_session: MagicMock,
    cairns_plan: JourneyPlanResult,
    header_age: int | None,
    record_age: int | None,
    expected_status: str,
    evidence_age: int | None,
) -> None:
    """Only fresh, timestamped feeds enrich the journey; old feeds leave provenance."""
    now_timestamp = int(CNS_NOW.timestamp())
    feed_session.get.return_value.__aenter__.return_value.read.return_value = (
        _cairns_trip_payload(
            now_timestamp - header_age if header_age is not None else None,
            now_timestamp - record_age if record_age is not None else None,
        )
    )
    client = TranslinkClient(session=feed_session, now=lambda: CNS_NOW)
    current = await client.fetch_trip_updates("CNS")
    evidence = await client.fetch_trip_updates("CNS", preserve_stale=True)
    summary = build_journey_summary(
        cairns_plan, trip_updates=evidence, realtime_region="CNS", now=CNS_NOW
    )

    assert bool(current) is (expected_status == "live")
    assert summary.realtime_status == expected_status
    if evidence_age is not None:
        assert summary.realtime_updated_at == CNS_NOW - timedelta(seconds=evidence_age)
        assert evidence["38292621"].vehicle_id == "cns-bus-1"
    if expected_status == "live":
        assert summary.departure_delay_seconds == 182
    else:
        assert summary.departure_delay_seconds is None
        assert summary.predicted_departure_time is None
        assert summary.itinerary_legs[0]["callingStopsSource"] == "unavailable"


@pytest.mark.parametrize("trailer", [b"\x12\x09a", b"\x12\x03\x1a\x07a"])
async def test_malformed_realtime_feed_discards_partial_records(
    feed_session: MagicMock,
    trailer: bytes,
) -> None:
    """A timestamped but truncated feed cannot surface its earlier complete records."""
    payload = _cairns_trip_payload(int(CNS_NOW.timestamp()), None)
    feed_session.get.return_value.__aenter__.return_value.read.return_value = (
        payload + trailer
    )
    client = TranslinkClient(session=feed_session, now=lambda: CNS_NOW)
    assert await client.fetch_trip_updates("CNS", preserve_stale=True) == {}


@pytest.mark.parametrize(
    "failure",
    [
        "missing_trip",
        "wrong_trip",
        "missing_route",
        "wrong_route",
        "missing_date",
        "wrong_date",
        "missing_origin",
        "wrong_stop",
        "duplicate_stop",
        "departure_baseline",
        "arrival_baseline",
        "missing_planner_route",
        "missing_planner_date",
        "malformed_planner_date",
    ],
)
def test_cairns_rejects_unproven_journey_identity_even_on_exact_alias(
    cairns_plan: JourneyPlanResult,
    cairns_update: TripUpdateRecord,
    cairns_position: VehiclePositionRecord,
    failure: str,
) -> None:
    """An exact lookup alias cannot bypass Cairns identity checks."""
    leg = cairns_plan.itineraries[0].legs[0]
    origin = cairns_update.stop_time_updates[0]
    if failure in ("missing_trip", "wrong_trip"):
        cairns_update.trip_id = None if failure == "missing_trip" else "928612-CNS"
    elif failure in ("missing_route", "wrong_route"):
        cairns_update.route_id = None if failure == "missing_route" else "C111-33"
    elif failure in ("missing_date", "wrong_date"):
        cairns_update.start_date = None if failure == "missing_date" else "20261007"
    elif failure == "missing_origin":
        leg.origin = None
    elif failure == "wrong_stop":
        origin.stop_id = "750442"
    elif failure == "duplicate_stop":
        cairns_update.stop_time_updates += (replace(origin, stop_sequence=3),)
    elif failure == "departure_baseline":
        origin.departure = StopTimeEventRecord(
            delay=182, time=int(CNS_DEPARTURE.timestamp())
        )
    elif failure == "arrival_baseline":
        origin.departure = None
        origin.arrival = StopTimeEventRecord(
            delay=182, time=int(CNS_DEPARTURE.timestamp())
        )
    elif failure == "missing_planner_route":
        leg.legRoute.code = None
    elif failure == "missing_planner_date":
        leg.tripId = "38292621"
    elif failure == "malformed_planner_date":
        leg.tripId = CNS_TRIP.replace("20261006", "202610XX")

    summary = build_journey_summary(
        cairns_plan,
        trip_updates={leg.tripId: cairns_update},
        vehicle_positions=(cairns_position,),
        realtime_region="CNS",
        now=CNS_NOW,
    )
    assert summary.realtime_status == "unavailable"
    assert summary.delay_mins is None
    assert summary.itinerary_legs[0]["callingStopsSource"] == "unavailable"
    assert summary.vehicle_position_status == "no_position"
    assert not summary.vehicle_tracked


@pytest.mark.parametrize(
    ("position_changes", "update_vehicle", "status"),
    [
        ({"trip_id": "38292621-other-CNS"}, "cns-bus-1", "no_position"),
        ({"vehicle_id": "other-bus"}, "cns-bus-1", "no_position"),
        ({}, None, "live"),
        ({"vehicle_id": None}, "cns-bus-1", "live"),
        ({"timestamp": int(CNS_NOW.timestamp()) - 91}, "cns-bus-1", "stale"),
    ],
)
def test_cairns_vehicle_requires_shared_full_trip_and_compatible_vehicle_id(
    cairns_plan: JourneyPlanResult,
    cairns_update: TripUpdateRecord,
    cairns_position: VehiclePositionRecord,
    position_changes: dict,
    update_vehicle: str | None,
    status: str,
) -> None:
    """CNS fixes inherit identity from the validated update and still age as fixes."""
    summary = build_journey_summary(
        cairns_plan,
        trip_updates={"38292621": replace(cairns_update, vehicle_id=update_vehicle)},
        vehicle_positions=(replace(cairns_position, **position_changes),),
        realtime_region="CNS",
        now=CNS_NOW,
    )
    assert summary.departure_delay_seconds == 182
    assert summary.vehicle_position_status == status
    assert summary.vehicle_tracked is (status == "live")


@pytest.mark.parametrize(
    ("region", "confirmed", "region_id", "region_name", "enriched"),
    [
        ("SEQ", False, "T", None, True),
        ("SEQ", False, None, "SEQ", True),
        ("SEQ", False, None, None, False),
        ("SEQ", True, None, None, True),
        ("SEQ", True, "C", "Cairns", False),
        ("SEQ", True, "T", "Cairns", False),
        ("CNS", True, "T", "SEQ", False),
        ("CNS", True, None, None, True),
        ("none", True, "T", "SEQ", False),
        ("unknown", False, "T", "SEQ", False),
    ],
)
def test_realtime_region_guard_applies_to_updates_and_positions(
    cairns_plan: JourneyPlanResult,
    cairns_update: TripUpdateRecord,
    cairns_position: VehiclePositionRecord,
    region: str,
    confirmed: bool,
    region_id: str | None,
    region_name: str | None,
    enriched: bool,
) -> None:
    """A syntactically matching record still needs an eligible leg region."""
    leg = cairns_plan.itineraries[0].legs[0]
    leg.legRoute.regionId = region_id
    leg.legRoute.regionName = region_name
    if region != "CNS":
        cairns_position.route_id = cairns_update.route_id = "110-33"
    summary = build_journey_summary(
        cairns_plan,
        trip_updates={"38292621": cairns_update},
        vehicle_positions=(cairns_position,),
        realtime_region=region,
        region_confirmed=confirmed,
        now=CNS_NOW,
    )
    assert (summary.departure_delay_seconds == 182) is enriched
    assert summary.vehicle_tracked is enriched


def test_mixed_region_journey_applies_cairns_data_only_to_cairns_leg(
    cairns_plan: JourneyPlanResult,
    cairns_update: TripUpdateRecord,
    cairns_position: VehiclePositionRecord,
) -> None:
    """Match each leg independently, including when a feed alias is reused."""
    itinerary = cairns_plan.itineraries[0]
    cairns_leg = itinerary.legs[0]
    seq_leg = cairns_leg.model_copy(deep=True)
    seq_leg.legRoute.regionId = "T"
    seq_leg.legRoute.regionName = "SEQ"
    itinerary.legs.insert(0, seq_leg)
    summary = build_journey_summary(
        cairns_plan,
        trip_updates={"38292621": cairns_update},
        vehicle_positions=(cairns_position,),
        realtime_region="CNS",
        now=CNS_NOW,
    )
    assert summary.itinerary_legs[0]["callingStopsSource"] == "unavailable"
    assert summary.itinerary_legs[1]["callingStopsSource"] == "realtime_partial"
    assert summary.departure_delay_seconds is None
    assert summary.arrival_delay_seconds == 480
    assert not summary.vehicle_tracked


def _cairns_position_payload(timestamp: int | None) -> bytes:
    trip = _encode_field(1, 2, CNS_FEED_TRIP)
    coordinates = _encode_field(1, 5, -16.92) + _encode_field(2, 5, 145.77)
    vehicle = _encode_field(1, 2, trip) + _encode_field(2, 2, coordinates)
    if timestamp is not None:
        vehicle += _encode_field(5, 0, timestamp)
    return _encode_field(2, 2, _encode_field(4, 2, vehicle))


@pytest.mark.parametrize(
    ("header_age", "record_age", "position_count", "alerts_count"),
    [
        (0, 0, 1, 1),
        (0, 301, 0, 1),
        (0, -61, 0, 1),
        (0, None, 1, 1),
        (301, 0, 0, 0),
        (-61, 0, 0, 0),
        (None, 0, 0, 0),
    ],
)
async def test_cairns_positions_and_alerts_require_fresh_feed(
    feed_session: MagicMock,
    header_age: int | None,
    record_age: int | None,
    position_count: int,
    alerts_count: int,
) -> None:
    """Keep actual fix timestamps while validating both optional feed headers."""
    now = int(CNS_NOW.timestamp())
    header = _encode_field(1, 2, "2.0")
    if header_age is not None:
        header += _encode_field(3, 0, now - header_age)
    position = _cairns_position_payload(
        now - record_age if record_age is not None else None
    )
    alert_text = _encode_field(1, 2, _encode_field(1, 2, "Cairns alert"))
    alert = _encode_field(2, 2, _encode_field(5, 2, _encode_field(10, 2, alert_text)))
    reader = feed_session.get.return_value.__aenter__.return_value.read
    reader.side_effect = [
        _encode_field(1, 2, header) + entity for entity in (position, alert)
    ]
    client = TranslinkClient(session=feed_session, now=lambda: CNS_NOW)

    positions = await client.fetch_vehicle_positions("CNS")
    assert len(positions) == position_count
    if positions:
        assert positions[0].timestamp == (
            now - record_age if record_age is not None else None
        )
    alerts = await client.fetch_alerts("CNS")
    assert len(alerts) == alerts_count
    if alerts:
        assert alerts[0].header_text == "Cairns alert"


@pytest.mark.parametrize(
    "mode", ["confirmed", "wrong_region", "missing_boarding", "wrong_vehicle"]
)
def test_cairns_progress_uses_the_same_regional_identity_guard(
    cairns_plan: JourneyPlanResult,
    cairns_update: TripUpdateRecord,
    cairns_position: VehiclePositionRecord,
    mode: str,
) -> None:
    from custom_components.translink.api.progress import (
        ProgressFeeds,
        evaluate_progress,
        snapshot_itinerary,
    )

    itinerary = cairns_plan.itineraries[0]
    itinerary.legs[0].origin.stopType = "Bus"
    itinerary.legs[0].destination.stopType = "Bus"
    itinerary = snapshot_itinerary(itinerary)
    later = CNS_ARRIVAL + timedelta(minutes=8)
    earlier = later - timedelta(seconds=25)
    cairns_update.timestamp = int(earlier.timestamp())
    cairns_position.timestamp = int(earlier.timestamp())
    cairns_position.current_stop_sequence = 1
    cairns_position.current_status = "IN_TRANSIT_TO"
    cairns_position.stop_id = "750441"
    feeds = ProgressFeeds(
        trip_updates={CNS_FEED_TRIP: cairns_update},
        vehicle_positions=(cairns_position,),
        realtime_region="SEQ" if mode == "wrong_region" else "CNS",
    )
    before = evaluate_progress(itinerary, planned_at=earlier, now=earlier, feeds=feeds)
    cairns_update.timestamp = int(later.timestamp())
    cairns_position.timestamp = int(later.timestamp())
    cairns_position.current_stop_sequence = 2
    cairns_position.current_status = "STOPPED_AT"
    cairns_position.stop_id = "750360"
    if mode == "missing_boarding":
        cairns_update.stop_time_updates = cairns_update.stop_time_updates[1:]
    elif mode == "wrong_vehicle":
        cairns_position.vehicle_id = "cns-bus-2"
    after = evaluate_progress(
        itinerary, planned_at=earlier, now=later, feeds=feeds, memory=before.memory
    ).progress
    if mode == "confirmed":
        assert [event.type for event in after.transitions] == ["alighting_stop_reached"]
        assert after.vehicle_observation.stop_name == "James Cook University"
    else:
        assert not after.transitions
        assert after.vehicle_observation is None
