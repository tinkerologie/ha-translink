"""Test planner notice transitions through Home Assistant entities."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant.common import MockConfigEntry

from custom_components.translink.api.models import StopTimetable
from custom_components.translink.client import (
    JourneyPlanResult,
    TranslinkClient,
    TranslinkConnectionError,
)
from custom_components.translink.const import (
    CONF_END_LOCATION_ID,
    CONF_END_NAME,
    CONF_MODE,
    CONF_NAME,
    CONF_START_LOCATION_ID,
    CONF_START_NAME,
    CONF_STOP_LOCATION_ID,
    CONF_STOP_NAME,
    DOMAIN,
    MODE_JOURNEY,
    MODE_STOP,
)
from custom_components.translink.event import TranslinkDisruptionEvent

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


@pytest.fixture
def planner(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Stub upstream requests while running the real integration and platforms."""
    plan_journey = AsyncMock()
    monkeypatch.setattr(TranslinkClient, "plan_journey", plan_journey)
    monkeypatch.setattr(
        TranslinkClient, "fetch_trip_updates", AsyncMock(return_value={})
    )
    monkeypatch.setattr(
        TranslinkClient, "fetch_vehicle_positions", AsyncMock(return_value={})
    )
    return plan_journey


@pytest.fixture
def trigger() -> Generator[MagicMock]:
    """Capture notifications at the Home Assistant event entity boundary."""
    with patch.object(
        TranslinkDisruptionEvent,
        "_trigger_event",
        autospec=True,
        side_effect=TranslinkDisruptionEvent._trigger_event,
    ) as mock_trigger:
        yield mock_trigger


@pytest.fixture
def journey_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Register a Central to Springfield journey."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_MODE: MODE_JOURNEY,
            CONF_NAME: "Commute",
            CONF_START_LOCATION_ID: "ST:place_censta",
            CONF_START_NAME: "Central station",
            CONF_END_LOCATION_ID: "ST:place_spcsta",
            CONF_END_NAME: "Springfield Central",
        },
    )
    entry.add_to_hass(hass)
    return entry


def closure_plan(
    *, populated: bool = False, ends_utc: str | None = None
) -> JourneyPlanResult:
    """Build the same closure with or without a referenced rail itinerary."""
    return JourneyPlanResult.model_validate(
        {
            "itineraries": [
                {
                    "legs": [
                        {
                            "travelMode": "Train",
                            "notices": [{"id": 101, "severity": "Major"}],
                        }
                    ]
                }
            ]
            if populated
            else [],
            "notices": [
                {
                    "id": "101",
                    "title": "Line closure",
                    "description": "Buses replace trains.",
                    "endsUtc": ends_utc,
                }
            ],
        }
    )


def sensor_state(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> State:
    """Get the state for a configured Translink sensor."""
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{key}"
    )
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    return state


