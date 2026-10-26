"""Translink Queensland integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import TranslinkCoordinator
from .frontend import async_register_frontend

_LOGGER = logging.getLogger(__name__)

type TranslinkConfigEntry = ConfigEntry[TranslinkCoordinator]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.DEVICE_TRACKER, Platform.EVENT]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up shared dashboard assets once for all Translink entries."""
    await async_register_frontend(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TranslinkConfigEntry) -> bool:
    """Set up Translink from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = TranslinkCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    return True


async def async_update_options(
    hass: HomeAssistant, entry: TranslinkConfigEntry
) -> None:
    """Reload the integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: TranslinkConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        domain_data = hass.data.get(DOMAIN, {})
        coordinator: TranslinkCoordinator | None = domain_data.pop(
            entry.entry_id, None
        ) or getattr(entry, "runtime_data", None)
        if coordinator is not None:
            await coordinator.async_shutdown()
    return unload_ok
