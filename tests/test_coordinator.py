"""Tests for Translink coordinator."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

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
    coordinator.client.fetch_vehicle_positions = AsyncMock(return_value={})
    coordinator.client.fetch_trip_updates = AsyncMock(return_value={})

    summary = await coordinator._async_update_data()
    assert isinstance(summary, JourneySummary)
    assert summary.status in ["scheduled", "on_time", "delayed", "departed", "arrived"]
    assert summary.duration_mins == 41


async def test_coordinator_update_stop_success(
    hass: HomeAssistant,
    stop_entry: MockConfigEntry,
    plan_response_data: dict[str, Any],
) -> None:
    """Test coordinator _async_update_stop."""
    plan_result = JourneyPlanResult.model_validate(plan_response_data)

    with patch("custom_components.translink.coordinator.async_get_clientsession"):
        coordinator = TranslinkCoordinator(hass, stop_entry)

    coordinator.client.plan_journey = AsyncMock(return_value=plan_result)
    coordinator.client.fetch_trip_updates = AsyncMock(return_value={})

    summary = await coordinator._async_update_data()
    assert isinstance(summary, StopSummary)
    assert summary.stop_id == "ST:place_romsta"
    assert summary.stop_name == "Roma Street station"


async def test_coordinator_update_failure_raises(
    hass: HomeAssistant, journey_entry: MockConfigEntry
) -> None:
    """Test coordinator raises UpdateFailed on API error."""
    with patch("custom_components.translink.coordinator.async_get_clientsession"):
        coordinator = TranslinkCoordinator(hass, journey_entry)

    coordinator.client.plan_journey = AsyncMock(
        side_effect=TranslinkConnectionError("Network timeout")
    )
    coordinator.client.fetch_vehicle_positions = AsyncMock(return_value={})
    coordinator.client.fetch_trip_updates = AsyncMock(return_value={})

    with pytest.raises(UpdateFailed):
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
    coordinator.client.fetch_trip_updates = AsyncMock(return_value={})

    summary = await coordinator._async_update_data()
    assert isinstance(summary, JourneySummary)


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
    coordinator.client.fetch_vehicle_positions = AsyncMock(return_value={})
    coordinator.client.fetch_trip_updates = AsyncMock(return_value={})

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_coordinator_update_journey_plan_fallback(
    hass: HomeAssistant,
    journey_entry: MockConfigEntry,
) -> None:
    """Test coordinator update when plan_journey returns non-JourneyPlanResult."""
    with patch("custom_components.translink.coordinator.async_get_clientsession"):
        coordinator = TranslinkCoordinator(hass, journey_entry)

    coordinator.client.plan_journey = AsyncMock(return_value=None)
    coordinator.client.fetch_vehicle_positions = AsyncMock(return_value={})
    coordinator.client.fetch_trip_updates = AsyncMock(return_value={})

    summary = await coordinator._async_update_data()
    assert isinstance(summary, JourneySummary)
    assert summary.status == "no_service"


async def test_coordinator_update_stop_central_station(
    hass: HomeAssistant,
    plan_response_data: dict[str, Any],
) -> None:
    """Test stop update when stop is Central Station avoiding self-destination."""
    plan_result = JourneyPlanResult.model_validate(plan_response_data)
    entry = MockConfigEntry(
        domain="translink",
        unique_id="stop_central",
        data={
            "mode": "stop",
            "name": "Central Station",
            "stop_location_id": "ST:place_censta",
            "stop_name": "Central Station",
        },
    )
    with patch("custom_components.translink.coordinator.async_get_clientsession"):
        coordinator = TranslinkCoordinator(hass, entry)

    coordinator.client.plan_journey = AsyncMock(return_value=plan_result)
    coordinator.client.fetch_trip_updates = AsyncMock(return_value={})

    summary = await coordinator._async_update_data()
    assert isinstance(summary, StopSummary)
    assert len(summary.departures) > 0
    # verify plan_journey was called with end_location_id="ST:place_romsta"
    coordinator.client.plan_journey.assert_called_once()
    call_kwargs = coordinator.client.plan_journey.call_args[1]
    assert call_kwargs["end_location_id"] == "ST:place_romsta"


async def test_coordinator_update_stop_empty_departures(
    hass: HomeAssistant,
    stop_entry: MockConfigEntry,
) -> None:
    """Test stop update falls back to journey legs when no transit departures."""
    plan_result = JourneyPlanResult(itineraries=[])

    with patch("custom_components.translink.coordinator.async_get_clientsession"):
        coordinator = TranslinkCoordinator(hass, stop_entry)

    coordinator.client.plan_journey = AsyncMock(return_value=plan_result)
    coordinator.client.fetch_trip_updates = AsyncMock(return_value={})

    summary = await coordinator._async_update_data()
    assert isinstance(summary, StopSummary)
    assert summary.departures == []


async def test_coordinator_update_stop_with_walk_and_transit_legs(
    hass: HomeAssistant,
    stop_entry: MockConfigEntry,
) -> None:
    """Test stop departures loop skips walk legs before taking transit leg."""
    from custom_components.translink.api.models import JourneyItinerary, JourneyLeg

    plan_result = JourneyPlanResult(
        itineraries=[
            JourneyItinerary(
                legs=[
                    JourneyLeg(travelMode="Walk"),
                    JourneyLeg(
                        travelMode="Bus",
                        tripHeadsign="Route 100",
                        departureTimeUtc="2026-10-06T09:40:00Z",
                    ),
                ]
            ),
            JourneyItinerary(
                legs=[
                    JourneyLeg(travelMode="Walk"),
                ]
            ),
        ]
    )

    with patch("custom_components.translink.coordinator.async_get_clientsession"):
        coordinator = TranslinkCoordinator(hass, stop_entry)

    coordinator.client.plan_journey = AsyncMock(return_value=plan_result)
    coordinator.client.fetch_trip_updates = AsyncMock(return_value={})

    summary = await coordinator._async_update_data()
    assert isinstance(summary, StopSummary)
    assert len(summary.departures) == 1
    assert summary.departures[0]["vehicle"] == "Bus"


async def test_timetable_cache_ttls_bounds_and_failures(
    hass, journey_entry, plan_response_data, monkeypatch
):
    """Optional enrichment is deduplicated, bounded and isolated from core data."""
    from types import SimpleNamespace

    from custom_components.translink import coordinator as module
    from custom_components.translink.api.models import TripTimetable
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
        leg.model_copy(update={"tripId": str(i)}) for i in range(10)
    ]
    coordinator.client.async_get_trip_timetable = AsyncMock(return_value=None)
    await coordinator._async_get_trip_timetables(many)
    assert (
        coordinator.client.async_get_trip_timetable.await_count
        == module.TRIP_PAGE_MAX_PER_REFRESH
    )
    coordinator._trip_cache = {
        f"old-{i}": (now[0] + 100, None) for i in range(module.TRIP_PAGE_CACHE_LIMIT)
    }
    await coordinator._async_get_trip_timetables(plan)
    assert len(coordinator._trip_cache) == module.TRIP_PAGE_CACHE_LIMIT
    assert "old-0" not in coordinator._trip_cache
    assert await coordinator._async_get_trip_timetables(JourneyPlanResult()) == {}
