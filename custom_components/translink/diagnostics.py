"""Diagnostics support for Translink Queensland integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant

from .client import redact_sensitive
from .const import DOMAIN, resolve_realtime_region
from .coordinator import TranslinkCoordinator

if TYPE_CHECKING:
    from . import TranslinkConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TranslinkConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    coordinator: TranslinkCoordinator | None = getattr(
        entry, "runtime_data", None
    ) or hass.data.get(DOMAIN, {}).get(entry.entry_id)

    raw_data = (
        coordinator.data.model_dump(mode="json")
        if coordinator and coordinator.data
        else None
    )

    region, confirmed = resolve_realtime_region(entry.data)
    return {
        "entry": redact_sensitive(dict(entry.data)),
        "options": redact_sensitive(dict(entry.options)),
        "realtime_region": region,
        "region_confirmed": confirmed,
        "data": redact_sensitive(raw_data),
    }
