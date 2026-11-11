"""Tests for Translink device tracker platform."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.components.device_tracker import SourceType
from homeassistant.components.recorder.db_schema import StateAttributes
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.util import dt as dt_util
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed_exact

from custom_components.translink.api.client import VEHICLE_POSITION_MAX_AGE_SECONDS
from custom_components.translink.client import JourneySummary
from custom_components.translink.const import (
    CONF_MODE,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    DOMAIN,
    MODE_JOURNEY,
)
from custom_components.translink.device_tracker import (
    TranslinkVehicleTracker,
    async_setup_entry,
)


class FakeEntry:
    """Fake ConfigEntry."""

    def __init__(self, mode: str = MODE_JOURNEY) -> None:
        self.entry_id = "test_entry_id"
        self.data = {
            CONF_MODE: mode,
            CONF_NAME: "My Journey",
        }
        self.runtime_data = None


class FakeCoordinator:
    """Fake coordinator."""

    def __init__(
        self,
        mode: str = MODE_JOURNEY,
        data: Any = None,
        track_vehicle: bool = True,
    ) -> None:
        self.mode = mode
        self.data = data
        self.track_vehicle = track_vehicle
        self.last_update_success = True
        self._listeners: list[Any] = []

    def async_add_listener(self, update_callback: Any) -> Any:
        self._listeners.append(update_callback)
        return lambda: self._listeners.remove(update_callback)


@pytest.fixture
def sample_journey_with_coords() -> JourneySummary:
    """Fixture with live vehicle coordinates."""
    return JourneySummary(
        status="on_time",
        vehicle_id="BUS_102",
        vehicle_label="102",
        vehicle_latitude=-27.4656,
        vehicle_longitude=153.0259,
        vehicle_bearing=90.0,
        vehicle_speed=12.5,
        vehicle_tracked=True,
        vehicle_position_status="live",
        vehicle_position_timestamp=dt_util.utcnow().isoformat(),
        active_leg_index=2,
        active_trip_id="TRIP_456",
        active_route_name="Route 102",
        active_route_code="102",
        active_route_color="#223344",
        active_vehicle_type="Bus",
        trip_id="TRIP_123",
        next_service_name="Route 66",
        next_service_vehicle="Bus",
    )


@pytest.mark.asyncio
async def test_setup_device_tracker_enabled(
    sample_journey_with_coords: JourneySummary,
) -> None:
    """Test device tracker setup when enabled."""
    hass = MagicMock()
    entry = FakeEntry()
    coordinator = FakeCoordinator(
        mode=MODE_JOURNEY,
        data=sample_journey_with_coords,
        track_vehicle=True,
    )
    entry.runtime_data = coordinator  # type: ignore[assignment]
    hass.data = {DOMAIN: {entry.entry_id: coordinator}}

    trackers: list[TranslinkVehicleTracker] = []
    await async_setup_entry(hass, entry, lambda added: trackers.extend(added))  # type: ignore[arg-type]

    assert len(trackers) == 1
    tracker = trackers[0]
    assert tracker.source_type == SourceType.GPS
    assert tracker.latitude == -27.4656
    assert tracker.longitude == 153.0259
    assert tracker.location_accuracy == 15
    assert tracker.available is True

    attrs = tracker.extra_state_attributes
    assert attrs["active_leg_index"] == 2
    assert attrs["trip_id"] == "TRIP_456"
    assert attrs["route_name"] == "Route 102"
    assert attrs["route_code"] == "102"
    assert attrs["route_color"] == "#223344"
    assert attrs["vehicle_type"] == "Bus"
    assert attrs["position_status"] == "live"
    assert (
        attrs["position_timestamp"]
        == sample_journey_with_coords.vehicle_position_timestamp
    )
    assert attrs["vehicle_id"] == "BUS_102"
    assert attrs["is_live_tracked"] is True
    assert attrs["bearing"] == 90.0
    assert attrs["speed"] == 12.5
    assert tracker.icon == "mdi:bus"
    assert tracker.location_accuracy == 15.0


@pytest.mark.asyncio
async def test_setup_device_tracker_disabled() -> None:
    """Test device tracker not added when track_vehicle is False."""
    hass = MagicMock()
    entry = FakeEntry()
    coordinator = FakeCoordinator(
        mode=MODE_JOURNEY,
        track_vehicle=False,
    )
    entry.runtime_data = coordinator  # type: ignore[assignment]
    hass.data = {DOMAIN: {entry.entry_id: coordinator}}

    trackers: list[TranslinkVehicleTracker] = []
    await async_setup_entry(hass, entry, lambda added: trackers.extend(added))  # type: ignore[arg-type]
    assert len(trackers) == 0


def test_tracker_available_without_coordinates() -> None:
    """Test tracker availability when coords are None."""
    coordinator = FakeCoordinator(
        mode=MODE_JOURNEY,
        data=JourneySummary(vehicle_latitude=None, vehicle_longitude=None),
    )
    entry = FakeEntry()
    tracker = TranslinkVehicleTracker(coordinator, entry)  # type: ignore[arg-type]
    assert tracker.available is True
    assert tracker.extra_state_attributes["position_status"] == "no_active_leg"
    assert tracker.latitude is None
    assert tracker.longitude is None
    assert tracker.device_info == DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="My Journey",
        manufacturer="Translink Queensland",
        model="Public Transport Journey",
        entry_type=DeviceEntryType.SERVICE,
    )


def test_tracker_non_journey_data() -> None:
    """Test tracker properties when data is not JourneySummary."""
    coordinator = FakeCoordinator(mode=MODE_JOURNEY, data=None)
    entry = FakeEntry()
    tracker = TranslinkVehicleTracker(coordinator, entry)  # type: ignore[arg-type]
    assert tracker.latitude is None
    assert tracker.longitude is None
    assert tracker.extra_state_attributes == {}
    assert tracker.icon == "mdi:bus-marker"
    assert tracker.available is False


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
        ("UnknownVehicle", "mdi:bus-marker"),
        (None, "mdi:bus-marker"),
    ],
)
def test_tracker_dynamic_icons(vehicle_type: str | None, expected_icon: str) -> None:
    """Test dynamic icons based on vehicle transport mode."""
    summary = JourneySummary(
        active_vehicle_type=vehicle_type,
        vehicle_latitude=-27.46,
        vehicle_longitude=153.02,
    )
    coordinator = FakeCoordinator(mode=MODE_JOURNEY, data=summary)
    entry = FakeEntry()
    tracker = TranslinkVehicleTracker(coordinator, entry)  # type: ignore[arg-type]
    assert tracker.icon == expected_icon


async def test_tracker_expires_in_hass_and_excludes_location_from_recorder(
    hass: HomeAssistant,
    sample_journey_with_coords: JourneySummary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live state expires by wall-clock time without another refresh."""
    timers: list[MagicMock] = []

    def track_expiry(*args: Any) -> MagicMock:
        cancel = MagicMock(wraps=async_track_point_in_time(*args))
        timers.append(cancel)
        return cancel

    monkeypatch.setattr(
        "custom_components.translink.device_tracker.async_track_point_in_time",
        track_expiry,
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_MODE: MODE_JOURNEY},
        options={CONF_SCAN_INTERVAL: 300},
    )
    entry.add_to_hass(hass)
    now = dt_util.utcnow()
    sample_journey_with_coords.vehicle_position_timestamp = now.isoformat()

    with patch(
        "custom_components.translink.coordinator.TranslinkCoordinator._async_update_data",
        return_value=sample_journey_with_coords,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    entity_id = er.async_get(hass).async_get_entity_id(
        "device_tracker", DOMAIN, f"{entry.entry_id}_vehicle_tracker"
    )
    assert entity_id is not None
    live = hass.states.get(entity_id)
    assert live is not None
    assert live.attributes["latitude"] == -27.4656
    assert live.attributes["longitude"] == 153.0259
    assert live.attributes["position_status"] == "live"
    private_fields = {
        "latitude",
        "longitude",
        "gps_accuracy",
        "bearing",
        "speed",
        "vehicle_id",
        "vehicle_label",
        "position_timestamp",
        "in_zones",
    }
    assert private_fields <= live.attributes.keys()
    assert private_fields <= live.state_info["unrecorded_attributes"]
    recorded = json.loads(
        StateAttributes.shared_attrs_bytes_from_event(
            Event("state_changed", {"new_state": live}), None
        )
    )
    assert private_fields.isdisjoint(recorded)
    assert recorded["position_status"] == "live"

    # A refresh replaces the initial deadline with the newer position's expiry.
    updated_at = now + timedelta(seconds=1)
    updated = sample_journey_with_coords.model_copy(
        update={"vehicle_position_timestamp": updated_at.isoformat()}
    )
    coordinator = entry.runtime_data
    coordinator.async_set_updated_data(updated)
    assert len(timers) == 2
    timers[0].assert_called_once_with()

    original_deadline = now + timedelta(
        seconds=VEHICLE_POSITION_MAX_AGE_SECONDS, milliseconds=1
    )
    with patch(
        "custom_components.translink.device_tracker.dt_util.utcnow",
        return_value=original_deadline,
    ):
        async_fire_time_changed_exact(hass, original_deadline)
        await hass.async_block_till_done()
    assert hass.states.get(entity_id).attributes["position_status"] == "live"

    expires = original_deadline + timedelta(seconds=1)
    with patch(
        "custom_components.translink.device_tracker.dt_util.utcnow",
        return_value=expires,
    ):
        async_fire_time_changed_exact(hass, expires)
        await hass.async_block_till_done()
        stale = hass.states.get(entity_id)
        assert stale.state == STATE_UNKNOWN
        assert stale.attributes["position_status"] == "stale"
        assert stale.attributes["is_live_tracked"] is False
        assert {"latitude", "longitude"}.isdisjoint(stale.attributes)

        # A failed refresh cannot expose even a recent cached fix.
        coordinator.async_set_updated_data(
            updated.model_copy(
                update={"vehicle_position_timestamp": expires.isoformat()}
            )
        )
        assert hass.states.get(entity_id).attributes["position_status"] == "live"
        coordinator.async_set_update_error(RuntimeError("feed failed"))
        assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
        assert "latitude" not in hass.states.get(entity_id).attributes
        timers[-1].assert_called_once_with()
        coordinator.async_set_updated_data(
            updated.model_copy(
                update={"vehicle_position_timestamp": expires.isoformat()}
            )
        )
        timers[-1].assert_not_called()

        assert await hass.config_entries.async_unload(entry.entry_id)
        timers[-1].assert_called_once_with()
