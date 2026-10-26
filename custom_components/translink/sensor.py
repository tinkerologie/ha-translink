"""Sensor platform for Translink Queensland integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import BRISBANE_TZ, CONF_NAME, DOMAIN, MODE_JOURNEY, get_vehicle_icon
from .coordinator import TranslinkCoordinator

if TYPE_CHECKING:
    from . import TranslinkConfigEntry

PARALLEL_UPDATES = 0


def _format_brisbane_time(dt: datetime | None) -> str | None:
    """Format datetime in Brisbane local time (UTC+10)."""
    if dt is None:
        return None
    return dt.astimezone(ZoneInfo(BRISBANE_TZ)).strftime("%I:%M %p")


@dataclass(frozen=True, kw_only=True)
class TranslinkSensorEntityDescription(SensorEntityDescription):
    """Describes a Translink sensor entity."""

    value_fn: Callable[[Any], Any]
    attributes_fn: Callable[[Any], dict[str, Any]] | None = None
    icon_fn: Callable[[Any], str | None] | None = None


JOURNEY_SENSORS: tuple[TranslinkSensorEntityDescription, ...] = (
    TranslinkSensorEntityDescription(
        key="next_departure",
        translation_key="next_departure",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.departure_time,
        attributes_fn=lambda data: {
            "origin": data.origin_name,
            "platform": data.origin_platform,
            "readable_time": _format_brisbane_time(data.departure_time),
        },
    ),
    TranslinkSensorEntityDescription(
        key="arrival_time",
        translation_key="arrival_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.arrival_time,
        attributes_fn=lambda data: {
            "destination": data.destination_name,
            "platform": data.destination_platform,
            "readable_time": _format_brisbane_time(data.arrival_time),
        },
    ),
    TranslinkSensorEntityDescription(
        key="duration",
        translation_key="duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement="min",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.duration_mins,
    ),
    TranslinkSensorEntityDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=[
            "scheduled",
            "on_time",
            "delayed",
            "departed",
            "arrived",
            "no_service",
        ],
        value_fn=lambda data: data.status,
    ),
    TranslinkSensorEntityDescription(
        key="next_service",
        translation_key="next_service",
        icon="mdi:train-bus",
        value_fn=lambda data: (
            f"{data.next_service_name} ({data.next_service_vehicle})"
            if data.next_service_name and data.next_service_vehicle
            else (data.next_service_name or "None")
        ),
        icon_fn=lambda data: get_vehicle_icon(data.next_service_vehicle),
        attributes_fn=lambda data: {
            "route_name": data.next_service_name,
            "vehicle": data.next_service_vehicle,
            "headsign": data.next_service_headsign,
            "route_code": data.next_service_route_code,
            "route_color": data.next_service_color,
            "operator": data.operator,
            "trip_id": data.trip_id,
        },
    ),
    TranslinkSensorEntityDescription(
        key="platform",
        translation_key="platform",
        icon="mdi:bus-stop-uncovered",
        value_fn=lambda data: data.origin_platform or "N/A",
    ),
    TranslinkSensorEntityDescription(
        key="transfers",
        translation_key="transfers",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.transfers,
    ),
    TranslinkSensorEntityDescription(
        key="fare",
        translation_key="fare",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="AUD",
        value_fn=lambda data: data.fare_price,
        attributes_fn=lambda data: {
            "fare_type": data.fare_type,
            "fares_breakdown": data.fares_breakdown,
        },
    ),
    TranslinkSensorEntityDescription(
        key="delay",
        translation_key="delay",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement="min",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.delay_mins,
    ),
    TranslinkSensorEntityDescription(
        key="walking_distance",
        translation_key="walking_distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement="m",
        value_fn=lambda data: data.walking_distance_m,
    ),
    TranslinkSensorEntityDescription(
        key="disruptions",
        translation_key="disruptions",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.disruptions_count,
        attributes_fn=lambda data: {
            "disruptions": data.disruptions,
            "description": data.disruptions_description,
            "summary": data.disruptions_summary,
            "latest_title": data.latest_disruption_title,
            "latest_description": data.latest_disruption_description,
        },
    ),
    TranslinkSensorEntityDescription(
        key="disruption_description",
        translation_key="disruption_description",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: (
            data.latest_disruption_title
            or ("Normal" if not data.disruptions_count else "Service Disruption")
        )[:255],
        attributes_fn=lambda data: {
            "description": data.disruptions_description,
            "count": data.disruptions_count,
            "disruptions": data.disruptions,
        },
    ),
    TranslinkSensorEntityDescription(
        key="itinerary",
        translation_key="itinerary",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: f"{len(data.itinerary_legs)} legs",
        attributes_fn=lambda data: {
            "legs": data.itinerary_legs,
            "polyline": data.polyline,
        },
    ),
)


STOP_SENSORS: tuple[TranslinkSensorEntityDescription, ...] = (
    TranslinkSensorEntityDescription(
        key="next_departure",
        translation_key="next_departure",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.next_departure_time,
        attributes_fn=lambda data: {
            "platform": data.next_platform,
            "readable_time": _format_brisbane_time(data.next_departure_time),
        },
    ),
    TranslinkSensorEntityDescription(
        key="next_service",
        translation_key="next_service",
        icon="mdi:train-bus",
        value_fn=lambda data: (
            f"{data.next_route} ({data.next_vehicle})"
            if data.next_route and data.next_vehicle
            else (data.next_route or "None")
        ),
        icon_fn=lambda data: get_vehicle_icon(data.next_vehicle),
        attributes_fn=lambda data: {
            "route": data.next_route,
            "vehicle": data.next_vehicle,
            "headsign": data.next_headsign,
            "platform": data.next_platform,
        },
    ),
    TranslinkSensorEntityDescription(
        key="platform",
        translation_key="platform",
        icon="mdi:bus-stop-uncovered",
        value_fn=lambda data: data.next_platform or "N/A",
    ),
    TranslinkSensorEntityDescription(
        key="delay",
        translation_key="delay",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement="min",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.delay_mins,
    ),
    TranslinkSensorEntityDescription(
        key="disruptions",
        translation_key="disruptions",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.disruptions_count,
        attributes_fn=lambda data: {
            "disruptions": data.disruptions,
            "description": data.disruptions_description,
            "summary": data.disruptions_summary,
            "latest_title": data.latest_disruption_title,
            "latest_description": data.latest_disruption_description,
        },
    ),
    TranslinkSensorEntityDescription(
        key="disruption_description",
        translation_key="disruption_description",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: (
            data.latest_disruption_title
            or ("Normal" if not data.disruptions_count else "Service Disruption")
        )[:255],
        attributes_fn=lambda data: {
            "description": data.disruptions_description,
            "count": data.disruptions_count,
            "disruptions": data.disruptions,
        },
    ),
    TranslinkSensorEntityDescription(
        key="departures_board",
        translation_key="departures_board",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: f"{len(data.departures)} departures",
        attributes_fn=lambda data: {
            "departures": data.departures,
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TranslinkConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Translink sensors from config entry."""
    coordinator: TranslinkCoordinator = (
        getattr(entry, "runtime_data", None) or hass.data[DOMAIN][entry.entry_id]
    )

    descriptions = JOURNEY_SENSORS if coordinator.mode == MODE_JOURNEY else STOP_SENSORS

    async_add_entities(
        TranslinkSensor(
            coordinator=coordinator,
            description=description,
            entry=entry,
        )
        for description in descriptions
    )


class TranslinkSensor(
    CoordinatorEntity[TranslinkCoordinator],
    SensorEntity,
):
    """Representation of a Translink sensor."""

    entity_description: TranslinkSensorEntityDescription
    _attr_has_entity_name = True
    _unrecorded_attributes = frozenset({"legs"})

    def __init__(
        self,
        coordinator: TranslinkCoordinator,
        description: TranslinkSensorEntityDescription,
        entry: TranslinkConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self.entry = entry

        name = entry.data.get(CONF_NAME, "Translink")
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

        device_model = (
            "Public Transport Journey"
            if coordinator.mode == MODE_JOURNEY
            else "Station Departure Board"
        )

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=name,
            manufacturer="Translink Queensland",
            model=device_model,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def icon(self) -> str | None:
        """Return the icon of the sensor."""
        if self.entity_description.icon_fn:
            if self.coordinator.data:
                return self.entity_description.icon_fn(self.coordinator.data)
            return self.entity_description.icon or "mdi:train-bus"
        return super().icon

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        if not self.coordinator.data or not self.entity_description.attributes_fn:
            return {}
        return self.entity_description.attributes_fn(self.coordinator.data)
