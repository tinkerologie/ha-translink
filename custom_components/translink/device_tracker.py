"""Device tracker platform for Translink live vehicle tracking."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.components.device_tracker.const import SourceType
from homeassistant.components.device_tracker.entity import TrackerEntity
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api.client import VEHICLE_POSITION_MAX_AGE_SECONDS, vehicle_position_is_fresh
from .client import JourneySummary, parse_iso_datetime
from .const import CONF_NAME, DOMAIN, MODE_JOURNEY, get_vehicle_icon
from .coordinator import TranslinkCoordinator

if TYPE_CHECKING:
    from . import TranslinkConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TranslinkConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Translink live vehicle device tracker from config entry."""
    coordinator: TranslinkCoordinator = (
        getattr(entry, "runtime_data", None) or hass.data[DOMAIN][entry.entry_id]
    )

    if coordinator.mode == MODE_JOURNEY and coordinator.track_vehicle:
        async_add_entities([TranslinkVehicleTracker(coordinator, entry)])


class TranslinkVehicleTracker(
    CoordinatorEntity[TranslinkCoordinator],
    TrackerEntity,
):
    """Realtime vehicle tracker for Translink public transit."""

    _attr_has_entity_name = True
    _attr_translation_key = "vehicle_tracker"
    _attr_source_type = SourceType.GPS
    _attr_location_accuracy = 15.0
    _unrecorded_attributes = frozenset(
        {
            "latitude",
            "longitude",
            "gps_accuracy",
            "in_zones",
            "bearing",
            "speed",
            "vehicle_id",
            "vehicle_label",
            "position_timestamp",
        }
    )
    _cancel_expiry: CALLBACK_TYPE | None = None

    def __init__(
        self,
        coordinator: TranslinkCoordinator,
        entry: TranslinkConfigEntry,
    ) -> None:
        """Initialize the tracker."""
        super().__init__(coordinator)
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_vehicle_tracker"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information."""
        name = self.entry.data.get(CONF_NAME, "Translink")
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=name,
            manufacturer="Translink Queensland",
            model="Public Transport Journey",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _journey(self) -> JourneySummary | None:
        data = self.coordinator.data
        return data if isinstance(data, JourneySummary) else None

    @property
    def icon(self) -> str:
        """Return dynamic icon based on vehicle transport type."""
        data = self._journey
        return get_vehicle_icon(
            data.active_vehicle_type if data is not None else None,
            default="mdi:bus-marker",
        )

    def _live_position_time(self, data: JourneySummary) -> datetime | None:
        if (
            not self.coordinator.last_update_success
            or data.vehicle_position_status != "live"
        ):
            return None
        timestamp = parse_iso_datetime(data.vehicle_position_timestamp)
        if timestamp is not None and vehicle_position_is_fresh(
            timestamp.timestamp(), dt_util.utcnow()
        ):
            return timestamp
        return None

    @property
    def latitude(self) -> float | None:
        """Return latitude only while the position is live."""
        data = self._journey
        if data is not None and self._live_position_time(data) is not None:
            return data.vehicle_latitude
        return None

    @property
    def longitude(self) -> float | None:
        """Return longitude only while the position is live."""
        data = self._journey
        if data is not None and self._live_position_time(data) is not None:
            return data.vehicle_longitude
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return active-leg identity and position provenance."""
        data = self._journey
        if data is None:
            return {}

        live = self._live_position_time(data) is not None
        position_status = data.vehicle_position_status
        if position_status == "live" and not live:
            position_status = "stale"
        return {
            "active_leg_index": data.active_leg_index,
            "trip_id": data.active_trip_id,
            "route_name": data.active_route_name,
            "route_code": data.active_route_code,
            "route_color": data.active_route_color,
            "vehicle_type": data.active_vehicle_type,
            "position_status": position_status,
            "position_timestamp": data.vehicle_position_timestamp if live else None,
            "vehicle_id": data.vehicle_id if live else None,
            "vehicle_label": data.vehicle_label if live else None,
            "bearing": data.vehicle_bearing if live else None,
            "speed": data.vehicle_speed if live else None,
            "is_live_tracked": live,
        }

    @property
    def available(self) -> bool:
        """Return whether a journey summary is available."""
        return super().available and self._journey is not None

    async def async_added_to_hass(self) -> None:
        """Schedule expiry for the first position and clean up on removal."""
        await super().async_added_to_hass()
        self.async_on_remove(self._async_cancel_expiry)
        self._async_schedule_expiry()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._async_schedule_expiry()
        super()._handle_coordinator_update()

    @callback
    def _async_schedule_expiry(self) -> None:
        self._async_cancel_expiry()
        data = self._journey
        timestamp = self._live_position_time(data) if data is not None else None
        if timestamp is not None:
            # A fix at the maximum age is still live. Expire just past that boundary.
            deadline = timestamp + timedelta(
                seconds=VEHICLE_POSITION_MAX_AGE_SECONDS, microseconds=1
            )
            self._cancel_expiry = async_track_point_in_time(
                self.hass, self._async_position_expired, deadline
            )

    @callback
    def _async_cancel_expiry(self) -> None:
        if self._cancel_expiry is not None:
            self._cancel_expiry()
            self._cancel_expiry = None

    @callback
    def _async_position_expired(self, _now: datetime) -> None:
        self._cancel_expiry = None
        self.async_write_ha_state()
