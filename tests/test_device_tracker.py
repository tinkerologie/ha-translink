"""Tests for Translink device tracker platform."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from homeassistant.components.device_tracker import SourceType
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from custom_components.translink.client import JourneySummary
from custom_components.translink.const import (
    CONF_MODE,
    CONF_NAME,
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


def test_tracker_unavailable_without_coordinates() -> None:
    """Test tracker availability when coords are None."""
    coordinator = FakeCoordinator(
        mode=MODE_JOURNEY,
        data=JourneySummary(vehicle_latitude=None, vehicle_longitude=None),
    )
    entry = FakeEntry()
    tracker = TranslinkVehicleTracker(coordinator, entry)  # type: ignore[arg-type]
    assert tracker.available is False
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
        next_service_vehicle=vehicle_type,
        vehicle_latitude=-27.46,
        vehicle_longitude=153.02,
    )
    coordinator = FakeCoordinator(mode=MODE_JOURNEY, data=summary)
    entry = FakeEntry()
    tracker = TranslinkVehicleTracker(coordinator, entry)  # type: ignore[arg-type]
    assert tracker.icon == expected_icon
