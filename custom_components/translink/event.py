"""Event platform for service disruptions and confirmed vehicle transitions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api.models import JourneyProgress, JourneySummary
from .const import (
    CONF_NAME,
    DEVICE_MODELS,
    DOMAIN,
    MODE_JOURNEY,
    MODE_NOTICES,
    MODE_STOP,
)
from .coordinator import TranslinkCoordinator

if TYPE_CHECKING:
    from . import TranslinkConfigEntry

EVENT_TYPE_DISRUPTION = "disruption"
EVENT_TYPE_CLEARED = "cleared"

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TranslinkConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the event entities supported by this config entry."""
    coordinator: TranslinkCoordinator = (
        getattr(entry, "runtime_data", None) or hass.data[DOMAIN][entry.entry_id]
    )
    entities: list[EventEntity] = [TranslinkDisruptionEvent(coordinator, entry)]
    if coordinator.mode == MODE_JOURNEY and coordinator.track_vehicle:
        entities.append(TranslinkJourneyTransitionEvent(coordinator, entry))
    async_add_entities(entities)


class TranslinkDisruptionEvent(
    CoordinatorEntity[TranslinkCoordinator],
    EventEntity,
):
    """Representation of a Translink disruption event entity."""

    _attr_has_entity_name = True
    _attr_translation_key = "disruption"

    def __init__(
        self,
        coordinator: TranslinkCoordinator,
        entry: TranslinkConfigEntry,
    ) -> None:
        """Initialize the disruption event entity."""
        super().__init__(coordinator)
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_disruption"
        self._attr_event_types = [EVENT_TYPE_DISRUPTION, EVENT_TYPE_CLEARED]
        self._last_disruption_ids: set[str] = set()

        name = entry.data.get(CONF_NAME, "Translink")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=name,
            manufacturer="Translink Queensland",
            model=DEVICE_MODELS.get(coordinator.mode, DEVICE_MODELS[MODE_STOP]),
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        """Handle entity added to Home Assistant."""
        await super().async_added_to_hass()
        self._process_disruptions()

    @callback
    def async_entity_id_changed(self, old_entity_id: str) -> None:
        """Opt in to in-place entity ID changes (Home Assistant 2026.11 and later).

        Nothing here is keyed on the entity ID. Older releases have no parent hook.
        """
        if (hook := getattr(super(), "async_entity_id_changed", None)) is not None:
            hook(old_entity_id)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._process_disruptions()
        self.async_write_ha_state()

    def _process_disruptions(self) -> None:
        """Evaluate disruption changes and trigger events accordingly."""
        if not self.coordinator.data or (
            self.coordinator.mode == MODE_NOTICES
            and not self.coordinator.last_update_success
        ):
            return

        disruptions = getattr(self.coordinator.data, "disruptions", [])
        current_ids = {str(d.get("id")) for d in disruptions if d.get("id") is not None}

        if current_ids and current_ids != self._last_disruption_ids:
            primary = disruptions[0] if disruptions else {}
            titles = [d.get("title") for d in disruptions if d.get("title")]
            descriptions = [
                d.get("description") for d in disruptions if d.get("description")
            ]
            event_data = {
                "count": len(disruptions),
                "title": primary.get("title")
                or (titles[0] if titles else "Service Disruption"),
                "description": primary.get("description")
                or (descriptions[0] if descriptions else None),
                "cause": primary.get("cause"),
                "effect": primary.get("effect"),
                "severity": primary.get("severity"),
                "route": primary.get("route"),
                "leg": primary.get("leg"),
                "summary": getattr(
                    self.coordinator.data, "disruptions_summary", "Normal"
                ),
                "disruptions": disruptions,
            }
            self._trigger_event(EVENT_TYPE_DISRUPTION, event_data)
            self._last_disruption_ids = current_ids
        elif not current_ids and self._last_disruption_ids:
            self._trigger_event(
                EVENT_TYPE_CLEARED,
                {
                    "count": 0,
                    "message": "All service disruptions cleared",
                },
            )
            self._last_disruption_ids = set()


class TranslinkJourneyTransitionEvent(
    CoordinatorEntity[TranslinkCoordinator],
    EventEntity,
):
    """A vehicle reached the planned transfer or alighting stop."""

    _attr_has_entity_name = True
    _attr_translation_key = "journey_transition"

    def __init__(
        self,
        coordinator: TranslinkCoordinator,
        entry: TranslinkConfigEntry,
    ) -> None:
        """Initialize the transition event entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_journey_transition"
        self._attr_event_types = ["transfer_stop_reached", "alighting_stop_reached"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data.get(CONF_NAME, "Translink"),
            manufacturer="Translink Queensland",
            model=DEVICE_MODELS[MODE_JOURNEY],
            entry_type=DeviceEntryType.SERVICE,
        )
        self._journey_id: str | None = None
        self._seen: set[str] = set()

    def _progress(self) -> JourneyProgress | None:
        summary = self.coordinator.data
        return summary.progress if isinstance(summary, JourneySummary) else None

    async def async_added_to_hass(self) -> None:
        """Subscribe after marking any existing transitions as historical."""
        if (progress := self._progress()) is not None:
            self._journey_id = progress.journey_id
            self._seen.update(item.dedup_key for item in progress.transitions)
        await super().async_added_to_hass()

    @callback
    def async_entity_id_changed(self, old_entity_id: str) -> None:
        """Allow the existing event entity to be renamed in place."""
        if (hook := getattr(super(), "async_entity_id_changed", None)) is not None:
            hook(old_entity_id)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Fire only fresh confirmations delivered by the coordinator."""
        if (progress := self._progress()) is None:
            return
        if progress.journey_id != self._journey_id:
            self._journey_id = progress.journey_id
            self._seen.clear()
        emitted = False
        for transition in progress.transitions:
            if transition.dedup_key in self._seen:
                continue
            self._seen.add(transition.dedup_key)
            attributes = transition.model_dump(
                mode="json", exclude={"type", "dedup_key"}
            )
            if transition.type == "alighting_stop_reached":
                attributes = {
                    key: value
                    for key, value in attributes.items()
                    if not key.startswith("next_leg_")
                }
            self._trigger_event(
                transition.type, {"journey_id": progress.journey_id, **attributes}
            )
            self.async_write_ha_state()
            emitted = True
        if not emitted:
            self.async_write_ha_state()
