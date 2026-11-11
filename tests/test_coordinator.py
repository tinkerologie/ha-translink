"""Tests for Translink coordinator."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant.common import MockConfigEntry

from custom_components.translink.api.models import StopTimetable
from custom_components.translink.client import (
    JourneyPlanResult,
    JourneySummary,
    StopSummary,
    TranslinkConnectionError,
)
from custom_components.translink.const import (
    CONF_END_LOCATION_ID,
    CONF_END_NAME,
    CONF_MODE,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    CONF_START_LOCATION_ID,
    CONF_START_NAME,
    CONF_STOP_LOCATION_ID,
    CONF_STOP_NAME,
    CONF_TRANSPORT_MODES,
    DOMAIN,
    MODE_JOURNEY,
    MODE_STOP,
)
from custom_components.translink.coordinator import TranslinkCoordinator


@pytest.fixture(autouse=True)
def mock_optional_trip_pages():
    """Existing coordinator cases isolate transport; cache cases override this mock."""
    with patch(
        "custom_components.translink.coordinator.TranslinkClient.async_get_trip_timetable",
        new_callable=AsyncMock,
        return_value=None,
    ):
        yield


@pytest.fixture
def journey_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Fixture for a journey config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_journey_1",
        data={
            CONF_MODE: MODE_JOURNEY,
            CONF_NAME: "Commute",
            CONF_START_LOCATION_ID: "ST:place_censta",
            CONF_START_NAME: "Central station",
            CONF_END_LOCATION_ID: "ST:place_spcsta",
            CONF_END_NAME: "Springfield Central",
            CONF_SCAN_INTERVAL: 60,
        },
        options={},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def stop_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Fixture for a stop config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_stop_1",
        data={
            CONF_MODE: MODE_STOP,
            CONF_NAME: "Roma Street",
            CONF_STOP_LOCATION_ID: "ST:place_romsta",
            CONF_STOP_NAME: "Roma Street station",
            CONF_SCAN_INTERVAL: 90,
        },
        options={},
    )
    entry.add_to_hass(hass)
    return entry


async def test_coordinator_init_journey(
    hass: HomeAssistant, journey_entry: MockConfigEntry
) -> None:
    """Test coordinator initialization for Journey mode."""
    with patch("custom_components.translink.coordinator.async_get_clientsession"):
        coordinator = TranslinkCoordinator(hass, journey_entry)

    assert coordinator.mode == MODE_JOURNEY
    assert coordinator.start_location_id == "ST:place_censta"
    assert coordinator.end_location_id == "ST:place_spcsta"
    assert coordinator.update_interval == timedelta(seconds=60)
    assert coordinator.track_vehicle is True


async def test_coordinator_init_stop(
    hass: HomeAssistant, stop_entry: MockConfigEntry
) -> None:
    """Test coordinator initialization for Stop mode."""
    with patch("custom_components.translink.coordinator.async_get_clientsession"):
        coordinator = TranslinkCoordinator(hass, stop_entry)

    assert coordinator.mode == MODE_STOP
    assert coordinator.update_interval == timedelta(seconds=90)


async def test_coordinator_update_journey_success(
    hass: HomeAssistant,
    journey_entry: MockConfigEntry,
    plan_response_data: dict[str, Any],
) -> None:
    """Test coordinator _async_update_journey successfully parses and caches data."""
    plan_result = JourneyPlanResult.model_validate(plan_response_data)

    with patch("custom_components.translink.coordinator.async_get_clientsession"):
        coordinator = TranslinkCoordinator(hass, journey_entry)

    coordinator.client.plan_journey = AsyncMock(return_value=plan_result)
    coordinator.client.fetch_vehicle_positions = AsyncMock(return_value=())
    coordinator.client.fetch_trip_updates = AsyncMock(return_value={})

    summary = await coordinator._async_update_data()
    assert isinstance(summary, JourneySummary)
    assert summary.status in ["scheduled", "on_time", "delayed", "departed", "arrived"]
    assert summary.duration_mins == 41


async def test_coordinator_stop_timetable_keeps_distinct_boardable_visits(
    hass: HomeAssistant, stop_entry: MockConfigEntry, stop_timetable_fixture
) -> None:
    """Use only the chosen timetable and keep real visits across directions."""
    coordinator = TranslinkCoordinator(hass, stop_entry)
    coordinator.client.fetch_stop_timetable = AsyncMock(
        return_value=StopTimetable.model_validate(stop_timetable_fixture("hub"))
    )
    coordinator.client.plan_journey = AsyncMock()
    coordinator.client.fetch_trip_updates = AsyncMock()

    await coordinator.async_refresh()

    assert coordinator.last_update_success
    coordinator.client.fetch_stop_timetable.assert_awaited_once_with("ST:place_romsta")
    coordinator.client.plan_journey.assert_not_called()
    coordinator.client.fetch_trip_updates.assert_not_called()
    summary = coordinator.data
    assert isinstance(summary, StopSummary)
    assert (summary.stop_id, summary.stop_name) == (
        "ST:place_romsta",
        "Roma Street station",
    )
    assert [row["trip_id"] for row in summary.departures] == [
        "cancelled",
        "skipped",
        "loop",
        "loop",
        "loop",
        "inbound",
        "bus",
        "unresolved",
    ]
    assert len({row["visit_id"] for row in summary.departures}) == 8
    cancelled, skipped, source, target, repeated, inbound, bus, unresolved = (
        summary.departures
    )
    assert cancelled["is_cancelled"] is True
    assert skipped["is_skipped"] is True
    assert source == {
        "route": "Harbour Loop",
        "vehicle": "Train",
        "headsign": "Harbour Terminus",
        "departure_time": "2099-01-01T02:10:00Z",
        "platform": "1",
        "trip_id": "loop",
        "visit_id": source["visit_id"],
        "route_id": "T:Train:LOOP",
        "direction": "Outbound",
        "boarding": "Both",
        "scheduled_departure_time": "2099-01-01T02:10:00Z",
        "expected_departure_time": "2099-01-01T02:13:30Z",
        "time_source": "realtime",
        "is_cancelled": False,
        "is_skipped": False,
        "is_extra": True,
        "platform_change": {"platform": "2", "old_platform": "1", "is_source": True},
        "route_color": "#abcdef",
    }
    assert target["platform"] == "2"
    assert target["platform_change"]["is_source"] is False
    assert target["is_extra"] is None
    assert repeated["platform"] == "3"
    assert repeated["scheduled_departure_time"] == "2099-01-01T02:12:00Z"
    assert repeated["time_source"] == "scheduled"
    assert repeated["expected_departure_time"] is None
    assert repeated["is_extra"] is None
    assert inbound["direction"] == "Inbound"
    assert inbound["route"] == "City Loop"
    assert bus["route"] == "42"
    assert bus["vehicle"] == "Bus"
    assert unresolved["vehicle"] is None
    assert unresolved["boarding"] == "Other"

    first, repeat = summary.arrivals
    assert [row["trip_id"] for row in summary.arrivals] == ["alighting", "alighting"]
    assert first["visit_id"] != repeat["visit_id"]
    assert [row["boarding"] for row in summary.arrivals] == ["Alighting", "Alighting"]
    assert (first["route_id"], first["direction"], first["platform"]) == (
        "T:Train:LOOP",
        "Outbound",
        "1",
    )
    assert first["scheduled_departure_time"] == "2099-01-01T02:02:00Z"
    assert first["expected_departure_time"] is None
    assert (repeat["route_id"], repeat["direction"], repeat["platform"]) == (
        "T:Train:LOOP",
        "Inbound",
        "2",
    )
    assert repeat["scheduled_departure_time"] == "2099-01-01T02:05:00Z"
    assert repeat["expected_departure_time"] == "2099-01-01T02:07:00Z"
    assert repeat["is_skipped"] is True

    assert summary.next_departure_time == datetime(2099, 1, 1, 2, 10, tzinfo=UTC)
    assert (summary.next_route, summary.next_vehicle, summary.next_platform) == (
        "Harbour Loop",
        "Train",
        "1",
    )
    assert summary.next_headsign == "Harbour Terminus"
    assert summary.delay_mins == 4
    assert summary.departure_delay_seconds == 210
    assert summary.predicted_departure_time == datetime(
        2099, 1, 1, 2, 13, 30, tzinfo=UTC
    )
    assert summary.realtime_status == "live"
    assert summary.delay_source == "stop_event"


@pytest.mark.parametrize("delay_seconds", [None, -120, 180, 0])
async def test_stop_summary_uses_the_selected_visits_signed_prediction(
    hass: HomeAssistant,
    stop_entry: MockConfigEntry,
    stop_timetable_fixture,
    delay_seconds: int | None,
) -> None:
    """Check stale visits are skipped and prediction provenance survives."""
    now = datetime.now(UTC).replace(microsecond=0)
    scheduled = now + timedelta(minutes=4 if delay_seconds != 180 else -1)
    expected = (
        scheduled + timedelta(seconds=delay_seconds)
        if delay_seconds is not None
        else None
    )
    board = stop_timetable_fixture("hub")
    board["departures"] = [
        {
            "id": "past",
            "scheduledDepartureUtc": (now - timedelta(minutes=5)).isoformat(),
        },
        {
            "id": "next",
            "routeId": "T:Bus:42",
            "scheduledDepartureUtc": scheduled.isoformat(),
            "realtime": {"expectedDepartureUtc": expected.isoformat()}
            if expected
            else None,
        },
    ]
    coordinator = TranslinkCoordinator(hass, stop_entry)
    coordinator.client.fetch_stop_timetable = AsyncMock(
        return_value=StopTimetable.model_validate(board)
    )
    await coordinator.async_refresh()
    summary = coordinator.data
    assert isinstance(summary, StopSummary)
    assert summary.next_route == "42"
    assert summary.next_departure_time == scheduled
    assert summary.predicted_departure_time == expected
    assert summary.departure_delay_seconds == delay_seconds
    assert summary.delay_mins == {None: None, -120: -2, 180: 3, 0: 0}[delay_seconds]
    assert summary.realtime_status == (
        "unavailable" if delay_seconds is None else "live"
    )
    assert summary.delay_source == (None if delay_seconds is None else "stop_event")
    assert summary.realtime_updated_at is None


async def test_stop_board_keeps_unresolved_modes_and_incomplete_visit_ids(
    hass: HomeAssistant, stop_entry: MockConfigEntry, stop_timetable_fixture
) -> None:
    """Mode options override entry data and incomplete visits never collapse."""
    board = stop_timetable_fixture("hub")
    board["routes"] = [
        *board["routes"],
        {
            "id": "T:Train:LOOP",
            "lines": [{"vehicleType": "Ferry"}],
            "direction": "Outbound",
        },
        {"id": "ferry-local", "lines": [{"vehicleType": "Ferry"}]},
        {"id": "other", "lines": [{"vehicleType": "Unknown"}]},
    ]
    duplicate = board["departures"][1]
    without_id = {**duplicate, "id": None}
    without_time = {"id": "untimed", "routeId": "other"}
    without_platform = {**duplicate, "id": "no-platform", "departurePlatform": None}
    board["departures"].extend(
        [
            duplicate,
            without_id,
            without_id,
            without_time,
            without_time,
            without_platform,
            without_platform,
            {
                "id": "ferry",
                "routeId": "ferry-local",
                "scheduledDepartureUtc": "2099-01-01T02:00:00Z",
            },
        ]
    )
    hass.config_entries.async_update_entry(
        stop_entry,
        data={**stop_entry.data, CONF_TRANSPORT_MODES: ["Bus"]},
        options={CONF_TRANSPORT_MODES: ["Train"]},
    )
    coordinator = TranslinkCoordinator(hass, stop_entry)
    coordinator.client.fetch_stop_timetable = AsyncMock(
        return_value=StopTimetable.model_validate(board)
    )

    await coordinator.async_refresh()
    summary = coordinator.data
    assert isinstance(summary, StopSummary)
    rows = summary.departures
    assert {row["vehicle"] for row in rows} == {"Train", None}
    assert len([row for row in rows if row["trip_id"] is None]) == 2
    assert len([row for row in rows if row["trip_id"] == "untimed"]) == 2
    assert len([row for row in rows if row["trip_id"] == "no-platform"]) == 2
    assert rows[-1]["scheduled_departure_time"] is None
    assert len({row["visit_id"] for row in rows}) == len(rows)
    first_loop = next(row for row in rows if row["trip_id"] == "loop")
    assert first_loop["expected_departure_time"] == "2099-01-01T02:13:30Z"

    hass.config_entries.async_update_entry(
        stop_entry, options={CONF_TRANSPORT_MODES: []}
    )
    await coordinator.async_refresh()
    summary = coordinator.data
    assert isinstance(summary, StopSummary)
    assert {row["vehicle"] for row in summary.departures} == {
        "Train",
        "Bus",
        "Ferry",
        None,
    }


async def test_stop_summary_without_scheduled_baseline_preserves_expected_time(
    hass: HomeAssistant, stop_entry: MockConfigEntry, stop_timetable_fixture
) -> None:
    """A prediction without a schedule still carries no calculable offset."""
    board = stop_timetable_fixture("platform")
    board["departures"] = [
        {"id": "untimed"},
        {
            "id": "prediction",
            "realtime": {"expectedDepartureUtc": "2099-01-01T02:10:00Z"},
        },
    ]
    coordinator = TranslinkCoordinator(hass, stop_entry)
    coordinator.client.fetch_stop_timetable = AsyncMock(
        return_value=StopTimetable.model_validate(board)
    )
    await coordinator.async_refresh()
    summary = coordinator.data
    assert isinstance(summary, StopSummary)
    assert summary.next_departure_time is None
    assert summary.predicted_departure_time == datetime(2099, 1, 1, 2, 10, tzinfo=UTC)
    assert summary.delay_mins is None
    assert summary.departure_delay_seconds is None
    assert summary.delay_source is None


async def test_coordinator_update_failure_raises(
    hass: HomeAssistant, journey_entry: MockConfigEntry
) -> None:
    """Test coordinator raises UpdateFailed on API error."""
    with patch("custom_components.translink.coordinator.async_get_clientsession"):
        coordinator = TranslinkCoordinator(hass, journey_entry)

    coordinator.client.plan_journey = AsyncMock(
        side_effect=TranslinkConnectionError("Network timeout")
    )
    coordinator.client.fetch_vehicle_positions = AsyncMock(return_value=())
    coordinator.client.fetch_trip_updates = AsyncMock(return_value={})

    with pytest.raises(
        UpdateFailed, match=r"^Translink update failed: Network timeout$"
    ):
        await coordinator._async_update_data()


async def test_coordinator_shutdown(
    hass: HomeAssistant, journey_entry: MockConfigEntry
) -> None:
    """Test coordinator shutdown cleanly closes client."""
    with patch("custom_components.translink.coordinator.async_get_clientsession"):
        coordinator = TranslinkCoordinator(hass, journey_entry)

    coordinator.client.close = AsyncMock()
    await coordinator.async_shutdown()
    coordinator.client.close.assert_awaited_once()


async def test_coordinator_update_journey_without_vehicle_tracking(
    hass: HomeAssistant,
    plan_response_data: dict[str, Any],
) -> None:
    """Test coordinator update with vehicle tracking disabled."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry_no_track",
        data={
            CONF_MODE: MODE_JOURNEY,
            CONF_NAME: "Commute",
            CONF_START_LOCATION_ID: "ST:place_censta",
            CONF_END_LOCATION_ID: "ST:place_spcsta",
        },
        options={"track_vehicle": False},
    )
    entry.add_to_hass(hass)
    plan_result = JourneyPlanResult.model_validate(plan_response_data)
    with patch("custom_components.translink.coordinator.async_get_clientsession"):
        coordinator = TranslinkCoordinator(hass, entry)

    coordinator.client.plan_journey = AsyncMock(return_value=plan_result)
    coordinator.client.fetch_vehicle_positions = AsyncMock()
    coordinator.client.fetch_trip_updates = AsyncMock(return_value={})

    summary = await coordinator._async_update_data()
    assert isinstance(summary, JourneySummary)
    assert summary.vehicle_position_status == "disabled"
    assert summary.vehicle_latitude is None
    assert summary.vehicle_longitude is None
    coordinator.client.fetch_vehicle_positions.assert_not_called()


