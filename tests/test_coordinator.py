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
    coordinator.client.fetch_vehicle_positions = AsyncMock(return_value={})
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
    board["departures"].extend(
        [
            duplicate,
            without_id,
            without_id,
            without_time,
            without_time,
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
    coordinator.client.fetch_vehicle_positions = AsyncMock(return_value={})
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
    coordinator.client.fetch_vehicle_positions = AsyncMock(return_value={})
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
    coordinator.client.fetch_vehicle_positions = AsyncMock(return_value={})
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
    coordinator.client.fetch_vehicle_positions = AsyncMock(return_value={})
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
    coordinator.client.fetch_vehicle_positions = AsyncMock(return_value={})
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
