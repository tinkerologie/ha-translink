"""Tests for Translink sensor platform."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from custom_components.translink.client import JourneySummary, StopSummary
from custom_components.translink.const import (
    CONF_MODE,
    CONF_NAME,
    DOMAIN,
    MODE_JOURNEY,
    MODE_STOP,
)
from custom_components.translink.sensor import (
    JOURNEY_SENSORS,
    STOP_SENSORS,
    TranslinkSensor,
    TranslinkSensorEntityDescription,
    async_setup_entry,
)


class FakeEntry:
    """Fake ConfigEntry for testing."""

    def __init__(self, mode: str = MODE_JOURNEY) -> None:
        self.entry_id = "test_entry_id"
        self.data = {
            CONF_MODE: mode,
            CONF_NAME: "My Journey",
        }
        self.runtime_data = None


class FakeCoordinator:
    """Fake coordinator for sensor tests."""

    def __init__(self, mode: str = MODE_JOURNEY, data: Any = None) -> None:
        self.mode = mode
        self.data = data
        self.entry = FakeEntry(mode=mode)
        self._listeners: list[Any] = []

    def async_add_listener(self, update_callback: Any) -> Any:
        self._listeners.append(update_callback)
        return lambda: self._listeners.remove(update_callback)


@pytest.fixture
def sample_journey_summary() -> JourneySummary:
    """Fixture with a populated JourneySummary."""
    dep_time = datetime(2026, 10, 6, 9, 30, tzinfo=UTC)
    arr_time = datetime(2026, 10, 6, 10, 11, tzinfo=UTC)
    return JourneySummary(
        status="on_time",
        departure_time=dep_time,
        arrival_time=arr_time,
        duration_mins=41,
        transfers=0,
        next_service_name="T2 Springfield Central",
        next_service_vehicle="Train",
        next_service_headsign="Springfield Central",
        origin_name="Central station",
        origin_platform="5",
        destination_name="Springfield Central station",
        destination_platform="1",
        fare_price=0.5,
        fare_currency="AUD",
        fare_type="Adult",
        walking_distance_m=120,
        delay_mins=1,
        disruptions_count=0,
        itinerary_legs=[{"travelMode": "Train", "durationMins": 41}],
    )


@pytest.fixture
def sample_stop_summary() -> StopSummary:
    """Fixture with a populated StopSummary."""
    dep_time = datetime(2026, 10, 6, 9, 35, tzinfo=UTC)
    return StopSummary(
        stop_id="ST:place_romsta",
        stop_name="Roma Street",
        next_departure_time=dep_time,
        next_route="T1 Caboolture",
        next_vehicle="Train",
        next_platform="3",
        delay_mins=2,
        departures=[{"route": "T1"}],
        disruptions_count=1,
    )


@pytest.mark.asyncio
async def test_async_setup_entry_journey(
    sample_journey_summary: JourneySummary,
) -> None:
    """Test setting up journey sensors."""
    hass = MagicMock()
    entry = FakeEntry(mode=MODE_JOURNEY)
    coordinator = FakeCoordinator(mode=MODE_JOURNEY, data=sample_journey_summary)
    entry.runtime_data = coordinator  # type: ignore[assignment]
    hass.data = {DOMAIN: {entry.entry_id: coordinator}}

    entities: list[TranslinkSensor] = []
    await async_setup_entry(hass, entry, lambda added: entities.extend(added))  # type: ignore[arg-type]

    assert len(entities) == len(JOURNEY_SENSORS)
    assert any(e.entity_description.key == "next_departure" for e in entities)
    assert any(e.entity_description.key == "duration" for e in entities)
    assert any(e.entity_description.key == "status" for e in entities)


@pytest.mark.asyncio
async def test_async_setup_entry_stop(sample_stop_summary: StopSummary) -> None:
    """Test setting up stop sensors."""
    hass = MagicMock()
    entry = FakeEntry(mode=MODE_STOP)
    coordinator = FakeCoordinator(mode=MODE_STOP, data=sample_stop_summary)
    entry.runtime_data = coordinator  # type: ignore[assignment]
    hass.data = {DOMAIN: {entry.entry_id: coordinator}}

    entities: list[TranslinkSensor] = []
    await async_setup_entry(hass, entry, lambda added: entities.extend(added))  # type: ignore[arg-type]

    assert len(entities) == len(STOP_SENSORS)


def test_journey_sensor_properties(sample_journey_summary: JourneySummary) -> None:
    """Test values and attributes for journey sensors."""
    coordinator = FakeCoordinator(mode=MODE_JOURNEY, data=sample_journey_summary)
    entry = FakeEntry(mode=MODE_JOURNEY)

    sensors = {
        desc.key: TranslinkSensor(coordinator, desc, entry)  # type: ignore[arg-type]
        for desc in JOURNEY_SENSORS
    }

    assert sensors["duration"].native_value == 41
    assert sensors["status"].native_value == "on_time"
    assert sensors["next_service"].native_value == "T2 Springfield Central (Train)"
    assert sensors["next_service"].icon == "mdi:train"
    assert sensors["platform"].native_value == "5"
    assert sensors["platform"].icon == "mdi:bus-stop-uncovered"
    assert sensors["transfers"].native_value == 0
    assert sensors["fare"].native_value == 0.5
    assert sensors["delay"].native_value == 1
    assert sensors["walking_distance"].native_value == 120
    assert sensors["disruptions"].native_value == 0
    assert sensors["disruption_description"].native_value == "Normal"

    # Extra state attributes
    disruption_attrs = sensors["disruptions"].extra_state_attributes
    assert disruption_attrs["summary"] == "Normal"
    assert disruption_attrs["description"] == "No active disruptions"
    assert disruption_attrs["latest_title"] is None

    desc_attrs = sensors["disruption_description"].extra_state_attributes
    assert desc_attrs["count"] == 0
    assert desc_attrs["description"] == "No active disruptions"

    # Extra state attributes
    attrs = sensors["next_departure"].extra_state_attributes
    assert attrs["platform"] == "5"
    assert attrs["origin"] == "Central station"
    assert attrs["readable_time"] == "07:30 PM"

    arrival_attrs = sensors["arrival_time"].extra_state_attributes
    assert arrival_attrs["readable_time"] == "08:11 PM"

    # Test None departure_time produces None readable_time
    sample_journey_summary.departure_time = None
    attrs_none = sensors["next_departure"].extra_state_attributes
    assert attrs_none["readable_time"] is None


def test_stop_sensor_properties(sample_stop_summary: StopSummary) -> None:
    """Test values and attributes for stop departure sensors."""
    sample_stop_summary.disruptions_count = 1
    sample_stop_summary.disruptions = [
        {"id": 1, "title": "Lift Maintenance", "description": "Platform 3 lift closed."}
    ]
    sample_stop_summary.disruptions_summary = "Lift Maintenance"
    sample_stop_summary.disruptions_description = (
        "• Lift Maintenance: Platform 3 lift closed."
    )
    sample_stop_summary.latest_disruption_title = "Lift Maintenance"
    sample_stop_summary.latest_disruption_description = "Platform 3 lift closed."

    coordinator = FakeCoordinator(mode=MODE_STOP, data=sample_stop_summary)
    entry = FakeEntry(mode=MODE_STOP)

    sensors = {
        desc.key: TranslinkSensor(coordinator, desc, entry)  # type: ignore[arg-type]
        for desc in STOP_SENSORS
    }

    assert sensors["platform"].native_value == "3"
    assert sensors["platform"].icon == "mdi:bus-stop-uncovered"
    assert sensors["disruptions"].native_value == 1
    assert sensors["disruption_description"].native_value == "Lift Maintenance"

    disruption_attrs = sensors["disruptions"].extra_state_attributes
    assert disruption_attrs["summary"] == "Lift Maintenance"
    assert (
        disruption_attrs["description"] == "• Lift Maintenance: Platform 3 lift closed."
    )
    assert disruption_attrs["latest_title"] == "Lift Maintenance"

    desc_attrs = sensors["disruption_description"].extra_state_attributes
    assert desc_attrs["count"] == 1
    assert desc_attrs["description"] == "• Lift Maintenance: Platform 3 lift closed."


def test_sensor_fallback_disruption_description() -> None:
    """Test disruption_description sensor fallback when count > 0 but no title."""
    summary = JourneySummary(
        disruptions_count=1,
        disruptions=[{"id": 99}],
        latest_disruption_title=None,
    )
    coordinator = FakeCoordinator(mode=MODE_JOURNEY, data=summary)
    entry = FakeEntry(mode=MODE_JOURNEY)

    sensors = {
        desc.key: TranslinkSensor(coordinator, desc, entry)  # type: ignore[arg-type]
        for desc in JOURNEY_SENSORS
    }
    assert sensors["disruption_description"].native_value == "Service Disruption"


def test_sensor_none_data() -> None:
    """Test sensor behavior when coordinator data is None."""
    coordinator = FakeCoordinator(mode=MODE_JOURNEY, data=None)
    entry = FakeEntry(mode=MODE_JOURNEY)
    sensor = TranslinkSensor(coordinator, JOURNEY_SENSORS[0], entry)  # type: ignore[arg-type]

    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}
    assert sensor.icon is None


@pytest.mark.parametrize(
    ("vehicle_type", "expected_icon"),
    [
        ("Train", "mdi:train"),
        ("Queensland Rail Train", "mdi:train"),
        ("Bus", "mdi:bus"),
        ("Ferry", "mdi:ferry"),
        ("CityCat Boat", "mdi:ferry"),
        ("Tram", "mdi:tram"),
        ("G:link Light Rail", "mdi:tram"),
        ("UnknownVehicle", "mdi:train-bus"),
        (None, "mdi:train-bus"),
    ],
)
def test_sensor_dynamic_icons(vehicle_type: str | None, expected_icon: str) -> None:
    """Test sensor dynamic icon based on vehicle transport mode."""
    from custom_components.translink.const import get_vehicle_icon

    assert get_vehicle_icon(vehicle_type) == expected_icon

    summary = JourneySummary(next_service_vehicle=vehicle_type)
    coordinator = FakeCoordinator(mode=MODE_JOURNEY, data=summary)
    entry = FakeEntry(mode=MODE_JOURNEY)
    # Find next_service description
    next_service_desc = next(d for d in JOURNEY_SENSORS if d.key == "next_service")
    sensor = TranslinkSensor(coordinator, next_service_desc, entry)  # type: ignore[arg-type]
    assert sensor.icon == expected_icon


def test_sensor_icon_fallback_when_coordinator_data_none() -> None:
    """Test sensor icon fallback when coordinator.data is None."""
    coordinator = FakeCoordinator(mode=MODE_JOURNEY, data=None)
    entry = FakeEntry(mode=MODE_JOURNEY)
    next_service_desc = next(d for d in JOURNEY_SENSORS if d.key == "next_service")
    sensor = TranslinkSensor(coordinator, next_service_desc, entry)  # type: ignore[arg-type]
    assert sensor.icon == "mdi:train-bus"

    # Description with icon_fn but icon=None
    desc_no_icon = TranslinkSensorEntityDescription(
        key="test_no_icon",
        translation_key="test_no_icon",
        icon=None,
        value_fn=lambda _: None,
        icon_fn=lambda _: "mdi:custom",
    )
    sensor_no_icon = TranslinkSensor(coordinator, desc_no_icon, entry)  # type: ignore[arg-type]
    assert sensor_no_icon.icon == "mdi:train-bus"


async def test_itinerary_calling_stops_contract(
    hass,
    sample_journey_summary: JourneySummary,
) -> None:
    """Expose additive live attributes without changing state or unique identity."""
    sample_journey_summary.itinerary_legs[0].update(
        {
            "callingStops": [
                {
                    "stopId": "600019",
                    "scheduledTimeUtc": "2026-10-06T00:00:00Z",
                    "realtime": None,
                }
            ],
            "callingStopsSource": "scheduled",
            "callingStopsRealtimeUpdatedAt": None,
        }
    )
    coordinator = FakeCoordinator(data=sample_journey_summary)
    description = next(d for d in JOURNEY_SENSORS if d.key == "itinerary")
    sensor = TranslinkSensor(coordinator, description, coordinator.entry)
    assert sensor.native_value == "1 legs"
    assert sensor.unique_id == "test_entry_id_itinerary"
    assert sensor.extra_state_attributes["legs"][0]["callingStopsSource"] == "scheduled"
    import json
    from types import SimpleNamespace

    from homeassistant.components.recorder.db_schema import StateAttributes
    from homeassistant.core import Event, State

    sensor.hass = hass
    sensor.entity_id = "sensor.itinerary_recorder_test"
    sensor.platform = SimpleNamespace(platform_name="translink", config_entry=None)
    await sensor.async_internal_added_to_hass()
    state = State(
        sensor.entity_id,
        sensor.native_value,
        sensor.extra_state_attributes,
        state_info=sensor._state_info,
    )
    assert "legs" in state.attributes
    assert "legs" in state.state_info["unrecorded_attributes"]
    recorded = json.loads(
        StateAttributes.shared_attrs_bytes_from_event(
            Event("state_changed", {"new_state": state}), None
        )
    )
    assert "legs" not in recorded
    assert "polyline" in recorded
