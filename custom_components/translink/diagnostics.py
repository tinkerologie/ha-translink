"""Diagnostics support for Translink Queensland integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant

from .client import redact_sensitive
from .const import (
    CONF_END_LOCATION_ID,
    CONF_END_NAME,
    CONF_MODE,
    CONF_NAME,
    CONF_START_LOCATION_ID,
    CONF_START_NAME,
    DOMAIN,
    MODE_WINDOW,
    resolve_realtime_region,
)
from .coordinator import TranslinkCoordinator
from .window_coordinator import WindowCoordinator

if TYPE_CHECKING:
    from . import TranslinkConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TranslinkConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    coordinator: TranslinkCoordinator | WindowCoordinator | None = getattr(
        entry, "runtime_data", None
    ) or hass.data.get(DOMAIN, {}).get(entry.entry_id)

    entry_data = dict(entry.data)
    if entry_data.get(CONF_MODE) == MODE_WINDOW:
        for key in (
            CONF_NAME,
            CONF_START_LOCATION_ID,
            CONF_START_NAME,
            CONF_END_LOCATION_ID,
            CONF_END_NAME,
        ):
            if key in entry_data:
                entry_data[key] = "**REDACTED**"
    raw_data: dict[str, Any] | None
    if isinstance(coordinator, WindowCoordinator):
        raw_data = coordinator.data.as_diagnostics() if coordinator.data else {}
        raw_data["ledger"] = {"trip_count": coordinator.ledger_size}
    else:
        raw_data = (
            coordinator.data.model_dump(mode="json")
            if coordinator and coordinator.data
            else None
        )

    region, confirmed = resolve_realtime_region(entry.data)
    return {
        "entry": redact_sensitive(entry_data),
        "options": redact_sensitive(dict(entry.options)),
        "realtime_region": region,
        "region_confirmed": confirmed,
        "data": redact_sensitive(raw_data),
    }