async def test_coordinator_update_unexpected_exception(
    hass: HomeAssistant,
    journey_entry: MockConfigEntry,
) -> None:
    """Test coordinator catches unexpected non-API exceptions and wraps as UpdateFailed."""
    with patch("custom_components.translink.coordinator.async_get_clientsession"):
        coordinator = TranslinkCoordinator(hass, journey_entry)

    coordinator.client.plan_journey = AsyncMock(
        side_effect=RuntimeError("System crash")
    )
    coordinator.client.fetch_vehicle_positions = AsyncMock(return_value=())
    coordinator.client.fetch_trip_updates = AsyncMock(return_value={})

    with pytest.raises(
        UpdateFailed,
        match=r"^Unexpected error fetching Translink data: RuntimeError: System crash$",
    ):
        await coordinator._async_update_data()


async def test_coordinator_unexpected_exception_without_message(
    hass: HomeAssistant,
    journey_entry: MockConfigEntry,
) -> None:
    """An exception with an empty message still names its type."""
    with patch("custom_components.translink.coordinator.async_get_clientsession"):
        coordinator = TranslinkCoordinator(hass, journey_entry)

    coordinator.client.plan_journey = AsyncMock(side_effect=KeyError())
    coordinator.client.fetch_vehicle_positions = AsyncMock(return_value=())
    coordinator.client.fetch_trip_updates = AsyncMock(return_value={})

    with pytest.raises(
        UpdateFailed, match=r"^Unexpected error fetching Translink data: KeyError$"
    ) as exc_info:
        await coordinator._async_update_data()
    assert isinstance(exc_info.value.__cause__, KeyError)