def assert_closure_sensors(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Verify both disruption sensors expose the planner's closure details."""
    disruptions = sensor_state(hass, entry, "disruptions")
    assert disruptions.state == "1"
    assert disruptions.attributes["latest_title"] == "Line closure"
    assert disruptions.attributes["latest_description"] == "Buses replace trains."
    assert [notice["id"] for notice in disruptions.attributes["disruptions"]] == ["101"]

    description = sensor_state(hass, entry, "disruption_description")
    assert description.state == "Line closure"
    assert description.attributes["count"] == 1
    assert (
        description.attributes["description"] == "• Line closure: Buses replace trains."
    )


async def test_journey_closure_survives_no_service_and_failed_refresh(
    hass: HomeAssistant,
    journey_entry: MockConfigEntry,
    planner: AsyncMock,
    trigger: MagicMock,
) -> None:
    """Only a successful refresh with the closure absent clears the alert."""
    planner.side_effect = [
        closure_plan(populated=True),
        closure_plan(),
        closure_plan(populated=True),
        TranslinkConnectionError("Network timeout"),
        JourneyPlanResult(),
    ]
    assert await hass.config_entries.async_setup(journey_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = journey_entry.runtime_data

    assert trigger.call_count == 1
    _, event_type, payload = trigger.call_args.args
    assert event_type == "disruption"
    assert payload["count"] == 1
    assert payload["title"] == "Line closure"
    assert payload["severity"] == "Major"
    assert payload["disruptions"][0]["id"] == 101

    await coordinator.async_refresh()
    assert sensor_state(hass, journey_entry, "status").state == "no_service"
    assert_closure_sensors(hass, journey_entry)
    assert trigger.call_count == 1

    await coordinator.async_refresh()
    assert sensor_state(hass, journey_entry, "disruptions").state == "1"
    assert trigger.call_count == 1

    await coordinator.async_refresh()
    assert isinstance(coordinator.last_exception, UpdateFailed)
    assert trigger.call_count == 1

    await coordinator.async_refresh()
    assert sensor_state(hass, journey_entry, "disruptions").state == "0"
    assert trigger.call_count == 2
    assert trigger.call_args.args[1:] == (
        "cleared",
        {"count": 0, "message": "All service disruptions cleared"},
    )


async def test_journey_closure_clears_when_its_end_time_passes(
    hass: HomeAssistant,
    journey_entry: MockConfigEntry,
    planner: AsyncMock,
    trigger: MagicMock,
) -> None:
    """A returned notice with a known past end time clears the event."""
    planner.side_effect = [
        closure_plan(populated=True),
        closure_plan(ends_utc="2000-01-01T00:00:00Z"),
    ]
    assert await hass.config_entries.async_setup(journey_entry.entry_id)
    await hass.async_block_till_done()
    assert trigger.call_count == 1
    assert trigger.call_args.args[1] == "disruption"

    await journey_entry.runtime_data.async_refresh()
    assert sensor_state(hass, journey_entry, "disruptions").state == "0"
    assert trigger.call_count == 2
    assert trigger.call_args.args[1:] == (
        "cleared",
        {"count": 0, "message": "All service disruptions cleared"},
    )


async def test_stop_notice_survives_empty_board_and_unavailable_alerts(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    stop_timetable_fixture,
    trigger: MagicMock,
) -> None:
    """Keep scoped notices through a missing section and clear on valid empty data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_MODE: MODE_STOP,
            CONF_NAME: "Example Hub",
            CONF_STOP_LOCATION_ID: "SI:10001",
            CONF_STOP_NAME: "Example Hub platform 1",
        },
    )
    entry.add_to_hass(hass)
    hub = stop_timetable_fixture("hub")
    platform = stop_timetable_fixture("platform")
    sections = stop_timetable_fixture("alert_sections")
    changed_alert = {"id": 1234, "title": "Lift replacement", "severity": "Major"}
    missing = {key: value for key, value in platform.items() if key != "serviceAlerts"}
    fetch_timetable = AsyncMock(
        side_effect=[
            StopTimetable.model_validate({**platform, "departures": hub["departures"]}),
            StopTimetable.model_validate(platform),
            StopTimetable.model_validate(missing),
            StopTimetable.model_validate(
                {**platform, "serviceAlerts": sections["malformed"]}
            ),
            StopTimetable.model_validate(
                {**platform, "serviceAlerts": {"current": [changed_alert]}}
            ),
            TranslinkConnectionError("Network timeout"),
            StopTimetable.model_validate(
                {**platform, "serviceAlerts": sections["upcoming_only"]}
            ),
        ]
    )
    monkeypatch.setattr(TranslinkClient, "fetch_stop_timetable", fetch_timetable)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert trigger.call_count == 1
    _, event_type, payload = trigger.call_args.args
    assert event_type == "disruption"
    assert payload["disruptions"][0]["id"] == 1234
    assert payload["title"] == "Lift maintenance"
    assert payload["severity"] == "Informative"

    departures = sensor_state(hass, entry, "departures_board")
    assert departures.state == "8 departures"
    assert (
        departures.attributes["departures"][2]["departure_time"]
        == "2099-01-01T02:10:00Z"
    )
    assert (
        departures.attributes["departures"][2]["expected_departure_time"]
        == "2099-01-01T02:13:30Z"
    )

    for _ in range(3):
        await entry.runtime_data.async_refresh()
        departures = sensor_state(hass, entry, "departures_board")
        assert departures.state == "0 departures"
        assert departures.attributes["departures"] == []
        disruptions = sensor_state(hass, entry, "disruptions")
        assert disruptions.state == "1"
        assert disruptions.attributes["latest_title"] == "Lift maintenance"
        assert disruptions.attributes["latest_description"] == "Use the other lift."
        assert trigger.call_count == 1

    await entry.runtime_data.async_refresh()
    assert (
        sensor_state(hass, entry, "disruptions").attributes["latest_title"]
        == "Lift replacement"
    )
    assert trigger.call_count == 1

    await entry.runtime_data.async_refresh()
    assert isinstance(entry.runtime_data.last_exception, UpdateFailed)
    assert trigger.call_count == 1

    await entry.runtime_data.async_refresh()
    assert sensor_state(hass, entry, "disruptions").state == "0"
    assert trigger.call_count == 2
    assert trigger.call_args.args[1] == "cleared"
    assert all(call.args == ("SI:10001",) for call in fetch_timetable.await_args_list)
