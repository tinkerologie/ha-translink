"""Unit tests for Translink API client, Protobuf parser, and models."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.translink.api.client import (
    DELAYED_THRESHOLD_MINUTES,
    EARLY_THRESHOLD_MINUTES,
)
from custom_components.translink.api.gtfs_realtime import (
    TripUpdateRecord,
    VehiclePositionRecord,
    _parse_fields,
    _parse_varint,
)
from custom_components.translink.api.models import JourneyLeg, TripTimetable
from custom_components.translink.client import (
    JourneyPlanResult,
    JourneySummary,
    LocationSearchResult,
    TranslinkClient,
    TranslinkConnectionError,
    TranslinkResponseError,
    build_journey_summary,
    calculate_plan_hash,
    parse_alerts,
    parse_iso_datetime,
    parse_trip_updates,
    parse_vehicle_positions,
    redact_sensitive,
)
from custom_components.translink.const import (
    REALTIME_MAX_AGE_SECONDS,
    REALTIME_MAX_FUTURE_SKEW_SECONDS,
)
from tests.test_gtfs_realtime import _encode_field


@pytest.mark.parametrize(
    ("location_id", "kind", "is_board_candidate"),
    [
        ("ST:place_romsta", "station", True),
        ("SI:600036", "stop", True),
        ("PL:parkland", "place", False),
        ("XX:other", "unknown", False),
    ],
)
def test_location_search_result_kind(
    location_id: str, kind: str, is_board_candidate: bool
) -> None:
    """Classify a location without requiring any additional API fields."""
    result = LocationSearchResult(LocationId=location_id, Description="Roma Street")
    assert result.id == location_id
    assert result.name == "Roma Street"
    assert result.kind == kind
    assert result.is_board_candidate is is_board_candidate


def test_calculate_plan_hash() -> None:
    """Test 32-bit signed string hash computation."""
    assert calculate_plan_hash("") == 0
    h1 = calculate_plan_hash("searchDate=2026-10-06&searchTime=9%3A30am")
    assert isinstance(h1, int)
    assert -0x80000000 <= h1 <= 0x7FFFFFFF


DEPARTURE = datetime(2026, 10, 6, 5, tzinfo=UTC)
ARRIVAL = datetime(2026, 10, 6, 5, 20, tzinfo=UTC)
BEFORE_DEPARTURE = datetime(2026, 10, 6, 4, 50, tzinfo=UTC)


@pytest.fixture
def realtime_plan() -> JourneyPlanResult:
    """A single service scheduled from 05:00 to 05:20."""
    return JourneyPlanResult.model_validate(
        {
            "itineraries": [
                {
                    "firstDepartureTimeUtc": DEPARTURE.isoformat(),
                    "lastArrivalTimeUtc": ARRIVAL.isoformat(),
                    "legs": [
                        {
                            "tripId": "trip-1",
                            "travelMode": "Bus",
                            "departureTimeUtc": DEPARTURE.isoformat(),
                            "arrivalTimeUtc": ARRIVAL.isoformat(),
                            "origin": {"id": "123", "name": "Boarding"},
                            "destination": {"id": "456", "name": "Alighting"},
                        }
                    ],
                }
            ]
        }
    )


def _stop_update(
    stop: str,
    *,
    sequence: int = 1,
    event_field: int = 3,
    predicted_time: datetime | None = None,
    delay: int | None = None,
    relationship: int | None = None,
) -> bytes:
    visit = _encode_field(1, 0, sequence) + _encode_field(4, 2, stop)
    if relationship is not None:
        visit += _encode_field(5, 0, relationship)
    event = b""
    if delay is not None:
        event += _encode_field(1, 0, delay)
    if predicted_time is not None:
        event += _encode_field(2, 0, int(predicted_time.timestamp()))
    if event:
        visit += _encode_field(event_field, 2, event)
    return _encode_field(2, 2, visit)


def _trip_entity(
    *visits: bytes,
    trip: str = "trip-1",
    delay: int | None = None,
    timestamp: int | None = None,
    relationship: int | None = None,
) -> bytes:
    descriptor = _encode_field(1, 2, trip)
    if relationship is not None:
        descriptor += _encode_field(4, 0, relationship)
    update = _encode_field(1, 2, descriptor) + b"".join(visits)
    if timestamp is not None:
        update += _encode_field(4, 0, timestamp)
    if delay is not None:
        update += _encode_field(5, 0, delay)
    return _encode_field(
        2, 2, _encode_field(1, 2, f"entity-{trip}") + _encode_field(3, 2, update)
    )


@pytest.mark.parametrize(
    ("delay", "status", "minutes", "realtime_status"),
    [
        (None, "scheduled", None, "unavailable"),
        (0, "on_time", 0, "live"),
        (-120, "early", -2, "live"),
        (EARLY_THRESHOLD_MINUTES * 60, "early", EARLY_THRESHOLD_MINUTES, "live"),
        (DELAYED_THRESHOLD_MINUTES * 60, "delayed", DELAYED_THRESHOLD_MINUTES, "live"),
    ],
)
def test_journey_distinguishes_scheduled_measured_zero_and_early(
    realtime_plan: JourneyPlanResult,
    delay: int | None,
    status: str,
    minutes: int | None,
    realtime_status: str,
) -> None:
    """Only the matched boarding visit can report a measured offset."""
    feed = b""
    if delay is not None:
        feed = _trip_entity(
            _stop_update(
                "SI:00123",
                predicted_time=DEPARTURE + timedelta(seconds=delay),
                delay=delay,
            ),
            _stop_update("999", sequence=2, delay=900),
        )
    summary = build_journey_summary(
        realtime_plan, trip_updates=parse_trip_updates(feed), now=BEFORE_DEPARTURE
    )
    assert (summary.status, summary.delay_mins, summary.realtime_status) == (
        status,
        minutes,
        realtime_status,
    )
    assert summary.departure_time == DEPARTURE
    assert summary.arrival_time == ARRIVAL
    assert summary.departure_delay_seconds == delay


@pytest.mark.parametrize(
    ("trip_age", "feed_age", "status", "used_age"),
    [
        (REALTIME_MAX_AGE_SECONDS + 1, 0, "stale", REALTIME_MAX_AGE_SECONDS + 1),
        (None, REALTIME_MAX_AGE_SECONDS + 1, "stale", REALTIME_MAX_AGE_SECONDS + 1),
        (0, REALTIME_MAX_AGE_SECONDS, "live", REALTIME_MAX_AGE_SECONDS),
        (None, None, "live", None),
        (None, 0, "live", 0),
        (
            -REALTIME_MAX_FUTURE_SKEW_SECONDS,
            REALTIME_MAX_AGE_SECONDS + 1,
            "live",
            -REALTIME_MAX_FUTURE_SKEW_SECONDS,
        ),
        (
            -REALTIME_MAX_FUTURE_SKEW_SECONDS - 1,
            0,
            "stale",
            -REALTIME_MAX_FUTURE_SKEW_SECONDS - 1,
        ),
    ],
)
def test_journey_checks_trip_timestamp_then_feed_timestamp(
    realtime_plan: JourneyPlanResult,
    trip_age: int | None,
    feed_age: int | None,
    status: str,
    used_age: int | None,
) -> None:
    """Ignore stale evidence and permit missing or moderately skewed timestamps."""
    now = int(BEFORE_DEPARTURE.timestamp())
    trip_timestamp = (
        (now - trip_age if trip_age else 0) if trip_age is not None else None
    )
    feed = _trip_entity(delay=180, timestamp=trip_timestamp)
    if feed_age is not None:
        feed = _encode_field(1, 2, _encode_field(3, 0, now - feed_age)) + feed
    summary = build_journey_summary(
        realtime_plan, trip_updates=parse_trip_updates(feed), now=BEFORE_DEPARTURE
    )
    assert summary.realtime_status == status
    assert summary.realtime_updated_at == (
        BEFORE_DEPARTURE - timedelta(seconds=used_age) if used_age is not None else None
    )
    if status == "live":
        assert summary.status == "delayed"
        assert summary.delay_source == "trip"
        assert summary.delay_mins == 3
        assert summary.predicted_departure_time == DEPARTURE + timedelta(minutes=3)
    else:
        assert summary.status == "scheduled"
        assert summary.delay_mins is None
        assert summary.predicted_departure_time is None


@pytest.mark.parametrize(
    ("visits", "status", "realtime_status", "boarding", "alighting_skipped"),
    [
        (
            (_stop_update("123", relationship=1),),
            "boarding_skipped",
            "no_prediction",
            "skipped",
            False,
        ),
        (
            (_stop_update("123", relationship=2),),
            "scheduled",
            "no_data",
            "no_data",
            False,
        ),
        (
            (_stop_update("456", relationship=1),),
            "scheduled",
            "no_prediction",
            None,
            True,
        ),
        (
            (_stop_update("456", relationship=2),),
            "scheduled",
            "no_data",
            None,
            False,
        ),
        ((_stop_update("999", delay=900),), "scheduled", "no_prediction", None, False),
        (
            (
                _stop_update("123", predicted_time=DEPARTURE, delay=0),
                _stop_update(
                    "123",
                    sequence=10,
                    predicted_time=DEPARTURE + timedelta(minutes=20),
                    delay=0,
                ),
            ),
            "scheduled",
            "no_prediction",
            None,
            False,
        ),
        (
            (_stop_update("123", predicted_time=DEPARTURE),),
            "scheduled",
            "no_prediction",
            None,
            False,
        ),
        (
            (_stop_update("123", predicted_time=DEPARTURE, delay=30),),
            "scheduled",
            "no_prediction",
            None,
            False,
        ),
    ],
)
def test_journey_scopes_stop_evidence_to_a_unique_endpoint(
    realtime_plan: JourneyPlanResult,
    visits: tuple[bytes, ...],
    status: str,
    realtime_status: str,
    boarding: str | None,
    alighting_skipped: bool,
) -> None:
    """Skip and no-data apply only to the matching stop visit."""
    feed = _trip_entity(*visits, delay=None if alighting_skipped else 900)
    summary = build_journey_summary(
        realtime_plan, trip_updates=parse_trip_updates(feed), now=BEFORE_DEPARTURE
    )
    assert (summary.status, summary.realtime_status, summary.boarding_relationship) == (
        status,
        realtime_status,
        boarding,
    )
    assert summary.delay_mins is None
    assert summary.alighting_skipped is alighting_skipped


def test_journey_uses_timetable_to_find_visits_and_preceding_no_data(
    realtime_plan: JourneyPlanResult,
) -> None:
    """A preceding timetable visit can suspend timing until a later update."""
    timetable = TripTimetable.model_validate(
        {
            "id": "trip-1",
            "departures": [
                {
                    "stopId": "555",
                    "order": 1,
                    "scheduledDepartureUtc": "2026-10-06T04:40:00Z",
                },
                {
                    "stopId": "123",
                    "order": 2,
                    "scheduledDepartureUtc": "2026-10-06T04:45:00Z",
                },
                {
                    "stopId": "123",
                    "order": 3,
                    "scheduledDepartureUtc": DEPARTURE.isoformat(),
                },
                {
                    "stopId": "456",
                    "order": 4,
                    "scheduledDepartureUtc": ARRIVAL.isoformat(),
                },
            ],
        }
    )
    no_data = _stop_update("555", sequence=1, relationship=2)
    earlier_boarding = _stop_update("123", sequence=2, relationship=2)
    boarding = _stop_update(
        "123", sequence=3, predicted_time=DEPARTURE - timedelta(minutes=2), delay=-120
    )
    for visits, expected, minutes in (
        ((no_data,), "no_data", None),
        ((no_data, earlier_boarding), "no_data", None),
        ((no_data, earlier_boarding, boarding), "live", -2),
        ((_stop_update("999", sequence=1, relationship=2),), "no_prediction", None),
        (
            (no_data, _stop_update("123", sequence=3, delay=60)),
            "no_prediction",
            None,
        ),
        (
            (no_data, _stop_update("456", sequence=4, relationship=2)),
            "no_data",
            None,
        ),
    ):
        summary = build_journey_summary(
            realtime_plan,
            trip_updates=parse_trip_updates(_trip_entity(*visits)),
            now=BEFORE_DEPARTURE,
            trip_timetables={"trip-1": timetable},
        )
        assert summary.realtime_status == expected
        assert summary.delay_mins == minutes


def test_journey_uses_the_endpoint_event_even_when_the_overlay_matched_another_event(
    realtime_plan: JourneyPlanResult,
) -> None:
    """A timetable arrival match cannot supply boarding departure evidence."""
    timetable = TripTimetable.model_validate(
        {
            "id": "trip-1",
            "departures": [
                {
                    "stopId": "123",
                    "order": 1,
                    "scheduledDepartureUtc": DEPARTURE.isoformat(),
                    "canBoardDebark": "Alighting",
                },
                {
                    "stopId": "456",
                    "order": 2,
                    "scheduledDepartureUtc": ARRIVAL.isoformat(),
                },
            ],
        }
    )
    update = _stop_update("123", event_field=2, predicted_time=DEPARTURE, delay=0)
    summary = build_journey_summary(
        realtime_plan,
        trip_updates=parse_trip_updates(_trip_entity(update)),
        now=BEFORE_DEPARTURE,
        trip_timetables={"trip-1": timetable},
    )
    assert summary.delay_mins is None
    assert summary.realtime_status == "no_prediction"
    calling_stop = summary.itinerary_legs[0]["callingStops"][0]
    assert calling_stop["realtime"]["arrivalDelaySeconds"] == 0


@pytest.mark.parametrize(
    ("relationship", "timestamp_age", "status", "cancelled"),
    [
        (3, 0, "cancelled", True),
        (7, 0, "cancelled", True),
        (3, REALTIME_MAX_AGE_SECONDS + 1, "scheduled", False),
    ],
)
def test_journey_reports_cancellation_only_for_an_applicable_trip(
    realtime_plan: JourneyPlanResult,
    relationship: int,
    timestamp_age: int,
    status: str,
    cancelled: bool,
) -> None:
    """A valid cancellation outranks any timing evidence."""
    later_leg = (
        realtime_plan.itineraries[0].legs[0].model_copy(update={"tripId": "trip-2"})
    )
    realtime_plan.itineraries[0].legs.append(later_leg)
    now = int(BEFORE_DEPARTURE.timestamp())
    feed = _trip_entity() + _trip_entity(
        trip="trip-2", relationship=relationship, timestamp=now - timestamp_age
    )
    summary = build_journey_summary(
        realtime_plan, trip_updates=parse_trip_updates(feed), now=BEFORE_DEPARTURE
    )
    assert summary.status == status
    assert summary.itinerary_legs[0]["tripCancelled"] is False
    assert summary.itinerary_legs[1]["tripCancelled"] is cancelled
    assert summary.itinerary_legs[1]["tripScheduleRelationship"] == (
        relationship if cancelled else None
    )
    if not cancelled:
        assert summary.realtime_status == "stale"


@pytest.mark.parametrize(
    ("current_time", "status"),
    [
        (DEPARTURE, "departed"),
        (ARRIVAL + timedelta(minutes=1), "departed"),
        (ARRIVAL + timedelta(minutes=12), "departed"),
        (ARRIVAL + timedelta(minutes=12, seconds=1), "arrived"),
    ],
)
def test_journey_uses_last_transit_arrival_prediction_and_includes_trailing_walk(
    realtime_plan: JourneyPlanResult, current_time: datetime, status: str
) -> None:
    """The alighting prediction offsets the full itinerary arrival."""
    itinerary = realtime_plan.itineraries[0]
    itinerary.lastArrivalTimeUtc = "2026-10-06T05:22:00Z"
    itinerary.legs.extend(
        [
            itinerary.legs[0].model_copy(update={"tripId": "trip-2"}),
            JourneyLeg(travelMode="Walk", durationMins=2),
        ]
    )
    feed = _trip_entity(
        _stop_update("456", event_field=2, predicted_time=ARRIVAL, delay=0)
    )
    feed += _trip_entity(
        _stop_update(
            "456",
            event_field=2,
            predicted_time=ARRIVAL + timedelta(minutes=10),
            delay=600,
        ),
        trip="trip-2",
    )
    summary = build_journey_summary(
        realtime_plan, trip_updates=parse_trip_updates(feed), now=current_time
    )
    assert summary.status == status
    assert summary.arrival_time == ARRIVAL + timedelta(minutes=2)
    assert summary.predicted_arrival_time == ARRIVAL + timedelta(minutes=12)
    assert summary.arrival_delay_seconds == 600


def test_journey_does_not_arrive_before_a_late_predicted_departure(
    realtime_plan: JourneyPlanResult,
) -> None:
    """Departure is an inclusive lower bound even if its prediction is very late."""
    predicted = DEPARTURE + timedelta(minutes=40)
    feed = _trip_entity(_stop_update("123", predicted_time=predicted, delay=2400))
    updates = parse_trip_updates(feed)
    for now, expected in (
        (ARRIVAL + timedelta(minutes=1), "delayed"),
        (predicted, "departed"),
        (predicted + timedelta(seconds=1), "arrived"),
    ):
        summary = build_journey_summary(realtime_plan, trip_updates=updates, now=now)
        assert summary.status == expected
        assert summary.predicted_arrival_time is None


def test_arrival_only_prediction_extends_the_journey(
    realtime_plan: JourneyPlanResult,
) -> None:
    """At 05:21 a 05:30 arrival prediction is still underway."""
    prediction = ARRIVAL + timedelta(minutes=10)
    feed = _trip_entity(
        _stop_update("456", event_field=2, predicted_time=prediction, delay=600)
    )
    summary = build_journey_summary(
        realtime_plan,
        trip_updates=parse_trip_updates(feed),
        now=ARRIVAL + timedelta(minutes=1),
    )
    assert summary.status == "departed"
    assert summary.delay_mins is None
    assert summary.realtime_status == "live"
    assert summary.arrival_time == ARRIVAL
    assert summary.predicted_arrival_time == prediction


def test_parse_iso_datetime() -> None:
    """Test ISO timestamp parsing."""
    assert parse_iso_datetime(None) is None
    assert parse_iso_datetime("") is None
    assert parse_iso_datetime("invalid") is None

    parsed = parse_iso_datetime("2026-10-06T00:24:00Z")
    assert parsed is not None
    assert parsed.year == 2026
    assert parsed.month == 10
    assert parsed.day == 6
    assert parsed.hour == 0
    assert parsed.minute == 24
    assert parsed.tzinfo == UTC


def test_varint_and_fields_parser() -> None:
    """Test low level varint and fields parsing."""
    val, offset = _parse_varint(b"\x01", 0)
    assert val == 1
    assert offset == 1

    # Multiple bytes varint (300 = 0xac 0x02)
    val, offset = _parse_varint(b"\xac\x02", 0)
    assert val == 300
    assert offset == 2

    fields = _parse_fields(b"")
    assert fields == []


def test_parse_vehicle_positions(sample_vehicle_positions_bytes: bytes) -> None:
    """Test parsing GTFS-RT VehiclePositions payload."""
    vp_map = parse_vehicle_positions(sample_vehicle_positions_bytes)
    assert len(vp_map) > 0

    sample_record = next(iter(vp_map.values()))
    assert isinstance(sample_record, VehiclePositionRecord)
    assert sample_record.latitude != 0.0
    assert sample_record.longitude != 0.0
    assert -90.0 <= sample_record.latitude <= 90.0
    assert -180.0 <= sample_record.longitude <= 180.0


def test_parse_trip_updates(sample_trip_updates_bytes: bytes) -> None:
    """Test parsing GTFS-RT TripUpdates payload."""
    tu_map = parse_trip_updates(sample_trip_updates_bytes)
    assert len(tu_map) > 0

    sample_record = next(iter(tu_map.values()))
    assert isinstance(sample_record, TripUpdateRecord)
    assert isinstance(sample_record.delay_seconds, int)


def test_parse_alerts() -> None:
    """Test alerts parser with empty or truncated bytes."""
    alerts = parse_alerts(b"")
    assert alerts == []


def test_build_journey_summary_with_plan(
    plan_response_data: dict[str, Any],
    sample_vehicle_positions_bytes: bytes,
    sample_trip_updates_bytes: bytes,
) -> None:
    """Test build_journey_summary with valid plan fixture and feeds."""
    plan = JourneyPlanResult.model_validate(plan_response_data)
    vp_map = parse_vehicle_positions(sample_vehicle_positions_bytes)
    tu_map = parse_trip_updates(sample_trip_updates_bytes)

    # Test Adult fare preference
    summary = build_journey_summary(
        plan=plan,
        vehicle_positions=vp_map,
        trip_updates=tu_map,
        fare_preference="Adult",
        origin_name_fallback="Central",
        destination_name_fallback="Springfield Central",
        now=datetime(2026, 10, 6, tzinfo=UTC),
    )

    assert isinstance(summary, JourneySummary)
    assert summary.status in ["scheduled", "on_time", "delayed", "departed", "arrived"]
    assert summary.departure_time is not None
    assert summary.arrival_time is not None
    assert summary.duration_mins == 41
    assert summary.transfers == 0
    assert summary.next_service_name == "T2 Springfield Central"
    assert summary.next_service_vehicle == "Train"
    assert summary.origin_platform == "5"
    assert summary.destination_platform == "1"
    assert summary.fare_price == 0.5
    assert summary.fare_currency == "AUD"
    assert len(summary.itinerary_legs) >= 1

    # Test Concession fare preference
    summary_concession = build_journey_summary(
        plan=plan,
        fare_preference="Concession",
        now=datetime(2026, 10, 6, tzinfo=UTC),
    )
    assert summary_concession.fare_price == 0.5


def test_build_journey_summary_empty() -> None:
    """Test build_journey_summary when no itineraries are returned."""
    plan = JourneyPlanResult(itineraries=[])
    summary = build_journey_summary(
        plan=plan,
        origin_name_fallback="Origin",
        destination_name_fallback="Destination",
        now=BEFORE_DEPARTURE,
    )
    assert summary.status == "no_service"
    assert summary.origin_name == "Origin"
    assert summary.destination_name == "Destination"
    assert summary.duration_mins == 0
    assert summary.disruptions_count == 0
    assert summary.disruptions_description == "No active disruptions"
    assert summary.disruptions_summary == "Normal"


def test_build_journey_summary_empty_with_notice() -> None:
    """A closure can explain why the planner returned no services."""
    plan = JourneyPlanResult.model_validate(
        {
            "itineraries": [],
            "notices": [
                {
                    "id": 101,
                    "title": "Line closure",
                    "description": "Buses replace trains.",
                }
            ],
        }
    )

    now = datetime(2026, 10, 6, tzinfo=UTC)
    summary = build_journey_summary(plan, now=now)

    assert summary.status == "no_service"
    assert summary.last_updated == now
    assert summary.itinerary_legs == []
    assert summary.disruptions_count == 1
    assert summary.disruptions_summary == "Line closure"
    assert summary.disruptions_description == "• Line closure: Buses replace trains."
    assert summary.latest_disruption_title == "Line closure"
    assert summary.latest_disruption_description == "Buses replace trains."
    assert summary.disruptions[0]["severity"] == "Informative"
    assert summary.disruptions[0]["leg"] is None
    assert summary.disruptions[0]["route"] is None


def test_build_journey_summary_empty_skips_invalid_notice_ids() -> None:
    """An empty plan does not expose notices without an ID."""
    plan = JourneyPlanResult.model_validate(
        {"notices": [{"id": notice_id} for notice_id in (None, "", " \t")]}
    )

    summary = build_journey_summary(plan)

    assert summary.status == "no_service"
    assert summary.disruptions_count == 0
    assert summary.disruptions_description == "No active disruptions"


def test_redact_sensitive() -> None:
    """Test redaction helper."""
    assert redact_sensitive("abc") == "abc"
    assert redact_sensitive([1, 2, {"k": "v"}]) == [1, 2, {"k": "v"}]


@pytest.mark.asyncio
async def test_search_locations_success() -> None:
    """Test searching locations with successful mock response."""
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(
        return_value=[
            {
                "LocationId": "ST:place_censta",
                "Description": "Central station, Brisbane City",
            }
        ]
    )

    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
    mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_session.closed = False

    client = TranslinkClient(session=mock_session)
    results = await client.search_locations("Central")

    assert len(results) == 1
    assert results[0].LocationId == "ST:place_censta"
    assert results[0].Description == "Central station, Brisbane City"
    assert results[0].id == "ST:place_censta"
    assert results[0].name == "Central station, Brisbane City"

    # Query too short
    empty = await client.search_locations("a")
    assert empty == []


@pytest.mark.asyncio
async def test_search_locations_error() -> None:
    """Test searching locations error handling."""
    mock_response = MagicMock()
    mock_response.status = 500
    mock_response.text = AsyncMock(return_value="<html>Reflected search</html>")
    mock_response.json = AsyncMock(return_value={"error": "Reflected search"})
    mock_response.read = AsyncMock(return_value=b"Reflected search")
    mock_response.content = MagicMock()

    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
    mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_session.closed = False

    client = TranslinkClient(session=mock_session)
    with pytest.raises(
        TranslinkResponseError, match=r"^Location search failed with status 500$"
    ):
        await client.search_locations("Central")
    mock_response.text.assert_not_called()
    mock_response.json.assert_not_called()
    mock_response.read.assert_not_called()
    assert mock_response.content.mock_calls == []


@pytest.mark.asyncio
async def test_plan_journey_success(plan_response_data: dict[str, Any]) -> None:
    """Test plan_journey with mock response."""
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value=plan_response_data)

    mock_session = MagicMock()
    mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_response)
    mock_session.post.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_session.closed = False

    client = TranslinkClient(session=mock_session)
    plan = await client.plan_journey(
        start_location_id="ST:place_censta",
        start_name="Central station",
        end_location_id="ST:place_spcsta",
        end_name="Springfield Central",
    )

    assert len(plan.itineraries) == 2
    assert plan.itineraries[0].durationMins == 41


@pytest.mark.asyncio
async def test_get_stops_by_geolocation() -> None:
    """Test get_stops_by_geolocation with mock response."""
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(
        return_value=[{"id": "SI:123", "description": "Stop 1"}]
    )

    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
    mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_session.closed = False

    client = TranslinkClient(session=mock_session)
    stops = await client.get_stops_by_geolocation(-27.46, 153.02)
    assert len(stops) == 1
    assert stops[0]["id"] == "SI:123"


@pytest.mark.asyncio
async def test_client_close() -> None:
    """Test client close behaviour."""
    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.close = AsyncMock()

    client = TranslinkClient()
    client._session = mock_session
    client._owns_session = True
    await client.close()
    mock_session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_vehicle_positions(sample_vehicle_positions_bytes: bytes) -> None:
    """Test fetch_vehicle_positions with mock HTTP response."""
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read = AsyncMock(return_value=sample_vehicle_positions_bytes)

    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
    mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_session.closed = False

    client = TranslinkClient(session=mock_session)
    vp = await client.fetch_vehicle_positions()
    assert len(vp) > 0
    first_rec = next(iter(vp.values()))
    assert first_rec.timestamp is not None


@pytest.mark.asyncio
async def test_fetch_trip_updates(sample_trip_updates_bytes: bytes) -> None:
    """Test fetch_trip_updates with mock HTTP response."""
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read = AsyncMock(return_value=sample_trip_updates_bytes)

    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
    mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_session.closed = False

    client = TranslinkClient(session=mock_session)
    tu = await client.fetch_trip_updates()
    assert len(tu) > 0


@pytest.mark.asyncio
async def test_fetch_alerts() -> None:
    """Test fetch_alerts with mock HTTP response."""
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read = AsyncMock(return_value=b"")

    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
    mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_session.closed = False

    client = TranslinkClient(session=mock_session)
    alerts = await client.fetch_alerts()
    assert alerts == []


def test_build_journey_summary_with_delay_and_vehicle(
    plan_response_data: dict[str, Any],
) -> None:
    """Test build_journey_summary with correlated trip update and vehicle position."""
    from datetime import datetime, timedelta

    from custom_components.translink.api.gtfs_realtime import (
        TripUpdateRecord,
        VehiclePositionRecord,
    )

    plan = JourneyPlanResult.model_validate(plan_response_data)
    first_trip_id = plan.itineraries[0].legs[0].tripId
    assert first_trip_id is not None

    trip_updates = {
        first_trip_id: TripUpdateRecord(
            entity_id="tu_1",
            trip_id=first_trip_id,
            route_id="RPSP",
            trip_delay_seconds=300,
        )
    }
    vehicle_positions = {
        first_trip_id: VehiclePositionRecord(
            entity_id="vp_1",
            vehicle_id="VEH_42",
            vehicle_label="42",
            trip_id=first_trip_id,
            route_id="RPSP",
            latitude=-27.465,
            longitude=153.028,
            bearing=180.0,
            speed=15.0,
        )
    }

    # Test future departure with delay -> status "delayed"
    future_now = datetime(2026, 10, 5, 23, 0, 0, tzinfo=UTC)
    summary = build_journey_summary(
        plan,
        trip_updates=trip_updates,
        vehicle_positions=vehicle_positions,
        now=future_now,
    )
    assert summary.delay_mins == 5
    assert summary.status == "delayed"
    assert summary.vehicle_id == "VEH_42"
    assert summary.vehicle_latitude == -27.465
    assert summary.vehicle_bearing == 180.0
    assert summary.vehicle_speed == 15.0
    assert summary.vehicle_tracked is True

    # Test departed status
    dep_time = summary.departure_time
    arr_time = summary.arrival_time
    assert dep_time is not None and arr_time is not None
    mid_now = dep_time + timedelta(minutes=5)
    summary_departed = build_journey_summary(plan, now=mid_now)
    assert summary_departed.status == "departed"

    # Test arrived status
    after_arr_now = arr_time + timedelta(minutes=5)
    summary_arrived = build_journey_summary(plan, now=after_arr_now)
    assert summary_arrived.status == "arrived"


def test_build_journey_summary_with_base_trip_id_correlation(
    plan_response_data: dict[str, Any],
) -> None:
    """Test correlation succeeds when GTFS-RT feed uses normalized base trip ID."""
    from custom_components.translink.api.client import _match_trip_record
    from custom_components.translink.api.gtfs_realtime import (
        TripUpdateRecord,
        VehiclePositionRecord,
    )

    # Test _match_trip_record edge cases
    assert _match_trip_record(None, {"123": "val"}) is None
    assert _match_trip_record("123", None) is None
    assert _match_trip_record("123", {}) is None
    assert _match_trip_record("123", {"123": "matched"}) == "matched"
    assert (
        _match_trip_record("s_T_SPRP_9_20261008_39040630", {"39040630": "matched"})
        == "matched"
    )
    assert _match_trip_record("unmatched_trip", {"other": "val"}) is None

    # Test route_id validation in _match_trip_record
    rec_with_route = TripUpdateRecord(
        entity_id="tu1", trip_id="39040630", route_id="SPRP"
    )
    rec_no_route = TripUpdateRecord(entity_id="tu2", trip_id="39040630", route_id=None)
    # Expected route matches
    assert (
        _match_trip_record(
            "s_T_SPRP_9_20261008_39040630",
            {"39040630": rec_with_route},
            expected_route_id="SPRP",
        )
        is rec_with_route
    )
    # Expected route does not match
    assert (
        _match_trip_record(
            "s_T_SPRP_9_20261008_39040630",
            {"39040630": rec_with_route},
            expected_route_id="OTHER_ROUTE",
        )
        is None
    )
    # Record has no route_id (passes through)
    assert (
        _match_trip_record(
            "s_T_SPRP_9_20261008_39040630",
            {"39040630": rec_no_route},
            expected_route_id="SPRP",
        )
        is rec_no_route
    )
    # No expected_route_id provided (passes through)
    assert (
        _match_trip_record(
            "s_T_SPRP_9_20261008_39040630",
            {"39040630": rec_with_route},
            expected_route_id=None,
        )
        is rec_with_route
    )

    plan = JourneyPlanResult.model_validate(plan_response_data)
    first_leg = plan.itineraries[0].legs[0]
    assert first_leg.legRoute is not None
    first_leg.tripId = "s_T_SPRP_9_20261008_39040630"
    first_leg.legRoute.code = "SPRP"

    trip_updates = {
        "39040630": TripUpdateRecord(
            entity_id="tu_base",
            trip_id="39040630-QR 26_27-44171-DY37",
            route_id="SPRP",
            trip_delay_seconds=180,
        )
    }
    vehicle_positions = {
        "39040630": VehiclePositionRecord(
            entity_id="vp_base",
            vehicle_id="DY37",
            vehicle_label="DY37",
            trip_id="39040630-QR 26_27-44171-DY37",
            route_id="SPRP",
            latitude=-27.4663,
            longitude=153.0228,
            speed=18.5,
            bearing=90.0,
        )
    }

    summary = build_journey_summary(
        plan,
        trip_updates=trip_updates,
        vehicle_positions=vehicle_positions,
        now=BEFORE_DEPARTURE,
    )
    assert summary.delay_mins == 3
    assert summary.vehicle_id == "DY37"
    assert summary.vehicle_label == "DY37"
    assert summary.vehicle_latitude == -27.4663
    assert summary.vehicle_longitude == 153.0228
    assert summary.vehicle_tracked is True

    # Test route mismatch in build_journey_summary
    first_leg.legRoute.code = "DIFFERENT_ROUTE"
    summary_mismatch = build_journey_summary(
        plan,
        trip_updates=trip_updates,
        vehicle_positions=vehicle_positions,
        now=BEFORE_DEPARTURE,
    )
    assert summary_mismatch.delay_mins is None
    assert summary_mismatch.vehicle_tracked is False


@pytest.mark.asyncio
async def test_client_own_session_lifecycle() -> None:
    """Test client handles creating its own session and closing cleanly."""
    client = TranslinkClient()
    session = await client._get_session()
    assert not session.closed
    await client.close()
    assert client._session is None


@pytest.mark.asyncio
async def test_search_locations_short_query_and_errors() -> None:
    """Test short queries, non-list responses, and client errors in search_locations."""
    import aiohttp

    client = TranslinkClient()
    assert await client.search_locations("a") == []
    assert await client.search_locations("") == []

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"error": "none"})
    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_session.closed = False
    c = TranslinkClient(session=mock_session)
    assert await c.search_locations("Central") == []

    mock_session.get.side_effect = aiohttp.ClientError("Conn error")
    with pytest.raises(TranslinkConnectionError):
        await c.search_locations("Central")


@pytest.mark.asyncio
async def test_get_stops_by_geolocation_errors() -> None:
    """Test non-200 responses, non-list payloads, and ClientError in get_stops_by_geolocation."""
    import aiohttp

    mock_resp = MagicMock()
    mock_resp.status = 500
    mock_resp.text = AsyncMock(return_value="<html>Reflected coordinates</html>")
    mock_resp.json = AsyncMock(return_value={"error": "Reflected coordinates"})
    mock_resp.read = AsyncMock(return_value=b"Reflected coordinates")
    mock_resp.content = MagicMock()
    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_session.closed = False
    c = TranslinkClient(session=mock_session)

    with pytest.raises(
        TranslinkResponseError,
        match=r"^Geolocation stop search failed with status 500$",
    ):
        await c.get_stops_by_geolocation(-27.46, 153.02)
    mock_resp.text.assert_not_called()
    mock_resp.json.assert_not_called()
    mock_resp.read.assert_not_called()
    assert mock_resp.content.mock_calls == []

    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"not": "a list"})
    assert await c.get_stops_by_geolocation(-27.46, 153.02) == []

    mock_session.get.side_effect = aiohttp.ClientError("Conn error")
    with pytest.raises(TranslinkConnectionError):
        await c.get_stops_by_geolocation(-27.46, 153.02)


@pytest.mark.asyncio
async def test_plan_journey_errors() -> None:
    """Test plan_journey error branches."""
    import aiohttp

    mock_resp = MagicMock()
    mock_resp.status = 400
    mock_resp.text = AsyncMock(return_value="<html>Reflected journey</html>")
    mock_resp.json = AsyncMock(return_value={"error": "Reflected journey"})
    mock_resp.read = AsyncMock(return_value=b"Reflected journey")
    mock_resp.content = MagicMock()
    mock_session = MagicMock()
    mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_session.post.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_session.closed = False
    c = TranslinkClient(session=mock_session)

    with pytest.raises(
        TranslinkResponseError, match=r"^Journey planner failed with status 400$"
    ):
        await c.plan_journey("S1", "Start", "S2", "End")
    mock_resp.text.assert_not_called()
    mock_resp.json.assert_not_called()
    mock_resp.read.assert_not_called()
    assert mock_resp.content.mock_calls == []

    mock_session.post.side_effect = aiohttp.ClientError("Conn timeout")
    with pytest.raises(TranslinkConnectionError):
        await c.plan_journey("S1", "Start", "S2", "End")


@pytest.mark.asyncio
async def test_gtfs_fetch_errors_and_non_200() -> None:
    """Test GTFS feeds error handling on non-200 and ClientError."""
    import aiohttp

    mock_resp = MagicMock()
    mock_resp.status = 503
    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_session.closed = False
    c = TranslinkClient(session=mock_session)

    assert await c.fetch_vehicle_positions() == {}
    assert await c.fetch_trip_updates() == {}
    assert await c.fetch_alerts() == []

    mock_session.get.side_effect = aiohttp.ClientError("Network drop")
    assert await c.fetch_vehicle_positions() == {}
    assert await c.fetch_trip_updates() == {}
    assert await c.fetch_alerts() == []


def test_build_journey_summary_edge_cases(plan_response_data: dict[str, Any]) -> None:
    """Test scheduled status, walk-only trip, concession fare, and fallback."""
    from datetime import timedelta

    plan = JourneyPlanResult.model_validate(plan_response_data)
    dep_time = parse_iso_datetime(plan.itineraries[0].firstDepartureTimeUtc)
    assert dep_time is not None
    before_dep = dep_time - timedelta(minutes=10)

    summary_scheduled = build_journey_summary(plan, now=before_dep)
    assert summary_scheduled.status == "scheduled"

    # Walk-only itinerary
    walk_plan_data = {
        "itineraries": [
            {
                "durationMins": 10,
                "firstDepartureTimeUtc": "2026-10-06T00:00:00Z",
                "lastArrivalTimeUtc": "2026-10-06T00:10:00Z",
                "legs": [
                    {
                        "travelMode": "Walk",
                        "durationMins": 10,
                        "distanceM": 800,
                        "origin": {
                            "name": "Start Point",
                            "position": {"lat": -27.46, "lng": 153.02},
                        },
                        "destination": {"name": "End Point"},
                        "notices": [],
                    }
                ],
                "fares": [{"name": "Special Fare", "type": "Other", "price": 4.50}],
            }
        ]
    }
    walk_plan = JourneyPlanResult.model_validate(walk_plan_data)
    walk_summary = build_journey_summary(
        walk_plan, fare_preference="Adult", now=before_dep
    )
    assert walk_summary.next_service_name == "Walk"
    assert walk_summary.fare_price == 4.50
    assert walk_summary.vehicle_latitude == -27.46
    assert walk_summary.vehicle_longitude == 153.02

    # Concession fare
    concession_summary = build_journey_summary(
        plan, fare_preference="Concession", now=before_dep
    )
    assert concession_summary.fare_price == 0.50

    # No legs plan
    no_legs_plan = JourneyPlanResult.model_validate(
        {"itineraries": [{"durationMins": 0, "legs": []}]}
    )
    no_legs_sum = build_journey_summary(no_legs_plan, now=BEFORE_DEPARTURE)
    assert no_legs_sum.transfers == 0

    # Plan with legs having no origin, destination, or departure time
    no_dep_plan = JourneyPlanResult.model_validate(
        {
            "itineraries": [
                {
                    "durationMins": 10,
                    "legs": [
                        {
                            "travelMode": "Bus",
                            "durationMins": 10,
                            "distanceM": 1000,
                            "origin": None,
                            "destination": None,
                            "notices": [],
                        }
                    ],
                }
            ]
        }
    )
    no_dep_sum = build_journey_summary(no_dep_plan, now=BEFORE_DEPARTURE)
    assert no_dep_sum.status == "scheduled"


@pytest.mark.asyncio
async def test_client_close_unowned_session() -> None:
    """Test client close does nothing when session is not owned."""
    mock_session = MagicMock(closed=False)
    c = TranslinkClient(session=mock_session)
    await c.close()
    mock_session.close.assert_not_called()


@pytest.mark.asyncio
async def test_search_locations_validation_error() -> None:
    """Test search_locations wraps ValidationError in TranslinkResponseError."""
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value=[{"InvalidKey": "InvalidVal"}])

    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
    mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_session.closed = False

    client = TranslinkClient(session=mock_session)
    with pytest.raises(
        TranslinkResponseError, match="Failed to parse location search response"
    ):
        await client.search_locations("Central")


@pytest.mark.asyncio
async def test_plan_journey_validation_error() -> None:
    """Test plan_journey wraps ValidationError in TranslinkResponseError."""
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"itineraries": "invalid_not_a_list"})

    mock_session = MagicMock()
    mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_response)
    mock_session.post.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_session.closed = False

    client = TranslinkClient(session=mock_session)
    with pytest.raises(
        TranslinkResponseError, match="Failed to parse journey planner response"
    ):
        await client.plan_journey(
            start_location_id="ST:1",
            start_name="Start",
            end_location_id="ST:2",
            end_name="End",
        )


def test_build_journey_summary_disruptions_enriched() -> None:
    """Test disruption notice resolution with PlanNotice matching and formatted descriptions."""
    plan_data = {
        "itineraries": [
            {
                "durationMins": 30,
                "legs": [
                    {
                        "travelMode": "Train",
                        "durationMins": 30,
                        "distanceM": 15000,
                        "notices": [
                            {"id": 101, "severity": "Major"},
                            {"id": 102, "severity": "Informative"},
                            {"id": None, "severity": "Minor"},
                        ],
                    }
                ],
            }
        ],
        "notices": [
            {
                "id": 101,
                "title": "Trackwork",
                "description": "Buses replace trains.",
                "cause": "MAINTENANCE",
                "effect": "NO_SERVICE",
                "startsUtc": "2026-10-06T00:00:00Z",
                "endsUtc": "2026-10-06T12:00:00Z",
            },
            {
                "id": 102,
                "title": "Delays Expected",
                "description": None,
                "cause": "WEATHER",
                "effect": "SIGNIFICANT_DELAYS",
            },
        ],
    }
    plan = JourneyPlanResult.model_validate(plan_data)
    summary = build_journey_summary(plan, now=datetime(2026, 10, 6, tzinfo=UTC))

    assert summary.disruptions_count == 2
    assert summary.disruptions_summary == "Trackwork; Delays Expected"
    assert "• Trackwork: Buses replace trains." in summary.disruptions_description
    assert "Delays Expected" in summary.disruptions_description
    assert summary.latest_disruption_title == "Trackwork"
    assert summary.latest_disruption_description == "Buses replace trains."


def test_build_journey_summary_top_level_notices_fallback() -> None:
    """Test top-level plan notices fallback when itinerary legs have no notices."""
    plan_data = {
        "itineraries": [
            {
                "durationMins": 20,
                "legs": [
                    {
                        "travelMode": "Bus",
                        "durationMins": 20,
                        "distanceM": 5000,
                        "notices": [],
                    }
                ],
            }
        ],
        "notices": [
            {
                "id": 201,
                "title": "General Alert",
                "description": "Service adjustments across the network.",
                "cause": "OTHER_CAUSE",
                "effect": "MODIFIED_SERVICE",
            },
            {
                "id": None,
                "title": "Unnamed Notice",
            },
        ],
    }
    plan = JourneyPlanResult.model_validate(plan_data)
    summary = build_journey_summary(plan, now=datetime(2026, 10, 6, tzinfo=UTC))

    assert summary.disruptions_count == 1
    assert summary.disruptions[0]["title"] == "General Alert"
    assert summary.disruptions_summary == "General Alert"
    assert summary.latest_disruption_title == "General Alert"


@pytest.mark.parametrize("leg_referenced", [False, True])
def test_build_journey_summary_filters_expired_winning_notice(
    leg_referenced: bool,
) -> None:
    """Use first fallback detail or last referenced detail before testing expiry."""
    expired = {
        "id": "101",
        "title": "Trackwork",
        "endsUtc": "2026-10-06T09:59:59+10:00",
    }
    active = {"id": 101, "title": "Duplicate notice", "endsUtc": "2026-10-06T12:00:00Z"}
    unrelated = {"id": 102, "title": "Unreferenced notice"}
    plan = JourneyPlanResult.model_validate(
        {
            "itineraries": [{"legs": [{"notices": [{"id": 101}]}]}]
            if leg_referenced
            else [],
            "notices": [active, expired, unrelated]
            if leg_referenced
            else [expired, active, unrelated],
        }
    )

    summary = build_journey_summary(plan, now=datetime(2026, 10, 6, tzinfo=UTC))

    assert [notice["id"] for notice in summary.disruptions] == (
        [] if leg_referenced else [102]
    )


@pytest.mark.parametrize(
    ("starts_utc", "ends_utc"),
    [
        ("2026-10-07T00:00:00Z", "2026-10-08T00:00:00Z"),
        (None, "2026-10-06T00:00:00Z"),
        (None, "not a date"),
        (None, "2026-10-05T23:59:59"),
        (None, None),
    ],
    ids=["future", "inclusive-end", "malformed-end", "naive-end", "missing-end"],
)
def test_build_journey_summary_preserves_current_or_unknown_notice_dates(
    starts_utc: str | None, ends_utc: str | None
) -> None:
    """Keep future notices and notices that cannot be confirmed as expired."""
    plan = JourneyPlanResult.model_validate(
        {"notices": [{"id": 101, "startsUtc": starts_utc, "endsUtc": ends_utc}]}
    )

    summary = build_journey_summary(plan, now=datetime(2026, 10, 6, tzinfo=UTC))

    assert summary.disruptions_count == 1
    assert summary.disruptions[0]["starts_utc"] == starts_utc
    assert summary.disruptions[0]["ends_utc"] == ends_utc


def test_build_journey_summary_scopes_notices_to_usable_leg_references() -> None:
    """Match equivalent IDs, deduplicate references and keep missing details."""
    plan = JourneyPlanResult.model_validate(
        {
            "itineraries": [
                {
                    "legs": [
                        {
                            "travelMode": "Train",
                            "notices": [
                                {"id": 101, "severity": "Major"},
                                {"id": " \t"},
                            ],
                        },
                        {
                            "travelMode": "Bus",
                            "notices": [{"id": "101"}, {"id": 102}],
                        },
                    ]
                }
            ],
            "notices": [
                {"id": "101", "title": "Earlier detail"},
                {"id": "101", "title": "Line closure"},
                {"id": 103, "title": "Unreferenced notice"},
            ],
        }
    )

    summary = build_journey_summary(plan)

    assert [notice["id"] for notice in summary.disruptions] == [101, 102]
    referenced, missing_detail = summary.disruptions
    assert referenced["title"] == "Line closure"
    assert referenced["severity"] == "Major"
    assert referenced["leg"] == "Train"
    assert missing_detail["title"] is None
    assert missing_detail["leg"] == "Bus"


@pytest.mark.asyncio
@pytest.mark.parametrize("where", ["call", "enter"])
async def test_required_requests_convert_timeouts(where: str) -> None:
    """A bare timeout, at call time or while reading the response, is a connection error."""
    mock_session = MagicMock()
    mock_session.closed = False
    for method in (mock_session.get, mock_session.post):
        if where == "call":
            method.side_effect = TimeoutError()
        else:
            method.return_value.__aenter__ = AsyncMock(side_effect=TimeoutError())
            method.return_value.__aexit__ = AsyncMock(return_value=None)
    c = TranslinkClient(session=mock_session)

    calls = [
        (c.plan_journey("S1", "Start", "S2", "End"), "journey planner"),
        (c.search_locations("Central"), "location search"),
        (c.get_stops_by_geolocation(-27.46, 153.02), "geolocation stop search"),
    ]
    for call, label in calls:
        with pytest.raises(TranslinkConnectionError) as exc_info:
            await call
        assert str(exc_info.value) == f"Timed out connecting to Translink {label}"
        assert isinstance(exc_info.value.__cause__, TimeoutError)


@pytest.mark.asyncio
async def test_plan_journey_propagates_cancellation() -> None:
    """Cancellation is never converted into a Translink error."""
    import asyncio

    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.post.return_value.__aenter__ = AsyncMock(
        side_effect=asyncio.CancelledError()
    )
    mock_session.post.return_value.__aexit__ = AsyncMock(return_value=None)
    c = TranslinkClient(session=mock_session)

    with pytest.raises(asyncio.CancelledError):
        await c.plan_journey("S1", "Start", "S2", "End")


@pytest.mark.asyncio
@pytest.mark.parametrize("where", ["call", "enter"])
async def test_gtfs_feeds_degrade_on_timeout(where: str) -> None:
    """Optional realtime feeds return their empty fallback on a timeout."""
    mock_session = MagicMock()
    mock_session.closed = False
    if where == "call":
        mock_session.get.side_effect = TimeoutError()
    else:
        mock_session.get.return_value.__aenter__ = AsyncMock(side_effect=TimeoutError())
        mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)
    c = TranslinkClient(session=mock_session)

    assert await c.fetch_vehicle_positions() == {}
    assert await c.fetch_trip_updates() == {}
    assert await c.fetch_alerts() == []