async def test_coordinator_api_error_without_message(
    hass: HomeAssistant,
    journey_entry: MockConfigEntry,
) -> None:
    """A Translink error with an empty message falls back to its type name."""
    with patch("custom_components.translink.coordinator.async_get_clientsession"):
        coordinator = TranslinkCoordinator(hass, journey_entry)

    coordinator.client.plan_journey = AsyncMock(side_effect=TranslinkConnectionError())
    coordinator.client.fetch_vehicle_positions = AsyncMock(return_value=())
    coordinator.client.fetch_trip_updates = AsyncMock(return_value={})

    with pytest.raises(
        UpdateFailed, match=r"^Translink update failed: TranslinkConnectionError$"
    ):
        await coordinator._async_update_data()


async def test_coordinator_planner_timeout_is_quiet_and_recovers(
    hass: HomeAssistant,
    journey_entry: MockConfigEntry,
    plan_response_data: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A planner timeout fails one refresh without a traceback; the next succeeds."""
    from unittest.mock import MagicMock

    with patch("custom_components.translink.coordinator.async_get_clientsession"):
        coordinator = TranslinkCoordinator(hass, journey_entry)

    session = MagicMock()
    session.closed = False
    session.post.side_effect = TimeoutError()
    coordinator.client._session = session
    coordinator.client.fetch_vehicle_positions = AsyncMock(return_value=())
    coordinator.client.fetch_trip_updates = AsyncMock(return_value={})

    with pytest.raises(
        UpdateFailed,
        match=r"^Translink update failed: Timed out connecting to Translink journey planner$",
    ):
        await coordinator._async_update_data()
    assert "Unexpected error fetching Translink data" not in caplog.text

    coordinator.client.plan_journey = AsyncMock(
        return_value=JourneyPlanResult.model_validate(plan_response_data)
    )
    summary = await coordinator._async_update_data()
    assert isinstance(summary, JourneySummary)


async def test_coordinator_update_journey_plan_fallback(
    hass: HomeAssistant,
    journey_entry: MockConfigEntry,
) -> None:
    """Test coordinator update when plan_journey returns non-JourneyPlanResult."""
    with patch("custom_components.translink.coordinator.async_get_clientsession"):
        coordinator = TranslinkCoordinator(hass, journey_entry)

    coordinator.client.plan_journey = AsyncMock(return_value=None)
    coordinator.client.fetch_vehicle_positions = AsyncMock(return_value=())
    coordinator.client.fetch_trip_updates = AsyncMock(return_value={})

    summary = await coordinator._async_update_data()
    assert isinstance(summary, JourneySummary)
    assert summary.status == "no_service"


async def test_timetable_cache_ttls_bounds_and_failures(
    hass, journey_entry, plan_response_data, monkeypatch
):
    """Optional enrichment is deduplicated, bounded and isolated from core data."""
    from types import SimpleNamespace

    from custom_components.translink import coordinator as module
    from custom_components.translink.api.models import TripDeparture, TripTimetable
    from custom_components.translink.api.trip_page import TripPageParseError

    with patch("custom_components.translink.coordinator.async_get_clientsession"):
        coordinator = TranslinkCoordinator(hass, journey_entry)
    now = [100.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: now[0]))
    plan = JourneyPlanResult.model_validate(plan_response_data)
    leg = plan.itineraries[0].legs[0]
    timetable = TripTimetable(id=leg.tripId, departures=[])
    coordinator.client.async_get_trip_timetable = AsyncMock(return_value=timetable)
    assert await coordinator._async_get_trip_timetables(plan) == {leg.tripId: timetable}
    assert await coordinator._async_get_trip_timetables(plan) == {leg.tripId: timetable}
    assert coordinator.client.async_get_trip_timetable.await_count == 1
    now[0] += module.TRIP_PAGE_SUCCESS_TTL + 1
    await coordinator._async_get_trip_timetables(plan)
    assert coordinator.client.async_get_trip_timetable.await_count == 2
    coordinator._trip_cache.clear()
    for error in [
        TimeoutError(),
        TranslinkConnectionError("offline"),
        TripPageParseError("changed"),
        None,
    ]:
        coordinator.client.async_get_trip_timetable = (
            AsyncMock(side_effect=error) if error else AsyncMock(return_value=None)
        )
        assert await coordinator._async_get_trip_timetables(plan) == {}
        await coordinator._async_get_trip_timetables(plan)
        assert coordinator.client.async_get_trip_timetable.await_count == 1
        now[0] += module.TRIP_PAGE_NEGATIVE_TTL + 1
    many = plan.model_copy(deep=True)
    many.itineraries[0].legs = [
        leg.model_copy(update={"tripId": f"trip-{i}"}) for i in range(5)
    ]
    scheduled_calls = [
        TripDeparture(
            stopId=leg.origin.id.removeprefix("SI:"),
            order=1,
            scheduledDepartureUtc=leg.departureTimeUtc,
        ),
        TripDeparture(
            stopId=leg.destination.id.removeprefix("SI:"),
            order=2,
            scheduledDepartureUtc=leg.arrivalTimeUtc,
        ),
    ]
    coordinator.client.async_get_trip_timetable = AsyncMock(
        side_effect=lambda trip_id: TripTimetable(
            id=trip_id, departures=scheduled_calls
        )
    )
    coordinator.client.plan_journey = AsyncMock(return_value=many)
    coordinator.client.fetch_trip_updates = AsyncMock(return_value={})
    coordinator.client.fetch_vehicle_positions = AsyncMock(return_value=[])
    summary = await coordinator._async_update_data()
    assert (
        coordinator.client.async_get_trip_timetable.await_count
        == module.TRIP_PAGE_MAX_PER_REFRESH
    )
    assert isinstance(summary, JourneySummary)
    assert len(summary.itinerary_legs) == 5
    assert all(leg["timetableUrl"] for leg in summary.itinerary_legs[:4])
    assert summary.itinerary_legs[4]["timetableUrl"] is None
    coordinator._trip_cache = {
        f"old-{i}": (now[0] + 100, None) for i in range(module.TRIP_PAGE_CACHE_LIMIT)
    }
    await coordinator._async_get_trip_timetables(plan)
    assert len(coordinator._trip_cache) == module.TRIP_PAGE_CACHE_LIMIT
    assert "old-0" not in coordinator._trip_cache
    assert await coordinator._async_get_trip_timetables(JourneyPlanResult()) == {}


async def test_notice_entry_retains_freshness_through_failure_and_recovery(
    hass: HomeAssistant,
) -> None:
    """A real config entry publishes refreshed notices without clearing on error."""
    from homeassistant.const import STATE_UNAVAILABLE
    from homeassistant.helpers import device_registry, entity_registry

    from custom_components.translink.api.gtfs_realtime import AlertDetail, AlertFeed
    from custom_components.translink.client import AlertFeedError

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Cairns notices",
        data={
            "name": "Cairns notices",
            "mode": "notices",
            "notice_network": "CNS",
            "notice_scope": "network",
        },
        options={CONF_SCAN_INTERVAL: 45},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.translink.coordinator.TranslinkClient.fetch_alert_feed",
        side_effect=[
            AlertFeed(42, "2.0", (AlertDetail("initial", "Initial alert"),)),
            AlertFeedError("Unavailable"),
            AlertFeed(43, "2.0", (AlertDetail("updated", "Updated alert"),)),
            AlertFeed(44, "2.0", (AlertDetail("updated", "Updated text"),)),
            AlertFeed(45, "2.0", ()),
        ],
    ) as fetch:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        coordinator = entry.runtime_data
        registry = entity_registry.async_get(hass)
        entities = {
            row.translation_key: row
            for row in entity_registry.async_entries_for_config_entry(
                registry, entry.entry_id
            )
        }
        assert set(entities) == {
            "disruptions",
            "disruption_description",
            "last_successful_fetch",
            "disruption",
        }
        assert entities["disruptions"].unique_id == f"{entry.entry_id}_disruptions"
        device = device_registry.async_get(hass).async_get(
            entities["disruptions"].device_id
        )
        assert device.model == "Service Notices"
        assert {row.device_id for row in entities.values()} == {device.id}
        notice = entities["disruptions"].entity_id
        freshness = entities["last_successful_fetch"].entity_id
        event = entities["disruption"].entity_id

        assert coordinator.update_interval == timedelta(seconds=45)
        assert hass.states.get(notice).state == "1"
        assert hass.states.get(notice).attributes["network"] == "CNS"
        assert "route" not in hass.states.get(notice).attributes
        assert hass.states.get(event).attributes["event_type"] == "disruption"
        initial_event = hass.states.get(event).state
        last_good = coordinator.data
        last_freshness = hass.states.get(freshness).state
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert not coordinator.last_update_success
        assert coordinator.data is last_good
        assert hass.states.get(notice).state == STATE_UNAVAILABLE
        assert hass.states.get(event).state == STATE_UNAVAILABLE
        assert hass.states.get(freshness).state == last_freshness
        assert hass.states.get(freshness).attributes["last_update_success"] is False

        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert coordinator.last_update_success
        assert hass.states.get(notice).attributes["disruptions"][0]["id"] == "updated"
        recovered_event = hass.states.get(event)
        assert recovered_event.state != initial_event
        assert recovered_event.attributes["event_type"] == "disruption"

        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert (
            hass.states.get(notice).attributes["disruptions"][0]["title"]
            == "Updated text"
        )
        assert hass.states.get(event).state == recovered_event.state

        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(notice).state == "0"
        assert hass.states.get(event).attributes["event_type"] == "cleared"
        assert [call.args for call in fetch.await_args_list] == [("CNS",)] * 5


async def test_notice_entry_first_fetch_failure_retries(hass: HomeAssistant) -> None:
    """An unavailable feed at setup raises the config-entry retry signal."""
    from homeassistant.config_entries import ConfigEntryState

    from custom_components.translink.client import AlertFeedError

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"mode": "notices", "notice_network": "SEQ", "notice_scope": "network"},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.translink.coordinator.TranslinkClient.fetch_alert_feed",
        side_effect=AlertFeedError("Unavailable"),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.reason is not None and "Unavailable" in entry.reason


@pytest.mark.parametrize(
    ("scope", "configured", "expected"),
    [
        ("route", {"notice_route_id": "RPSP"}, "RPSP"),
        ("mode", {"notice_route_mode": "Tram"}, 0),
    ],
)
async def test_notice_refresh_applies_configured_filter(
    hass: HomeAssistant, scope: str, configured: dict[str, str], expected: str | int
) -> None:
    """The coordinator interprets notice route and mode settings for its own feed."""
    from custom_components.translink.api.gtfs_realtime import (
        AlertDetail,
        AlertFeed,
        AlertSelector,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_MODE: "notices",
            "notice_network": "SEQ",
            "notice_scope": scope,
            **configured,
        },
    )
    entry.add_to_hass(hass)
    coordinator = TranslinkCoordinator(hass, entry)
    feed = AlertFeed(
        None,
        "2.0",
        (
            AlertDetail(
                "right", selectors=(AlertSelector(route_id="RPSP-5154", route_type=0),)
            ),
            AlertDetail(
                "wrong", selectors=(AlertSelector(route_id="else", route_type=3),)
            ),
        ),
    )
    with patch.object(coordinator.client, "fetch_alert_feed", return_value=feed):
        await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert coordinator.data.scope_value == expected
    assert [row["id"] for row in coordinator.data.disruptions] == ["right"]
