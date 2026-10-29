"""Unit tests for Translink API client, Protobuf parser, and models."""

from __future__ import annotations

from datetime import UTC
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.translink.api.gtfs_realtime import (
    TripUpdateRecord,
    VehiclePositionRecord,
    _parse_fields,
    _parse_varint,
)
from custom_components.translink.client import (
    JourneyPlanResult,
    JourneySummary,
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


def test_calculate_plan_hash() -> None:
    """Test 32-bit signed string hash computation."""
    assert calculate_plan_hash("") == 0
    h1 = calculate_plan_hash("searchDate=2026-10-06&searchTime=9%3A30am")
    assert isinstance(h1, int)
    assert -0x80000000 <= h1 <= 0x7FFFFFFF


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
    )
    assert summary_concession.fare_price == 0.5


def test_build_journey_summary_empty() -> None:
    """Test build_journey_summary when no itineraries are returned."""
    plan = JourneyPlanResult(itineraries=[])
    summary = build_journey_summary(
        plan=plan,
        origin_name_fallback="Origin",
        destination_name_fallback="Destination",
    )
    assert summary.status == "no_service"
    assert summary.origin_name == "Origin"
    assert summary.destination_name == "Destination"
    assert summary.duration_mins == 0


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
    mock_response.text = AsyncMock(return_value="Server error")

    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
    mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_session.closed = False

    client = TranslinkClient(session=mock_session)
    with pytest.raises(TranslinkResponseError):
        await client.search_locations("Central")


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
            delay_seconds=300,
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
            delay_seconds=180,
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
    )
    assert summary_mismatch.delay_mins == 0
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
    mock_resp.text = AsyncMock(return_value="Server error")
    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_session.closed = False
    c = TranslinkClient(session=mock_session)

    with pytest.raises(TranslinkResponseError):
        await c.get_stops_by_geolocation(-27.46, 153.02)

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
    mock_resp.text = AsyncMock(return_value="Bad Request")
    mock_session = MagicMock()
    mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_session.post.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_session.closed = False
    c = TranslinkClient(session=mock_session)

    with pytest.raises(TranslinkResponseError):
        await c.plan_journey("S1", "Start", "S2", "End")

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
    """Test on_time status, walk-only trip, concession fare, and platform coords fallback."""
    from datetime import timedelta

    plan = JourneyPlanResult.model_validate(plan_response_data)
    dep_time = parse_iso_datetime(plan.itineraries[0].firstDepartureTimeUtc)
    assert dep_time is not None
    before_dep = dep_time - timedelta(minutes=10)

    summary_on_time = build_journey_summary(plan, now=before_dep)
    assert summary_on_time.status == "on_time"

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
    no_legs_sum = build_journey_summary(no_legs_plan)
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
    no_dep_sum = build_journey_summary(no_dep_plan)
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
    summary = build_journey_summary(plan)

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
    summary = build_journey_summary(plan)

    assert summary.disruptions_count == 1
    assert summary.disruptions[0]["title"] == "General Alert"
    assert summary.disruptions_summary == "General Alert"
    assert summary.latest_disruption_title == "General Alert"


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
